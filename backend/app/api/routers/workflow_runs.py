"""
Workflow Run router.

n8n's Main Orchestrator is the primary caller: create a run at the very
start (before Research), then PATCH current_stage/status as it moves
through the pipeline, and PATCH status=COMPLETED/FAILED (+
total_cost_usd) at the end. GET is for the dashboard and for n8n to
recover state after a restart.

No AI logic, no provider calls, no n8n changes live here — this router
only tracks a WorkflowRun row's lifecycle.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.services.pipeline_state import InvalidStageTransitionError
from app.schemas.workflow_run import (
    WorkflowRunCreateRequest,
    WorkflowRunCreateResponse,
    WorkflowRunResponse,
    WorkflowRunUpdateRequest,
)
from app.services.workflow_service import (
    ProjectNotFoundError,
    create_workflow_run,
    get_workflow_run,
    update_workflow_run,
)

router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])


@router.post("/", response_model=WorkflowRunCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_run_endpoint(
    payload: WorkflowRunCreateRequest, db: AsyncSession = Depends(get_db)
) -> WorkflowRunCreateResponse:
    """Create a new WorkflowRun. Always starts at
    status=PENDING / current_stage="created" (PipelineStage.CREATED) —
    not settable by the caller, per the task's requirements."""
    try:
        run = await create_workflow_run(
            db, project_id=payload.project_id, topic=payload.topic, mode=payload.mode
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return WorkflowRunCreateResponse(
        workflow_run_id=run.id,
        status=run.status,
        current_stage=run.current_stage,
    )


@router.get("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run_endpoint(
    workflow_run_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> WorkflowRunResponse:
    run = await get_workflow_run(db, workflow_run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"WorkflowRun {workflow_run_id} not found",
        )
    return WorkflowRunResponse.model_validate(run)


@router.patch("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def update_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    payload: WorkflowRunUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    """Only status, current_stage, completed_at, failure_reason, and
    total_cost_usd are updatable — enforced by
    WorkflowRunUpdateRequest's extra='forbid', which rejects any other
    field with a 422 before this handler even runs.

    current_stage specifically: the value itself must be a real
    PipelineStage member (422 if not, from the schema), AND the
    transition from the run's current stage to that value must be
    legal per pipeline_state.STAGE_TRANSITIONS (409 if not, from here).
    This is the fix for audit Issue 2 — current_stage can no longer be
    set to anything the state machine wouldn't also allow via
    advance_stage().
    """
    try:
        run = await update_workflow_run(db, workflow_run_id, payload)
    except InvalidStageTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"WorkflowRun {workflow_run_id} not found",
        )
    return WorkflowRunResponse.model_validate(run)
