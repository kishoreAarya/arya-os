"""Unit tests for ElevenLabs production promotion, Kokoro fallback, and telemetry.

Tests:
1. Production default voice provider is ElevenLabs.
2. Preset configuration for cinematic_story specifies ElevenLabs.
3. VoiceAgent priority resolution (defaults, explicit elevenlabs, explicit replicate).
4. Media dispatch translation for Kokoro fallback.
5. Fallback simulation on Timeout, 401 Unauthorized, and 429 Rate Limit.
6. GenerationAttempt persistence records primary attempt failure and fallback attempt success.
7. Real timestamps flag when ElevenLabs succeeds vs fallback flags when Replicate is used.
"""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings
from app.core.presets import get_preset
from app.agents.voice import VoiceAgent
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine
from app.models.approval import GenerationAttempt


# 1. Configuration & Presets
def test_production_default_voice_is_elevenlabs():
    """Verify that settings default voice provider is elevenlabs."""
    s = Settings(_env_file=None)
    assert s.default_voice_provider == "elevenlabs"
    assert s.elevenlabs_voice_id == "JBFqnCBsd6RMkjVDRZzb"
    assert s.elevenlabs_model_id == "eleven_turbo_v2_5"


def test_cinematic_story_preset_voice_settings():
    """Verify that cinematic_story preset is configured with ElevenLabs."""
    preset = get_preset("cinematic_story")
    assert preset.voice_provider == "elevenlabs"
    assert preset.voice_id == "JBFqnCBsd6RMkjVDRZzb"
    assert preset.voice_model == "eleven_turbo_v2_5"
    assert preset.captions_enabled is True


# 2. Priority Resolution in VoiceAgent
@pytest.mark.asyncio
async def test_voice_agent_default_priority():
    """When voice_provider is not provided, VoiceAgent tries elevenlabs first then replicate."""
    db = AsyncMock()
    agent = VoiceAgent(db=db)

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        from app.services.execution_engine import ExecutionResult
        mock_exec.return_value = ExecutionResult(
            success=True,
            provider="elevenlabs",
            output={"storage_path": "/tmp/test.mp3", "duration_seconds": 3.5},
            cost_usd=0.01,
            elapsed_time=1.2,
        )

        context = {
            "voiceover": "A chilling whisper echoed down the stone corridor.",
            "workflow_run_id": str(uuid.uuid4()),
        }
        res = await agent.run(context)

        assert res.success is True
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["priority"] == ["elevenlabs", "replicate"]


@pytest.mark.asyncio
async def test_voice_agent_explicit_replicate_override():
    """When caller explicitly specifies provider='replicate', priority contains only replicate."""
    db = AsyncMock()
    agent = VoiceAgent(db=db)

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        from app.services.execution_engine import ExecutionResult
        mock_exec.return_value = ExecutionResult(
            success=True,
            provider="replicate",
            output={"storage_path": "/tmp/test_kokoro.wav", "duration_seconds": 3.0},
            cost_usd=0.01,
            elapsed_time=2.0,
        )

        context = {
            "voiceover": "A chilling whisper echoed down the stone corridor.",
            "voice_provider": "replicate",
            "workflow_run_id": str(uuid.uuid4()),
        }
        res = await agent.run(context)

        assert res.success is True
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["priority"] == ["replicate"]


# 3. Media Dispatch Translation
@pytest.mark.asyncio
async def test_media_dispatch_protects_kokoro_from_elevenlabs_model():
    """Media dispatch does not forward elevenlabs model strings or voice hash to Replicate Kokoro."""
    from app.providers.capabilities import ProviderCapability

    rep_provider = ProviderCapability(
        name="replicate",
        capabilities=(Capability.TTS,),
        cost_tier=3,
        avg_latency_seconds=40,
        supported_models=("jaaari/kokoro-82m:f559560eb822dc509045f3921a1921234918b91739db4bf3daab2169b71c7a13",),
        capability_models={
            Capability.TTS: ("jaaari/kokoro-82m:f559560eb822dc509045f3921a1921234918b91739db4bf3daab2169b71c7a13",),
        },
        secret_name="replicate_api_key",
    )

    with patch("app.providers.replicate.generate_speech", new_callable=AsyncMock) as mock_speech, \
         patch("app.providers.media_dispatch.get_secrets_manager") as mock_sm:
        mock_sm.return_value.get.return_value = "fake_replicate_key"
        mock_speech.return_value = ({"storage_path": "/tmp/kokoro.wav"}, 0.01)

        call_fn = build_media_generation_call(
            capability=Capability.TTS,
            prompt="Test prompt",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            voice_model="eleven_turbo_v2_5",
        )

        await call_fn(rep_provider)

        call_args = mock_speech.call_args
        # Verify eleven_turbo_v2_5 was NOT passed as model to replicate
        assert "eleven" not in call_args.kwargs.get("model", "")
        # Verify voice_id was translated to a safe Kokoro voice
        assert call_args.kwargs.get("voice_id") == "bm_george"


