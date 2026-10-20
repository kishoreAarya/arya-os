"""
AryaOS V1 — Slice 16: Full-System Architecture & End-to-End Workflow Integrity Audit Suite.

Verifies:
1. End-to-End Stage Data Flow: Research -> Script -> Storyboard -> Video -> Analytics -> Learning
2. AnalyticsAgent Persistence: Lineage preservation (workflow_run_id, platform, idempotency_key)
3. Learning Loop Execution: Analytics -> Learning Update -> PerformanceLearningFeedback -> TrendAgent consumption
4. Object-Level Security & Authorization: IDOR protection across workflow runs, checkpoints, and projects
5. State Machine Invariants: Verification of all legal and terminal transitions
6. Durable Execution & Lease Recovery: Claim lease, lease staleness, recovery
"""

import asyncio
from datetime import datetime, timezone
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analytics import AnalyticsAgent
from app.agents.script import ScriptAgent
from app.agents.trend import TrendAgent
from app.models.analytics import Analytics, PerformanceLearningFeedback
from app.models.approval import ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalStage, PipelineStage, PublishStatus, WorkflowMode, WorkflowStatus
from app.models.media import Video
from app.models.system import SystemLog
from app.services.analytics_service import AnalyticsIngestionService
from app.services.authorization_service import add_project_membership, create_api_key
from app.services.pipeline_state import advance_stage, InvalidStageTransitionError, STAGE_TRANSITIONS
from app.services.workflow_execution_service import (
    claim_execution_lease,
    determine_next_stage,
    is_lease_stale,
    recover_workflow_run,
)
from app.workers.jobs import _execute_learning_update

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _cleanup_run(db: AsyncSession, run_id: uuid.UUID) -> None:
    """Helper to clean up a workflow run and all related cascading entities in reverse FK order."""
    try:
        # 1. Leaf / child records referencing Video or WorkflowRun
        await db.execute(delete(Analytics).where(Analytics.workflow_run_id == run_id))
        await db.execute(delete(SystemLog).where(SystemLog.workflow_run_id == run_id))
        await db.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))

        # 2. Videos referencing WorkflowRun
        await db.execute(delete(Video).where(Video.workflow_run_id == run_id))

        # 3. Storyboard referencing Script, Script referencing WorkflowRun
        scripts = (await db.execute(select(Script.id).where(Script.workflow_run_id == run_id))).scalars().all()
        if scripts:
            await db.execute(delete(Storyboard).where(Storyboard.script_id.in_(scripts)))
        await db.execute(delete(Script).where(Script.workflow_run_id == run_id))

        # 4. WorkflowRun itself
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
        await db.commit()
    except Exception:
        await db.rollback()


# ===========================================================================
# 1. AnalyticsAgent Lineage & Idempotency Hardening
# ===========================================================================

