"""
Arya OS — Transient Workflow State.

In-memory accumulator used during a single workflow execution.
Not persisted to the database. Not an API schema. Not an ORM model.

Tracks execution progress, stage completion, retry counts, accumulated
costs, and artifacts while the Orchestrator runs the pipeline. At the
end of execution, the Runner reads this state to build the final
WorkflowResult and update the persistent WorkflowRun.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.enums import WorkflowStatus

PIPELINE_STAGE_COUNT: int = 12


class WorkflowState:
    """Transient state for one workflow execution.

    Attributes:
        workflow_run_id: UUID of the persistent WorkflowRun being executed.
        status: Current coarse workflow status.
        current_stage: The stage currently executing, or None.
        completed_stages: Ordered list of stage keys that finished successfully.
        failed_stage: The stage key that caused failure, or None.
        progress: Completion percentage from 0.0 to 100.0.
        retry_count: Retry attempts for the current stage.
        total_cost_usd: Accumulated cost across all completed stages.
        artifacts: Merged outputs from all completed stages.
        stage_results: Per-stage result references for the final result.
        started_at: When this workflow execution began.
        completed_at: When this workflow execution finished, or None.
    """

    def __init__(self, workflow_run_id: uuid.UUID) -> None:
        """Initialize transient state for a new workflow execution.

        Args:
            workflow_run_id: UUID of the persistent WorkflowRun.
        """
        self.workflow_run_id: uuid.UUID = workflow_run_id
        self.status: WorkflowStatus = WorkflowStatus.PENDING
        self.current_stage: Optional[str] = None
        self.completed_stages: List[str] = []
        self.failed_stage: Optional[str] = None
        self.progress: float = 0.0
        self.retry_count: int = 0
        self.total_cost_usd: float = 0.0
        self.artifacts: Dict[str, Any] = {}
        self.stage_results: List[Any] = []
        self.started_at: datetime = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def mark_running(self, stage: str) -> None:
        """Mark a stage as currently executing.

        Sets status to RUNNING, records the current stage, and resets
        the retry counter.

        Args:
            stage: The stage key that is starting.
        """
        self.status = WorkflowStatus.RUNNING
        self.current_stage = stage
        self.retry_count = 0

    def mark_stage_completed(self, stage: str, cost_usd: float, output: Dict[str, Any]) -> None:
        """Record a successfully completed stage.

        Appends the stage to completed_stages, adds its cost, merges
        its output into artifacts, and recalculates progress.

        Args:
            stage: The stage key that completed.
            cost_usd: Cost incurred by this stage.
            output: Output data produced by this stage.
        """
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        self.total_cost_usd += cost_usd
        self.artifacts.update(output)
        self.current_stage = None
        self.retry_count = 0
        self._recalculate_progress()

    def mark_failed(self, stage: str) -> None:
        """Mark the workflow as failed.

        Sets status to FAILED, records the failed stage, and stamps
        the completion time.

        Args:
            stage: The stage key that failed.
        """
        self.status = WorkflowStatus.FAILED
        self.failed_stage = stage
        self.current_stage = None
        self.completed_at = datetime.now(timezone.utc)
        self._recalculate_progress()

    def mark_completed(self) -> None:
        """Mark the workflow as fully completed.

        Sets status to COMPLETED, clears the current stage, stamps the
        completion time, and sets progress to 100.0.
        """
        self.status = WorkflowStatus.COMPLETED
        self.current_stage = None
        self.completed_at = datetime.now(timezone.utc)
        self.progress = 100.0

    def increment_retry(self) -> None:
        """Increment the retry count for the current stage."""
        self.retry_count += 1

    def _recalculate_progress(self) -> None:
        """Recalculate progress based on completed stages.

        Progress is the ratio of completed stages to the total
        pipeline length.
        """
        completed_count = len(self.completed_stages)
        self.progress = round((completed_count / PIPELINE_STAGE_COUNT) * 100.0, 2)
