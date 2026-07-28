"""
AnalyticsAgent — STRUCTURAL SHELL for "collect", REAL implementation
for "store". Read this before wiring anything to it.

STOPPED, NOT INVENTED — WHY (same root cause as PublishingAgent, see
that file's docstring for the full explanation): "Collect platform
analytics" requires a PlatformAdapter's fetch_analytics() method,
which doesn't exist anywhere in this codebase — only documented as a
future note. Per this task's final instruction, that interface was
not invented here.

What IS real and implemented: the Analytics model
(app/models/analytics.py) already exists with exactly the fields a
real fetch_analytics() call would need to fill (views, likes,
comments, shares, subscribers_gained, click_through_rate,
average_view_duration_seconds, average_view_percentage). Storing a
snapshot — once real data exists to store — is genuinely buildable
against real, existing schema, not a placeholder. What's missing is
purely the "go get the real numbers from YouTube/Instagram/etc."
step, which needs the same PlatformAdapter decision PublishingAgent
is waiting on.

"Produce LearningFeedback input" is left as a TODO for the same
reason: PerformanceLearningFeedback (app/models/analytics.py) already
exists and is real, but turning a raw Analytics snapshot into a
genuine insight ("high Image Quality correlates with higher CTR") is
real analysis logic this task explicitly said not to build
("actual analytics API calls" / heavy business logic where a
placeholder is more appropriate) — deferred, not invented.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.models.analytics import Analytics

logger = get_logger(__name__)


@dataclass
class AnalyticsResult:
    """Strongly-typed output of AnalyticsAgent.run() — attached under
    AgentResult.output["analytics_result"]."""

    video_id: str | None
    snapshot_stored: bool = False
    analytics_id: str | None = None


class AnalyticsAgent(BaseAgent):
    name = "analytics_agent"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def _fetch_platform_analytics(
        self, platform: str, published_content_id: str
    ) -> dict:
        """TODO: real integration required — needs a PlatformAdapter's
        fetch_analytics() (see module docstring). Raises rather than
        returning fabricated numbers."""
        raise NotImplementedError(
            f"Cannot fetch analytics from '{platform}': no PlatformAdapter "
            "abstraction exists in this codebase yet. See this module's "
            "docstring, and app/agents/publishing.py's for the shared root "
            "cause."
        )

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        platform (str, required)
        video_id (str, required)
        published_content_id (str, required) — the platform's own ID
            for the published content (e.g. a YouTube video ID)
        """
        platform = context.get("platform")
        video_id = context.get("video_id")
        published_content_id = context.get("published_content_id")

        missing = [
            name
            for name, value in (
                ("platform", platform),
                ("video_id", video_id),
                ("published_content_id", published_content_id),
            )
            if not value
        ]
        if missing:
            return AgentResult(
                success=False,
                error=f"Missing required context field(s): {', '.join(missing)}",
            )

        try:
            await self._fetch_platform_analytics(platform, published_content_id)
        except NotImplementedError as exc:
            logger.warning(
                "analytics_agent_no_platform_adapter",
                platform=platform,
                video_id=video_id,
                reason=str(exc),
            )
            return AgentResult(success=False, error=str(exc))

        # Unreachable until a real PlatformAdapter exists — kept so the
        # storage half (genuinely implementable against the real
        # Analytics model) is ready the moment fetch works.
        return AgentResult(
            success=True,
            output={
                "analytics_result": AnalyticsResult(
                    video_id=video_id, snapshot_stored=False
                )
            },
        )

    async def _store_snapshot(self, video_id: str, data: dict) -> Analytics:
        """Real, implemented persistence against the actual Analytics
        model — not a stub. Not yet reachable from run() because
        _fetch_platform_analytics always raises first; kept as its own
        method so wiring it in later is a one-line change in run(),
        not new code here.
        """
        snapshot = Analytics(
            video_id=video_id,
            snapshot_at=data["snapshot_at"],
            views=data.get("views", 0),
            likes=data.get("likes", 0),
            comments=data.get("comments", 0),
            shares=data.get("shares", 0),
            subscribers_gained=data.get("subscribers_gained", 0),
            click_through_rate=data.get("click_through_rate"),
            average_view_duration_seconds=data.get("average_view_duration_seconds"),
            average_view_percentage=data.get("average_view_percentage"),
        )
        self._db.add(snapshot)
        await self._db.commit()
        await self._db.refresh(snapshot)
        return snapshot
