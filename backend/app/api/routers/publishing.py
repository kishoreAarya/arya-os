"""Publishing API Router for Arya OS V1.

Provides dedicated endpoints for social media publishing and scheduling via Postiz:
- GET /publishing/status: Diagnostic probe for Postiz connectivity and connected channels.
- POST /publishing/publish: Dispatches publishing or scheduling job for stored media asset (supports dry-run).
- GET /publishing/posts/{post_id}: Synchronizes post status with Postiz.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.publishing import PublishingAgent
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import get_secrets_manager
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import get_db
from app.models.enums import PublishStatus
from app.models.media import Video
from app.platforms.registry import get_platform_adapter
from app.services.authorization_service import verify_workflow_access

logger = get_logger("arya.api.publishing")

router = APIRouter(prefix="/publishing", tags=["publishing"])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_storage_path: str = Field(..., description="Local or storage path of the media asset to publish")
    title: str = Field(default="", max_length=255, description="Title of the post")
    caption: str = Field(default="", max_length=5000, description="Post body or caption text")
    platform: str = Field(default="postiz", description="Target platform adapter ('postiz' or 'youtube')")
    social_platform: str = Field(default="youtube", description="Social destination ('youtube', 'tiktok', 'instagram', 'x', etc.)")
    integration_id: str | None = Field(default=None, description="Connected Postiz integration/channel ID")
    scheduled_at: str | None = Field(default=None, description="ISO 8601 UTC timestamp for scheduled release")
    publish_type: str = Field(default="draft", description="'now', 'schedule', or 'draft'")
    dry_run: bool = Field(default=False, description="If true, validates contract and simulates without external post")
    workflow_run_id: uuid.UUID | None = Field(default=None, description="Associated WorkflowRun ID for provenance")
    video_id: str | None = Field(default=None, description="Associated Video DB row ID")


class PublishResponse(BaseModel):
    success: bool
    platform: str
    published_content_id: str | None = None
    publish_status: str
    scheduled_at: str | None = None
    url: str | None = None
    is_dry_run: bool = False
    error: str | None = None


@router.get("/status")
async def get_publishing_status(
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Check Postiz connection and configured credentials."""
    settings = get_settings()
    secrets = get_secrets_manager()
    api_key = secrets.get("postiz_api_key", required=False)

    adapter = get_platform_adapter("postiz", db, secrets)
    auth_result = await adapter.authenticate()

    integrations = []
    if auth_result.success and isinstance(auth_result.credentials, dict):
        integrations = auth_result.credentials.get("integrations", [])

    return {
        "platform": "postiz",
        "base_url": settings.postiz_base_url,
        "configured": bool(api_key),
        "reachable": auth_result.success,
        "status": "connected" if auth_result.success else "disconnected",
        "error": auth_result.error if not auth_result.success else None,
        "connected_channels": len(integrations),
        "channels": [
            {
                "id": ch.get("id"),
                "name": ch.get("name"),
                "identifier": ch.get("identifier"),
            }
            for ch in integrations
            if isinstance(ch, dict)
        ],
    }


@router.post("/publish", response_model=PublishResponse)
async def publish_asset(
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> PublishResponse:
    """Publish or schedule a stored media asset via PublishingAgent."""
    # Verify object-level authorization for workflow_run_id or video_id
    if payload.workflow_run_id is not None:
        await verify_workflow_access(db, principal, payload.workflow_run_id)

    video: Video | None = None
    if payload.video_id:
        try:
            vid_uuid = uuid.UUID(str(payload.video_id))
            stmt = select(Video).where(Video.id == vid_uuid).with_for_update()
            video = (await db.execute(stmt)).scalar_one_or_none()
            if video and video.workflow_run_id:
                await verify_workflow_access(db, principal, video.workflow_run_id)
        except (ValueError, TypeError):
            pass
    elif payload.workflow_run_id:
        stmt = (
            select(Video)
            .where(Video.workflow_run_id == payload.workflow_run_id)
            .order_by(Video.version.desc())
            .with_for_update()
        )
        video = (await db.execute(stmt)).scalars().first()

    # Idempotency check: if already published or scheduled, return existing publish details
    if (
        not payload.dry_run
        and video is not None
        and video.publish_status in (PublishStatus.PUBLISHED, PublishStatus.SCHEDULED)
        and video.youtube_video_id
    ):
        logger.info(
            "publishing_asset_already_published_idempotent_return",
            video_id=str(video.id),
            published_content_id=video.youtube_video_id,
            publish_status=video.publish_status.value,
        )
        pub_url = (
            f"https://www.youtube.com/watch?v={video.youtube_video_id}"
            if payload.platform == "youtube" or payload.social_platform == "youtube"
            else None
        )
        return PublishResponse(
            success=True,
            platform=payload.platform,
            published_content_id=video.youtube_video_id,
            publish_status=video.publish_status.value,
            scheduled_at=payload.scheduled_at,
            url=pub_url,
            is_dry_run=False,
        )

    # Prevent arbitrary file access — ensure path remains strictly confined to storage root
    if not payload.asset_storage_path.startswith(("http://", "https://")):
        from app.storage import get_storage_provider
        from app.storage.local import LocalStorageProvider

        storage = get_storage_provider()
        if isinstance(storage, LocalStorageProvider):
            try:
                storage.resolve_path(payload.asset_storage_path)
            except ValueError as exc:
                logger.warning(
                    "publishing_path_traversal_blocked",
                    path=payload.asset_storage_path,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: path traversal detected in asset path",
                ) from exc

    agent = PublishingAgent(db=db)
    context = {
        "platform": payload.platform,
        "video_id": payload.video_id or str(uuid.uuid4()),
        "video_storage_path": payload.asset_storage_path,
        "title": payload.title,
        "description": payload.caption,
        "caption": payload.caption,
        "social_platform": payload.social_platform,
        "integration_id": payload.integration_id,
        "scheduled_at": payload.scheduled_at,
        "publish_type": payload.publish_type,
        "dry_run": payload.dry_run,
        "workflow_run_id": str(payload.workflow_run_id) if payload.workflow_run_id else None,
    }

    result = await agent.run(context)

    if not result.success:
        return PublishResponse(
            success=False,
            platform=payload.platform,
            publish_status="failed",
            is_dry_run=payload.dry_run,
            error=result.error,
        )

    pub_result = result.output.get("publishing_result")
    content_id = result.output.get("published_video_id")
    pub_url = result.output.get("public_url")
    pub_status = getattr(pub_result, "publish_status", "published") if pub_result else "published"

    return PublishResponse(
        success=True,
        platform=payload.platform,
        published_content_id=content_id,
        publish_status=pub_status,
        scheduled_at=payload.scheduled_at,
        url=pub_url,
        is_dry_run=payload.dry_run,
    )


@router.get("/posts/{post_id}")
async def get_post_status(
    post_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Retrieve and synchronize the status of an existing Postiz post."""
    secrets = get_secrets_manager()
    adapter = get_platform_adapter("postiz", db, secrets)
    status_result = await adapter.check_processing(content_id=post_id)

    return {
        "post_id": post_id,
        "status": status_result.status,
        "progress_percent": status_result.progress_percent,
        "error": status_result.error,
    }
