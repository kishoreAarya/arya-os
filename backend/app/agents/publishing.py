"""
PublishingAgent — STRUCTURAL SHELL ONLY. Read this before wiring
anything to it.

STOPPED, NOT INVENTED — WHY:
This task's own responsibility list for PublishingAgent says "Publish
through existing PlatformAdapter abstraction." There is no such
abstraction anywhere in this repository's actual code. It exists ONLY
as a documented future note in ARYA_OS_BUILD_INSTRUCTIONS.md (section
"Future Architecture Notes" / Step 10's "Platform Adapter Interface"
sketch — `authenticate()`, `upload_content()`, `publish()`,
`check_processing()`, `fetch_url()`, `fetch_analytics()`). No Python
class, no ABC, no file implements any of that today.

Per this task's final instruction ("if any requested capability
conflicts with the current repository architecture, stop and explain
instead of inventing new architecture"), a full PlatformAdapter
interface was NOT invented here. Building one would be a real,
consequential architecture decision — which platform(s) it needs to
support on day one, what its exact method signatures are, how
credentials are injected — that belongs in its own reviewed task, not
something to improvise silently inside an "extend agents only"
milestone.

What IS real here: the agent shell itself (BaseAgent, async, DI,
structured logging, a strongly-typed result) and the one thing that's
genuinely implementable without PlatformAdapter — validating that the
request is well-formed before attempting anything. The actual publish
action raises NotImplementedError with this exact explanation, not a
fabricated success.

The Video model (app/models/media.py) already has `youtube_video_id`
and `publish_status` fields ready to receive a real result once this
is built — that part of the architecture already anticipated this
agent; only the Python-side adapter interface is missing.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PublishingResult:
    """Strongly-typed output of PublishingAgent.run() — attached under
    AgentResult.output["publishing_result"] on the (currently
    unreachable) success path. Field names mirror Video.publish_status
    / Video.youtube_video_id (app/models/media.py) generalized to
    "platform" rather than hardcoded to YouTube, per the multi-platform
    architecture direction in ARYA_OS_BUILD_INSTRUCTIONS.md."""

    platform: str
    video_id: str | None
    published_content_id: str | None = None
    publish_status: str = "failed"


class PublishingAgent(BaseAgent):
    name = "publishing_agent"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        platform (str, required) — e.g. "youtube"
        video_id (str, required)
        video_storage_path (str, required)
        title / description / tags (str, optional)

        Validates the request shape (real logic, not a stub), then
        stops before attempting to publish anything — see module
        docstring for exactly why.
        """
        platform = context.get("platform")
        video_id = context.get("video_id")
        video_storage_path = context.get("video_storage_path")

        missing = [
            name
            for name, value in (
                ("platform", platform),
                ("video_id", video_id),
                ("video_storage_path", video_storage_path),
            )
            if not value
        ]
        if missing:
            return AgentResult(
                success=False,
                error=f"Missing required context field(s): {', '.join(missing)}",
            )

        logger.warning(
            "publishing_agent_no_platform_adapter",
            platform=platform,
            video_id=video_id,
            reason=(
                "No PlatformAdapter implementation exists yet for any platform "
                "(see this module's docstring) — publish request validated but "
                "not attempted."
            ),
        )

        return AgentResult(
            success=False,
            error=(
                f"Cannot publish to '{platform}': no PlatformAdapter abstraction "
                "exists in this codebase yet. See app/agents/publishing.py's "
                "module docstring for the full explanation and what would need "
                "to be built first."
            ),
        )
