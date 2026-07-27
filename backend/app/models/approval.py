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

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text
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
