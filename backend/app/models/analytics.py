"""
Analytics, PerformanceLearningFeedback, GenerationLearningEvent.

Beginner note — this file implements the two SEPARATE learning systems
from the architecture brief. They stay in different tables on purpose:

A. Generation Learning (`GenerationLearningEvent`) — pre-publish. Fires
   when a validator rejects something, e.g. "Image Validator detected
   face inconsistency -> Prompt rewritten -> Image regenerated". This
   improves generation quality DURING a run, before anything publishes.

B. Performance Learning (`PerformanceLearningFeedback`) — post-publish.
   Fires from `Analytics` snapshots pulled from YouTube after a video
   is live (CTR, retention, watch time, drop-off, likes, comments,
   shares, subscribers gained). This improves FUTURE runs' topic,
   script, prompt, and thumbnail choices.

Never merge these two into one table — a validator's opinion of a
draft and YouTube's audience response are different kinds of evidence
and answer different questions.
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Analytics(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A snapshot of how a published video is performing, pulled from
    the YouTube API on a schedule. Feeds PerformanceLearningFeedback."""

    __tablename__ = "analytics"

    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0)
    click_through_rate: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    average_view_duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    average_view_percentage: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    audience_drop_off_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PerformanceLearningFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """System B: a conclusion drawn from post-publish Analytics, tagged
    so future Trend/Script/Prompt/Thumbnail agents can query "what have
    we learned?" before their next run. E.g. correlating high Image
    Quality with higher CTR, or high Story Quality with higher
    retention (per the Quality Score system)."""

    __tablename__ = "performance_learning_feedback"

    category: Mapped[str] = mapped_column(String(50), nullable=False)  # "topic" | "script" | "thumbnail" | "prompt" | "title"
    insight: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)  # 0.0-1.0
    based_on_video_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)  # superseded feedback gets deactivated, not deleted


class GenerationLearningEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """System A: one row per validator-driven correction made DURING a
    run, before anything is published. Example: Image Validator flags
    face inconsistency -> this row records that -> the Prompt Agent
    reads it and rewrites the prompt for the next GenerationAttempt.
    This is what makes generation quality improve run-over-run without
    needing any YouTube data at all."""

    __tablename__ = "generation_learning_events"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    validator_name: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "image_validator"
    reference_table: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issue_detected: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "face inconsistency"
    correction_applied: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. "prompt rewritten"
