"""Unit tests for ImageAgent. ExecutionEngine mocked directly — no
real image provider, no GPU, no external API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.image import ImageAgent, ImageResult
from app.providers.capabilities import Capability
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> ImageAgent:
    agent = ImageAgent(db=AsyncMock())
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_shot_description():
    agent = ImageAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "shot_description" in result.error


@pytest.mark.asyncio
async def test_run_success_produces_image_result():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={"storage_path": "/images/shot1.png"},
            provider="fal",
            cost_usd=0.02,
        )
    )

    result = await agent.run(
        {
            "shot_description": "a wide shot of a pizzeria",
            "shot_number": 1,
            "style_guide": "cinematic",
        }
    )

    assert result.success is True
    image_result = result.output["image_result"]
    assert isinstance(image_result, ImageResult)
    assert image_result.shot_number == 1
    assert "cinematic" in image_result.prompt
    assert image_result.storage_path == "/images/shot1.png"


@pytest.mark.asyncio
async def test_run_reflects_current_no_image_adapter_reality():
    agent = ImageAgent(db=AsyncMock())
    with patch("app.services.execution_engine.asyncio.sleep", new=AsyncMock()):
        result = await agent.run({"shot_description": "a shot"})
    assert result.success is False


@pytest.mark.asyncio
async def test_run_uses_image_generation_capability():
    agent = _agent_with_mocked_engine(ExecutionResult(success=True, output={}))
    await agent.run({"shot_description": "a shot"})
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.IMAGE_GENERATION
    assert call_kwargs["stage"] == "image_generation"
