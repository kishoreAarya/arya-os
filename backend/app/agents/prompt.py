"""PromptAgent — generates content for the 'prompt' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine

from app.agents.base import AgentResult, BaseAgent
from dataclasses import dataclass

DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, watermark, logo, text, "
    "bad anatomy, extra fingers, extra limbs, "
    "duplicate subject, cropped, deformed face, "
    "bad hands, oversaturated, noisy"
)

@dataclass
class PromptResult:
   positive_prompt: str
   negative_prompt: str


def _build_prompt_prompt(
   script: str,
   shot_description: str | None = None,
   shot_number: int | None = None,
   character_bible: str | None = None,
   environment_bible: str | None = None,
   style_bible: str | None = None,
   camera_style: str | None = None,
   lighting_style: str | None = None,
   continuity_notes: str | None = None,
   aspect_ratio: str | None = None,
   target_model: str | None = None,
) -> str:
   lines = [
       "You are an elite cinematic AI prompt engineer specializing in production-quality image generation.",
       "",
       "Your task: analyze the provided script and shot context, then generate a single JSON object containing a cinematic positive prompt and a comprehensive negative prompt.",
       "",
       "OUTPUT RULES:",
       '- Return ONLY valid JSON. No markdown, no code fences, no explanations, no preamble, no postscript.',
       '- The JSON object must have exactly two string keys: "positive_prompt" and "negative_prompt".',
       '- Both values must be strings.',
       '- Do not include line breaks inside the JSON string values.',
       "",
       "CINEMATIC POSITIVE PROMPT REQUIREMENTS (incorporate all that apply):",
       "• Specific Shot Framing — explicit scale: extreme close-up, choker, medium close-up, medium shot, wide establishing.",
       "• Character Anchors — persistent facial structure, skin pores, gaze direction, precise wardrobe materials, and wear patterns.",
       "• Environment Anchors — tangible architectural materials, peeling plaster, damp floorboards, weather, and specific era details.",
       "• Lens & Optics — specific focal lengths and optical physics (e.g., 35mm anamorphic prime, f/1.8 shallow depth of field, subtle peripheral falloff).",
       "• Motivated Lighting — explicit source, angle, and temperature (e.g., single low-hanging tungsten filament bulb casting hard downward shadows, cold moonlight spill on floor).",
       "• Three-Plane Depth Staging — intentional foreground (e.g., blurred doorway frame), midground (primary subject), and background (textured room depth).",
       "• Tactile Materials & Texture — coarse woven fabric, flaking rust, beads of perspiration, organic 35mm film grain, physical weight.",
       "• Emotion & Micro-Behavior — caught mid-breath, tension in shoulders, wide pupillary response, subtle hesitation.",
       "• Color Palette & Shadow Roll-off — desaturated shadows, cool greenish-black undertones, warm amber practical accents.",
       "• STRICT BUZZWORD BAN — DO NOT use generic filler words like 'cinematic', 'photorealistic', 'hyper-realistic', 'masterpiece', or '8K UHD'. Describe physical optics, tangible materials, and motivated light instead.",
       "",
       "NEGATIVE PROMPT REQUIREMENTS:",
       "Include a thorough negative_prompt that excludes: deformed anatomy, extra limbs, missing fingers,",
       "bad proportions, blurry, out of focus, watermark, text, logo, signature, oversaturated,",
       "chromatic aberration, noise, grain, duplicate subjects, cropped frame, mutated features,",
       "disfigured, poorly drawn face, cross-eyed, floating objects, inconsistent shadows.",
       "",
       "INPUT CONTEXT:",
       f"Script: {script}",
       "",
   ]

   if shot_description:
       lines.append(f"Shot {shot_number or 1}: {shot_description}")
       lines.append("")

   if character_bible:
       lines.append(f"Character Bible: {character_bible}")
       lines.append("")

   if environment_bible:
       lines.append(f"Environment Bible: {environment_bible}")
       lines.append("")

   if style_bible:
       lines.append(f"Style Bible: {style_bible}")
       lines.append("")

   if camera_style:
       lines.append(f"Camera Style: {camera_style}")
       lines.append("")

   if lighting_style:
       lines.append(f"Lighting Style: {lighting_style}")
       lines.append("")

   if continuity_notes:
       lines.append(f"Continuity Notes: {continuity_notes}")
       lines.append("")

   if aspect_ratio:
       lines.append(f"Target Aspect Ratio: {aspect_ratio}")
       if aspect_ratio == "9:16":
           lines.append("Framing & Composition instructions: Target is vertical 9:16 Shorts format. Emphasize vertical composition, centered subject, safe margins for mobile UI overlays, vertical headroom, and portrait perspective.")
       elif aspect_ratio == "16:9":
           lines.append("Framing & Composition instructions: Target is horizontal 16:9 widescreen format. Emphasize cinematic horizontal breadth, panoramic landscape, and wide aspect composition.")
       lines.append("")

   if target_model:
       lines.append(f"Target Model: {target_model} — optimize prompt syntax for this engine.")
       lines.append("")

   lines.extend([
       "OUTPUT FORMAT:",
       '{"positive_prompt":"...","negative_prompt":"..."}',
   ])

   return "\n".join(lines)


class PromptAgent(BaseAgent):
   name = "prompt_agent"

   def __init__(self, db: AsyncSession):
       self._db = db
       self._execution_engine = ExecutionEngine(db)

   async def run(self, context: dict) -> AgentResult:
       script = context.get("script")

       if not script or not str(script).strip():
           return AgentResult(
               success=False,
               error="context.script is required and was empty",
           )

       shot_description = context.get("shot_description")
       shot_number = context.get("shot_number")

       prompt = _build_prompt_prompt(
           script=script,
           shot_description=shot_description,
           shot_number=shot_number,
           character_bible=context.get("character_bible"),
           environment_bible=context.get("environment_bible"),
           style_bible=context.get("style_bible"),
           camera_style=context.get("camera_style"),
           lighting_style=context.get("lighting_style"),
           continuity_notes=context.get("continuity_notes"),
           aspect_ratio=context.get("aspect_ratio"),
           target_model=context.get("target_model"),
       )

       exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="prompt_generation",
            validator_name="prompt",
        )

       if not exec_result.success:
           return AgentResult(
               success=False,
               error=exec_result.error,
           )

       content = str(exec_result.output or "")

       # Safe JSON parsing with fallback to raw text for backward compatibility.
       positive_prompt = content
       negative_prompt = DEFAULT_NEGATIVE_PROMPT

       try:
           parsed = json.loads(content.strip())
           if isinstance(parsed, dict):
               positive_prompt = str(parsed.get("positive_prompt") or content)
               negative_prompt = str(
                    parsed.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT
                )
       except (json.JSONDecodeError, ValueError, TypeError):
           pass

       from app.services.visual_profiles import resolve_visual_profile, sanitize_prompt_v2
       from app.core.shot_classifier import get_enforced_negative_prompt

       prof = resolve_visual_profile(context.get("visual_profile"))
       if prof.prompt_policy in ("v2_lean", "v2_flagship") or context.get("prompt_policy_v2"):
           positive_prompt = sanitize_prompt_v2(positive_prompt)
           negative_prompt = get_enforced_negative_prompt(negative_prompt)

       prompt_result = PromptResult(
           positive_prompt=positive_prompt,
           negative_prompt=negative_prompt,
       )

       output = {
           "prompt": positive_prompt,
           "prompt_result": prompt_result,
           "positive_prompt": positive_prompt,
           "negative_prompt": negative_prompt,
           "aspect_ratio": context.get("aspect_ratio", "16:9"),
       }

       # Carry shot context forward for ImageAgent traceability
       if shot_description:
           output["shot_description"] = shot_description
       if shot_number is not None:
           output["shot_number"] = shot_number

       return AgentResult(
           success=True,
           output=output,
           provider_used=exec_result.provider,
           cost_usd=exec_result.cost_usd,
           duration_seconds=exec_result.elapsed_time,
       )