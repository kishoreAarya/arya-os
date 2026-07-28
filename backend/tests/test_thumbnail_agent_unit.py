"""Unit tests for ThumbnailAgent. ExecutionEngine mocked directly —
no real image provider, no GPU, no external API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.thumbnail import ThumbnailAgent, ThumbnailResult
from app.providers.capabilities import Capability
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> ThumbnailAgent:
    agent = ThumbnailAgent(db=AsyncMock())
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_topic():
    agent = ThumbnailAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "topic" in result.error


@pytest.mark.asyncio
async def test_run_success_produces_thumbnail_result():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={"storage_path": "/thumbnails/run1.png"},
            provider="fal",
            cost_usd=0.02,
        )
    )

    result = await agent.run(
        {"topic": "the history of pizza", "style_guide": "bold text"}
    )

    assert result.success is True
    thumbnail_result = result.output["thumbnail_result"]
    assert isinstance(thumbnail_result, ThumbnailResult)
    assert "pizza" in thumbnail_result.prompt
    assert "bold text" in thumbnail_result.prompt
    assert thumbnail_result.storage_path == "/thumbnails/run1.png"


@pytest.mark.asyncio
async def test_run_reflects_current_no_image_adapter_reality():
    agent = ThumbnailAgent(db=AsyncMock())
    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await agent.run({"topic": "cats"})
    assert result.success is False


@pytest.mark.asyncio
async def test_run_uses_image_generation_capability():
    agent = _agent_with_mocked_engine(ExecutionResult(success=True, output={}))
    await agent.run({"topic": "cats"})
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.IMAGE_GENERATION
    assert call_kwargs["stage"] == "thumbnail_generation"
