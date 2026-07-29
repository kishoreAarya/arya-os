"""
TrendAgent — fulfills the "ResearchAgent" role from ARCHITECTURE_v1.0
(ARYA_OS_BUILD_INSTRUCTIONS.md's Step 3, "Research/Trend Agent").

Kept as `TrendAgent`/`trend.py` rather than renamed to `ResearchAgent`/
`research.py` — it's already the registered agent for this pipeline
stage (see agents/registry.py and the n8n "Arya OS - Research"
workflow), and renaming it would touch more of the existing repository
than this task's scope justifies. If a literal `ResearchAgent` class
name is required later, that's a small, deliberate rename — not
something to do silently here.

Responsibilities implemented this milestone (structure, not heavy
business logic — matches ScriptAgent's own level of completeness):
- Trend discovery: TODO, real integration deferred (see
  _discover_trends below) — this is an external HTTP/SDK integration
  (Google Trends, Reddit, etc.), explicitly out of scope per this
  milestone's "do not implement actual provider SDK integrations."
- Read previous LearningFeedback: real query against the actual
  PerformanceLearningFeedback model (app/models/analytics.py) — this
  table already exists, so this is genuinely implemented, not a TODO.
- Generate research output: a real ExecutionEngine call using
  Capability.TEXT_GENERATION (OpenRouter, already configured) to turn
  raw trend signals + past feedback into a research brief. This is the
  same pattern ScriptAgent already uses.
- Produce ResearchResult: a real, defined dataclass (see below),
  attached to AgentResult.output — AgentResult itself stays the return
  type BaseAgent already requires, unchanged.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.models.analytics import PerformanceLearningFeedback
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.services.execution_engine import ExecutionEngine


@dataclass
class ResearchResult:
    """Strongly-typed output of TrendAgent.run() — attached under
    AgentResult.output["research_result"]."""

    topic: str
    trend_signals: list[dict] = field(default_factory=list)
    learning_feedback_applied: list[str] = field(default_factory=list)
    research_brief: str | None = None


async def _discover_trends(topic_hint: str | None) -> list[dict]:
    """TODO: real integration required — Google Trends (pytrends),
    Reddit, YouTube Trends, RSS, or News APIs, per
    ARYA_OS_BUILD_INSTRUCTIONS.md's TrendSource interface note.
    Explicitly out of scope this milestone ("do not implement actual
    provider SDK integrations"). Returns an empty list rather than
    fabricated data — an honest "nothing discovered yet", not a fake
    placeholder trend.
    """
    return []


def _build_research_prompt(
    topic: str, trend_signals: list[dict], feedback: list[PerformanceLearningFeedback]
) -> str:
    lines = [
        "You are a research assistant preparing a brief for a video script writer.",
        f"Topic: {topic}",
    ]
    if trend_signals:
        lines.append("")
        lines.append("Trend signals discovered:")
        for item in trend_signals[:5]:
            lines.append(f"- {item}")
    if feedback:
        lines.append("")
        lines.append("Apply these lessons learned from past published videos:")
        for fb in feedback[:5]:
            lines.append(
                f"- [{fb.category}] {fb.insight} (confidence: {fb.confidence})"
            )
    lines.append("")
    lines.append("Produce a short research brief: 3-5 factual angles worth covering.")
    return "\n".join(lines)


class TrendAgent(BaseAgent):
    name = "trend_agent"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def _read_learning_feedback(self) -> list[PerformanceLearningFeedback]:
        """Real query — is_active feedback only, most recent first.
        superseded (is_active=False) feedback is intentionally
        excluded, per analytics.py's own docstring."""
        result = await self._db.execute(
            select(PerformanceLearningFeedback)
            .where(PerformanceLearningFeedback.is_active.is_(True))
            .order_by(PerformanceLearningFeedback.created_at.desc())
            .limit(10)
        )
        return list(result.scalars().all())

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys: topic (str, required)."""
        topic = context.get("topic")
        if not topic or not str(topic).strip():
            return AgentResult(
                success=False, error="context.topic is required and was empty"
            )

        trend_signals = await _discover_trends(topic)
        feedback = await self._read_learning_feedback()
        prompt = _build_research_prompt(topic, trend_signals, feedback)

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="research",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        research_result = ResearchResult(
            topic=topic,
            trend_signals=trend_signals,
            learning_feedback_applied=[fb.insight for fb in feedback],
            research_brief=exec_result.output,
        )

        return AgentResult(
            success=True,
            output={"research_result": research_result},
            provider_used=exec_result.provider,
            cost_usd=exec_result.cost_usd,
            duration_seconds=exec_result.elapsed_time,
        )
