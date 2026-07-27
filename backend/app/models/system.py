"""
Artifact and SystemLog tables.

Beginner note: `Artifact` is a generic "we produced a thing" record —
it exists so the Artifact Registry in the architecture doc has one
place to list EVERY output (scripts, images, videos, prompts, voice,
music, metadata) regardless of which specific table holds the detail.
Think of it as an index card that points at the real row.
`SystemLog` captures workflow-level events for the Observability layer
(failure reports, execution time) beyond what structlog writes to stdout.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ArtifactType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Artifact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "artifacts"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="artifact_type"), nullable=False
    )
    # Points at the specific row in scripts/images/generated_videos/etc.
    reference_table: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(default=1)


class SystemLog(Base, UUIDPrimaryKeyMixin):
    """Append-only event log for workflow-level history — separate from
    stdout logs so the dashboard can query "everything that happened on
    this run" without grepping log files."""

    __tablename__ = "system_logs"

    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "WorkflowFailed"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="info")  # info | warning | error
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
