"""
VoiceAgent — generates narration audio from script content.

Uses Capability.TTS via the shared media dispatch
(app/providers/media_dispatch.py) to route to openai or replicate
depending on provider availability and cost ceilings.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine

@dataclass
class VoiceResult:
    """Strongly-typed output of VoiceAgent.run() — attached under
    AgentResult.output["voice_result"]. storage_path/duration_seconds
    mirror the shape ARYA_OS_BUILD_INSTRUCTIONS.md's Step 5 (Voice
    Agent) describes: an audio file plus its duration, so the Video
    Agent can target that duration instead of guessing."""

    script_id: str | None
    storage_path: str | None
    duration_seconds: float | None
    voice_profile: str | None = None


class VoiceAgent(BaseAgent):
    name = "voice_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        voiceover (str, preferred) — per-shot voiceover line from storyboard
        script_content (str, fallback) — full script if voiceover not available
        script_id (str, optional)
        voice_profile (str, optional) — carried through to VoiceResult
        for downstream use; not passed to the TTS provider since
        the shared dispatch does not yet support voice-selection
        parameters (all providers use their default voice).
        """
        # P0 FIX: Use per-shot voiceover if available, fall back to full script
        voice_text = context.get("voiceover") or context.get("script_content")
        if not voice_text or not str(voice_text).strip():
            return AgentResult(
                success=False,
                error="context.voiceover or context.script_content is required and was empty",
            )

        voice_profile = context.get("voice_profile")

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,
            call=build_media_generation_call(
                capability=Capability.TTS,
                prompt=voice_text,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="voice_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        duration_seconds = output.get("duration_seconds")
        storage_path = output.get("storage_path")

        voice_result = VoiceResult(
            script_id=context.get("script_id"),
            storage_path=storage_path,
            duration_seconds=duration_seconds,
            voice_profile=voice_profile,
        )

        result_output = {
            "voice_result": voice_result,
            "target_duration_seconds": duration_seconds,
        }

        # Carry forward media path for VideoAgent
        if storage_path:
            result_output["voice_path"] = storage_path

        # Carry script context forward for VideoAgent traceability
        script_id = context.get("script_id")
        if script_id:
            result_output["script_id"] = script_id
        # Carry the actual text that was narrated (voiceover or script)
        if voice_text:
            result_output["voice_text"] = voice_text

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )