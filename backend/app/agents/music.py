"""MusicAgent — generates content for the 'music' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""
from app.agents.base import AgentResult, BaseAgent


class MusicAgent(BaseAgent):
    name = "music_agent"

    def run(self, context: dict) -> AgentResult:
        raise NotImplementedError(
            "MusicAgent.run() will call a real provider in Sprint 3+"
        )
