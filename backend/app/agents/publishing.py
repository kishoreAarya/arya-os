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

        # Publication-attempt core (operator-authorized slice): the
        # durable, DB-idempotent attempt record for THIS publication
        # intent. Written BEFORE any external call. Dry-run validates
        # only and records no attempt. Duplicate intents resolve to the
        # existing attempt — never a second external publication.
        is_dry_run = bool(context.get("dry_run") or context.get("is_dry_run"))
        social_platform = context.get("social_platform") or context.get("platform_type") or "youtube"
        attempt = None
        if not is_dry_run:
            from app.models.enums import PublicationAttemptStatus
            from app.services.publication_attempts import admit_attempt

            try:
                attempt_video_uuid = UUID(str(video_id))
            except (ValueError, TypeError, AttributeError):
                # Non-UUID video ids are tolerated by the existing path
                # (the Video writeback skips them the same way); they get
                # no attempt record rather than failing the publication.
                attempt_video_uuid = None
            if attempt_video_uuid is not None:
                attempt, created = await admit_attempt(
                    self._db,
                    video_id=attempt_video_uuid,
                    platform=platform,
                    social_platform=social_platform,
                    integration_id=context.get("integration_id"),
                    workflow_run_id=(
                        UUID(str(context["workflow_run_id"]))
                        if context.get("workflow_run_id")
                        else None
                    ),
                    scheduled_at=context.get("scheduled_at"),
                )
                if not created:
                    if attempt.status == PublicationAttemptStatus.SUCCEEDED:
                        # Idempotent duplicate: the identical intent already
                        # published — return the existing outcome, no second
                        # external publication.
                        return AgentResult(
                            success=True,
                            output={
                                "publishing_result": None,
                                "published_video_id": attempt.external_post_id,
                                "public_url": attempt.public_url,
                                "attempt_id": str(attempt.id),
                                "attempt_status": attempt.status.value,
                                "attempt_number": attempt.attempt_number,
                                "duplicate": True,
                            },
                            error=None,
                        )
                    reason = {
                        PublicationAttemptStatus.PENDING: "a submission of this publication "
                        "intent is already pending",
                        PublicationAttemptStatus.IN_PROGRESS: "a publication of this intent "
                        "is currently in progress",
                        PublicationAttemptStatus.UNKNOWN: "a previous publication of this "
                        "intent has an AMBIGUOUS outcome (manual reconciliation required; "
                        "automatic retry is blocked)",
                    }[attempt.status]
                    return AgentResult(
                        success=False,
                        error=f"Publication attempt {attempt.attempt_number} for this intent "
                        f"is {attempt.status.value}: {reason}",
                    )

        # Authenticate with the platform
        from app.services.publication_attempts import mark_failed as _attempt_failed

        try:
            auth_result = await adapter.authenticate()
        except Exception as exc:  # noqa: BLE001 — auth is a read-only call: no submission possible → FAILED
            logger.error("publishing_agent_authentication_error", platform=platform, error=str(exc))
            if attempt is not None:
                await _attempt_failed(self._db, attempt, f"authentication error: {type(exc).__name__}")
            return AgentResult(success=False, error=f"Authentication failed for '{platform}': {exc}")
        if not auth_result.success:
            logger.error(
                "publishing_agent_authentication_failed",
                platform=platform,
                error=auth_result.error,
            )
            if attempt is not None:
                await _attempt_failed(
                    self._db, attempt, f"authentication failed: {auth_result.error}"
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
            if attempt is not None:
                await _attempt_failed(self._db, attempt, f"asset resolution failed: {exc}")
            return AgentResult(
                success=False,
                error=f"Asset resolution failed for '{platform}': {exc}",
            )

        from app.services.publication_attempts import (
            mark_external_content,
            mark_failed,
            mark_in_progress,
            mark_succeeded,
            mark_unknown,
        )

        try:
            upload_result = await adapter.upload_content(
                file_path=local_video_path,
                title=title,
                description=description,
                tags=tags or None,
                credentials=auth_result.credentials,
                is_dry_run=is_dry_run,
            )
        except Exception as exc:  # noqa: BLE001 — external ambiguity: provider may hold the media → UNKNOWN
            # External submission ambiguity (the provider may hold the
            # media): UNKNOWN — never silently FAILED.
            logger.error("publishing_agent_upload_error", platform=platform, error=str(exc))
            recorded_unknown = True
            if attempt is not None:
                recorded_unknown = await mark_unknown(
                    self._db, attempt, f"upload exception: {type(exc).__name__}"
                )
            suffix = (
                " (attempt recorded UNKNOWN)"
                if recorded_unknown
                else " (attempt already resolved — transition refused)"
            )
            return AgentResult(
                success=False,
                error=f"Upload raised for '{platform}': {exc}{suffix}",
            )
        if not upload_result.success:
            logger.error(
                "publishing_agent_upload_failed",
                platform=platform,
                video_id=video_id,
                error=upload_result.error,
            )
            if attempt is not None:
                await mark_failed(self._db, attempt, f"upload rejected: {upload_result.error}")
            return AgentResult(
                success=False,
                error=f"Upload failed for '{platform}': {upload_result.error}",
            )
        if attempt is not None and upload_result.content_id:
            # Persist the provider content id BEFORE the publish call —
            # the crash-recovery anchor (ratified §9).
            await mark_external_content(self._db, attempt, upload_result.content_id)

        # Upload thumbnail if provided
        thumbnail_path = await ensure_local_asset(
            context.get("thumbnail_storage_path")
        )

        if thumbnail_path and upload_result.content_id:
            try:
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
            except Exception as exc:  # noqa: BLE001 — non-fatal thumbnail ambiguity; publish below decides
                # Non-fatal (parity with thumbnail rejection): the
                # publication itself has not been submitted; the publish
                # call below determines the attempt outcome.
                logger.warning(
                    "publishing_agent_thumbnail_upload_error",
                    platform=platform,
                    video_id=video_id,
                    error=str(exc),
                )

        # Publish or schedule the video. IN_PROGRESS is persisted
        # immediately BEFORE this — the first irreversible external call.
        # The PENDING -> IN_PROGRESS CAS is the publication PERMIT (H1):
        # if it refuses, the attempt was resolved underneath this
        # execution and the irreversible external call must NOT happen.
        privacy_status = context.get("privacy_status") or (context.get("metadata") or {}).get("privacy_status") or "private"
        default_pub_type = "schedule" if context.get("scheduled_at") else ("draft" if is_dry_run else "now")
        publish_type = context.get("publish_type") or default_pub_type

        if attempt is not None:
            permit_granted = await mark_in_progress(self._db, attempt)
            if not permit_granted:
                logger.error(
                    "publishing_agent_permit_denied",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                    attempt_status=attempt.status.value,
                )
                return AgentResult(
                    success=False,
                    error=f"Publication permit denied for attempt {attempt.attempt_number} of "
                    f"this intent: the attempt is now {attempt.status.value} (resolved by an "
                    "operator or another execution); no external publish was made",
                )
        try:
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
        except Exception as exc:  # noqa: BLE001 — ambiguity after possible submission → UNKNOWN
            # Ambiguity after external submission may have occurred:
            # durable UNKNOWN — never auto-retried, never FAILED without
            # evidence (ratified §2/§11). If the CAS refuses, an operator
            # resolution already moved the attempt: it stands (H1).
            logger.error("publishing_agent_publish_error", platform=platform, error=str(exc))
            recorded_unknown = True
            if attempt is not None:
                recorded_unknown = await mark_unknown(
                    self._db, attempt, f"publish exception: {type(exc).__name__}"
                )
            suffix = (
                " (attempt recorded UNKNOWN; manual reconciliation required)"
                if recorded_unknown
                else " (attempt already resolved — transition refused)"
            )
            return AgentResult(
                success=False,
                error=f"Publish raised for '{platform}': {exc}{suffix}",
            )
        if not publish_result.success:
            logger.error(
                "publishing_agent_publish_failed",
                platform=platform,
                video_id=video_id,
                error=publish_result.error,
            )
            if attempt is not None:
                await mark_failed(self._db, attempt, f"publish rejected: {publish_result.error}")
            return AgentResult(
                success=False,
                error=f"Publish failed for '{platform}': {publish_result.error}",
            )
        if attempt is not None:
            # External identifiers persisted immediately at confirmed
            # success — independent of the Video writeback below. The
            # CAS refuses if an operator resolution moved the attempt
            # while the publish call was in flight: that resolution
            # stands (H1) — never resurrect it; surface for manual review.
            succeeded_recorded = await mark_succeeded(
                self._db,
                attempt,
                external_post_id=publish_result.published_content_id,
                public_url=publish_result.url,
            )
            if not succeeded_recorded:
                logger.error(
                    "publishing_agent_success_bookkeeping_refused",
                    platform=platform,
                    video_id=video_id,
                    attempt_id=str(attempt.id),
                    attempt_status=attempt.status.value,
                    external_post_id=publish_result.published_content_id,
                )
                return AgentResult(
                    success=False,
                    error=f"Publish succeeded externally for '{platform}' "
                    f"(content id {publish_result.published_content_id}), but publication "
                    f"attempt {attempt.attempt_number} is now {attempt.status.value} "
                    "(resolved underneath this execution); the operator resolution stands — "
                    "manual review required",
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
        if attempt is not None:
            # Additive: the durable attempt identity for this publication.
            result_output["attempt_id"] = str(attempt.id)
            result_output["attempt_status"] = attempt.status.value
            result_output["attempt_number"] = attempt.attempt_number
            if public_url and attempt.public_url is None:
                from app.services.publication_attempts import _transition

                # Status-preserving CAS bookkeeping (best-effort): only
                # while the attempt still holds its recorded status.
                await _transition(
                    self._db, attempt, None, (attempt.status,), public_url=public_url
                )

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
