"""
Workflow Execution Lease, Heartbeat, and Recovery Service.

Provides persistent, restart-safe execution management:
1. Execution Lease Claiming with row-level locking (SELECT ... FOR UPDATE).
2. Heartbeat tracking to detect orphaned/crashed worker processes.
3. Durable Approval Checkpoint boundaries (execution suspends cleanly; resumes upon decision).
4. Stage Resume Determination: identifies the exact stage to continue without duplicate generation.
5. Context Hydration from persistent artifacts (Scripts, Storyboards, Videos, Media).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.models.approval import ApprovalAction, ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import WorkflowRun
from app.models.enums import ApprovalStage, PipelineStage, WorkflowMode, WorkflowStatus
from app.models.media import Asset, Image, Thumbnail, Video
from app.services.workflow_service import _to_naive_utc

logger = get_logger("arya.services.workflow_execution")


class WorkflowExecutionConflictError(RuntimeError):
    """Raised when an operation conflicts with the current execution lease or lifecycle state."""

    pass


def get_current_worker_id() -> str:
    """Generate or retrieve a unique worker process identifier."""
    pid = os.getpid()
    return f"worker-proc-{pid}"


def is_lease_stale(run: WorkflowRun, timeout_seconds: int | None = None) -> bool:
    """Determine whether an execution lease on a running workflow has expired."""
    if run.status != WorkflowStatus.RUNNING:
        return False

    settings = get_settings()
    timeout = timeout_seconds if timeout_seconds is not None else settings.workflow_lease_timeout_seconds

    if run.last_heartbeat_at is None:
        return True

    now = datetime.now(timezone.utc)
    hb = run.last_heartbeat_at
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    elapsed = (now - hb).total_seconds()
    return elapsed > timeout


async def claim_execution_lease(
    db: AsyncSession,
    run_id: uuid.UUID,
    worker_id: str,
    force: bool = False,
    timeout_seconds: int | None = None,
) -> WorkflowRun:
    """Acquire an exclusive execution lease on a WorkflowRun using row-level locking.

    Raises:
        ValueError: If WorkflowRun does not exist.
        WorkflowExecutionConflictError: If the run is completed, actively leased,
                                        or waiting for approval without force.
    """
    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise ValueError(f"WorkflowRun {run_id} not found")

    if run.status == WorkflowStatus.COMPLETED:
        raise WorkflowExecutionConflictError(f"WorkflowRun {run_id} has already completed")

    if not force:
        # Check active lease conflict
        if run.status == WorkflowStatus.RUNNING:
            if not is_lease_stale(run, timeout_seconds):
                raise WorkflowExecutionConflictError(
                    f"WorkflowRun {run_id} is actively executing (lease held by {run.worker_id or 'another process'})"
                )
            logger.warning(
                "recovering_stale_workflow_lease",
                workflow_run_id=str(run_id),
                previous_worker=run.worker_id,
                last_heartbeat=str(run.last_heartbeat_at),
            )

        # Check awaiting approval state
        if run.status == WorkflowStatus.AWAITING_APPROVAL and run.waiting_checkpoint_id:
            # Check if checkpoint was already decided
            cp = await db.get(ApprovalCheckpoint, run.waiting_checkpoint_id)
            if cp and cp.action is None:
                raise WorkflowExecutionConflictError(
                    f"WorkflowRun {run_id} is awaiting human approval on checkpoint {run.waiting_checkpoint_id}"
                )

    now = _to_naive_utc(datetime.now(timezone.utc))
    run.status = WorkflowStatus.RUNNING
    run.worker_id = worker_id
    run.execution_started_at = now
    run.last_heartbeat_at = now
    run.execution_attempt = (run.execution_attempt or 0) + 1
    run.waiting_checkpoint_id = None
    if run.started_at is None:
        run.started_at = now

    await db.commit()
    await db.refresh(run)

    await log_event(
        EventType.WORKFLOW_STARTED,
        message=f"Execution lease claimed by {worker_id} (attempt #{run.execution_attempt})",
        workflow_run_id=run_id,
    )
    return run


async def update_heartbeat(
    db: AsyncSession,
    run_id: uuid.UUID,
    worker_id: str | None = None,
) -> None:
    """Update the heartbeat timestamp for an active execution lease.

    Raises:
        WorkflowExecutionConflictError: If a worker_id is provided that does not
                                        match the active lease owner.
    """
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"WorkflowRun {run_id} not found")

    if run.status != WorkflowStatus.RUNNING:
        return

    if worker_id and not run.worker_id:
        run.worker_id = worker_id
    elif worker_id and run.worker_id != worker_id:
        raise WorkflowExecutionConflictError(
            f"Worker {worker_id} cannot update heartbeat for lease owned by {run.worker_id}"
        )
    now = _to_naive_utc(datetime.now(timezone.utc))
    run.last_heartbeat_at = now
    await db.commit()


async def finalize_workflow_execution(
    db: AsyncSession,
    run_id: uuid.UUID,
    worker_id: str,
    status: WorkflowStatus,
    total_cost_usd: float | None = None,
    failure_reason: str | None = None,
    completed_at: datetime | None = None,
) -> WorkflowRun:
    """Safely finalize a workflow execution, ensuring the calling worker still owns the lease.

    Uses row-level locking (with_for_update) to prevent race conditions during recovery.
    If the lease was stolen or recovered by another worker, raises WorkflowExecutionConflictError.
    """
    from decimal import Decimal

    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise ValueError(f"WorkflowRun {run_id} not found")

    if run.status != WorkflowStatus.RUNNING:
        raise WorkflowExecutionConflictError(
            f"Worker {worker_id} cannot finalize workflow run {run_id} with status {run.status.value}"
        )

    if run.worker_id != worker_id:
        raise WorkflowExecutionConflictError(
            f"Worker {worker_id} cannot finalize workflow run {run_id} (lease currently owned by {run.worker_id or 'nobody'})"
        )

    now = _to_naive_utc(completed_at or datetime.now(timezone.utc))
    run.status = status
    run.worker_id = None
    run.completed_at = now
    if total_cost_usd is not None:
        run.total_cost_usd = Decimal(str(round(total_cost_usd, 4)))
    if failure_reason is not None:
        run.failure_reason = failure_reason

    await db.commit()
    await db.refresh(run)
    return run


async def suspend_for_approval(
    db: AsyncSession,
    run_id: uuid.UUID,
    checkpoint_id: uuid.UUID,
    worker_id: str | None = None,
) -> WorkflowRun:
    """Transition workflow into persistent AWAITING_APPROVAL state and release the execution lease."""
    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise ValueError(f"WorkflowRun {run_id} not found")

    if run.status != WorkflowStatus.RUNNING:
        raise WorkflowExecutionConflictError(
            f"Cannot suspend workflow run {run_id} in status {run.status.value}"
        )

    if worker_id is not None and run.worker_id != worker_id:
        raise WorkflowExecutionConflictError(
            f"Worker {worker_id} cannot suspend workflow run {run_id} (lease currently owned by {run.worker_id or 'nobody'})"
        )

    now = _to_naive_utc(datetime.now(timezone.utc))
    run.status = WorkflowStatus.AWAITING_APPROVAL
    run.waiting_checkpoint_id = checkpoint_id
    run.worker_id = None
    run.last_heartbeat_at = now

    await db.commit()
    await db.refresh(run)

    await log_event(
        EventType.WORKFLOW_AWAITING_APPROVAL,
        message=f"Workflow paused at approval checkpoint {checkpoint_id}",
        workflow_run_id=run_id,
    )
    return run


def determine_next_stage(
    last_completed_stage: str | None,
    current_stage: str | None,
    pipeline: list[str] | None = None,
) -> str:
    """Determine the next pipeline stage to run based on persisted progress."""
    from app.workflows.orchestrator import _PIPELINE

    pipe = pipeline or _PIPELINE

    if not last_completed_stage:
        # Fallback to current_stage mapping if available
        if current_stage == PipelineStage.TREND_SELECTED.value:
            return "script"
        elif current_stage == PipelineStage.SCRIPT_GENERATED.value:
            return "voice" if "voice" in pipe else "storyboard"
        elif current_stage == PipelineStage.STORYBOARD_GENERATED.value:
            return "shot_executor"
        elif current_stage == PipelineStage.VIDEO_GENERATED.value:
            return "thumbnail"
        elif current_stage == PipelineStage.APPROVED.value:
            return "publishing"
        elif current_stage == PipelineStage.PUBLISHED.value:
            return "analytics"
        return pipe[0]

    try:
        idx = pipe.index(last_completed_stage)
        if idx + 1 < len(pipe):
            return pipe[idx + 1]
        return pipe[-1]
    except ValueError:
        pass

    return pipe[0]


async def hydrate_resume_context(
    db: AsyncSession,
    run_id: uuid.UUID,
    initial_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hydrate workflow execution context from persisted database artifacts."""
    context = dict(initial_context or {})
    context["workflow_run_id"] = str(run_id)

    # 1. Script
    s_stmt = select(Script).where(Script.workflow_run_id == run_id).order_by(Script.created_at.desc()).limit(1)
    s_res = await db.execute(s_stmt)
    script = s_res.scalars().first()
    if script:
        context["script_id"] = str(script.id)
        context["script"] = {
            "content": script.content,
            "word_count": script.word_count,
        }
        context["script_content"] = script.content

        # 2. Storyboard
        sb_stmt = select(Storyboard).where(Storyboard.script_id == script.id).order_by(Storyboard.created_at.desc()).limit(1)
        sb_res = await db.execute(sb_stmt)
        storyboard = sb_res.scalars().first()
        if storyboard:
            context["storyboard_id"] = str(storyboard.id)
            context["storyboard"] = storyboard.shots

    # 3. Video
    v_stmt = select(Video).where(Video.workflow_run_id == run_id).order_by(Video.created_at.desc()).limit(1)
    v_res = await db.execute(v_stmt)
    video = v_res.scalars().first()
    if video:
        context["video_id"] = str(video.id)
        context["video_storage_path"] = video.storage_path
        context["video_duration_seconds"] = video.duration_seconds
        context["aspect_ratio"] = video.aspect_ratio

    # 4. Thumbnail
    t_stmt = select(Thumbnail).where(Thumbnail.workflow_run_id == run_id).order_by(Thumbnail.created_at.desc()).limit(1)
    t_res = await db.execute(t_stmt)
    thumb = t_res.scalars().first()
    if thumb:
        context["thumbnail_id"] = str(thumb.id)
        context["thumbnail_storage_path"] = thumb.storage_path

    return context


