"""
ImageAgent — generates one image per storyboard shot.

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
class ImageResult:
    """Strongly-typed output of ImageAgent.run() — attached under
    AgentResult.output["image_result"]. Mirrors the fields already on
    the Image model (app/models/media.py) without this agent touching
    the database itself (that stays a router's job, same as
    ScriptAgent)."""

    shot_number: int | None
    prompt: str
    storage_path: str | None = None


def _build_image_prompt(shot_description: str, style_guide: str | None) -> str:
    """Build the image generation prompt from shot description and
    optional style guide."""
    prompt = shot_description
    if style_guide:
        prompt = f"{shot_description}, style: {style_guide}"
    return prompt


class ImageAgent(BaseAgent):
    name = "image_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        prompt (str, required) — the AI image generation prompt
        shot_description (str, required) — the original shot description
        shot_number (int, optional)
        style_guide (str, optional)
        """
        prompt = context.get("prompt")
        if not prompt or not str(prompt).strip():
            return AgentResult(
                success=False,
                error="context.prompt is required and was empty",
            )

        shot_description = context.get("shot_description")
        if not shot_description or not str(shot_description).strip():
            return AgentResult(
                success=False,
                error="context.shot_description is required and was empty",
            )

        # Use the provided prompt directly; fall back to building from shot_description
        generation_prompt = prompt if prompt else _build_image_prompt(shot_description, context.get("style_guide"))

        exec_result = await self._execution_engine.execute(
            capability=Capability.IMAGE_GENERATION,
            call=build_media_generation_call(
                capability=Capability.IMAGE_GENERATION,
                prompt=generation_prompt,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="image_generation",
            validator_name="image",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        storage_path = output.get("storage_path")

        image_result = ImageResult(
            shot_number=context.get("shot_number"),
            prompt=generation_prompt,
            storage_path=storage_path,
        )

        result_output = {
            "image_result": image_result,
            "source_image_path": storage_path,
        }

        # Carry shot context forward for downstream agents (VoiceAgent, VideoAgent)
        shot_number = context.get("shot_number")
        if shot_number is not None:
            result_output["shot_number"] = shot_number
        if shot_description:
            result_output["shot_description"] = shot_description
        if generation_prompt:
            result_output["prompt"] = generation_prompt

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
