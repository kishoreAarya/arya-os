"""
Shared TEXT_GENERATION provider dispatch.

Beginner note: TrendAgent and StoryboardAgent both need to turn a
`ProviderCapability` (handed to them one at a time by
`app/providers/router.py::call_with_fallback`, via ExecutionEngine)
into an actual `generate_text(prompt, api_key, model)` call against
the right adapter module. Before this file existed, each agent had its
own `call_provider` closure that only knew how to call
`app.providers.openrouter` and raised `RuntimeError` for every other
provider name — so Gemini/OpenAI/Anthropic were registered in
`capabilities.py` (see PROVIDER_CAPABILITIES) but could never actually
be reached; the fallback chain always failed past OpenRouter.

This module is the single place that maps a provider name to its
adapter module. Adding a fifth text-generation provider later means
adding one line to `_TEXT_ADAPTERS` below — not touching any agent.

Nothing about ProviderRouter's contract changes: `build_text_generation_call`
just returns a `ProviderCall` (the same
`Callable[[ProviderCapability], Awaitable[tuple[object, float]]]` shape
`call_with_fallback`/`ExecutionEngine.execute` already expect), so it
drops straight into the existing `call=...` parameter both agents
already pass to `ExecutionEngine.execute`.

None of the adapter modules (openrouter.py, gemini.py,
openai_provider.py, anthropic_provider.py) are modified — they're
reused exactly as they already exist, all sharing the same
`generate_text(prompt: str, api_key: str, model: str) -> tuple[str, float]`
signature by design.
"""
from app.core.config import get_settings
from app.core.secrets import SecretNotConfigured, get_secrets_manager
from app.providers import anthropic_provider, gemini, openai_provider, openrouter
from app.providers.capabilities import ProviderCapability
from app.providers.router import ProviderCall

# Every provider capable of Capability.TEXT_GENERATION (per
# capabilities.py's PROVIDER_CAPABILITIES) must have an entry here, or
# the fallback chain will reach it, find no adapter, and raise —
# indistinguishable from a real provider failure, which is the correct
# behavior for a provider that's registered but genuinely not wired in
# yet (there are none right now; all four text providers are wired).
_TEXT_ADAPTERS = {
    "openrouter": openrouter,
    "gemini": gemini,
    "openai": openai_provider,
    "anthropic": anthropic_provider,
}


def build_text_generation_call(prompt: str) -> ProviderCall:
    """Returns a `call_provider` closure bound to `prompt`, suitable
    for `ExecutionEngine.execute(capability=Capability.TEXT_GENERATION,
    call=..., ...)`.

    Raises RuntimeError (never returns a failing tuple) for:
    - a provider name with no adapter in `_TEXT_ADAPTERS`
    - a provider with no `secret_name` configured in capabilities.py
    - a configured `secret_name` whose value isn't set in Settings/.env

    All three are treated as an ordinary per-provider failure by
    `call_with_fallback` (any exception triggers fallback to the next
    candidate) — same taxonomy the adapters themselves already use.
    """

    async def call_provider(provider: ProviderCapability) -> tuple[str, float]:
        adapter = _TEXT_ADAPTERS.get(provider.name)
        if adapter is None:
            raise RuntimeError(
                f"No text-generation adapter implemented yet for provider '{provider.name}'"
            )

        if not provider.secret_name:
            raise RuntimeError(
                f"Provider '{provider.name}' has no secret_name configured "
                "for text generation"
            )

        try:
            api_key = get_secrets_manager().get(provider.secret_name)
        except SecretNotConfigured as exc:
            raise RuntimeError(str(exc)) from exc

        model = (
            provider.supported_models[0]
            if provider.supported_models
            else get_settings().default_llm_model
        )

        return await adapter.generate_text(prompt=prompt, api_key=api_key, model=model)

    return call_provider
