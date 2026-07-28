"""
Unit tests for AnalyticsAgent — confirms the "collect" half is
honestly stopped (no PlatformAdapter to fetch from) while the "store"
half is genuinely implemented against the real Analytics model.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from app.agents.analytics import AnalyticsAgent, AnalyticsResult
from app.models.analytics import Analytics


@pytest.mark.asyncio
async def test_run_requires_platform():
    agent = AnalyticsAgent(db=AsyncMock())
    result = await agent.run({"video_id": "v1", "published_content_id": "yt123"})
    assert result.success is False
    assert "platform" in result.error


@pytest.mark.asyncio
async def test_run_requires_video_id():
    agent = AnalyticsAgent(db=AsyncMock())
    result = await agent.run({"platform": "youtube", "published_content_id": "yt123"})
    assert result.success is False
    assert "video_id" in result.error


@pytest.mark.asyncio
async def test_run_requires_published_content_id():
    agent = AnalyticsAgent(db=AsyncMock())
    result = await agent.run({"platform": "youtube", "video_id": "v1"})
    assert result.success is False
    assert "published_content_id" in result.error


@pytest.mark.asyncio
async def test_run_never_succeeds_today_even_with_valid_request():
    """Core claim to verify: a well-formed request still cannot
    collect analytics, because no PlatformAdapter exists to fetch
    from — must never fabricate numbers."""
    agent = AnalyticsAgent(db=AsyncMock())
    result = await agent.run(
        {"platform": "youtube", "video_id": "v1", "published_content_id": "yt123"}
    )
    assert result.success is False
    assert "PlatformAdapter" in result.error


@pytest.mark.asyncio
async def test_fetch_platform_analytics_raises_not_implemented():
    agent = AnalyticsAgent(db=AsyncMock())
    with pytest.raises(NotImplementedError):
        await agent._fetch_platform_analytics("youtube", "yt123")


@pytest.mark.asyncio
async def test_store_snapshot_is_genuinely_implemented_against_real_model():
    """Unlike fetch, _store_snapshot is real, working code — verified
    by actually calling it and checking a real Analytics instance is
    built and persisted via the (mocked) db session."""
    from unittest.mock import MagicMock

    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add() is synchronous, unlike commit()/refresh()
    agent = AnalyticsAgent(db=db)

    data = {
        "snapshot_at": datetime.now(UTC),
        "views": 1000,
        "likes": 50,
        "click_through_rate": 0.045,
    }

    result = await agent._store_snapshot("some-video-id", data)

    assert isinstance(result, Analytics)
    assert result.views == 1000
    assert result.likes == 50
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_analytics_result_dataclass_shape():
    result = AnalyticsResult(video_id="v1")
    assert result.snapshot_stored is False
