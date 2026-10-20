"""
Approval router — one of several routers under the SINGLE FastAPI app
(per the architecture decision: no microservices, one app, multiple
routers, shared database).

n8n's job: pause the workflow after each stage, POST here to create a
checkpoint, then poll GET until a decision has been recorded (or use
its own wait-for-webhook node if you wire a callback later).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import get_db
from app.models.approval import ApprovalCheckpoint
from app.models.core import WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowStatus
from app.services.authorization_service import (
    get_authorized_project_ids,
    verify_checkpoint_access,
    verify_workflow_access,
)


logger = get_logger("arya.api.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


class CreateCheckpointRequest(BaseModel):
    workflow_run_id: uuid.UUID
    stage: ApprovalStage
    reference_table: str
    reference_id: uuid.UUID

    model_config = ConfigDict(extra="forbid")


class DecideCheckpointRequest(BaseModel):
    action: ApprovalAction
    reviewer_notes: str | None = None
    operator_confirmed: bool | None = None

    model_config = ConfigDict(extra="forbid")


class ApprovalCheckpointResponse(BaseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    stage: ApprovalStage
    reference_table: str
    reference_id: uuid.UUID
    action: ApprovalAction | None = None
    reviewer_notes: str | None = None
    decided_at: datetime | None = None
    decided_by_principal_id: uuid.UUID | None = None
    decided_by_actor_type: str | None = None
    decided_by_principal_name: str | None = None
    created_at: datetime
    updated_at: datetime
    review_content: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


async def _enrich_checkpoint(
    db: AsyncSession, checkpoint: ApprovalCheckpoint
) -> ApprovalCheckpointResponse:
    """Enrich an ApprovalCheckpoint with reviewable content from whitelisted tables."""
    content: dict[str, Any] | None = None
    ref_table = checkpoint.reference_table
    ref_id = checkpoint.reference_id

    try:
        if ref_table == "scripts":
            from app.models.content import Script

            script = await db.get(Script, ref_id)
            if script:
                content = {
                    "type": "script",
                    "content": script.content,
                    "word_count": script.word_count,
                    "validation_notes": script.validation_notes,
                }
        elif ref_table == "storyboards":
            from app.models.content import Storyboard

            sb = await db.get(Storyboard, ref_id)
            if sb:
                content = {
                    "type": "storyboard",
                    "shots": sb.shots,
                    "validation_notes": sb.validation_notes,
                }
        elif ref_table == "images":
            from app.models.media import Image

            img = await db.get(Image, ref_id)
            if img:
                content = {
                    "type": "image",
                    "storage_path": img.storage_path,
                    "shot_number": img.shot_number,
                    "provider_name": img.provider_name,
                }
        elif ref_table == "videos":
            from app.models.media import Video

            vid = await db.get(Video, ref_id)
            if vid:
                content = {
                    "type": "video",
                    "storage_path": vid.storage_path,
                    "title": vid.title,
                    "description": vid.description,
                    "duration_seconds": vid.duration_seconds,
                    "aspect_ratio": vid.aspect_ratio,
                }
        elif ref_table == "thumbnails":
            from app.models.media import Thumbnail

            thumb = await db.get(Thumbnail, ref_id)
            if thumb:
                content = {
                    "type": "thumbnail",
                    "storage_path": thumb.storage_path,
                    "provider_name": thumb.provider_name,
                }
    except Exception as exc:
        logger.warning(
            "approval_content_lookup_failed",
            error=str(exc),
            ref_table=ref_table,
            ref_id=str(ref_id),
        )

    resp = ApprovalCheckpointResponse.model_validate(checkpoint)
    resp.review_content = content
    return resp


@router.post("/", response_model=ApprovalCheckpointResponse)
async def create_checkpoint(
    payload: CreateCheckpointRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApprovalCheckpointResponse:
    """n8n calls this right after generating something, to pause and
    wait for a human (or an autonomous-mode auto-approve, later) before
    the workflow is allowed to continue."""
    await verify_workflow_access(db, principal, payload.workflow_run_id)

    checkpoint = ApprovalCheckpoint(
        workflow_run_id=payload.workflow_run_id,
        stage=payload.stage,
        reference_table=payload.reference_table,
        reference_id=payload.reference_id,
    )
    db.add(checkpoint)
    await db.commit()
    await db.refresh(checkpoint)
    return await _enrich_checkpoint(db, checkpoint)


@router.get("/", response_model=list[ApprovalCheckpointResponse])
async def list_checkpoints_endpoint(
    workflow_run_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100, description="Max checkpoints to return"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalCheckpointResponse]:
    """List approval checkpoints, optionally filtered by workflow_run_id."""
    if principal.is_admin:
        stmt = select(ApprovalCheckpoint).order_by(ApprovalCheckpoint.created_at.desc()).limit(limit)
        if workflow_run_id:
            stmt = stmt.where(ApprovalCheckpoint.workflow_run_id == workflow_run_id)
        result = await db.execute(stmt)
        checkpoints = list(result.scalars().all())
    else:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if not allowed_ids:
            return []
        if workflow_run_id:
            run = await db.get(WorkflowRun, workflow_run_id)
            if not run or run.project_id not in allowed_ids:
                return []
            stmt = (
                select(ApprovalCheckpoint)
                .where(ApprovalCheckpoint.workflow_run_id == workflow_run_id)
                .order_by(ApprovalCheckpoint.created_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            checkpoints = list(result.scalars().all())
        else:
            stmt = (
                select(ApprovalCheckpoint)
                .join(WorkflowRun, ApprovalCheckpoint.workflow_run_id == WorkflowRun.id)
                .where(WorkflowRun.project_id.in_(list(allowed_ids)))
                .order_by(ApprovalCheckpoint.created_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            checkpoints = list(result.scalars().all())

    return [await _enrich_checkpoint(db, cp) for cp in checkpoints]


@router.get("/pending/{workflow_run_id}", response_model=list[ApprovalCheckpointResponse])
async def list_pending_checkpoints(
    workflow_run_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalCheckpointResponse]:
    """Dashboard calls this to show 'what's waiting on you right now'
    for a given run."""
    await verify_workflow_access(db, principal, workflow_run_id)

    result = await db.execute(
        select(ApprovalCheckpoint).where(
            ApprovalCheckpoint.workflow_run_id == workflow_run_id,
            ApprovalCheckpoint.action.is_(None),
        )
    )
    checkpoints = list(result.scalars().all())
    return [await _enrich_checkpoint(db, cp) for cp in checkpoints]


@router.get("/{checkpoint_id}", response_model=ApprovalCheckpointResponse)
async def get_checkpoint(
    checkpoint_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApprovalCheckpointResponse:
    """n8n polls this — action is null until a human decides."""
    checkpoint, _ = await verify_checkpoint_access(db, principal, checkpoint_id)
    return await _enrich_checkpoint(db, checkpoint)


@router.post("/{checkpoint_id}/decide", response_model=ApprovalCheckpointResponse)
async def decide_checkpoint(
    checkpoint_id: uuid.UUID,
    payload: DecideCheckpointRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApprovalCheckpointResponse:
    """The dashboard calls this when you click Approve / Reject / Retry
    / Manual Edit / Continue. This is the ONLY place a decision gets
    written — Telegram only notifies, per the architecture doc."""
    checkpoint, run = await verify_checkpoint_access(db, principal, checkpoint_id, for_update=True)

    if checkpoint.action is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Checkpoint has already been decided: {checkpoint.action.value}",
        )

    checkpoint.action = payload.action
    checkpoint.reviewer_notes = payload.reviewer_notes
    checkpoint.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    checkpoint.decided_by_principal_id = principal.api_key_id
    checkpoint.decided_by_actor_type = principal.principal_type
    checkpoint.decided_by_principal_name = principal.name

    # Update associated WorkflowRun state and trigger resume if approved
    if run:
        if payload.action == ApprovalAction.APPROVE:
            if run.waiting_checkpoint_id == checkpoint.id:
                run.waiting_checkpoint_id = None
            await db.commit()
            await db.refresh(checkpoint)
            try:
                from app.api.routers.workflow_runs import _launch_workflow_resume
                await _launch_workflow_resume(run.id)
            except Exception as exc:
                logger.error("failed_to_launch_workflow_resume", run_id=str(run.id), error=str(exc))
        elif payload.action == ApprovalAction.REJECT:
            run.status = WorkflowStatus.FAILED
            run.failure_reason = f"Rejected at {checkpoint.stage.value} approval checkpoint: {payload.reviewer_notes or 'No reason provided'}"
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.worker_id = None
            if run.waiting_checkpoint_id == checkpoint.id:
                run.waiting_checkpoint_id = None
            await db.commit()
            await db.refresh(checkpoint)
        elif payload.action == ApprovalAction.RETRY:
            if run.waiting_checkpoint_id == checkpoint.id:
                run.waiting_checkpoint_id = None
            await db.commit()
            await db.refresh(checkpoint)
            try:
                from app.api.routers.workflow_runs import _launch_workflow_resume
                stage_val = checkpoint.stage.value
                stage_map = {
                    "video": "video_assembler",
                    "trend_selection": "trend",
                    "image": "shot_executor",
                    "prompt": "storyboard",
                }
                retry_stage = stage_map.get(stage_val, stage_val)
                await _launch_workflow_resume(run.id, resume_stage=retry_stage)
            except Exception as exc:
                logger.error("failed_to_launch_workflow_retry", run_id=str(run.id), error=str(exc))
        else:
            await db.commit()
            await db.refresh(checkpoint)
    else:
        await db.commit()
        await db.refresh(checkpoint)

    return await _enrich_checkpoint(db, checkpoint)


@router.post("/admin/api-keys/{key_id}/promote-human", status_code=status.HTTP_200_OK)
async def promote_key_to_human(
    key_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    """Administratively promote an active API key to human operator status."""
    from app.services.authorization_service import promote_api_key_to_human
    promoted = await promote_api_key_to_human(db, key_id, principal)
    return {
        "status": "promoted",
        "api_key_id": promoted.id,
        "name": promoted.name,
        "principal_type": promoted.principal_type,
    }
