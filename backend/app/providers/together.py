"""Together AI adapter — image generation and video generation.

Official REST API integration for Together AI:
- Text-to-Image via https://api.together.ai/v1/images/generations
- Target image model: black-forest-labs/FLUX.1.1-pro
- Target video candidate inspection: Wan 2.1 / dedicated containers
- Strict error classification (401, 402, 429, timeout, network, model unavailable)
- Cost, latency, and generation telemetry
- Safe asset download integration
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.asset_downloader import download_media_asset

logger = get_logger("arya.providers.together")

_IMAGES_API_URL = "https://api.together.ai/v1/images/generations"
_VIDEOS_API_URL = "https://api.together.ai/v1/videos/generations"

# Official model aliases for Together AI
_MODEL_ALIASES = {
    "flux-1.1-pro": "black-forest-labs/FLUX.1.1-pro",
    "flux-pro-1.1": "black-forest-labs/FLUX.1.1-pro",
    "flux-pro": "black-forest-labs/FLUX.1.1-pro",
    "flux-1-dev": "black-forest-labs/FLUX.1-dev",
    "flux-dev": "black-forest-labs/FLUX.1-dev",
    "flux-1-schnell": "black-forest-labs/FLUX.1-schnell",
    "flux-schnell": "black-forest-labs/FLUX.1-schnell",
}

# Unit pricing estimates for Together AI
_PRICING_PER_IMAGE_USD = {
    "black-forest-labs/FLUX.1.1-pro": 0.040,
    "black-forest-labs/FLUX.1-dev": 0.025,
    "black-forest-labs/FLUX.1-schnell": 0.003,
}
_DEFAULT_IMAGE_COST_USD = 0.040
_DEFAULT_VIDEO_COST_USD = 0.30


def _normalize_together_model(model: str) -> str:
    """Resolve model aliases to Together AI's official model string."""
    m_clean = model.strip()
    return _MODEL_ALIASES.get(m_clean.lower(), m_clean)


def _resolve_dimensions(aspect_ratio: str | None, width: int | None = None, height: int | None = None) -> tuple[int, int]:
    """Map standard aspect ratios to pixel dimensions accepted by FLUX.1.1-pro."""
    if width and height:
        return width, height

    if not aspect_ratio:
        return 1024, 1024

    ar = aspect_ratio.strip()
    if ar == "9:16":
        return 768, 1344
    if ar == "16:9":
        return 1344, 768
    if ar == "4:5":
        return 864, 1080
    if ar == "1:1":
        return 1024, 1024

    return 1024, 1024


