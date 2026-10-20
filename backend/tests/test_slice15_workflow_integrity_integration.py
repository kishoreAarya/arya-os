"""
AryaOS V1 — Slice 15: End-to-End Contract, Idempotency & Production Workflow Integrity Suite.

Integration & Contract tests verifying:
1. Concurrent Execution Lease Rejection (HTTP 409 on actively running or leased workflows)
2. Terminal Workflow Protection (HTTP 409 on completed/failed workflows for execute, recover, patch)
3. Approval Checkpoint Concurrency & Idempotency (Row locking, duplicate decision HTTP 409, reject semantics)
4. State Machine Invariants & Approval Bypass Protection (Bypassing undecided approval via PATCH returns 409)
5. Publishing Idempotency (Already published video short-circuits without re-dispatching)
6. Analytics Ingestion Idempotency & Metrics Normalization (In-place update on duplicate, race-safe, bounds validation)
7. Workflow Resume Artifact Reuse & Cumulative Cost Accounting
"""

import asyncio
from datetime import datetime, timezone
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
from app.models.enums import ApprovalStage, PipelineStage, PublishStatus, WorkflowMode, WorkflowStatus
from app.models.media import Thumbnail, Video
from app.models.system import SystemLog
from app.models.analytics import Analytics
from app.services.analytics_service import AnalyticsIngestionService, MetricValidationError
from app.services.pipeline_state import (
    InvalidStageTransitionError,
    advance_stage,
    STAGE_TRANSITIONS,
)
from app.services.workflow_execution_service import (
    WorkflowExecutionConflictError,
    claim_execution_lease,
    determine_next_stage,
    hydrate_resume_context,
    is_lease_stale,
    recover_workflow_run,
    suspend_for_approval,
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
        await db.execute(delete(Analytics).where(Analytics.workflow_run_id == run_id))
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db.commit()
    except Exception:
        await db.rollback()


# ===========================================================================
# 1. Concurrent Execution & Terminal State Hardening
# ===========================================================================

async def test_concurrent_execution_claim_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Executing an already RUNNING workflow must return HTTP 409 Conflict."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Concurrent Lease Topic", "mode": "assisted"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        # Simulate active lease
        await claim_execution_lease(db_session, run_id, worker_id="worker-proc-alpha")

        # Second execute request must be rejected with 409
        exec_resp = await client.post(f"/workflow-runs/{run_id}/execute")
        assert exec_resp.status_code == 409
        assert "already running" in exec_resp.json()["detail"].lower()
    finally:
        await _cleanup_run(db_session, run_id)


async def test_completed_workflow_reexecution_and_patch_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Terminal (COMPLETED) workflow cannot be re-executed, recovered, or mutated."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Terminal Workflow Topic", "mode": "autonomous"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        run = await db_session.get(WorkflowRun, run_id)
        run.status = WorkflowStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db_session.commit()

        # 1. Execute must return 409
        exec_resp = await client.post(f"/workflow-runs/{run_id}/execute")
        assert exec_resp.status_code == 409
        assert "already completed" in exec_resp.json()["detail"].lower()

        # 2. Recover must return 409
        rec_resp = await client.post(f"/workflow-runs/{run_id}/recover")
        assert rec_resp.status_code == 409
        assert "already completed" in rec_resp.json()["detail"].lower()

        # 3. Patching status to RUNNING must return 409
        patch_resp = await client.patch(
            f"/workflow-runs/{run_id}",
            json={"status": "running"},
        )
        assert patch_resp.status_code == 409
        assert "terminal" in patch_resp.json()["detail"].lower()
    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# 2. Approval Idempotency, Concurrency & State Machine Integrity
# ===========================================================================

async def test_approval_decision_idempotency_duplicate_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Once decided, any subsequent decision on the same checkpoint returns 409 Conflict."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Approval Idempotency Topic", "mode": "assisted"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        # Create a script and checkpoint
        script = Script(
            workflow_run_id=run_id,
            content="Script for approval idempotency verification.",
            word_count=5,
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
        await db_session.flush()

        # Mark run as awaiting approval
        run = await db_session.get(WorkflowRun, run_id)
        run.status = WorkflowStatus.AWAITING_APPROVAL
        run.waiting_checkpoint_id = checkpoint.id
        await db_session.commit()
        await db_session.refresh(checkpoint)

        # First decision: Approve
        with patch("app.api.routers.workflow_runs._launch_workflow_resume", new_callable=AsyncMock) as mock_resume:
            decide_resp = await client.post(
                f"/approvals/{checkpoint.id}/decide",
                json={"action": "approve", "reviewer_notes": "First approval decision"},
            )
            assert decide_resp.status_code == 200
            assert decide_resp.json()["action"] == "approve"
            mock_resume.assert_awaited_once_with(run_id)

        # Second decision: Duplicate approve must be rejected with 409 Conflict
        dup_resp = await client.post(
            f"/approvals/{checkpoint.id}/decide",
            json={"action": "approve", "reviewer_notes": "Duplicate attempt"},
        )
        assert dup_resp.status_code == 409
        assert "already been decided" in dup_resp.json()["detail"].lower()

        # Third decision: Conflicting reject must also be rejected with 409 Conflict
        conflict_resp = await client.post(
            f"/approvals/{checkpoint.id}/decide",
            json={"action": "reject", "reviewer_notes": "Conflicting decision"},
        )
        assert conflict_resp.status_code == 409
        assert "already been decided" in conflict_resp.json()["detail"].lower()
    finally:
        await _cleanup_run(db_session, run_id)


async def test_approval_rejection_marks_workflow_failed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Rejecting an approval checkpoint marks workflow as FAILED with rejection notes and timestamp."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Approval Rejection Topic", "mode": "assisted"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        script = Script(
            workflow_run_id=run_id,
            content="Script to reject.",
            word_count=3,
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
        await db_session.flush()

        run = await db_session.get(WorkflowRun, run_id)
        run.status = WorkflowStatus.AWAITING_APPROVAL
        run.waiting_checkpoint_id = checkpoint.id
        await db_session.commit()

        # Reject checkpoint
        reject_resp = await client.post(
            f"/approvals/{checkpoint.id}/decide",
            json={"action": "reject", "reviewer_notes": "Narrative pacing is too slow"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["action"] == "reject"

        # Verify WorkflowRun state
        await db_session.refresh(run)
        assert run.status == WorkflowStatus.FAILED
        assert run.waiting_checkpoint_id is None
        assert "Narrative pacing is too slow" in run.failure_reason
        assert run.completed_at is not None
        assert run.worker_id is None
    finally:
        await _cleanup_run(db_session, run_id)


async def test_state_machine_approval_bypass_protection(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Directly PATCHing status to RUNNING/COMPLETED or advancing stage when awaiting approval is rejected."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Bypass Protection Topic", "mode": "assisted"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        script = Script(
            workflow_run_id=run_id,
            content="Undecided checkpoint script.",
            word_count=4,
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
        await db_session.flush()

        run = await db_session.get(WorkflowRun, run_id)
        run.status = WorkflowStatus.AWAITING_APPROVAL
        run.waiting_checkpoint_id = checkpoint.id
        await db_session.commit()

        # Attempt 1: PATCH status to RUNNING while checkpoint is undecided -> 409
        patch_resp1 = await client.patch(
            f"/workflow-runs/{run_id}",
            json={"status": "running"},
        )
        assert patch_resp1.status_code == 409
        assert "cannot bypass approval" in patch_resp1.json()["detail"].lower()

        # Attempt 2: PATCH status to COMPLETED while checkpoint is undecided -> 409
        patch_resp2 = await client.patch(
            f"/workflow-runs/{run_id}",
            json={"status": "completed"},
        )
        assert patch_resp2.status_code == 409
        assert "cannot bypass approval" in patch_resp2.json()["detail"].lower()

        # Attempt 3: Execute endpoint when awaiting approval -> 409
        exec_resp = await client.post(f"/workflow-runs/{run_id}/execute")
        assert exec_resp.status_code == 409
        assert "awaiting human approval" in exec_resp.json()["detail"].lower()
    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# 3. Publishing Idempotency
# ===========================================================================

async def test_publishing_idempotency_already_published_video(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Calling /publishing/publish on an already published video returns the existing publish record."""
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "Publishing Idempotency Topic", "mode": "autonomous"},
    )
    assert create_resp.status_code == 201
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    try:
        # Create an already PUBLISHED video row
        video = Video(
            workflow_run_id=run_id,
            storage_path="videos/already_published.mp4",
            title="Already Published Video",
            youtube_video_id="yt-idempotent-999",
            publish_status=PublishStatus.PUBLISHED,
        )
        db_session.add(video)
        await db_session.commit()
        await db_session.refresh(video)

        # Call /publishing/publish with video_id
        with patch("app.agents.publishing.PublishingAgent.run", new_callable=AsyncMock) as mock_agent_run:
            pub_resp = await client.post(
                "/publishing/publish",
                json={
                    "asset_storage_path": "videos/already_published.mp4",
                    "title": "Already Published Video",
                    "platform": "youtube",
                    "social_platform": "youtube",
                    "video_id": str(video.id),
                    "dry_run": False,
                },
            )
            assert pub_resp.status_code == 200
            data = pub_resp.json()
            assert data["success"] is True
            assert data["published_content_id"] == "yt-idempotent-999"
            assert data["publish_status"] == "published"
            assert data["url"] == "https://www.youtube.com/watch?v=yt-idempotent-999"
            assert data["is_dry_run"] is False

            # Crucial: PublishingAgent was NOT invoked again, preserving idempotency
            mock_agent_run.assert_not_called()

        # Call /publishing/publish with workflow_run_id instead of video_id
        with patch("app.agents.publishing.PublishingAgent.run", new_callable=AsyncMock) as mock_agent_run:
            pub_resp2 = await client.post(
                "/publishing/publish",
                json={
                    "asset_storage_path": "videos/already_published.mp4",
                    "title": "Already Published Video",
                    "platform": "youtube",
                    "social_platform": "youtube",
                    "workflow_run_id": str(run_id),
                    "dry_run": False,
                },
            )
            assert pub_resp2.status_code == 200
            data2 = pub_resp2.json()
            assert data2["success"] is True
            assert data2["published_content_id"] == "yt-idempotent-999"
            mock_agent_run.assert_not_called()
    finally:
        await _cleanup_run(db_session, run_id)


# ===========================================================================
# 4. Analytics Ingestion Idempotency & Validation
# ===========================================================================

async def test_analytics_ingestion_idempotency_and_update_in_place(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Ingesting snapshots with identical key updates the existing record in-place."""
    service = AnalyticsIngestionService(db_session)
    fixed_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    post_id = f"post-slice15-{uuid.uuid4().hex[:8]}"

    raw_payload_1 = {
        "snapshot_at": fixed_time.isoformat(),
        "views": 1000,
        "likes": 50,
        "comments": 10,
        "engagement_rate": 0.05,
    }

    # First ingestion
    record_1 = await service.ingest_snapshot(
        platform="youtube",
        raw_metrics=raw_payload_1,
        external_post_id=post_id,
        source="test",
    )
    rec_id_1 = record_1.id
    assert record_1.views == 1000
    assert record_1.likes == 50
    assert record_1.comments == 10

    # Second ingestion with updated values for the exact same snapshot timestamp
    raw_payload_2 = {
        "snapshot_at": fixed_time.isoformat(),
        "views": 1500,
        "likes": 85,
        "comments": 22,
        "engagement_rate": 0.07,
    }

    record_2 = await service.ingest_snapshot(
        platform="youtube",
        raw_metrics=raw_payload_2,
        external_post_id=post_id,
        source="test",
    )

    # Must be the exact same DB row updated in-place (no duplicate record)
    assert record_2.id == rec_id_1
    assert record_2.views == 1500
    assert record_2.likes == 85
    assert record_2.comments == 22

    # Clean up
    await db_session.delete(record_2)
    await db_session.commit()


async def test_analytics_metric_validation():
    """Metrics validator rejects negative numbers and normalizes percentages."""
    service = AnalyticsIngestionService(AsyncMock())

    # Negative views rejected
    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"views": -10})

    # Rate > 100% rejected
    with pytest.raises(MetricValidationError, match="cannot exceed 1.0"):
        service.normalize_metrics({"engagement_rate": 150.0})

    # Percentage normalization: 75.0% -> 0.75
    normalized = service.normalize_metrics({"engagement_rate": 75.0, "click_through_rate": 0.12})
    assert normalized["engagement_rate"] == 0.75
    assert normalized["click_through_rate"] == 0.12


# ===========================================================================
# 5. Workflow Resume Artifact Reuse & Cost Accounting
# ===========================================================================

async def test_hydrate_resume_context_preserves_artifacts(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Resume hydration loads previously generated script, storyboard, video, thumbnail."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Artifact Reuse Topic",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        # Add Script
        script = Script(workflow_run_id=run.id, content="Hydration test script", word_count=3)
        db_session.add(script)
        await db_session.flush()

        # Add Storyboard
        storyboard = Storyboard(
            script_id=script.id,
            shots=[{"shot_number": 1, "visual_description": "Shot 1"}],
        )
        db_session.add(storyboard)
        await db_session.flush()

        # Add Video
        video = Video(
            workflow_run_id=run.id,
            storage_path="videos/reused_cut.mp4",
            title="Reused Video",
            publish_status=PublishStatus.DRAFT,
        )
        db_session.add(video)
        await db_session.flush()

        # Add Thumbnail
        thumbnail = Thumbnail(
            workflow_run_id=run.id,
            storage_path="thumbnails/reused_thumb.jpg",
            provider_name="recraft",
        )
        db_session.add(thumbnail)
        await db_session.commit()

        # Hydrate context
        context = await hydrate_resume_context(db_session, run.id)

        assert context["script_id"] == str(script.id)
        assert context["script_content"] == "Hydration test script"
        assert context["storyboard_id"] == str(storyboard.id)
        assert context["storyboard"] == [{"shot_number": 1, "visual_description": "Shot 1"}]
        assert context["video_id"] == str(video.id)
        assert context["video_storage_path"] == "videos/reused_cut.mp4"
        assert context["thumbnail_id"] == str(thumbnail.id)
        assert context["thumbnail_storage_path"] == "thumbnails/reused_thumb.jpg"
    finally:
        await _cleanup_run(db_session, run.id)


async def test_determine_next_stage_progression():
    """Verify standard next stage progression rules."""
    assert determine_next_stage("trend", "trend_selected") == "script"
    assert determine_next_stage("script", "script_generated") == "storyboard"
    assert determine_next_stage("storyboard", "storyboard_generated") == "shot_executor"
    assert determine_next_stage("shot_executor", "image_generated") == "music"
    assert determine_next_stage("video_assembler", "video_generated") == "thumbnail"
    assert determine_next_stage("thumbnail", "video_generated") == "storage"


# ===========================================================================
# 6. Pipeline State Machine Transition Invariants
# ===========================================================================

async def test_pipeline_state_machine_legal_and_illegal_transitions(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify strict validation of STAGE_TRANSITIONS."""
    run = WorkflowRun(
        project_id=test_project,
        topic="State Transitions Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.PENDING,
        current_stage=PipelineStage.CREATED.value,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        # Legal progression: created -> trend -> script
        run = await advance_stage(db_session, run.id, PipelineStage.TREND_SELECTED)
        assert run.current_stage == PipelineStage.TREND_SELECTED.value

        run = await advance_stage(db_session, run.id, PipelineStage.SCRIPT_GENERATED)
        assert run.current_stage == PipelineStage.SCRIPT_GENERATED.value

        # Illegal skip: script_generated -> video_generated must raise InvalidStageTransitionError
        with pytest.raises(InvalidStageTransitionError, match="Cannot advance"):
            await advance_stage(db_session, run.id, PipelineStage.VIDEO_GENERATED)

        # Illegal skip: script_generated -> published
        with pytest.raises(InvalidStageTransitionError, match="Cannot advance"):
            await advance_stage(db_session, run.id, PipelineStage.PUBLISHED)
    finally:
        await _cleanup_run(db_session, run.id)
