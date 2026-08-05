"""
Arya OS — Workflow Orchestration Models.

Pydantic models shared by the Runner, Orchestrator, API Router, and
WorkflowState during workflow execution.

These are orchestration-level data structures only. They are NOT
SQLAlchemy ORM models and do NOT duplicate any database schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import WorkflowStatus


class WorkflowInput(BaseModel):
    """Input parameters for initiating a new workflow.

    Attributes:
        topic: The subject matter of the content to produce.
        language: The target language for the content.
        style: The visual or narrative style to apply.
        duration: The target duration in seconds.
        platform: The target publishing platform (e.g., "youtube").
        metadata: Optional additional parameters for the pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1, description="Content topic")
    language: str = Field(..., min_length=1, description="Target language")
    style: str = Field(..., min_length=1, description="Visual or narrative style")
    duration: int = Field(..., gt=0, description="Target duration in seconds")
    platform: str = Field(..., min_length=1, description="Target publishing platform")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Optional additional parameters"
    )

    @field_validator("topic", "language", "style", "platform")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        return v.strip()


class StageResult(BaseModel):
    """Result of executing one pipeline stage.

    Bridges the internal AgentResult dataclass to the orchestration
    layer's structured output.

    Attributes:
        stage: The stage key that was executed.
        success: Whether the stage completed successfully.
        output: The data produced by the stage.
        error: Error message if the stage failed.
        started_at: When stage execution began.
        completed_at: When stage execution finished.
        execution_time_ms: Time taken to execute the stage in milliseconds.
        provider_used: The provider that served the request.
        cost_usd: Cost incurred for this stage in USD.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(..., description="Stage key that was executed")
    success: bool = Field(..., description="Whether the stage succeeded")
    output: Dict[str, Any] = Field(
        default_factory=dict, description="Stage output data"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if stage failed"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Stage start time"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="Stage completion time"
    )
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Execution time in milliseconds"
    )
    provider_used: Optional[str] = Field(
        default=None, description="Provider that served the request"
    )
    cost_usd: float = Field(
        default=0.0, ge=0.0, description="Cost incurred in USD"
    )


class WorkflowResult(BaseModel):
    """Final result of a workflow execution.

    Returned by the Runner after the Orchestrator completes or fails.

    Attributes:
        workflow_id: UUID of the WorkflowRun.
        status: Final WorkflowStatus value.
        success: Whether the entire workflow succeeded.
        completed_stages: Stage keys that finished successfully.
        failed_stage: Stage key that caused failure, if any.
        stage_results: Detailed results from each executed stage.
        error: Error message if the workflow failed.
        started_at: When the workflow started.
        completed_at: When the workflow finished.
        total_execution_time_ms: Total time taken in milliseconds.
        total_cost_usd: Sum of all stage costs in USD.
        artifacts: Accumulated outputs from all stages.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: uuid.UUID = Field(..., description="UUID of the WorkflowRun")
    status: WorkflowStatus = Field(..., description="Final workflow status")
    success: bool = Field(..., description="Whether the workflow succeeded")
    completed_stages: List[str] = Field(
        default_factory=list, description="Successfully completed stages"
    )
    failed_stage: Optional[str] = Field(
        default=None, description="Stage that failed, if any"
    )
    stage_results: List[StageResult] = Field(
        default_factory=list, description="Results from each stage"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if workflow failed"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Workflow start time"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="Workflow completion time"
    )
    total_execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Total execution time in milliseconds"
    )
    total_cost_usd: float = Field(
        default=0.0, ge=0.0, description="Total cost in USD"
    )
    artifacts: Dict[str, Any] = Field(
        default_factory=dict, description="Accumulated stage outputs"
    )
