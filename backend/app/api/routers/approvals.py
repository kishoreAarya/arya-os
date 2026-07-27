"""
Approval router — one of several routers under the SINGLE FastAPI app
(per the architecture decision: no microservices, one app, multiple
routers, shared database).

n8n's job: pause the workflow after each stage, POST here to create a
checkpoint, then poll GET until a decision has been recorded (or use
its own wait-for-webhook node if you wire a callback later).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.models.approval import ApprovalCheckpoint
from app.models.enums import ApprovalAction, ApprovalStage

router = APIRouter(prefix="/approvals", tags=["approvals"])


class CreateCheckpointRequest(BaseModel):
    workflow_run_id: uuid.UUID
    stage: ApprovalStage
    reference_table: str
    reference_id: uuid.UUID


class DecideCheckpointRequest(BaseModel):
    action: ApprovalAction
    reviewer_notes: str | None = None


@router.post("/")
async def create_checkpoint(
    payload: CreateCheckpointRequest, db: AsyncSession = Depends(get_db)
):
    """n8n calls this right after generating something, to pause and
    wait for a human (or an autonomous-mode auto-approve, later) before
    the workflow is allowed to continue."""
    checkpoint = ApprovalCheckpoint(
        workflow_run_id=payload.workflow_run_id,
        stage=payload.stage,
        reference_table=payload.reference_table,
        reference_id=payload.reference_id,
    )
    db.add(checkpoint)
    await db.commit()
    await db.refresh(checkpoint)
    return checkpoint


@router.get("/{checkpoint_id}")
async def get_checkpoint(checkpoint_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """n8n polls this — action is null until a human decides."""
    result = await db.execute(
        select(ApprovalCheckpoint).where(ApprovalCheckpoint.id == checkpoint_id)
    )
    checkpoint = result.scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return checkpoint


@router.post("/{checkpoint_id}/decide")
async def decide_checkpoint(
    checkpoint_id: uuid.UUID,
    payload: DecideCheckpointRequest,
    db: AsyncSession = Depends(get_db),
):
    """The dashboard calls this when you click Approve / Reject / Retry
    / Manual Edit / Continue. This is the ONLY place a decision gets
    written — Telegram only notifies, per the architecture doc."""
    result = await db.execute(
        select(ApprovalCheckpoint).where(ApprovalCheckpoint.id == checkpoint_id)
    )
    checkpoint = result.scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    checkpoint.action = payload.action
    checkpoint.reviewer_notes = payload.reviewer_notes
    checkpoint.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(checkpoint)
    return checkpoint


@router.get("/pending/{workflow_run_id}")
async def list_pending_checkpoints(
    workflow_run_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """Dashboard calls this to show 'what's waiting on you right now'
    for a given run."""
    result = await db.execute(
        select(ApprovalCheckpoint).where(
            ApprovalCheckpoint.workflow_run_id == workflow_run_id,
            ApprovalCheckpoint.action.is_(None),
        )
    )
    return list(result.scalars().all())
