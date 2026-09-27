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

State transitions are committed immediately; each transition helper is
best-effort against the attempt row only (an attempt bookkeeping
failure must never resurrect a blocked or duplicate publication).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt

BLOCKING_STATUSES = (
    PublicationAttemptStatus.PENDING,
    PublicationAttemptStatus.IN_PROGRESS,
    PublicationAttemptStatus.UNKNOWN,
    PublicationAttemptStatus.SUCCEEDED,
)


def derive_intent_key(video_id, platform: str, social_platform: str, integration_id) -> str:
    """Server-derived publication-intent identity. Deterministic; carries
    no credentials (identifiers only)."""
    return f"{video_id}|{platform}|{social_platform}|{integration_id or ''}"


async def _latest_attempt(db: AsyncSession, intent_key: str) -> PublicationAttempt | None:
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
    except Exception:  # noqa: BLE001 — bookkeeping must never resurrect a publication
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001, S110 — rollback best-effort inside the tolerance path
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


async def _transition(
    db: AsyncSession,
    attempt: PublicationAttempt,
    status: PublicationAttemptStatus,
    **fields,
) -> None:
    attempt.status = status
    for name, value in fields.items():
        setattr(attempt, name, value)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001 — bookkeeping must never resurrect a publication
        await db.rollback()  # bookkeeping must never resurrect a publication


async def mark_in_progress(db: AsyncSession, attempt: PublicationAttempt) -> None:
    """Persisted immediately BEFORE the first irreversible external
    publication call (ratified §9)."""
    await _transition(db, attempt, PublicationAttemptStatus.IN_PROGRESS)


async def mark_external_content(db: AsyncSession, attempt: PublicationAttempt, content_id: str) -> None:
    """Persist the provider content id as soon as it is safely available
    (after upload, BEFORE publish) — the crash-recovery anchor."""
    await _transition(
        db, attempt, attempt.status, external_content_id=content_id
    )


async def mark_succeeded(
    db: AsyncSession,
    attempt: PublicationAttempt,
    *,
    external_post_id: str | None,
    public_url: str | None = None,
) -> None:
    await _transition(
        db,
        attempt,
        PublicationAttemptStatus.SUCCEEDED,
        external_post_id=external_post_id,
        public_url=public_url,
    )


async def mark_failed(db: AsyncSession, attempt: PublicationAttempt, error: str) -> None:
    """Confirmed provider rejection, local validation failure, or a
    pre-submission external read failure — evidence supports 'no public
    post was created'."""
    await _transition(db, attempt, PublicationAttemptStatus.FAILED, error=error)


async def mark_unknown(db: AsyncSession, attempt: PublicationAttempt, reason: str) -> None:
    """Ambiguous outcome: an exception/timeout AFTER external submission
    may have occurred. Durable manual-operations state; automatic retry
    is blocked at admission."""
    await _transition(db, attempt, PublicationAttemptStatus.UNKNOWN, error=reason)
