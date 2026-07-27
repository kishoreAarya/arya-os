"""ScriptAgent — generates content for the 'script' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""
from app.agents.base import AgentResult, BaseAgent


class ScriptAgent(BaseAgent):
    name = "script_agent"

    def run(self, context: dict) -> AgentResult:
        raise NotImplementedError(
            "ScriptAgent.run() will call a real provider in Sprint 3+"
        )