async def generate_image(
    prompt: str,
    api_key: str,
    model: str = "black-forest-labs/FLUX.1.1-pro",
    aspect_ratio: str | None = None,
    num_outputs: int = 1,
    width: int | None = None,
    height: int | None = None,
    download_locally: bool = False,
) -> tuple[dict, float]:
    """Generate image(s) using Together AI's official API.

    Returns:
        tuple of (result_dict, cost_usd)
    Raises:
        RuntimeError with granular error classification on any failure.
    """
    settings = get_settings()
    effective_model = _normalize_together_model(model)
    w, h = _resolve_dimensions(aspect_ratio, width, height)

    payload: dict[str, Any] = {
        "model": effective_model,
        "prompt": prompt,
        "width": w,
        "height": h,
        "n": max(1, int(num_outputs)),
        "response_format": "url",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    log = logger.bind(
        provider="together",
        model=effective_model,
        width=w,
        height=h,
        candidates=num_outputs,
    )
    log.info("together_image_generation_started")

    timeout_secs = float(getattr(settings, "together_timeout_seconds", 120))
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout_secs) as client:
            response = await client.post(_IMAGES_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("together_request_timeout", error=str(exc))
        raise RuntimeError(f"Together AI timed out after {timeout_secs}s: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("together_network_error", error=str(exc))
        raise RuntimeError(f"Together AI network error: {exc}") from exc

    gen_duration = round(time.perf_counter() - start_time, 3)

    # Granular HTTP error inspection
    if response.status_code == 401:
        log.warning("together_auth_failed")
        raise RuntimeError("Together AI rejected the API key (401 Unauthorized)")
    if response.status_code == 402:
        log.warning("together_credits_exhausted")
        raise RuntimeError("Together AI credits exhausted (402 Payment Required)")
    if response.status_code == 429:
        log.warning("together_rate_limited")
        raise RuntimeError("Together AI rate limit exceeded (429 Too Many Requests)")
    if response.status_code == 404:
        log.warning("together_model_not_found", model=effective_model)
        raise RuntimeError(f"Together AI model unavailable (404 Not Found): {effective_model}")
    if response.status_code >= 400:
        err_body = response.text[:500]
        log.warning("together_error_response", status_code=response.status_code, body=err_body)
        if any(w in err_body.lower() for w in ("credit", "payment required", "billing", "unpaid", "insufficient balance")):
            raise RuntimeError(f"Together AI payment required ({response.status_code}): {err_body}")
        raise RuntimeError(f"Together AI returned {response.status_code}: {err_body}")

    try:
        data = response.json()
        image_items = data.get("data", [])
        if not image_items:
            raise ValueError("No images returned in response data")
        candidate_urls = [item.get("url") for item in image_items if item.get("url")]
        if not candidate_urls:
            raise ValueError("Image objects missing 'url' key")
        storage_path = candidate_urls[0]
    except (ValueError, KeyError, IndexError) as exc:
        log.warning("together_response_malformed", error=str(exc), text=response.text[:300])
        raise RuntimeError(f"Together AI response missing expected fields: {exc}") from exc

    # Download locally if requested
    download_telemetry = None
    if download_locally and storage_path.startswith("http"):
        try:
            local_path, download_telemetry = await download_media_asset(storage_path)
            storage_path = local_path
        except Exception as exc:
            log.warning("together_asset_download_failed", error=str(exc))

    unit_price = _PRICING_PER_IMAGE_USD.get(effective_model, _DEFAULT_IMAGE_COST_USD)
    total_cost = round(unit_price * len(candidate_urls), 4)

    telemetry = {
        "provider": "together",
        "model": effective_model,
        "input_dimensions": f"{w}x{h}",
        "output_dimensions": f"{w}x{h}",
        "generation_duration_seconds": gen_duration,
        "num_candidates": len(candidate_urls),
        "cost_usd": total_cost,
        "download_telemetry": download_telemetry,
    }

    log.info("together_image_generation_succeeded", **telemetry)
    return {
        "storage_path": storage_path,
        "image_url": storage_path,
        "candidate_urls": candidate_urls,
        "candidates": candidate_urls,
        "provider": "together",
        "model": effective_model,
        "raw": data,
        "telemetry": telemetry,
    }, total_cost


async def generate_video(
    prompt: str,
    api_key: str,
    model: str = "kling",
    image_url: str | None = None,
    aspect_ratio: str | None = None,
) -> tuple[dict, float]:
    """Generate video or probe video generation model availability on Together AI.

    Together AI supports Wan video models via dedicated containers and does not host
    Kling or Seedance in its standard serverless API catalog.
    """
    settings = get_settings()
    m_clean = model.strip().lower()

    log = logger.bind(provider="together", model=model, capability="video_generation")
    log.info("together_video_request_started")

    # If user requests Kling or Seedance via Together AI:
    if any(k in m_clean for k in ("kling", "seedance")):
        reason = (
            f"Together AI serverless API does not offer '{model}'. "
            "Kling is proprietary to Kuaishou and Seedance is served via ByteDance/fal.ai."
        )
        log.warning("together_video_model_unsupported", reason=reason)
        raise RuntimeError(f"Together AI model unavailable: {reason}")

    # For Wan or generic video requests:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    if image_url:
        payload["image_url"] = image_url
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio

    timeout_secs = float(getattr(settings, "together_timeout_seconds", 300))
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout_secs) as client:
            response = await client.post(_VIDEOS_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Together AI video generation timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Together AI video network error: {exc}") from exc

    if response.status_code == 401:
        raise RuntimeError("Together AI rejected the API key (401 Unauthorized)")
    if response.status_code == 402:
        raise RuntimeError("Together AI credits exhausted (402 Payment Required)")
    if response.status_code == 404:
        raise RuntimeError(f"Together AI video model '{model}' not found in serverless catalog (404)")
    if response.status_code >= 400:
        raise RuntimeError(f"Together AI video returned {response.status_code}: {response.text[:400]}")

    data = response.json()
    storage_path = data.get("url") or data.get("output", {}).get("url")
    return {"storage_path": storage_path, "raw": data}, _DEFAULT_VIDEO_COST_USD
