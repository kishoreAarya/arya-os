"""
Unit tests for app/providers/text_dispatch.py — the shared dispatcher
that replaced TrendAgent's and StoryboardAgent's identical
`if provider.name == "openrouter"` special-casing.

No real HTTP: each adapter's `generate_text` is monkeypatched directly
(same style as test_llm_provider_adapters_unit.py), so these tests
prove the dispatcher picks the right adapter, resolves the right
secret, and picks the right model — not that the adapters themselves
work (that's already covered by their own test files).
"""
from unittest.mock import AsyncMock

import pytest

from app.providers import anthropic_provider, gemini, openai_provider, openrouter
from app.providers.capabilities import PROVIDER_CAPABILITIES
from app.providers.text_dispatch import build_text_generation_call


def _settings_with_keys(monkeypatch, **keys):
    """Point every secret_name at a fake key, only for the ones passed in."""
    from app.core import secrets as secrets_module

    settings = secrets_module.get_settings()
    for key_name, value in keys.items():
        monkeypatch.setattr(settings, key_name, value, raising=False)
    # Force a fresh SecretsManager bound to the (mutated) settings above.
    monkeypatch.setattr(secrets_module, "_secrets_manager", None)


@pytest.mark.parametrize(
    ("provider_name", "adapter", "secret_name"),
    [
        ("openrouter", openrouter, "openrouter_api_key"),
        ("gemini", gemini, "gemini_api_key"),
        ("openai", openai_provider, "openai_api_key"),
        ("anthropic", anthropic_provider, "anthropic_api_key"),
    ],
)
@pytest.mark.asyncio
async def test_dispatches_to_correct_adapter_for_each_provider(
    monkeypatch, provider_name, adapter, secret_name
):
    _settings_with_keys(monkeypatch, **{secret_name: "fake-key"})
    monkeypatch.setattr(
        adapter, "generate_text", AsyncMock(return_value=("generated text", 0.01))
    )

    call_provider = build_text_generation_call("a prompt")
    provider = PROVIDER_CAPABILITIES[provider_name]

    text, cost_usd = await call_provider(provider)

    assert text == "generated text"
    assert cost_usd == 0.01
    adapter.generate_text.assert_awaited_once()
    call_kwargs = adapter.generate_text.await_args.kwargs
    assert call_kwargs["prompt"] == "a prompt"
    assert call_kwargs["api_key"] == "fake-key"
    from app.core.config import get_settings

    expected_model = (
        provider.supported_models[0]
        if provider.supported_models
        else get_settings().default_llm_model
    )
    assert call_kwargs["model"] == expected_model


@pytest.mark.asyncio
async def test_non_openrouter_provider_no_longer_raises_unimplemented(monkeypatch):
    """Regression test for the removed special-casing: before this
    change, any provider other than 'openrouter' hit
    `raise RuntimeError("No adapter implemented yet for provider ...")`
    in TrendAgent/StoryboardAgent, even though gemini/openai/anthropic
    adapters existed. This confirms Gemini (i.e. any non-OpenRouter
    provider) is now actually reachable.
    """
    _settings_with_keys(monkeypatch, gemini_api_key="fake-key")
    monkeypatch.setattr(
        gemini, "generate_text", AsyncMock(return_value=("hola", 0.001))
    )

    call_provider = build_text_generation_call("say hi")
    result = await call_provider(PROVIDER_CAPABILITIES["gemini"])

    assert result == ("hola", 0.001)


@pytest.mark.asyncio
async def test_missing_secret_raises_runtime_error(monkeypatch):
    _settings_with_keys(monkeypatch, openai_api_key=None)

    call_provider = build_text_generation_call("a prompt")

    with pytest.raises(RuntimeError, match="not configured"):
        await call_provider(PROVIDER_CAPABILITIES["openai"])


@pytest.mark.asyncio
async def test_unknown_provider_name_raises_runtime_error():
    from dataclasses import replace

    unknown = replace(PROVIDER_CAPABILITIES["openrouter"], name="not_a_real_provider")
    call_provider = build_text_generation_call("a prompt")

    with pytest.raises(RuntimeError, match="No text-generation adapter"):
        await call_provider(unknown)
