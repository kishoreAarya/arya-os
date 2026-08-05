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
       "• Character consistency — same face, age, build, ethnicity, and distinguishing features across every frame.",
       "• Face consistency — identical facial structure, eye color, expression baseline, and skin texture.",
       "• Costume consistency — same clothing, colors, textures, accessories, and wear patterns.",
       "• Environment consistency — coherent geography, architecture, vegetation, weather, and time of day.",
       "• Camera angle — explicit viewpoint (e.g., low-angle, high-angle, Dutch tilt, bird's-eye, worm's-eye).",
       "• Camera movement — implied motion (e.g., slow dolly in, handheld shake, static tripod, aerial drift).",
       "• Lens — focal length character (e.g., 24mm wide, 85mm portrait, 135mm telephoto compression).",
       "• Lighting — key light direction, fill ratio, bounce sources, practicals, time-of-day quality, volumetrics.",
       "• Mood — emotional tone conveyed through expression, posture, color temperature, and shadow weight.",
       "• Composition — rule of thirds, leading lines, symmetry, negative space, depth layers, framing devices.",
       "• Atmosphere — haze, fog, dust motes, precipitation, wind interaction, temperature impression.",
       "• Color grading — dominant palette, complementary accents, saturation level, film-stock emulation.",
       "• Art style — photorealistic, cinematic, hyper-real, painterly, stylized 3D, analog film, etc.",
       "• Shot continuity — logical progression from previous shots, matching eyelines, consistent screen direction.",
       "• Subject placement — clear foreground, midground, background hierarchy; intentional focal placement.",
       "• Image quality — 8K UHD, highly detailed, sharp focus, HDR, subsurface scattering, ray-traced reflections.",
       "• Realism — anatomically correct proportions, physically accurate materials, believable physics.",
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

       prompt_result = PromptResult(
           positive_prompt=positive_prompt,
           negative_prompt=negative_prompt,
       )

       output = {
           "prompt": positive_prompt,
           "prompt_result": prompt_result,
           "positive_prompt": positive_prompt,
           "negative_prompt": negative_prompt,
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