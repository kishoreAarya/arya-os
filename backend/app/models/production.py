"""
AryaOS V1 Phase 8 — Production Timeline & Job Persistence Models.

Maps the functional control surface and multi-shot production timeline
directly to the relational database:
- ProductionSequence: Sequence groupings within a Project
- ProductionShot: Individual shots with prompts, model routing, continuity, and keyframes
- ProductionJob: Discrete generation executions tracking AryaJobPackage boundary contracts
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProductionSequence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A production sequence within a Project, grouping sequential shots."""

    __tablename__ = "production_sequences"
    __table_args__ = (
        Index("ix_production_sequences_project_order", "project_id", "order_index"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="READY", nullable=False)

    project: Mapped["Project"] = relationship(back_populates="production_sequences")
    shots: Mapped[list["ProductionShot"]] = relationship(
        back_populates="sequence",
        cascade="all, delete-orphan",
        order_by="ProductionShot.shot_number",
    )


class ProductionShot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An individual shot in the production timeline corridor."""

    __tablename__ = "production_shots"
    __table_args__ = (
        Index("ix_production_shots_project_sequence", "project_id", "sequence_id"),
        Index("ix_production_shots_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shot_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_type: Mapped[str] = mapped_column(String(50), default="image", nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(50), default="16:9", nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="READY", nullable=False)
    first_frame: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_frame: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reference_assets: Mapped[list[str] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        default=list,
    )
    continuity_status: Mapped[str | None] = mapped_column(String(50), default="PASS", nullable=True)
    dependency_state: Mapped[str] = mapped_column(String(50), default="INDEPENDENT", nullable=False)
    predecessor_shot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    output_asset_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        default=dict,
    )

    project: Mapped["Project"] = relationship(back_populates="production_shots")
    sequence: Mapped["ProductionSequence"] = relationship(back_populates="shots")
    jobs: Mapped[list["ProductionJob"]] = relationship(
        back_populates="shot",
        cascade="all, delete-orphan",
    )


class ProductionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A discrete execution job tracking an AryaJobPackage boundary contract."""

    __tablename__ = "production_jobs"
    __table_args__ = (
        Index("ix_production_jobs_project_status", "project_id", "status"),
        Index("ix_production_jobs_job_package_id", "job_package_id"),
        Index("ix_production_jobs_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_shots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_package_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="CREATED", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_package_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
    )

    project: Mapped["Project"] = relationship(back_populates="production_jobs")
    shot: Mapped["ProductionShot | None"] = relationship(back_populates="jobs")
