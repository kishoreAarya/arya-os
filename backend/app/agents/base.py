"""
Base agent interface — every agent (trend, script, prompt, image,
video, thumbnail, music, and any future_agent.py) implements this same
shape, so adding a new agent means: write one class, register it, done.

Beginner note: an Agent only GENERATES. It never validates its own
output and never decides whether to publish — that's the Validators'
job and the Approval checkpoints' job, respectively (kept deliberately
separate per the architecture brief).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentResult:
    success: bool
    output: dict = field(default_factory=dict)  # whatever this agent produced
    provider_used: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float | None = None
    error: str | None = None


class BaseAgent(ABC):
    name: str = "base_agent"

    @abstractmethod
    def run(self, context: dict) -> AgentResult:
        """`context` carries whatever upstream data this agent needs
        (e.g. the Script Agent's context includes the selected topic;
        the Image Agent's context includes the approved Prompt)."""
        raise NotImplementedError
