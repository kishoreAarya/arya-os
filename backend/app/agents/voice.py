"""
VoiceAgent — generates narration audio from script content.

Uses Capability.TTS via the shared media dispatch
(app/providers/media_dispatch.py) to route to openai or replicate
depending on provider availability and cost ceilings.
"""

from dataclasses import dataclass
from typing import Any

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
    narration_timing: Any | None = None


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
        """
        from app.core.audio_timing import build_narration_timing

        # P0 FIX: Use per-shot voiceover if available, fall back to full script
        voice_text = context.get("voiceover") or context.get("script_content")
        if not voice_text or not str(voice_text).strip():
            return AgentResult(
                success=False,
                error="context.voiceover or context.script_content is required and was empty",
            )

        voice_profile = context.get("voice_profile")
        voice_provider = context.get("voice_provider") or context.get("provider")
        voice_id = context.get("voice_id")
        voice_model = context.get("voice_model") or context.get("model")

        from app.core.config import get_settings
        settings = get_settings()
        default_provider = getattr(settings, "default_voice_provider", "elevenlabs")

        if voice_provider:
            if voice_provider == "elevenlabs":
                priority = ["elevenlabs", "replicate"]
            else:
                priority = [voice_provider]
        else:
            if default_provider == "elevenlabs":
                priority = ["elevenlabs", "replicate"]
            else:
                priority = [default_provider]

        primary_provider = priority[0]

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,
            call=build_media_generation_call(
                capability=Capability.TTS,
                prompt=str(voice_text),
                voice_id=voice_id,
                voice_model=voice_model,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="voice_generation",
            priority=priority,
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        final_provider = exec_result.provider
        if final_provider != primary_provider:
            from app.core.logging import get_logger
            logger = get_logger("arya.agents.voice")
            logger.warning(
                "voice_provider_fallback_occurred",
                primary_provider=primary_provider,
                fallback_provider=final_provider,
                workflow_run_id=str(context.get("workflow_run_id")),
            )

        output = exec_result.output or {}
        duration_seconds = output.get("duration_seconds")
        storage_path = output.get("storage_path")
        alignment = output.get("alignment")

        # Build typed narration timing (real timestamps if alignment available, fallback otherwise)
        narration_timing = build_narration_timing(
            text=str(voice_text),
            audio_path=storage_path,
            duration_seconds=duration_seconds,
            alignment_data=alignment,
            provider=exec_result.provider,
        )

        measured_dur = narration_timing.total_duration_seconds

        voice_result = VoiceResult(
            script_id=context.get("script_id"),
            storage_path=storage_path,
            duration_seconds=measured_dur,
            voice_profile=voice_profile,
            narration_timing=narration_timing.model_dump(),
        )

        result_output = {
            "voice_result": voice_result,
            "target_duration_seconds": measured_dur,
            "voice_duration_seconds": measured_dur,
            "narration_timing": narration_timing.model_dump(),
            "has_real_timestamps": narration_timing.has_real_timestamps,
            "fallback_used": narration_timing.fallback_used,
            "segment_count": len(narration_timing.segments),
        }

        # Carry forward media paths
        if storage_path:
            result_output["voice_path"] = storage_path
            result_output["master_voice_path"] = storage_path

        # Carry script context forward for traceability
        script_id = context.get("script_id")
        if script_id:
            result_output["script_id"] = script_id
        if voice_text:
            result_output["voice_text"] = voice_text

        return AgentResult(
            success=True,
            output=result_output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )