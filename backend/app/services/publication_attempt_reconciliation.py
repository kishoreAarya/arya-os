"""Publication-attempt operator reconciliation (operator-authorized slice).

The operator surface for exiting the durable manual-operations states of
the publication-attempt core (ratified: UNKNOWN is durable manual
operations; automated reconciliation via provider polling is a DEFERRED
contract — this module implements NO polling and NO automatic retry).

Rules (explicit transition matrix):
- UNKNOWN -> SUCCEEDED: requires the external post id AND verified
  external publication evidence. Verification is performed IN the
  resolve operation itself via the existing read-only provider
  check_processing() lookup against the attempt's persisted
  external_content_id anchor; anything other than a provider-confirmed
  "ready" fails closed (no resolution).
- UNKNOWN -> FAILED: requires an explicit non-empty operator
  attestation (the evidence statement that no public post was created).
  F-14a: for SCHEDULED attempts the attestation must additionally
  acknowledge the deferred commitment verbatim ("including scheduled
  posts") — a scheduled provider-side publication may still execute at
  its scheduled time, so the absence of a public post today establishes
  nothing; cancel/verify the scheduled publication with the provider
  first.
- PENDING / IN_PROGRESS -> FAILED: requires explicit operator force AND
  an attestation AND the active-execution floor: the attempt row must
  have been untouched for at least _ACTIVE_EXECUTION_FLOOR (every live
  execution transition rewrites updated_at; provider timeouts are
  seconds). A fresh row is never resolved underneath a possibly-active
  execution.
- F-02a — evidence-gated FAILED resolutions (one-sided): any -> FAILED
  resolution of an ANCHORED attempt consults the existing read-only
  provider evidence lookup (check_processing against the persisted
  external_content_id anchor) after the guards above and before the
  terminal CAS. If the evidence positively reports the publication
  publicly live ("ready" — Postiz post state published/ready, or
  YouTube processing succeeded AND public), the FAILED resolution is
  REFUSED (the attestation is contradicted). Every other outcome —
  processing, failed, not-found, unknown, missing evidence, provider
  error or unavailability — leaves the operator attestation
  authoritative. Unanchored attempts make no provider call. Ratified
  residual: this narrows but does not eliminate the F-02 epistemic
  race (TOCTOU between lookup and CAS; provider-side late completion;
  unanchored-but-dispatched attempts bypass the gate).
- IN_PROGRESS -> SUCCEEDED (H2, evidence-based): requires the external
  post id AND the same fail-closed in-resolve provider verification as
  UNKNOWN -> SUCCEEDED AND the active-execution floor — the crash
  window where the provider accepted the publication but the execution
  died before persisting SUCCEEDED. PENDING -> SUCCEEDED remains
  illegal (no irreversible external call was ever made from PENDING).
- SUCCEEDED -> * and FAILED -> * are illegal (FAILED already admits
  retry via the existing admission algorithm, which this module never
  touches).

Concurrency: resolution is a conditional compare-and-swap UPDATE
(WHERE id = :id AND status = :expected_status). Zero rows changed means
the attempt moved underneath the operator (a live execution or another
resolution) -> refused, never retried blindly. Symmetrically (H1), the
agent-side execution transitions in services/publication_attempts.py
are CAS-guarded on their expected source statuses: a late agent
transition can never resurrect (overwrite) an operator resolution,
and a refused publication permit (PENDING -> IN_PROGRESS) blocks the
irreversible external publish call.

Auditability: every successful resolution appends an IMMUTABLE SystemLog
event ("PublicationAttemptResolved") carrying the from/to statuses, the
operator inputs, and the verification outcome. The attempt row's
original `error` text is never overwritten — it documents why the
attempt entered its blocking state; the resolution history lives in the
append-only event log.
"""
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt
from app.models.system import SystemLog
from app.platforms.registry import get_platform_adapter

logger = get_logger(__name__)

# A row untouched for this long in PENDING/IN_PROGRESS is treated as
# crashed, not live: every live execution path rewrites updated_at at
# each transition, and provider calls time out in seconds
# (postiz_timeout_seconds default 30s). Generous by two orders of
# magnitude on purpose.
_ACTIVE_EXECUTION_FLOOR = timedelta(minutes=30)

# F-14a (ratified): the mandatory attestation phrase acknowledging that a
# provider-side SCHEDULED publication may still execute at its scheduled
# time even though no public post exists today.
_SCHEDULED_ACK_PHRASE = "including scheduled posts"

