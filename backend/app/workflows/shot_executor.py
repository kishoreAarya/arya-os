"""ShotExecutor — executes every storyboard shot through the generation pipeline.

Integrates with the existing Orchestrator architecture by reusing the
same stage-execution mechanism (agent-registry lookup, retry logic,
timing, cost tracking, and StageResult wrapping).  Does not publish,
write to the database, or run analytics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult
from app.agents.storyboard import Shot
from app.core.logging import get_logger
from app.workflows.models import StageResult
from app.workflows.stage_executor import execute_stage, _merge_context

logger = get_logger("arya.workflows.shot_executor")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ShotExecutionResult:
    shot_number: int
    stage_results: list[StageResult] = field(default_factory=list)
    positive_prompt: str = ""
    negative_prompt: str = ""
    image_path: str | None = None
    video_path: str | None = None
    voice_path: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    success: bool = False
    error: str | None = None


@dataclass
class ShotExecutionSummary:
    results: list[ShotExecutionResult] = field(default_factory=list)

    video_clips: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    voice_paths: list[str] = field(default_factory=list)

    total_cost: float = 0.0
    total_duration: float = 0.0


# ---------------------------------------------------------------------------
# ShotExecutor
# ---------------------------------------------------------------------------


class ShotExecutor:
    """Executes a list of storyboard shots through Prompt → Image → Video → Voice.

    Each shot runs sequentially.  One shot failing does not abort the
    remaining shots.  The class delegates stage execution to the shared
    ``execute_stage`` helper so that Orchestrator and ShotExecutor
    follow the same execution path.
    """

    def __init__(self, db: AsyncSession, max_retries: int = 3) -> None:
        self._db = db
        self._max_retries = max_retries

    async def execute(self, context: dict[str, Any]) -> ShotExecutionSummary:
        """Run every shot in *context["shots"]* through the pipeline.

        Args:
            context: Execution context containing at least ``shots``.
                Each entry is a :class:`Shot` dataclass.

        Returns:
            Summary with per-shot results and rolled-up totals.
        """
        shots: list[Shot] = context.get("shots", [])

        logger.info(
            "shot_executor_summary",
            shot_count=len(shots),
        )

        if not shots:
            logger.warning("shot_executor_no_shots")
            logger.info(
                "shot_summary_debug",
                video_clips=video_clips,
                image_paths=image_paths,
                voice_paths=voice_paths,
            )
            return ShotExecutionSummary()

        results: list[ShotExecutionResult] = []
        total_cost = 0.0
        total_duration = 0.0

        video_clips = []
        image_paths = []
        voice_paths = []

        for shot in shots:
            shot_result = await self._execute_single_shot(shot, context)
            results.append(shot_result)
            if shot_result.video_path:
                video_clips.append(shot_result.video_path)

            if shot_result.image_path:
                image_paths.append(shot_result.image_path)

            if shot_result.voice_path:
                voice_paths.append(shot_result.voice_path)
            total_cost += shot_result.cost_usd
            total_duration += shot_result.duration_seconds

        return ShotExecutionSummary(
            results=results,
            video_clips=video_clips,
            image_paths=image_paths,
            voice_paths=voice_paths,
            total_cost=total_cost,
            total_duration=total_duration,
        )

    async def _execute_single_shot(
        self,
        shot: Shot,
        base_context: dict[str, Any],
    ) -> ShotExecutionResult:
        """Execute one shot through Prompt → Image → Video → Voice."""
        shot_start = time.perf_counter()
        if isinstance(shot, dict):
            shot_number = shot.get("shot_number", 0)
            shot_description = shot.get("description", "")
        else:
            shot_number = shot.shot_number
            shot_description = shot.description

        result = ShotExecutionResult(
            shot_number=shot_number,
        )
        stage_results: list[StageResult] = []
        shot_cost = 0.0

        shot_context = _merge_context(base_context, {
            "shot_number": shot_number,
            "shot_description": shot_description,
        })

        # Inject optional cinematic metadata if present on the shot.
        if getattr(shot, "camera_angle", None):
            shot_context["camera_style"] = shot.camera_angle
        if getattr(shot, "lighting", None):
            shot_context["lighting_style"] = shot.lighting
        if getattr(shot, "environment", None):
            shot_context["environment_bible"] = shot.environment
        if getattr(shot, "continuity_notes", None):
            shot_context["continuity_notes"] = shot.continuity_notes
        if getattr(shot, "duration_seconds", None):
            shot_context["duration_seconds"] = shot.duration_seconds
        if getattr(shot, "dialogue", None):
            shot_context["dialogue"] = shot.dialogue
        if getattr(shot, "voiceover", None):
            shot_context["voiceover"] = shot.voiceover
        if getattr(shot, "transition", None):
            shot_context["transition"] = shot.transition
        if getattr(shot, "image_prompt_hint", None):
            shot_context["image_prompt_hint"] = shot.image_prompt_hint
        if getattr(shot, "negative_prompt_hint", None):
            shot_context["negative_prompt_hint"] = shot.negative_prompt_hint

        logger.info(
            "shot_execution_started",
            shot_number=shot_number,
            description=shot_description,
        )

        stages = ["prompt", "image", "video", "voice"]

        for stage_key in stages:
            stage_result = await execute_stage(
                stage_key=stage_key,
                context=shot_context,
                db=self._db,
                max_retries=self._max_retries,
            )
            stage_results.append(stage_result)
            shot_cost += stage_result.cost_usd or 0.0

            if not stage_result.success:
                result.error = f"{stage_key} failed: {stage_result.error}"
                result.stage_results = stage_results
                result.duration_seconds = time.perf_counter() - shot_start
                result.cost_usd = shot_cost
                logger.warning(
                    "shot_execution_failed",
                    shot_number=shot_number,
                    stage=stage_key,
                    error=stage_result.error,
                )
                return result

            if stage_result.output:
                shot_context = _merge_context(shot_context, stage_result.output)

        # Collect outputs safely.
        result.positive_prompt = _extract_str(shot_context, "positive_prompt") or ""
        result.negative_prompt = _extract_str(shot_context, "negative_prompt") or ""
        result.image_path = (
            _extract_str(shot_context, "image_path")
            or _extract_str(shot_context, "storage_path")
        )
        result.video_path = (
            _extract_str(shot_context, "video_path")
            or _extract_str(shot_context, "video_storage_path")
        )
        result.voice_path = (
            _extract_str(shot_context, "voice_path")
            or _extract_str(shot_context, "audio_path")
        )
        result.stage_results = stage_results
        result.cost_usd = shot_cost
        result.duration_seconds = time.perf_counter() - shot_start
        result.success = True

        logger.info(
            "shot_execution_succeeded",
            shot_number=shot_number,
            cost_usd=shot_cost,
            duration_seconds=result.duration_seconds,
        )

        logger.info(
            "shot_result_debug",
            video_path=result.video_path,
            image_path=result.image_path,
            voice_path=result.voice_path,
        )

        return result


def _extract_str(context: dict[str, Any], key: str) -> str | None:
    """Safely extract a non-empty string value from context."""
    value = context.get(key)
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None