"""Focused unit tests for the AryaOS V1 Learning Loop Bridge.

Validates Slice 5 implementation:
1. Empty Analytics dataset handled cleanly without errors.
2. One valid Analytics record → LearningAnalyzer invoked and feedback generated.
3. Analyzer result → to_feedback_rows() invoked with expected schema.
4. Feedback rows → SqlAlchemyLearningRepository persisted to database.
5. Multiple Analytics records processed and distinct targets analyzed.
6. Malformed Analytics record does not crash the entire scheduled job.
7. Database save failure on individual feedback row is handled gracefully.
8. TrendAgent feedback consumption read path is fully compatible with persisted feedback.
9. Scheduled job run_learning_update() is importable and executable with zero arguments.
10. Repository exact-match deduplication prevents duplicate active feedback rows on repeat updates.
"""

import datetime
import json
from unittest.mock import patch
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.trend import TrendAgent
from app.database.session import AsyncSessionLocal
from app.models.analytics import Analytics, PerformanceLearningFeedback
from app.models.core import Project, WorkflowRun
from app.models.enums import PublishStatus, WorkflowMode, WorkflowStatus
from app.models.learning import AnalyticsInput, LearningResult
from app.models.media import Video
from app.repositories.learning_repository import SqlAlchemyLearningRepository
from app.services.learning_analyzer import LearningAnalyzer
from app.workers import jobs

TEST_SECRET = "arya_dev_secret_key_change_in_production"

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def setup_api_auth(monkeypatch):
    """Ensure ARYA_API_KEY is configured for authentication checks across all tests."""
    monkeypatch.setenv("ARYA_API_KEY", TEST_SECRET)
    with patch("app.core.secrets.SecretsManager.get", return_value=TEST_SECRET):
        yield


async def provision_video(session: AsyncSession, title: str = "Test Video", topic: str = "AI") -> Video:
    """Provisions valid Project, WorkflowRun, and Video rows to satisfy foreign keys."""
    proj = Project(name=f"test-proj-{uuid.uuid4().hex[:8]}")
    session.add(proj)
    await session.flush()

    run = WorkflowRun(
        project_id=proj.id,
        topic=topic,
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.COMPLETED,
    )
    session.add(run)
    await session.flush()

    video = Video(
        workflow_run_id=run.id,
        title=title,
        publish_status=PublishStatus.PUBLISHED,
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)
    return video


async def test_learning_update_empty_dataset():
    """Verify that an empty Analytics dataset returns zero counts without errors."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        stats = await jobs.run_learning_update(db=session)
        assert stats["records_examined"] == 0
        assert stats["records_analyzed"] == 0
        assert stats["feedback_generated"] == 0
        assert stats["feedback_persisted"] == 0
        assert stats["records_skipped"] == 0
        assert stats["errors"] == 0


async def test_learning_update_one_valid_record():
    """Verify one valid Analytics record is analyzed and produces persisted feedback."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video = await provision_video(session, title="10 AI Tools That Feel Illegal to Know", topic="AI Tools")

        record = Analytics(
            video_id=video.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=2500,
            likes=300,
            comments=40,
            shares=15,
            click_through_rate=0.095,  # Strong CTR (> 0.08) -> Title pattern generated
            average_view_percentage=0.60,  # High retention (> 0.50)
            raw_metadata=json.dumps({
                "title": "10 AI Tools That Feel Illegal to Know",
                "topic": "AI Tools",
                "script_summary": "Fast-paced breakdown of automation tools with visual hooks",
            }),
        )
        session.add(record)
        await session.commit()

        stats = await jobs.run_learning_update(db=session)
        assert stats["records_examined"] == 1
        assert stats["records_analyzed"] == 1
        assert stats["feedback_generated"] >= 1
        assert stats["feedback_persisted"] >= 1
        assert stats["errors"] == 0

        # Verify rows in database
        fb_res = await session.execute(select(PerformanceLearningFeedback))
        feedback_rows = fb_res.scalars().all()
        assert len(feedback_rows) >= 1
        assert any(fb.category in {"title", "topic", "script"} for fb in feedback_rows)
        assert all(fb.is_active is True for fb in feedback_rows)


