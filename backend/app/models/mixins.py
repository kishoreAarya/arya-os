"""
Shared building blocks for every table.

Beginner note: a "mixin" is a small class that adds the same columns
to many tables without copy-pasting. Every table in this app inherits
from TimestampMixin (created_at/updated_at) and uses a UUID primary key
so records get a globally-unique ID the moment they're created — useful
once artifacts get passed between n8n, this backend, and RunPod.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import AssetStatus


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VersionedAssetMixin:
    """Applied to every generation-pipeline artifact (Script, Storyboard,
    Prompt, Image, Video, Thumbnail) so each one supports full version
    history instead of being overwritten in place.

    Beginner note: `parent_version_id` points at the previous attempt
    (e.g. Image V2's parent_version_id = Image V1's id) so you can walk
    backwards through "why did we end up here" — Prompt V1 -> Image V1
    -> Rejected -> Prompt V2 -> Image V2 -> Approved. The Learning Loop
    reads `status == APPROVED` to know exactly which version got
    published, ignoring every rejected draft along the way.
    One Postgres enum type ("asset_status") is shared across all six
    tables that use this mixin — that's intentional, not a mistake.
    """
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), default=AssetStatus.DRAFT, nullable=False
    )
    retry_reason: Mapped[str | None] = mapped_column(nullable=True)
    quality_score: Mapped[int | None] = mapped_column(nullable=True)  # 0-100, set by validators
