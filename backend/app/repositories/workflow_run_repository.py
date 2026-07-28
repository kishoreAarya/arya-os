"""
WorkflowRun Repository — pure data access, no business rules.

Beginner note: a repository's job stops at "read this row" / "write
that row". It never decides defaults, never validates input, never
knows what a valid status transition looks like — that's the service
layer's job (app/services/workflow_service.py). Keeping that split
means the service layer can be unit-tested with a fake repository,
with no real database involved.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Project, WorkflowRun


class WorkflowRunRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def add(self, workflow_run: WorkflowRun) -> WorkflowRun:
        """Insert a new, not-yet-persisted WorkflowRun instance."""
        self._db.add(workflow_run)
        await self._db.commit()
        await self._db.refresh(workflow_run)
        return workflow_run

    async def get_by_id(self, run_id: uuid.UUID) -> WorkflowRun | None:
        result = await self._db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        return result.scalar_one_or_none()

    async def save(self, workflow_run: WorkflowRun) -> WorkflowRun:
        """Persist in-place attribute changes made to an already-loaded
        row (used by PATCH, after the service applies the whitelisted
        field updates onto the ORM instance)."""
        await self._db.commit()
        await self._db.refresh(workflow_run)
        return workflow_run

    async def project_exists(self, project_id: uuid.UUID) -> bool:
        """Used by the service to turn a bad project_id into a clean
        422/404 instead of letting a raw FK IntegrityError surface."""
        result = await self._db.execute(select(Project.id).where(Project.id == project_id))
        return result.scalar_one_or_none() is not None
