"""
Simple CRUD service for WorkflowRun — the replacement for a
Repository-pattern abstraction.

Beginner note: a "Repository" pattern usually wraps every table in its
own class with methods like `get_by_id`, `create`, `update`, purely so
you could theoretically swap out the database later. For a solo
developer on one Postgres instance, that indirection buys you nothing
and adds a file per table. Instead: plain functions that take a
session and do the SQLAlchemy query directly. When logic gets more
complex than a single query (e.g. "create a WorkflowRun AND its first
ApprovalCheckpoint AND log it"), it becomes its own function here —
not a new abstraction layer.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import WorkflowRun


async def create_workflow_run(
    db: AsyncSession, project_id: uuid.UUID, topic: str | None = None
) -> WorkflowRun:
    run = WorkflowRun(project_id=project_id, topic=topic)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def get_workflow_run(db: AsyncSession, run_id: uuid.UUID) -> WorkflowRun | None:
    result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    return result.scalar_one_or_none()


async def list_workflow_runs(
    db: AsyncSession, project_id: uuid.UUID | None = None
) -> list[WorkflowRun]:
    stmt = select(WorkflowRun)
    if project_id:
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
