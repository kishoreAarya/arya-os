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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult
from app.agents.registry import AGENT_REGISTRY
from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.models.approval import ApprovalAction, ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import WorkflowRun
from app.models.enums import ApprovalStage, PipelineStage, WorkflowMode, WorkflowStatus
from app.services.pipeline_state import advance_stage
from app.services.workflow_execution_service import (
    hydrate_resume_context,
    suspend_for_approval,
    update_heartbeat,
)
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
    "music",
    "video_assembler",
    "thumbnail",
    "storage",
    "metadata",
    "publishing",
    "analytics",
]

_CINEMATIC_PIPELINE: List[str] = [
    "trend",
    "script",
    "voice",
    "storyboard",
    "shot_executor",
    "music",
    "video_assembler",
    "thumbnail",
    "storage",
    "metadata",
    "publishing",
    "analytics",
]

# Mapping from AGENT_REGISTRY key to PipelineStage for the state machine.
# The synthetic "storage" and "metadata" stages map to APPROVED since
# they prepare approved assets immediately prior to publishing.
_KEY_TO_PIPELINE_STAGE: Dict[str, PipelineStage] = {
    "trend": PipelineStage.TREND_SELECTED,
    "script": PipelineStage.SCRIPT_GENERATED,
    "voice": PipelineStage.SCRIPT_GENERATED,
    "storyboard": PipelineStage.STORYBOARD_GENERATED,
    "shot_executor": PipelineStage.VIDEO_GENERATED,
    "music": PipelineStage.VIDEO_GENERATED,
    "video_assembler": PipelineStage.VIDEO_GENERATED,
    "thumbnail": PipelineStage.APPROVED,
    "storage": PipelineStage.APPROVED,
    "metadata": PipelineStage.APPROVED,
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

   def __init__(self, db: AsyncSession, max_retries: int = 3, worker_id: str | None = None) -> None:
       self._db = db
       self._max_retries = max(0, max_retries)
       self._worker_id = worker_id
       logger.info(
           "orchestrator_initialized",
           stage_count=len(_PIPELINE),
           max_retries=self._max_retries,
           worker_id=self._worker_id,
       )

   def _get_pipeline(self, context: Dict[str, Any]) -> List[str]:
       """Determine pipeline stage order based on cinematic or standard workflow."""
       if context.get("use_cinematic_director") or context.get("cinematic_mode"):
           return _CINEMATIC_PIPELINE
       return _PIPELINE

   async def run(
       self,
       workflow_run_id: uuid.UUID,
       workflow_input: Dict[str, Any],
       resume_from_stage: str | None = None,
   ) -> WorkflowResult:
       """
       Execute the full pipeline sequentially, with support for resuming from a stage.

       Args:
           workflow_run_id: The persistent WorkflowRun UUID.
           workflow_input: Initial input parameters (topic, style, etc.).
           resume_from_stage: Optional stage to resume execution from.

       Returns:
           WorkflowResult with final status, outputs, and timing.
       """
       logger.info(
           "workflow_started",
           workflow_run_id=str(workflow_run_id),
           resume_from_stage=resume_from_stage,
       )

       started_at = datetime.now(timezone.utc)
       start_perf = time.perf_counter()
       stage_results: List[StageResult] = []
       total_cost_usd = 0.0

       # Seed the execution context with workflow parameters

       if hasattr(workflow_input, "model_dump"):
           context = workflow_input.model_dump()
       else:
           context = dict(workflow_input)

       meta = context.get("metadata")
       if isinstance(meta, dict):
           for k, v in meta.items():
               if k not in context:
                   context[k] = v

       logger.info(
           "workflow_input_received",
           topic=context.get("topic"),
           platform=context.get("platform"),
           language=context.get("language"),
           style=context.get("style"),
           aspect_ratio=context.get("aspect_ratio"),
       )

       from app.core.aspect_ratio import validate_aspect_ratio
       raw_ar = context.get("aspect_ratio")
       try:
           context["aspect_ratio"] = validate_aspect_ratio(raw_ar)
       except ValueError as exc:
           return self._build_result(
               workflow_run_id=workflow_run_id,
               status=WorkflowStatus.FAILED.value,
               success=False,
               completed_stages=[],
               failed_stage="validation",
               stage_results=[],
               error=str(exc),
               started_at=started_at,
               start_perf=start_perf,
               total_cost_usd=0.0,
               context=context,
           )

       context["workflow_run_id"] = str(workflow_run_id)

       # Hydrate execution context from persisted database artifacts if available
       try:
           context = await hydrate_resume_context(self._db, workflow_run_id, context)
       except Exception as exc:
           logger.warning("hydrate_resume_context_warning", error=str(exc))

       # Query workflow mode
       workflow_mode = WorkflowMode.AUTONOMOUS
       try:
           run_row = await self._db.get(WorkflowRun, workflow_run_id)
           if run_row:
               if getattr(run_row, "mode", None):
                   workflow_mode = run_row.mode
               if getattr(run_row, "total_cost_usd", None) is not None and resume_from_stage:
                   total_cost_usd = float(run_row.total_cost_usd)
       except Exception:
           pass

       pipeline = self._get_pipeline(context)
       if resume_from_stage and resume_from_stage in pipeline:
           start_idx = pipeline.index(resume_from_stage)
           completed_stages = list(pipeline[:start_idx])
           stages_to_run = pipeline[start_idx:]
       else:
           completed_stages = []
           stages_to_run = list(pipeline)

       for stage_key in stages_to_run:
           # Heartbeat before stage
           await update_heartbeat(self._db, workflow_run_id, worker_id=self._worker_id)

           result = await self._execute_stage(stage_key, context)
           stage_results.append(result)

           if not result.success:
               try:
                   run_row = await self._db.get(WorkflowRun, workflow_run_id)
                   if run_row:
                       run_row.last_completed_stage = completed_stages[-1] if completed_stages else None
                       await self._db.commit()
               except Exception:
                   pass
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
               summary = context.get("shot_execution_summary")

               logger.info(
                    "orchestrator_summary_debug",
                    summary_is_none=summary is None,
                    result_count=len(summary.results) if summary else 0,
                    video_clips=summary.video_clips if summary else [],
               )

           logger.info(
               "context_after_merge",
               stage=stage_key,
               platform=context.get("platform"),
           )

           # Persist the Script aggregate
           if stage_key == "script":
               script_content = (
                   context.get("script_content")
                   or (context.get("script") if isinstance(context.get("script"), str) else None)
                   or (context.get("script", {}).get("content") if isinstance(context.get("script"), dict) else None)
               )
               if script_content:
                   try:
                       s_stmt = (
                           select(Script)
                           .where(Script.workflow_run_id == workflow_run_id)
                           .order_by(Script.created_at.desc())
                           .limit(1)
                       )
                       s_res = await self._db.execute(s_stmt)
                       existing_script = s_res.scalar_one_or_none()
                       if not existing_script:
                           script_row = Script(
                               workflow_run_id=workflow_run_id,
                               content=str(script_content),
                               word_count=len(str(script_content).split()),
                           )
                           self._db.add(script_row)
                           await self._db.flush()
                           context["script_id"] = str(script_row.id)
                       else:
                           context["script_id"] = str(existing_script.id)
                   except Exception as exc:
                       logger.warning("script_persistence_warning", error=str(exc))

           # Persist the Storyboard aggregate
           if stage_key == "storyboard":
               shots_data = context.get("storyboard") or context.get("shots")
               script_id = context.get("script_id")
               if shots_data and script_id:
                   try:
                       sb_stmt = (
                           select(Storyboard)
                           .where(Storyboard.script_id == uuid.UUID(str(script_id)))
                           .order_by(Storyboard.created_at.desc())
                           .limit(1)
                       )
                       sb_res = await self._db.execute(sb_stmt)
                       existing_sb = sb_res.scalar_one_or_none()
                       if not existing_sb:
                           sb_shots = shots_data if isinstance(shots_data, (dict, list)) else {"shots": shots_data}
                           sb_row = Storyboard(
                               script_id=uuid.UUID(str(script_id)),
                               shots=sb_shots if isinstance(sb_shots, dict) else {"shots": sb_shots},
                           )
                           self._db.add(sb_row)
                           await self._db.flush()
                           context["storyboard_id"] = str(sb_row.id)
                       else:
                           context["storyboard_id"] = str(existing_sb.id)
                   except Exception as exc:
                       logger.warning("storyboard_persistence_warning", error=str(exc))

           # Persist the Video aggregate immediately after successful video assembly.
           if stage_key == "video_assembler":
               video_storage_path = context.get("video_storage_path")

               if video_storage_path:
                   try:
                       v_stmt = (
                           select(Video)
                           .where(Video.workflow_run_id == workflow_run_id)
                           .order_by(Video.created_at.desc())
                           .limit(1)
                       )
                       v_res = await self._db.execute(v_stmt)
                       existing_video = v_res.scalar_one_or_none()
                       if not existing_video:
                           video_row = Video(
                               workflow_run_id=workflow_run_id,
                               storage_path=video_storage_path,
                               duration_seconds=context.get("video_duration_seconds"),
                               publish_status=PublishStatus.DRAFT,
                               aspect_ratio=context.get("aspect_ratio", "16:9"),
                           )

                           self._db.add(video_row)
                           await self._db.flush()

                           context["video_id"] = str(video_row.id)
                       else:
                           context["video_id"] = str(existing_video.id)

                       logger.info(
                           "video_row_created",
                           video_id=context.get("video_id"),
                           storage_path=video_storage_path,
                       )
                   except Exception as exc:
                       logger.warning("video_persistence_warning", error=str(exc))

           # Persist last_completed_stage
           try:
               run_row = await self._db.get(WorkflowRun, workflow_run_id)
               if run_row:
                   run_row.last_completed_stage = stage_key
                   await self._db.commit()
           except Exception as exc:
               logger.warning("last_completed_stage_update_warning", stage=stage_key, error=str(exc))

           # Advance WorkflowRun.current_stage in persistent storage
           target_stage = _KEY_TO_PIPELINE_STAGE.get(stage_key)
           if target_stage:
               try:
                   await advance_stage(self._db, workflow_run_id, target_stage)
               except Exception as exc:
                   logger.warning(
                       "stage_advance_warning",
                       stage=stage_key,
                       target_stage=target_stage.value,
                       error=str(exc),
                   )

           # Heartbeat after stage
           await update_heartbeat(self._db, workflow_run_id, worker_id=self._worker_id)

           logger.info(
               "stage_completed",
               workflow_run_id=str(workflow_run_id),
               stage=stage_key,
               progress=f"{len(completed_stages)}/{len(pipeline)}",
               cost_usd=result.cost_usd,
           )

           # Check approval boundaries for human-in-the-loop workflows
           if workflow_mode in (WorkflowMode.MANUAL, WorkflowMode.ASSISTED):
               approval_stage_enum: ApprovalStage | None = None
               ref_table: str = ""
               ref_id: uuid.UUID = workflow_run_id

               if stage_key == "script":
                   approval_stage_enum = ApprovalStage.SCRIPT
                   ref_table = "scripts"
                   if context.get("script_id"):
                       try:
                           ref_id = uuid.UUID(str(context["script_id"]))
                       except (ValueError, TypeError):
                           pass
               elif stage_key == "video_assembler":
                   approval_stage_enum = ApprovalStage.VIDEO
                   ref_table = "videos"
                   if context.get("video_id"):
                       try:
                           ref_id = uuid.UUID(str(context["video_id"]))
                       except (ValueError, TypeError):
                           pass

               if approval_stage_enum is not None:
                   try:
                       cp_stmt = (
                           select(ApprovalCheckpoint)
                           .where(
                               ApprovalCheckpoint.workflow_run_id == workflow_run_id,
                               ApprovalCheckpoint.stage == approval_stage_enum,
                           )
                           .order_by(ApprovalCheckpoint.created_at.desc())
                           .limit(1)
                       )
                       cp_res = await self._db.execute(cp_stmt)
                       cp = cp_res.scalar_one_or_none()

                       if cp is not None and cp.action == ApprovalAction.APPROVE:
                           logger.info(
                               "approval_checkpoint_previously_approved",
                               stage=stage_key,
                               checkpoint_id=str(cp.id),
                           )
                       else:
                           if cp is None:
                               cp = ApprovalCheckpoint(
                                   workflow_run_id=workflow_run_id,
                                   stage=approval_stage_enum,
                                   reference_table=ref_table,
                                   reference_id=ref_id,
                               )
                               self._db.add(cp)
                               await self._db.flush()

                           if cp.action is None:
                               await suspend_for_approval(self._db, workflow_run_id, cp.id)
                               logger.info(
                                   "workflow_suspended_for_approval",
                                   workflow_run_id=str(workflow_run_id),
                                   stage=stage_key,
                                   checkpoint_id=str(cp.id),
                               )
                               return self._build_result(
                                   workflow_run_id=workflow_run_id,
                                   status=WorkflowStatus.AWAITING_APPROVAL.value,
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
                   except Exception as exc:
                       logger.error("approval_boundary_check_error", stage=stage_key, error=str(exc))

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

       if stage_key == "storyboard":
           if context.get("use_cinematic_director") or context.get("cinematic_mode"):
               if not context.get("narration_timing"):
                   from app.core.audio_timing import build_narration_timing
                   script_text = context.get("script_content") or context.get("script") or ""
                   if script_text:
                       dur = float(context.get("duration") or context.get("target_duration") or 20.0)
                       context["narration_timing"] = build_narration_timing(
                           text=str(script_text), duration_seconds=dur
                       ).model_dump()
               return await execute_stage(
                   "cinematic_director",
                   context,
                   self._db,
                   self._max_retries,
               )

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

       if stage_key == "music":
           return await self._execute_music_stage(context)

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
               music_path = context.get("music_path")
               aspect_ratio = context.get("aspect_ratio", "16:9")
               target_duration = context.get("duration")

               narration_timing = context.get("narration_timing")
               captions_enabled = context.get("captions_enabled", False)
               captions_required = context.get("captions_required", False)
               if context.get("use_cinematic_director") or context.get("cinematic_mode"):
                   captions_enabled = True
                   captions_required = True

               assembly = await assembler.assemble(
                   summary,
                   music_path=music_path,
                   aspect_ratio=aspect_ratio,
                   target_duration=target_duration,
                   music_volume=context.get("music_volume", 0.25),
                   music_ducking_volume=context.get("music_ducking_volume", 0.08),
                   master_voice_path=context.get("master_voice_path") or context.get("voice_path"),
                   master_audio_plan=context.get("master_audio_plan"),
                   narration_timing=narration_timing,
                   captions_enabled=captions_enabled,
                   captions_required=captions_required,
               )
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

               output_payload = {
                   "video_storage_path": assembly.final_video_path,
                   "video_duration_seconds": assembly.duration_seconds,
                   "aspect_ratio": aspect_ratio,
                   "captions": assembly.captions or [],
                   "captions_burned_in": assembly.captions_burned_in,
                   "captions_required": captions_required,
               }
               if assembly.caption_timeline:
                   output_payload["caption_timeline"] = assembly.caption_timeline.model_dump()

               # Mandatory technical and caption validation for cinematic productions
               if captions_required:
                   from app.validators.video_validator import VideoValidator
                   val_artifact = {
                       "video_storage_path": assembly.final_video_path,
                       "duration_seconds": assembly.duration_seconds,
                       "aspect_ratio": aspect_ratio,
                       "captions": assembly.captions or [],
                       "captions_required": True,
                       "voice_duration_seconds": context.get("voice_duration_seconds"),
                   }
                   val_res = VideoValidator(captions_required=True).validate(val_artifact)
                   if not val_res.passed:
                       return StageResult(
                           stage="video_assembler",
                           success=False,
                           output=output_payload,
                           error=f"Video validation failed: {'; '.join(val_res.issues)}",
                           started_at=started_at,
                           completed_at=datetime.now(timezone.utc),
                           execution_time_ms=execution_time_ms,
                       )

               return StageResult(
                   stage="video_assembler",
                   success=True,
                   output=output_payload,
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

   async def _execute_music_stage(
       self,
       context: Dict[str, Any],
   ) -> StageResult:
       stage_start = time.perf_counter()
       started_at = datetime.now(timezone.utc)

       music_enabled = context.get("music_enabled", True)
       if not music_enabled:
           logger.info("music_stage_disabled_by_config")
           return StageResult(
               stage="music",
               success=True,
               output={
                   "music_path": None,
                   "music_skipped": True,
               },
               started_at=started_at,
               completed_at=datetime.now(timezone.utc),
               execution_time_ms=round((time.perf_counter() - stage_start) * 1000, 3),
           )

       summary = context.get("shot_execution_summary")
       duration = None
       if summary and hasattr(summary, "total_duration") and summary.total_duration:
           duration = summary.total_duration
       if not duration:
           duration = context.get("duration", 30)

       music_context = {
           "topic": context.get("topic", ""),
           "style": context.get("style", ""),
           "mood": context.get("music_mood") or context.get("mood", "cinematic"),
           "music_style": context.get("music_style"),
           "target_duration_seconds": duration,
           "aspect_ratio": context.get("aspect_ratio", "16:9"),
           "provider": context.get("music_provider"),
           "model": context.get("music_model"),
           "workflow_run_id": context.get("workflow_run_id"),
       }

       from app.agents.music import MusicAgent
       agent = MusicAgent(self._db)
       try:
           agent_result = await agent.run(music_context)
           execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)

           if agent_result.success and agent_result.output:
               music_path = agent_result.output.get("music_path")
               return StageResult(
                   stage="music",
                   success=True,
                   output={
                       "music_path": music_path,
                       "music_result": agent_result.output.get("music_result"),
                   },
                   started_at=started_at,
                   completed_at=datetime.now(timezone.utc),
                   execution_time_ms=execution_time_ms,
                   cost_usd=agent_result.cost_usd,
               )
           else:
               logger.warning(
                   "music_stage_failed_fallback_to_silent",
                   error=agent_result.error,
               )
               return StageResult(
                   stage="music",
                   success=True,
                   output={
                       "music_path": None,
                       "music_error": agent_result.error,
                       "fallback": True,
                   },
                   started_at=started_at,
                   completed_at=datetime.now(timezone.utc),
                   execution_time_ms=execution_time_ms,
               )
       except Exception as exc:
           logger.warning(
               "music_stage_exception_fallback_to_silent",
               error=str(exc),
           )
           return StageResult(
               stage="music",
               success=True,
               output={
                   "music_path": None,
                   "music_error": str(exc),
                   "fallback": True,
               },
               started_at=started_at,
               completed_at=datetime.now(timezone.utc),
               execution_time_ms=round((time.perf_counter() - stage_start) * 1000, 3),
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
       completed_at = (
           None
           if status == WorkflowStatus.AWAITING_APPROVAL.value
           else datetime.now(timezone.utc)
       )
       return WorkflowResult(
           workflow_id=str(workflow_run_id),
           status=status,
           success=success,
           completed_stages=completed_stages,
           failed_stage=failed_stage,
           stage_results=stage_results,
           error=error,
           started_at=started_at,
           completed_at=completed_at,
           total_execution_time_ms=total_time_ms,
           total_cost_usd=total_cost_usd,
           artifacts={
               k: v
               for k, v in context.items()
               if k not in ("workflow_run_id", "topic", "style", "language", "duration", "platform")
           },
       )