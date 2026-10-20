"""Unit and integration tests for Slice 10: Durable Workflow Execution & Approval Resume Foundation.

Validates:
1. Persistent Execution Lease & Heartbeat Management:
   - Database schema persistence of worker_id, execution_attempt, last_heartbeat_at, last_completed_stage, waiting_checkpoint_id.
   - Heartbeat updates during active execution.
   - Lease stale detection (timeout expiration, missing heartbeats, non-running states).
   - Exclusive lease claiming with row-level locking (409 Conflict on active leases).
   - Stale lease recovery and execution attempt incrementing.
   - Completed run execution protection (409 Conflict).
2. Clean Approval Suspension & Resumption:
   - Clean suspension at approval boundaries (AWAITING_APPROVAL, cleared worker_id, checkpoint tracking).
   - Non-blocking suspension (no in-memory while loops or sleep polling).
   - Human approval decision hooks (APPROVE triggers resume; REJECT sets FAILED).
   - Context hydration from persistent database artifacts (Script, Storyboard, Video, Thumbnail).
   - Next-stage determination avoiding duplicate execution and re-billing.
3. API Endpoints:
   - GET /workflow-runs/{id} returns lease fields and computed is_stale.
   - POST /workflow-runs/{id}/recover reclaims stale runs; rejects active leases with 409.
   - POST /workflow-runs/{id}/resume explicitly continues suspended runs; rejects completed/active runs with 409.
   - POST /approvals/{checkpoint_id}/decide updates checkpoint and orchestrates run state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, PipelineStage, PublishStatus, WorkflowMode, WorkflowStatus
from app.models.media import Video, Thumbnail
from app.models.system import SystemLog
from app.schemas.workflow_run import WorkflowRunRecoverResponse, WorkflowRunResumeResponse
from app.services.workflow_execution_service import (
    WorkflowExecutionConflictError,
    claim_execution_lease,
    determine_next_stage,
    hydrate_resume_context,
    is_lease_stale,
    recover_workflow_run,
    suspend_for_approval,
    update_heartbeat,
)
from app.workflows.models import StageResult, WorkflowResult
from app.workflows.orchestrator import Orchestrator, _PIPELINE, _CINEMATIC_PIPELINE

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def cleanup_run(db: AsyncSession, run_id: uuid.UUID) -> None:
    """Helper to clean up a workflow run and all related cascading entities."""
    await db.execute(delete(SystemLog).where(SystemLog.workflow_run_id == run_id))
    await db.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
    await db.execute(delete(Thumbnail).where(Thumbnail.workflow_run_id == run_id))
    await db.execute(delete(Video).where(Video.workflow_run_id == run_id))
    scripts = (await db.execute(select(Script.id).where(Script.workflow_run_id == run_id))).scalars().all()
    for s_id in scripts:
        await db.execute(delete(Storyboard).where(Storyboard.script_id == s_id))
    await db.execute(delete(Script).where(Script.workflow_run_id == run_id))
    await db.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
    await db.commit()


# ---------------------------------------------------------------------------
# 1. Lease, Heartbeat, and Recovery Unit Tests
# ---------------------------------------------------------------------------

async def test_workflow_execution_state_persistence(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify new durable execution columns are written, committed, and queryable."""
    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Durable Lease Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
        last_completed_stage="script",
        execution_started_at=now,
        last_heartbeat_at=now,
        execution_attempt=2,
        worker_id="worker-proc-9999",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed is not None
        assert refreshed.last_completed_stage == "script"
        assert refreshed.execution_started_at == now
        assert refreshed.last_heartbeat_at == now
        assert refreshed.execution_attempt == 2
        assert refreshed.worker_id == "worker-proc-9999"
        assert refreshed.waiting_checkpoint_id is None
    finally:
        await cleanup_run(db_session, run_id)


