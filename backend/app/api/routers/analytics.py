"""Analytics API router for Arya OS V1.

Exposes authenticated endpoints to ingest, normalize, and retrieve publishing analytics:
- POST /analytics/ingest: Ingest a raw performance snapshot (from Postiz, connectors, or fixtures).
- GET /analytics/snapshots: Retrieve historical analytics snapshots.
- GET /analytics/latest: Get the most recent metrics snapshot for a video, workflow run, or external post.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.session import get_db
from app.services.analytics_service import AnalyticsIngestionService, MetricValidationError

logger = get_logger("arya.api.analytics")

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(..., description="Target platform ('youtube', 'tiktok', 'instagram', 'x', etc.)")
    metrics: dict[str, Any] = Field(..., description="Dictionary of platform metrics (views, likes, etc.)")
    video_id: str | None = Field(default=None, description="Optional internal Video ID")
    workflow_run_id: uuid.UUID | None = Field(default=None, description="Optional associated WorkflowRun UUID")
    asset_id: uuid.UUID | None = Field(default=None, description="Optional associated Asset UUID")
    external_post_id: str | None = Field(default=None, description="External social platform / Postiz post ID")
    source: str = Field(default="direct", description="Data source ('postiz', 'youtube_api', 'fixture', etc.)")


class AnalyticsSnapshotResponse(BaseModel):
    id: str
    video_id: str | None = None
    workflow_run_id: str | None = None
    asset_id: str | None = None
    platform: str
    external_post_id: str | None = None
    source: str
    snapshot_at: str
    views: int
    impressions: int | None = None
    likes: int
    comments: int
    shares: int
    saves: int | None = None
    subscribers_gained: int
    click_through_rate: float | None = None
    average_view_duration_seconds: float | None = None
    average_view_percentage: float | None = None
    engagement_rate: float | None = None
    watch_time_seconds: float | None = None
    completion_rate: float | None = None
    clicks: int | None = None
    revenue_usd: float | None = None
    audience_drop_off_notes: str | None = None


def _serialize_record(r: Any) -> dict[str, Any]:
    raw_meta = {}
    if getattr(r, "raw_metadata", None):
        try:
            raw_meta = json.loads(r.raw_metadata)
        except Exception:
            pass
    impressions = raw_meta.get("impressions") or raw_meta.get("impression_count")
    if impressions is not None:
        try:
            impressions = int(impressions)
        except Exception:
            impressions = None

    return {
        "id": str(r.id),
        "video_id": str(r.video_id) if r.video_id else None,
        "workflow_run_id": str(r.workflow_run_id) if r.workflow_run_id else None,
        "asset_id": str(r.asset_id) if r.asset_id else None,
        "platform": r.platform,
        "external_post_id": r.external_post_id,
        "source": r.source,
        "snapshot_at": r.snapshot_at.isoformat() if r.snapshot_at else None,
        "views": r.views,
        "impressions": impressions,
        "likes": r.likes,
        "comments": r.comments,
        "shares": r.shares,
        "saves": r.saves,
        "subscribers_gained": r.subscribers_gained,
        "click_through_rate": float(r.click_through_rate) if r.click_through_rate is not None else None,
        "average_view_duration_seconds": r.average_view_duration_seconds,
        "average_view_percentage": float(r.average_view_percentage) if r.average_view_percentage is not None else None,
        "engagement_rate": float(r.engagement_rate) if r.engagement_rate is not None else None,
        "watch_time_seconds": float(r.watch_time_seconds) if r.watch_time_seconds is not None else None,
        "completion_rate": float(r.completion_rate) if r.completion_rate is not None else None,
        "clicks": r.clicks,
        "revenue_usd": float(r.revenue_usd) if r.revenue_usd is not None else None,
        "audience_drop_off_notes": r.audience_drop_off_notes,
    }


@router.post("/ingest", response_model=AnalyticsSnapshotResponse)
async def ingest_analytics(
    payload: AnalyticsIngestRequest,
    db: AsyncSession = Depends(get_db),
):
    """Ingest, validate, and store a normalized metrics snapshot."""
    service = AnalyticsIngestionService(db=db)
    try:
        record = await service.ingest_snapshot(
            platform=payload.platform,
            raw_metrics=payload.metrics,
            video_id=payload.video_id,
            workflow_run_id=payload.workflow_run_id,
            asset_id=payload.asset_id,
            external_post_id=payload.external_post_id,
            source=payload.source,
        )
        return _serialize_record(record)
    except MetricValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Metric validation failed: {exc}",
        ) from exc


@router.get("/snapshots", response_model=list[AnalyticsSnapshotResponse])
async def list_snapshots(
    workflow_run_id: uuid.UUID | None = Query(default=None, description="Filter by WorkflowRun ID"),
    video_id: str | None = Query(default=None, description="Filter by Video ID"),
    external_post_id: str | None = Query(default=None, description="Filter by Postiz or platform post ID"),
    platform: str | None = Query(default=None, description="Filter by social platform"),
    limit: int = Query(default=50, ge=1, le=100, description="Max snapshots to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query historical analytics snapshots ordered by snapshot timestamp."""
    service = AnalyticsIngestionService(db=db)
    snapshots = await service.get_snapshots(
        workflow_run_id=workflow_run_id,
        video_id=video_id,
        external_post_id=external_post_id,
        platform=platform,
        limit=limit,
    )
    return [_serialize_record(s) for s in snapshots]


@router.get("/latest", response_model=AnalyticsSnapshotResponse)
async def get_latest_snapshot(
    workflow_run_id: uuid.UUID | None = Query(default=None, description="Filter by WorkflowRun ID"),
    video_id: str | None = Query(default=None, description="Filter by Video ID"),
    external_post_id: str | None = Query(default=None, description="Filter by Postiz or platform post ID"),
    platform: str | None = Query(default=None, description="Filter by social platform"),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent single snapshot matching query criteria."""
    service = AnalyticsIngestionService(db=db)
    snapshots = await service.get_snapshots(
        workflow_run_id=workflow_run_id,
        video_id=video_id,
        external_post_id=external_post_id,
        platform=platform,
        limit=1,
    )
    if not snapshots:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analytics snapshot found for the specified criteria",
        )
    return _serialize_record(snapshots[0])
