"""
Anthropic adapter — text generation, Messages API.

Same architecture as `app/providers/openrouter.py`:

    await anthropic_provider.generate_text(prompt=prompt, api_key=api_key, model=model)
    -> (text: str, cost_usd: float)

File named `anthropic_provider.py` (not `anthropic.py`), matching the
`openai_provider.py` convention already established in this directory
for the same reason: avoid shadowing the real `anthropic` PyPI package
on sys.path, even though this adapter uses plain httpx, not the
official SDK.

Auth and payload shape differ from OpenRouter/OpenAI (Anthropic uses
`x-api-key` + `anthropic-version` headers instead of a Bearer token,
`max_tokens` is required rather than optional, and the response's text
lives in a `content` block list rather than `choices[0].message`) —
exactly the kind of per-provider quirk this file exists to absorb;
callers never see the difference from openrouter.py's.
"""
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096
# Rough blended $/1K tokens for claude-sonnet-4-6 — used only as a
# cost-ceiling estimate for ProviderRouter's cost check, not meant to
# be exact-to-the-cent.
_EST_COST_PER_1K_TOKENS = 0.006


async def generate_text(prompt: str, api_key: str, model: str) -> tuple[str, float]:
    """Raises RuntimeError on any failure (auth, rate limit, timeout,
    network, malformed response) — same taxonomy as
    openrouter.py::generate_text, compatible with ExecutionEngine's
    `_is_transient_failure` (anything other than CostLimitExceededError
    is treated as transient/retryable)."""
    settings = get_settings()
    payload = {
        "model": model,
        "max_tokens": _DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _API_VERSION,
        "Content-Type": "application/json",
    }

    log = logger.bind(provider="anthropic", model=model)
    log.info("provider_request_started")

    try:
        async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
            response = await client.post(_API_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("provider_request_timeout", error=str(exc))
        raise RuntimeError(f"Anthropic timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        log.warning("provider_request_network_error", error=str(exc))
        raise RuntimeError(f"Anthropic network error: {exc}") from exc

    if response.status_code == 401:
        log.warning("provider_auth_failed")
        raise RuntimeError("Anthropic rejected the API key (401)")
    if response.status_code == 429:
        log.warning("provider_rate_limited")
        raise RuntimeError("Anthropic rate limit exceeded (429)")
    if response.status_code >= 400:
        log.warning(
            "provider_error_response",
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise RuntimeError(f"Anthropic returned {response.status_code}: {response.text[:500]}")

    try:
        data = response.json()
        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens") or 0
        output_tokens = usage.get("output_tokens") or 0
        total_tokens = input_tokens + output_tokens
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("provider_response_malformed", error=str(exc))
        raise RuntimeError(f"Anthropic response missing expected fields: {exc}") from exc

    cost_usd = round((total_tokens / 1000) * _EST_COST_PER_1K_TOKENS, 6)
    log.info("provider_request_succeeded", total_tokens=total_tokens, cost_usd=cost_usd)

    return text, cost_usd
