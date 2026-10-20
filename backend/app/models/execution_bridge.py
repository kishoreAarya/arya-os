"""
AryaOS V1 Stage 25 Phase 1 — Autonomous Execution Bridge Models.

Defines the durable PostgreSQL schema for:
- Mission: Multi-goal objectives, priorities, constraints, and completion criteria.
- AutonomousGoal: Discrete autonomous intents with planned action DAGs.
- AutonomousActionNode: Execution nodes with inputs, outputs, capabilities, and links to jobs/checkpoints.
- GovernanceDecision: Server-side record of policy evaluations, verdicts, and risk ratings.

All models adhere to repository conventions:
- UUIDPrimaryKeyMixin & TimestampMixin
- Explicit ForeignKeys with ON DELETE CASCADE / SET NULL
- JSONB with SQLite fallback variant for test compatibility
- Explicit lifecycle states (never defaulting to completion)
- Zero sensitive credentials or plaintext secrets
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Mission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A multi-goal mission coordinating autonomous operational objectives."""

    __tablename__ = "missions"
    __table_args__ = (
        Index("ix_missions_project_status", "project_id", "status"),
        Index("ix_missions_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="PLANNED", server_default="PLANNED", nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(20), default="NORMAL", server_default="NORMAL", nullable=False
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=lambda: {
            "total_goals": 0,
            "completed_goals": 0,
            "failed_goals": 0,
            "percentage": 0.0,
        },
    )
    completion_criteria_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
    execution_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )

    project: Mapped["Project"] = relationship(back_populates="missions")
    goals: Mapped[list["AutonomousGoal"]] = relationship(
        back_populates="mission",
        order_by="AutonomousGoal.created_at",
    )


class AutonomousGoal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An autonomous intent with an action DAG, executing under a project or mission."""

    __tablename__ = "autonomous_goals"
    __table_args__ = (
        Index("ix_autonomous_goals_project_status", "project_id", "status"),
        Index("ix_autonomous_goals_mission_id", "mission_id"),
        Index("ix_autonomous_goals_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="DRAFT", server_default="DRAFT", nullable=False
    )
    current_plan_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    plan_dag_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
    context_memory_ids: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=list,
    )
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="autonomous_goals")
    mission: Mapped["Mission | None"] = relationship(back_populates="goals")
    actions: Mapped[list["AutonomousActionNode"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        order_by="AutonomousActionNode.created_at",
    )
    governance_decisions: Mapped[list["GovernanceDecision"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
    )
    budget_reservations: Mapped[list["BudgetReservation"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
    )


class AutonomousActionNode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A discrete action node within an autonomous goal's execution DAG."""

    __tablename__ = "autonomous_action_nodes"
    __table_args__ = (
        Index("ix_autonomous_actions_goal_status", "goal_id", "status"),
        Index("ix_autonomous_actions_status", "status"),
        Index("ix_autonomous_actions_production_job", "production_job_id"),
        Index("ix_autonomous_actions_approval_checkpoint", "approval_checkpoint_id"),
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("autonomous_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="PENDING", server_default="PENDING", nullable=False
    )
    risk_level: Mapped[str] = mapped_column(
        String(20), default="LOW", server_default="LOW", nullable=False
    )
    inputs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
    outputs_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 4), default=0.0, server_default="0.0", nullable=False
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional foreign key to existing ProductionJob when action requires media generation
    production_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Optional foreign key to existing ApprovalCheckpoint when action requires human sign-off
    approval_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_checkpoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    goal: Mapped["AutonomousGoal"] = relationship(back_populates="actions")
    production_job: Mapped["ProductionJob | None"] = relationship()
    approval_checkpoint: Mapped["ApprovalCheckpoint | None"] = relationship()
    governance_decisions: Mapped[list["GovernanceDecision"]] = relationship(
        back_populates="action_node",
        cascade="all, delete-orphan",
    )


class GovernanceDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Server-side audit record of automated policy evaluations and risk ratings."""

    __tablename__ = "governance_decisions"
    __table_args__ = (
        Index("ix_governance_decisions_project", "project_id"),
        Index("ix_governance_decisions_goal", "goal_id"),
        Index("ix_governance_decisions_action", "action_node_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("autonomous_goals.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    action_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("autonomous_action_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(20), default="LOW", server_default="LOW", nullable=False
    )
    policy_evaluations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=list,
    )
    reasons: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=list,
    )

    project: Mapped["Project"] = relationship()
    goal: Mapped["AutonomousGoal | None"] = relationship(
        back_populates="governance_decisions"
    )
    action_node: Mapped["AutonomousActionNode | None"] = relationship(
        back_populates="governance_decisions"
    )


class BudgetReservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authoritative project-scoped budget reservation for an autonomous goal plan version."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("goal_id", "plan_version", name="uq_budget_reservations_goal_plan_version"),
        Index("ix_budget_reservations_project_status", "project_id", "status"),
        Index("ix_budget_reservations_project_id", "project_id"),
        Index("ix_budget_reservations_goal_id", "goal_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("autonomous_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    reserved_amount_usd: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    consumed_amount_usd: Mapped[float] = mapped_column(
        Numeric(10, 4), default=0.0, server_default="0.0000", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default="RESERVED", server_default="RESERVED", nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="budget_reservations")
    goal: Mapped["AutonomousGoal"] = relationship(back_populates="budget_reservations")


class ConsumedCapabilityNonce(Base, UUIDPrimaryKeyMixin):
    """PostgreSQL-backed durable replay protection for GovernedExecutionContext capability tokens."""

    __tablename__ = "consumed_capability_nonces"
    __table_args__ = (
        UniqueConstraint("execution_nonce", name="uq_consumed_capability_nonce"),
        Index("ix_consumed_capability_nonces_nonce", "execution_nonce"),
        Index("ix_consumed_capability_nonces_action_node_id", "action_node_id"),
        Index("ix_consumed_capability_nonces_goal_id", "goal_id"),
        Index("ix_consumed_capability_nonces_project_id", "project_id"),
        Index("ix_consumed_capability_nonces_reservation_id", "reservation_id"),
    )

    execution_nonce: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    action_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(50), nullable=False)
    capability_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(100), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
