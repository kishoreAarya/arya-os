"""
Unit tests for TrendAgent (fulfills the ResearchAgent role — see
agents/trend.py's module docstring for why it wasn't renamed).

ExecutionEngine is mocked by replacing the agent's own
`_execution_engine` attribute after construction — no real provider
call, no real database beyond a mocked AsyncSession, no GPU, no
external API.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.trend import ResearchResult, TrendAgent
from app.models.analytics import PerformanceLearningFeedback
from app.services.execution_engine import ExecutionResult


def _mock_db_with_feedback(feedback_rows: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = feedback_rows
    db.execute.return_value = result
    return db


def _agent_with_mocked_engine(db, exec_result: ExecutionResult) -> TrendAgent:
    agent = TrendAgent(db=db)
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_topic():
    agent = TrendAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "topic" in result.error


@pytest.mark.asyncio
async def test_run_success_path_produces_research_result():
    db = _mock_db_with_feedback([])
    agent = _agent_with_mocked_engine(
        db,
        ExecutionResult(
            success=True,
            output="Brief: 3 angles worth covering.",
            provider="openrouter",
            cost_usd=0.001,
        ),
    )

    result = await agent.run({"topic": "the history of pizza"})

    assert result.success is True
    research_result = result.output["research_result"]
    assert isinstance(research_result, ResearchResult)
    assert research_result.topic == "the history of pizza"
    assert research_result.research_brief == "Brief: 3 angles worth covering."
    assert result.provider_used == "openrouter"
    assert result.cost_usd == 0.001


@pytest.mark.asyncio
async def test_run_reads_active_learning_feedback():
    feedback = [
        PerformanceLearningFeedback(
            category="thumbnail", insight="Bright colors get higher CTR", confidence=0.8
        )
    ]
    db = _mock_db_with_feedback(feedback)
    agent = _agent_with_mocked_engine(
        db, ExecutionResult(success=True, output="brief", provider="openrouter")
    )

    result = await agent.run({"topic": "cats"})

    research_result = result.output["research_result"]
    assert "Bright colors get higher CTR" in research_result.learning_feedback_applied


@pytest.mark.asyncio
async def test_run_propagates_execution_engine_failure():
    db = _mock_db_with_feedback([])
    agent = _agent_with_mocked_engine(
        db, ExecutionResult(success=False, error="all providers failed")
    )

    result = await agent.run({"topic": "cats"})

    assert result.success is False
    assert result.error == "all providers failed"


@pytest.mark.asyncio
async def test_run_calls_execution_engine_with_research_stage():
    db = _mock_db_with_feedback([])
    agent = _agent_with_mocked_engine(
        db, ExecutionResult(success=True, output="brief", provider="openrouter")
    )

    await agent.run({"topic": "cats", "workflow_run_id": "abc-123"})

    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["stage"] == "research"
    assert call_kwargs["workflow_run_id"] == "abc-123"
