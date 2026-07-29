"""
RunPod adapter — GPU job execution (Capability.GPU_EXECUTION).

Same architecture as `app/providers/openrouter.py` (plain httpx,
RuntimeError on any failure), but a different shape from the other
media adapters: RunPod isn't itself an image/video/text model, it's a
serverless GPU runner — this adapter submits a job to a RunPod
Serverless endpoint (e.g. the endpoint fronting a self-hosted ComfyUI
or custom inference container) and waits for it to finish, using
RunPod's `/runsync` route so the call shape stays one-request-in,
one-`(result, cost_usd)`-out, matching every adapter in this package.

One entry point, matching Capability.GPU_EXECUTION:

    await runpod.run_gpu_job(payload={"endpoint_id": "...", "input": {...}},
                              api_key=api_key, model=model)
    -> (result: dict, cost_usd: float)

`payload["endpoint_id"]` takes precedence; if omitted, `model` is used
as the endpoint id (capabilities.py's "runpod" entry has no
`supported_models`, so callers are expected to pass `endpoint_id`
explicitly via `payload`, same as the entry's own
`avg_latency_seconds=0` comment: "not a generation call itself; GPU
rental" — there's no single default endpoint to fall back to).

Cost is computed from RunPod's own `executionTime` (milliseconds) in
the response using a rough $/second GPU-rental estimate — same
"estimate, not exact-to-the-cent" spirit as every other adapter's
`_EST_COST_PER_*` constant.
"""
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL_TEMPLATE = "https://api.runpod.ai/v2/{endpoint_id}/runsync"
# Rough $/second estimate for a mid-tier GPU (e.g. RTX 4090) serverless
# rental — used only as a cost-ceiling estimate for ProviderRouter's
# cost check, not meant to be exact-to-the-cent.
_EST_COST_PER_SECOND_USD = 0.0006


async def run_gpu_job(
    payload: dict, api_key: str, model: str | None = None
) -> tuple[dict, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response, or a job that completes with a
    non-COMPLETED status) — same taxonomy as every other adapter here,
    compatible with ExecutionEngine's `_is_transient_failure`.
    """
    endpoint_id = payload.get("endpoint_id") or model or get_settings().runpod_endpoint_id
    if not endpoint_id:
        raise RuntimeError(
            "RunPod job requires an endpoint_id (payload['endpoint_id'], "
            "the provider's model/version, or Settings.runpod_endpoint_id)"
        )

    settings = get_settings()
    url = _API_URL_TEMPLATE.format(endpoint_id=endpoint_id)
    body = {"input": payload.get("input", {})}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    log = logger.bind(provider="runpod", endpoint_id=endpoint_id, capability="gpu_execution")
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"RunPod timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"RunPod network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("RunPod rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("RunPod rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"RunPod returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        status = data["status"]
    except (KeyError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"RunPod response missing expected fields: {exc}") from exc

    if status != "COMPLETED":
        log.warning("provider_job_not_completed", status=status)
        raise RuntimeError(f"RunPod job did not complete (status={status}): {data.get('error')}")

    execution_ms = data.get("executionTime") or 0
    cost_usd = round((execution_ms / 1000) * _EST_COST_PER_SECOND_USD, 6)

    log.info("provider_request_succeeded", execution_ms=execution_ms, cost_usd=cost_usd)
    return {"output": data.get("output"), "raw": data}, cost_usd
