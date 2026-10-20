"""
ScriptAgent — generates the video script from a topic (+ optional
research data), following the exact pattern TrendAgent already
establishes: DI'd `db`, `ExecutionEngine`, and the shared
`build_text_generation_call` dispatcher instead of a private
`call_provider` closure.
"""

from sqlalchemy.ext.asyncio import AsyncSession  
from dataclasses import dataclass
from typing import Any

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
    research_data: list[Any] | None = None,
    target_duration: int | None = None,
    is_cinematic: bool = False,
    research_brief: str | None = None,
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

    if research_brief and str(research_brief).strip():
        lines.append("")
        lines.append("Research brief:")
        lines.append(str(research_brief).strip())

    researched_bullets: list[str] = []
    if research_data:
        items = research_data if isinstance(research_data, (list, tuple)) else [research_data]
        for raw_item in items[:5]:
            item = (
                raw_item.to_dict()
                if hasattr(raw_item, "to_dict") and callable(raw_item.to_dict)
                else raw_item
            )
            if isinstance(item, dict):
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                title = (
                    item.get("topic")
                    or item.get("title")
                    or metadata.get("title")
                    or ""
                )
                if not isinstance(title, str):
                    title = str(title)
                title = title.strip()

                summary = (
                    item.get("search_volume_or_signal")
                    or item.get("signal")
                    or item.get("summary")
                    or metadata.get("snippet")
                    or metadata.get("content")
                    or ""
                )
                if not isinstance(summary, str):
                    summary = str(summary)
                summary = summary.strip()

                if title and summary:
                    researched_bullets.append(f"- {title}: {summary}")
                elif title:
                    researched_bullets.append(f"- {title}")
                elif summary:
                    researched_bullets.append(f"- {summary}")
            elif isinstance(item, str) and item.strip():
                researched_bullets.append(f"- {item.strip()}")

    if researched_bullets:
        lines.append("")
        lines.append("Use these researched facts/angles where relevant:")
        lines.extend(researched_bullets)

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
        trend_signals (list[dict], optional)
        research_brief (str, optional)
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

        research_data = context.get("research_data")
        if research_data is None:
            research_data = context.get("trend_signals")

        research_brief = context.get("research_brief")

        prompt = _build_script_prompt(
            topic=topic,
            research_data=research_data,
            target_duration=target_duration,
            is_cinematic=is_cinematic,
            research_brief=research_brief,
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="script_generation",
            validator_name="story",
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

        val_res = getattr(exec_result.context, "validation_result", None) if exec_result.context else None
        if val_res is not None:
            output["validation_result"] = val_res
            if getattr(val_res, "score", None) is not None:
                output["quality_score"] = val_res.score

        return AgentResult(
            success=True,
            output=output,
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
