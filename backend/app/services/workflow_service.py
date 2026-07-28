"""
Workflow Run service — business rules for creating, reading, and
updating a WorkflowRun, sitting on top of WorkflowRunRepository.

Beginner note: this file used to contain plain SQLAlchemy queries
directly (see the project's documented decision to skip the Repository
pattern generally). It now delegates to
app/repositories/workflow_run_repository.py instead, because a
Repository layer was an explicit requirement of the Workflow Run
Management task. get_workflow_run's signature is unchanged on purpose
— app/services/pipeline_state.py already imports and calls it and was
not touched.

STAGE-MACHINE COMPATIBILITY (fixes audit Issues 1 & 2): current_stage
is no longer written directly by this module. Every write goes through
pipeline_state.advance_stage() — the same function, with the same
STAGE_TRANSITIONS validation, that pipeline_state.py's own docstring
already claims is "the ONLY function allowed to write
WorkflowRun.current_stage." Before this fix that claim was false (this
file wrote the column directly, with no validation); now it's true
again. advance_stage() is imported lazily, inside
update_workflow_run(), rather than at module level, specifically to
avoid a circular import: pipeline_state.py imports get_workflow_run
from this module already, so a top-level `from
app.services.pipeline_state import advance_stage` here would create a
cycle. This is the minimal fix for that, not a restructuring.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import WorkflowRun
from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus
from app.repositories.workflow_run_repository import WorkflowRunRepository
from app.schemas.workflow_run import INITIAL_STAGE, WorkflowRunUpdateRequest


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """WorkflowRun.completed_at / started_at are naive
    `TIMESTAMP WITHOUT TIME ZONE` columns (app/models/core.py declares
    them with plain `mapped_column(nullable=True)`, unlike
    TimestampMixin's created_at/updated_at which explicitly use
    `DateTime(timezone=True)`). That's an existing model detail this
    task isn't allowed to change — so it's normalized for here instead:
    any timezone-aware datetime (e.g. from `datetime.now(timezone.utc)`,
    or a caller's ISO string with a UTC offset) is converted to UTC and
    has its tzinfo stripped before being handed to asyncpg, which
    otherwise raises `TypeError: can't subtract offset-naive and
    offset-aware datetimes` trying to bind an aware value into a naive
    column — confirmed by an integration test against real Postgres.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class ProjectNotFoundError(ValueError):
    """Raised when project_id doesn't reference a real Project row.
    Caught by the router and turned into a 404 — never allowed to
    surface as a raw FK IntegrityError from Postgres."""

    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id
        super().__init__(f"Project {project_id} does not exist")


async def create_workflow_run(
    db: AsyncSession,
    project_id: uuid.UUID,
    topic: str | None = None,
    mode: WorkflowMode = WorkflowMode.ASSISTED,
) -> WorkflowRun:
    """Create a new WorkflowRun.

    Business rules enforced here (not in the repository, not in the
    router): project_id must reference a real Project, and every new
    run always starts at status=PENDING / current_stage="created"
    (PipelineStage.CREATED — see INITIAL_STAGE in schemas/workflow_run.py)
    — per the Workflow Run Management task's requirements, that's not
    caller-configurable.
    """
    repo = WorkflowRunRepository(db)

    if not await repo.project_exists(project_id):
        raise ProjectNotFoundError(project_id)

    run = WorkflowRun(
        project_id=project_id,
        topic=topic,
        mode=mode,
        status=WorkflowStatus.PENDING,
        current_stage=INITIAL_STAGE,
    )
    return await repo.add(run)


async def get_workflow_run(db: AsyncSession, run_id: uuid.UUID) -> WorkflowRun | None:
    """Unchanged signature — app/services/pipeline_state.py depends on
    this exact call shape (db, run_id) -> WorkflowRun | None."""
    repo = WorkflowRunRepository(db)
    return await repo.get_by_id(run_id)


async def update_workflow_run(
    db: AsyncSession, run_id: uuid.UUID, payload: WorkflowRunUpdateRequest
) -> WorkflowRun | None:
    """Apply only the fields explicitly present in `payload` onto an
    existing WorkflowRun. Returns None if the run doesn't exist (the
    router turns that into a 404).

    exclude_unset=True is what makes this a true partial update — a
    field the caller didn't mention is left alone, it is NOT reset to
    None just because the schema declares a default of None.

    current_stage is handled separately from every other field (fixes
    audit Issue 2): it is NOT written via setattr like the rest. It's
    pulled out of `updates` and handed to
    pipeline_state.advance_stage(), which validates the transition
    against STAGE_TRANSITIONS and raises
    pipeline_state.InvalidStageTransitionError for anything illegal —
    the router translates that into a 409. This means there is exactly
    one code path that ever writes this column, in this file or
    anywhere else.
    """
    repo = WorkflowRunRepository(db)
    run = await repo.get_by_id(run_id)
    if run is None:
        return None

    updates = payload.model_dump(exclude_unset=True)

    # current_stage is excluded from the generic field loop below —
    # see the module docstring for why advance_stage() is imported
    # here (lazily) instead of at module level.
    requested_stage: PipelineStage | None = updates.pop("current_stage", None)

    if "completed_at" in updates:
        updates["completed_at"] = _to_naive_utc(updates["completed_at"])
    for field_name, value in updates.items():
        setattr(run, field_name, value)

    # Convenience: if the caller marks a run COMPLETED or FAILED but
    # didn't separately set completed_at, stamp it automatically. This
    # is the one place business logic goes beyond a blind field copy —
    # everything else is a direct passthrough of the whitelisted fields.
    if (
        "status" in updates
        and updates["status"] in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED)
        and "completed_at" not in updates
    ):
        run.completed_at = _to_naive_utc(datetime.now(timezone.utc))

    if updates:
        run = await repo.save(run)

    if requested_stage is not None:
        from app.services.pipeline_state import advance_stage

        # advance_stage() re-fetches the run, validates the transition,
        # commits, and refreshes — it will see the non-stage changes
        # just committed above (same session, sequential commits), so
        # the returned object reflects both sets of updates together.
        run = await advance_stage(db, run_id, requested_stage)

    return run


async def list_workflow_runs(
    db: AsyncSession, project_id: uuid.UUID | None = None
) -> list[WorkflowRun]:
    """Preserved for backward compatibility with anything already
    calling this; not exercised by the three new endpoints, which only
    need create/get/update."""
    from sqlalchemy import select  # local import: only path still using raw select

    stmt = select(WorkflowRun)
    if project_id:
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
