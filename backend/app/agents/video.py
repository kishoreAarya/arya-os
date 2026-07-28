"""
VideoAgent — generates one video clip per shot (image-to-video).

Uses Capability.VIDEO_GENERATION (fal, comfyui already registered).
No video provider adapter exists yet — same honest-stub pattern as
ImageAgent/VoiceAgent: `_call_provider` raises for every candidate,
surfacing a real AllProvidersFailedError rather than faking output.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability, ProviderCapability
from app.services.execution_engine import ExecutionEngine


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
        shot_number (int, optional)
        target_duration_seconds (float, optional) — per
            ARYA_OS_BUILD_INSTRUCTIONS.md's Voice-before-Video fix:
            the Voice Agent's narration duration should drive this,
            not the other way around.
        """
        source_image_path = context.get("source_image_path")
        if not source_image_path:
            return AgentResult(
                success=False,
                error="context.source_image_path is required and was empty",
            )

        target_duration = context.get("target_duration_seconds")

        async def call_provider(provider: ProviderCapability) -> tuple[dict, float]:
            # TODO: real integration required — no video provider
            # adapter exists yet. Both "fal" and "comfyui" (the
            # Capability.VIDEO_GENERATION candidates) raise here until
            # one is written.
            raise RuntimeError(
                f"No video-generation adapter implemented yet for provider "
                f"'{provider.name}' (source_image_path={source_image_path!r}, "
                f"target_duration_seconds={target_duration!r})"
            )

        exec_result = await self._execution_engine.execute(
            capability=Capability.VIDEO_GENERATION,
            call=call_provider,
            workflow_run_id=context.get("workflow_run_id"),
            stage="video_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        video_result = VideoResult(
            shot_number=context.get("shot_number"),
            source_image_path=source_image_path,
            storage_path=output.get("storage_path"),
            duration_seconds=output.get("duration_seconds"),
        )

        return AgentResult(
            success=True,
            output={"video_result": video_result},
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
