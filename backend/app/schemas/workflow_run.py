"""
Pydantic request/response schemas for Workflow Run management.

Kept separate from the SQLAlchemy models (app/models/core.py) on
purpose — the API's shape and the database's shape are allowed to
drift independently. No models were modified to support this task.

CANONICAL STAGE VOCABULARY (fixes audit Issues 1 & 2): `PipelineStage`
(app/models/enums.py) is now the single source of truth for
WorkflowRun.current_stage's *values*. The column itself is unchanged —
still a plain String(100), no migration needed — but every value ever
written to it going forward is a real PipelineStage member, validated
the same way pipeline_state.py's advance_stage() already validates
transitions. See workflow_service.py for how writes are enforced.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus

# Was the literal string "research" — not a valid PipelineStage member
# at all, which is exactly the mismatch audit Issue 1 flagged (a run
# created via POST /workflow-runs/ held a current_stage value that
# pipeline_state.py's _current_stage() would crash trying to parse).
# Now derived directly from the canonical enum instead of being an
# independent literal.
INITIAL_STAGE = PipelineStage.CREATED.value


def _normalize_enum_input(value: object) -> object:
    """Accepts case-insensitively so both {"mode": "ASSISTED"} and
    {"mode": "assisted"} validate — WorkflowMode/WorkflowStatus/
    PipelineStage all store lowercase values, but it's easy for a
    caller to send upper/mixed case."""
    if isinstance(value, str):
        return value.lower()
    return value


class WorkflowRunCreateRequest(BaseModel):
    project_id: uuid.UUID
    topic: str | None = Field(default=None, max_length=500)
    mode: WorkflowMode = WorkflowMode.ASSISTED

    model_config = ConfigDict(extra="forbid")

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, v: object) -> object:
        return _normalize_enum_input(v)


class WorkflowRunCreateResponse(BaseModel):
    """Exact shape requested for POST /workflow-runs — unchanged by
    this fix. Only the *value* current_stage starts at changes (from
    the invalid "research" to the valid "created")."""

    workflow_run_id: uuid.UUID
    status: WorkflowStatus
    current_stage: str | None


class WorkflowRunResponse(BaseModel):
    """Full representation returned by GET, and by PATCH after update.

    current_stage is deliberately left as `str | None` here (not typed
    as PipelineStage) even though writes are now enforced to always be
    valid PipelineStage values (see WorkflowRunUpdateRequest below).
    This is an intentional asymmetry: the read path stays permissive so
    a GET never fails to serialize regardless of what's already in the
    column, while the write path is where the enum is actually
    enforced. Tightening the read side too is left for a future task —
    out of scope for Issues 1/2.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    topic: str | None
    mode: WorkflowMode
    status: WorkflowStatus
    current_stage: str | None
    total_cost_usd: Decimal
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowRunUpdateRequest(BaseModel):
    """PATCH payload.

    extra='forbid' is what actually enforces 'no arbitrary updates' —
    any field not in this exact list (e.g. project_id, topic, mode)
    is rejected with a 422 before the request ever reaches the service
    layer. All fields are optional; only whatever is explicitly present
    in the request body gets applied (see WorkflowRunUpdate.model_dump
    with exclude_unset=True in the service).

    current_stage is now typed as PipelineStage, not a bare string
    (fixes audit Issue 2): a request naming a stage that doesn't exist
    is rejected here, at the schema layer, with a 422 — before it ever
    reaches the service. Whether the *transition* from the run's
    current stage to this one is actually legal is a business rule
    that depends on the run's existing state, so that check still
    belongs to pipeline_state.py's STAGE_TRANSITIONS, applied in
    workflow_service.update_workflow_run() (see that file).
    """

    model_config = ConfigDict(extra="forbid")

    status: WorkflowStatus | None = None
    current_stage: PipelineStage | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    total_cost_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("status", "current_stage", mode="before")
    @classmethod
    def _normalize_status_and_stage(cls, v: object) -> object:
        return _normalize_enum_input(v)