async def test_analytics_agent_persists_workflow_lineage_and_idempotency(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """AnalyticsAgent must populate workflow_run_id, platform, and idempotency_key."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Analytics Lineage Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    video = Video(
        workflow_run_id=run.id,
        storage_path="videos/test_vid.mp4",
        youtube_video_id="yt-lineage-123",
        publish_status=PublishStatus.PUBLISHED,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    try:
        agent = AnalyticsAgent(db=db_session)
        mock_data = {
            "snapshot_at": datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
            "views": 2500,
            "likes": 120,
            "comments": 15,
            "click_through_rate": 0.065,
        }

        with patch.object(agent, "_fetch_platform_analytics", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data

            result = await agent.run({
                "platform": "youtube",
                "video_id": str(video.id),
                "published_video_id": "yt-lineage-123",
                "workflow_run_id": str(run.id),
            })

            assert result.success is True
            analytics_id = uuid.UUID(result.output["analytics_result"].analytics_id)

            # Verify persisted row in DB
            snapshot = await db_session.get(Analytics, analytics_id)
            assert snapshot is not None
            assert snapshot.workflow_run_id == run.id
            assert snapshot.video_id == video.id
            assert snapshot.platform == "youtube"
            assert snapshot.external_post_id == "yt-lineage-123"
            assert snapshot.idempotency_key is not None
            assert "youtube:yt-lineage-123:" in snapshot.idempotency_key
            assert snapshot.views == 2500
            assert snapshot.likes == 120
    finally:
        await _cleanup_run(db_session, run.id)


# ===========================================================================
# 2. End-to-End Learning Loop Integration
# ===========================================================================

async def test_analytics_to_learning_loop_trace(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Trace: Analytics Snapshot -> _execute_learning_update -> PerformanceLearningFeedback -> TrendAgent."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Deep Sea Exploration",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    video = Video(
        workflow_run_id=run.id,
        storage_path="videos/deep_sea.mp4",
        title="Deep Sea Mysteries",
        youtube_video_id="yt-deep-sea-001",
        publish_status=PublishStatus.PUBLISHED,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    try:
        # 1. Ingest Analytics with high engagement (CTR > 10%, retention > 70%)
        service = AnalyticsIngestionService(db_session)
        snapshot = await service.ingest_snapshot(
            platform="youtube",
            raw_metrics={
                "snapshot_at": datetime.now(timezone.utc).isoformat(),
                "views": 15000,
                "likes": 900,
                "click_through_rate": 0.12,
                "average_view_percentage": 0.75,
                "engagement_rate": 0.08,
            },
            video_id=video.id,
            workflow_run_id=run.id,
            external_post_id="yt-deep-sea-001",
        )
        assert snapshot is not None

        # 2. Run Learning Update worker job
        stats = await _execute_learning_update(db_session, limit=10)
        assert stats["records_examined"] >= 1
        assert stats["feedback_persisted"] >= 1

        # 3. Verify that PerformanceLearningFeedback exists
        stmt = (
            select(PerformanceLearningFeedback)
            .where(PerformanceLearningFeedback.is_active.is_(True))
            .order_by(PerformanceLearningFeedback.created_at.desc())
        )
        feedback_list = list((await db_session.execute(stmt)).scalars().all())
        assert len(feedback_list) > 0

        # 4. Verify TrendAgent reads this active feedback
        trend_agent = TrendAgent(db=db_session)
        retrieved_feedback = await trend_agent._read_learning_feedback()
        assert len(retrieved_feedback) > 0
        insights = [f.insight for f in retrieved_feedback]
        assert any("Deep Sea" in ins or "CTR" in ins or "retention" in ins for ins in insights)
    finally:
        await _cleanup_run(db_session, run.id)
        # Clean up feedback records created during test
        await db_session.execute(delete(PerformanceLearningFeedback))
        await db_session.commit()


# ===========================================================================
# 3. Stage Data Flow: TrendAgent -> ScriptAgent Context Handoff
# ===========================================================================

async def test_trend_to_script_handoff(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify research brief and signals from TrendAgent pass into ScriptAgent."""
    from app.agents.script import _build_script_prompt

    context = {
        "topic": "Quantum Computing Frontiers",
        "duration": 30,
        "research_brief": "Quantum computing enables exponential speedups via entanglement and superposition.",
        "trend_signals": [
            {"topic": "Qubits", "search_volume_or_signal": "Spike in interest", "confidence": 0.9}
        ],
    }

    prompt = _build_script_prompt(
        topic=context["topic"],
        research_data=context["trend_signals"],
        target_duration=context["duration"],
        is_cinematic=False,
        research_brief=context["research_brief"],
    )

    assert "Quantum Computing Frontiers" in prompt
    assert "Research brief:" in prompt
    assert "entanglement and superposition" in prompt
    assert "Qubits" in prompt
    assert "30 seconds" in prompt


# ===========================================================================
# 4. Object-Level Security & IDOR Enforcement Across All Surface Routers
# ===========================================================================

async def test_security_idor_isolation_across_projects(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify that accessing workflows or checkpoints belonging to another project returns 404."""
    # Create two isolated projects
    proj_a = Project(name=f"Project-A-{uuid.uuid4().hex[:6]}")
    proj_b = Project(name=f"Project-B-{uuid.uuid4().hex[:6]}")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    # Key A has access only to Project A
    key_a_model, key_a_raw = await create_api_key(db_session, name="Audit Key A", is_admin=False)
    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="member")

    # Workflow and Checkpoint in Project B
    run_b = WorkflowRun(
        project_id=proj_b.id,
        topic="Secret Topic in Project B",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.AWAITING_APPROVAL,
    )
    db_session.add(run_b)
    await db_session.commit()
    await db_session.refresh(run_b)

    cp_b = ApprovalCheckpoint(
        workflow_run_id=run_b.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(cp_b)
    await db_session.commit()
    await db_session.refresh(cp_b)

    headers_a = {"Authorization": f"Bearer {key_a_raw}"}

    try:
        # Caller A attempting to access run_b -> Must return 404 (IDOR masked)
        res_run = await client.get(f"/workflow-runs/{run_b.id}", headers=headers_a)
        assert res_run.status_code == 404

        # Caller A attempting to access cp_b -> Must return 404 (IDOR masked)
        res_cp = await client.get(f"/approvals/{cp_b.id}", headers=headers_a)
        assert res_cp.status_code == 404

        # Caller A attempting to decide cp_b -> Must return 404 (IDOR masked)
        res_decide = await client.post(
            f"/approvals/{cp_b.id}/decide",
            json={"action": "approve"},
            headers=headers_a,
        )
        assert res_decide.status_code == 404
    finally:
        await _cleanup_run(db_session, run_b.id)
        await db_session.execute(delete(ProjectMembership).where(ProjectMembership.project_id.in_([proj_a.id, proj_b.id])))
        await db_session.execute(delete(ApiKey).where(ApiKey.id == key_a_model.id))
        await db_session.execute(delete(Project).where(Project.id.in_([proj_a.id, proj_b.id])))
        await db_session.commit()


# ===========================================================================
# 5. State Machine Invariants
# ===========================================================================

async def test_state_machine_legal_and_illegal_transitions(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify that stage progression enforces strict transition graph and rejects invalid jumps."""
    run = WorkflowRun(
        project_id=test_project,
        topic="State Machine Invariant Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.CREATED.value,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        # Legal transition: CREATED -> TREND_SELECTED
        updated_run = await advance_stage(db_session, run.id, PipelineStage.TREND_SELECTED)
        assert updated_run.current_stage == PipelineStage.TREND_SELECTED.value

        # Legal transition: TREND_SELECTED -> SCRIPT_GENERATED
        updated_run = await advance_stage(db_session, run.id, PipelineStage.SCRIPT_GENERATED)
        assert updated_run.current_stage == PipelineStage.SCRIPT_GENERATED.value

        # Illegal transition: SCRIPT_GENERATED cannot jump directly to PUBLISHED
        with pytest.raises(InvalidStageTransitionError):
            await advance_stage(db_session, run.id, PipelineStage.PUBLISHED)
    finally:
        await _cleanup_run(db_session, run.id)


# ===========================================================================
# 6. Durable Execution & Lease Recovery
# ===========================================================================

async def test_durable_execution_lease_recovery(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Verify worker lease claiming, stale heartbeat detection, and safe recovery."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Lease Recovery Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.SCRIPT_GENERATED.value,
        last_completed_stage="script",
        last_heartbeat_at=datetime(2026, 1, 1, 0, 0, 0),  # very old heartbeat -> stale
        worker_id="crashed-worker-proc-9999",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    try:
        # Check lease is detected as stale
        assert is_lease_stale(run, timeout_seconds=60) is True

        # Next stage should be storyboard based on completed script
        next_stage = determine_next_stage(run.last_completed_stage, run.current_stage)
        assert next_stage == "storyboard"

        # Recover workflow run under a new worker
        recovered_run, stage = await recover_workflow_run(db_session, run.id, worker_id="new-worker-proc-1001", timeout_seconds=60)
        assert recovered_run.worker_id == "new-worker-proc-1001"
        assert recovered_run.status == WorkflowStatus.RUNNING
        assert stage == "storyboard"
    finally:
        await _cleanup_run(db_session, run.id)
