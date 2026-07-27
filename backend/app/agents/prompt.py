"""PromptAgent — generates content for the 'prompt' pipeline stage.
Real provider calls (via app/providers/) get wired in during Sprint 3+;
this stub defines the contract so the pipeline shape is complete now."""
from app.agents.base import AgentResult, BaseAgent


class PromptAgent(BaseAgent):
    name = "prompt_agent"

    def run(self, context: dict) -> AgentResult:
        raise NotImplementedError(
            "PromptAgent.run() will call a real provider in Sprint 3+"
        )
