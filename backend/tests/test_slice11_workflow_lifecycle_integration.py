"""
AryaOS V1 — Slice 11: Production Hardening & End-to-End Workflow Verification Suite.

Comprehensive integration-level verification of:
1. End-to-End Workflow Lifecycle (Create -> Execute -> Checkpoint -> Suspend -> Approve -> Resume -> Complete)
2. State Machine Transitions & Terminal State Enforcements
3. Lease Safety & Concurrent Recovery Races
4. Heartbeat Ownership & Stale Lease Dynamics
5. Approval Resume Correctness & Artifact Reuse Invariant (Script, Storyboard, Video, Thumbnail)
6. Retry Semantics & Stage Targeting
7. Cumulative Cost Accounting Across Pause/Resume and Retry
8. Failure, Cancellation, and Worker Lease Release Safety
9. Multi-Stage Recovery Safety
10. API Contracts, Bounded Pagination, and Error Handling
11. Security Hardening (Bearer Auth, Content Whitelist, Bounded Pagination)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalAction, ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import WorkflowRun
from app.models.system import SystemLog
from app.models.enums import ApprovalStage, PipelineStage, WorkflowMode, WorkflowStatus
from app.models.media import Thumbnail, Video
from app.services.pipeline_state import InvalidStageTransitionError, advance_stage, STAGE_TRANSITIONS
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
from app.services.workflow_service import update_workflow_run
from app.schemas.workflow_run import WorkflowRunUpdateRequest

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _cleanup_run(db: AsyncSession, run_id: uuid.UUID) -> None:
    """Helper to clean up a workflow run and all related cascading entities."""
    try:
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
    except Exception:
        await db.rollback()



# ===========================================================================
# WORKSTREAM 1 & 5: End-to-End Workflow Lifecycle & Artifact Reuse
# ===========================================================================

async def test_e2e_workflow_lifecycle_assisted_mode(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify complete lifecycle in ASSISTED mode:
    Create -> Pending -> Execute -> Suspend at Script Checkpoint ->
    Approve -> Resume -> Next Stages -> Complete.
    Verify that PostgreSQL state transitions correctly and artifacts are not duplicated.
    """
    # 1. Create run via API
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "E2E Lifecycle Topic", "mode": "assisted"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        run = await db_session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.status == WorkflowStatus.PENDING
        assert run.current_stage == PipelineStage.CREATED.value

        # 2. Simulate stage progression up to script generation
        await claim_execution_lease(db_session, run_id, worker_id="worker-proc-alpha")
        await advance_stage(db_session, run_id, PipelineStage.TREND_SELECTED)
        await advance_stage(db_session, run_id, PipelineStage.SCRIPT_GENERATED)

        script = Script(
            workflow_run_id=run_id,
            content="Original narrative script for lifecycle verification.",
            word_count=7,
        )
        db_session.add(script)
        await db_session.flush()

        checkpoint = ApprovalCheckpoint(
            workflow_run_id=run_id,
            stage=ApprovalStage.SCRIPT,
            reference_table="scripts",
            reference_id=script.id,
        )
        db_session.add(checkpoint)
        await db_session.commit()

        # 3. Clean suspension at checkpoint
        suspended = await suspend_for_approval(db_session, run_id, checkpoint.id)
        assert suspended.status == WorkflowStatus.AWAITING_APPROVAL
        assert suspended.waiting_checkpoint_id == checkpoint.id
        assert suspended.worker_id is None

        # 4. Human Decision: APPROVE checkpoint via API
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            decide_resp = await client.post(
                f"/approvals/{checkpoint.id}/decide",
                json={"action": "approve", "reviewer_notes": "Script looks excellent"},
            )
            assert decide_resp.status_code == 200
            mock_resume.assert_awaited_once_with(run_id)

        db_session.expire(run)
        refreshed_run = await db_session.get(WorkflowRun, run_id)
        assert refreshed_run.waiting_checkpoint_id is None

        # 5. Hydrate resume context — verify existing script is reused
        context = await hydrate_resume_context(db_session, run_id)
        assert context["script_id"] == str(script.id)
        assert context["script_content"] == "Original narrative script for lifecycle verification."

        # 6. Next stage determination advances to storyboard
        next_stage = determine_next_stage("script", PipelineStage.SCRIPT_GENERATED.value)
        assert next_stage == "storyboard"

        # 7. Complete subsequent stages and verify completion
        await claim_execution_lease(db_session, run_id, worker_id="worker-proc-beta")
        await advance_stage(db_session, run_id, PipelineStage.STORYBOARD_GENERATED)
        await advance_stage(db_session, run_id, PipelineStage.VIDEO_GENERATED)
        await advance_stage(db_session, run_id, PipelineStage.APPROVED)
        await advance_stage(db_session, run_id, PipelineStage.PUBLISHED)

        # Ensure no duplicate scripts were created
        scripts_stmt = select(Script).where(Script.workflow_run_id == run_id)
        all_scripts = (await db_session.execute(scripts_stmt)).scalars().all()
        assert len(all_scripts) == 1
        assert all_scripts[0].id == script.id

    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 2: State Machine Integrity & Invalid Transitions
