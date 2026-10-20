"""Unit tests for ScriptAgent and prompt builder research data handling.

Verifies:
- TrendSignal dicts (topic, search_volume_or_signal / signal) format into script prompts correctly.
- Legacy format (title, summary) continues to format correctly.
- Direct TrendSignal instances format correctly.
- Research brief is incorporated when provided.
- Malformed, empty, or None research data does not generate empty "- : " bullets.
- ScriptAgent.run forwards research_data, trend_signals fallback, and research_brief.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agents.script import ScriptAgent, _build_script_prompt
from app.services.trend_sources.base import TrendSignal


def test_build_script_prompt_with_trend_signal_dict():
    """Verify TrendSignal.to_dict() data renders meaningful bullets, never '- : '."""
    signal = TrendSignal(
        topic="AI video generation",
        search_volume_or_signal="15,000 upvotes, 320 comments",
        relevance=0.92,
        freshness="2026-09-25T00:00:00Z",
        source="reddit",
        competition="high",
        confidence=0.88,
    )
    research_data = [signal.to_dict()]

    prompt = _build_script_prompt(
        topic="AI video generation",
        research_data=research_data,
        target_duration=30,
    )

    assert "- AI video generation: 15,000 upvotes, 320 comments" in prompt
    assert "- : " not in prompt
    assert "- :" not in prompt


def test_build_script_prompt_with_legacy_title_summary():
    """Verify backwards-compatibility with legacy {'title': ..., 'summary': ...}."""
    research_data = [
        {"title": "OpenAI Sora", "summary": "Breakthrough in generative video"}
    ]
    prompt = _build_script_prompt(
        topic="Video Tech",
        research_data=research_data,
    )

    assert "- OpenAI Sora: Breakthrough in generative video" in prompt
    assert "- : " not in prompt


def test_build_script_prompt_with_direct_trend_signal_instance():
    """Verify raw TrendSignal dataclass instances are safely consumed."""
    signal = TrendSignal(
        topic="Autonomous Coding",
        search_volume_or_signal="8,500 stars this week",
        relevance=0.95,
        freshness="2026-09-25T00:00:00Z",
        source="github_trends",
    )
    prompt = _build_script_prompt(
        topic="Autonomous Coding",
        research_data=[signal],
    )

    assert "- Autonomous Coding: 8,500 stars this week" in prompt
    assert "- : " not in prompt


def test_build_script_prompt_with_research_brief():
    """Verify research_brief is included in prompt when provided."""
    prompt = _build_script_prompt(
        topic="Space Mining",
        research_data=None,
        research_brief="Key angles: asteroid composition, cost per kg, legal ownership.",
    )

    assert "Research brief:" in prompt
    assert "Key angles: asteroid composition, cost per kg, legal ownership." in prompt
    assert "- : " not in prompt


def test_build_script_prompt_empty_and_malformed_safety():
    """Verify empty dicts, empty strings, and None values do not emit '- : '."""
    malformed_data = [
        {},
        {"topic": "", "search_volume_or_signal": ""},
        {"title": "   ", "summary": None},
        {"metadata": {}},
    ]
    prompt = _build_script_prompt(
        topic="Ocean Depths",
        research_data=malformed_data,
        research_brief=None,
    )

    assert "- : " not in prompt
    assert "- :" not in prompt
    assert "Use these researched facts/angles where relevant:" not in prompt


def test_build_script_prompt_none_research():
    """Verify None research_data produces clean prompt without bullets."""
    prompt = _build_script_prompt(
        topic="Ocean Depths",
        research_data=None,
        target_duration=15,
    )

    assert "Write a complete video script about: Ocean Depths" in prompt
    assert "Use these researched facts/angles where relevant:" not in prompt
    assert "- : " not in prompt


@pytest.mark.asyncio
async def test_script_agent_run_forwards_research_data_and_brief():
    """Verify ScriptAgent.run forwards research_data, fallback to trend_signals, and brief to prompt."""
    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    mock_exec_res = MagicMock()
    mock_exec_res.success = True
    mock_exec_res.output = "Here is the final generated narration."
    mock_exec_res.cost_usd = 0.002
    mock_exec_res.provider = "openrouter"
    mock_exec_res.elapsed_time = 1.1

    executed_calls: list = []

    async def fake_execute(*args, **kwargs):
        call_obj = kwargs.get("call")
        executed_calls.append(call_obj)
        return mock_exec_res

    from app.providers.text_dispatch import build_text_generation_call

    with (
        patch.object(agent._execution_engine, "execute", side_effect=fake_execute),
        patch("app.agents.script.build_text_generation_call", side_effect=build_text_generation_call) as mock_build_call,
    ):
        signal = TrendSignal(
            topic="Reddit AI Trends",
            search_volume_or_signal="12,000 upvotes",
            relevance=0.9,
            freshness="2026-09-25",
        )
        context = {
            "topic": "Reddit AI Trends",
            "trend_signals": [signal.to_dict()],  # tests trend_signals fallback
            "research_brief": "Core angle: prompt engineering is evolving into autonomous agent workflows.",
            "duration": 30,
        }
        res = await agent.run(context)

        assert res.success is True
        assert res.output["script"] == "Here is the final generated narration."
        assert len(executed_calls) == 1
        assert mock_build_call.call_count == 1

        actual_prompt = mock_build_call.call_args[0][0]
        assert "- Reddit AI Trends: 12,000 upvotes" in actual_prompt
        assert "Core angle: prompt engineering is evolving into autonomous agent workflows." in actual_prompt
        assert "- : " not in actual_prompt


@pytest.mark.asyncio
async def test_script_agent_passes_story_validator_name_to_engine():
    """Verify ScriptAgent explicitly configures validator_name='story' on execution."""
    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    captured_kwargs: dict = {}

    async def fake_execute(*args, **kwargs):
        captured_kwargs.update(kwargs)
        res = MagicMock()
        res.success = True
        res.output = "Valid script content that exceeds fifty characters easily for validation."
        res.cost_usd = 0.001
        res.provider = "openrouter"
        res.elapsed_time = 0.5
        res.context = MagicMock()
        res.context.validation_result = MagicMock(passed=True, score=85.0)
        return res

    with patch.object(agent._execution_engine, "execute", side_effect=fake_execute):
        res = await agent.run({"topic": "AI Agents"})

        assert res.success is True
        assert captured_kwargs.get("validator_name") == "story"
        assert res.output.get("quality_score") == 85.0
        assert res.output.get("validation_result") is not None


@pytest.mark.asyncio
async def test_script_agent_with_execution_engine_validation_success():
    """End-to-end test of ScriptAgent + ExecutionEngine + StoryValidator on passing script."""
    from app.providers.router import RouterResult

    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    good_script = (
        "Why does everybody get pasta wrong? The secret isn't more salt—it's boiling water timing!\n\n"
        "In fact, Italian chefs have known this rule for generations. When you drop fresh noodles "
        "into gently simmering broth instead of violent bubbles, the starch forms a silky glaze. "
        "For example, traditional carbonara relies entirely on this emulsion technique.\n\n"
        "What do you think about this cooking secret? Leave a comment below and subscribe for part 2!"
    )

    async def fake_router(*args, **kwargs):
        return RouterResult(
            output=good_script,
            provider_used="openrouter",
            attempts=["openrouter"],
            cost_usd=0.001,
            duration_seconds=0.5,
        )

    with patch("app.services.execution_engine.call_with_fallback", side_effect=fake_router):
        res = await agent.run({"topic": "Pasta cooking secret"})

        assert res.success is True
        assert res.output["script"] == good_script
        assert res.output["quality_score"] >= 70.0
        assert res.output["validation_result"].passed is True


@pytest.mark.asyncio
async def test_script_agent_with_execution_engine_validation_failure_too_short():
    """End-to-end test of ScriptAgent + ExecutionEngine + StoryValidator rejecting short script."""
    from app.providers.router import RouterResult

    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    short_script = "Too short to pass."

    async def fake_router(*args, **kwargs):
        return RouterResult(
            output=short_script,
            provider_used="openrouter",
            attempts=["openrouter"],
            cost_usd=0.001,
            duration_seconds=0.2,
        )

    with patch("app.services.execution_engine.call_with_fallback", side_effect=fake_router):
        res = await agent.run({"topic": "Space"})

        assert res.success is False
        assert "Validation 'story' failed" in res.error
        assert "too short to evaluate" in res.error


@pytest.mark.asyncio
async def test_script_agent_with_execution_engine_validation_failure_empty():
    """End-to-end test of ScriptAgent + ExecutionEngine + StoryValidator rejecting empty script."""
    from app.providers.router import RouterResult

    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    async def fake_router(*args, **kwargs):
        return RouterResult(
            output="",
            provider_used="openrouter",
            attempts=["openrouter"],
            cost_usd=0.001,
            duration_seconds=0.1,
        )

    with patch("app.services.execution_engine.call_with_fallback", side_effect=fake_router):
        res = await agent.run({"topic": "Space"})

        assert res.success is False
        assert "Validation 'story' failed" in res.error
        assert "Script content is empty" in res.error


@pytest.mark.asyncio
async def test_script_agent_with_execution_engine_validation_failure_repetition():
    """End-to-end test of ScriptAgent + ExecutionEngine + StoryValidator rejecting excessive repetition."""
    from app.providers.router import RouterResult

    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    repetitive_script = "pizza " * 40

    async def fake_router(*args, **kwargs):
        return RouterResult(
            output=repetitive_script,
            provider_used="openrouter",
            attempts=["openrouter"],
            cost_usd=0.001,
            duration_seconds=0.4,
        )

    with patch("app.services.execution_engine.call_with_fallback", side_effect=fake_router):
        res = await agent.run({"topic": "Pizza"})

        assert res.success is False
        assert "Validation 'story' failed" in res.error
        assert "Excessive word repetition" in res.error
