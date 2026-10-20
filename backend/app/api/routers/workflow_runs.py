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

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import AsyncSessionLocal, get_db
from app.models.approval import ApprovalCheckpoint
from app.models.core import WorkflowRun
from app.models.enums import WorkflowMode, WorkflowStatus
from app.services.authorization_service import (
    get_authorized_project_ids,
    verify_project_access,
    verify_workflow_access,
)

from app.services.pipeline_state import InvalidStageTransitionError
from app.schemas.workflow_run import (
    WorkflowRunCreateRequest,
    WorkflowRunCreateResponse,
    WorkflowRunRecoverResponse,
    WorkflowRunResponse,
    WorkflowRunResumeResponse,
    WorkflowRunUpdateRequest,
)
from app.services.workflow_execution_service import (
    WorkflowExecutionConflictError,
    determine_next_stage,
    get_current_worker_id,
    is_lease_stale,
    recover_workflow_run,
)
from app.services.workflow_service import (
    ProjectNotFoundError,
    create_workflow_run,
    get_workflow_run,
    get_workflow_run_artifacts,
    list_workflow_runs,
    update_workflow_run,
)

logger = get_logger("arya.api.workflow_runs")

router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])

_WORKFLOW_RUN_LOCK = asyncio.Lock()
_RUNNING_WORKFLOW_RUN_IDS: set[uuid.UUID] = set()
_ACTIVE_BACKGROUND_TASKS: set[asyncio.Task] = set()
_IS_SHUTTING_DOWN: bool = False


async def shutdown_background_workflow_tasks(timeout: float = 5.0) -> None:
    """Signal background tasks to gracefully stop during server shutdown."""
    global _IS_SHUTTING_DOWN
    _IS_SHUTTING_DOWN = True
    if not _ACTIVE_BACKGROUND_TASKS:
        return
    logger.info("shutting_down_background_workflow_tasks", count=len(_ACTIVE_BACKGROUND_TASKS))
    done, pending = await asyncio.wait(_ACTIVE_BACKGROUND_TASKS, timeout=timeout)
    if pending:
        logger.warning("cancelling_remaining_background_workflow_tasks", count=len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def _run_workflow_background_task(
    run_id: uuid.UUID,
    topic: str | None,
    mode: WorkflowMode,
    resume_from_stage: str | None = None,
) -> None:
    """Asynchronously execute workflow pipeline outside the HTTP request lifecycle."""
    from app.workflows.models import WorkflowInput
    from app.workflows.runner import Runner

    logger.info("workflow_run_background_task_started", run_id=str(run_id), resume_stage=resume_from_stage)
    my_worker_id = get_current_worker_id()
    try:
        import structlog
        structlog.contextvars.bind_contextvars(
            workflow_run_id=str(run_id),
            worker_id=my_worker_id,
            stage=resume_from_stage or "start",
        )
    except Exception:
        pass

    try:
        async with AsyncSessionLocal() as session:
            runner = Runner(db=session)
            input_model = WorkflowInput(
                topic=topic or "General Content",
                preset="documentary_short",
                platform="youtube",
            )

            await runner.execute_existing_run(
                run_id,
                input_model,
                resume_from_stage=resume_from_stage,
                worker_id=my_worker_id,
                claim_lease=True,
            )
    except WorkflowExecutionConflictError as exc:
        logger.warning(
            "workflow_run_lease_claim_conflict_ignored",
            run_id=str(run_id),
            worker_id=my_worker_id,
            error=str(exc),
        )
        return
    except asyncio.CancelledError:
        logger.warning(
            "workflow_run_background_task_cancelled",
            run_id=str(run_id),
            shutting_down=_IS_SHUTTING_DOWN,
        )
        try:
            async with AsyncSessionLocal() as cancel_session:
                c_run = await cancel_session.get(WorkflowRun, run_id)
                if (
                    c_run
                    and (c_run.worker_id == my_worker_id or c_run.worker_id is None)
                    and c_run.status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)
                ):
                    if _IS_SHUTTING_DOWN:
                        logger.info("releasing_workflow_lease_on_shutdown", run_id=str(run_id))
                        c_run.worker_id = None
                        await cancel_session.commit()
                    else:
                        c_run.status = WorkflowStatus.FAILED
                        c_run.failure_reason = "Workflow execution was cancelled"
                        c_run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        c_run.worker_id = None
                        await cancel_session.commit()
        except Exception:
            pass
        raise
    except Exception as exc:
        logger.exception("workflow_run_background_task_failed", run_id=str(run_id), error=str(exc))
        try:
            async with AsyncSessionLocal() as err_session:
                e_run = await err_session.get(WorkflowRun, run_id)
                if (
                    e_run
                    and (e_run.worker_id == my_worker_id or e_run.worker_id is None)
                    and e_run.status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)
                ):
                    e_run.status = WorkflowStatus.FAILED
                    e_run.failure_reason = str(exc)
                    e_run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    e_run.worker_id = None
                    await err_session.commit()
        except Exception:
            pass
    finally:
        try:
            import structlog
            structlog.contextvars.unbind_contextvars("workflow_run_id", "worker_id", "stage")
        except Exception:
            pass
        async with _WORKFLOW_RUN_LOCK:
            _RUNNING_WORKFLOW_RUN_IDS.discard(run_id)