async def test_learning_update_analyzer_invocation():
    """Verify LearningAnalyzer.analyze is invoked with correct AnalyticsInput."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video = await provision_video(session, title="Test Viral Title", topic="Tech")

        record = Analytics(
            video_id=video.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=1500,
            likes=120,
            click_through_rate=0.085,
            raw_metadata=json.dumps({"title": "Test Viral Title", "topic": "Tech"}),
        )
        session.add(record)
        await session.commit()

        with patch.object(LearningAnalyzer, "analyze", wraps=LearningAnalyzer().analyze) as mock_analyze:
            stats = await jobs.run_learning_update(db=session)
            assert mock_analyze.called
            call_arg = mock_analyze.call_args[0][0]
            assert isinstance(call_arg, AnalyticsInput)
            assert call_arg.views == 1500
            assert call_arg.title == "Test Viral Title"
            assert stats["records_analyzed"] == 1


async def test_learning_update_multiple_records():
    """Verify multiple distinct Analytics records are processed."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        for i in range(3):
            video = await provision_video(session, title=f"Video Title Number {i}", topic=f"Topic-{i}")
            rec = Analytics(
                video_id=video.id,
                platform="youtube",
                snapshot_at=now_utc - datetime.timedelta(hours=i),
                views=1000 * (i + 1),
                likes=100 * (i + 1),
                click_through_rate=0.09,
                raw_metadata=json.dumps({
                    "title": f"Video Title Number {i}",
                    "topic": f"Topic-{i}",
                }),
            )
            session.add(rec)
        await session.commit()

        stats = await jobs.run_learning_update(db=session)
        assert stats["records_examined"] == 3
        assert stats["records_analyzed"] == 3
        assert stats["feedback_persisted"] >= 3
        assert stats["errors"] == 0


async def test_learning_update_malformed_record_does_not_crash():
    """Verify an individual malformed record does not crash the entire scheduled update."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video = await provision_video(session, title="Good Record", topic="Tech")

        valid_rec = Analytics(
            video_id=video.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=1500,
            likes=100,
            click_through_rate=0.09,
            raw_metadata=json.dumps({"title": "Good Record", "topic": "Tech"}),
        )
        # Record with corrupt raw_metadata and no video_id (external post)
        bad_rec = Analytics(
            external_post_id="post_corrupt_123",
            platform="youtube",
            snapshot_at=now_utc - datetime.timedelta(minutes=5),
            views=500,
            raw_metadata="NOT_VALID_JSON{{{",
        )
        session.add_all([valid_rec, bad_rec])
        await session.commit()

        stats = await jobs.run_learning_update(db=session)
        assert stats["records_examined"] == 2
        assert stats["records_analyzed"] == 2
        assert stats["feedback_persisted"] >= 1


async def test_learning_update_db_error_handled():
    """Verify repository persistence failures are safely captured and session restored."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video = await provision_video(session, title="DB Failure Video", topic="AI")

        record = Analytics(
            video_id=video.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=2000,
            click_through_rate=0.09,
            raw_metadata=json.dumps({"title": "DB Failure Video", "topic": "AI"}),
        )
        session.add(record)
        await session.commit()

        with patch.object(SqlAlchemyLearningRepository, "save_feedback", side_effect=RuntimeError("DB Lock")):
            stats = await jobs.run_learning_update(db=session)
            assert stats["records_analyzed"] == 1
            assert stats["feedback_generated"] >= 1
            assert stats["feedback_persisted"] == 0
            assert stats["errors"] >= 1


