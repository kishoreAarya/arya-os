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
from app.models.approval import ApprovalCheckpoint, ApprovalDecision
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
    # OPTIONAL caller-asserted provenance ONLY. The current authentication
    # (shared service API key) provides no human identity and none is
    # invented: this field is non-authoritative metadata, exactly like the
    # jobs-surface user_id (D3). Blank is stored as NULL.
    decided_by: str | None = None
    # Phase 54B-I4: STRICT consistency echo, never a selector. When the
    # checkpoint is content-bound to a publication manifest, a decision
    # MUST echo the server-bound manifest_id; a mismatched or stale id is
    # rejected (409) BEFORE any decision event is written. Omitting the
    # echo on a bound checkpoint is rejected (422). Unbound checkpoints
    # (all other stages, legacy rows) are unaffected; sending an echo to
    # an unbound checkpoint is a 409 mismatch.
    manifest_id: uuid.UUID | None = None


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
    / Manual Edit / Continue (and now Revoke). This is the ONLY place a
    decision gets written — Telegram only notifies, per the architecture
    doc.

    Decision-history architecture (operator-locked): APPEND-ONLY. Each
    call locks the checkpoint row (FOR UPDATE), allocates the next
    per-checkpoint sequence_number under that lock, appends ONE immutable
    ApprovalDecision event (server-generated decided_at — the future TTL
    anchor), and refreshes the checkpoint's current-state cache from that
    event — all in a single transaction. Previous events are NEVER
    modified. REJECT ("request not authorized") and REVOKE ("a previously
    existing authorization is withdrawn") are distinct, permanently
    recorded semantics."""
    from sqlalchemy import func

    result = await db.execute(
        select(ApprovalCheckpoint)
        .where(ApprovalCheckpoint.id == checkpoint_id)
        .with_for_update()
    )
    checkpoint = result.scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    # Phase 54B-I4: manifest consistency — verified UNDER the row lock
    # and BEFORE any event is appended, so a stale review can never
    # become a confusing decision in the append-only history. The
    # server's pre-bound manifest stays authoritative; the client can
    # neither select nor replace it.
    if checkpoint.publication_manifest_id is not None:
        if payload.manifest_id is None:
            raise HTTPException(
                status_code=422,
                detail="this checkpoint is content-bound to a publication "
                "manifest; the decision must echo that manifest_id for "
                "consistency (fetch the current review state first)",
            )
        if payload.manifest_id != checkpoint.publication_manifest_id:
            raise HTTPException(
                status_code=409,
                detail="manifest_id does not match the manifest bound to this "
                "checkpoint; the server-bound manifest is authoritative — "
                "the reviewed content changed, fetch the current review "
                "state and re-review",
            )
    elif payload.manifest_id is not None:
        raise HTTPException(
            status_code=409,
            detail="manifest_id was provided but this checkpoint is not "
            "content-bound to any publication manifest",
        )

    next_sequence = (
        await db.execute(
            select(func.coalesce(func.max(ApprovalDecision.sequence_number), 0)).where(
                ApprovalDecision.checkpoint_id == checkpoint_id
            )
        )
    ).scalar() + 1

    event = ApprovalDecision(
        checkpoint_id=checkpoint.id,
        sequence_number=next_sequence,
        action=payload.action,
        # Server-generated immutable event timestamp. Stored as naive UTC —
        # the repository's timestamp-without-timezone convention
        # (creator.py precedent; capabilities test helpers do the same).
        decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        decided_by=(payload.decided_by.strip() or None) if payload.decided_by else None,
        reviewer_notes=payload.reviewer_notes,
    )
    db.add(event)

    # Current-state cache refresh — atomic with the event append; the
    # cache always equals the latest decision event.
    checkpoint.action = payload.action
    checkpoint.reviewer_notes = payload.reviewer_notes
    checkpoint.decided_at = event.decided_at
    await db.commit()
    await db.refresh(checkpoint)
    return checkpoint


@router.get("/{checkpoint_id}/decisions")
async def list_decisions(
    checkpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """The complete, ordered, append-only decision history for one
    checkpoint. Ordered by the deterministic per-checkpoint
    sequence_number (allocated under the checkpoint row lock), never by
    timestamps or unordered query results. The original APPROVE event
    remains permanently observable here after any REVOKE."""
    checkpoint = await db.get(ApprovalCheckpoint, checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    result = await db.execute(
        select(ApprovalDecision)
        .where(ApprovalDecision.checkpoint_id == checkpoint_id)
        .order_by(ApprovalDecision.sequence_number)
    )
    return list(result.scalars().all())


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
