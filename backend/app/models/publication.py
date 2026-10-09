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

from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import PublicationAttemptStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PublicationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint(
            "intent_key", "attempt_number", name="uq_publication_attempts_intent_seq"
        ),
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
    # Phase 54B-I1: the immutable publication-content manifest this
    # attempt dispatches under. NULL on all pre-Phase-54B rows (and on
    # dry-run, which records no attempt). The digest is stamped
    # atomically with the dispatch permit in the later gate-integration
    # phase; both columns are written by AryaOS only — never clients.
    manifest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publication_manifests.id"),
        nullable=True,
    )
    manifest_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PublicationManifest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable publication-content manifest (Phase 54B-I1).

    Binds a human publication approval to the EXACT content and final
    effective parameters dispatched to the provider. Rows are
    APPEND-ONLY: never updated, never re-bound — a changed artifact or
    parameter set produces a NEW row (a different digest), which
    requires fresh approval before dispatch.

    The exact canonical SERIALIZED BYTES are authoritative
    (canonical_bytes, Text): the digest is computed over these bytes
    (SHA-256 with the AOS-PUBMANIFEST-v1 domain prefix — see
    app/services/publication_manifest.py) and must NEVER be re-derived
    from a JSONB re-rendering, which does not preserve byte-level
    serialization. Queryable identity/digest columns are explicit
    duplicates of values inside the canonical bytes for indexing only.

    Digest uniqueness enforces concurrent-creation dedupe: two workers
    deriving the identical manifest from the same persisted artifacts
    produce identical canonical bytes and collide on
    uq_publication_manifests_digest; the loser re-resolves to the
    winner's row (the admit_attempt race pattern).
    """

    __tablename__ = "publication_manifests"
    __table_args__ = (
        UniqueConstraint("manifest_digest", name="uq_publication_manifests_digest"),
        Index("ix_publication_manifests_workflow_run_id", "workflow_run_id"),
        Index("ix_publication_manifests_video_id", "video_id"),
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False
    )
    # The exact canonical serialization — authoritative digest input.
    canonical_bytes: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # Authoritative persisted artifact identity (explicit, indexable
    # duplicates of values inside the canonical bytes).
    video_storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    video_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    video_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thumbnail_storage_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    thumbnail_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
