"""
Workflow State Machine + Pipeline Resume.

Beginner note: `WorkflowRun.current_stage` already existed as a free
string (Sprint 2). This file adds the two things a "state machine"
actually needs on top of that column: (1) a fixed transition table so
a run can't jump from SCRIPT_GENERATED straight to PUBLISHED, and
(2) `resume_stage()`, which is Pipeline Resume: on restart, n8n (or a
recovery script) calls this to find out exactly where to continue,
instead of re-running the whole pipeline from scratch.

Every WorkflowRun is always in exactly ONE PipelineStage — enforced by
only ever writing it through `advance_stage()` below.

Transition table matches the orchestrator pipeline exactly.
VALIDATION_FAILED and RETRY are legacy stages kept for backward
compatibility but have no transitions in the current pipeline.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.log import EventType, log_event
from app.models.core import WorkflowRun
from app.models.enums import PipelineStage
from app.services.workflow_service import get_workflow_run

# Happy-path edges exactly as orchestrator.py advances through its
# _PIPELINE stages. Self-loops exist where multiple logical stages
# (voice/video, thumbnail/storage) map to the same PipelineStage.
STAGE_TRANSITIONS: dict[PipelineStage, set[PipelineStage]] = {
    PipelineStage.CREATED: {PipelineStage.TREND_SELECTED},
    PipelineStage.TREND_SELECTED: {PipelineStage.SCRIPT_GENERATED},
    PipelineStage.SCRIPT_GENERATED: {PipelineStage.STORYBOARD_GENERATED},
    PipelineStage.STORYBOARD_GENERATED: {PipelineStage.PROMPT_GENERATED},
    PipelineStage.PROMPT_GENERATED: {PipelineStage.IMAGE_GENERATED},
    PipelineStage.IMAGE_GENERATED: {PipelineStage.VIDEO_GENERATED},
    PipelineStage.VIDEO_GENERATED: {PipelineStage.VIDEO_GENERATED, PipelineStage.APPROVED},
    PipelineStage.APPROVED: {PipelineStage.APPROVED, PipelineStage.PUBLISHED},
    PipelineStage.PUBLISHED: {PipelineStage.ANALYTICS_COLLECTED},
    PipelineStage.ANALYTICS_COLLECTED: {PipelineStage.LEARNING_UPDATED},
    PipelineStage.LEARNING_UPDATED: set(),
    PipelineStage.VALIDATION_FAILED: set(),
    PipelineStage.RETRY: set(),
}


class InvalidStageTransitionError(RuntimeError):
    pass


def _current_stage(run: WorkflowRun) -> PipelineStage:
    if run.current_stage is None:
        return PipelineStage.CREATED
    return PipelineStage(run.current_stage)


async def advance_stage(
    db: AsyncSession, run_id: uuid.UUID, to_stage: PipelineStage
) -> WorkflowRun:
    """The ONLY function allowed to write WorkflowRun.current_stage.
    Rejects any transition not listed in STAGE_TRANSITIONS."""
    run = await get_workflow_run(db, run_id)
    if run is None:
        raise ValueError(f"WorkflowRun {run_id} not found")

    from_stage = _current_stage(run)
    allowed = STAGE_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise InvalidStageTransitionError(
            f"Cannot advance {run_id} from {from_stage.value} to {to_stage.value}. "
            f"Allowed next stages: {[s.value for s in allowed]}"
        )

    run.current_stage = to_stage.value
    await db.commit()
    await db.refresh(run)

    await log_event(
        EventType.STAGE_ADVANCED,
        message=f"{from_stage.value} -> {to_stage.value}",
        workflow_run_id=run_id,
    )
    return run


async def resume_stage(db: AsyncSession, run_id: uuid.UUID) -> PipelineStage:
    """Pipeline Resume: on crash recovery, call this instead of
    restarting from CREATED. Returns the last successfully-completed
    stage so the caller (n8n, or a recovery script) knows exactly which
    step to run next — skipping everything already paid for."""
    run = await get_workflow_run(db, run_id)
    if run is None:
        raise ValueError(f"WorkflowRun {run_id} not found")

    stage = _current_stage(run)
    await log_event(
        EventType.PIPELINE_RESUMED,
        message=f"Resuming {run_id} from {stage.value}",
        workflow_run_id=run_id,
    )
    return stage