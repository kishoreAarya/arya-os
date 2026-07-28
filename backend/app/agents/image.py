"""
ImageAgent — generates one image per storyboard shot.

Uses Capability.IMAGE_GENERATION (app/providers/capabilities.py — fal
and comfyui already registered; nothing added here). No image
provider adapter exists yet (only app/providers/openrouter.py is a
real adapter today) — per this milestone's "do not implement actual
image generation logic," `_call_provider`'s closure honestly raises
for every candidate provider rather than faking a working call.
Calling this agent today surfaces a real AllProvidersFailedError via
ExecutionEngine, same as VoiceAgent — that's correct, not a bug.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability, ProviderCapability
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
    """TODO: real prompt-engineering (negative prompts, style/LoRA
    selection, aspect ratio per the Workflow Manifest concept in
    ARYA_OS_BUILD_INSTRUCTIONS.md section 6) is deliberately not built
    here — this is the simplest prompt that could work, matching how
    ScriptAgent's own _build_prompt started."""
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
        shot_description (str, required)
        shot_number (int, optional)
        style_guide (str, optional)
        """
        shot_description = context.get("shot_description")
        if not shot_description or not str(shot_description).strip():
            return AgentResult(
                success=False,
                error="context.shot_description is required and was empty",
            )

        prompt = _build_image_prompt(shot_description, context.get("style_guide"))

        async def call_provider(provider: ProviderCapability) -> tuple[dict, float]:
            # TODO: real integration required — no image provider
            # adapter exists yet (see module docstring). Both "fal"
            # and "comfyui" (the Capability.IMAGE_GENERATION
            # candidates) raise here until one is written.
            raise RuntimeError(
                f"No image-generation adapter implemented yet for provider "
                f"'{provider.name}' (prompt would have been: {prompt!r})"
            )

        exec_result = await self._execution_engine.execute(
            capability=Capability.IMAGE_GENERATION,
            call=call_provider,
            workflow_run_id=context.get("workflow_run_id"),
            stage="image_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        image_result = ImageResult(
            shot_number=context.get("shot_number"),
            prompt=prompt,
            storage_path=output.get("storage_path"),
        )

        return AgentResult(
            success=True,
            output={"image_result": image_result},
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
