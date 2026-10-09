"""Publication attempt lifecycle/admission service (operator-authorized slice).

The concurrency-safe, database-enforced admission and state-transition
core for the OPERATOR publishing path (agents/publishing.py). The
Hermes publishing.request capability remains dry-run and untouched.

Admission semantics (ratified):
- The publication INTENT is identified by the server-derived
  `intent_key` (video/platform/social/integration family).
- A submission whose intent already has an attempt in PENDING,
  IN_PROGRESS, or UNKNOWN resolves to that EXISTING attempt — never a
  second external publication (UNKNOWN additionally BLOCKS retry as a
  durable manual-operations state).
- An intent whose LATEST attempt is SUCCEEDED also resolves to the
  existing attempt: re-publishing the identical intent is refused
  (duplicate-publication guard). A genuinely new publication intent
  requires new content (a new versioned Video row ⇒ a new family).
- Only a FAILED latest attempt may be retried: a NEW row is created
  with attempt_number+1 (deterministic numbering; the evidence-based
  FAILED definition means no public post exists from that attempt).
- Concurrent duplicate admission is arbitrated by the database
  UNIQUE(intent_key, attempt_number): the loser of the insert race
  re-queries and resolves to the winner's row.

H1 state-machine amendment: every EXECUTION transition is a conditional
compare-and-swap UPDATE (WHERE id = :id AND status IN :expected). A
transition whose expected source statuses no longer hold is REFUSED
(returns False, nothing written) — a late agent transition can never
overwrite an operator resolution or any other concurrent state change.
mark_in_progress is the publication PERMIT: the execution may make the
first irreversible external publication call only after the
PENDING -> IN_PROGRESS CAS succeeds; a refused permit aborts the
publication before any external submission. Transitions remain
fail-closed best-effort against the attempt row only: a commit failure
refuses the transition (an attempt bookkeeping failure must never
resurrect a blocked or duplicate publication).

Phase 54B-I2 anchor semantics: _transition_detailed distinguishes the
three possible write outcomes so the publishing agent can enforce the
MANDATORY external-content-anchor precondition before adapter.publish():
- PERSISTED — positively confirmed: the conditional UPDATE matched
  exactly one row AND the commit returned without raising.
- REFUSED — CAS refusal: the row no longer holds an expected status;
  nothing was written (the operator resolution that moved the row
  stands, per H1).
- UNCERTAIN — the execute or commit RAISED: the local outcome is
  unknown (the write may or may not have landed server-side). Callers
  must fail closed and never treat this as success.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt

BLOCKING_STATUSES = (
    PublicationAttemptStatus.PENDING,
    PublicationAttemptStatus.IN_PROGRESS,
    PublicationAttemptStatus.UNKNOWN,
    PublicationAttemptStatus.SUCCEEDED,
)

# The execution owns the attempt only while it sits in these statuses.
# Once an operator resolution (or any other transition) moves the row,
# every execution-side CAS below refuses.
EXECUTION_OWNED_STATUSES = (
    PublicationAttemptStatus.PENDING,
    PublicationAttemptStatus.IN_PROGRESS,
)


def derive_intent_key(
    video_id, platform: str, social_platform: str, integration_id
) -> str:
    """Server-derived publication-intent identity. Deterministic; carries
    no credentials (identifiers only)."""
    return f"{video_id}|{platform}|{social_platform}|{integration_id or ''}"


async def _latest_attempt(
    db: AsyncSession, intent_key: str
) -> PublicationAttempt | None:
    """Latest attempt for an intent family, or None. Tolerant of lookup
    failures: correctness is backstopped by the database
    UNIQUE(intent_key, attempt_number) — a missed lookup can at worst
    collide on insert, which the admission race path then resolves to
    the existing row (never a second external publication)."""
    from sqlalchemy import select

    try:
        rows = (
            (
                await db.execute(
                    select(PublicationAttempt)
                    .where(PublicationAttempt.intent_key == intent_key)
                    .order_by(PublicationAttempt.attempt_number.desc())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        return rows[0] if rows else None
    except Exception:  # bookkeeping must never resurrect a publication
        try:
            await db.rollback()
        except Exception:  # rollback best-effort inside the tolerance path
            pass
        return None


async def admit_attempt(
    db: AsyncSession,
    *,
    video_id,
    platform: str,
    social_platform: str,
    integration_id,
    workflow_run_id=None,
    scheduled_at: str | None = None,
) -> tuple[PublicationAttempt, bool]:
    """Admit one publication intent. Returns (attempt, created).

    created=False means an existing attempt now OWNS this intent:
      PENDING/IN_PROGRESS -> a concurrent execution is live;
      UNKNOWN             -> ambiguous outcome, retry BLOCKED (manual ops);
      SUCCEEDED           -> already published (duplicate guard).
    Only a FAILED latest attempt (or no attempt) admits a new row.
    """
    intent_key = derive_intent_key(video_id, platform, social_platform, integration_id)
    latest = await _latest_attempt(db, intent_key)
    if latest is not None and latest.status in BLOCKING_STATUSES:
        return latest, False
    next_number = 1 if latest is None else latest.attempt_number + 1
    attempt = PublicationAttempt(
        video_id=video_id,
        workflow_run_id=workflow_run_id,
        platform=platform,
        social_platform=social_platform,
        integration_id=integration_id,
        intent_key=intent_key,
        attempt_number=next_number,
        status=PublicationAttemptStatus.PENDING,
        scheduled_at=scheduled_at,
        # F-12a (ratified): stamp updated_at EXPLICITLY with the
        # application clock — the same authority every execution
        # transition, resolution, and the active-execution floor use —
        # so the floor never compares against a DB-stamped value. The
        # database server_default remains as a fallback only.
        updated_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    try:
        await db.commit()
    except Exception:
        # Concurrent admission lost the UNIQUE(intent_key, attempt_number)
        # race — resolve to the winner's attempt (never a second external
        # publication).
        await db.rollback()
        existing = await _latest_attempt(db, intent_key)
        if existing is not None:
            return existing, False
        raise
    return attempt, True


class TransitionOutcome(enum.Enum):
    """Distinguished outcome of one conditional attempt-row write.

    PERSISTED — positively confirmed success (UPDATE matched one row
    AND the commit returned cleanly). Every other outcome must be
    treated by callers as NOT persisted (fail closed).
    REFUSED   — CAS refusal: nothing written; a concurrent resolution
    of the row stands (H1).
    UNCERTAIN — execute/commit raised: the local outcome is unknown;
    the write may or may not have landed. Never auto-retried.
    """

    PERSISTED = "persisted"
    REFUSED = "refused"
    UNCERTAIN = "uncertain"


async def _transition_detailed(
    db: AsyncSession,
    attempt: PublicationAttempt,
    status: PublicationAttemptStatus | None,
    expected_statuses: tuple[PublicationAttemptStatus, ...],
    **fields,
) -> TransitionOutcome:
    """Conditional compare-and-swap transition (H1) with distinguished
    outcomes (Phase 54B-I2).

    Applies `status` (unless None: status-preserving field write) and
    `fields` ONLY IF the row still holds one of `expected_statuses`.
    PERSISTED means positively confirmed (row matched AND committed).
    REFUSED means the CAS did not match (nothing written; the in-memory
    attempt is refreshed best-effort so callers can report the true
    current status). UNCERTAIN means execute/commit raised — the local
    outcome is unknown and the session is rolled back best-effort.
    """
    values = dict(fields)
    if status is not None:
        values["status"] = status
    values["updated_at"] = datetime.now(timezone.utc)
    try:
        result = await db.execute(
            update(PublicationAttempt)
            .where(
                PublicationAttempt.id == attempt.id,
                PublicationAttempt.status.in_(expected_statuses),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            # The attempt moved underneath this execution (operator
            # resolution or concurrent transition): refuse, never
            # overwrite. Nothing to resurrect.
            await db.rollback()
            try:
                await db.refresh(attempt)
            except Exception:  # refresh is reporting-only
                pass
            return TransitionOutcome.REFUSED
        await db.commit()
    except Exception:  # bookkeeping must never resurrect a publication
        # Execute or commit raised: the local outcome is UNKNOWN (the
        # write may or may not have landed server-side). Roll back
        # best-effort; never report success without positive
        # confirmation (Phase 54B-I2).
        try:
            await db.rollback()
        except Exception:  # best-effort rollback
            pass
        return TransitionOutcome.UNCERTAIN
    if status is not None:
        attempt.status = status
    for name, value in fields.items():
        setattr(attempt, name, value)
    return TransitionOutcome.PERSISTED


async def _transition(
    db: AsyncSession,
    attempt: PublicationAttempt,
    status: PublicationAttemptStatus | None,
    expected_statuses: tuple[PublicationAttemptStatus, ...],
    **fields,
) -> bool:
    """Conditional compare-and-swap transition (H1), bool form.

    True ONLY on positively confirmed success (PERSISTED); False for
    CAS refusal and for execute/commit failure alike (fail-closed
    bookkeeping: an attempt write failure must never resurrect a
    publication). Unchanged contract for every existing caller.
    """
    outcome = await _transition_detailed(
        db, attempt, status, expected_statuses, **fields
    )
    return outcome is TransitionOutcome.PERSISTED


async def mark_in_progress(db: AsyncSession, attempt: PublicationAttempt) -> bool:
    """The publication PERMIT (H1): PENDING -> IN_PROGRESS via CAS.

    Persisted immediately BEFORE the first irreversible external
    publication call (ratified §9). True grants the permit; False means
    the attempt no longer belongs to this execution (e.g., an operator
    resolution landed) and the external publication call must NOT be
    made."""
    return await _transition(
        db,
        attempt,
        PublicationAttemptStatus.IN_PROGRESS,
        (PublicationAttemptStatus.PENDING,),
    )


async def mark_external_content(
    db: AsyncSession, attempt: PublicationAttempt, content_id: str
) -> bool:
    """Persist the provider content id as soon as it is safely available
    (after upload, BEFORE publish) — the crash-recovery anchor.
    Status-preserving; CAS-guarded on the execution-owned statuses.
    Bool contract unchanged: True only on positively confirmed
    persistence."""
    return await _transition(
        db, attempt, None, EXECUTION_OWNED_STATUSES, external_content_id=content_id
    )


async def persist_external_content_anchor(
    db: AsyncSession, attempt: PublicationAttempt, content_id: str
) -> TransitionOutcome:
    """Phase 54B-I2: the MANDATORY pre-publication anchor write, with
    distinguished outcomes.

    adapter.publish() may be called only when this returns PERSISTED:
    a positively confirmed (row matched AND committed) persistence of
    the provider media id. REFUSED (the attempt was resolved
    underneath — that resolution stands) and UNCERTAIN (execute/commit
    raised; the anchor may or may not have landed) both require the
    caller to abort publication. No outcome here is ever auto-retried.
    """
    return await _transition_detailed(
        db, attempt, None, EXECUTION_OWNED_STATUSES, external_content_id=content_id
    )


async def mark_succeeded(
    db: AsyncSession,
    attempt: PublicationAttempt,
    *,
    external_post_id: str | None,
    public_url: str | None = None,
) -> bool:
    return await _transition(
        db,
        attempt,
        PublicationAttemptStatus.SUCCEEDED,
        (PublicationAttemptStatus.IN_PROGRESS,),
        external_post_id=external_post_id,
        public_url=public_url,
    )


async def mark_failed(
    db: AsyncSession, attempt: PublicationAttempt, error: str
) -> bool:
    """Confirmed provider rejection, local validation failure, or a
    pre-submission external read failure — evidence supports 'no public
    post was created'."""
    return await _transition(
        db,
        attempt,
        PublicationAttemptStatus.FAILED,
        EXECUTION_OWNED_STATUSES,
        error=error,
    )


async def mark_unknown(
    db: AsyncSession, attempt: PublicationAttempt, reason: str
) -> bool:
    """Ambiguous outcome: an exception/timeout AFTER external submission
    may have occurred. Durable manual-operations state; automatic retry
    is blocked at admission."""
    return await _transition(
        db,
        attempt,
        PublicationAttemptStatus.UNKNOWN,
        EXECUTION_OWNED_STATUSES,
        error=reason,
    )