async def recover_workflow_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    worker_id: str,
    timeout_seconds: int | None = None,
) -> tuple[WorkflowRun, str]:
    """Recover an orphaned or stale workflow run and prepare it for continued execution.

    Returns:
        Tuple of (WorkflowRun, resume_stage_name).
    """
    run = await claim_execution_lease(
        db=db,
        run_id=run_id,
        worker_id=worker_id,
        force=False,
        timeout_seconds=timeout_seconds,
    )

    next_stage = determine_next_stage(run.last_completed_stage, run.current_stage)

    await log_event(
        EventType.PIPELINE_RESUMED,
        message=f"Workflow {run_id} recovered from stage {next_stage}",
        workflow_run_id=run_id,
    )
    return run, next_stage


async def auto_recover_stale_workflow_runs(
    db: AsyncSession,
    timeout_seconds: int | None = None,
) -> list[uuid.UUID]:
    """Find running workflow runs with stale leases and release their leases for safe resumption.

    Returns:
        List of recovered WorkflowRun IDs.
    """
    settings = get_settings()
    timeout = timeout_seconds if timeout_seconds is not None else settings.workflow_lease_timeout_seconds

    stmt = select(WorkflowRun).where(WorkflowRun.status == WorkflowStatus.RUNNING)
    result = await db.execute(stmt)
    running_runs = result.scalars().all()

    recovered_ids: list[uuid.UUID] = []
    for run in running_runs:
        if is_lease_stale(run, timeout):
            logger.warning(
                "auto_recovering_stale_workflow_lease",
                workflow_run_id=str(run.id),
                previous_worker=run.worker_id,
                last_heartbeat=str(run.last_heartbeat_at),
            )
            run.worker_id = None
            recovered_ids.append(run.id)

    if recovered_ids:
        await db.commit()

    return recovered_ids
