"""Artifact lineage — trace a WorkflowRun's full production history."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import get_db
from app.services.authorization_service import verify_workflow_access
from app.services.lineage_service import get_lineage

router = APIRouter(prefix="/lineage", tags=["lineage"])


@router.get("/{workflow_run_id}")
async def lineage(
    workflow_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    await verify_workflow_access(db, principal, workflow_run_id)
    try:
        return await get_lineage(db, workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
