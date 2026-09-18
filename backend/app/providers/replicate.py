"""
Replicate adapter — image generation, video generation, and TTS.

Same architecture as `app/providers/openrouter.py`: plain httpx,
RuntimeError on any failure, compatible with `call_with_fallback`'s
retry/fallback classification.

Replicate's API is prediction-based (create a prediction, then it
runs async) rather than a single request/response round-trip like
OpenRouter/fal.ai. This adapter uses the `Prefer: wait=<seconds>`
header (Replicate's documented synchronous-wait mode) to keep the
call shape identical to every other adapter here — one HTTP call in,
one `(result, cost_usd)` tuple out — instead of building a separate
polling loop. If a prediction genuinely doesn't finish inside the
wait window, that's treated as a real failure (RuntimeError), which
triggers the same fallback-to-next-provider behavior as a timeout
would; a caller who reliably needs longer-running Replicate jobs than
`api_timeout_seconds` allows is expected to raise that setting, not
something this adapter silently works around.

Three entry points, matching the three capabilities Replicate is
registered for in `app/providers/capabilities.py`:

    await replicate.generate_image(prompt=prompt, api_key=api_key, model=model)
    await replicate.generate_video(prompt=prompt, api_key=api_key, model=model, image_url=None)
    await replicate.generate_speech(text=text, api_key=api_key, model=model)
    -> (result: dict, cost_usd: float) in all three cases

`model` is expected to be a Replicate model version id (e.g.
"owner/model:version_hash"), matching what `supported_models` entries
in capabilities.py would hold once populated for this provider.
"""
import asyncio
import time
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://api.replicate.com/v1/predictions"
_WAIT_SECONDS = 15
# Rough flat-fee estimates — used only as a cost-ceiling estimate for
# ProviderRouter's cost check, not meant to be exact-to-the-cent.
_EST_COST_PER_IMAGE_USD = 0.03
_EST_COST_PER_VIDEO_USD = 0.5
_EST_COST_PER_AUDIO_USD = 0.01


async def _create_prediction(
    version: str, model_input: dict, api_key: str, capability: str
) -> dict:
    """Shared HTTP + error-handling core for all capabilities
    below — only the input payload and cost estimate differ per
    capability, so that's kept in the wrappers instead of
    duplicating the request/error-handling logic."""
    settings = get_settings()
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Prefer": f"wait={_WAIT_SECONDS}",
    }
    # Replicate API requires just the version hash if owner/model:hash was passed
    version_id = version.split(":")[-1] if ":" in version else version
    body = {"version": version_id, "input": model_input}

    log = logger.bind(provider="replicate", model=version, capability=capability)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=max(30.0, float(settings.api_timeout_seconds))) as client:
            response = await client.post(_API_URL, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"Replicate timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"Replicate network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("Replicate rejected the API key (401)")
    if response.status_code == 402:
        log.warning("provider_credit_exhausted")
        raise RuntimeError("Replicate credits exhausted (402 Payment Required)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        await asyncio.sleep(10.0)
        try:
            async with httpx.AsyncClient(timeout=max(30.0, float(settings.api_timeout_seconds))) as retry_client:
                response = await retry_client.post(_API_URL, json=body, headers=headers)
        except Exception:
            pass
        if response.status_code == 429:
            raise RuntimeError("Replicate rate limit exceeded (429)")
    if response.status_code >= 400:
        err_body = response.text[:500]
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=err_body,
        )
        if any(w in err_body.lower() for w in ("credit", "payment required", "billing", "unpaid", "insufficient")):
            raise RuntimeError(f"Replicate credits exhausted ({response.status_code}): {err_body}")
        raise RuntimeError(f"Replicate returned {response.status_code}: {err_body}")

    try:
        data = response.json()
    except ValueError as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"Replicate response missing expected fields: {exc}") from exc

    status = data.get("status")
    get_url = data.get("urls", {}).get("get")
    if status in ("starting", "processing") and get_url:
        is_kling_model = "kling" in version.lower()
        if is_kling_model:
            poll_timeout = float(getattr(settings, "kling_timeout_seconds", 360))
        elif capability == "video_generation":
            poll_timeout = float(getattr(settings, "replicate_timeout_seconds", 300))
        else:
            poll_timeout = max(180.0, float(settings.api_timeout_seconds))

        deadline = time.monotonic() + poll_timeout
        while status in ("starting", "processing") and time.monotonic() < deadline:
            await asyncio.sleep(3.0)
            try:
                async with httpx.AsyncClient(timeout=30.0) as poll_client:
                    poll_resp = await poll_client.get(get_url, headers={"Authorization": f"Token {api_key}"})
                    if poll_resp.status_code == 200:
                        data = poll_resp.json()
                        status = data.get("status")
                    elif poll_resp.status_code >= 400:
                        break
            except Exception:
                pass

    if status in ("failed", "canceled"):
        err = str(data.get("error") or "")
        log.warning("provider_prediction_failed", status=status, error=err)
        if any(w in err.lower() for w in ("credit", "payment required", "billing", "unpaid", "insufficient")):
            raise RuntimeError(f"Replicate credits exhausted: {err}")
        raise RuntimeError(f"Replicate prediction {status}: {err}")
    if status != "succeeded":
        log.warning("provider_prediction_incomplete", status=status)
        raise RuntimeError(
            f"Replicate prediction did not complete (status={status})"
        )

    log.info("provider_request_succeeded", status=status)
    return data