async def _launch_workflow_execution(
    run_id: uuid.UUID, topic: str | None, mode: WorkflowMode
) -> None:
    async with _WORKFLOW_RUN_LOCK:
        if run_id in _RUNNING_WORKFLOW_RUN_IDS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"WorkflowRun {run_id} is already executing",
            )
        _RUNNING_WORKFLOW_RUN_IDS.add(run_id)

    task = asyncio.create_task(_run_workflow_background_task(run_id, topic=topic, mode=mode))
    _ACTIVE_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_ACTIVE_BACKGROUND_TASKS.discard)


async def _launch_workflow_resume(
    run_id: uuid.UUID,
    resume_stage: str | None = None,
) -> None:
    """Launch asynchronous workflow execution resumption outside the HTTP loop."""
    async with _WORKFLOW_RUN_LOCK:
        if run_id in _RUNNING_WORKFLOW_RUN_IDS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"WorkflowRun {run_id} is already executing",
            )
        _RUNNING_WORKFLOW_RUN_IDS.add(run_id)

    async with AsyncSessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        topic = run.topic if run else "General Content"
        mode = run.mode if run else WorkflowMode.AUTONOMOUS

    task = asyncio.create_task(
        _run_workflow_background_task(
            run_id,
            topic=topic,
            mode=mode,
            resume_from_stage=resume_stage,
        )
    )
    _ACTIVE_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_ACTIVE_BACKGROUND_TASKS.discard)


@router.get("/", response_model=list[WorkflowRunResponse])
async def list_workflow_runs_endpoint(
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100, description="Max workflow runs to return (1-100)"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRunResponse]:
    """List recent workflow runs from persistent storage."""
    if principal.is_admin:
        runs = await list_workflow_runs(db, project_id=project_id, limit=limit)
    else:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if not allowed_ids:
            return []
        if project_id is not None:
            if project_id not in allowed_ids:
                return []
            runs = await list_workflow_runs(db, project_id=project_id, limit=limit)
        else:
            runs = await list_workflow_runs(db, project_ids=allowed_ids, limit=limit)

    res_list: list[WorkflowRunResponse] = []
    for r in runs:
        item = WorkflowRunResponse.model_validate(r)
        item.is_stale = is_lease_stale(r)
        res_list.append(item)
    return res_list


@router.post("/", response_model=WorkflowRunCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_run_endpoint(
    payload: WorkflowRunCreateRequest,
    execute: bool = Query(default=False, description="Whether to immediately begin background execution"),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunCreateResponse:
    """Create a new WorkflowRun. Always starts at
    status=PENDING / current_stage="created" (PipelineStage.CREATED) —
    not settable by the caller, per the task's requirements."""
    # Enforce project access (422 if project missing, 403 if unauthorized)
    await verify_project_access(
        db, principal, payload.project_id, not_found_status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
    )

    try:
        run = await create_workflow_run(
            db, project_id=payload.project_id, topic=payload.topic, mode=payload.mode
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if execute:
        await _launch_workflow_execution(run.id, topic=run.topic, mode=run.mode)

    return WorkflowRunCreateResponse(
        workflow_run_id=run.id,
        status=WorkflowStatus.RUNNING if execute else run.status,
        current_stage=run.current_stage,
    )


@router.post(
    "/{workflow_run_id}/execute",
    response_model=WorkflowRunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunCreateResponse:
    """Trigger asynchronous execution of an existing WorkflowRun outside the HTTP loop."""
    run = await verify_workflow_access(db, principal, workflow_run_id)

    if run.status == WorkflowStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} is already running",
        )

    if run.status == WorkflowStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} has already completed",
        )

    if run.status == WorkflowStatus.AWAITING_APPROVAL and run.waiting_checkpoint_id:
        cp = await db.get(ApprovalCheckpoint, run.waiting_checkpoint_id)
        if cp and cp.action is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"WorkflowRun {workflow_run_id} is awaiting human approval on checkpoint {run.waiting_checkpoint_id}",
            )

    await _launch_workflow_execution(workflow_run_id, topic=run.topic, mode=run.mode)

    return WorkflowRunCreateResponse(
        workflow_run_id=run.id,
        status=WorkflowStatus.RUNNING,
        current_stage=run.current_stage,
    )


