"""
Approval and GenerationAttempt tables.

Beginner note:
- `ApprovalCheckpoint` is one row per human decision point. n8n pauses
  the workflow after each stage (Trend, Script, Storyboard, Prompt,
  Image, Video, Thumbnail) and waits for a row here to be written with
  action=APPROVE before continuing. This is what keeps Sprint 1-5 from
  auto-publishing.
- `GenerationAttempt` is retry history: instead of a single
  success/failed flag, every single try gets its own row, so you can
  see "Attempt 1 failed (face inconsistency) -> Attempt 2 failed (bad
  lighting) -> Attempt 3 passed" and know exactly what it cost you to
  get there.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ApprovalAction, ApprovalStage
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ApprovalCheckpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "approval_checkpoints"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    stage: Mapped[ApprovalStage] = mapped_column(
        Enum(ApprovalStage, name="approval_stage"), nullable=False
    )
    # Points at the specific versioned row being reviewed (a script id,
    # an image id, etc.) — same pattern as Artifact.reference_id.
    reference_table: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[ApprovalAction | None] = mapped_column(
        Enum(ApprovalAction, name="approval_action"), nullable=True
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Model B (§ approval parameter binding): the digest of the EXACT
    # validated parameter snapshot this approval authorizes — computed
    # server-side from {"capability": <name>, "parameters": <model_dump()>}
    # via app.hermes.audit.compute_parameter_digest. NULL = legacy Model-A
    # approval (pre-Model-B row); never client-writable through any surface.
    parameter_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human-review evidence ONLY (Model B §6): a bounded server-generated
    # preview of the same validated parameter object the digest covers.
    # Never an authorization primitive — the digest is authoritative.
    parameter_preview: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only approval decision history (one row per decision event).

    Authorization architecture (operator-locked): ApprovalCheckpoint
    remains the fast current-state CACHE (action/decided_at/
    reviewer_notes = the latest event); this table is the authoritative,
    IMMUTABLE history. Events are created ONLY by
    POST /approvals/{id}/decide, which locks the checkpoint row (FOR
    UPDATE), allocates the next per-checkpoint sequence_number inside
    that lock, appends the event, and refreshes the cache — one
    transaction. No API updates or deletes events; decided_at is a
    server-generated immutable timestamp (the future TTL anchor).

    decided_by is OPTIONAL CALLER-ASSERTED PROVENANCE ONLY: the current
    authentication (shared service API key, security.py verify_api_key)
    provides no human identity, and none is invented — the field is
    non-authoritative metadata, exactly like the jobs-surface user_id
    (D3). REJECT and REVOKE are distinct semantics and stay distinct
    here: REJECT = request not authorized; REVOKE = a previously
    existing authorization is withdrawn.
    """

    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "sequence_number", name="uq_approval_decisions_checkpoint_seq"),
    )

    checkpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_checkpoints.id"), nullable=False
    )
    # Deterministic monotonic ordering within the checkpoint, allocated
    # under the checkpoint row lock (never derived from timestamps).
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[ApprovalAction] = mapped_column(
        Enum(ApprovalAction, name="approval_action"), nullable=False
    )
    # Server-generated at event creation; immutable thereafter.
    decided_at: Mapped[datetime] = mapped_column(nullable=False)
    # Caller-asserted provenance only — NOT authenticated identity.
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-event notes: history-scoped, never overwritten on later events.
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalTtlPolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Ratified approval-TTL policy: a GLOBAL DEFAULT row (stage IS NULL)
    plus optional PER-STAGE overrides. Authorization freshness is derived
    at evaluation time (approval timestamp + ttl) — never persisted on
    the immutable decision facts and never on the checkpoint cache.

    Validity semantics (gate-evaluated): an APPROVE is valid iff
    decided_at IS NULL (anchor-less legacy rows: perpetual, ratified)
    or now < decided_at + ttl_seconds. Expiry is decided_at + ttl <= now.
    """

    __tablename__ = "approval_ttl_policies"
    __table_args__ = (
        # At most one global row (stage IS NULL) and one row per stage.
        Index(
            "uq_approval_ttl_policies_scope",
            text("COALESCE(stage, '')"),
            unique=True,
        ),
        # Ratified: TTL durations are strictly positive — zero/negative
        # values are invalid policy data (they would instantly expire
        # every approval) and are rejected by the database.
        CheckConstraint("ttl_seconds > 0", name="ck_approval_ttl_policies_positive"),
    )

    # ApprovalStage VALUE this override applies to; NULL = global default.
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class GenerationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Full retry history for one artifact. `attempt_number` starts at 1
    per (reference_table, reference_id) family — i.e. per version chain,
    not per row — so you can query 'show me every attempt that led to
    this approved image' in one filter."""

    __tablename__ = "generation_attempts"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    reference_table: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded: Mapped[bool] = mapped_column(default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True
    )
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
