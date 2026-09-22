"""Analytics ingestion and measurement service for Arya OS V1.

Normalizes raw platform metrics from Postiz, direct connectors (YouTube, TikTok, etc.),
and deterministic fixtures into platform-neutral Analytics records.
Enforces:
- Metric validation (non-negative metrics, valid rate bounds)
- Idempotency per (platform, external_post_id, snapshot_at, source)
- Historical snapshot retention (Day 1 vs Day 2 coexist)
- Lineage & provenance preservation (workflow_run_id, asset_id, raw_metadata)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.analytics import Analytics

logger = get_logger("arya.services.analytics")


class MetricValidationError(ValueError):
    """Raised when an analytics metric is invalid (e.g. negative count)."""


class AnalyticsIngestionService:
    """Service to ingest, normalize, and query publishing analytics."""

    def __init__(self, db: AsyncSession):
        self._db = db

    def normalize_metrics(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Map heterogeneous platform metric names into canonical schema fields.

        Handles aliases:
        - views / impressions / view_count -> views, impressions
        - likes / like_count -> likes
        - comments / comment_count -> comments
        - shares / share_count / retweets / reposts -> shares
        - saves / bookmarks -> saves
        - subscribers_gained / followers_gained -> subscribers_gained
        - engagement_rate / engagementRate -> engagement_rate
        - watch_time_seconds / watch_time / watchTime -> watch_time_seconds
        - click_through_rate / ctr -> click_through_rate
        - clicks / link_clicks -> clicks
        - revenue / revenue_usd / earnings -> revenue_usd
        """
        data = raw_data.copy()

        # If payload contains raw Postiz labeled metrics list under "data", unpack canonical metrics
        if "views" not in data and isinstance(data.get("data"), list):
            from app.platforms.postiz import PostizAdapter
            postiz_metrics = PostizAdapter.parse_postiz_analytics(data["data"])
            for k, v in postiz_metrics.items():
                if k not in data:
                    data[k] = v

        # Extract snapshot timestamp
        raw_ts = data.get("snapshot_at") or data.get("timestamp") or data.get("date")
        if isinstance(raw_ts, datetime):
            snapshot_at = raw_ts.astimezone(timezone.utc).replace(tzinfo=None) if raw_ts.tzinfo else raw_ts
        elif isinstance(raw_ts, str):
            try:
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                snapshot_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                snapshot_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            snapshot_at = datetime.now(timezone.utc).replace(tzinfo=None)

        def _get_int(*keys: str) -> int | None:
            for k in keys:
                if k in data and data[k] is not None:
                    try:
                        val = int(data[k])
                        if val < 0:
                            raise MetricValidationError(f"Metric '{k}' cannot be negative: {val}")
                        return val
                    except (ValueError, TypeError) as exc:
                        if isinstance(exc, MetricValidationError):
                            raise
                        raise MetricValidationError(f"Invalid integer metric for '{k}': {data[k]}") from exc
            return None

        def _get_float(*keys: str, is_rate: bool = False) -> float | None:
            for k in keys:
                if k in data and data[k] is not None:
                    try:
                        val = float(data[k])
                        if val < 0:
                            raise MetricValidationError(f"Metric '{k}' cannot be negative: {val}")
                        if is_rate and val > 1.0:
                            # Normalize percentage 0-100 to 0.0-1.0
                            if val <= 100.0:
                                val = val / 100.0
                            else:
                                raise MetricValidationError(f"Rate metric '{k}' cannot exceed 1.0 (or 100%): {val}")
                        return val
                    except (ValueError, TypeError) as exc:
                        if isinstance(exc, MetricValidationError):
                            raise
                        raise MetricValidationError(f"Invalid float metric for '{k}': {data[k]}") from exc
            return None

        views = _get_int("views", "view_count")
        impressions = _get_int("impressions", "impression_count")
        likes = _get_int("likes", "like_count") or 0
        comments = _get_int("comments", "comment_count") or 0
        shares = _get_int("shares", "share_count", "retweets", "reposts") or 0
        saves = _get_int("saves", "bookmarks")
        subscribers = _get_int("subscribers_gained", "followers_gained", "new_subscribers") or 0
        clicks = _get_int("clicks", "link_clicks")

        engagement_rate = _get_float("engagement_rate", "engagementRate", is_rate=True)
        ctr = _get_float("click_through_rate", "ctr", is_rate=True)
        completion_rate = _get_float("completion_rate", "retention_rate", is_rate=True)
        avg_view_pct = _get_float("average_view_percentage", is_rate=True)
        watch_time = _get_float("watch_time_seconds", "watch_time", "watchTime")
        avg_view_duration = _get_float("average_view_duration_seconds", "avg_view_duration")
        revenue = _get_float("revenue_usd", "revenue", "earnings")

        return {
            "snapshot_at": snapshot_at,
            "views": views if views is not None else (impressions or 0),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "subscribers_gained": subscribers,
            "click_through_rate": ctr,
            "average_view_duration_seconds": avg_view_duration,
            "average_view_percentage": avg_view_pct,
            "engagement_rate": engagement_rate,
            "watch_time_seconds": watch_time,
            "completion_rate": completion_rate,
            "clicks": clicks,
            "revenue_usd": revenue,
            "audience_drop_off_notes": data.get("audience_drop_off_notes"),
        }

    async def ingest_snapshot(
        self,
        *,
        platform: str,
        raw_metrics: dict[str, Any],
        video_id: str | uuid.UUID | None = None,
        workflow_run_id: str | uuid.UUID | None = None,
        asset_id: str | uuid.UUID | None = None,
        external_post_id: str | None = None,
        source: str = "direct",
    ) -> Analytics:
        """Ingest and persist a validated analytics snapshot.

        Enforces idempotency: identical snapshot_at for the same post/platform updates
        the existing record rather than creating a duplicate.
        """
        normalized = self.normalize_metrics(raw_metrics)

        # Parse UUIDs safely
        def _parse_uuid(val: Any) -> uuid.UUID | None:
            if not val:
                return None
            if isinstance(val, uuid.UUID):
                return val
            try:
                return uuid.UUID(str(val))
            except (ValueError, TypeError):
                return None

        clean_video_id = _parse_uuid(video_id)
        clean_workflow_run_id = _parse_uuid(workflow_run_id)
        clean_asset_id = _parse_uuid(asset_id)
        clean_post_id = str(external_post_id).strip() if external_post_id else None

        # Build idempotency key
        target_id = clean_post_id or str(video_id or clean_workflow_run_id or "unknown")
        idempotency_key = f"{platform.lower()}:{target_id}:{normalized['snapshot_at'].isoformat()}:{source.lower()}"

        # Check existing for idempotency
        stmt = select(Analytics).where(Analytics.idempotency_key == idempotency_key)
        existing = (await self._db.execute(stmt)).scalars().first()

        raw_meta_json = json.dumps(raw_metrics, default=str)

        if existing:
            # Update existing snapshot in-place (idempotent overwrite)
            logger.info("analytics_snapshot_idempotent_update", idempotency_key=idempotency_key)
            for field, val in normalized.items():
                setattr(existing, field, val)
            existing.raw_metadata = raw_meta_json
            if clean_workflow_run_id:
                existing.workflow_run_id = clean_workflow_run_id
            if clean_asset_id:
                existing.asset_id = clean_asset_id
            await self._db.commit()
            await self._db.refresh(existing)
            return existing

        # Create fresh snapshot
        record = Analytics(
            video_id=clean_video_id,
            workflow_run_id=clean_workflow_run_id,
            asset_id=clean_asset_id,
            platform=platform.lower(),
            external_post_id=clean_post_id,
            source=source.lower(),
            idempotency_key=idempotency_key,
            raw_metadata=raw_meta_json,
            **normalized,
        )

        self._db.add(record)
        await self._db.commit()
        await self._db.refresh(record)

        logger.info(
            "analytics_snapshot_persisted",
            analytics_id=str(record.id),
            platform=record.platform,
            views=record.views,
            likes=record.likes,
            idempotency_key=idempotency_key,
        )
        return record

    async def get_snapshots(
        self,
        *,
        workflow_run_id: str | uuid.UUID | None = None,
        video_id: str | uuid.UUID | None = None,
        external_post_id: str | None = None,
        platform: str | None = None,
        limit: int = 50,
    ) -> list[Analytics]:
        """Query historical analytics snapshots ordered by snapshot_at DESC."""
        stmt = select(Analytics).order_by(Analytics.snapshot_at.desc()).limit(limit)

        if workflow_run_id:
            try:
                run_uuid = uuid.UUID(str(workflow_run_id))
                stmt = stmt.where(Analytics.workflow_run_id == run_uuid)
            except ValueError:
                pass

        if video_id:
            try:
                vid_uuid = uuid.UUID(str(video_id))
                stmt = stmt.where(Analytics.video_id == vid_uuid)
            except ValueError:
                pass

        if external_post_id:
            stmt = stmt.where(Analytics.external_post_id == str(external_post_id))

        if platform:
            stmt = stmt.where(Analytics.platform == platform.lower())

        results = (await self._db.execute(stmt)).scalars().all()
        return list(results)
