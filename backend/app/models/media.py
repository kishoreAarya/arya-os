"""
Media tables: Image, GeneratedVideo, Asset, Video, Thumbnail.

Beginner note: Image, GeneratedVideo, Video, and Thumbnail all use
VersionedAssetMixin — each can go through Draft -> Generated ->
Approved/Rejected, exactly like the Prompt V1/V2 example in the
architecture brief. `Asset` (voice/music/overlay) does NOT version —
those are supporting files regenerated fresh each run, not iterated
on with approve/reject cycles.
"""
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import PublishStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, VersionedAssetMixin


class Image(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """One generated image for one storyboard shot (e.g. a ComfyUI/Flux
    output). `storage_path` points at wherever the file actually lives
    (S3, local disk, RunPod volume) — this table just tracks metadata."""

    __tablename__ = "images"

    storyboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storyboards.id"), nullable=False
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    shot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class GeneratedVideo(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """One generated video clip for one shot (image-to-video or
    text-to-video output), before final assembly stitches clips
    together into the finished Video."""

    __tablename__ = "generated_videos"

    storyboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storyboards.id"), nullable=False
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    shot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Asset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Supporting media that isn't a generated shot: voice-over audio,
    background music, overlays, subtitle files. Deliberately not
    versioned — see module docstring."""

    __tablename__ = "assets"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "voice" | "music" | "subtitle" | "overlay"
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Thumbnail(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """The thumbnail image offered to YouTube — versioned separately
    from the video itself, since a thumbnail can be rejected and
    regenerated independently of the video passing validation."""

    __tablename__ = "thumbnails"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Video(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """The final assembled video for one WorkflowRun. Versioned because
    a fully-assembled cut can itself be rejected (per the architecture
    brief's example: Video V1 -> Rejected, Video V2 -> Approved) even
    if every individual shot passed."""

    __tablename__ = "videos"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    thumbnail_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thumbnails.id"), nullable=True
    )
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_status: Mapped[PublishStatus] = mapped_column(
        Enum(PublishStatus, name="publish_status"), default=PublishStatus.DRAFT
    )

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="video")
