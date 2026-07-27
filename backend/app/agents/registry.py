"""
Agent registry — a plain dict mapping agent name -> instance.

Beginner note: this is intentionally NOT a fancy plugin-loader with
auto-discovery/entry-points — that's over-engineering for a
single-developer project. To add a new agent: write agents/foo.py
implementing BaseAgent, import it below, add one line to the dict.
That's the whole "minimal change" requirement satisfied.
"""
from app.agents.base import BaseAgent
from app.agents.trend import TrendAgent
from app.agents.script import ScriptAgent
from app.agents.prompt import PromptAgent
from app.agents.image import ImageAgent
from app.agents.video import VideoAgent
from app.agents.thumbnail import ThumbnailAgent
from app.agents.music import MusicAgent

AGENT_REGISTRY: dict[str, BaseAgent] = {
    "trend": TrendAgent(),
    "script": ScriptAgent(),
    "prompt": PromptAgent(),
    "image": ImageAgent(),
    "video": VideoAgent(),
    "thumbnail": ThumbnailAgent(),
    "music": MusicAgent(),
}

# To add a new agent later (e.g. a Voice Agent):
#   1. Create agents/voice.py with `class VoiceAgent(BaseAgent): ...`
#   2. Import it above
#   3. Add "voice": VoiceAgent() to the dict
