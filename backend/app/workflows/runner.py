"""
Arya OS — Workflow Runner.

Entry point for end-to-end workflow execution.

Creates a persistent WorkflowRun, invokes the Orchestrator to execute
the full pipeline, measures total execution time, persists the final
state back to the database, and returns a WorkflowResult.

The Runner delegates all execution to the Orchestrator and all
persistence to the existing workflow_service. It contains no business
logic, no retry logic, no provider knowledge, and no platform knowledge.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.models.enums import WorkflowMode, WorkflowStatus
from app.schemas.workflow_run import WorkflowRunUpdateRequest
from app.services.workflow_service import create_workflow_run, update_workflow_run
from app.workflows.models import WorkflowInput, WorkflowResult
from app.workflows.orchestrator import Orchestrator

logger = get_logger("arya.workflows.runner")


class Runner:
    """Coordinates workflow initialization, execution, and result return."""

    def __init__(self, db: AsyncSession, max_retries: int = 3) -> None:
        """Initialize with a request-scoped database session.

        Args:
            db: AsyncSession for WorkflowRun persistence and agent DI.
            max_retries: Per-stage retry attempts passed to Orchestrator.
        """
        self._db = db
        self._max_retries = max_retries
        self._orchestrator = Orchestrator(db=db, max_retries=max_retries)
        logger.info("runner_initialized", max_retries=max_retries)

    async def start(
        self,
        workflow_input: WorkflowInput,
        project_id: uuid.UUID,
        mode: WorkflowMode = WorkflowMode.AUTONOMOUS,
    ) -> WorkflowResult:
        """Start and execute a new end-to-end workflow.

        1. Creates a WorkflowRun via the existing service.
        2. Logs the workflow start event.
        3. Invokes the Orchestrator to run all pipeline stages.
        4. Measures total execution time.
        5. Updates the WorkflowRun with final status and cost.
        6. Returns the WorkflowResult.

        Args:
            workflow_input: Validated workflow parameters.
            project_id: The Project this run belongs to.
            mode: Execution mode (manual, assisted, autonomous).

        Returns:
            WorkflowResult with final status, outputs, and timing.

        Raises:
            RuntimeError: If WorkflowRun creation fails.
        """
        run = await self._create_run(workflow_input, project_id, mode)
        workflow_run_id = run.id

        await log_event(
            EventType.WORKFLOW_STARTED,
            message=f"Workflow started: {workflow_input.topic}",
            workflow_run_id=workflow_run_id,
        )

        started_at = datetime.now(timezone.utc)
        start_perf = time.perf_counter()

        try:
            result = await self._orchestrator.run(
                workflow_run_id=workflow_run_id,
                workflow_input=workflow_input.model_dump(),
            )
        except Exception as exc:
            logger.exception(
                "orchestrator_unhandled_exception",
                workflow_run_id=str(workflow_run_id),
                error=str(exc),
            )
            result = await self._build_failure_result(
                workflow_run_id=workflow_run_id,
                error=f"Unhandled orchestrator exception: {exc}",
                started_at=started_at,
                start_perf=start_perf,
            )

        total_time_ms = round((time.perf_counter() - start_perf) * 1000, 3)
        result.total_execution_time_ms = total_time_ms

        await self._update_run_final_state(workflow_run_id, result)

        logger.info(
            "workflow_finished",
            workflow_run_id=str(workflow_run_id),
            status=result.status,
            success=result.success,
            total_time_ms=total_time_ms,
            total_cost_usd=result.total_cost_usd,
        )

        return result

    async def _create_run(
        self,
        workflow_input: WorkflowInput,
        project_id: uuid.UUID,
        mode: WorkflowMode,
    ) -> Any:
        """Create a persistent WorkflowRun via the existing service.

        Args:
            workflow_input: Workflow parameters.
            project_id: Project UUID.
            mode: Execution mode.

        Returns:
            The created WorkflowRun ORM instance.

        Raises:
            RuntimeError: If creation fails.
        """
        try:
            run = await create_workflow_run(
                db=self._db,
                project_id=project_id,
                topic=workflow_input.topic,
                mode=mode,
            )
        except Exception as exc:
            logger.exception("workflow_run_creation_failed", error=str(exc))
            raise RuntimeError(f"Failed to create WorkflowRun: {exc}") from exc

        logger.info(
            "workflow_run_created",
            workflow_run_id=str(run.id),
            topic=workflow_input.topic,
            platform=workflow_input.platform,
        )
        return run

    async def _build_failure_result(
        self,
        *,
        workflow_run_id: uuid.UUID,
        error: str,
        started_at: datetime,
        start_perf: float,
    ) -> WorkflowResult:
        """Build a WorkflowResult for an unhandled orchestrator exception.

        Args:
            workflow_run_id: The WorkflowRun UUID.
            error: The exception message.
            started_at: The workflow start datetime.
            start_perf: The perf_counter start time for elapsed calculation.

        Returns:
            A failed WorkflowResult.
        """
        total_time_ms = round((time.perf_counter() - start_perf) * 1000, 3)
        return WorkflowResult(
            workflow_id=str(workflow_run_id),
            status=WorkflowStatus.FAILED.value,
            success=False,
            completed_stages=[],
            failed_stage=None,
            stage_results=[],
            error=error,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            total_execution_time_ms=total_time_ms,
            total_cost_usd=0.0,
            artifacts={},
        )

    async def _update_run_final_state(
        self,
        workflow_run_id: uuid.UUID,
        result: WorkflowResult,
    ) -> None:
        """Write the final result back to the persistent WorkflowRun.

        Args:
            workflow_run_id: The WorkflowRun UUID.
            result: The final WorkflowResult.
        """
        try:
            update = WorkflowRunUpdateRequest(
                status=WorkflowStatus(result.status),
                total_cost_usd=result.total_cost_usd,
            )
            await update_workflow_run(self._db, workflow_run_id, update)
        except Exception as exc:
            logger.error(
                "workflow_run_update_failed",
                workflow_run_id=str(workflow_run_id),
                error=str(exc),
            )
