"""Pluggable agents — see registry.py for how to add a new one."""
from app.agents.base import BaseAgent, AgentResult  # noqa: F401
from app.agents.registry import AGENT_REGISTRY  # noqa: F401
