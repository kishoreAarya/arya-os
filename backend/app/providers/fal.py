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
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL_TEMPLATE = "https://fal.run/{model}"
# Rough flat-fee estimates — used only as a cost-ceiling estimate for
# ProviderRouter's cost check, not meant to be exact-to-the-cent.
_EST_COST_PER_IMAGE_USD = 0.02
_EST_COST_PER_VIDEO_USD = 0.35


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}


async def generate_image(prompt: str, api_key: str, model: str) -> tuple[dict, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — same taxonomy as the LLM adapters."""
    settings = get_settings()
    url = _API_URL_TEMPLATE.format(model=model)
    payload = {"prompt": prompt}

    log = logger.bind(provider="fal", model=model, capability="image_generation")
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=_headers(api_key))
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"fal.ai timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"fal.ai network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("fal.ai rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("fal.ai rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"fal.ai returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        storage_path = data["images"][0]["url"]
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"fal.ai response missing expected fields: {exc}") from exc

    log.info("provider_request_succeeded", cost_usd=_EST_COST_PER_IMAGE_USD)
    return {"storage_path": storage_path, "raw": data}, _EST_COST_PER_IMAGE_USD


async def generate_video(
    prompt: str, api_key: str, model: str, image_url: str | None = None
) -> tuple[dict, float]:
    """Raises RuntimeError on any failure — same taxonomy as
    generate_image above. `image_url` is optional: some fal.ai video
    models are text-to-video only, others (image-to-video) require it;
    passing None omits it from the payload rather than sending a null."""
    settings = get_settings()
    url = _API_URL_TEMPLATE.format(model=model)
    payload = {"prompt": prompt}
    if image_url:
        payload["image_url"] = image_url

    log = logger.bind(provider="fal", model=model, capability="video_generation")
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=_headers(api_key))
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"fal.ai timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"fal.ai network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("fal.ai rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("fal.ai rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"fal.ai returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        video = data["video"]
        storage_path = video["url"]
    except (KeyError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"fal.ai response missing expected fields: {exc}") from exc

    duration_seconds = video.get("duration")
    log.info("provider_request_succeeded", cost_usd=_EST_COST_PER_VIDEO_USD)
    return (
        {"storage_path": storage_path, "duration_seconds": duration_seconds, "raw": data},
        _EST_COST_PER_VIDEO_USD,
    )