def _first_output_url(data: dict) -> str:
    output = data.get("output")
    if isinstance(output, list) and output:
        return output[0]
    if isinstance(output, str) and output:
        return output
    raise RuntimeError("Replicate response missing expected fields: no usable 'output'")


async def generate_image(
    prompt: str,
    api_key: str,
    model: str,
    aspect_ratio: str | None = None,
    num_outputs: int = 1,
) -> tuple[dict, float]:
    model_input = {"prompt": prompt}
    if aspect_ratio:
        model_input["aspect_ratio"] = aspect_ratio
    if num_outputs > 1:
        model_input["num_outputs"] = int(num_outputs)
    data = await _create_prediction(model, model_input, api_key, "image_generation")
    storage_path = _first_output_url(data)
    outputs = data.get("output")
    candidate_urls = outputs if isinstance(outputs, list) and outputs else [storage_path]
    est_cost = _EST_COST_PER_IMAGE_USD * max(1, len(candidate_urls))
    return {"storage_path": storage_path, "candidate_urls": candidate_urls, "raw": data}, est_cost


_KLING_DEFAULT_VERSION = (
    "kwaivgi/kling-v1.6-standard:e6f571e8d6990da3c96abf8d3082894024d652822f0ca3cd244acece84a1cc3e"
)
_LTX_DEFAULT_VERSION = (
    "lightricks/ltx-video:8c47da666861d081eeb4d1261853087de23923a268a69b63febdf5dc1dee08e4"
)


async def generate_video(
    prompt: str,
    api_key: str,
    model: str,
    image_url: str | None = None,
    aspect_ratio: str | None = None,
) -> tuple[dict, float]:
    effective_model = model
    if model in ("kling", "kling-standard", "kwaivgi/kling-v1.6-standard"):
        effective_model = _KLING_DEFAULT_VERSION
    elif model in ("ltx", "ltx-video", "lightricks/ltx-video"):
        effective_model = _LTX_DEFAULT_VERSION

    is_kling = "kling" in effective_model.lower()
    model_input = {"prompt": prompt}
    if image_url:
        if is_kling:
            model_input["start_image"] = image_url
        else:
            model_input["image"] = image_url
    if aspect_ratio and is_kling:
        model_input["aspect_ratio"] = aspect_ratio
    data = await _create_prediction(effective_model, model_input, api_key, "video_generation")
    storage_path = _first_output_url(data)
    est_cost = 0.25 if is_kling else _EST_COST_PER_VIDEO_USD
    return {"storage_path": storage_path, "raw": data}, est_cost


async def generate_speech(
    text: str,
    api_key: str,
    model: str,
    voice_id: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
) -> tuple[dict, float]:
    model_input: dict[str, Any] = {"text": text}
    chosen_voice = voice_id or voice
    if chosen_voice:
        model_input["voice"] = chosen_voice
    if speed is not None:
        model_input["speed"] = speed
    data = await _create_prediction(model, model_input, api_key, "tts")
    storage_path = _first_output_url(data)
    return {"storage_path": storage_path, "raw": data}, _EST_COST_PER_AUDIO_USD


async def generate_music(
    prompt: str,
    api_key: str,
    model: str,
    duration_seconds: int | float | None = None,
) -> tuple[dict, float]:
    """Generate instrumental background music using Replicate models (e.g. Meta MusicGen).

    Raises RuntimeError on failure (401, 429, timeout, prediction failed).
    """
    model_input: dict = {
        "prompt": prompt,
        "model_version": "stereo-melody-large",
        "output_format": "mp3",
        "normalization_strategy": "loudness",
    }
    if duration_seconds is not None:
        model_input["duration"] = min(30, max(5, int(duration_seconds)))

    data = await _create_prediction(model, model_input, api_key, "music_generation")
    storage_path = _first_output_url(data)
    return {
        "storage_path": storage_path,
        "raw": data,
        "duration_seconds": model_input.get("duration", duration_seconds),
    }, _EST_COST_PER_AUDIO_USD
