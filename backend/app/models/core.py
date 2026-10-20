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

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint

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
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", server_default="ACTIVE", nullable=False)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    budget_limit_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    production_sequences: Mapped[list["ProductionSequence"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    production_shots: Mapped[list["ProductionShot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    production_jobs: Mapped[list["ProductionJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    missions: Mapped[list["Mission"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    autonomous_goals: Mapped[list["AutonomousGoal"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    budget_reservations: Mapped[list["BudgetReservation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class WorkflowRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One full pipeline execution for one video, start to finish.

    This is the row n8n updates as a video moves through each stage.
    `total_cost_usd` accumulates spend across every provider call made
    during this run (RunPod GPU time, LLM tokens, etc.) — this is the
    cost-per-video tracking flagged in the architecture review."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_project_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True, nullable=False
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
    last_completed_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    execution_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    execution_attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    waiting_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_checkpoints.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="workflow_runs")
    scripts: Mapped[list["Script"]] = relationship(
        back_populates="workflow_run", cascade="all, delete-orphan"
    )
    video: Mapped["Video"] = relationship(
        back_populates="workflow_run", uselist=False, cascade="all, delete-orphan"
    )


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An API key credential associated with a principal."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    principal_type: Mapped[str] = mapped_column(
        String(50), default="service_account", server_default="service_account", nullable=False
    )

    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="api_key", cascade="all, delete-orphan"
    )


class ProjectMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Associates an API key / principal with a project and role."""

    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "api_key_id", name="uq_project_memberships_project_api_key"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), default="owner", server_default="owner", nullable=False)

    project: Mapped["Project"] = relationship(back_populates="memberships")
    api_key: Mapped["ApiKey"] = relationship(back_populates="memberships")
