"""
OpenAI adapter — text generation, Chat Completions API.

Same architecture as `app/providers/openrouter.py` — the two APIs
share the OpenAI-compatible chat-completions request/response shape,
so this file is nearly identical to openrouter.py by design, just
pointed at a different URL/default model/cost estimate:

    await openai_provider.generate_text(prompt=prompt, api_key=api_key, model=model)
    -> (text: str, cost_usd: float)

File named `openai_provider.py` (not `openai.py`) to avoid shadowing
the real `openai` PyPI package on sys.path — this adapter uses plain
httpx, not the official SDK, so there's no real import collision risk
in practice, but the name stays deliberately unambiguous, matching the
naming convention already used elsewhere in this repository's history.
"""
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://api.openai.com/v1/chat/completions"
# Rough blended $/1K tokens for gpt-4o-mini — used only as a
# cost-ceiling estimate for ProviderRouter's cost check, not meant to
# be exact-to-the-cent.
_EST_COST_PER_1K_TOKENS = 0.00075


async def generate_text(prompt: str, api_key: str, model: str) -> tuple[str, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — same taxonomy as
    openrouter.py::generate_text, compatible with ExecutionEngine's
    `_is_transient_failure` (anything other than CostLimitExceededError
    is treated as transient/retryable)."""
    settings = get_settings()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    log = logger.bind(provider="openai", model=model)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"OpenAI timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"OpenAI network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("OpenAI rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("OpenAI rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"OpenAI returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens") or (
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"OpenAI response missing expected fields: {exc}") from exc

    cost_usd = round((total_tokens / 1000) * _EST_COST_PER_1K_TOKENS, 6)
    log.info("provider_request_succeeded", total_tokens=total_tokens, cost_usd=cost_usd)

    return text, cost_usd
