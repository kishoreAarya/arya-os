"""StoryboardAgent — breaks a script into a sequence of cinematic shots.

Uses the project's style guide (if present) to influence shot
composition, lens choices, and continuity notes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine

logger = get_logger("arya.agents.storyboard")


@dataclass
class Shot:
    shot_number: int
    description: str
    shot_type: str = "medium"
    duration_seconds: int | None = None
    camera_angle: str | None = None
    camera_movement: str | None = None
    lens: str | None = None
    framing: str | None = None
    lighting: str | None = None
    mood: str | None = None
    environment: str | None = None
    continuity_notes: str | None = None
    dialogue: str | None = None
    voiceover: str | None = None
    transition: str | None = None
    image_prompt_hint: str | None = None
    negative_prompt_hint: str | None = None


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


def _parse_shots_from_json(raw_text: str) -> list[Shot] | None:
    """Parse shots from a JSON object. Returns None if parsing fails
    or yields no valid shots."""
    raw_text = raw_text.strip()
    if not raw_text:
        return None

    # Some LLMs wrap the JSON in markdown code blocks
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    # Find the first '{' and last '}'
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1:
        return None
    raw_text = raw_text[start : end + 1]

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
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
            shot = Shot(
                shot_number=_to_int_or_none(item.get("shot_number")),
                description=_to_str_or_none(item.get("description")) or "",
                shot_type=_to_str_or_none(item.get("shot_type")) or "medium",
                duration_seconds=_to_int_or_none(item.get("duration_seconds")),
                camera_angle=_to_str_or_none(item.get("camera_angle")),
                camera_movement=_to_str_or_none(item.get("camera_movement")),
                lens=_to_str_or_none(item.get("lens")),
                framing=_to_str_or_none(item.get("framing")),
                lighting=_to_str_or_none(item.get("lighting")),
                mood=_to_str_or_none(item.get("mood")),
                environment=_to_str_or_none(item.get("environment")),
                continuity_notes=_to_str_or_none(item.get("continuity_notes")),
                dialogue=_to_str_or_none(item.get("dialogue")),
                voiceover=_to_str_or_none(item.get("voiceover")),
                transition=_to_str_or_none(item.get("transition")),
                image_prompt_hint=_to_str_or_none(item.get("image_prompt_hint")),
                negative_prompt_hint=_to_str_or_none(item.get("negative_prompt_hint")),
            )
            shots.append(shot)
        except Exception:
            continue

    return shots if shots else None


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

    def _shots_from_voice_segments(self, segments: list[dict]) -> list[Shot]:
        """Create shots directly from voice segments (voice-first workflow)."""
        shots = []
        for i, seg in enumerate(segments, 1):
            duration = int(seg.get("end_time", 4.0) - seg.get("start_time", 0.0))
            shots.append(Shot(
                shot_number=i,
                description=f"Scene for: {seg['text'][:50]}...",
                shot_type="medium",
                duration_seconds=max(duration, 1),
                voiceover=seg.get("text", ""),
                transition="cut" if i > 1 else "fade_in",
                image_prompt_hint=f"cinematic shot, {seg.get('text', '')[:100]}",
            ))
        return shots

    async def run(self, context: dict) -> AgentResult:
        """Break script into cinematic shots.

        Expected context keys:
        - script_content (str, required)
        - style (str, optional)
        - project_id (uuid, optional)
        - continuity_notes (str, optional)
        - voice_segments (list[dict], optional) — voice-first workflow
        """
        script_content = context.get("script_content")
        if not script_content or not str(script_content).strip():
            return AgentResult(
                success=False,
                error="context.script_content is required and was empty",
            )

        # Voice-first: use voice segments for shot timing if available
        voice_segments = context.get("voice_segments")
        if voice_segments:
            shots = self._shots_from_voice_segments(voice_segments)
            if shots:
                return AgentResult(
                    success=True,
                    output={
                        "storyboard": shots,
                        "shots": shots,
                        "shot_count": len(shots),
                    },
                    provider_used="voice_first",
                    cost_usd=0.0,
                    duration_seconds=0.0,
                )

        style = context.get("style", "cinematic")
        continuity_notes = context.get("continuity_notes", "")

        prompt = self._build_prompt(script_content, style, continuity_notes)

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            
            call=build_text_generation_call(
                
                prompt=prompt,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="storyboard",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        raw_output = exec_result.output or {}
        raw_text = raw_output.get("text", "") if isinstance(raw_output, dict) else str(raw_output)

        shots = _parse_shots(raw_text)

        if not shots:
            logger.warning(
                "storyboard_parsing_failed",
                raw_preview=raw_text[:200],
            )
            return AgentResult(
                success=False,
                error="Failed to parse storyboard shots from model output",
            )

        return AgentResult(
            success=True,
            output={
                "storyboard": shots,
                "shots": shots,
                "shot_count": len(shots),
            },
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )

    def _build_prompt(self, script_content: str, style: str, continuity_notes: str) -> str:
        continuity_section = ""
        if continuity_notes:
            continuity_section = (
                f"\n\nCONTINUITY NOTES FROM PREVIOUS SCENES:\n{continuity_notes}\n"
                "Ensure all new shots respect these continuity requirements."
            )

        return (
            f"You are a cinematic storyboard artist. Break the following {style} script into a sequence of detailed shots.\n\n"
            f"SCRIPT:\n{script_content}\n\n"
            "For each shot, provide:\n"
            '    "shot_number" (int),\n'
            '    "description" (string: vivid visual description),\n'
            '    "shot_type" (string: e.g., wide, medium, close-up, extreme close-up, establishing),\n'
            '    "duration_seconds" (int, estimated shot duration),\n'
            '    "camera_angle" (string: e.g., eye-level, low angle, high angle, dutch angle, overhead),\n'
            '    "camera_movement" (string: e.g., static, pan, tilt, dolly, tracking, handheld, crane),\n'
            '    "lens" (string: e.g., 24mm, 50mm, 85mm, 135mm, macro),\n'
            '    "framing" (string: e.g., rule of thirds, center frame, leading lines, symmetry),\n'
            '    "lighting" (string: e.g., natural daylight, golden hour, blue hour, noir, high-key, low-key),\n'
            '    "mood" (string: emotional tone),\n'
            '    "environment" (string: setting details),\n'
            '    "continuity_notes" (string: props, wardrobe, hair, makeup consistency),\n'
            '    "dialogue" (string, optional: exact spoken lines in this shot, or empty string if none),\n'
            '    "voiceover" (string, optional: narration or inner monologue heard over this shot, or empty string if none),\n'
            '    "transition" (string: e.g., cut, fade_in, fade_out, dissolve, wipe, match_cut),\n'
            '    "image_prompt_hint" (string: concise prompt for an image-generation model to create this shot),\n'
            '    "negative_prompt_hint" (string: things to avoid in the generated image)\n\n'
            "Return ONLY a JSON object in this exact format:\n"
            '{"shots":[{"shot_number":1,"description":"...","shot_type":"...","duration_seconds":5,...}]}\n\n'
            "Guidelines:\n"
            "• Each shot should be 3-8 seconds.\n"
            "• Cover the entire script — no gaps, no omissions.\n"
            "• Dialogue and voiceover must be transcribed exactly from the script when present.\n"
            "• Continuity notes should track props, wardrobe, and appearance across shots.\n"
            "• Image prompt hints should be detailed enough for AI image generation.\n"
            "• Negative prompt hints should list common AI image artifacts to avoid.\n"
            "• The total duration should roughly match the intended video length.\n"
            "• Return ONLY the JSON object, no markdown, no extra text."
            f"{continuity_section}"
        )