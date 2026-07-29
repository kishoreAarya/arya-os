"""
ComfyUI adapter — self-hosted image and video generation.

Same architecture as `app/providers/openrouter.py` (plain httpx,
RuntimeError on any failure), with two deliberate differences that
follow directly from `capabilities.py`'s own entry for this provider:

1. No API key. `secret_name=None` for "comfyui" in
   PROVIDER_CAPABILITIES on purpose ("self-hosted, reached over the
   RunPod tunnel URL, not a key") — this adapter reads
   `Settings.comfyui_base_url` instead, via `get_settings()`, the same
   way every other adapter already reads `Settings.api_timeout_seconds`.
   `api_key` is still accepted as a parameter (kept for call-shape
   symmetry with the other media adapters/`build_media_generation_call`)
   but is intentionally unused here.

2. Two-step submit-then-poll flow, because ComfyUI's `/prompt`
   endpoint queues a job and returns immediately — unlike fal.ai's
   single-call API. Polling is capped at `_MAX_POLL_ATTEMPTS`; running
   out is a real failure (RuntimeError), which is exactly what should
   trigger `call_with_fallback`'s move to the next candidate provider.

Two entry points, matching Capability.IMAGE_GENERATION and
Capability.VIDEO_GENERATION:

    await comfyui.generate_image(prompt=prompt, api_key=None, model=model)
    await comfyui.generate_video(prompt=prompt, api_key=None, model=model)
    -> (result: dict, cost_usd: float) — cost_usd is always 0.0: this
       is self-hosted GPU compute, not a metered API call (see
       capabilities.py's own "compute cost only, no per-call fee" note
       for "comfyui"'s cost_tier=1). Any real compute-cost accounting
       is a RunPod-adapter/billing concern, out of scope here.

`model` here names a checkpoint/model file already loaded on the
target ComfyUI instance (e.g. "flux1-dev.safetensors"), NOT a full
node-graph workflow — building real, production node graphs (like
Arya OS's own "Director's Edition" JSON workflows referenced in
`Arya OS/n8n/workflows/`) is a separate, much larger concern than this
adapter's job of "submit one graph, wait for output." `_build_*_workflow`
below is the simplest graph that could work for a plain
prompt-in/image-or-video-out call; a caller with a real, pre-built
ComfyUI graph should submit it directly against ComfyUI's HTTP API
rather than going through this simplified helper.
"""
import asyncio
import uuid

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_POLL_ATTEMPTS = 60
_POLL_INTERVAL_SECONDS = 1.0


def _build_image_workflow(prompt: str, model: str) -> dict:
    """Minimal single-checkpoint text-to-image graph — see module
    docstring's note on scope. Real workflows come from Arya OS's own
    workflow JSON files, not from this function."""
    return {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt}},
    }


def _build_video_workflow(prompt: str, model: str) -> dict:
    """Minimal single-checkpoint text-to-video graph — same scope note
    as `_build_image_workflow` above."""
    return {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt}},
        "mode": {"class_type": "VideoGenerationMode", "inputs": {}},
    }


def _require_base_url() -> str:
    base_url = get_settings().comfyui_base_url
    if not base_url:
        raise RuntimeError(
            "ComfyUI base URL is not configured (set COMFYUI_BASE_URL / "
            "Settings.comfyui_base_url)"
        )
    return base_url.rstrip("/")


async def _submit_and_await(base_url: str, workflow: dict, capability: str) -> dict:
    settings = get_settings()
    client_id = str(uuid.uuid4())
    log = logger.bind(provider="comfyui", capability=capability)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            submit_response = await client.post(
                f"{base_url}/prompt", json={"prompt": workflow, "client_id": client_id}
            )
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"ComfyUI timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"ComfyUI network error: {exc}") from exc

    if submit_response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=submit_response.status_code,
            body=submit_response.text[:500],
        )
        raise RuntimeError(
            f"ComfyUI returned {submit_response.status_code}: {submit_response.text[:500]}"
        )

    try:
        submit_data = submit_response.json()
        prompt_id = submit_data["prompt_id"]
    except (KeyError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"ComfyUI response missing expected fields: {exc}") from exc

    for attempt in range(_MAX_POLL_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
                history_response = await client.get(f"{base_url}/history/{prompt_id}")
        except httpx.TimeoutException as exc:
            log.warning("provider_request_timeout", error=str(exc))
            raise RuntimeError(f"ComfyUI timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            log.warning("provider_request_network_error", error=str(exc))
            raise RuntimeError(f"ComfyUI network error: {exc}") from exc

        if history_response.status_code >= 400:
            log.warning(
                "provider_error_response",
                status_code=history_response.status_code,
                body=history_response.text[:500],
            )
            raise RuntimeError(
                f"ComfyUI returned {history_response.status_code}: "
                f"{history_response.text[:500]}"
            )

        try:
            history_data = history_response.json()
        except ValueError as exc:
            log.warning("provider_response_malformed", error=str(exc))
            raise RuntimeError(f"ComfyUI response missing expected fields: {exc}") from exc

        entry = history_data.get(prompt_id)
        if entry:
            log.info("provider_request_succeeded", attempts=attempt + 1)
            return entry

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    log.warning("provider_polling_exhausted", prompt_id=prompt_id)
    raise RuntimeError(
        f"ComfyUI job {prompt_id} did not complete within "
        f"{_MAX_POLL_ATTEMPTS} polling attempts"
    )


def _first_output_filename(entry: dict, *node_output_keys: str) -> str:
    outputs = entry.get("outputs", {})
    for node_output in outputs.values():
        for key in node_output_keys:
            files = node_output.get(key)
            if files:
                return files[0]["filename"]
    raise RuntimeError("ComfyUI response missing expected fields: no output files found")


async def generate_image(prompt: str, api_key: str | None, model: str) -> tuple[dict, float]:
    """`api_key` is accepted for call-shape symmetry with the other
    media adapters but is unused — see module docstring."""
    base_url = _require_base_url()
    workflow = _build_image_workflow(prompt, model)
    entry = await _submit_and_await(base_url, workflow, "image_generation")
    filename = _first_output_filename(entry, "images")
    storage_path = f"{base_url}/view?filename={filename}"
    return {"storage_path": storage_path, "raw": entry}, 0.0


async def generate_video(prompt: str, api_key: str | None, model: str) -> tuple[dict, float]:
    """`api_key` is accepted for call-shape symmetry with the other
    media adapters but is unused — see module docstring."""
    base_url = _require_base_url()
    workflow = _build_video_workflow(prompt, model)
    entry = await _submit_and_await(base_url, workflow, "video_generation")
    filename = _first_output_filename(entry, "gifs", "videos")
    storage_path = f"{base_url}/view?filename={filename}"
    return {"storage_path": storage_path, "raw": entry}, 0.0
