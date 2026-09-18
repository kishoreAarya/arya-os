"""Unit tests for MetadataAgent.

ExecutionEngine is mocked directly — no external LLM APIs, no live network calls.
"""
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from app.agents.metadata import MetadataAgent, MetadataResult
from app.providers.capabilities import Capability
from app.services.execution_engine import ExecutionResult


def _agent_with_mocked_engine(exec_result: ExecutionResult) -> MetadataAgent:
    db = AsyncMock()
    agent = MetadataAgent(db=db)
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(return_value=exec_result)
    return agent


@pytest.mark.asyncio
async def test_run_requires_script_content_or_topic():
    agent = MetadataAgent(db=AsyncMock())
    result = await agent.run({})
    assert result.success is False
    assert "context.script_content or context.topic is required" in result.error


@pytest.mark.asyncio
async def test_run_success_path_produces_metadata_result():
    sample_json = {
        "title": "Why Coffee Keeps You Awake: The Biology of Caffeine",
        "description": "Ever wondered why coffee stops tiredness? In this video, we explore how caffeine blocks adenosine receptors in the human brain. Subscribe for daily science breakdowns!",
        "tags": ["caffeine", "coffee science", "biology", "brain chemistry", "adenosine", "health"],
        "hashtags": ["#Coffee", "#Science", "#Health"],
        "category": "Science & Technology",
    }
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output=sample_json,
            provider="openrouter",
            cost_usd=0.003,
        )
    )

    result = await agent.run({
        "script_content": "Why does coffee keep you awake? The secret lies in a molecule called adenosine...",
        "topic": "caffeine science",
    })

    assert result.success is True
    assert result.provider_used == "openrouter"
    assert result.cost_usd == 0.003

    # Check top-level output fields for downstream PublishingAgent
    assert result.output["title"] == "Why Coffee Keeps You Awake: The Biology of Caffeine"
    assert "adenosine receptors" in result.output["description"]
    assert "caffeine" in result.output["tags"]
    assert result.output["category"] == "Science & Technology"
    assert "#Coffee" in result.output["hashtags"]

    # Check strongly-typed MetadataResult
    meta_res = result.output["metadata_result"]
    assert isinstance(meta_res, MetadataResult)
    assert meta_res.title == result.output["title"]
    assert meta_res.character_count_title == len(meta_res.title)
    assert meta_res.character_count_description == len(meta_res.description)


@pytest.mark.asyncio
async def test_run_propagates_execution_engine_failure():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=False,
            error="All providers for 'text_generation' failed",
        )
    )

    result = await agent.run({
        "script_content": "Test script content here.",
        "topic": "test topic",
    })

    assert result.success is False
    assert "All providers" in result.error


@pytest.mark.asyncio
async def test_run_updates_video_db_row():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    agent = MetadataAgent(db=db)
    agent._execution_engine = MagicMock()
    agent._execution_engine.execute = AsyncMock(
        return_value=ExecutionResult(
            success=True,
            output={
                "title": "Quantum Physics Made Simple",
                "description": "An introduction to quantum physics and wave-particle duality for curious minds. Subscribe for more!",
                "tags": ["quantum", "physics", "science"],
                "hashtags": ["#Quantum", "#Physics"],
                "category": "Science & Technology",
            },
            provider="openai",
        )
    )

    fake_video_id = uuid.uuid4()
    result = await agent.run({
        "script_content": "Today we explore quantum physics.",
        "topic": "quantum physics",
        "video_id": fake_video_id,
    })

    assert result.success is True
    assert db.execute.called
    assert db.commit.called


@pytest.mark.asyncio
async def test_run_sanitizes_unclean_llm_output():
    # Model returns quotes in title, title over 100 chars, category alias
    long_raw_title = '"' + "The Ultimate Comprehensive Guide To Ancient Roman Architecture And Aqueducts Around The World In History" * 2 + '"'
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={
                "title": long_raw_title,
                "description": "",  # Empty description fallback
                "tags": ["rome", "rome", "rome", "aqueducts"],  # Duplicates
                "hashtags": [],  # Missing hashtags
                "category": "history",  # Alias
            },
            provider="gemini",
        )
    )

    result = await agent.run({
        "script_content": "Rome was famous for engineering aqueducts.",
        "topic": "Roman aqueducts",
    })

    assert result.success is True
    # Title truncated to <= 100 and stripped of quotes
    assert len(result.output["title"]) <= 100
    assert not result.output["title"].startswith('"')
    # Description fallback populated
    assert len(result.output["description"]) >= 30
    assert "Subscribe" in result.output["description"]
    # Tags deduplicated
    tags_list = result.output["tags_list"]
    assert len(tags_list) == len(set(tags_list))
    # Hashtags fallback generated
    assert len(result.output["hashtags"]) >= 2
    assert all(h.startswith("#") for h in result.output["hashtags"])


@pytest.mark.asyncio
async def test_run_uses_text_generation_capability_and_metadata_stage():
    agent = _agent_with_mocked_engine(
        ExecutionResult(
            success=True,
            output={
                "title": "Title",
                "description": "Description with more than thirty characters.",
                "tags": ["tag1", "tag2", "tag3"],
                "hashtags": ["#tag1", "#tag2"],
                "category": "Education",
            },
        )
    )

    wf_id = uuid.uuid4()
    await agent.run({
        "script_content": "Narration content.",
        "topic": "Robotics",
        "workflow_run_id": wf_id,
    })

    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.TEXT_GENERATION
    assert call_kwargs["stage"] == "metadata_generation"
    assert call_kwargs["validator_name"] == "metadata"
    assert call_kwargs["workflow_run_id"] == wf_id
