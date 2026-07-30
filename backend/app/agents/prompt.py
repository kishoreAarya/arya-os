"""PromptAgent — generates content for the 'prompt' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""


from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine

from app.agents.base import AgentResult, BaseAgent
from dataclasses import dataclass

@dataclass
class PromptResult:
    positive_prompt: str
    negative_prompt: str

def _build_prompt_prompt(script: str) -> str:
    lines = [
        "Generate a cinematic AI image prompt from the following script.",
        "",
        script,
        "",
        "Return only the prompt.",
        "Do not include markdown.",
        "Do not include explanations.",
    ]
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

        prompt = _build_prompt_prompt(script)

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

        prompt_result = PromptResult(
            positive_prompt=content,
            negative_prompt="",
        )
        return AgentResult(
            success=True,
            output={
                "prompt_result": prompt_result
            },
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
