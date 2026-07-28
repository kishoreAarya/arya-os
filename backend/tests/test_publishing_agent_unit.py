"""
Unit tests for PublishingAgent — confirms the "stopped, not invented"
claim in agents/publishing.py's module docstring is actually true in
code, not just asserted in a comment. No PlatformAdapter is mocked
here because none exists to mock.
"""

from unittest.mock import AsyncMock

import pytest
from app.agents.publishing import PublishingAgent, PublishingResult


@pytest.mark.asyncio
async def test_run_requires_platform():
    agent = PublishingAgent(db=AsyncMock())
    result = await agent.run({"video_id": "v1", "video_storage_path": "/videos/v1.mp4"})
    assert result.success is False
    assert "platform" in result.error


@pytest.mark.asyncio
async def test_run_requires_video_id():
    agent = PublishingAgent(db=AsyncMock())
    result = await agent.run(
        {"platform": "youtube", "video_storage_path": "/videos/v1.mp4"}
    )
    assert result.success is False
    assert "video_id" in result.error


@pytest.mark.asyncio
async def test_run_requires_video_storage_path():
    agent = PublishingAgent(db=AsyncMock())
    result = await agent.run({"platform": "youtube", "video_id": "v1"})
    assert result.success is False
    assert "video_storage_path" in result.error


@pytest.mark.asyncio
async def test_run_reports_all_missing_fields_at_once():
    agent = PublishingAgent(db=AsyncMock())
    result = await agent.run({})
    assert "platform" in result.error
    assert "video_id" in result.error
    assert "video_storage_path" in result.error


@pytest.mark.asyncio
async def test_run_never_succeeds_today_even_with_valid_request():
    """This is the core claim to verify: a WELL-FORMED request still
    cannot publish, because no PlatformAdapter exists — this must
    never silently succeed."""
    agent = PublishingAgent(db=AsyncMock())
    result = await agent.run(
        {
            "platform": "youtube",
            "video_id": "v1",
            "video_storage_path": "/videos/v1.mp4",
        }
    )
    assert result.success is False
    assert "PlatformAdapter" in result.error


def test_publishing_result_dataclass_shape():
    """PublishingResult exists and is constructible, per the "produce a
    strongly-typed result" requirement, even though run() never
    reaches the point of returning one today."""
    result = PublishingResult(platform="youtube", video_id="v1")
    assert result.publish_status == "failed"