async def test_heartbeat_updates(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify update_heartbeat updates last_heartbeat_at and worker_id for running workflows."""
    run_id = uuid.uuid4()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Heartbeat Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
        last_heartbeat_at=past,
        worker_id=None,
    )
    db_session.add(run)
    await db_session.commit()

    try:
        await update_heartbeat(db_session, run_id, worker_id="worker-proc-2222")
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed is not None
        assert refreshed.worker_id == "worker-proc-2222"
        assert refreshed.last_heartbeat_at > past
    finally:
        await cleanup_run(db_session, run_id)


async def test_lease_stale_detection():
    """Verify is_lease_stale evaluates timeout, missing heartbeats, and non-running statuses."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=10)).replace(tzinfo=None)
    stale_time = (now - timedelta(seconds=400)).replace(tzinfo=None)

    # 1. Non-running is never considered an active stale lease
    pending_run = WorkflowRun(status=WorkflowStatus.PENDING, last_heartbeat_at=stale_time)
    assert is_lease_stale(pending_run, timeout_seconds=300) is False

    completed_run = WorkflowRun(status=WorkflowStatus.COMPLETED, last_heartbeat_at=stale_time)
    assert is_lease_stale(completed_run, timeout_seconds=300) is False

    awaiting_run = WorkflowRun(status=WorkflowStatus.AWAITING_APPROVAL, last_heartbeat_at=stale_time)
    assert is_lease_stale(awaiting_run, timeout_seconds=300) is False

    # 2. Running without heartbeat is immediately stale
    no_hb_run = WorkflowRun(status=WorkflowStatus.RUNNING, last_heartbeat_at=None)
    assert is_lease_stale(no_hb_run, timeout_seconds=300) is True

    # 3. Running with expired heartbeat is stale
    expired_run = WorkflowRun(status=WorkflowStatus.RUNNING, last_heartbeat_at=stale_time)
    assert is_lease_stale(expired_run, timeout_seconds=300) is True

    # 4. Running with fresh heartbeat is active (not stale)
    active_run = WorkflowRun(status=WorkflowStatus.RUNNING, last_heartbeat_at=recent)
    assert is_lease_stale(active_run, timeout_seconds=300) is False


async def test_active_lease_claim_conflict(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify claim_execution_lease raises WorkflowExecutionConflictError if lease is actively held."""
    run_id = uuid.uuid4()
    recent = datetime.now(timezone.utc).replace(tzinfo=None)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Active Lease Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
        last_heartbeat_at=recent,
        worker_id="worker-proc-primary",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        with pytest.raises(WorkflowExecutionConflictError) as exc_info:
            await claim_execution_lease(db_session, run_id, worker_id="worker-proc-secondary", timeout_seconds=300)
        assert "actively executing" in str(exc_info.value)
    finally:
        await cleanup_run(db_session, run_id)


async def test_completed_run_lease_claim_conflict(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify claim_execution_lease raises WorkflowExecutionConflictError if run already completed."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Completed Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="published",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        with pytest.raises(WorkflowExecutionConflictError) as exc_info:
            await claim_execution_lease(db_session, run_id, worker_id="worker-proc-any")
        assert "already completed" in str(exc_info.value)
    finally:
        await cleanup_run(db_session, run_id)


async def test_stale_lease_recovery(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify recover_workflow_run successfully reclaims lease on stale run and increments attempt."""
    run_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Stale Orphaned Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
        last_completed_stage="script",
        last_heartbeat_at=stale_time,
        worker_id="worker-crashed-old",
        execution_attempt=1,
    )
    db_session.add(run)
    await db_session.commit()

    try:
        recovered_run, next_stage = await recover_workflow_run(
            db=db_session,
            run_id=run_id,
            worker_id="worker-recovered-new",
            timeout_seconds=300,
        )
        assert recovered_run.worker_id == "worker-recovered-new"
        assert recovered_run.execution_attempt == 2
        assert recovered_run.status == WorkflowStatus.RUNNING
        assert next_stage == "storyboard"
    finally:
        await cleanup_run(db_session, run_id)


# ---------------------------------------------------------------------------
# 2. Approval Suspension & Resume Foundation Tests
# ---------------------------------------------------------------------------

async def test_waiting_for_approval_entry(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify suspend_for_approval sets AWAITING_APPROVAL, clears worker lease, and records checkpoint."""
    run_id = uuid.uuid4()
    cp_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Suspend Test Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
        worker_id="worker-proc-active",
    )
    db_session.add(run)
    await db_session.commit()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(checkpoint)
    await db_session.commit()

    try:
        suspended = await suspend_for_approval(db_session, run_id, cp_id)
        assert suspended.status == WorkflowStatus.AWAITING_APPROVAL
        assert suspended.waiting_checkpoint_id == cp_id
        assert suspended.worker_id is None
    finally:
        await cleanup_run(db_session, run_id)


async def test_determine_next_stage():
    """Verify determine_next_stage selects correct subsequent stage for both standard and cinematic pipelines."""
    # Standard pipeline progression
    assert determine_next_stage(None, PipelineStage.CREATED.value) == "trend"
    assert determine_next_stage(None, PipelineStage.TREND_SELECTED.value) == "script"
    assert determine_next_stage("script", PipelineStage.SCRIPT_GENERATED.value) == "storyboard"
    assert determine_next_stage("storyboard", PipelineStage.STORYBOARD_GENERATED.value) == "shot_executor"
    assert determine_next_stage("video_assembler", PipelineStage.VIDEO_GENERATED.value) == "thumbnail"
    assert determine_next_stage("analytics", PipelineStage.ANALYTICS_COLLECTED.value) == "analytics"

    # Cinematic pipeline progression
    assert determine_next_stage(None, PipelineStage.SCRIPT_GENERATED.value, pipeline=_CINEMATIC_PIPELINE) == "voice"
    assert determine_next_stage("script", None, pipeline=_CINEMATIC_PIPELINE) == "voice"
    assert determine_next_stage("voice", None, pipeline=_CINEMATIC_PIPELINE) == "storyboard"


async def test_hydrate_resume_context(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify hydrate_resume_context populates context from DB artifacts without regeneration."""
    run_id = uuid.uuid4()
    script_id = uuid.uuid4()
    sb_id = uuid.uuid4()
    vid_id = uuid.uuid4()
    thumb_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Hydration Test Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="script_generated",
    )
    script = Script(
        id=script_id,
        workflow_run_id=run_id,
        content="Resumed narration content for AI video.",
        word_count=7,
    )
    storyboard = Storyboard(
        id=sb_id,
        script_id=script_id,
        shots={"shots": [{"shot": 1, "description": "Resumed scene"}]},
    )
    video = Video(
        id=vid_id,
        workflow_run_id=run_id,
        storage_path="/storage/videos/resumed.mp4",
        duration_seconds=12.5,
        publish_status=PublishStatus.DRAFT,
        aspect_ratio="16:9",
    )
    thumb = Thumbnail(
        id=thumb_id,
        workflow_run_id=run_id,
        storage_path="/storage/thumbnails/resumed.jpg",
        provider_name="test_fal",
    )
    db_session.add_all([run, script, storyboard, video, thumb])
    await db_session.commit()

    try:
        context = await hydrate_resume_context(db_session, run_id, initial_context={"topic": "Initial Topic"})
        assert context["script_id"] == str(script_id)
        assert context["script_content"] == "Resumed narration content for AI video."
        assert context["storyboard_id"] == str(sb_id)
        assert context["storyboard"] == {"shots": [{"shot": 1, "description": "Resumed scene"}]}
        assert context["video_id"] == str(vid_id)
        assert context["video_storage_path"] == "/storage/videos/resumed.mp4"
        assert context["thumbnail_id"] == str(thumb_id)
        assert context["topic"] == "Initial Topic"
    finally:
        await cleanup_run(db_session, run_id)


async def test_orchestrator_suspends_at_approval_boundary(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify Orchestrator suspends cleanly at script stage when in ASSISTED mode, creating ApprovalCheckpoint."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Assisted Story Approval",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
    )
    db_session.add(run)
    await db_session.commit()

    orch = Orchestrator(db=db_session)

    with patch.object(orch, "_execute_stage", new_callable=AsyncMock) as mock_exec:
        # Mock trend stage success
        mock_exec.side_effect = [
            StageResult(stage="trend", success=True, output={"topic": "Assisted Story Approval"}),
            StageResult(stage="script", success=True, output={"script": "Script content generated."}),
        ]

        result = await orch.run(
            workflow_run_id=run_id,
            workflow_input={"topic": "Assisted Story Approval", "aspect_ratio": "16:9"},
        )

        assert result.status == WorkflowStatus.AWAITING_APPROVAL.value
        assert "script" in result.completed_stages

        # Verify DB state
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed.status == WorkflowStatus.AWAITING_APPROVAL
        assert refreshed.waiting_checkpoint_id is not None
        assert refreshed.last_completed_stage == "script"

        # Verify Checkpoint created
        cp = await db_session.get(ApprovalCheckpoint, refreshed.waiting_checkpoint_id)
        assert cp is not None
        assert cp.stage == ApprovalStage.SCRIPT
        assert cp.reference_table == "scripts"
        assert cp.action is None

    await cleanup_run(db_session, run_id)


# ---------------------------------------------------------------------------
# 3. HTTP API Lease & Resumption Endpoints Tests
# ---------------------------------------------------------------------------

async def test_workflow_run_endpoint_exposes_lease_fields_and_is_stale(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """GET /workflow-runs/{id} returns durable lease fields and accurate is_stale flag."""
    run_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Stale Status Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="storyboard_generated",
        last_completed_stage="storyboard",
        execution_started_at=stale_time,
        last_heartbeat_at=stale_time,
        execution_attempt=1,
        worker_id="worker-stale-01",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        resp = await client.get(f"/workflow-runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["last_completed_stage"] == "storyboard"
        assert data["execution_attempt"] == 1
        assert data["worker_id"] == "worker-stale-01"
        assert data["is_stale"] is True
    finally:
        await cleanup_run(db_session, run_id)


async def test_recover_endpoint_recovers_stale_run(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/recover succeeds on stale run and triggers background resume."""
    run_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Recoverable Stale Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
        last_completed_stage="script",
        last_heartbeat_at=stale_time,
        execution_attempt=1,
        worker_id="worker-old",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            resp = await client.post(f"/workflow-runs/{run_id}/recover")
            assert resp.status_code == 200
            data = resp.json()

            assert data["workflow_run_id"] == str(run_id)
            assert data["recovered_from_stage"] == "storyboard"
            assert data["execution_attempt"] == 2
            mock_resume.assert_awaited_once_with(run_id, resume_stage="storyboard")
    finally:
        await cleanup_run(db_session, run_id)


async def test_recover_endpoint_rejects_active_run(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/recover returns 409 Conflict if lease is actively held."""
    run_id = uuid.uuid4()
    recent = datetime.now(timezone.utc).replace(tzinfo=None)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Active Non-Stale Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
        last_heartbeat_at=recent,
        execution_attempt=1,
        worker_id="worker-live",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        resp = await client.post(f"/workflow-runs/{run_id}/recover")
        assert resp.status_code == 409
        assert "actively executing" in resp.json()["detail"]
    finally:
        await cleanup_run(db_session, run_id)


async def test_resume_endpoint_resumes_suspended_run(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/resume triggers resumption from next stage."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Paused Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="script_generated",
        last_completed_stage="script",
        waiting_checkpoint_id=None,
    )
    db_session.add(run)
    await db_session.commit()

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            resp = await client.post(f"/workflow-runs/{run_id}/resume")
            assert resp.status_code == 200
            data = resp.json()

            assert data["resumed_from_stage"] == "storyboard"
            assert data["status"] == "running"
            mock_resume.assert_awaited_once_with(run_id, resume_stage="storyboard")
    finally:
        await cleanup_run(db_session, run_id)


async def test_resume_endpoint_rejects_completed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /workflow-runs/{id}/resume returns 409 Conflict if run already completed."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Finished Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="published",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        resp = await client.post(f"/workflow-runs/{run_id}/resume")
        assert resp.status_code == 409
        assert "already completed" in resp.json()["detail"]
    finally:
        await cleanup_run(db_session, run_id)


async def test_decide_approval_approve_resumes_workflow(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /approvals/{checkpoint_id}/decide with APPROVE clears checkpoint lock and triggers resume."""
    run_id = uuid.uuid4()
    cp_id = uuid.uuid4()
    script_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Approval Resumption Test",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="script_generated",
        last_completed_stage="script",
    )
    db_session.add(run)
    await db_session.commit()

    script = Script(
        id=script_id,
        workflow_run_id=run_id,
        content="Approved script body.",
        word_count=3,
    )
    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=script_id,
    )
    db_session.add_all([script, checkpoint])
    await db_session.commit()

    run.waiting_checkpoint_id = cp_id
    await db_session.commit()

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            resp = await client.post(
                f"/approvals/{cp_id}/decide",
                json={"action": "approve", "reviewer_notes": "Looks stellar!"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["action"] == "approve"
            assert data["reviewer_notes"] == "Looks stellar!"

            db_session.expire(run)
            refreshed_run = await db_session.get(WorkflowRun, run_id)
            assert refreshed_run.waiting_checkpoint_id is None
            mock_resume.assert_awaited_once_with(run_id)
    finally:
        await cleanup_run(db_session, run_id)


async def test_decide_approval_reject_fails_workflow(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /approvals/{checkpoint_id}/decide with REJECT sets run status to FAILED."""
    run_id = uuid.uuid4()
    cp_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Rejection Test Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="script_generated",
        last_completed_stage="script",
    )
    db_session.add(run)
    await db_session.commit()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(checkpoint)
    await db_session.commit()

    run.waiting_checkpoint_id = cp_id
    await db_session.commit()

    try:
        resp = await client.post(
            f"/approvals/{cp_id}/decide",
            json={"action": "reject", "reviewer_notes": "Narrative pacing is off."},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "reject"

        db_session.expire(run)
        refreshed_run = await db_session.get(WorkflowRun, run_id)
        assert refreshed_run.status == WorkflowStatus.FAILED
        assert refreshed_run.waiting_checkpoint_id is None
        assert "Rejected at script approval checkpoint" in (refreshed_run.failure_reason or "")
        assert refreshed_run.completed_at is not None
    finally:
        await cleanup_run(db_session, run_id)
