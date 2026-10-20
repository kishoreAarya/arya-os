"""
Unit and integration tests for Slice 8: Backend UI Contracts & Workflow Execution Readiness.

Covers:
1. Workflow Execution:
   - Asynchronous trigger via POST /workflow-runs/{id}/execute (202 Accepted)
   - Creation with immediate execute flag POST /workflow-runs/?execute=true
   - Duplicate execution protection (409 Conflict on running or completed runs)
   - 404 on nonexistent run execution
   - Polling status and state representation
2. Workflow Artifacts:
   - Direct artifact references in GET /workflow-runs/{id}
   - Safe null/empty representation when artifacts are absent
   - Real artifact lookup (script, video, thumbnail, audio, storyboard, metadata)
3. Learning Feedback Read API:
   - Authentication enforcement (401 without Bearer token)
   - GET /learning/feedback returns active feedback
   - Category filtering and min_confidence filtering
   - Bounded pagination/limit enforcement
   - GET /analytics/learning alias
4. Approval Checkpoint Inspection:
   - Checkpoint retrieval enriches review_content for whitelisted tables
   - Pending checkpoints query includes review_content
   - Decision records successfully and rejects duplicates with 409
   - Authentication enforcement on approval endpoints
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import app
from app.models.analytics import PerformanceLearningFeedback
from app.models.approval import ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.media import Asset, Image, Thumbnail, Video

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ---------------------------------------------------------------------------
# 1. Workflow Run Execution & State Contract Tests
# ---------------------------------------------------------------------------

async def test_execute_workflow_run_endpoint_accepts_and_starts(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/execute returns 202 and initiates asynchronous execution."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Asynchronous execution test",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.PENDING,
        current_stage="created",
    )
    db_session.add(run)
    await db_session.commit()

    with patch("app.api.routers.workflow_runs._run_workflow_background_task", new_callable=AsyncMock) as mock_task:
        resp = await client.post(f"/workflow-runs/{run_id}/execute")
        assert resp.status_code == 202
        data = resp.json()
        assert data["workflow_run_id"] == str(run_id)
        assert data["status"] == "running"
        mock_task.assert_called_once()


async def test_create_workflow_run_with_execute_flag(
    client: httpx.AsyncClient,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/?execute=true creates run and starts execution immediately."""
    with patch("app.api.routers.workflow_runs._run_workflow_background_task", new_callable=AsyncMock) as mock_task:
        resp = await client.post(
            "/workflow-runs/?execute=true",
            json={"project_id": str(test_project), "topic": "Immediate execution test"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "running"
        mock_task.assert_called_once()


async def test_execute_workflow_run_rejects_already_running_or_completed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/execute returns 409 Conflict if already running or completed."""
    run_running = WorkflowRun(
        id=uuid.uuid4(),
        project_id=test_project,
        topic="Already running",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="trend_selected",
    )
    run_completed = WorkflowRun(
        id=uuid.uuid4(),
        project_id=test_project,
        topic="Already completed",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.COMPLETED,
        current_stage="published",
    )
    db_session.add_all([run_running, run_completed])
    await db_session.commit()

    resp_running = await client.post(f"/workflow-runs/{run_running.id}/execute")
    assert resp_running.status_code == 409
    assert "already running" in resp_running.json()["detail"]

    resp_completed = await client.post(f"/workflow-runs/{run_completed.id}/execute")
    assert resp_completed.status_code == 409
    assert "already completed" in resp_completed.json()["detail"]


async def test_execute_workflow_run_404_for_unknown_run(
    client: httpx.AsyncClient,
):
    """POST /workflow-runs/{id}/execute returns 404 for unknown UUID."""
    unknown_id = uuid.uuid4()
    resp = await client.post(f"/workflow-runs/{unknown_id}/execute")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Workflow Artifacts Contract Tests
# ---------------------------------------------------------------------------

async def test_get_workflow_run_exposes_artifacts_when_available(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """GET /workflow-runs/{id} returns populated artifact references without fabricating fake paths."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Artifact test run",
        status=WorkflowStatus.COMPLETED,
        current_stage="published",
    )
    db_session.add(run)
    await db_session.commit()

    script = Script(
        workflow_run_id=run_id,
        content="Welcome to this video on quantum physics!",
        word_count=7,
        validation_notes="Passed validation",
    )
    db_session.add(script)
    await db_session.commit()

    storyboard = Storyboard(
        script_id=script.id,
        shots=[{"shot": 1, "description": "Intro animation"}],
        validation_notes="Passed",
    )
    db_session.add(storyboard)
    await db_session.commit()

    image = Image(
        storyboard_id=storyboard.id,
        storage_path="/storage/images/shot1.png",
        shot_number=1,
        provider_name="flux",
    )
    video = Video(
        workflow_run_id=run_id,
        storage_path="/storage/videos/final.mp4",
        title="Quantum Physics 101",
        description="A primer on quantum mechanics",
        tags="quantum,science,physics",
        duration_seconds=15.0,
        aspect_ratio="16:9",
    )
    thumbnail = Thumbnail(
        workflow_run_id=run_id,
        storage_path="/storage/thumbnails/thumb.jpg",
        provider_name="fal",
    )
    audio = Asset(
        workflow_run_id=run_id,
        asset_type="voice",
        storage_path="/storage/audio/narration.mp3",
        provider_name="elevenlabs",
    )
    db_session.add_all([image, video, thumbnail, audio])
    await db_session.commit()

    try:
        resp = await client.get(f"/workflow-runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["artifacts"] is not None
        artifacts = data["artifacts"]
        assert artifacts["video_path"] == "/storage/videos/final.mp4"
        assert artifacts["thumbnail_path"] == "/storage/thumbnails/thumb.jpg"
        assert artifacts["audio_path"] == "/storage/audio/narration.mp3"
        assert artifacts["script_content"] == "Welcome to this video on quantum physics!"
        assert artifacts["storyboard"] is not None
        assert len(artifacts["storyboard"]["shots"]) == 1
        assert "/storage/images/shot1.png" in artifacts["images"]
        assert artifacts["metadata"]["title"] == "Quantum Physics 101"
    finally:
        await db_session.execute(delete(Image).where(Image.storyboard_id == storyboard.id))
        await db_session.execute(delete(Storyboard).where(Storyboard.id == storyboard.id))
        await db_session.execute(delete(Script).where(Script.id == script.id))
        await db_session.execute(delete(Video).where(Video.workflow_run_id == run_id))
        await db_session.execute(delete(Thumbnail).where(Thumbnail.workflow_run_id == run_id))
        await db_session.execute(delete(Asset).where(Asset.workflow_run_id == run_id))
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db_session.commit()


async def test_get_workflow_run_handles_absent_artifacts_cleanly(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """GET /workflow-runs/{id} returns nulls/empty when artifacts do not exist."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Pending run with no artifacts",
        status=WorkflowStatus.PENDING,
        current_stage="created",
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.get(f"/workflow-runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifacts"] is not None
    assert data["artifacts"]["video_path"] is None
    assert data["artifacts"]["thumbnail_path"] is None
    assert data["artifacts"]["audio_path"] is None
    assert data["artifacts"]["script_content"] is None
    assert data["artifacts"]["storyboard"] is None
    assert data["artifacts"]["images"] == []
    assert data["artifacts"]["metadata"] is None


# ---------------------------------------------------------------------------
# 3. Learning Feedback Read API Contract Tests
# ---------------------------------------------------------------------------

async def test_learning_feedback_requires_authentication(client: httpx.AsyncClient):
    """GET /learning/feedback without API key returns 401 Unauthorized."""
    resp = await client.get("/learning/feedback", headers={"Authorization": ""})
    assert resp.status_code == 401


async def test_learning_feedback_returns_active_records_with_pagination(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """GET /learning/feedback retrieves active patterns, applies category and limit filters."""
    f1 = PerformanceLearningFeedback(
        id=uuid.uuid4(),
        category="script",
        insight="Short hooks under 3 seconds retain 20% more viewers",
        confidence=Decimal("0.850"),
        based_on_video_count=5,
        is_active=True,
    )
    f2 = PerformanceLearningFeedback(
        id=uuid.uuid4(),
        category="thumbnail",
        insight="High contrast borders improve CTR by 4%",
        confidence=Decimal("0.910"),
        based_on_video_count=8,
        is_active=True,
    )
    f3_inactive = PerformanceLearningFeedback(
        id=uuid.uuid4(),
        category="script",
        insight="Old outdated rule",
        confidence=Decimal("0.500"),
        based_on_video_count=1,
        is_active=False,
    )
    db_session.add_all([f1, f2, f3_inactive])
    await db_session.commit()

    try:
        # 1. Fetch all active
        resp = await client.get("/learning/feedback?limit=10")
        assert resp.status_code == 200
        items = resp.json()
        assert any(i["id"] == str(f1.id) for i in items)
        assert any(i["id"] == str(f2.id) for i in items)
        assert not any(i["id"] == str(f3_inactive.id) for i in items)

        # 2. Filter by category
        resp_cat = await client.get("/learning/feedback?category=thumbnail")
        assert resp_cat.status_code == 200
        thumb_items = resp_cat.json()
        assert all(i["category"] == "thumbnail" for i in thumb_items)
        assert any(i["id"] == str(f2.id) for i in thumb_items)

        # 3. Filter by min_confidence
        resp_conf = await client.get("/learning/feedback?min_confidence=0.90")
        assert resp_conf.status_code == 200
        conf_items = resp_conf.json()
        assert all(i["confidence"] >= 0.90 for i in conf_items)

        # 4. Verify alias /analytics/learning
        resp_alias = await client.get("/analytics/learning?category=script")
        assert resp_alias.status_code == 200
        alias_items = resp_alias.json()
        assert any(i["id"] == str(f1.id) for i in alias_items)
    finally:
        await db_session.execute(
            delete(PerformanceLearningFeedback).where(
                PerformanceLearningFeedback.id.in_([f1.id, f2.id, f3_inactive.id])
            )
        )
        await db_session.commit()


# ---------------------------------------------------------------------------
# 4. Approval Checkpoint Inspection & Decision Contract Tests
# ---------------------------------------------------------------------------

async def test_approval_checkpoint_retrieval_enriches_review_content(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """GET /approvals/{id} enriches review_content for scripts, storyboards, images, and videos."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Approval review content test",
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
    )
    db_session.add(run)
    await db_session.commit()

    script = Script(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        content="Script content to be approved by creator.",
        word_count=7,
        validation_notes="Story score: 85",
    )
    db_session.add(script)
    await db_session.commit()

    cp = ApprovalCheckpoint(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=script.id,
    )
    db_session.add(cp)
    await db_session.commit()

    try:
        resp = await client.get(f"/approvals/{cp.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(cp.id)
        assert data["stage"] == "script"
        assert data["action"] is None
        assert data["review_content"] is not None
        assert data["review_content"]["type"] == "script"
        assert data["review_content"]["content"] == "Script content to be approved by creator."
        assert data["review_content"]["word_count"] == 7

        # Also verify pending list includes enriched review_content
        resp_pending = await client.get(f"/approvals/pending/{run_id}")
        assert resp_pending.status_code == 200
        pending_list = resp_pending.json()
        assert len(pending_list) == 1
        assert pending_list[0]["review_content"]["content"] == "Script content to be approved by creator."
    finally:
        await db_session.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
        await db_session.execute(delete(Script).where(Script.workflow_run_id == run_id))
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db_session.commit()


async def test_approval_checkpoint_decision_and_duplicate_conflict(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /approvals/{id}/decide records human decision and returns 409 on duplicate."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Approval decision test",
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
    )
    db_session.add(run)
    await db_session.commit()

    cp = ApprovalCheckpoint(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(cp)
    await db_session.commit()

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock):
            # First decision succeeds
            resp1 = await client.post(
                f"/approvals/{cp.id}/decide",
                json={"action": "approve", "reviewer_notes": "Great script, proceed"},
            )
            assert resp1.status_code == 200
            data1 = resp1.json()
            assert data1["action"] == "approve"
            assert data1["reviewer_notes"] == "Great script, proceed"
            assert data1["decided_at"] is not None

            # Duplicate decision returns 409 Conflict
            resp2 = await client.post(
                f"/approvals/{cp.id}/decide",
                json={"action": "reject", "reviewer_notes": "Duplicate should fail"},
            )
            assert resp2.status_code == 409
            assert "already been decided" in resp2.json()["detail"]
    finally:
        await db_session.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db_session.commit()


async def test_list_all_checkpoints_endpoint(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """GET /approvals/?workflow_run_id=... returns all checkpoints with pagination."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="List checkpoints test",
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
    )
    db_session.add(run)
    await db_session.commit()

    cp1 = ApprovalCheckpoint(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
        action=ApprovalAction.APPROVE,
        decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    cp2 = ApprovalCheckpoint(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        stage=ApprovalStage.IMAGE,
        reference_table="images",
        reference_id=uuid.uuid4(),
        action=None,
    )
    db_session.add_all([cp1, cp2])
    await db_session.commit()

    try:
        resp = await client.get(f"/approvals/?workflow_run_id={run_id}&limit=10")
        assert resp.status_code == 200
        checkpoints = resp.json()
        assert len(checkpoints) == 2
        assert any(c["id"] == str(cp1.id) and c["action"] == "approve" for c in checkpoints)
        assert any(c["id"] == str(cp2.id) and c["action"] is None for c in checkpoints)
    finally:
        await db_session.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db_session.commit()
