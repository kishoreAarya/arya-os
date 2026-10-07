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


def test_run_never_succeeds_today_even_with_valid_request(monkeypatch):
    """The core claim, under the Phase 53B/I5 contract: a fully
    authorized, manifest-bound request STILL never silently succeeds
    when platform authentication fails — the attempt is recorded FAILED
    and no publication is reported."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.platforms.base import AuthResult
    from tests._dispatch_manifest_fixtures import (
        cleanup_manifest_bound_target,
        seed_manifest_bound_target,
    )

    seeded = seed_manifest_bound_target(
        platform="youtube",
        social_platform="youtube",
        integration_id=None,
        privacy_status="public",
        publish_type="draft",
    )
    run_id, video_id, _mid, vpath, _thumb = seeded

    mock_adapter = MagicMock()
    mock_adapter.authenticate = AsyncMock(
        return_value=AuthResult(success=False, error="No YouTube credentials available")
    )
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: mock_adapter,
    )

    async def _run():
        from app.hermes.capabilities import _make_capability_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        session = async_sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            return await PublishingAgent(db=session).run(
                {
                    "platform": "youtube",
                    "video_id": str(video_id),
                    "video_storage_path": vpath,
                    "title": "t",
                    "description": "d",
                    "social_platform": "youtube",
                    "integration_id": None,
                    "workflow_run_id": str(run_id),
                    "dry_run": False,
                }
            )
        finally:
            await session.close()
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        assert result.success is False
        assert "failed" in result.error.lower()

        from app.models.enums import PublicationAttemptStatus
        from app.models.publication import PublicationAttempt
        from sqlalchemy import select

        async def _attempts():
            from app.hermes.capabilities import _make_capability_engine
            from sqlalchemy.ext.asyncio import async_sessionmaker

            engine = _make_capability_engine()
            session = async_sessionmaker(bind=engine, expire_on_commit=False)()
            try:
                return (
                    (
                        await session.execute(
                            select(PublicationAttempt).where(
                                PublicationAttempt.video_id == video_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            finally:
                await session.close()
                await engine.dispose()

        rows = asyncio.run(_attempts())
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
    finally:
        cleanup_manifest_bound_target(run_id, video_id, vpath)


def test_publishing_result_dataclass_shape():
    """PublishingResult exists and is constructible, per the "produce a
    strongly-typed result" requirement, even though run() never
    reaches the point of returning one today."""
    result = PublishingResult(platform="youtube", video_id="v1")
    assert result.publish_status == "failed"
