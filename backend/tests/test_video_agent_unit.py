"""Unit tests for VideoAgent. ExecutionEngine mocked directly — no
real video provider, no GPU, no external API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.video import VideoAgent, VideoResult
from app.providers.capabilities import Capability
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> VideoAgent:
    agent = VideoAgent(db=AsyncMock())
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_source_image_path():
    agent = VideoAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "source_image_path" in result.error


@pytest.mark.asyncio
async def test_run_success_produces_video_result():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={"storage_path": "/clips/shot1.mp4", "duration_seconds": 5.2},
            provider="fal",
            cost_usd=0.05,
        )
    )

    result = await agent.run(
        {
            "source_image_path": "/images/shot1.png",
            "shot_number": 1,
            "target_duration_seconds": 5.0,
        }
    )

    assert result.success is True
    video_result = result.output["video_result"]
    assert isinstance(video_result, VideoResult)
    assert video_result.source_image_path == "/images/shot1.png"
    assert video_result.storage_path == "/clips/shot1.mp4"
    assert video_result.duration_seconds == 5.2


@pytest.mark.asyncio
async def test_run_reflects_current_no_video_adapter_reality():
    agent = VideoAgent(db=AsyncMock())
    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await agent.run({"source_image_path": "/images/shot1.png"})
    assert result.success is False


@pytest.mark.asyncio
async def test_run_uses_video_generation_capability():
    agent = _agent_with_mocked_engine(ExecutionResult(success=True, output={}))
    await agent.run({"source_image_path": "/images/shot1.png"})
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.VIDEO_GENERATION
    assert call_kwargs["stage"] == "video_generation"
