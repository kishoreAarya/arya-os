"""
Agent registry — a plain dict mapping agent name -> CLASS (not an
instance).

CHANGED FROM instance-per-entry TO class-per-entry: most agents now
take `db: AsyncSession` in their constructor (they use ExecutionEngine,
which itself needs a request-scoped session — see execution_engine.py).
Instantiating every agent eagerly at module-import time (the original
approach) is incompatible with that — there's no db session available
at import time, and it would break the whole app's import chain the
moment any agent needed one (which is exactly what happened while
building this file). Storing classes and instantiating at the point of
use (e.g. `AGENT_REGISTRY["image"](db)`) is what every other DI'd
piece in this codebase already does (WorkflowRunRepository(db),
ExecutionEngine(db)) — this brings the registry in line with that,
rather than being the one exception.

ScriptAgent, PromptAgent, and MusicAgent take no constructor args
(`AGENT_REGISTRY["script"]()`), but the registry stores classes
uniformly — the caller instantiates with or without db as needed,
same pattern as every other DI'd class in this codebase.

Beginner note: still intentionally NOT a fancy plugin-loader with
auto-discovery/entry-points — that's over-engineering for a
single-developer project. To add a new agent: write agents/foo.py
implementing BaseAgent, import it below, add one line to the dict.
"""

from app.agents.analytics import AnalyticsAgent
from app.agents.base import BaseAgent
from app.agents.image import ImageAgent
from app.agents.prompt import PromptAgent
from app.agents.publishing import PublishingAgent
from app.agents.script import ScriptAgent
from app.agents.storyboard import StoryboardAgent
from app.agents.thumbnail import ThumbnailAgent
from app.agents.trend import TrendAgent
from app.agents.video import VideoAgent
from app.agents.voice import VoiceAgent
from app.agents.music import MusicAgent
from app.agents.voice_first import VoiceFirstAgent
# Registry keys match orchestrator.py _PIPELINE stage names exactly:
# ["trend", "script", "storyboard", "prompt", "image", "voice",
#  "video", "thumbnail", "publishing", "analytics"]
#
# "learning" is intentionally omitted — no LearningAgent exists yet.
# "music" is intentionally omitted — not in the finalized pipeline.
# "storage" is intentionally omitted — synthetic stage handled by
#   orchestrator._execute_storage_stage(), not an agent.
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "trend": TrendAgent,
    "script": ScriptAgent,
    "storyboard": StoryboardAgent,
    "prompt": PromptAgent,
    "image": ImageAgent,
    "voice": VoiceAgent,
    "video": VideoAgent,
    "thumbnail": ThumbnailAgent,
    "publishing": PublishingAgent,
    "analytics": AnalyticsAgent,
    "music": MusicAgent,
    "voice_first": VoiceFirstAgent,
}

# To add a new agent later:
#   1. Create agents/foo.py with `class FooAgent(BaseAgent): ...`
#   2. Import it above
#   3. Add "foo": FooAgent to the dict
#   4. Instantiate at the point of use: AGENT_REGISTRY["foo"](db) if it
#      needs a db session, or AGENT_REGISTRY["foo"]() if it doesn't.
