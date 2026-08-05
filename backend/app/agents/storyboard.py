"""
StoryboardAgent — converts a Script into a shot-by-shot storyboard.

Fills the gap flagged in the earlier engineering audit
(IMPLEMENTATION_GAP.md): no storyboard.py existed at all, and it was
unclear whether prompt.py was meant to cover this role. This is a
genuinely new file for a genuinely missing agent — prompt.py is left
untouched, since its actual scope is still a separate open question
(see prompt.py's own docstring), not something this task resolves.

Same shape as ScriptAgent/TrendAgent: builds a prompt, executes it
through ExecutionEngine (Capability.TEXT_GENERATION — no new
capability needed), and produces a strongly-typed result. The actual
"is this a good shot list" judgment is NOT this agent's job — that's
the "consistency"/"story" validators already registered in
VALIDATOR_REGISTRY, wired in by whatever calls this agent (e.g. a
future backend route, matching Script Agent's own router pattern in
app/api/routers/agents.py — not built here, out of scope for this
agent-layer-only milestone).
"""

import json
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine


@dataclass
class Shot:
   shot_number: int
   description: str
   shot_type: str = "medium"
   duration_seconds: int | None = None
   camera_angle: str | None = None
   camera_movement: str | None = None
   lens: str | None = None
   lighting: str | None = None
   composition: str | None = None
   mood: str | None = None
   continuity_notes: str | None = None


@dataclass
class StoryboardResult:
   """Strongly-typed output of StoryboardAgent.run() — attached under
   AgentResult.output["storyboard_result"]. Mirrors the `shots` JSONB
   shape already expected by the Storyboard model
   (app/models/content.py) and by the 'Arya OS - Storyboard' n8n
   workflow, without this agent touching the database itself (that
   stays a router's job, same as ScriptAgent)."""

   script_id: str | None
   shots: list[Shot] = field(default_factory=list)


def _build_storyboard_prompt(
   script_content: str,
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
       "You are an elite cinematic storyboard artist and film director.",
       "",
       "Your task: analyze the provided script and generate a professional shot-by-shot storyboard.",
       "",
       "OUTPUT RULES:",
       '- Return ONLY valid JSON. No markdown, no code fences, no explanations, no preamble, no postscript.',
       '- The JSON root object must have exactly one key: "shots".',
       '- "shots" is a list of shot objects.',
       '- Each shot object must contain these keys:',
       '    "shot_number" (int, 1-indexed),',
       '    "description" (string, vivid visual description),',
       '    "shot_type" (string: Wide / Medium / Close-Up / Extreme Close-Up / Establishing / Aerial / POV / Over-the-Shoulder),',
       '    "duration_seconds" (int, estimated shot duration),',
       '    "camera_angle" (string: Eye Level / Low Angle / High Angle / Dutch Tilt / Bird\'s Eye / Worm\'s Eye / Overhead),',
       '    "camera_movement" (string: Static / Slow Dolly In / Dolly Out / Pan Left / Pan Right / Tilt Up / Tilt Down / Tracking / Steadicam / Handheld / Crane Up / Crane Down / Zoom In / Zoom Out / Rack Focus),',
       '    "lens" (string: 14mm / 24mm / 35mm / 50mm / 85mm / 135mm / 200mm / Macro / Fisheye),',
       '    "lighting" (string: Key light direction, fill ratio, practicals, volumetrics, time of day),',
       '    "composition" (string: Rule of Thirds / Symmetry / Leading Lines / Negative Space / Depth Layers / Framing Device / Centered / Golden Ratio),',
       '    "mood" (string: emotional tone conveyed through color temperature, shadow weight, and atmosphere),',
       '    "continuity_notes" (string: eyeline match, screen direction, prop placement, costume state, hair continuity).',
       "",
       "CINEMATIC STORYBOARD REQUIREMENTS (incorporate all that apply):",
       "• Character consistency — same face, age, build, ethnicity, and distinguishing features across every shot.",
       "• Costume consistency — same clothing, colors, textures, accessories, and wear patterns.",
       "• Environment consistency — coherent geography, architecture, vegetation, weather, and time of day.",
       "• Shot continuity — logical progression from previous shots, matching eyelines, consistent screen direction.",
       "• Subject placement — clear foreground, midground, background hierarchy; intentional focal placement.",
       "• Image quality — 8K UHD, highly detailed, sharp focus, HDR, cinematic.",
       "",
       "INPUT CONTEXT:",
       f"Script:\n{script_content}",
       "",
   ]

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
       lines.append(f"Target Model: {target_model} — optimize descriptions for this engine.")
       lines.append("")

   lines.extend([
       "OUTPUT FORMAT:",
       '{"shots":[{"shot_number":1,"description":"...","shot_type":"Wide","duration_seconds":5,"camera_angle":"Eye Level","camera_movement":"Static","lens":"24mm","lighting":"Golden hour key from camera-left, soft fill, warm bounce","composition":"Rule of Thirds with subject on left third","mood":"Melancholic and contemplative","continuity_notes":"Subject wears same leather jacket from previous shot, hair slightly wind-tousled"}]}',
   ])

   return "\n".join(lines)


