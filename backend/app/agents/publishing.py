"""
PublishingAgent — publishes a video to a platform via PlatformAdapter.

Uses the shared adapter architecture (app/platforms/) to abstract
which platform is being published to. PublishingAgent only knows:
- the platform name (from context)
- the video to publish (from context)
- the metadata (title, description, tags from context)

Everything platform-specific (authentication, upload protocol, publish
flow, URL format) lives in the PlatformAdapter implementation.
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.core.logging import get_logger
from app.platforms.registry import UnknownPlatformError, get_platform_adapter
from app.utils.asset_manager import ensure_local_asset

from uuid import UUID

from sqlalchemy import update

from app.models.enums import PublishStatus
from app.models.media import Video

logger = get_logger(__name__)


@dataclass
class PublishingResult:
    """Strongly-typed output of PublishingAgent.run() — attached under
    AgentResult.output["publishing_result"]. Field names mirror
    Video.publish_status / Video.youtube_video_id (app/models/media.py)
    generalized to "platform" rather than hardcoded to YouTube."""

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
        thumbnail_storage_path (str, optional)
        topic (str, optional) — carried forward for AnalyticsAgent
        title (str, optional)
        description (str, optional)
        tags (str, optional) — comma-separated
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

        # Resolve platform adapter via factory
        try:
            adapter = get_platform_adapter(platform, self._db)
        except UnknownPlatformError as exc:
            logger.error(
                "publishing_agent_unknown_platform",
                platform=platform,
                error=str(exc),
            )
            return AgentResult(success=False, error=str(exc))

        # Authenticate with the platform
        auth_result = await adapter.authenticate()
        if not auth_result.success:
            logger.error(
                "publishing_agent_authentication_failed",
                platform=platform,
                error=auth_result.error,
            )
            return AgentResult(
                success=False,
                error=f"Authentication failed for '{platform}': {auth_result.error}",
            )

        aspect_ratio = context.get("aspect_ratio", "16:9")
        title = context.get("title")
        description = context.get("description")
        tags_raw = context.get("tags")
        tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

        if aspect_ratio == "9:16":
            if "#Shorts" not in (title or "") and "#Shorts" not in (description or ""):
                description = f"{description or ''}\n\n#Shorts".strip()
            if "Shorts" not in tags:
                tags.append("Shorts")

        try:
            local_video_path = await ensure_local_asset(video_storage_path)
        except RuntimeError as exc:
            logger.error(
                "publishing_agent_asset_error",
                platform=platform,
                video_id=video_id,
                error=str(exc),
            )
            return AgentResult(
                success=False,
                error=f"Asset resolution failed for '{platform}': {exc}",
            )

        is_dry_run = bool(context.get("dry_run") or context.get("is_dry_run"))
        upload_result = await adapter.upload_content(
            file_path=local_video_path, 
            title=title,
            description=description,
            tags=tags or None,
            credentials=auth_result.credentials,
            is_dry_run=is_dry_run,
        )
        if not upload_result.success:
            logger.error(
                "publishing_agent_upload_failed",
                platform=platform,
                video_id=video_id,
                error=upload_result.error,
            )
            return AgentResult(
                success=False,
                error=f"Upload failed for '{platform}': {upload_result.error}",
            )

        # Upload thumbnail if provided
        thumbnail_path = await ensure_local_asset(
            context.get("thumbnail_storage_path")
        )

        if thumbnail_path and upload_result.content_id:
            thumb_result = await adapter.upload_thumbnail(
                video_content_id=upload_result.content_id,
                thumbnail_path=thumbnail_path,
                credentials=auth_result.credentials,
                is_dry_run=is_dry_run,
            )
            if not thumb_result.success:
                logger.warning(
                    "publishing_agent_thumbnail_upload_failed",
                    platform=platform,
                    video_id=video_id,
                    error=thumb_result.error,
                )
                # Non-fatal: video uploaded successfully, thumbnail failed.

        # Publish or schedule the video
        privacy_status = context.get("privacy_status") or (context.get("metadata") or {}).get("privacy_status") or "private"
        default_pub_type = "schedule" if context.get("scheduled_at") else ("draft" if is_dry_run else "now")
        publish_type = context.get("publish_type") or default_pub_type

        publish_result = await adapter.publish(
            content_id=upload_result.content_id,
            credentials=auth_result.credentials,
            privacy_status=privacy_status,
            title=title,
            description=description,
            caption=description or title,
            tags=tags or None,
            integration_id=context.get("integration_id"),
            platform_type=context.get("social_platform") or context.get("platform_type") or "youtube",
            publish_type=publish_type,
            scheduled_at=context.get("scheduled_at"),
            is_dry_run=is_dry_run,
        )
        if not publish_result.success:
            logger.error(
                "publishing_agent_publish_failed",
                platform=platform,
                video_id=video_id,
                error=publish_result.error,
            )
            return AgentResult(
                success=False,
                error=f"Publish failed for '{platform}': {publish_result.error}",
            )

        # Update the existing Video row after successful publish.
        status_map = {
            "published": PublishStatus.PUBLISHED,
            "scheduled": PublishStatus.SCHEDULED,
            "draft": PublishStatus.DRAFT,
            "failed": PublishStatus.FAILED,
        }
        db_status = status_map.get(publish_result.publish_status, PublishStatus.PUBLISHED)

        if video_id and publish_result.published_content_id:
            try:
                vid_uuid = UUID(str(video_id))
                await self._db.execute(
                    update(Video)
                    .where(Video.id == vid_uuid)
                    .values(
                        youtube_video_id=publish_result.published_content_id,
                        publish_status=db_status,
                    )
                )
                await self._db.commit()

                logger.info(
                    "video_row_updated",
                    video_id=video_id,
                    youtube_video_id=publish_result.published_content_id,
                    publish_status=db_status.value,
                )
            except (ValueError, TypeError):
                logger.debug("video_id_not_uuid_skipping_row_update", video_id=video_id)

        # Persist provenance in SystemLog if workflow_run_id is attached
        workflow_run_id = context.get("workflow_run_id")
        if workflow_run_id:
            try:
                import json
                from app.models.system import SystemLog
                log_entry = SystemLog(
                    workflow_run_id=UUID(str(workflow_run_id)),
                    event_type="PostPublished" if platform != "postiz" else "PostizPublishDispatched",
                    message=json.dumps({
                        "platform": platform,
                        "video_id": video_id,
                        "published_content_id": publish_result.published_content_id,
                        "publish_status": publish_result.publish_status,
                        "scheduled_at": context.get("scheduled_at"),
                        "social_platform": context.get("social_platform") or "youtube",
                        "is_dry_run": is_dry_run,
                    }),
                    level="info",
                )
                self._db.add(log_entry)
                await self._db.commit()
            except Exception as exc:
                logger.warning("publishing_log_persist_failed", error=str(exc))

        # Fetch the public URL
        public_url = None
        if publish_result.published_content_id:
            public_url = await adapter.fetch_url(
                published_content_id=publish_result.published_content_id,
                credentials=auth_result.credentials,
            )

        publishing_result = PublishingResult(
            platform=platform,
            video_id=video_id,
            published_content_id=publish_result.published_content_id,
            publish_status=publish_result.publish_status,
        )

        logger.info(
            "publishing_agent_succeeded",
            platform=platform,
            video_id=video_id,
            published_content_id=publish_result.published_content_id,
            url=public_url,
        )

        result_output = {
            "publishing_result": publishing_result,
            "published_video_id": publish_result.published_content_id,
        }

        # Carry forward context for AnalyticsAgent
        if public_url:
            result_output["public_url"] = public_url
        if platform:
            result_output["platform"] = platform
        topic = context.get("topic")
        if topic:
            result_output["topic"] = topic
        if video_id:
            result_output["video_id"] = video_id
        result_output["aspect_ratio"] = aspect_ratio


        return AgentResult(
            success=True,
            output=result_output,
            provider_used=platform,
            duration_seconds=None,
            error=None,
        )
