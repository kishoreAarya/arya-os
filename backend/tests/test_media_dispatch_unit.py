"""
Unit tests for app/providers/media_dispatch.py — the shared dispatcher
that maps (provider.name, capability) -> the right adapter method,
analogous to test_provider_text_dispatch_unit.py for
text_dispatch.py.

Each adapter's actual generate_x/run_gpu_job is monkeypatched directly
(no real HTTP) — these tests prove the dispatcher wires the right
adapter/method/model/secret together, not that the adapters themselves
work (already covered by their own test files).
"""
from unittest.mock import AsyncMock

import pytest

from app.providers import comfyui, fal, replicate, runpod
from app.providers.capabilities import PROVIDER_CAPABILITIES, Capability
from app.providers.media_dispatch import build_media_generation_call


def _settings_with_keys(monkeypatch, **keys):
    from app.core import secrets as secrets_module

    settings = secrets_module.get_settings()
    for key_name, value in keys.items():
        monkeypatch.setattr(settings, key_name, value, raising=False)
    monkeypatch.setattr(secrets_module, "_secrets_manager", None)


@pytest.mark.asyncio
async def test_image_generation_dispatches_to_fal(monkeypatch):
    _settings_with_keys(monkeypatch, fal_api_key="fal-key")
    monkeypatch.setattr(fal, "generate_image", AsyncMock(return_value=({"storage_path": "u"}, 0.02)))

    call_provider = build_media_generation_call(Capability.IMAGE_GENERATION, prompt="a cat")
    result = await call_provider(PROVIDER_CAPABILITIES["fal"])

    assert result == ({"storage_path": "u"}, 0.02)
    fal.generate_image.assert_awaited_once()
    kwargs = fal.generate_image.await_args.kwargs
    assert kwargs["prompt"] == "a cat"
    assert kwargs["api_key"] == "fal-key"
    assert kwargs["model"] == PROVIDER_CAPABILITIES["fal"].supported_models[0]


@pytest.mark.asyncio
async def test_image_generation_dispatches_to_comfyui_with_no_secret(monkeypatch):
    """comfyui has secret_name=None — the dispatcher must not attempt
    a secret lookup for it, and must pass api_key=None through."""
    monkeypatch.setattr(
        comfyui, "generate_image", AsyncMock(return_value=({"storage_path": "u"}, 0.0))
    )

    call_provider = build_media_generation_call(Capability.IMAGE_GENERATION, prompt="a cat")
    result = await call_provider(PROVIDER_CAPABILITIES["comfyui"])

    assert result == ({"storage_path": "u"}, 0.0)
    kwargs = comfyui.generate_image.await_args.kwargs
    assert kwargs["api_key"] is None


@pytest.mark.asyncio
async def test_video_generation_passes_image_url_when_adapter_supports_it(monkeypatch):
    _settings_with_keys(monkeypatch, fal_api_key="fal-key")
    captured = {}

    async def fake_generate_video(prompt, api_key, model, image_url=None):
        captured["image_url"] = image_url
        return {"storage_path": "v"}, 0.35

    monkeypatch.setattr(fal, "generate_video", fake_generate_video)

    call_provider = build_media_generation_call(
        Capability.VIDEO_GENERATION, prompt="a cat running", image_url="https://x/y.png"
    )
    await call_provider(PROVIDER_CAPABILITIES["fal"])

    assert captured["image_url"] == "https://x/y.png"


@pytest.mark.asyncio
async def test_video_generation_omits_image_url_for_adapter_without_it(monkeypatch):
    """comfyui.generate_video doesn't accept image_url — the
    dispatcher must call it without that kwarg instead of raising."""
    captured = {}

    async def fake_generate_video(prompt, api_key, model):
        captured["called"] = True
        return {"storage_path": "v"}, 0.0

    monkeypatch.setattr(comfyui, "generate_video", fake_generate_video)

    call_provider = build_media_generation_call(
        Capability.VIDEO_GENERATION, prompt="a cat running", image_url="https://x/y.png"
    )
    result = await call_provider(PROVIDER_CAPABILITIES["comfyui"])

    assert result == ({"storage_path": "v"}, 0.0)
    assert captured["called"] is True


@pytest.mark.asyncio
async def test_tts_dispatches_to_replicate_generate_speech(monkeypatch):
    _settings_with_keys(monkeypatch, replicate_api_key="r-key")
    monkeypatch.setattr(
        replicate, "generate_speech", AsyncMock(return_value=({"storage_path": "a.mp3"}, 0.01))
    )

    call_provider = build_media_generation_call(Capability.TTS, prompt="hello world")
    result = await call_provider(PROVIDER_CAPABILITIES["replicate"])

    assert result == ({"storage_path": "a.mp3"}, 0.01)
    kwargs = replicate.generate_speech.await_args.kwargs
    assert kwargs["text"] == "hello world"


@pytest.mark.asyncio
async def test_gpu_execution_dispatches_to_runpod(monkeypatch):
    _settings_with_keys(monkeypatch, runpod_api_key="rp-key")
    monkeypatch.setattr(
        runpod, "run_gpu_job", AsyncMock(return_value=({"output": {}}, 0.0012))
    )

    call_provider = build_media_generation_call(
        Capability.GPU_EXECUTION, payload={"endpoint_id": "ep-1", "input": {"x": 1}}
    )
    result = await call_provider(PROVIDER_CAPABILITIES["runpod"])

    assert result == ({"output": {}}, 0.0012)
    kwargs = runpod.run_gpu_job.await_args.kwargs
    assert kwargs["payload"] == {"endpoint_id": "ep-1", "input": {"x": 1}}
    assert kwargs["api_key"] == "rp-key"


@pytest.mark.asyncio
async def test_unknown_provider_name_raises_runtime_error():
    from dataclasses import replace

    unknown = replace(PROVIDER_CAPABILITIES["fal"], name="not_a_real_provider")
    call_provider = build_media_generation_call(Capability.IMAGE_GENERATION, prompt="x")

    with pytest.raises(RuntimeError, match="No media adapter"):
        await call_provider(unknown)


@pytest.mark.asyncio
async def test_capability_with_no_dispatch_mapping_raises_runtime_error():
    call_provider = build_media_generation_call(Capability.EMBEDDINGS, prompt="x")

    with pytest.raises(RuntimeError, match="No media dispatch method mapped"):
        await call_provider(PROVIDER_CAPABILITIES["fal"])


@pytest.mark.asyncio
async def test_adapter_missing_required_method_raises_runtime_error():
    """runpod has no generate_image method — asking for
    IMAGE_GENERATION against it must fail cleanly, not with
    AttributeError."""
    call_provider = build_media_generation_call(Capability.IMAGE_GENERATION, prompt="x")

    with pytest.raises(RuntimeError, match="no 'generate_image' implementation"):
        await call_provider(PROVIDER_CAPABILITIES["runpod"])


@pytest.mark.asyncio
async def test_missing_secret_raises_runtime_error(monkeypatch):
    _settings_with_keys(monkeypatch, fal_api_key=None)

    call_provider = build_media_generation_call(Capability.IMAGE_GENERATION, prompt="x")
    with pytest.raises(RuntimeError, match="not configured"):
        await call_provider(PROVIDER_CAPABILITIES["fal"])