async def test_trend_agent_reads_persisted_feedback():
    """Verify TrendAgent consumes the feedback rows generated and persisted by the learning update."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video = await provision_video(session, title="Quantum Computing in 60 Seconds", topic="Quantum Computing")

        record = Analytics(
            video_id=video.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=5000,
            likes=400,
            click_through_rate=0.10,
            raw_metadata=json.dumps({
                "title": "Quantum Computing in 60 Seconds",
                "topic": "Quantum Computing",
            }),
        )
        session.add(record)
        await session.commit()

        # Run the learning update to generate feedback
        stats = await jobs.run_learning_update(db=session)
        assert stats["feedback_persisted"] >= 1

        # Now verify TrendAgent._read_learning_feedback() reads it
        agent = TrendAgent(db=session)
        read_fb = await agent._read_learning_feedback()
        assert len(read_fb) >= 1
        assert any("Quantum Computing" in fb.insight or fb.category in {"title", "topic"} for fb in read_fb)
        assert all(fb.is_active is True for fb in read_fb)


async def test_no_duplicate_feedback_on_repeated_runs():
    """Verify repeat runs merge identical insights via based_on_video_count rather than creating duplicate rows."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(PerformanceLearningFeedback))
        await session.execute(delete(Analytics))
        await session.commit()

        video1 = await provision_video(session, title="Standard High CTR Format", topic="Education")
        record = Analytics(
            video_id=video1.id,
            platform="youtube",
            snapshot_at=now_utc,
            views=2000,
            likes=200,
            click_through_rate=0.09,
            raw_metadata=json.dumps({
                "title": "Standard High CTR Format",
                "topic": "Education",
            }),
        )
        session.add(record)
        await session.commit()

        # First run
        stats1 = await jobs.run_learning_update(db=session)
        count1 = (await session.execute(select(PerformanceLearningFeedback))).scalars().all()
        num_rows1 = len(count1)
        assert num_rows1 >= 1

        # Second video producing the exact same title pattern
        video2 = await provision_video(session, title="Standard High CTR Format", topic="Education")
        record2 = Analytics(
            video_id=video2.id,
            platform="youtube",
            snapshot_at=now_utc + datetime.timedelta(hours=1),
            views=3000,
            likes=300,
            click_through_rate=0.09,
            raw_metadata=json.dumps({
                "title": "Standard High CTR Format",
                "topic": "Education",
            }),
        )
        session.add(record2)
        await session.commit()

        stats2 = await jobs.run_learning_update(db=session)
        count2 = (await session.execute(select(PerformanceLearningFeedback))).scalars().all()

        # Row count should not have doubled for the identical title pattern; based_on_video_count should increase
        matching_title_fb = [fb for fb in count2 if fb.category == "title" and "Standard High CTR Format" in fb.insight]
        assert len(matching_title_fb) == 1
        assert matching_title_fb[0].based_on_video_count >= 2


async def test_scheduled_job_callable_with_zero_arguments():
    """Verify run_learning_update() can be called without arguments as registered in APScheduler."""
    # Should run with default AsyncSessionLocal() session and succeed
    stats = await jobs.run_learning_update()
    assert isinstance(stats, dict)
    assert "records_examined" in stats
    assert "feedback_persisted" in stats


async def test_analyzer_result_to_feedback_rows_contract():
    """Verify LearningResult.to_feedback_rows contract perfectly matches SqlAlchemyLearningRepository inputs."""
    analyzer = LearningAnalyzer()
    inp = AnalyticsInput(
        video_id="video-contract-test",
        title="Contract Testing Video Title",
        topic="Contract Testing",
        views=3000,
        likes=250,
        ctr=0.09,
        upload_date=datetime.datetime.now(datetime.timezone.utc),
    )
    result = analyzer.analyze(inp)
    assert isinstance(result, LearningResult)
    rows = result.to_feedback_rows()
    assert len(rows) >= 1
    for r in rows:
        assert "category" in r
        assert "insight" in r
        assert "confidence" in r
        assert "based_on_video_count" in r
        assert "is_active" in r
        assert isinstance(r["category"], str)
        assert isinstance(r["insight"], str)
        assert isinstance(r["confidence"], float)
