"""MusicAgent — generates instrumental background music for videos.

Uses Replicate's MusicGen or similar TTS-capable provider to generate
instrumental audio matching the video's mood and topic.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine


@dataclass
class MusicResult:
    storage_path: str | None
    duration_seconds: float | None
    mood: str | None = None


class MusicAgent(BaseAgent):
    name = "music_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Generate background music matching the video mood.

        Expected context keys:
        - topic (str)
        - style (str) — e.g., 'Cinematic', 'Documentary'
        - mood (str, optional) — e.g., 'epic', 'calm', 'tense'
        - target_duration_seconds (float, optional) — defaults to 30
        - workflow_run_id (str)
        """
        topic = context.get("topic", "")
        style = context.get("style", "")
        mood = context.get("mood", "cinematic")
        target_duration = context.get("target_duration_seconds", 30)

        # Build prompt for instrumental music
        prompt = (
            f"Instrumental background music for a {style.lower()} video about {topic}. "
            f"Mood: {mood}. No vocals, no lyrics. Atmospheric, cinematic, suitable for voiceover narration."
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,  # Replicate handles music via TTS dispatch
            call=build_media_generation_call(
                capability=Capability.TTS,
                prompt=prompt,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="music_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        music_result = MusicResult(
            storage_path=output.get("storage_path"),
            duration_seconds=output.get("duration_seconds"),
            mood=mood,
        )

        return AgentResult(
            success=True,
            output={
                "music_result": music_result,
                "music_path": music_result.storage_path,
            },
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )