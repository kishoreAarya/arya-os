"""
Google Gemini adapter — text generation only.

Same architecture as `app/providers/openrouter.py`, deliberately
mirrored line-for-line where the two providers' APIs agree, so the two
files read as obviously-the-same-shape:

    await gemini.generate_text(prompt=prompt, api_key=api_key, model=model)
    -> (text: str, cost_usd: float)

The one real difference is auth: Gemini takes the key as a `?key=`
query param on `generateContent`, not an `Authorization: Bearer`
header — everything else (timeout source, error taxonomy, logging
event names, retry/fallback compatibility) is identical to
openrouter.py on purpose.

Not wired into any agent's `call_provider` closure by this change —
those closures (`agents/trend.py`, `agents/storyboard.py`) currently
special-case `if provider.name == "openrouter"` only; adding Gemini as
a real fallback candidate there is a separate, deliberate call site
change, out of scope for "add the adapter" per this task's own
instruction to return only changed files for what was asked.
"""
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Rough blended $/1K tokens for gemini-2.0-flash — used only as a
# cost-ceiling estimate for ProviderRouter's cost check, not meant to
# be exact-to-the-cent.
_EST_COST_PER_1K_TOKENS = 0.0003


async def generate_text(prompt: str, api_key: str, model: str) -> tuple[str, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — same taxonomy as
    openrouter.py::generate_text, compatible with ExecutionEngine's
    `_is_transient_failure` (anything other than CostLimitExceededError
    is treated as transient/retryable)."""
    settings = get_settings()
    url = _API_URL_TEMPLATE.format(model=model)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    log = logger.bind(provider="gemini", model=model)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(url, json=payload, params={"key": api_key})
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"Gemini timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"Gemini network error: {exc}") from exc

    if response.status_code in (401, 403):
        log.warning("provider_auth_failed", status_code=response.status_code)
        raise RuntimeError(f"Gemini rejected the API key ({response.status_code})")
    if response.status_code == 429:
        log.warning(
            "provider_rate_limited",
            body=response.text,
        )
        raise RuntimeError(f"Gemini rate limit exceeded (429): {response.text}")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"Gemini returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        total_tokens = usage.get("totalTokenCount") or (
            (usage.get("promptTokenCount") or 0) + (usage.get("candidatesTokenCount") or 0)
        )
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"Gemini response missing expected fields: {exc}") from exc

    cost_usd = round((total_tokens / 1000) * _EST_COST_PER_1K_TOKENS, 6)
    log.info("provider_request_succeeded", total_tokens=total_tokens, cost_usd=cost_usd)

    return text, cost_usd
