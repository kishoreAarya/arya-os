"""
AnalyticsAgent — collects platform analytics and stores snapshots.

Uses the shared PlatformAdapter architecture (app/platforms/) to
fetch analytics from any registered platform. The agent itself only
knows the platform name and published_content_id; all platform-
specific API calls live in the adapter.
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.models.analytics import Analytics
from app.platforms.registry import UnknownPlatformError, get_platform_adapter

logger = get_logger(__name__)


@dataclass
class AnalyticsResult:
    """Strongly-typed output of AnalyticsAgent.run()."""

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
        """Fetch analytics via the shared PlatformAdapter architecture."""
        adapter = get_platform_adapter(platform, self._db)

        auth_result = await adapter.authenticate()
        if not auth_result.success:
            raise RuntimeError(
                f"Authentication failed for \'{platform}\': {auth_result.error}"
            )

        data = await adapter.fetch_analytics(
            published_content_id=published_content_id,
            credentials=auth_result.credentials,
        )
        return data

    async def run(self, context: dict) -> AgentResult:
        """Expected context keys:
        published_video_id (str, required) — the platform content ID
        public_url (str, optional) — for reference/link tracking
        platform (str, required) — e.g. "youtube"
        topic (str, optional) — carried forward for LearningAgent
        video_id (str, optional) — internal video reference
        """
        platform = context.get("platform")
        published_video_id = context.get("published_video_id")
        video_id = context.get("video_id")

        # Support both new key (published_video_id) and legacy key (published_content_id)
        published_content_id = published_video_id or context.get("published_content_id")

        missing = [
            name
            for name, value in (
                ("platform", platform),
                ("published_video_id", published_content_id),
            )
            if not value
        ]
        if missing:
            return AgentResult(
                success=False,
                error=f"Missing required context field(s): {', '.join(missing)}",
            )

        try:
            data = await self._fetch_platform_analytics(
                platform, published_content_id
            )
        except UnknownPlatformError as exc:
            logger.error(
                "analytics_agent_unknown_platform",
                platform=platform,
                error=str(exc),
            )
            return AgentResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "analytics_agent_fetch_failed",
                platform=platform,
                video_id=video_id,
                error=str(exc),
            )
            return AgentResult(
                success=False,
                error=f"Failed to fetch analytics from \'{platform}\': {exc}",
            )

        # Store the snapshot
        snapshot = await self._store_snapshot(video_id, data)

        analytics_result = AnalyticsResult(
            video_id=video_id,
            snapshot_stored=True,
            analytics_id=str(snapshot.id),
        )

        result_output = {
            "analytics_result": analytics_result,
            "analytics_metrics": data,
        }

        # Carry forward context for LearningAgent
        if platform:
            result_output["platform"] = platform
        topic = context.get("topic")
        if topic:
            result_output["topic"] = topic
        if video_id:
            result_output["video_id"] = video_id
        if published_content_id:
            result_output["published_video_id"] = published_content_id
        public_url = context.get("public_url")
        if public_url:
            result_output["public_url"] = public_url

        return AgentResult(
            success=True,
            output=result_output,
        )

    async def _store_snapshot(self, video_id: str, data: dict) -> Analytics:
        """Real persistence against the Analytics model."""
        import datetime

        snapshot = Analytics(
            video_id=video_id,
            snapshot_at=datetime.datetime.utcnow(),
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