def _parse_shots_from_json(raw_text: str) -> list[Shot] | None:
   """Attempt to parse shots from JSON. Returns None on any failure
   so the caller can fall back to the legacy line parser."""
   try:
       data = json.loads(raw_text.strip())
   except (json.JSONDecodeError, ValueError, TypeError):
       return None

   if not isinstance(data, dict):
       return None

   shots_data = data.get("shots")
   if not isinstance(shots_data, list):
       return None

   shots: list[Shot] = []
   for item in shots_data:
       if not isinstance(item, dict):
           continue
       try:
           shot_number = int(item.get("shot_number", 0))
           if shot_number <= 0:
               continue
       except (ValueError, TypeError):
           continue

       shots.append(
           Shot(
               shot_number=shot_number,
               description=str(item.get("description") or ""),
               shot_type=str(item.get("shot_type") or "medium"),
               duration_seconds=_to_int_or_none(item.get("duration_seconds")),
               camera_angle=_to_str_or_none(item.get("camera_angle")),
               camera_movement=_to_str_or_none(item.get("camera_movement")),
               lens=_to_str_or_none(item.get("lens")),
               lighting=_to_str_or_none(item.get("lighting")),
               composition=_to_str_or_none(item.get("composition")),
               mood=_to_str_or_none(item.get("mood")),
               continuity_notes=_to_str_or_none(item.get("continuity_notes")),
           )
       )

   return shots if shots else None


def _to_int_or_none(value) -> int | None:
   if value is None:
       return None
   try:
       return int(value)
   except (ValueError, TypeError):
       return None


def _to_str_or_none(value) -> str | None:
   if value is None:
       return None
   result = str(value).strip()
   return result if result else None


def _parse_shots_legacy(raw_text: str) -> list[Shot]:
   """Deliberately simple line-based parsing — this is the piece most
   worth iterating on once real output is seen, same spirit as
   ScriptAgent's _build_prompt note. Never raises on malformed input;
   a line that doesn't parse is just skipped, not a hard failure."""
   shots: list[Shot] = []
   for i, line in enumerate(raw_text.strip().splitlines(), start=1):
       line = line.strip()
       if not line:
           continue
       shots.append(Shot(shot_number=i, description=line))
   return shots


def _parse_shots(raw_text: str) -> list[Shot]:
   """Parse shots from JSON first; fall back to legacy line parser
   if JSON parsing fails or yields no valid shots. Preserves backward
   compatibility with plain-text LLM outputs."""
   parsed = _parse_shots_from_json(raw_text)
   if parsed is not None:
       return parsed
   return _parse_shots_legacy(raw_text)


class StoryboardAgent(BaseAgent):
   name = "storyboard_agent"

   def __init__(self, db: AsyncSession):
       self._db = db
       self._execution_engine = ExecutionEngine(db)

   async def run(self, context: dict) -> AgentResult:
       """Expected context keys:
       script_content (str, required)
       script_id (str, optional) — carried through to StoryboardResult
       """
       script_content = context.get("script_content")
       if not script_content or not str(script_content).strip():
           return AgentResult(
               success=False, error="context.script_content is required and was empty"
           )

       prompt = _build_storyboard_prompt(
           script_content=script_content,
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
           stage="storyboard",
       )

       if not exec_result.success:
           return AgentResult(success=False, error=exec_result.error)

       shots = _parse_shots(exec_result.output)
       storyboard_result = StoryboardResult(
           script_id=context.get("script_id"), shots=shots
       )

       output: dict = {
           "shots": shots,
           "storyboard_result": storyboard_result,
       }

       # Carry script_id forward for downstream traceability if present
       script_id = context.get("script_id")
       if script_id:
           output["script_id"] = script_id

       # Expose first shot details for downstream single-shot processing
       if shots:
           first_shot = shots[0]
           output["shot_description"] = first_shot.description
           output["shot_number"] = first_shot.shot_number

       return AgentResult(
           success=True,
           output=output,
           provider_used=exec_result.provider,
           cost_usd=exec_result.cost_usd,
           duration_seconds=exec_result.elapsed_time,
       )