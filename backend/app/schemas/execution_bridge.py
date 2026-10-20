"""
AryaOS V1 Stage 25 Phase 1 — Autonomous Execution Bridge Schemas.

Pydantic schemas for validating and serializing:
- Missions
- Autonomous Goals
- Autonomous Action Nodes
- Governance Decisions
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sanitization import sanitize_payload, sanitize_text


# -----------------------------------------------------------------------------
# 1. Mission Schemas
# -----------------------------------------------------------------------------

class MissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(..., min_length=1)
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    deadline: datetime | None = None
    completion_criteria_json: dict[str, Any] = Field(default_factory=dict)
    execution_policy_json: dict[str, Any] = Field(default_factory=dict)


class MissionUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    objective: str | None = None
    status: Literal["PLANNED", "ACTIVE", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"] | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] | None = None
    deadline: datetime | None = None
    progress_json: dict[str, Any] | None = None
    completion_criteria_json: dict[str, Any] | None = None
    execution_policy_json: dict[str, Any] | None = None


class MissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    objective: str
    status: str
    priority: str
    deadline: datetime | None = None
    progress_json: dict[str, Any] = Field(default_factory=dict)
    completion_criteria_json: dict[str, Any] = Field(default_factory=dict)
    execution_policy_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# 2. Autonomous Action Node Schemas
# -----------------------------------------------------------------------------

class AutonomousActionNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    action_type: Literal["RESEARCH", "SYNTHESIS", "JOB_PACKAGE", "EXTERNAL_ACTION", "DECISION"]
    required_capability: str = Field(..., min_length=1, max_length=100)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    inputs_json: dict[str, Any] = Field(default_factory=dict)
    production_job_id: uuid.UUID | None = None
    approval_checkpoint_id: uuid.UUID | None = None


class AutonomousActionNodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: (
        Literal[
            "PENDING",
            "READY",
            "EXECUTING",
            "SUCCEEDED",
            "FAILED",
            "AWAITING_APPROVAL",
            "SKIPPED",
            "BLOCKED",
            "UNKNOWN_PENDING_RECONCILIATION",
            "RECOVERY_REQUIRED",
        ]
        | None
    ) = None
    production_job_id: uuid.UUID | None = None


class AutonomousActionNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    goal_id: uuid.UUID
    client_action_id: str
    title: str
    action_type: str
    required_capability: str
    status: str
    risk_level: str
    inputs_json: dict[str, Any] = Field(default_factory=dict)
    outputs_json: dict[str, Any] | None = None
    error: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float | None = None
    production_job_id: uuid.UUID | None = None
    approval_checkpoint_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("inputs_json", "outputs_json", mode="after")
    @classmethod
    def sanitize_action_payloads(cls, v: Any) -> Any:
        if v is not None:
            return sanitize_payload(v)
        return v

    @field_validator("error", mode="after")
    @classmethod
    def sanitize_action_error(cls, v: str | None) -> str | None:
        if v is not None:
            return sanitize_text(v)
        return v


# -----------------------------------------------------------------------------
# 3. Autonomous Goal Schemas
# -----------------------------------------------------------------------------

class AutonomousGoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID | None = None
    objective: str = Field(..., min_length=1)
    current_plan_version: int = Field(default=1, ge=1)
    plan_dag_json: dict[str, Any] = Field(default_factory=dict)
    context_memory_ids: list[str] = Field(default_factory=list)
    actions: list[AutonomousActionNodeCreate] = Field(default_factory=list)


class AutonomousGoalUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str | None = None
    status: (
        Literal[
            "DRAFT",
            "READY",
            "PLANNING",
            "EXECUTING",
            "PAUSED",
            "AWAITING_APPROVAL",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "BLOCKED",
            "RECOVERY_REQUIRED",
        ]
        | None
    ) = None
    current_plan_version: int | None = None
    plan_dag_json: dict[str, Any] | None = None
    context_memory_ids: list[str] | None = None
    final_summary: str | None = None
    failure_reason: str | None = None


class AutonomousGoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    mission_id: uuid.UUID | None = None
    objective: str
    status: str
    current_plan_version: int
    plan_dag_json: dict[str, Any] = Field(default_factory=dict)
    context_memory_ids: list[str] = Field(default_factory=list)
    final_summary: str | None = None
    failure_reason: str | None = None
    actions: list[AutonomousActionNodeResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("plan_dag_json", mode="after")
    @classmethod
    def sanitize_goal_dag(cls, v: Any) -> Any:
        if v is not None:
            return sanitize_payload(v)
        return v

    @field_validator("final_summary", "failure_reason", mode="after")
    @classmethod
    def sanitize_goal_text(cls, v: str | None) -> str | None:
        if v is not None:
            return sanitize_text(v)
        return v


# -----------------------------------------------------------------------------
# 4. Governance Decision Schemas
# -----------------------------------------------------------------------------

class GovernanceDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: uuid.UUID | None = None
    action_node_id: uuid.UUID | None = None
    verdict: Literal["APPROVED", "DENIED", "REQUIRES_ESCALATION"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    policy_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class GovernanceDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    goal_id: uuid.UUID | None = None
    action_node_id: uuid.UUID | None = None
    verdict: str
    risk_level: str
    policy_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("policy_evaluations", "reasons", mode="after")
    @classmethod
    def sanitize_governance_data(cls, v: Any) -> Any:
        if v is not None:
            return sanitize_payload(v)
        return v
