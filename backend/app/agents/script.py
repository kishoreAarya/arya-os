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
    target_duration: int | None = None,
    is_cinematic: bool = False,
) -> str:
    if is_cinematic:
        lines = [
            "You are a master cinematic screenwriter for gripping, atmospheric short films.",
            f"Write a complete cinematic narrative script about: {topic}",
            "",
            "Requirements:",
            "- HOOK: Grab the viewer immediately in the first sentence with the concrete subject, situation, and tension. Avoid slow atmospheric throat-clearing, generic setup, or abstract philosophical rambling.",
            "- Clear, spoken-language sentences with natural cadence, pauses, and visceral imagery (this will be narrated aloud by a voice actor).",
            "- ENDING: Conclude with a chilling, resonant final beat, revelation, or eerie emotional punchline. STRICTLY DO NOT include social media calls-to-action (NO 'subscribe', 'follow', 'like', 'comment', or 'stay tuned'). Keep the viewer completely immersed in the narrative universe.",
            "- Do not include scene directions, camera angles, sound effects, or [brackets] — narration text only.",
        ]
    else:
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

    if target_duration and target_duration > 0:
        # Realistic conversational TTS speech rate (including natural sentence pauses) is ~2.1-2.3 words/sec
        target_words = round(target_duration * 2.2)
        min_words = max(12, round(target_duration * 1.9))
        max_words = round(target_duration * 2.3)
        lines.extend([
            f"- TARGET DURATION: Exactly {target_duration} seconds of spoken narration.",
            f"- WORD COUNT: Strictly between {min_words} and {max_words} words (target approximately {target_words} words).",
            "- Pacing must be tight, engaging, and paced to fill the full duration without rushing or lagging.",
        ])

    lines.extend([
        "",
        "Return only the narration.",
        "Do not use markdown.",
        "Do not use headings.",
        "Do not use bullet points.",
        "Do not include camera directions.",
    ])

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
        duration (int, optional) — target video duration in seconds
        target_duration (int, optional) — alias for duration
        mode (str, optional)
        """
        topic = context.get("topic")
        if not topic or not str(topic).strip():
            return AgentResult(
                success=False, error="context.topic is required and was empty"
            )

        raw_duration = context.get("duration") or context.get("target_duration")
        target_duration = None
        if raw_duration is not None:
            try:
                target_duration = int(raw_duration)
            except (ValueError, TypeError):
                target_duration = None

        is_cinematic = bool(
            context.get("use_cinematic_director")
            or context.get("cinematic_mode")
            or context.get("preset") == "cinematic_story"
        )

        prompt = _build_script_prompt(
            topic=topic,
            research_data=context.get("research_data"),
            target_duration=target_duration,
            is_cinematic=is_cinematic,
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

        output: dict = {
            "script": content,
            "script_content": content,
            "script_result": script_result,
            "word_count": word_count,
        }
        if target_duration:
            output["target_duration"] = target_duration
            output["duration"] = target_duration

        return AgentResult(
            success=True,
            output=output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