# 4. Fallback Execution & GenerationAttempt Telemetry
@pytest.mark.asyncio
@pytest.mark.parametrize("error_scenario", [
    ("timeout", asyncio.TimeoutError("Request timed out")),
    ("auth_401", RuntimeError("ElevenLabs TTS failed with HTTP 401: Unauthorized [REDACTED]")),
    ("rate_limit_429", RuntimeError("ElevenLabs TTS failed with HTTP 429: Too Many Requests")),
])
async def test_fallback_triggers_kokoro_and_records_telemetry(error_scenario):
    """When ElevenLabs fails (timeout, 401, 429), router falls back to Replicate Kokoro,
    and ExecutionEngine records both the failed primary attempt and successful fallback attempt."""
    scenario_name, simulated_error = error_scenario

    db = AsyncMock()
    db.add = MagicMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = uuid.uuid4()
    db.execute.return_value = mock_res
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    engine = ExecutionEngine(db=db)
    wf_id = uuid.uuid4()

    async def mock_call(provider):
        if provider.name == "elevenlabs":
            raise simulated_error
        elif provider.name == "replicate":
            return ({"storage_path": "/tmp/fallback_kokoro.wav", "duration_seconds": 4.2}, 0.01)
        raise RuntimeError(f"Unexpected provider {provider.name}")

    result = await engine.execute(
        capability=Capability.TTS,
        call=mock_call,
        workflow_run_id=wf_id,
        stage="voice_generation",
        priority=["elevenlabs", "replicate"],
    )

    assert result.success is True
    assert result.provider == "replicate"

    # Verify GenerationAttempt telemetry
    persisted_attempts = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], GenerationAttempt)
    ]
    assert len(persisted_attempts) == 2

    # Attempt 1: Failed ElevenLabs
    attempt_1 = persisted_attempts[0]
    assert attempt_1.workflow_run_id == wf_id
    assert attempt_1.attempt_number == 1
    assert attempt_1.succeeded is False
    assert "elevenlabs" in attempt_1.failure_reason.lower()

    # Attempt 2: Succeeded Replicate
    attempt_2 = persisted_attempts[1]
    assert attempt_2.workflow_run_id == wf_id
    assert attempt_2.attempt_number == 2
    assert attempt_2.succeeded is True
    assert attempt_2.cost_usd == 0.01


# 5. Timestamp Flag Validation
@pytest.mark.asyncio
async def test_narration_timing_flags_on_success_and_fallback():
    """Verify real timestamp flag is True when ElevenLabs succeeds, and False on Kokoro fallback."""
    db = AsyncMock()
    agent = VoiceAgent(db=db)

    # Success case: ElevenLabs returns alignment
    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        from app.services.execution_engine import ExecutionResult
        mock_exec.return_value = ExecutionResult(
            success=True,
            provider="elevenlabs",
            output={
                "storage_path": "/tmp/elevenlabs_real.mp3",
                "duration_seconds": 3.0,
                "alignment": {
                    "characters": ["H", "e", "l", "l", "o"],
                    "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4],
                    "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5],
                },
            },
            cost_usd=0.02,
            elapsed_time=1.5,
        )

        res = await agent.run({"voiceover": "Hello", "workflow_run_id": str(uuid.uuid4())})
        assert res.success is True
        assert res.output["has_real_timestamps"] is True
        assert res.output["fallback_used"] is False

    # Fallback case: Kokoro returns no alignment
    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = ExecutionResult(
            success=True,
            provider="replicate",
            output={
                "storage_path": "/tmp/kokoro_fallback.wav",
                "duration_seconds": 3.0,
                "alignment": None,
            },
            cost_usd=0.01,
            elapsed_time=2.0,
        )

        res = await agent.run({"voiceover": "Hello", "workflow_run_id": str(uuid.uuid4())})
        assert res.success is True
        assert res.output["has_real_timestamps"] is False
        assert res.output["fallback_used"] is True
