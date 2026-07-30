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
        script_content (str, required)
        script_id (str, optional)
        voice_profile (str, optional) — carried through to VoiceResult
            for downstream use; not passed to the TTS provider since
            the shared dispatch does not yet support voice-selection
            parameters (all providers use their default voice).
        """
        script_content = context.get("script_content")
        if not script_content or not str(script_content).strip():
            return AgentResult(
                success=False, error="context.script_content is required and was empty"
            )

        voice_profile = context.get("voice_profile")

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,
            call=build_media_generation_call(
                capability=Capability.TTS,
                prompt=script_content,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="voice_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        voice_result = VoiceResult(
            script_id=context.get("script_id"),
            storage_path=output.get("storage_path"),
            duration_seconds=output.get("duration_seconds"),
            voice_profile=voice_profile,
        )

        return AgentResult(
            success=True,
            output={"voice_result": voice_result},
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
