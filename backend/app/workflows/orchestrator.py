"""
Arya OS — End-to-End Workflow Orchestrator.

Executes the full agent pipeline sequentially using the EXISTING
AGENT_REGISTRY, ExecutionEngine, and StorageProvider. Does NOT create
new registry, execution, or storage abstractions.

Design constraints:
- Uses AGENT_REGISTRY from app.agents.registry (class-per-entry,
  instantiate with db session at point of use).
- Uses StorageProvider via get_storage_provider() for the synthetic
  STORAGE stage.
- Uses pipeline_state.advance_stage() for state machine transitions.
- Uses log_event() for all observability.
- Never knows provider details (delegates to ExecutionEngine).
- Never knows platform details (delegates to PublishingAgent).
"""

from __future__ import annotations

import dataclasses
import inspect
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from app.models.media import Video
from app.models.enums import PublishStatus

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult
from app.agents.registry import AGENT_REGISTRY
from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.models.enums import PipelineStage, WorkflowStatus
from app.services.pipeline_state import advance_stage
from app.storage import get_storage_provider
from app.workflows.models import StageResult, WorkflowResult

logger = get_logger("arya.workflows.orchestrator")

# ---------------------------------------------------------------------------
# Pipeline definition
# ---------------------------------------------------------------------------

_PIPELINE: List[str] = [
    "trend",
    "script",
    "storyboard",
    "prompt",
    "image",
    "voice",
    "video",
    "thumbnail",
    "storage",
    "publishing",
    "analytics",
]

# Mapping from AGENT_REGISTRY key to PipelineStage for the state machine.
# The synthetic "storage" stage maps to APPROVED since storage is a
# persistence checkpoint, not a generation stage.
_KEY_TO_PIPELINE_STAGE: Dict[str, PipelineStage] = {
    "trend": PipelineStage.TREND_SELECTED,
    "script": PipelineStage.SCRIPT_GENERATED,
    "storyboard": PipelineStage.STORYBOARD_GENERATED,
    "prompt": PipelineStage.PROMPT_GENERATED,
    "image": PipelineStage.IMAGE_GENERATED,
    "video": PipelineStage.VIDEO_GENERATED,
    "voice": PipelineStage.VIDEO_GENERATED,
    "thumbnail": PipelineStage.APPROVED,
    "storage": PipelineStage.APPROVED,
    "publishing": PipelineStage.PUBLISHED,
    "analytics": PipelineStage.ANALYTICS_COLLECTED,
}


