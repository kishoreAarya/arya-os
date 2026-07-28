"""Unit tests for VoiceAgent. ExecutionEngine mocked directly — no
real TTS provider, no GPU, no external API."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.voice import VoiceAgent, VoiceResult
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> VoiceAgent:
    agent = VoiceAgent(db=AsyncMock())
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_script_content():
    agent = VoiceAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "script_content" in result.error


@pytest.mark.asyncio
async def test_run_success_produces_voice_result():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={"storage_path": "/audio/run1.mp3", "duration_seconds": 42.5},
            provider="openai",
            cost_usd=0.01,
        )
    )

    result = await agent.run(
        {
            "script_content": "narration text",
            "script_id": "s1",
            "voice_profile": "warm-male",
        }
    )

    assert result.success is True
    voice_result = result.output["voice_result"]
    assert isinstance(voice_result, VoiceResult)
    assert voice_result.storage_path == "/audio/run1.mp3"
    assert voice_result.duration_seconds == 42.5
    assert voice_result.voice_profile == "warm-male"


@pytest.mark.asyncio
async def test_run_reflects_current_no_tts_adapter_reality():
    """Documents the real, current state: with the REAL ExecutionEngine
    (not mocked), this fails today because no TTS adapter exists yet —
    confirmed by not mocking ExecutionEngine at all. asyncio.sleep is
    patched only to avoid real retry-backoff delay slowing the test;
    nothing about the failure itself is mocked."""
    from unittest.mock import patch

    agent = VoiceAgent(db=AsyncMock())
    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await agent.run({"script_content": "narration text"})
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_run_uses_tts_capability_and_voice_stage():
    from app.providers.capabilities import Capability

    agent = _agent_with_mocked_engine(ExecutionResult(success=True, output={}))
    await agent.run({"script_content": "narration text"})
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.TTS
    assert call_kwargs["stage"] == "voice_generation"
