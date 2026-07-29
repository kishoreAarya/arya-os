"""
OpenRouter adapter — text generation only.

This file was referenced by `agents/trend.py` and `agents/storyboard.py`
(`from app.providers import openrouter` / `openrouter.generate_text(...)`)
but did not exist in the repository, which broke both modules' imports
— and, because `agents/registry.py` imports every agent unconditionally
to build `AGENT_REGISTRY`, broke importing `app.agents.registry` at
all, and anything downstream of it (the FastAPI app, and every test
module that imports an agent).

Function signature matches the call sites exactly, unchanged:

    await openrouter.generate_text(prompt=prompt, api_key=api_key, model=model)
    -> (text: str, cost_usd: float)

Both call sites already do their own try/except around
`get_secrets_manager().get("openrouter_api_key")` before calling this,
and both pass `api_key` in explicitly — so this module does not read
Settings or SecretsManager itself, it only does the HTTP call. This
keeps this fix scoped to exactly what was missing, not a redesign of
how the agents obtain credentials.

Any exception raised here propagates out of the `call_provider`
closure in trend.py/storyboard.py, which `providers/router.py`'s
`call_with_fallback` (called via ExecutionEngine) already catches as a
per-provider failure — no changes needed there for retry/fallback
compatibility.
"""
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Rough $/1K tokens blended estimate for the OpenRouter model family in
# use (DeepSeek/Kimi) — used only as a cost-ceiling estimate for
# ProviderRouter's cost check, not meant to be exact-to-the-cent.
_EST_COST_PER_1K_TOKENS = 0.002


async def generate_text(prompt: str, api_key: str, model: str) -> tuple[str, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — deliberately a plain RuntimeError,
    matching the style already used in trend.py/storyboard.py's own
    `call_provider` closures (`raise RuntimeError(...)` for the
    no-adapter case), and compatible with ExecutionEngine's
    `_is_transient_failure`, which treats any exception other than
    CostLimitExceededError as transient/retryable."""
    settings = get_settings()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    log = logger.bind(provider="openrouter", model=model)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"OpenRouter timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"OpenRouter network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("OpenRouter rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("OpenRouter rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"OpenRouter returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens") or (
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"OpenRouter response missing expected fields: {exc}") from exc

    cost_usd = round((total_tokens / 1000) * _EST_COST_PER_1K_TOKENS, 6)
    log.info("provider_request_succeeded", total_tokens=total_tokens, cost_usd=cost_usd)

    return text, cost_usd
