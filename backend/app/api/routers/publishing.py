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
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.publishing import PublishingAgent
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import get_secrets_manager
from app.database.session import get_db
from app.models.enums import PublicationAttemptStatus
from app.platforms.registry import get_platform_adapter
from app.services import publication_attempt_reconciliation as recon

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
    # Additive (publication-attempt core): the durable attempt identity
    # for this publication intent, when one was recorded (never for
    # dry-run validation).
    attempt_id: str | None = None
    attempt_status: str | None = None


@router.get("/status")
async def get_publishing_status(db: AsyncSession = Depends(get_db)):
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
) -> PublishResponse:
    """Publish or schedule a stored media asset via PublishingAgent."""
    # Prevent arbitrary file access - ensure path does not contain illegal traversal
    if ".." in payload.asset_storage_path or "\0" in payload.asset_storage_path:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path traversal detected in asset path",
        )

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
        attempt_id=result.output.get("attempt_id"),
        attempt_status=result.output.get("attempt_status"),
    )


@router.get("/posts/{post_id}")
async def get_post_status(
    post_id: str,
    db: AsyncSession = Depends(get_db),
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


# ---------------------------------------------------------------------------
# Publication-attempt operator reconciliation surface (additive, read +
# evidence + resolve; NO automated reconciliation or polling).
# ---------------------------------------------------------------------------


class PublicationAttemptView(BaseModel):
    """Operator view of one durable publication attempt. Carries no
    credential material by construction (the model never stores any)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    video_id: str
    workflow_run_id: str | None = None
    platform: str
    social_platform: str
    integration_id: str | None = None
    intent_key: str
    attempt_number: int
    status: str
    scheduled_at: str | None = None
    external_content_id: str | None = None
    external_post_id: str | None = None
    public_url: str | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AttemptEvidenceResponse(BaseModel):
    attempt_id: str
    attempt_status: str
    external_content_id: str
    provider_status: str
    progress_percent: float | None = None
    provider_error: str | None = None
    checked_at: str


class ResolveAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_status: PublicationAttemptStatus
    to_status: PublicationAttemptStatus
    external_post_id: str | None = Field(
        default=None, max_length=255, description="Required for UNKNOWN -> SUCCEEDED"
    )
    public_url: str | None = Field(default=None, max_length=1000)
    attestation: str | None = Field(
        default=None,
        max_length=2000,
        description="Operator evidence statement; required for any -> FAILED",
    )
    force: bool = Field(
        default=False,
        description="Required for PENDING/IN_PROGRESS -> FAILED (active-execution floor also applies)",
    )


def _attempt_view(a) -> PublicationAttemptView:
    return PublicationAttemptView(
        id=str(a.id),
        video_id=str(a.video_id),
        workflow_run_id=str(a.workflow_run_id) if a.workflow_run_id else None,
        platform=a.platform,
        social_platform=a.social_platform,
        integration_id=a.integration_id,
        intent_key=a.intent_key,
        attempt_number=a.attempt_number,
        status=a.status.value,
        scheduled_at=a.scheduled_at,
        external_content_id=a.external_content_id,
        external_post_id=a.external_post_id,
        public_url=a.public_url,
        error=a.error,
        created_at=a.created_at.isoformat() if a.created_at else None,
        updated_at=a.updated_at.isoformat() if a.updated_at else None,
    )


@router.get("/attempts", response_model=list[PublicationAttemptView])
async def list_publication_attempts(
    status: PublicationAttemptStatus | None = None,
    video_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List durable publication attempts (newest first) with optional
    status/video filters — the operator observability surface for the
    manual-operations states (UNKNOWN / stale PENDING / IN_PROGRESS)."""
    from sqlalchemy import select

    from app.models.publication import PublicationAttempt

    stmt = (
        select(PublicationAttempt)
        .order_by(PublicationAttempt.created_at.desc(), PublicationAttempt.attempt_number.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(PublicationAttempt.status == status)
    if video_id is not None:
        stmt = stmt.where(PublicationAttempt.video_id == video_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_attempt_view(a) for a in rows]


@router.get("/attempts/{attempt_id}/evidence", response_model=AttemptEvidenceResponse)
async def get_publication_attempt_evidence(
    attempt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Read-only provider evidence for one attempt via the existing
    check_processing() capability. Never mutates the attempt."""
    try:
        return AttemptEvidenceResponse(
            **await recon.fetch_evidence(db, attempt_id)
        )
    except recon.AttemptNotFoundError:
        raise HTTPException(status_code=404, detail="no such publication attempt")
    except recon.MissingAnchorError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/attempts/{attempt_id}/resolve", response_model=PublicationAttemptView)
async def resolve_publication_attempt(
    attempt_id: uuid.UUID,
    payload: ResolveAttemptRequest,
    db: AsyncSession = Depends(get_db),
):
    """Operator resolution of a blocking attempt (UNKNOWN, or a stale
    PENDING/IN_PROGRESS). Conditional CAS update — never resolves
    underneath a live execution or a concurrent resolution."""
    try:
        attempt, _audit = await recon.resolve_attempt(
            db,
            attempt_id,
            from_status=payload.from_status,
            to_status=payload.to_status,
            external_post_id=payload.external_post_id,
            public_url=payload.public_url,
            attestation=payload.attestation,
            force=payload.force,
        )
    except recon.AttemptNotFoundError:
        raise HTTPException(status_code=404, detail="no such publication attempt")
    except recon.MissingAnchorError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except recon.VerificationFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except recon.ActiveExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except recon.ConcurrentResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except recon.IllegalTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _attempt_view(attempt)
