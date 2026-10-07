"""Phase 53B-T shared fixtures: seed an APPROVED publish target.

Creates the minimal real-model chain the publish approval gate requires
(Project -> WorkflowRun -> Video -> THUMBNAIL ApprovalCheckpoint ->
APPROVE ApprovalDecision) plus cleanup helpers. Offline: touches only
the local test database; no providers are contacted here.
"""
import uuid
from datetime import UTC, datetime

from app.models.approval import ApprovalCheckpoint, ApprovalDecision
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage
from app.models.media import Video


async def seed_approved_publish_target(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Return (workflow_run_id, video_id) authorized for publishing.

    Caller is responsible for cleanup via cleanup_publish_target()."""
    project = Project(name=f"publish-gate-{uuid.uuid4()}")
    session.add(project)
    await session.flush()
    run = WorkflowRun(project_id=project.id)
    session.add(run)
    await session.flush()
    video = Video(workflow_run_id=run.id, storage_path=f"gate/{uuid.uuid4()}.mp4")
    session.add(video)
    await session.flush()
    checkpoint = ApprovalCheckpoint(
        workflow_run_id=run.id,
        stage=ApprovalStage.THUMBNAIL,
        reference_table="videos",
        reference_id=video.id,
        action=ApprovalAction.APPROVE,
        decided_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(checkpoint)
    await session.flush()
    session.add(
        ApprovalDecision(
            checkpoint_id=checkpoint.id,
            sequence_number=1,
            action=ApprovalAction.APPROVE,
            decided_at=datetime.now(UTC).replace(tzinfo=None),
            decided_by="53B-T-seeder",
        )
    )
    await session.commit()
    return run.id, video.id


async def cleanup_publish_target(session, workflow_run_id: uuid.UUID) -> None:
    """Delete the seeded chain (decisions, checkpoint, video, run,
    project). Best-effort ordering respects FKs; approval_decisions and
    approval_checkpoints are removed first."""
    from app.models.media import Video as VideoModel
    from sqlalchemy import delete, select

    run = (
        await session.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        return
    checkpoint_ids = list(
        (
            await session.execute(
                select(ApprovalCheckpoint.id).where(
                    ApprovalCheckpoint.workflow_run_id == run.id
                )
            )
        )
        .scalars()
        .all()
    )
    if checkpoint_ids:
        await session.execute(
            delete(ApprovalDecision).where(
                ApprovalDecision.checkpoint_id.in_(checkpoint_ids)
            )
        )
    await session.execute(
        delete(ApprovalCheckpoint).where(
            ApprovalCheckpoint.workflow_run_id == run.id
        )
    )
    # Same pre-existing schema gap conftest.py works around: SystemLog rows
    # reference workflow_runs without ON DELETE CASCADE.
    from app.models.system import SystemLog

    await session.execute(
        delete(SystemLog).where(SystemLog.workflow_run_id == run.id)
    )
    await session.execute(
        delete(VideoModel).where(VideoModel.workflow_run_id == run.id)
    )
    await session.delete(run)
    await session.commit()
    project = (
        await session.execute(select(Project).where(Project.id == run.project_id))
    ).scalar_one_or_none()
    if project is not None:
        await session.delete(project)
        await session.commit()
