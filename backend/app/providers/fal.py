"""
fal.ai adapter — image and video generation.

Same architecture as `app/providers/openrouter.py` and the other
LLM adapters: plain httpx, a fixed request/response shape per
capability, and RuntimeError on any failure so the shape is
compatible with `call_with_fallback`/ExecutionEngine's
`_is_transient_failure` (anything other than CostLimitExceededError
is transient/retryable).

Two entry points, one per capability this provider is registered for
in `app/providers/capabilities.py` (Capability.IMAGE_GENERATION,
Capability.VIDEO_GENERATION):

    await fal.generate_image(prompt=prompt, api_key=api_key, model=model)
    -> (result: dict, cost_usd: float)

    await fal.generate_video(prompt=prompt, api_key=api_key, model=model, image_url=None)
    -> (result: dict, cost_usd: float)

`result` always carries a `storage_path` key (a fal.ai-hosted URL —
downloading/re-hosting it into Arya OS's own storage backend is a
caller concern, same as every other agent already treats provider
output as "the URL/bytes to store", not something this adapter does
itself) plus the raw provider response under `raw`, in case a caller
needs a field this adapter doesn't surface yet.
"""
import asyncio
import time

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_QUEUE_API_BASE = "https://queue.fal.run"
_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLL_SECONDS_IMAGE = 120
_MAX_POLL_SECONDS_VIDEO = 300

# Flat-fee estimates for fal.ai models:
# FLUX Pro: $0.050/image; Dev: $0.025/image; Schnell: $0.003/image
_EST_COST_PER_IMAGE_USD = 0.025
_EST_COST_PER_PRO_IMAGE_USD = 0.050
_EST_COST_PER_VIDEO_USD = 0.100


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}


def _normalize_model_id(model: str) -> str:
    """Map common short names to full fal-ai model paths.

    Fal.ai model IDs are structured as ``fal-ai/<namespace>/<name>``.
    If the caller already passes a full path starting with ``fal-ai/``
    we use it verbatim.  Otherwise we look up known aliases and fall
    back to prepending ``fal-ai/`` for unknown short names.
    """
    if model.startswith("fal-ai/"):
        return model

    aliases = {
        "flux-1.1-pro": "fal-ai/flux-pro/v1.1",
        "flux-pro-1.1": "fal-ai/flux-pro/v1.1",
        "flux-pro/v1.1": "fal-ai/flux-pro/v1.1",
        "flux-kontext": "fal-ai/flux-pro/kontext",
        "flux-kontext-pro": "fal-ai/flux-pro/kontext",
        "flux-kontext-max": "fal-ai/flux-pro/kontext/max",
        "flux-dev": "fal-ai/flux/dev",
        "flux-schnell": "fal-ai/flux/schnell",
        "flux-pro": "fal-ai/flux-pro",
        "flux-lora": "fal-ai/flux-lora",
        "nano-banana-2": "fal-ai/nano-banana-2",
        "nano-banana-2-pro": "fal-ai/nano-banana-2-pro",
        "recraft-v3": "fal-ai/recraft/v3",
        "stable-diffusion-v35-large": "fal-ai/stable-diffusion-v35-large",
        "kling": "fal-ai/kling-video/v1.6/standard/image-to-video",
        "kling-standard": "fal-ai/kling-video/v1.6/standard/image-to-video",
        "kling-1.6": "fal-ai/kling-video/v1.6/standard/image-to-video",
        "kling-2.1": "fal-ai/kling-video/v2.1/standard/image-to-video",
        "kling-v3-pro": "fal-ai/kling/v3.0/pro",
        "kling-v3-standard": "fal-ai/kling/v3.0/standard",
        "wan": "fal-ai/wan-i2v",
        "wan-i2v": "fal-ai/wan-i2v",
        "wan-2.1": "fal-ai/wan-i2v",
        "wan-video": "fal-ai/wan/v2.1",
        "veo-3": "fal-ai/veo/v3.1",
        "ltx-video": "fal-ai/ltx-video",
    }
    if model in aliases:
        return aliases[model]
    return f"fal-ai/{model}"


normalize_fal_model = _normalize_model_id


