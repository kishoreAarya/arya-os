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

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.secrets import SecretNotConfigured, get_secrets_manager
from app.providers import openrouter
from app.providers.capabilities import Capability, ProviderCapability
from app.services.execution_engine import ExecutionEngine


@dataclass
class Shot:
    shot_number: int
    description: str
    shot_type: str = "medium"


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


def _build_storyboard_prompt(script_content: str) -> str:
    return (
        "You are a storyboard artist breaking a video script into shots.\n"
        f"Script:\n{script_content}\n\n"
        "Break this into a numbered shot list. For each shot, give a short "
        "visual description and a shot type (close-up, medium, wide, etc.). "
        "One shot per line, format: 'N. [shot_type] description'."
    )


def _parse_shots(raw_text: str) -> list[Shot]:
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

        prompt = _build_storyboard_prompt(script_content)

        async def call_provider(provider: ProviderCapability) -> tuple[str, float]:
            if provider.name == "openrouter":
                try:
                    api_key = get_secrets_manager().get("openrouter_api_key")
                except SecretNotConfigured as exc:
                    raise RuntimeError(str(exc)) from exc
                model = (
                    provider.supported_models[0]
                    if provider.supported_models
                    else "deepseek/deepseek-chat"
                )
                return await openrouter.generate_text(
                    prompt=prompt, api_key=api_key, model=model
                )
            raise RuntimeError(
                f"No adapter implemented yet for provider '{provider.name}'"
            )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=call_provider,
            workflow_run_id=context.get("workflow_run_id"),
            stage="storyboard",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        shots = _parse_shots(exec_result.output)
        storyboard_result = StoryboardResult(
            script_id=context.get("script_id"), shots=shots
        )

        return AgentResult(
            success=True,
            output={"storyboard_result": storyboard_result},
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