_RESOLUTION_TARGETS = frozenset(
    {PublicationAttemptStatus.SUCCEEDED, PublicationAttemptStatus.FAILED}
)
_FORCEABLE_SOURCES = frozenset(
    {PublicationAttemptStatus.PENDING, PublicationAttemptStatus.IN_PROGRESS}
)


class ReconciliationError(Exception):
    """Base: operator-detectable reconciliation failure (never a 500)."""


class AttemptNotFoundError(ReconciliationError):
    pass


class IllegalTransitionError(ReconciliationError):
    pass


class MissingAnchorError(ReconciliationError):
    pass


class VerificationFailedError(ReconciliationError):
    pass


class ActiveExecutionError(ReconciliationError):
    pass


class ConcurrentResolutionError(ReconciliationError):
    pass


async def _get_attempt(db: AsyncSession, attempt_id: UUID) -> PublicationAttempt:
    attempt = (
        (await db.execute(select(PublicationAttempt).where(PublicationAttempt.id == attempt_id)))
        .scalars()
        .first()
    )
    if attempt is None:
        raise AttemptNotFoundError(str(attempt_id))
    return attempt


async def fetch_evidence(db: AsyncSession, attempt_id: UUID) -> dict:
    """Operator-triggered READ-ONLY provider lookup for one attempt.

    Uses the existing adapter check_processing() against the persisted
    external_content_id anchor. Never mutates the attempt, never
    resolves anything, never returns credential material.
    """
    attempt = await _get_attempt(db, attempt_id)
    if not attempt.external_content_id:
        raise MissingAnchorError(
            "attempt has no persisted external_content_id anchor to verify"
        )
    adapter = get_platform_adapter(attempt.platform, db)
    processing = await adapter.check_processing(content_id=attempt.external_content_id)
    return {
        "attempt_id": str(attempt.id),
        "attempt_status": attempt.status.value,
        "external_content_id": attempt.external_content_id,
        "provider_status": processing.status,
        "progress_percent": processing.progress_percent,
        "provider_error": processing.error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _verify_ready_with_provider(db: AsyncSession, attempt: PublicationAttempt) -> dict:
    """Fail-closed in-resolve verification for -> SUCCEEDED resolutions
    (UNKNOWN and IN_PROGRESS sources)."""
    if not attempt.external_content_id:
        raise MissingAnchorError(
            "-> SUCCEEDED requires the persisted external_content_id "
            "anchor to verify against the provider"
        )
    adapter = get_platform_adapter(attempt.platform, db)
    processing = await adapter.check_processing(content_id=attempt.external_content_id)
    if processing.status != "ready":
        raise VerificationFailedError(
            f"provider did not confirm the publication as ready "
            f"(check_processing status: {processing.status!r}"
            + (f"; {processing.error}" if processing.error else "")
            + "). -> SUCCEEDED fails closed without verified evidence."
        )
    return {
        "provider_status": processing.status,
        "progress_percent": processing.progress_percent,
    }


def _require_scheduled_commitment_acknowledgement(
    attempt: PublicationAttempt, attestation: str | None
) -> None:
    """F-14a: an -> FAILED resolution of a SCHEDULED attempt requires the
    operator attestation to explicitly acknowledge the deferred provider
    side publication (it may still execute at its scheduled time; the
    absence of a public post today establishes nothing). Without the
    acknowledgement, refuse with guidance to cancel/verify the scheduled
    publication with the provider first."""
    if not attempt.scheduled_at:
        return
    if _SCHEDULED_ACK_PHRASE not in (attestation or "").lower():
        raise IllegalTransitionError(
            "this attempt dispatched a SCHEDULED provider-side publication "
            "that may still execute at its scheduled time — resolving FAILED "
            "requires cancelling/verifying that scheduled publication with "
            "the provider first, and the attestation must explicitly "
            f"acknowledge deferred commitments (include the phrase "
            f"'{_SCHEDULED_ACK_PHRASE}')"
        )


def _require_beyond_active_execution_floor(attempt: PublicationAttempt) -> None:
    """The active-execution floor for resolutions out of PENDING /
    IN_PROGRESS: the row must have been untouched for at least
    _ACTIVE_EXECUTION_FLOOR — never resolve underneath a possibly-live
    execution."""
    last_touch = attempt.updated_at
    if last_touch is None or last_touch.tzinfo is None:
        raise ActiveExecutionError(
            "cannot establish the attempt's last-touch time; refusing to "
            "resolve a possibly-active execution"
        )
    age = datetime.now(timezone.utc) - last_touch
    if age < _ACTIVE_EXECUTION_FLOOR:
        raise ActiveExecutionError(
            f"attempt was touched {int(age.total_seconds())}s ago — inside the "
            f"{int(_ACTIVE_EXECUTION_FLOOR.total_seconds())}s active-execution "
            "floor; never resolve underneath a possibly-live execution"
        )


def _validate_transition(
    attempt: PublicationAttempt,
    *,
    from_status: PublicationAttemptStatus,
    to_status: PublicationAttemptStatus,
    external_post_id: str | None,
    attestation: str | None,
    force: bool,
) -> None:
    if to_status not in _RESOLUTION_TARGETS:
        raise IllegalTransitionError(
            f"resolution target must be SUCCEEDED or FAILED, not {to_status.value!r}"
        )
    if attempt.status != from_status:
        raise ConcurrentResolutionError(
            f"attempt status is {attempt.status.value}, not the asserted {from_status.value}"
        )
    source = from_status
    if source not in (
        PublicationAttemptStatus.UNKNOWN,
        PublicationAttemptStatus.PENDING,
        PublicationAttemptStatus.IN_PROGRESS,
    ):
        raise IllegalTransitionError(
            f"{source.value} attempts are not resolvable "
            "(FAILED already admits retry via admission; SUCCEEDED is terminal)"
        )
    # F-14a (ratified): deferred-commitment-aware FAILED resolution. A
    # scheduled attempt dispatched a provider-side deferred publication
    # that may still execute at its scheduled time — the absence of a
    # public post TODAY does not establish that none will exist. The
    # operator must explicitly acknowledge the deferred commitment in
    # the attestation (and cancel/verify the scheduled publication with
    # the provider first); a generic confirmation is insufficient.
    if to_status == PublicationAttemptStatus.FAILED:
        _require_scheduled_commitment_acknowledgement(attempt, attestation)
    if source == PublicationAttemptStatus.UNKNOWN:
        if to_status == PublicationAttemptStatus.SUCCEEDED:
            if not (external_post_id or "").strip():
                raise IllegalTransitionError(
                    "UNKNOWN -> SUCCEEDED requires the external post id"
                )
            return
        # UNKNOWN -> FAILED
        if not (attestation or "").strip():
            raise IllegalTransitionError(
                "UNKNOWN -> FAILED requires an explicit operator attestation "
                "(the evidence statement that no public post was created)"
            )
        return
    # Active-execution sources (PENDING / IN_PROGRESS)
    if to_status == PublicationAttemptStatus.SUCCEEDED:
        # H2: evidence-based IN_PROGRESS -> SUCCEEDED (crash window:
        # provider accepted, execution died before persisting success).
        if source != PublicationAttemptStatus.IN_PROGRESS:
            raise IllegalTransitionError(
                "PENDING -> SUCCEEDED is not a legal resolution (no "
                "irreversible external publication call was made from "
                "PENDING)"
            )
        if not (external_post_id or "").strip():
            raise IllegalTransitionError(
                "IN_PROGRESS -> SUCCEEDED requires the external post id"
            )
        _require_beyond_active_execution_floor(attempt)
        return
    # PENDING / IN_PROGRESS -> FAILED
    if to_status != PublicationAttemptStatus.FAILED:
        raise IllegalTransitionError(
            f"{source.value} -> {to_status.value} is not a legal resolution"
        )
    if not force:
        raise IllegalTransitionError(
            f"{source.value} -> FAILED requires explicit operator force"
        )
    if not (attestation or "").strip():
        raise IllegalTransitionError(
            f"{source.value} -> FAILED requires an explicit operator attestation"
        )
    _require_beyond_active_execution_floor(attempt)


async def resolve_attempt(
    db: AsyncSession,
    attempt_id: UUID,
    *,
    from_status: PublicationAttemptStatus,
    to_status: PublicationAttemptStatus,
    external_post_id: str | None = None,
    public_url: str | None = None,
    attestation: str | None = None,
    force: bool = False,
) -> tuple[PublicationAttempt, dict]:
    """Resolve one blocking attempt via conditional CAS update.

    Returns (refreshed_attempt, audit_payload). Raises the typed
    ReconciliationError subclasses for every refusal path. FAILED
    resolutions of anchored attempts are evidence-gated (F-02a):
    refused only when the provider positively reports the publication
    publicly live; every other evidence outcome leaves the operator
    attestation authoritative.
    """
    attempt = await _get_attempt(db, attempt_id)
    _validate_transition(
        attempt,
        from_status=from_status,
        to_status=to_status,
        external_post_id=external_post_id,
        attestation=attestation,
        force=force,
    )
    verification: dict = {}
    if to_status == PublicationAttemptStatus.SUCCEEDED and from_status in (
        PublicationAttemptStatus.UNKNOWN,
        PublicationAttemptStatus.IN_PROGRESS,
    ):
        verification = await _verify_ready_with_provider(db, attempt)

    # F-02a — evidence-gated FAILED resolutions (one-sided). For an
    # ANCHORED attempt, consult the existing provider evidence lookup
    # after all force/floor/attestation guards and BEFORE the terminal
    # CAS: if the provider POSITIVELY reports the publication publicly
    # live ("ready"), the FAILED resolution is refused — the operator
    # may resolve -> SUCCEEDED on that evidence or remove the external
    # publication first. Every other outcome (processing, failed,
    # not-found, unknown, missing evidence, provider error or
    # unavailability) leaves the operator attestation authoritative:
    # the transition proceeds unchanged. The gate never converts
    # evidence into SUCCEEDED, never runs for SUCCEEDED resolutions,
    # makes no provider call for unanchored attempts, and does not
    # alter the CAS below. RATIFIED RESIDUAL: the epistemic race is
    # narrowed, not eliminated — the publication may become public
    # between this lookup and the terminal CAS (TOCTOU), provider-side
    # late application remains possible, and rare
    # unanchored-but-dispatched attempts (anchor-write failure) bypass
    # the gate entirely.
    if to_status == PublicationAttemptStatus.FAILED and attempt.external_content_id:
        gate_evidence = None
        try:
            adapter = get_platform_adapter(attempt.platform, db)
            gate_evidence = await adapter.check_processing(
                content_id=attempt.external_content_id
            )
        except Exception as exc:  # noqa: BLE001 — provider unavailable: the attestation stays authoritative
            logger.warning(
                "publication_attempt_failed_gate_evidence_unavailable",
                attempt_id=str(attempt_id),
                error=str(exc),
            )
        verification = {
            "gate": "failed_resolution_evidence",
            "provider_status": gate_evidence.status if gate_evidence else None,
        }
        if gate_evidence is not None and gate_evidence.status == "ready":
            raise VerificationFailedError(
                f"provider evidence reports the publication for anchor "
                f"{attempt.external_content_id!r} as publicly live "
                "(check_processing status: 'ready') — the FAILED attestation "
                "('no public post was created') is contradicted. Resolve to "
                "SUCCEEDED on this evidence or remove the external "
                "publication first."
            )

    values = {"status": to_status, "updated_at": datetime.now(timezone.utc)}
    if to_status == PublicationAttemptStatus.SUCCEEDED:
        values["external_post_id"] = external_post_id
        if public_url:
            values["public_url"] = public_url
    # FAILED keeps the original error text untouched: it documents WHY the
    # attempt blocked; the resolution itself is recorded in the audit event.

    result = await db.execute(
        update(PublicationAttempt)
        .where(
            PublicationAttempt.id == attempt_id,
            PublicationAttempt.status == from_status,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise ConcurrentResolutionError(
            "attempt changed before the resolution committed "
            "(live execution or concurrent resolution); nothing was written"
        )

    audit_payload = {
        "event": "PublicationAttemptResolved",
        "attempt_id": str(attempt_id),
        "from_status": from_status.value,
        "to_status": to_status.value,
        "external_post_id": external_post_id,
        "public_url": public_url,
        "attestation": attestation,
        "force": force,
        "verification": verification,
        "intent_key": attempt.intent_key,
        "attempt_number": attempt.attempt_number,
    }
    db.add(
        SystemLog(
            workflow_run_id=attempt.workflow_run_id,
            event_type="PublicationAttemptResolved",
            message=json.dumps(audit_payload, default=str),
            level="info",
        )
    )
    await db.commit()
    logger.info(
        "publication_attempt_resolved",
        attempt_id=str(attempt_id),
        from_status=from_status.value,
        to_status=to_status.value,
    )
    refreshed = await _get_attempt(db, attempt_id)
    return refreshed, audit_payload