async def _submit_and_poll(
    model_id: str,
    payload: dict,
    api_key: str,
    max_poll_seconds: float,
    log,
) -> dict:
    """Submit a request to the fal.ai queue, poll until COMPLETED, and
    return the result payload.  Raises RuntimeError on any failure.
    """
    settings = get_settings()
    headers = _headers(api_key)
    submit_url = f"{_QUEUE_API_BASE}/{model_id}"

    # 1. Submit to queue
    log.info("provider_queue_submit_started")
    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(submit_url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"fal.ai submit timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"fal.ai submit network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("fal.ai rejected the API key (401)")
    if response.status_code == 402:
        log.warning("provider_credit_exhausted")
        raise RuntimeError("fal.ai credits exhausted (402 Payment Required)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("fal.ai rate limit exceeded (429)")
    if response.status_code == 404:
        log.warning("provider_model_not_found", model=model_id)
        raise RuntimeError(f"fal.ai model unavailable (404 Not Found): {model_id}")
    if response.status_code >= 400:
        err_body = response.text[:500]
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=err_body,
        )
        if any(w in err_body.lower() for w in ("credit", "payment required", "billing", "unpaid", "insufficient")):
            raise RuntimeError(f"fal.ai credits exhausted ({response.status_code}): {err_body}")
        raise RuntimeError(
            f"fal.ai submit returned {response.status_code}: {err_body}"
        )

    try:
        submit_data = response.json()
        request_id = submit_data["request_id"]
        status_url = submit_data["status_url"]
        response_url = submit_data["response_url"]
    except (KeyError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(
            f"fal.ai submit response missing expected fields: {exc}"
        ) from exc

    log.info("provider_queue_submitted", request_id=request_id)

    # 2. Poll status_url until COMPLETED
    deadline = time.monotonic() + max_poll_seconds

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        while time.monotonic() < deadline:
            try:
                status_resp = await client.get(status_url, headers=headers)
            except httpx.TimeoutException as exc:
                log.warning("provider_status_timeout", error=str(exc))
                raise RuntimeError(
                    f"fal.ai status poll timed out: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                log.warning("provider_status_network_error", error=str(exc))
                raise RuntimeError(
                    f"fal.ai status poll network error: {exc}"
                ) from exc

            if status_resp.status_code >= 400:
                log.warning(
                    "provider_status_error",
                    status_code=status_resp.status_code,
                    body=status_resp.text[:500],
                )
                raise RuntimeError(
                    f"fal.ai status check returned {status_resp.status_code}: {status_resp.text[:500]}"
                )

            try:
                status_data = status_resp.json()
            except ValueError as exc:
                log.warning("provider_status_malformed", error=str(exc))
                raise RuntimeError(
                    f"fal.ai status response malformed: {exc}"
                ) from exc

            status = status_data.get("status")

            if status == "COMPLETED":
                log.info(
                    "provider_queue_completed",
                    request_id=request_id,
                    metrics=status_data.get("metrics"),
                )
                break
            elif status == "IN_QUEUE":
                log.debug(
                    "provider_queue_in_queue",
                    request_id=request_id,
                    position=status_data.get("queue_position"),
                )
            elif status == "IN_PROGRESS":
                log.debug(
                    "provider_queue_in_progress",
                    request_id=request_id,
                )
            elif status_data.get("error"):
                log.warning(
                    "provider_queue_failed",
                    request_id=request_id,
                    error=status_data.get("error"),
                    error_type=status_data.get("error_type"),
                )
                raise RuntimeError(
                    f"fal.ai request failed: {status_data.get('error')}"
                )
            else:
                log.warning(
                    "provider_queue_unknown_status",
                    request_id=request_id,
                    status=status,
                )
                raise RuntimeError(
                    f"fal.ai returned unknown queue status: {status}"
                )

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        else:
            log.warning(
                "provider_queue_poll_timeout",
                request_id=request_id,
                max_seconds=max_poll_seconds,
            )
            raise RuntimeError(
                f"fal.ai queue polling timed out after {max_poll_seconds}s"
            )

    # 3. Fetch result from response_url
    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            result_resp = await client.get(response_url, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_result_timeout", error=str(exc))
        raise RuntimeError(f"fal.ai result fetch timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_result_network_error", error=str(exc))
        raise RuntimeError(f"fal.ai result fetch network error: {exc}") from exc

    if result_resp.status_code >= 400:
        log.warning(
            "provider_result_error",
            status_code=result_resp.status_code,
            body=result_resp.text[:500],
        )
        raise RuntimeError(
            f"fal.ai result fetch returned {result_resp.status_code}: {result_resp.text[:500]}"
        )

    try:
        result_data = result_resp.json()
    except ValueError as exc:
        log.warning("provider_result_malformed", error=str(exc))
        raise RuntimeError(
            f"fal.ai result response malformed: {exc}"
        ) from exc

    return result_data


async def generate_image(
    prompt: str,
    api_key: str,
    model: str,
    aspect_ratio: str | None = None,
    num_outputs: int = 1,
) -> tuple[dict, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — same taxonomy as the LLM adapters."""
    model_id = _normalize_model_id(model)
    payload = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
        if aspect_ratio == "9:16":
            payload["image_size"] = "portrait_16_9"
        elif aspect_ratio == "16:9":
            payload["image_size"] = "landscape_16_9"
    if num_outputs > 1:
        payload["num_images"] = int(num_outputs)

    log = logger.bind(provider="fal", model=model_id, capability="image_generation")
    log.info("provider_request_started")

    start_time = time.perf_counter()
    data = await _submit_and_poll(
        model_id=model_id,
        payload=payload,
        api_key=api_key,
        max_poll_seconds=_MAX_POLL_SECONDS_IMAGE,
        log=log,
    )
    duration = round(time.perf_counter() - start_time, 3)

    try:
        images = data.get("images", [])
        candidate_urls = [img["url"] for img in images if "url" in img]
        if not candidate_urls and "image" in data and "url" in data["image"]:
            candidate_urls = [data["image"]["url"]]
        storage_path = candidate_urls[0] if candidate_urls else None
        if not storage_path:
            raise ValueError("No valid image URLs in fal response")
    except Exception as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"fal.ai response missing expected fields: {exc}") from exc

    unit_cost = _EST_COST_PER_PRO_IMAGE_USD if "pro" in model_id.lower() else _EST_COST_PER_IMAGE_USD
    total_cost = round(unit_cost * max(1, len(candidate_urls)), 4)
    log.info("provider_request_succeeded", cost_usd=total_cost, duration=duration)
    return {
        "storage_path": storage_path,
        "image_url": storage_path,
        "candidate_urls": candidate_urls,
        "candidates": candidate_urls,
        "provider": "fal",
        "model": model_id,
        "raw": data,
        "telemetry": {
            "provider": "fal",
            "model": model_id,
            "duration_seconds": duration,
            "num_candidates": len(candidate_urls),
            "cost_usd": total_cost,
        },
    }, total_cost


async def generate_video(
    prompt: str,
    api_key: str,
    model: str,
    image_url: str | None = None,
    aspect_ratio: str | None = None,
) -> tuple[dict, float]:
    """Raises RuntimeError on any failure — same taxonomy as
    generate_image above. `image_url` is optional: some fal.ai video
    models are text-to-video only, others (image-to-video) require it;
    passing None omits it from the payload rather than sending a null."""
    model_id = _normalize_model_id(model)
    payload = {"prompt": prompt}
    if image_url:
        payload["image_url"] = image_url
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio

    log = logger.bind(provider="fal", model=model_id, capability="video_generation")
    log.info("provider_request_started")

    start_time = time.perf_counter()
    data = await _submit_and_poll(
        model_id=model_id,
        payload=payload,
        api_key=api_key,
        max_poll_seconds=_MAX_POLL_SECONDS_VIDEO,
        log=log,
    )
    duration = round(time.perf_counter() - start_time, 3)

    try:
        video = data.get("video", {})
        storage_path = video.get("url")
        if not storage_path and "url" in data:
            storage_path = data["url"]
        if not storage_path:
            raise ValueError("No video URL returned")
    except Exception as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"fal.ai response missing expected fields: {exc}") from exc

    duration_seconds = video.get("duration")
    est_cost = 0.25 if "wan" in model_id.lower() else _EST_COST_PER_VIDEO_USD
    log.info("provider_request_succeeded", cost_usd=est_cost, duration=duration)
    return {
        "storage_path": storage_path,
        "duration_seconds": duration_seconds,
        "raw": data,
        "telemetry": {
            "provider": "fal",
            "model": model_id,
            "duration_seconds": duration,
            "cost_usd": est_cost,
        },
    }, est_cost