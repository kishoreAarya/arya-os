"""MusicAgent — generates instrumental background music for videos.

Uses dedicated MUSIC_GENERATION models (such as Meta's MusicGen via Replicate)
to generate high-quality instrumental audio tailored to the video's mood, topic,
and duration. Keeps voiceover clearly audible by enforcing instrumental-only
generations suitable for dynamic audio ducking.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine

logger = get_logger("arya.agents.music")


@dataclass
class MusicResult:
    storage_path: str | None
    duration_seconds: float | None
    mood: str | None = None
    prompt: str | None = None
    style: str | None = None


def _build_music_prompt(
    topic: str,
    style: str | None = None,
    mood: str | None = None,
    intensity: str | None = None,
    aspect_ratio: str | None = None,
    music_style: str | None = None,
) -> str:
    """Build a tailored prompt for instrumental background music generation."""
    parts = []

    # 1. Base style & genre
    resolved_style = music_style or style or "cinematic"
    parts.append(f"Instrumental {resolved_style.lower()} background music for a video about {topic}.")

    # 2. Mood & feel
    resolved_mood = mood or "atmospheric and inspiring"
    parts.append(f"Mood: {resolved_mood}.")

    # 3. Intensity / tempo
    if intensity:
        parts.append(f"Energy / Intensity: {intensity}.")

    # 4. Aspect ratio consideration
    if aspect_ratio == "9:16":
        parts.append("Format: Fast-paced, punchy, engaging dynamic rhythm suited for vertical short-form video.")
    else:
        parts.append("Format: Expansive, immersive, widescreen cinematic progression with balanced dynamics.")

    # 5. Instrumental constraints (crucial for clean audio ducking under speech)
    parts.append(
        "Pure instrumental background music. Strictly no vocals, no singing, no spoken words, no speech, no lyrics. "
        "Clean frequency mix, well-balanced dynamics, mastered for ducking under voiceover narration."
    )

    return " ".join(parts)


class MusicAgent(BaseAgent):
    name = "music_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Generate background music matching the video mood and duration.

        Expected context keys:
        - topic (str)
        - style (str, optional) — e.g., 'Cinematic', 'Documentary', 'Lo-Fi'
        - mood (str, optional) — e.g., 'epic', 'calm', 'tense', 'inspirational'
        - music_style (str, optional) — specific genre/style override
        - intensity (str, optional) — e.g. 'high', 'subtle', 'moderate'
        - aspect_ratio (str, optional) — '16:9' or '9:16'
        - target_duration_seconds (float, optional) — defaults to 30
        - workflow_run_id (str, optional)
        """
        topic = context.get("topic") or "educational documentary"
        style = context.get("style")
        mood = context.get("music_mood") or context.get("mood")
        intensity = context.get("intensity")
        music_style = context.get("music_style")
        aspect_ratio = context.get("aspect_ratio", "16:9")
        target_duration = float(
            context.get("target_duration_seconds")
            or context.get("duration")
            or 30
        )

        prompt = _build_music_prompt(
            topic=topic,
            style=style,
            mood=mood,
            intensity=intensity,
            aspect_ratio=aspect_ratio,
            music_style=music_style,
        )

        logger.info(
            "music_generation_started",
            topic=topic,
            mood=mood,
            duration=target_duration,
            aspect_ratio=aspect_ratio,
        )

        provider_override = context.get("provider") or context.get("music_provider")
        model_override = context.get("model") or context.get("music_model")

        exec_result = await self._execution_engine.execute(
            capability=Capability.MUSIC_GENERATION,
            call=build_media_generation_call(
                capability=Capability.MUSIC_GENERATION,
                prompt=prompt,
                duration_seconds=target_duration,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="music_generation",
            validator_name="audio",
        )

        if not exec_result.success:
            logger.warning("music_generation_failed", error=exec_result.error)
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output if isinstance(exec_result.output, dict) else {}
        storage_path = output.get("storage_path")
        actual_duration = output.get("duration_seconds") or target_duration

        music_result = MusicResult(
            storage_path=storage_path,
            duration_seconds=actual_duration,
            mood=mood or "cinematic",
            prompt=prompt,
            style=music_style or style,
        )

        logger.info(
            "music_generation_succeeded",
            storage_path=storage_path,
            duration_seconds=actual_duration,
            provider=exec_result.provider,
        )

        return AgentResult(
            success=True,
            output={
                "music_result": music_result,
                "music_path": storage_path,
                "aspect_ratio": aspect_ratio,
            },
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )