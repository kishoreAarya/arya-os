"""
ScriptAgent — generates the video script from a topic (+ optional
research data), following the exact pattern TrendAgent already
establishes: DI'd `db`, `ExecutionEngine`, and the shared
`build_text_generation_call` dispatcher instead of a private
`call_provider` closure.
"""

from sqlalchemy.ext.asyncio import AsyncSession  
from dataclasses import dataclass

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine

@dataclass
class ScriptResult:
    content: str
    word_count: int

def _build_script_prompt(
    topic: str,
    research_data: list[dict] | None,
) -> str:
    lines = [
        "You are a scriptwriter for short-form YouTube videos.",
        f"Write a complete video script about: {topic}",
        "",
        "Requirements:",
        "- Hook the viewer in the first 2 sentences",
        "- Clear, spoken-language sentences (this will be read aloud by a voice AI)",
        "- End with a natural call-to-action",
        "- Do not include scene directions, camera angles, or [brackets] — narration text only",
    ]

    if research_data:
        lines.append("")
        lines.append("Use these researched facts/angles where relevant:")
        for item in research_data[:5]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            lines.append(f"- {title}: {summary}")

    return "\n".join(lines)


class ScriptAgent(BaseAgent):
    name = "script_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        topic (str, required)
        research_data (list[dict], optional)
        mode (str, optional)
        """
        topic = context.get("topic")
        if not topic or not str(topic).strip():
            return AgentResult(
                success=False, error="context.topic is required and was empty"
            )

        prompt = _build_script_prompt(
            topic=topic,
            research_data=context.get("research_data"),
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="script_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        content = str(exec_result.output or "")
        word_count = len(content.split())

        script_result = ScriptResult(
            content=content,
            word_count=word_count,
        )

        return AgentResult(
            success=True,
            output={
                "script_result": script_result
            },
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )


        lines.append("")
        lines.append("Return only the narration.")
        lines.append("Do not use markdown.")
        lines.append("Do not use headings.")
        lines.append("Do not use bullet points.")
        lines.append("Do not include camera directions.")