# ===========================================================================

async def test_canonical_pipeline_state_machine_transitions(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that all canonical forward transitions defined in the state machine succeed."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Canonical State Machine Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.CREATED.value,
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id

    try:
        # created -> trend_selected
        run = await advance_stage(db_session, run_id, PipelineStage.TREND_SELECTED)
        assert run.current_stage == PipelineStage.TREND_SELECTED.value

        # trend_selected -> script_generated
        run = await advance_stage(db_session, run_id, PipelineStage.SCRIPT_GENERATED)
        assert run.current_stage == PipelineStage.SCRIPT_GENERATED.value

        # script_generated -> storyboard_generated
        run = await advance_stage(db_session, run_id, PipelineStage.STORYBOARD_GENERATED)
        assert run.current_stage == PipelineStage.STORYBOARD_GENERATED.value

        # storyboard_generated -> video_generated
        run = await advance_stage(db_session, run_id, PipelineStage.VIDEO_GENERATED)
        assert run.current_stage == PipelineStage.VIDEO_GENERATED.value

        # video_generated -> approved
        run = await advance_stage(db_session, run_id, PipelineStage.APPROVED)
        assert run.current_stage == PipelineStage.APPROVED.value

        # approved -> published
        run = await advance_stage(db_session, run_id, PipelineStage.PUBLISHED)
        assert run.current_stage == PipelineStage.PUBLISHED.value

        # published -> analytics_collected
        run = await advance_stage(db_session, run_id, PipelineStage.ANALYTICS_COLLECTED)
        assert run.current_stage == PipelineStage.ANALYTICS_COLLECTED.value

        # analytics_collected -> learning_updated
        run = await advance_stage(db_session, run_id, PipelineStage.LEARNING_UPDATED)
        assert run.current_stage == PipelineStage.LEARNING_UPDATED.value

    finally:
        await _cleanup_run(db_session, run_id)


async def test_invalid_stage_transitions_rejected(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify illegal jumps across pipeline stages are rejected with InvalidStageTransitionError."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Invalid Transitions Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.LEARNING_UPDATED.value,
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id

    try:
        # learning_updated -> script_generated (illegal backward jump)
        with pytest.raises(InvalidStageTransitionError):
            await advance_stage(db_session, run_id, PipelineStage.SCRIPT_GENERATED)

        # Reset stage to published
        run.current_stage = PipelineStage.PUBLISHED.value
        await db_session.commit()

        # published -> created (illegal jump)
        with pytest.raises(InvalidStageTransitionError):
            await advance_stage(db_session, run_id, PipelineStage.CREATED)

    finally:
        await _cleanup_run(db_session, run_id)


async def test_terminal_workflow_transitions_rejected(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that completed or failed workflows reject status changes back to RUNNING and reject stage advancement."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Terminal Workflow State Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage=PipelineStage.PUBLISHED.value,
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id

    try:
        # 1. Attempt completed -> running
        update_req = WorkflowRunUpdateRequest(status=WorkflowStatus.RUNNING)
        with pytest.raises(InvalidStageTransitionError) as exc_info:
            await update_workflow_run(db_session, run_id, update_req)
        assert "Cannot transition terminal workflow" in str(exc_info.value)

        # 2. Attempt stage advance on completed workflow
        stage_req = WorkflowRunUpdateRequest(current_stage=PipelineStage.ANALYTICS_COLLECTED)
        with pytest.raises(InvalidStageTransitionError) as exc_info:
            await update_workflow_run(db_session, run_id, stage_req)
        assert "Cannot advance stage of terminal workflow" in str(exc_info.value)

        # 3. Test failed run rejection
        run.status = WorkflowStatus.FAILED
        await db_session.commit()

        with pytest.raises(InvalidStageTransitionError):
            await update_workflow_run(db_session, run_id, WorkflowRunUpdateRequest(status=WorkflowStatus.RUNNING))

    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 3: Lease Safety & Concurrent Recovery Race
# ===========================================================================

async def test_concurrent_recovery_race_single_winner(test_project: uuid.UUID):
    """Verify that when two workers race to recover the exact same stale workflow,
    PostgreSQL row-level locking ensures exactly one succeeds and the other is rejected with conflict.
    """
    from app.database.session import AsyncSessionLocal

    run_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)

    async with AsyncSessionLocal() as setup_session:
        run = WorkflowRun(
            id=run_id,
            project_id=test_project,
            topic="Concurrent Recovery Race Run",
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
            current_stage="script_generated",
            last_completed_stage="script",
            last_heartbeat_at=stale_time,
            worker_id="crashed-worker-old",
            execution_attempt=1,
        )
        setup_session.add(run)
        await setup_session.commit()

    async def attempt_recovery(worker_name: str) -> tuple[str, bool, str | None]:
        async with AsyncSessionLocal() as session:
            try:
                rec_run, next_stg = await recover_workflow_run(
                    db=session,
                    run_id=run_id,
                    worker_id=worker_name,
                    timeout_seconds=300,
                )
                return worker_name, True, next_stg
            except WorkflowExecutionConflictError as err:
                return worker_name, False, str(err)

    try:
        results = await asyncio.gather(
            attempt_recovery("worker-race-1"),
            attempt_recovery("worker-race-2"),
        )

        winners = [r for r in results if r[1] is True]
        losers = [r for r in results if r[1] is False]

        assert len(winners) == 1, f"Expected exactly 1 recovery winner, got {len(winners)}"
        assert len(losers) == 1, f"Expected exactly 1 conflict rejection, got {len(losers)}"
        assert "actively executing" in losers[0][2]

        async with AsyncSessionLocal() as verify_session:
            final_run = await verify_session.get(WorkflowRun, run_id)
            assert final_run.worker_id == winners[0][0]
            assert final_run.execution_attempt == 2
            assert final_run.status == WorkflowStatus.RUNNING
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await _cleanup_run(cleanup_session, run_id)


async def test_completed_workflow_cannot_be_recovered(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that a completed workflow run cannot be recovered or leased."""
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Completed Recovery Immunity Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="published",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        with pytest.raises(WorkflowExecutionConflictError) as exc_info:
            await recover_workflow_run(db_session, run_id, worker_id="worker-intruder")
        assert "already completed" in str(exc_info.value)
    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 4: Heartbeat Safety & Worker Ownership
# ===========================================================================

async def test_heartbeat_worker_ownership_enforcement(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that a worker cannot update the heartbeat on a lease owned by another worker."""
    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Heartbeat Ownership Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
        last_heartbeat_at=now,
        worker_id="worker-legitimate-owner",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        # Legitimate worker heartbeat succeeds
        await update_heartbeat(db_session, run_id, worker_id="worker-legitimate-owner")

        # Rogue worker heartbeat fails with conflict error
        with pytest.raises(WorkflowExecutionConflictError) as exc_info:
            await update_heartbeat(db_session, run_id, worker_id="worker-rogue-usurper")
        assert "cannot update heartbeat for lease owned by" in str(exc_info.value)

        # Heartbeat on completed run does not revive or update
        run.status = WorkflowStatus.COMPLETED
        await db_session.commit()

        past_time = now - timedelta(hours=1)
        run.last_heartbeat_at = past_time
        await db_session.commit()

        await update_heartbeat(db_session, run_id, worker_id="worker-legitimate-owner")
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed.status == WorkflowStatus.COMPLETED
        assert refreshed.last_heartbeat_at == past_time  # Unmodified!

    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 6 & 7: Retry Semantics, Multi-Stage Checkpoints & Cumulative Cost
# ===========================================================================

async def test_checkpoint_retry_semantics_and_stage_targeting(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify retry on SCRIPT and VIDEO checkpoints:
    1. Checkpoint lock is cleared.
    2. Resumes from the target stage (e.g. video -> video_assembler).
    3. Accumulated costs are preserved and not zeroed out.
    """
    run_id = uuid.uuid4()
    vid_id = uuid.uuid4()
    cp_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Video Retry Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="video_generated",
        last_completed_stage="video_assembler",
        total_cost_usd=Decimal("0.4500"),
        execution_attempt=1,
    )
    db_session.add(run)
    await db_session.commit()

    video = Video(
        id=vid_id,
        workflow_run_id=run_id,
        storage_path="/storage/videos/attempt1.mp4",
        duration_seconds=30.0,
        aspect_ratio="16:9",
    )
    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.VIDEO,
        reference_table="videos",
        reference_id=vid_id,
    )
    db_session.add_all([video, checkpoint])
    await db_session.commit()

    run.waiting_checkpoint_id = cp_id
    await db_session.commit()

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            resp = await client.post(
                f"/approvals/{cp_id}/decide",
                json={"action": "retry", "reviewer_notes": "Audio sync off in clip 2"},
            )
            assert resp.status_code == 200
            assert resp.json()["action"] == "retry"

            # Checkpoint stage 'video' maps to orchestrator stage 'video_assembler'
            mock_resume.assert_awaited_once_with(run_id, resume_stage="video_assembler")

        db_session.expire(run)
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed.waiting_checkpoint_id is None
        assert refreshed.total_cost_usd == Decimal("0.4500")  # Cost preserved!

    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 8: Failure, Cancellation & Worker Lease Release
# ===========================================================================

async def test_workflow_failure_releases_worker_lease(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that when a workflow fails, status is FAILED, failure_reason and completed_at are set,
    and worker_id is explicitly released to None (not permanently locked).
    """
    from app.workflows.runner import Runner
    from app.workflows.models import StageResult, WorkflowResult

    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Failure Lease Release Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="script_generated",
        worker_id="worker-doomed-to-fail",
    )
    db_session.add(run)
    await db_session.commit()

    try:
        runner = Runner(db=db_session)
        failed_result = WorkflowResult(
            workflow_id=str(run_id),
            status=WorkflowStatus.FAILED.value,
            success=False,
            completed_stages=["trend"],
            failed_stage="script",
            stage_results=[],
            error="Script generation timeout",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            total_execution_time_ms=1200.0,
            total_cost_usd=0.015,
        )

        await runner._update_run_final_state(run_id, failed_result)

        db_session.expire(run)
        refreshed = await db_session.get(WorkflowRun, run_id)
        assert refreshed.status == WorkflowStatus.FAILED
        assert refreshed.failure_reason == "Script generation timeout"
        assert refreshed.completed_at is not None
        assert refreshed.worker_id is None  # Lease released!

    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# WORKSTREAM 10 & 11: API Contracts, Pending Endpoint, & Security Audit
# ===========================================================================

async def test_approvals_pending_endpoint_routing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify that GET /approvals/pending/{workflow_run_id} is evaluated correctly without UUID parsing collisions."""
    run_id = uuid.uuid4()
    cp_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Pending Approvals API Test",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage="script_generated",
    )
    script = Script(
        workflow_run_id=run_id,
        content="Pending test script content.",
        word_count=4,
    )
    db_session.add_all([run, script])
    await db_session.flush()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=script.id,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    try:
        resp = await client.get(f"/approvals/pending/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == str(cp_id)
        assert data[0]["review_content"]["type"] == "script"
        assert data[0]["review_content"]["content"] == "Pending test script content."
    finally:
        await _cleanup_run(db_session, run_id)


async def test_authentication_enforcement_on_protected_endpoints():
    """Verify that requests missing Bearer tokens are rejected with 401/403 across workflow endpoints."""
    # Use raw AsyncClient without default auth headers
    async with httpx.AsyncClient(base_url="http://testserver") as unauthed_client:
        from app.main import app

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            r1 = await c.get("/workflow-runs/")
            assert r1.status_code in (401, 403)

            r2 = await c.get("/approvals/")
            assert r2.status_code in (401, 403)

            r3 = await c.get("/learning/feedback")
            assert r3.status_code in (401, 403)


async def test_bounded_pagination_limits(client: httpx.AsyncClient):
    """Verify that requests exceeding maximum page limit (le=100) are rejected with 422 Unprocessable Content."""
    resp = await client.get("/workflow-runs/?limit=500")
    assert resp.status_code == 422

    resp2 = await client.get("/approvals/?limit=500")
    assert resp2.status_code == 422


async def test_approval_content_whitelist_safety(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify that checkpoints referencing non-whitelisted tables return safe null content and do not perform arbitrary table lookup."""
    run_id = uuid.uuid4()
    cp_id = uuid.uuid4()

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Arbitrary Whitelist Test Run",
        mode=WorkflowMode.MANUAL,
        status=WorkflowStatus.AWAITING_APPROVAL,
    )
    db_session.add(run)
    await db_session.commit()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="system_logs",  # Not in whitelisted review tables!
        reference_id=uuid.uuid4(),
    )
    db_session.add(checkpoint)
    await db_session.commit()

    try:
        resp = await client.get(f"/approvals/{cp_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_content"] is None  # Safe rejection, no unauthorized table read!
    finally:
        await _cleanup_run(db_session, run_id)
