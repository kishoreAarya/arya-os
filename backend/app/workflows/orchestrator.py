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
from app.workflows.stage_executor import execute_stage, _merge_context
from app.workflows.shot_executor import ShotExecutor
from app.workflows.video_assembler import VideoAssembler

logger = get_logger("arya.workflows.orchestrator")

# ---------------------------------------------------------------------------
# Pipeline definition
# ---------------------------------------------------------------------------

_PIPELINE: List[str] = [
   "trend",
   "script",
   "storyboard",
   "shot_executor",
   "video_assembler",
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
   "shot_executor": PipelineStage.VIDEO_GENERATED,
   "video_assembler": PipelineStage.VIDEO_GENERATED,
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

       if hasattr(workflow_input, "model_dump"):
           context = workflow_input.model_dump()
       else:
           context = dict(workflow_input)

       logger.info(
           "workflow_input_received",
           topic=context.get("topic"),
           platform=context.get("platform"),
           language=context.get("language"),
           style=context.get("style"),
       )

       context["workflow_run_id"] = str(workflow_run_id)

       for stage_key in _PIPELINE:
           result = await self._execute_stage(stage_key, context)
           stage_results.append(result)

           if not result.success:
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
                   total_cost_usd=total_cost_usd,
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
               context = _merge_context(context, result.output)

           logger.info(
               "context_after_merge",
               stage=stage_key,
               platform=context.get("platform"),
           )

           # Persist the Video aggregate immediately after successful video assembly.
           if stage_key == "video_assembler":
               video_storage_path = context.get("video_storage_path")

               if video_storage_path:
                   video_row = Video(
                       workflow_run_id=workflow_run_id,
                       storage_path=video_storage_path,
                       duration_seconds=context.get("video_duration_seconds"),
                       publish_status=PublishStatus.DRAFT,
                   )

                   self._db.add(video_row)
                   await self._db.flush()

                   context["video_id"] = str(video_row.id)

                   logger.info(
                       "video_row_created",
                       video_id=context["video_id"],
                       storage_path=video_storage_path,
                   )

           logger.info(
               "stage_completed",
               workflow_run_id=str(workflow_run_id),
               stage=stage_key,
               progress=f"{len(completed_stages)}/{len(_PIPELINE)}",
               cost_usd=result.cost_usd,
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
       """Thin dispatch wrapper: storage, shot_executor, and
       video_assembler stages are local to Orchestrator; everything
       else delegates to the shared execute_stage helper."""
       stage_start = time.perf_counter()
       started_at = datetime.now(timezone.utc)

       if stage_key == "shot_executor":
        shot_executor = ShotExecutor(self._db)

        logger.info("shot_executor_starting")

        try:
            summary = await shot_executor.execute(context)

            logger.info("shot_executor_finished")

            execution_time_ms = round(
                (time.perf_counter() - stage_start) * 1000,
                3,
            )

            return StageResult(
                stage="shot_executor",
                success=True,
                output={
                    "shot_execution_summary": summary,
                    "video_clips": [
                        r.video_path for r in summary.results if r.video_path
                    ],
                    "image_paths": [
                        r.image_path for r in summary.results if r.image_path
                    ],
                    "voice_paths": [
                        r.voice_path for r in summary.results if r.voice_path
                    ],
                },
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
                cost_usd=summary.total_cost,
            )

        except Exception as exc:
            import traceback

            logger.exception("SHOT EXECUTOR CRASH")
            print(traceback.format_exc())

            execution_time_ms = round(
                (time.perf_counter() - stage_start) * 1000,
                3,
            )

            return StageResult(
                stage="shot_executor",
                success=False,
                output={},
                error=f"ShotExecutor failed: {exc}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
            )

       if stage_key == "video_assembler":
           try:
               summary = context.get("shot_execution_summary")
               if not summary:
                   return StageResult(
                       stage="video_assembler",
                       success=False,
                       output={},
                       error="No shot execution summary found in context",
                       started_at=started_at,
                       execution_time_ms=round((time.perf_counter() - stage_start) * 1000, 3),
                   )

               assembler = VideoAssembler(self._db)
               assembly = await assembler.assemble(summary)
               execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)

               if not assembly.success:
                   return StageResult(
                       stage="video_assembler",
                       success=False,
                       output={},
                       error=assembly.error or "Video assembly failed",
                       started_at=started_at,
                       completed_at=datetime.now(timezone.utc),
                       execution_time_ms=execution_time_ms,
                   )

               return StageResult(
                   stage="video_assembler",
                   success=True,
                   output={
                       "video_storage_path": assembly.final_video_path,
                       "video_duration_seconds": assembly.duration_seconds,
                   },
                   started_at=started_at,
                   completed_at=datetime.now(timezone.utc),
                   execution_time_ms=execution_time_ms,
               )
           except Exception as exc:
               execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
               return StageResult(
                   stage="video_assembler",
                   success=False,
                   output={},
                   error=f"VideoAssembler failed: {exc}",
                   started_at=started_at,
                   completed_at=datetime.now(timezone.utc),
                   execution_time_ms=execution_time_ms,
               )
       if stage_key == "storage":
        return await self._execute_storage_stage(
            context=context,
            stage_start=stage_start,
            started_at=started_at,
        )

       return await execute_stage(
            stage_key,
            context,
            self._db,
            self._max_retries,
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