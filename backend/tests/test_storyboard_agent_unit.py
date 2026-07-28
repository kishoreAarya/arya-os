"""Unit tests for StoryboardAgent. ExecutionEngine mocked directly on
the instance — no real provider, database, GPU, or external API."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.storyboard import Shot, StoryboardAgent, StoryboardResult
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> StoryboardAgent:
    agent = StoryboardAgent(db=AsyncMock())
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_script_content():
    agent = StoryboardAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "script_content" in result.error


@pytest.mark.asyncio
async def test_run_success_parses_shots():
    raw_shots = (
        "1. [wide] Establishing shot of a pizzeria\n2. [close-up] Dough being kneaded"
    )
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True, output=raw_shots, provider="openrouter", cost_usd=0.002
        )
    )

    result = await agent.run(
        {"script_content": "Pizza has a long history...", "script_id": "s1"}
    )

    assert result.success is True
    storyboard_result = result.output["storyboard_result"]
    assert isinstance(storyboard_result, StoryboardResult)
    assert storyboard_result.script_id == "s1"
    assert len(storyboard_result.shots) == 2
    assert all(isinstance(s, Shot) for s in storyboard_result.shots)


@pytest.mark.asyncio
async def test_run_propagates_execution_engine_failure():
    agent = _agent_with_mocked_engine(
        ExecutionResult(success=False, error="provider down")
    )
    result = await agent.run({"script_content": "some script"})
    assert result.success is False
    assert result.error == "provider down"


@pytest.mark.asyncio
async def test_run_uses_storyboard_stage():
    agent = _agent_with_mocked_engine(ExecutionResult(success=True, output="1. a shot"))
    await agent.run({"script_content": "some script"})
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["stage"] == "storyboard"


@pytest.mark.asyncio
async def test_parse_shots_skips_blank_lines():
    from app.agents.storyboard import _parse_shots

    shots = _parse_shots("1. first\n\n2. second\n   \n3. third")
    assert len(shots) == 3
