"""
Core tables: Project and WorkflowRun.

Beginner note: a "Project" is a content series/channel concept (you
might run more than one channel someday, or want to group videos by
theme). A "WorkflowRun" is one trip through the whole pipeline for one
video — Trend Discovery all the way to Publish. Everything else in
this app (scripts, images, videos) links back to a WorkflowRun so you
can always answer "what happened during the making of this video?".
"""
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import WorkflowMode, WorkflowStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A channel or content series. Sprint 1's "one creator" scope means
    you'll likely have just one row here for now — but it means you're
    not locked in if you start a second channel later."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class WorkflowRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One full pipeline execution for one video, start to finish.

    This is the row n8n updates as a video moves through each stage.
    `total_cost_usd` accumulates spend across every provider call made
    during this run (RunPod GPU time, LLM tokens, etc.) — this is the
    cost-per-video tracking flagged in the architecture review."""

    __tablename__ = "workflow_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mode: Mapped[WorkflowMode] = mapped_column(
        Enum(WorkflowMode, name="workflow_mode"), default=WorkflowMode.ASSISTED
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status"), default=WorkflowStatus.PENDING
    )
    current_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="workflow_runs")
    scripts: Mapped[list["Script"]] = relationship(
        back_populates="workflow_run", cascade="all, delete-orphan"
    )
    video: Mapped["Video"] = relationship(
        back_populates="workflow_run", uselist=False, cascade="all, delete-orphan"
    )
