"""TrendAgent — generates content for the 'trend' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""
from app.agents.base import AgentResult, BaseAgent


class TrendAgent(BaseAgent):
    name = "trend_agent"

    def run(self, context: dict) -> AgentResult:
        raise NotImplementedError(
            "TrendAgent.run() will call a real provider in Sprint 3+"
        )