@router.post(
    "/{workflow_run_id}/recover",
    response_model=WorkflowRunRecoverResponse,
    status_code=status.HTTP_200_OK,
)
async def recover_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunRecoverResponse:
    """Recover an orphaned or stale workflow run and trigger background execution resumption."""
    run = await verify_workflow_access(db, principal, workflow_run_id)

    if run.status == WorkflowStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} has already completed",
        )

    if run.status == WorkflowStatus.RUNNING and not is_lease_stale(run):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} is actively executing (lease held by {run.worker_id or 'another process'})",
        )

    if run.status == WorkflowStatus.AWAITING_APPROVAL and run.waiting_checkpoint_id:
        cp = await db.get(ApprovalCheckpoint, run.waiting_checkpoint_id)
        if cp and cp.action is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"WorkflowRun {workflow_run_id} is awaiting human approval on checkpoint {run.waiting_checkpoint_id}",
            )

    worker_id = get_current_worker_id()
    try:
        recovered_run, next_stage = await recover_workflow_run(
            db=db,
            run_id=workflow_run_id,
            worker_id=worker_id,
        )
    except WorkflowExecutionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await _launch_workflow_resume(workflow_run_id, resume_stage=next_stage)

    return WorkflowRunRecoverResponse(
        workflow_run_id=recovered_run.id,
        status=recovered_run.status,
        current_stage=recovered_run.current_stage,
        recovered_from_stage=next_stage,
        execution_attempt=recovered_run.execution_attempt or 1,
        message=f"Workflow run {recovered_run.id} recovered and resumed from stage {next_stage}",
    )


@router.post(
    "/{workflow_run_id}/resume",
    response_model=WorkflowRunResumeResponse,
    status_code=status.HTTP_200_OK,
)
async def resume_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResumeResponse:
    """Explicitly resume execution of a suspended or paused workflow run."""
    run = await verify_workflow_access(db, principal, workflow_run_id)

    if run.status == WorkflowStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} has already completed",
        )

    if run.status == WorkflowStatus.RUNNING and not is_lease_stale(run):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"WorkflowRun {workflow_run_id} is already actively running",
        )

    if run.status == WorkflowStatus.AWAITING_APPROVAL and run.waiting_checkpoint_id:
        cp = await db.get(ApprovalCheckpoint, run.waiting_checkpoint_id)
        if cp and cp.action is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"WorkflowRun {workflow_run_id} is awaiting human approval on checkpoint {run.waiting_checkpoint_id}",
            )

    next_stage = determine_next_stage(run.last_completed_stage, run.current_stage)
    await _launch_workflow_resume(workflow_run_id, resume_stage=next_stage)

    return WorkflowRunResumeResponse(
        workflow_run_id=run.id,
        status=WorkflowStatus.RUNNING,
        current_stage=run.current_stage,
        resumed_from_stage=next_stage,
        execution_attempt=(run.execution_attempt or 0) + 1,
        message=f"Workflow run {run.id} resumed from stage {next_stage}",
    )


@router.get("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    run = await verify_workflow_access(db, principal, workflow_run_id)
    artifacts = await get_workflow_run_artifacts(db, run.id)
    resp = WorkflowRunResponse.model_validate(run)
    resp.artifacts = artifacts
    resp.is_stale = is_lease_stale(run)
    return resp


@router.patch("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def update_workflow_run_endpoint(
    workflow_run_id: uuid.UUID,
    payload: WorkflowRunUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
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
    await verify_workflow_access(db, principal, workflow_run_id)

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
