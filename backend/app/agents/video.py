"""
VideoAgent — generates one video clip per shot (image-to-video).

Uses Capability.VIDEO_GENERATION via the shared media dispatch
(app/providers/media_dispatch.py) to route to fal, comfyui, or
replicate depending on provider availability and cost ceilings.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine

logger = get_logger(__name__)


@dataclass
class VideoResult:
    """Strongly-typed output of VideoAgent.run() — attached under
    AgentResult.output["video_result"]. Mirrors GeneratedVideo
    (app/models/media.py) — the per-shot clip, distinct from the final
    assembled Video row, which a future merge step (out of scope here)
    would produce."""

    shot_number: int | None
    source_image_path: str | None
    storage_path: str | None = None
    duration_seconds: float | None = None


class VideoAgent(BaseAgent):
    name = "video_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        source_image_path (str, required) — the shot's generated image
        target_duration_seconds (float, optional) — per
            ARYA_OS_BUILD_INSTRUCTIONS.md's Voice-before-Video fix:
            the Voice Agent's narration duration should drive this,
            not the other way around.
        prompt (str, optional) — text description of the desired video;
            falls back to shot_description if not provided.
        shot_description (str, optional) — the original storyboard shot
            description; used as prompt fallback.
        voice_path (str, optional) — the generated voice audio path,
            carried forward for downstream assembly.
        """
        source_image_path = context.get("source_image_path")
        if not source_image_path:
            return AgentResult(
                success=False,
                error="context.source_image_path is required and was empty",
            )

        target_duration = context.get("target_duration_seconds")

        # Use an explicit prompt if the caller provided one (e.g. from
        # PromptAgent or the image-generation prompt), otherwise fall
        # back to the shot description, then to a generic descriptor.
        prompt = (
            context.get("prompt")
            or context.get("shot_description")
            or f"Animate this image into a short video clip"
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.VIDEO_GENERATION,
            call=build_media_generation_call(
                capability=Capability.VIDEO_GENERATION,
                prompt=prompt,
                image_url=source_image_path,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="video_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        logger.info(
            "video_agent_output",
            output=output,
        )
        storage_path = output.get("storage_path")
        logger.info(
            "video_storage_path",
            storage_path=storage_path,
        )
        duration_seconds = output.get("duration_seconds")

        video_result = VideoResult(
            shot_number=context.get("shot_number"),
            source_image_path=source_image_path,
            storage_path=storage_path,
            duration_seconds=duration_seconds,
        )

        result_output = {
            "video_result": video_result,
            "video_storage_path": storage_path,
        }

        # Carry forward media paths for downstream agents (ThumbnailAgent, PublishingAgent)
        if storage_path:
            result_output["source_video_path"] = storage_path
        voice_path = context.get("voice_path")
        if voice_path:
            result_output["voice_path"] = voice_path

        # Carry shot context forward for traceability
        shot_number = context.get("shot_number")
        if shot_number is not None:
            result_output["shot_number"] = shot_number
        shot_description = context.get("shot_description")
        if shot_description:
            result_output["shot_description"] = shot_description
        if prompt:
            result_output["prompt"] = prompt
        if target_duration is not None:
            result_output["target_duration_seconds"] = target_duration

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
