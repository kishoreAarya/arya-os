"""
ThumbnailAgent — generates a thumbnail image.

Uses Capability.IMAGE_GENERATION via the shared media dispatch
(app/providers/media_dispatch.py) to route to fal, comfyui, or
replicate depending on provider availability and cost ceilings.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine


@dataclass
class ThumbnailResult:
    """Strongly-typed output of ThumbnailAgent.run() — attached under
    AgentResult.output["thumbnail_result"]. Mirrors the Thumbnail model
    (app/models/media.py)."""

    prompt: str
    storage_path: str | None = None


def _build_thumbnail_prompt(topic: str, style_guide: str | None) -> str:
    """TODO: real thumbnail prompt engineering (CTR-oriented framing,
    bold text overlays, face/expression emphasis) is deliberately not
    built here — same "simplest prompt that could work" approach as
    ImageAgent."""
    prompt = f"Eye-catching YouTube thumbnail for a video about: {topic}"
    if style_guide:
        prompt += f", style: {style_guide}"
    return prompt


class ThumbnailAgent(BaseAgent):
    name = "thumbnail_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        topic (str, required)
        style_guide (str, optional)
        """
        topic = context.get("topic")
        if not topic or not str(topic).strip():
            return AgentResult(
                success=False, error="context.topic is required and was empty"
            )

        prompt = _build_thumbnail_prompt(topic, context.get("style_guide"))

        exec_result = await self._execution_engine.execute(
            capability=Capability.IMAGE_GENERATION,
            call=build_media_generation_call(
                capability=Capability.IMAGE_GENERATION,
                prompt=prompt,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="thumbnail_generation",
            validator_name="thumbnail",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        storage_path = output.get("storage_path")

        thumbnail_result = ThumbnailResult(
            prompt=prompt,
            storage_path=storage_path,
        )

        result_output = {
            "thumbnail_result": thumbnail_result,
            "thumbnail_storage_path": storage_path,
            "topic": topic,
        }

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
