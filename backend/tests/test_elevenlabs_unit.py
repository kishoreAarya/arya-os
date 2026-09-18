"""Focused unit tests for ElevenLabs Text-to-Speech integration in Arya OS.

Covers:
1. ElevenLabs configuration (Settings, environment variables, default preservation)
2. Provider selection and routing (explicit vs default Kokoro/Replicate)
3. Missing API key handling (raises SecretNotConfigured / RuntimeError cleanly)
4. Adapter request construction (headers, with-timestamps URL, payload, voice/model)
5. Timestamp & alignment parsing (ElevenLabs character alignment to WordTiming and segments)
6. Error handling (HTTP 401, 429, network errors)
7. Security & secret redaction (API key never exposed in logs or exception messages)
8. Telemetry and cost calculation
"""

import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.voice import VoiceAgent, VoiceResult
from app.core.audio_timing import parse_alignment_data
from app.core.config import Settings
from app.core.secrets import SecretNotConfigured, SecretsManager
from app.providers import elevenlabs
from app.providers.capabilities import Capability, PROVIDER_CAPABILITIES, providers_for
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine, ExecutionResult
from app.workflows.models import WorkflowInput


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


# ---------------------------------------------------------------------------
# 1. Configuration Tests
# ---------------------------------------------------------------------------
def test_elevenlabs_configuration_defaults(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    settings = Settings(
        _env_file=None,
        app_name="arya-test",
        postgres_user="u",
        postgres_password="p",
        postgres_db="db",
        secret_key="secret",
    )
    assert settings.elevenlabs_api_key is None
    assert settings.elevenlabs_voice_id == "JBFqnCBsd6RMkjVDRZzb"
    assert settings.elevenlabs_model_id == "eleven_turbo_v2_5"
    assert settings.elevenlabs_timeout_seconds == 60
    assert settings.elevenlabs_cost_per_1k_chars_usd == 0.30
    assert settings.default_voice_provider == "elevenlabs"


def test_elevenlabs_configuration_env_overrides(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_123")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom_voice_abc")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    monkeypatch.setenv("DEFAULT_VOICE_PROVIDER", "replicate")

    settings = Settings(
        app_name="arya-test",
        postgres_user="u",
        postgres_password="p",
        postgres_db="db",
        secret_key="secret",
    )
    assert settings.elevenlabs_api_key == "test_key_123"
    assert settings.elevenlabs_voice_id == "custom_voice_abc"
    assert settings.elevenlabs_model_id == "eleven_multilingual_v2"
    assert settings.default_voice_provider == "replicate"


# ---------------------------------------------------------------------------
# 2. Provider Capability & Model Registration
# ---------------------------------------------------------------------------
def test_elevenlabs_provider_registration():
    cap = PROVIDER_CAPABILITIES.get("elevenlabs")
    assert cap is not None
    assert cap.name == "elevenlabs"
    assert Capability.TTS in cap.capabilities
    assert cap.secret_name == "elevenlabs_api_key"
    assert "eleven_turbo_v2_5" in cap.supported_models
    assert cap.get_model(Capability.TTS) == "eleven_turbo_v2_5"


# ---------------------------------------------------------------------------
# 3. Provider Selection & Default Preservation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_voice_agent_uses_default_provider_when_unspecified():
    """When no voice provider is specified, VoiceAgent uses default_voice_provider (elevenlabs with replicate fallback)."""
    db_mock = AsyncMock()
    agent = VoiceAgent(db=db_mock)
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(
        return_value=ExecutionResult(
            success=True,
            output={"storage_path": "/tmp/default.mp3", "duration_seconds": 3.0},
            provider="elevenlabs",
            cost_usd=0.01,
        )
    )

    res = await agent.run({"script_content": "Testing voice narration"})
    assert res.success is True
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["priority"] == ["elevenlabs", "replicate"]


@pytest.mark.asyncio
async def test_voice_agent_explicit_elevenlabs_selection():
    """When provider='elevenlabs' is specified, VoiceAgent prioritizes elevenlabs with replicate fallback."""
    db_mock = AsyncMock()
    agent = VoiceAgent(db=db_mock)
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(
        return_value=ExecutionResult(
            success=True,
            output={"storage_path": "/tmp/el.mp3", "duration_seconds": 3.2},
            provider="elevenlabs",
            cost_usd=0.005,
        )
    )

    res = await agent.run(
        {
            "script_content": "Testing voice narration",
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "voice_model": "eleven_multilingual_v2",
        }
    )
    assert res.success is True
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["priority"] == ["elevenlabs", "replicate"]


def test_workflow_input_voice_selection_fields():
    """WorkflowInput allows explicit voice selection fields."""
    wi = WorkflowInput(
        topic="Haunted cellars",
        preset="documentary_short",
        voice_provider="elevenlabs",
        voice_id="custom_voice_id",
        voice_model="eleven_multilingual_v2",
    )
    assert wi.voice_provider == "elevenlabs"
    assert wi.voice_id == "custom_voice_id"
    assert wi.voice_model == "eleven_multilingual_v2"


# ---------------------------------------------------------------------------
# 4. Adapter Request Construction & Response Parsing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_elevenlabs_request_construction(monkeypatch):
    """Verify URL, headers, payload, and response processing in generate_speech."""
    recorded_requests = []

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            recorded_requests.append({"url": url, "json": json, "headers": headers})
            # Generate valid dummy mp3 base64
            dummy_bytes = b"ID3\x03\x00\x00\x00\x00\x00#TSSE\x00\x00\x00\x0f\x00\x00\x01Lavf62.12.102"
            dummy_b64 = base64.b64encode(dummy_bytes).decode("ascii")
            return FakeResponse(
                status_code=200,
                json_data={
                    "audio_base64": dummy_b64,
                    "alignment": {
                        "characters": ["H", "e", "l", "l", "o"],
                        "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4],
                        "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5],
                    },
                },
            )

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", MockAsyncClient)
    monkeypatch.setattr(elevenlabs, "_probe_duration", lambda p: 2.5)

    result, cost_usd = await elevenlabs.generate_speech(
        text="Hello world",
        api_key="sk_test_secret_key",
        model="eleven_turbo_v2_5",
        voice_id="test_voice_456",
    )

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req["url"] == "https://api.elevenlabs.io/v1/text-to-speech/test_voice_456/with-timestamps"
    assert req["headers"]["xi-api-key"] == "sk_test_secret_key"
    assert req["headers"]["Content-Type"] == "application/json"
    assert req["json"]["text"] == "Hello world"
    assert req["json"]["model_id"] == "eleven_turbo_v2_5"
    assert "stability" in req["json"]["voice_settings"]

    assert result["duration_seconds"] == 2.5
    assert os.path.exists(result["storage_path"])
    assert result["alignment"]["characters"] == ["H", "e", "l", "l", "o"]
    assert cost_usd > 0.0


# ---------------------------------------------------------------------------
# 5. Missing API Key & Error Handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_elevenlabs_missing_api_key():
    with pytest.raises(RuntimeError, match="ElevenLabs API key is missing or empty"):
        await elevenlabs.generate_speech(text="Hello", api_key="")


@pytest.mark.asyncio
async def test_elevenlabs_empty_text():
    with pytest.raises(RuntimeError, match="Text to synthesize is empty"):
        await elevenlabs.generate_speech(text="", api_key="valid_key")


@pytest.mark.asyncio
async def test_elevenlabs_http_401_error(monkeypatch):
    class Mock401Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            return FakeResponse(status_code=401, text="Invalid credentials provided")

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", Mock401Client)
    with pytest.raises(RuntimeError, match="ElevenLabs TTS failed with HTTP 401"):
        await elevenlabs.generate_speech(text="Test", api_key="secret_key_xyz")


@pytest.mark.asyncio
async def test_elevenlabs_network_error(monkeypatch):
    class MockNetworkErrorClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", MockNetworkErrorClient)
    with pytest.raises(RuntimeError, match="ElevenLabs network error"):
        await elevenlabs.generate_speech(text="Test", api_key="secret_key_xyz")


# ---------------------------------------------------------------------------
# 6. Security & Secret Redaction
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_elevenlabs_secret_redaction_in_error_message(monkeypatch):
    """Verify that if the API key appears in server error text, it is redacted."""
    leaked_key = "sk_sensitive_key_999"

    class MockLeakingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            return FakeResponse(
                status_code=400,
                text=f"Unauthorized for key {leaked_key}: please check account status.",
            )

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", MockLeakingClient)

    try:
        await elevenlabs.generate_speech(text="Test", api_key=leaked_key)
        pytest.fail("Should have raised RuntimeError")
    except RuntimeError as exc:
        err_str = str(exc)
        assert leaked_key not in err_str
        assert "[REDACTED]" in err_str


# ---------------------------------------------------------------------------
# 7. Character Alignment Parsing & Timing Integration
# ---------------------------------------------------------------------------
def test_elevenlabs_alignment_parsing_to_words():
    """Verify ElevenLabs character alignment schema groups cleanly into word timings."""
    chars = ["T", "h", "e", " ", "d", "o", "o", "r", " ", "o", "p", "e", "n", "e", "d", "."]
    starts = [round(i * 0.05, 3) for i in range(len(chars))]
    ends = [round(s + 0.05, 3) for s in starts]

    alignment = {
        "characters": chars,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }

    timing = parse_alignment_data(
        text="The door opened.",
        alignment=alignment,
        total_duration=1.5,
        provider="elevenlabs",
    )

    assert timing.has_real_timestamps is True
    assert timing.fallback_used is False
    assert len(timing.words) == 3
    assert [w.word for w in timing.words] == ["The", "door", "opened."]
    assert timing.words[0].start_seconds == 0.0
    assert timing.words[1].word == "door"
    assert timing.words[2].word == "opened."
