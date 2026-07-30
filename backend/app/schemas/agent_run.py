"""
Pydantic request/response schemas for the Agent execution endpoint.

Kept separate from app/agents/base.py::AgentResult on the same
principle already established in schemas/workflow_run.py: the API's
shape and the internal dataclass's shape are allowed to drift
independently. AgentResult itself is unmodified.
"""

from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(default_factory=dict)
    workflow_run_id: uuid.UUID | None = None


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    provider_used: str | None = None
    cost_usd: float
    duration_seconds: float | None = None
    error: str | None = None