"""
ImageAgent — generates one image per storyboard shot.

Uses Capability.IMAGE_GENERATION via the shared media dispatch
(app/providers/media_dispatch.py) to route to fal, comfyui, or
replicate depending on provider availability and cost ceilings.
"""

import os
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine

logger = get_logger("arya.agents.image")


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
    candidate_urls: list[str] = field(default_factory=list)
    keyframe_selection: dict | None = None
    model: str | None = None
    provider: str | None = None


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
        prompt (str, optional) — the AI image generation prompt; generated from shot_description if omitted
        shot_description (str, required) — the original shot description
        shot_number (int, optional)
        style_guide (str, optional)
        """
        shot_description = context.get("shot_description")
        if not shot_description or not str(shot_description).strip():
            return AgentResult(
                success=False,
                error="context.shot_description is required and was empty",
            )

        prompt = context.get("prompt")
        # Use the provided prompt directly; fall back to building from shot_description
        generation_prompt = (
            str(prompt).strip()
            if prompt and str(prompt).strip()
            else _build_image_prompt(shot_description, context.get("style_guide"))
        )

        aspect_ratio = context.get("aspect_ratio", "16:9")

        # Configurable keyframe candidates count (default 1 in production, 3 in benchmark)
        raw_cand = (
            context.get("num_keyframe_candidates")
            or context.get("num_outputs")
            or context.get("keyframe_candidates")
            or os.environ.get("VISUAL_KEYFRAME_CANDIDATES", 1)
        )
        try:
            num_candidates = max(1, min(4, int(raw_cand)))
        except (ValueError, TypeError):
            num_candidates = 1

        from app.services.visual_profiles import resolve_visual_profile, sanitize_prompt_v2
        from app.core.config import get_settings
        settings = get_settings()

        profile = resolve_visual_profile(context.get("visual_profile"))
        if profile.prompt_policy in ("v2_lean", "v2_flagship") or context.get("prompt_policy_v2"):
            generation_prompt = sanitize_prompt_v2(generation_prompt)

        is_dry_run = bool(
            context.get("visual_dry_run")
            or getattr(settings, "visual_dry_run", False)
        )

        if is_dry_run:
            shot_num = context.get("shot_number", 1)
            storage_path = f"dry_run://shot_{shot_num}_keyframe.png"
            candidate_urls = [f"dry_run://shot_{shot_num}_candidate_{i+1}.png" for i in range(num_candidates)]
            keyframe_selection_data = None
            if num_candidates > 1:
                keyframe_selection_data = {
                    "selected_index": 0,
                    "selected_candidate": {
                        "candidate_index": 0,
                        "candidate_url": candidate_urls[0],
                        "total_score": round(profile.target_quality_rating, 2),
                        "realism_score": 9.2,
                        "composition_score": 9.4,
                    },
                    "selection_summary": f"Dry-run deterministic selection: candidate 1 chosen under {profile.name} policy",
                }
            image_result = ImageResult(
                shot_number=shot_num,
                prompt=generation_prompt,
                storage_path=storage_path,
                candidate_urls=candidate_urls,
                keyframe_selection=keyframe_selection_data,
            )
            return AgentResult(
                success=True,
                output={
                    "image_result": image_result,
                    "source_image_path": storage_path,
                    "aspect_ratio": aspect_ratio,
                    "candidate_urls": candidate_urls,
                    "keyframe_selection": keyframe_selection_data,
                    "shot_number": shot_num,
                    "prompt": generation_prompt,
                    "is_dry_run": True,
                },
                provider_used=f"dry_run ({profile.image_model})",
                cost_usd=0.0,
                duration_seconds=0.01,
            )

        explicit_model = context.get("image_model") or context.get("model")
        explicit_provider = context.get("image_provider") or context.get("provider")

        target_model = explicit_model if explicit_model else profile.image_model
        priority = [explicit_provider] if explicit_provider else None

        exec_result = await self._execution_engine.execute(
            capability=Capability.IMAGE_GENERATION,
            call=build_media_generation_call(
                capability=Capability.IMAGE_GENERATION,
                prompt=generation_prompt,
                aspect_ratio=aspect_ratio,
                num_outputs=num_candidates,
                image_model=target_model,
                image_provider=explicit_provider,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="image_generation",
            validator_name="image",
            priority=priority,
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        storage_path = output.get("storage_path")
        candidate_urls = output.get("candidate_urls") or ([storage_path] if storage_path else [])
        keyframe_selection_data = None

        actual_provider = getattr(exec_result, "provider", None) or (
            output.get("provider_used") if isinstance(output, dict) else None
        )
        actual_model = (
            getattr(exec_result, "model", None)
            or (output.get("model_used") if isinstance(output, dict) else None)
            or (output.get("model") if isinstance(output, dict) else None)
            or target_model
        )

        if len(candidate_urls) > 1:
            try:
                from app.services.keyframe_selector import select_best_keyframe
                sel_res = select_best_keyframe(
                    candidates=candidate_urls,
                    prompt=generation_prompt,
                    aspect_ratio=aspect_ratio,
                    continuity_context=context.get("continuity_notes"),
                )
                storage_path = sel_res.selected_candidate.candidate_url
                keyframe_selection_data = sel_res.model_dump()
            except Exception as exc:
                logger.warning("keyframe_selection_failed_fallback", error=str(exc))

        image_result = ImageResult(
            shot_number=context.get("shot_number"),
            prompt=generation_prompt,
            storage_path=storage_path,
            candidate_urls=candidate_urls,
            keyframe_selection=keyframe_selection_data,
            model=actual_model,
            provider=actual_provider,
        )

        result_output = {
            "image_result": image_result,
            "source_image_path": storage_path,
            "aspect_ratio": aspect_ratio,
            "candidate_urls": candidate_urls,
            "provider_used": actual_provider,
            "model_used": actual_model,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "requested_provider": explicit_provider,
            "requested_model": explicit_model,
        }
        if keyframe_selection_data:
            result_output["keyframe_selection"] = keyframe_selection_data

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
            provider_used=actual_provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
