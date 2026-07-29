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
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://api.replicate.com/v1/predictions"
_WAIT_SECONDS = 30
# Rough flat-fee estimates — used only as a cost-ceiling estimate for
# ProviderRouter's cost check, not meant to be exact-to-the-cent.
_EST_COST_PER_IMAGE_USD = 0.03
_EST_COST_PER_VIDEO_USD = 0.5
_EST_COST_PER_AUDIO_USD = 0.01


async def _create_prediction(
    version: str, model_input: dict, api_key: str, capability: str
) -> dict:
    """Shared HTTP + error-handling core for all three capabilities
    below — only the input payload and cost estimate differ per
    capability, so that's kept in the three thin wrappers instead of
    duplicating the request/error-handling logic three times."""
    settings = get_settings()
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Prefer": f"wait={_WAIT_SECONDS}",
    }
    body = {"version": version, "input": model_input}

    log = logger.bind(provider="replicate", model=version, capability=capability)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
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
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("Replicate rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"Replicate returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
    except ValueError as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"Replicate response missing expected fields: {exc}") from exc

    status = data.get("status")
    if status in ("failed", "canceled"):
        log.warning("provider_prediction_failed", status=status)
        raise RuntimeError(f"Replicate prediction {status}: {data.get('error')}")
    if status != "succeeded":
        log.warning("provider_prediction_incomplete", status=status)
        raise RuntimeError(
            f"Replicate prediction did not complete within {_WAIT_SECONDS}s "
            f"(status={status})"
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


async def generate_image(prompt: str, api_key: str, model: str) -> tuple[dict, float]:
    data = await _create_prediction(model, {"prompt": prompt}, api_key, "image_generation")
    storage_path = _first_output_url(data)
    return {"storage_path": storage_path, "raw": data}, _EST_COST_PER_IMAGE_USD


async def generate_video(
    prompt: str, api_key: str, model: str, image_url: str | None = None
) -> tuple[dict, float]:
    model_input = {"prompt": prompt}
    if image_url:
        model_input["image"] = image_url
    data = await _create_prediction(model, model_input, api_key, "video_generation")
    storage_path = _first_output_url(data)
    return {"storage_path": storage_path, "raw": data}, _EST_COST_PER_VIDEO_USD


async def generate_speech(text: str, api_key: str, model: str) -> tuple[dict, float]:
    data = await _create_prediction(model, {"text": text}, api_key, "tts")
    storage_path = _first_output_url(data)
    return {"storage_path": storage_path, "raw": data}, _EST_COST_PER_AUDIO_USD
