"""Server-side publish approval gate (Phase 53B, finding 53A-01).

AryaOS owns approval policy: publishing must not dispatch unless the
workflow run's terminal human checkpoint (THUMBNAIL — the last stage a
human approves before storage/metadata/publishing per the documented
pipeline; see models/approval.py docstring and
workflows/orchestrator.py stage mapping) holds an APPROVE state.

Semantics (fail closed on everything else):
- The exact video being published must exist and belong to the exact
  workflow run being claimed (video.workflow_run_id match).
- The latest THUMBNAIL-stage checkpoint for that run must exist and its
  cached action must be APPROVE.
- The authoritative append-only history (latest ApprovalDecision by
  sequence_number) must also be APPROVE — a REVOKE or REJECT as the
  latest decision denies dispatch even if a stale cache said otherwise.
- TTL (ApprovalTtlPolicy): an approval with decided_at expires at
  decided_at + ttl_seconds using the stage-specific override when
  present, else the global default row; no policy row configured means
  no expiry (perpetual), and decided_at IS NULL (legacy Model-A rows)
  is perpetual by ratified semantics.

Known binding gap (reported, not enforced): ApprovalCheckpoint.parameter_digest
is the Hermes Model-B digest of capability parameters — it does NOT cover
publish content or publish parameters, so this gate binds authorization to
(run, stage, video-membership, decision, TTL) but NOT to a content digest.
Complete digest binding would require schema/policy work under separate
authorization.

The checkpoint row is locked (FOR UPDATE) for the duration of the
decision read, serializing against decide_checkpoint's own row lock —
a revoke that lands before the gate completes blocks this dispatch, and
a revoke that lands after it has been evaluated cannot un-dispatch what
already started (residual documented in the phase report).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.approval import ApprovalCheckpoint, ApprovalDecision, ApprovalTtlPolicy
from app.models.enums import ApprovalAction, ApprovalStage
from app.models.media import Video

logger = get_logger(__name__)

# The final required human checkpoint before publishing (verified against
# the pipeline stage mapping: thumbnail -> APPROVED; storage/metadata/
# publishing follow without further human gates).
AUTHORIZING_STAGE = ApprovalStage.THUMBNAIL


class PublishApprovalDenied(RuntimeError):
    """Publishing is not authorized. reason_code is a stable, non-sensitive
    machine code (never includes identifiers, notes, or secrets)."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _denied(reason_code: str) -> PublishApprovalDenied:
    logger.warning("publish_approval_gate_denied", reason_code=reason_code)
    return PublishApprovalDenied(reason_code)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def evaluate_authorizing_checkpoint(
    db: AsyncSession,
    checkpoint: ApprovalCheckpoint,
) -> None:
    """Evaluate the cached action, the authoritative append-only latest
    decision, and TTL freshness for one authorizing checkpoint.

    Shared evaluation core (Phase 54B-I5): assert_publish_authorized
    runs it under the checkpoint row lock, and the dispatch-time
    authorize-and-permit transaction runs it again immediately before
    the permit CAS — a denial at either point blocks dispatch. Raises
    PublishApprovalDenied with the same stable reason codes and check
    order as the gate (steps 3-5)."""
    if checkpoint.action != ApprovalAction.APPROVE:
        state = checkpoint.action.value if checkpoint.action is not None else "pending"
        raise _denied(f"checkpoint_{state}")

    decision = (
        await db.execute(
            select(ApprovalDecision)
            .where(ApprovalDecision.checkpoint_id == checkpoint.id)
            .order_by(ApprovalDecision.sequence_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if decision is None or decision.action != ApprovalAction.APPROVE:
        raise _denied("latest_decision_not_approve")

    if checkpoint.decided_at is not None:
        policy = (
            await db.execute(
                select(ApprovalTtlPolicy)
                .where(ApprovalTtlPolicy.stage.in_([AUTHORIZING_STAGE.value, None]))
                .order_by(ApprovalTtlPolicy.stage.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        if policy is not None:
            expires = _as_utc(checkpoint.decided_at) + timedelta(
                seconds=policy.ttl_seconds
            )
            if datetime.now(UTC) >= expires:
                raise _denied("approval_expired")


async def assert_publish_authorized(
    db: AsyncSession,
    workflow_run_id: uuid.UUID | str,
    video_id: uuid.UUID | str,
) -> None:
    """Raise PublishApprovalDenied unless publishing this video under this
    workflow run is authorized. Raises nothing when authorized."""
    # 1. Identifiers must parse — malformed input never authorizes.
    try:
        run_uuid = uuid.UUID(str(workflow_run_id))
        video_uuid = uuid.UUID(str(video_id))
    except (ValueError, TypeError, AttributeError):
        raise _denied("invalid_identifier") from None

    # 2. Exact target binding: the video must exist and belong to the run.
    video = (
        await db.execute(select(Video).where(Video.id == video_uuid))
    ).scalar_one_or_none()
    if video is None:
        raise _denied("unknown_video")
    if video.workflow_run_id != run_uuid:
        raise _denied("video_not_in_workflow_run")

    # 3. Latest THUMBNAIL checkpoint for the run, locked against concurrent
    #    decide/revoke (decide_checkpoint takes the same row lock).
    checkpoint = (
        await db.execute(
            select(ApprovalCheckpoint)
            .where(
                ApprovalCheckpoint.workflow_run_id == run_uuid,
                ApprovalCheckpoint.stage == AUTHORIZING_STAGE,
            )
            .order_by(ApprovalCheckpoint.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if checkpoint is None:
        raise _denied("no_thumbnail_checkpoint")

    # 4-5. Cached action, authoritative history, TTL (shared core).
    await evaluate_authorizing_checkpoint(db, checkpoint)
