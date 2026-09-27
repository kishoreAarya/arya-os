"""Publication attempt model (operator-authorized slice).

The durable system-of-record for publication attempts on the OPERATOR
publishing path. The attempt row exists BEFORE the first irreversible
external call, transitions to IN_PROGRESS before that call, and carries
the provider/external identifiers as soon as they are safely available
— independent of (and never replaced by) the post-success Video
writeback.

NEVER store credentials, tokens, auth headers, or any adapter
authentication material here: external ids are provider-allocated
public identifiers only.

Idempotency: `intent_key` identifies one publication INTENT
(video/platform/social/integration family); `attempt_number` is the
deterministic sequential attempt within that family. The database
UNIQUE(intent_key, attempt_number) is the concurrency-safe admission
guarantee — a duplicate submission of the same intent resolves to the
existing attempt, never a second external publication.
"""
import uuid

from sqlalchemy import Enum, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import PublicationAttemptStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PublicationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint("intent_key", "attempt_number", name="uq_publication_attempts_intent_seq"),
        Index("ix_publication_attempts_video_id", "video_id"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    social_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Server-derived publication-intent identity (see module docstring).
    intent_key: Mapped[str] = mapped_column(String(500), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PublicationAttemptStatus] = mapped_column(
        Enum(PublicationAttemptStatus, name="publication_attempt_status"),
        nullable=False,
        default=PublicationAttemptStatus.PENDING,
    )
    # Scheduled intent bookkeeping: recorded when EXECUTION begins (not
    # when a future schedule is merely defined).
    scheduled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_content_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Value-free-safe error text; never credentials.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
