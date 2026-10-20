"""
AryaOS V1 — Slice 17: Production Launch Gate, Deployment Verification & Final Integrity Hardening.

Comprehensive verification of:
1. Stale Worker Fencing & Late Mutation Rejection (heartbeat, finalization, suspension).
2. Terminal State Machine Guards (cannot advance stage on COMPLETED or FAILED runs).
3. Concurrent Approval Decisions (idempotent rejection, HTTP 409 on second race).
4. Publishing & Analytics Idempotency (deduplication on retries, lineage preservation).
5. Comprehensive Security & Authorization Gate (IDOR 404, Admin 403, SSRF & path traversal blocks).
"""

from datetime import datetime, timezone
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal
from app.models.analytics import Analytics
from app.models.approval import ApprovalAction, ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalStage, PipelineStage, PublishStatus, WorkflowMode, WorkflowStatus
from app.models.media import Video
from app.models.system import SystemLog
from app.services.analytics_service import AnalyticsIngestionService
from app.services.authorization_service import add_project_membership, create_api_key
from app.services.pipeline_state import advance_stage, InvalidStageTransitionError
from app.services.workflow_execution_service import (
    WorkflowExecutionConflictError,
    claim_execution_lease,
    finalize_workflow_execution,
    suspend_for_approval,
    update_heartbeat,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _cleanup_workflow(db: AsyncSession, run_id: uuid.UUID) -> None:
    """Helper to cleanly teardown a workflow run and all referencing children in reverse FK order."""
    try:
        await db.execute(delete(Analytics).where(Analytics.workflow_run_id == run_id))
        await db.execute(delete(SystemLog).where(SystemLog.workflow_run_id == run_id))
        await db.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
        await db.execute(delete(Video).where(Video.workflow_run_id == run_id))
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db.commit()
    except Exception:
        await db.rollback()


# ===========================================================================
# 1. Stale Worker Fencing & Late Mutation Rejection
# ===========================================================================

async def test_stale_worker_heartbeat_and_finalize_rejected(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """A worker whose lease expired or was transferred to another worker cannot update heartbeat or finalize."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Worker Fencing Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.SCRIPT_GENERATED.value,
        worker_id="worker-A",
        last_heartbeat_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        # Worker B recovers the lease
        await claim_execution_lease(db_session, run.id, worker_id="worker-B", force=True)

        # Worker A attempts late heartbeat -> Must raise WorkflowExecutionConflictError
        with pytest.raises(WorkflowExecutionConflictError) as exc_hb:
            await update_heartbeat(db_session, run.id, worker_id="worker-A")
        assert "Worker worker-A cannot update heartbeat" in str(exc_hb.value)

        # Worker A attempts late finalize -> Must raise WorkflowExecutionConflictError
        with pytest.raises(WorkflowExecutionConflictError) as exc_fin:
            await finalize_workflow_execution(
                db_session,
                run.id,
                worker_id="worker-A",
                status=WorkflowStatus.FAILED,
                failure_reason="Late failure report",
            )
        assert "Worker worker-A cannot finalize workflow run" in str(exc_fin.value)

        # Worker A attempts late suspend -> Must raise WorkflowExecutionConflictError
        dummy_cp = uuid.uuid4()
        with pytest.raises(WorkflowExecutionConflictError) as exc_susp:
            await suspend_for_approval(
                db_session,
                run.id,
                checkpoint_id=dummy_cp,
                worker_id="worker-A",
            )
        assert "Worker worker-A cannot suspend workflow run" in str(exc_susp.value)

        # Confirm WorkflowRun is still running under worker-B and untouched by worker-A
        await db_session.refresh(run)
        assert run.worker_id == "worker-B"
        assert run.status == WorkflowStatus.RUNNING
    finally:
        await _cleanup_workflow(db_session, run.id)


async def test_worker_cannot_finalize_non_running_workflow(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """A worker cannot finalize a workflow that is already COMPLETED or FAILED."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Terminal Workflow Finalize Guard",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage=PipelineStage.PUBLISHED.value,
        worker_id=None,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        with pytest.raises(WorkflowExecutionConflictError) as exc:
            await finalize_workflow_execution(
                db_session,
                run.id,
                worker_id="stale-worker",
                status=WorkflowStatus.FAILED,
                failure_reason="Late failure report after completion",
            )
        assert "cannot finalize workflow run" in str(exc.value)
    finally:
        await _cleanup_workflow(db_session, run.id)


# ===========================================================================
# 2. Terminal State Machine Guard
# ===========================================================================

async def test_terminal_state_advance_stage_blocked(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """advance_stage must raise InvalidStageTransitionError on COMPLETED or FAILED runs."""
    run_completed = WorkflowRun(
        project_id=test_project,
        topic="Completed Terminal Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage=PipelineStage.PUBLISHED.value,
    )
    run_failed = WorkflowRun(
        project_id=test_project,
        topic="Failed Terminal Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.FAILED,
        current_stage=PipelineStage.SCRIPT_GENERATED.value,
    )
    db_session.add_all([run_completed, run_failed])
    await db_session.commit()
    await db_session.refresh(run_completed)
    await db_session.refresh(run_failed)

    try:
        with pytest.raises(InvalidStageTransitionError) as exc_comp:
            await advance_stage(db_session, run_completed.id, PipelineStage.ANALYTICS_COLLECTED)
        assert "in terminal status completed" in str(exc_comp.value)

        with pytest.raises(InvalidStageTransitionError) as exc_fail:
            await advance_stage(db_session, run_failed.id, PipelineStage.STORYBOARD_GENERATED)
        assert "in terminal status failed" in str(exc_fail.value)
    finally:
        await _cleanup_workflow(db_session, run_completed.id)
        await _cleanup_workflow(db_session, run_failed.id)


# ===========================================================================
# 3. Concurrent Approval Decisions & Idempotency
# ===========================================================================

async def test_approval_decision_conflict_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Deciding an approval checkpoint twice returns HTTP 409 on the second call."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Approval Race Check",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=PipelineStage.SCRIPT_GENERATED.value,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    cp = ApprovalCheckpoint(
        workflow_run_id=run.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(cp)
    await db_session.commit()
    await db_session.refresh(cp)

    try:
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock):
            # First decision: Succeeds
            resp1 = await client.post(
                f"/approvals/{cp.id}/decide",
                json={"action": "approve", "reviewer_notes": "First approval"},
            )
            assert resp1.status_code == 200
            assert resp1.json()["action"] == "approve"

            # Second decision (race or retry): Rejection with HTTP 409
            resp2 = await client.post(
                f"/approvals/{cp.id}/decide",
                json={"action": "reject", "reviewer_notes": "Second conflicting decision"},
            )
            assert resp2.status_code == 409
            assert "already been decided" in resp2.json()["detail"]
    finally:
        await _cleanup_workflow(db_session, run.id)


# ===========================================================================
# 4. Publishing & Analytics Idempotency
# ===========================================================================

async def test_publishing_idempotent_return_on_already_published(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """POST /publishing/publish returns existing URL without external re-publish if video already published."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Publishing Idempotency Check",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    video = Video(
        workflow_run_id=run.id,
        storage_path="videos/idempotent_test.mp4",
        youtube_video_id="yt-already-published-999",
        publish_status=PublishStatus.PUBLISHED,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    try:
        resp = await client.post(
            "/publishing/publish",
            json={
                "asset_storage_path": "videos/idempotent_test.mp4",
                "platform": "youtube",
                "workflow_run_id": str(run.id),
                "video_id": str(video.id),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["published_content_id"] == "yt-already-published-999"
        assert "youtube.com/watch?v=yt-already-published-999" in data["url"]
    finally:
        await _cleanup_workflow(db_session, run.id)


async def test_analytics_ingestion_idempotency_upsert(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Same metrics snapshot ingested twice with same key updates existing row without duplicate."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Analytics Deduplication Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    video = Video(
        workflow_run_id=run.id,
        storage_path="videos/analytics_test.mp4",
        youtube_video_id="yt-analytics-dedup-1",
        publish_status=PublishStatus.PUBLISHED,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    try:
        service = AnalyticsIngestionService(db_session)
        fixed_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc).isoformat()

        # Ingest 1
        s1 = await service.ingest_snapshot(
            platform="youtube",
            raw_metrics={"snapshot_at": fixed_time, "views": 100, "likes": 10},
            video_id=video.id,
            workflow_run_id=run.id,
            external_post_id="yt-analytics-dedup-1",
        )

        # Ingest 2 with updated view count
        s2 = await service.ingest_snapshot(
            platform="youtube",
            raw_metrics={"snapshot_at": fixed_time, "views": 150, "likes": 15},
            video_id=video.id,
            workflow_run_id=run.id,
            external_post_id="yt-analytics-dedup-1",
        )

        assert s1.id == s2.id
        assert s2.views == 150

        # Verify only 1 record in database
        stmt = select(Analytics).where(Analytics.workflow_run_id == run.id)
        records = list((await db_session.execute(stmt)).scalars().all())
        assert len(records) == 1
    finally:
        await _cleanup_workflow(db_session, run.id)


# ===========================================================================
# 5. Security & Authorization Gate (IDOR, Admin isolation, SSRF)
# ===========================================================================

async def test_security_launch_gate_idor_and_admin_isolation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Comprehensive test: IDOR returns 404, admin mutations return 403, and path traversal returns 403."""
    proj_a = Project(name=f"Gate-Proj-A-{uuid.uuid4().hex[:6]}")
    proj_b = Project(name=f"Gate-Proj-B-{uuid.uuid4().hex[:6]}")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    key_a_model, key_a_raw = await create_api_key(db_session, name="Gate Key A", is_admin=False)
    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="member")

    run_b = WorkflowRun(
        project_id=proj_b.id,
        topic="Project B Secret Run",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(run_b)
    await db_session.commit()
    await db_session.refresh(run_b)

    headers_a = {"Authorization": f"Bearer {key_a_raw}"}

    try:
        # 1. IDOR WorkflowRun GET -> 404
        r_get = await client.get(f"/workflow-runs/{run_b.id}", headers=headers_a)
        assert r_get.status_code == 404

        # 2. IDOR WorkflowRun PATCH -> 404
        r_patch = await client.patch(f"/workflow-runs/{run_b.id}", json={"failure_reason": "Hacked"}, headers=headers_a)
        assert r_patch.status_code == 404

        # 3. IDOR WorkflowRun EXECUTE -> 404
        r_exec = await client.post(f"/workflow-runs/{run_b.id}/execute", headers=headers_a)
        assert r_exec.status_code == 404

        # 4. IDOR Lineage GET -> 404
        r_lin = await client.get(f"/lineage/{run_b.id}", headers=headers_a)
        assert r_lin.status_code == 404

        # 5. Non-Admin Feature Flag Mutation -> 403 Forbidden
        r_flag = await client.put(
            "/feature-flags/enable_learning_loop",
            json={"enabled": False},
            headers=headers_a,
        )
        assert r_flag.status_code == 403
        assert "Admin access required" in r_flag.json()["detail"]

        # 6. Path Traversal Download -> 403 Forbidden
        r_trav = await client.get(
            "/creator/assets/download?url=../../../../etc/passwd",
            headers=headers_a,
        )
        assert r_trav.status_code == 403
        assert "path traversal" in r_trav.json()["detail"]
    finally:
        await _cleanup_workflow(db_session, run_b.id)
        await db_session.execute(delete(ProjectMembership).where(ProjectMembership.project_id.in_([proj_a.id, proj_b.id])))
        await db_session.execute(delete(ApiKey).where(ApiKey.id == key_a_model.id))
        await db_session.execute(delete(Project).where(Project.id.in_([proj_a.id, proj_b.id])))
        await db_session.commit()