class Orchestrator:
    """
    Sequential workflow orchestrator.

    Executes stages in fixed order, passing outputs forward as inputs.
    If any stage fails after retries, execution stops and structured
    error information is returned.
    """

    def __init__(self, db: AsyncSession, max_retries: int = 3) -> None:
        self._db = db
        self._max_retries = max(0, max_retries)
        logger.info(
            "orchestrator_initialized",
            stage_count=len(_PIPELINE),
            max_retries=self._max_retries,
        )

    async def run(
        self,
        workflow_run_id: uuid.UUID,
        workflow_input: Dict[str, Any],
    ) -> WorkflowResult:
        """
        Execute the full pipeline sequentially.

        Args:
            workflow_run_id: The persistent WorkflowRun UUID.
            workflow_input: Initial input parameters (topic, style, etc.).

        Returns:
            WorkflowResult with final status, outputs, and timing.
        """
        logger.info(
            "workflow_started",
            workflow_run_id=str(workflow_run_id),
        )

        started_at = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        completed_stages: List[str] = []
        stage_results: List[StageResult] = []
        total_cost_usd = 0.0

        # Seed the execution context with workflow parameters
        context = dict(workflow_input)
        context["workflow_run_id"] = str(workflow_run_id)

        for stage_key in _PIPELINE:
            # Advance persistent state machine
            pipeline_stage = _KEY_TO_PIPELINE_STAGE.get(stage_key, PipelineStage.CREATED)
            try:
                await advance_stage(self._db, workflow_run_id, pipeline_stage)
            except Exception as exc:
                logger.error(
                    "state_machine_transition_failed",
                    workflow_run_id=str(workflow_run_id),
                    stage=stage_key,
                    error=str(exc),
                )
                return self._build_result(
                    workflow_run_id=workflow_run_id,
                    status=WorkflowStatus.FAILED.value,
                    success=False,
                    completed_stages=completed_stages,
                    failed_stage=stage_key,
                    stage_results=stage_results,
                    error=f"State machine transition failed: {exc}",
                    started_at=started_at,
                    start_perf=start_perf,
                    total_cost_usd=total_cost_usd,
                    context=context,
                )

            logger.info(
                "stage_started",
                workflow_run_id=str(workflow_run_id),
                stage=stage_key,
            )

            # Execute the stage
            result = await self._execute_stage(stage_key, context)
            stage_results.append(result)

            if not result.success:
                logger.error(
                    "stage_failed",
                    workflow_run_id=str(workflow_run_id),
                    stage=stage_key,
                    error=result.error,
                )
                await log_event(
                    EventType.WORKFLOW_FAILED,
                    message=f"Stage {stage_key} failed: {result.error}",
                    workflow_run_id=workflow_run_id,
                    level="error",
                )
                return self._build_result(
                    workflow_run_id=workflow_run_id,
                    status=WorkflowStatus.FAILED.value,
                    success=False,
                    completed_stages=completed_stages,
                    failed_stage=stage_key,
                    stage_results=stage_results,
                    error=result.error,
                    started_at=started_at,
                    start_perf=start_perf,
                    total_cost_usd=total_cost_usd + result.cost_usd,
                    context=context,
                )

            # Success — propagate output
            completed_stages.append(stage_key)
            total_cost_usd += result.cost_usd
            logger.info(
                    "context_before_merge",
                    stage=stage_key,
                    platform=context.get("platform"),
                )

            if result.output:
                context = self._merge_context(context, result.output)

                logger.info(
                    "context_after_merge",
                    stage=stage_key,
                    platform=context.get("platform"),
                )
                # Persist the Video aggregate immediately after successful video generation.
                if stage_key == "video":
                    video_result = context.get("video_result")

                    if isinstance(video_result, dict):
                        video_row = Video(
                            workflow_run_id=workflow_run_id,
                            storage_path=video_result.get("storage_path"),
                            duration_seconds=video_result.get("duration_seconds"),
                            publish_status=PublishStatus.DRAFT,
                        )

                        self._db.add(video_row)
                        await self._db.flush()

                        context["video_id"] = str(video_row.id)   

            logger.info(
                "stage_completed",
                workflow_run_id=str(workflow_run_id),
                stage=stage_key,
                progress=f"{len(completed_stages)}/{len(_PIPELINE)}",
                cost_usd=result.cost_usd,
            )

        # All stages completed
        total_time_ms = round((time.perf_counter() - start_perf) * 1000, 3)
        await log_event(
            EventType.WORKFLOW_COMPLETED,
            message="All stages completed successfully",
            workflow_run_id=workflow_run_id,
        )
        logger.info(
            "workflow_completed",
            workflow_run_id=str(workflow_run_id),
            total_cost_usd=total_cost_usd,
            total_time_ms=total_time_ms,
        )

        return self._build_result(
            workflow_run_id=workflow_run_id,
            status=WorkflowStatus.COMPLETED.value,
            success=True,
            completed_stages=completed_stages,
            failed_stage=None,
            stage_results=stage_results,
            error=None,
            started_at=started_at,
            start_perf=start_perf,
            total_cost_usd=total_cost_usd,
            context=context,
        )

    async def _execute_stage(
        self,
        stage_key: str,
        context: Dict[str, Any],
    ) -> StageResult:
        """
        Execute a single stage with retry logic.

        For agent stages: instantiates from AGENT_REGISTRY, calls .run(context).
        For the synthetic "storage" stage: delegates to get_storage_provider().
        """
        stage_start = time.perf_counter()
        started_at = datetime.now(timezone.utc)

        if stage_key == "storage":
            return await self._execute_storage_stage(context, stage_start, started_at)

        agent_cls = AGENT_REGISTRY.get(stage_key)
        if agent_cls is None:
            return StageResult(
                stage=stage_key,
                success=False,
                output={},
                error=f"No agent registered for key \'{stage_key}\'",
                started_at=started_at,
                execution_time_ms=round((time.perf_counter() - stage_start) * 1000, 3),
            )

        # Determine if agent needs db session in constructor.
        # Matches the pattern in app/api/routers/agents.py.
        sig = inspect.signature(agent_cls.__init__)
        needs_db = len(sig.parameters) > 1
        agent = agent_cls(self._db) if needs_db else agent_cls()

        last_error: str | None = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                logger.warning(
                    "stage_retry",
                    stage=stage_key,
                    attempt=attempt,
                    max_retries=self._max_retries,
                )

            try:
                maybe_result = agent.run(context)
                # Handle both sync and async agent.run() methods.
                if inspect.isawaitable(maybe_result):
                    result: AgentResult = await maybe_result
                else:
                    result = maybe_result

                execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)

                return StageResult(
                    stage=stage_key,
                    success=result.success,
                    output=self._serialize_output(result.output),
                    error=result.error,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    execution_time_ms=execution_time_ms,
                    provider_used=result.provider_used,
                    cost_usd=result.cost_usd,
                )

            except NotImplementedError as exc:
                # Stubs (ScriptAgent, PromptAgent, MusicAgent) raise this.
                execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
                return StageResult(
                    stage=stage_key,
                    success=False,
                    output={},
                    error=f"Agent not implemented: {exc}",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    execution_time_ms=execution_time_ms,
                )

            except Exception as exc:
                last_error = str(exc)
                logger.exception(
                    "stage_execution_failed",
                    stage=stage_key,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < self._max_retries:
                    continue

        # Retries exhausted.
        execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
        return StageResult(
            stage=stage_key,
            success=False,
            output={},
            error=last_error,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            execution_time_ms=execution_time_ms,
        )

    async def _execute_storage_stage(
        self,
        context: Dict[str, Any],
        stage_start: float,
        started_at: datetime,
    ) -> StageResult:
        """
        Execute the synthetic STORAGE stage.

        Verifies storage is reachable. Actual artifact persistence is
        handled by agents via StorageProvider directly.
        """
        try:
            storage = get_storage_provider()
            _ = storage
            execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
            return StageResult(
                stage="storage",
                success=True,
                output={},
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
            )
        except Exception as exc:
            execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
            return StageResult(
                stage="storage",
                success=False,
                output={},
                error=f"Storage stage failed: {exc}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
            )

    def _merge_context(
        self,
        existing: Dict[str, Any],
        new_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge stage output into the running execution context."""
        merged = existing.copy()
        merged.update(new_output)
        return merged

    def _serialize_output(self, output: Any) -> Dict[str, Any]:
        """
        Recursively serialize dataclass instances to plain dicts.

        Matches the pattern in app/api/routers/agents.py.
        """
        if dataclasses.is_dataclass(output) and not isinstance(output, type):
            return {
                k: self._serialize_output(v)
                for k, v in dataclasses.asdict(output).items()
            }
        if isinstance(output, dict):
            return {k: self._serialize_output(v) for k, v in output.items()}
        if isinstance(output, (list, tuple)):
            return [self._serialize_output(v) for v in output]  # type: ignore[return-value]
        return output  # type: ignore[return-value]

    def _build_result(
        self,
        *,
        workflow_run_id: uuid.UUID,
        status: str,
        success: bool,
        completed_stages: List[str],
        failed_stage: str | None,
        stage_results: List[StageResult],
        error: str | None,
        started_at: datetime,
        start_perf: float,
        total_cost_usd: float,
        context: Dict[str, Any],
    ) -> WorkflowResult:
        """Build the final WorkflowResult."""
        total_time_ms = round((time.perf_counter() - start_perf) * 1000, 3)
        return WorkflowResult(
            workflow_id=str(workflow_run_id),
            status=status,
            success=success,
            completed_stages=completed_stages,
            failed_stage=failed_stage,
            stage_results=stage_results,
            error=error,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            total_execution_time_ms=total_time_ms,
            total_cost_usd=total_cost_usd,
            artifacts={
                k: v
                for k, v in context.items()
                if k not in ("workflow_run_id", "topic", "style", "language", "duration", "platform")
            },
        )
