"""
VoiceAgent — generates narration audio from script content.

Uses Capability.TTS (app/providers/capabilities.py) — this capability
and its two registered providers (openai, replicate) already existed
before this task; nothing was added to the registry for this agent.

No TTS provider adapter exists yet (only app/providers/openrouter.py is
a real adapter today) — per this milestone's "do not implement actual
provider SDK integrations," `_call_provider`'s closure below honestly
raises for both candidate providers rather than faking a working
integration. Calling this agent today will surface a real
AllProvidersFailedError via ExecutionEngine — that's correct,
structural behavior, not a bug: it tells you exactly what's missing
(a TTS adapter file), the same way ScriptAgent looked before
app/providers/openrouter.py was written.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability, ProviderCapability
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


def _build_narration_request(script_content: str, voice_profile: str | None) -> dict:
    """TODO: real TTS request shape depends on which provider adapter
    is eventually written (OpenAI's audio API and Replicate's TTS
    models have different request shapes) — this is a placeholder
    payload describing intent, not a real API call body."""
    return {"text": script_content, "voice_profile": voice_profile or "default"}


class VoiceAgent(BaseAgent):
    name = "voice_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        script_content (str, required)
        script_id (str, optional)
        voice_profile (str, optional) — per the Workflow Manifest
            concept in ARYA_OS_BUILD_INSTRUCTIONS.md section 6
            (not implemented as a real object yet — just a plain
            optional string here until that exists for real)
        """
        script_content = context.get("script_content")
        if not script_content or not str(script_content).strip():
            return AgentResult(
                success=False, error="context.script_content is required and was empty"
            )

        voice_profile = context.get("voice_profile")
        request_payload = _build_narration_request(script_content, voice_profile)

        async def call_provider(provider: ProviderCapability) -> tuple[dict, float]:
            # TODO: real integration required — no TTS provider adapter
            # exists yet (see module docstring). Both "openai" and
            # "replicate" (the two Capability.TTS candidates) raise
            # here until one is written.
            raise RuntimeError(
                f"No TTS adapter implemented yet for provider '{provider.name}' "
                f"(request would have been: {request_payload})"
            )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,
            call=call_provider,
            workflow_run_id=context.get("workflow_run_id"),
            stage="voice_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        # Unreachable until a real TTS adapter exists — kept so the
        # success path's shape is correct and ready, matching every
        # other agent in this file set.
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
