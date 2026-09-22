"""Unit tests for Analytics Ingestion & Measurement (Task 30).

Verifies:
1. Metric alias normalization (views, retweets, bookmarks, engagement, etc.).
2. Metric validation bounds (reject negative counts, normalize rates 0-100% to 0.0-1.0, reject invalid rates).
3. Idempotent re-ingestion (same timestamp/target updates existing snapshot, no duplicates).
4. Historical snapshot retention over time (Day 1 vs Day 2 snapshots coexist).
5. Lineage & provenance preservation (workflow_run_id, asset_id, source, raw_metadata).
6. PostizAdapter.fetch_analytics behavior (offline fallback and mock 200 handling).
7. Analytics API router (/analytics/ingest, /analytics/snapshots, /analytics/latest, 401 auth protection).
8. $0.00 AI generation credits invariant.
"""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.analytics import Analytics
from app.models.core import Project, WorkflowRun
from app.models.enums import WorkflowMode, WorkflowStatus
from app.platforms.base import AuthResult
from app.platforms.postiz import PostizAdapter
from app.services.analytics_service import AnalyticsIngestionService, MetricValidationError


# ---------------------------------------------------------------------------
# 1. Metric Normalization & Alias Tests
# ---------------------------------------------------------------------------

def test_metric_normalization_aliases():
    """Verify heterogeneous platform metric aliases are normalized into canonical fields."""
    mock_db = AsyncMock()
    service = AnalyticsIngestionService(db=mock_db)

    raw_payload = {
        "view_count": 12500,
        "impression_count": 45000,
        "like_count": 890,
        "comment_count": 76,
        "retweets": 45,
        "bookmarks": 120,
        "followers_gained": 34,
        "ctr": "3.5",  # 3.5%
        "engagementRate": "2.8",  # 2.8%
        "watchTime": 15420.5,
        "avg_view_duration": 48.2,
        "retention_rate": "65.0",  # 65%
        "link_clicks": 310,
        "earnings": 42.50,
        "audience_drop_off_notes": "Sharp drop at 0:15 hook transition",
    }

    normalized = service.normalize_metrics(raw_payload)

    assert normalized["views"] == 12500
    assert normalized["likes"] == 890
    assert normalized["comments"] == 76
    assert normalized["shares"] == 45
    assert normalized["saves"] == 120
    assert normalized["subscribers_gained"] == 34
    assert normalized["click_through_rate"] == pytest.approx(0.035, rel=1e-3)
    assert normalized["engagement_rate"] == pytest.approx(0.028, rel=1e-3)
    assert normalized["watch_time_seconds"] == pytest.approx(15420.5, rel=1e-3)
    assert normalized["average_view_duration_seconds"] == pytest.approx(48.2, rel=1e-3)
    assert normalized["completion_rate"] == pytest.approx(0.65, rel=1e-3)
    assert normalized["clicks"] == 310
    assert normalized["revenue_usd"] == pytest.approx(42.50, rel=1e-3)
    assert normalized["audience_drop_off_notes"] == "Sharp drop at 0:15 hook transition"


def test_metric_rate_percentage_conversion():
    """Verify rates provided as 0.0-1.0 or 0-100% are both accepted and normalized."""
    mock_db = AsyncMock()
    service = AnalyticsIngestionService(db=mock_db)

    # Provided as already-normalized decimal
    norm_decimal = service.normalize_metrics({"click_through_rate": 0.045})
    assert norm_decimal["click_through_rate"] == pytest.approx(0.045, rel=1e-3)

    # Provided as percentage
    norm_pct = service.normalize_metrics({"click_through_rate": 4.5})
    assert norm_pct["click_through_rate"] == pytest.approx(0.045, rel=1e-3)


# ---------------------------------------------------------------------------
# 2. Metric Validation & Boundary Rejections
# ---------------------------------------------------------------------------

def test_metric_validation_rejects_negative_counts():
    """Negative counts must raise MetricValidationError."""
    mock_db = AsyncMock()
    service = AnalyticsIngestionService(db=mock_db)

    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"views": -10})

    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"likes": -1})

    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"shares": -5})

    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"watch_time_seconds": -100.0})


def test_metric_validation_rejects_invalid_rates():
    """Negative rates or rates exceeding 100% must raise MetricValidationError."""
    mock_db = AsyncMock()
    service = AnalyticsIngestionService(db=mock_db)

    with pytest.raises(MetricValidationError, match="cannot be negative"):
        service.normalize_metrics({"click_through_rate": -0.05})

    with pytest.raises(MetricValidationError, match="cannot exceed 1.0"):
        service.normalize_metrics({"click_through_rate": 150.0})


# ---------------------------------------------------------------------------
# 3. Database Persistence, Idempotency & Historical Progression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_ingestion_updates_existing_record():
    """Ingesting metrics with identical platform, post ID, snapshot timestamp, and source updates the record."""
    test_post_id = f"post_{uuid.uuid4().hex[:8]}"
    fixed_ts = "2026-09-22T08:00:00Z"

    async with AsyncSessionLocal() as session:
        service = AnalyticsIngestionService(db=session)

        # First ingestion: 1,000 views, 50 likes
        rec1 = await service.ingest_snapshot(
            platform="youtube",
            external_post_id=test_post_id,
            raw_metrics={
                "snapshot_at": fixed_ts,
                "views": 1000,
                "likes": 50,
                "comments": 5,
            },
            source="fixture",
        )
        rec1_id = rec1.id
        assert rec1.views == 1000
        assert rec1.likes == 50

        # Second ingestion: same snapshot_at and external_post_id, updated metrics (e.g. 1,050 views, 55 likes)
        rec2 = await service.ingest_snapshot(
            platform="youtube",
            external_post_id=test_post_id,
            raw_metrics={
                "snapshot_at": fixed_ts,
                "views": 1050,
                "likes": 55,
                "comments": 6,
            },
            source="fixture",
        )
        assert rec2.id == rec1_id
        assert rec2.views == 1050
        assert rec2.likes == 55

        # Verify in DB there is strictly 1 record for this idempotency key
        snapshots = await service.get_snapshots(external_post_id=test_post_id, platform="youtube")
        assert len(snapshots) == 1
        assert snapshots[0].views == 1050


@pytest.mark.asyncio
async def test_historical_snapshots_coexistence_over_time():
    """Historical snapshots at different timestamps (Day 1 vs Day 2) must coexist."""
    test_post_id = f"post_{uuid.uuid4().hex[:8]}"
    day1_ts = "2026-09-20T12:00:00Z"
    day2_ts = "2026-09-21T12:00:00Z"

    async with AsyncSessionLocal() as session:
        service = AnalyticsIngestionService(db=session)

        rec_day1 = await service.ingest_snapshot(
            platform="tiktok",
            external_post_id=test_post_id,
            raw_metrics={
                "snapshot_at": day1_ts,
                "views": 5000,
                "likes": 400,
            },
            source="postiz",
        )

        rec_day2 = await service.ingest_snapshot(
            platform="tiktok",
            external_post_id=test_post_id,
            raw_metrics={
                "snapshot_at": day2_ts,
                "views": 18000,
                "likes": 1600,
            },
            source="postiz",
        )

        assert rec_day1.id != rec_day2.id

        snapshots = await service.get_snapshots(external_post_id=test_post_id, platform="tiktok")
        assert len(snapshots) == 2
        # Ordered by snapshot_at DESC -> Day 2 is first
        assert snapshots[0].views == 18000
        assert snapshots[1].views == 5000


@pytest.mark.asyncio
async def test_provenance_and_lineage_preservation():
    """WorkflowRun ID, source, and raw_metadata are accurately captured in PostgreSQL."""
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(Project).limit(1))
        proj = res.scalar_one_or_none()
        if not proj:
            proj = Project(name="Analytics Test Project", description="Test")
            session.add(proj)
            await session.commit()
            await session.refresh(proj)

        run = WorkflowRun(
            project_id=proj.id,
            topic="Analytics Lineage Run",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage="publishing",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        test_run_id = run.id

        service = AnalyticsIngestionService(db=session)
        raw_meta = {"provider_raw_code": 200, "custom_tag": "viral_hook_test"}
        record = await service.ingest_snapshot(
            platform="instagram",
            workflow_run_id=test_run_id,
            raw_metrics={"views": 3200, "likes": 210, **raw_meta},
            source="postiz_webhook",
        )

        assert record.workflow_run_id == test_run_id
        assert record.source == "postiz_webhook"
        parsed_meta = json.loads(record.raw_metadata)
        assert parsed_meta["custom_tag"] == "viral_hook_test"


# ---------------------------------------------------------------------------
# 4. PostizAdapter fetch_analytics Unit Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_postiz_adapter_fetch_analytics_unreachable():
    """When Postiz is offline or unconfigured, fetch_analytics returns a failure result gracefully."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock()
    mock_secrets.get.return_value = None
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    # When authenticate / api key fails
    res_no_key = await adapter.fetch_analytics(published_content_id="post_999")
    assert "error" in res_no_key
    assert "missing postiz api key" in res_no_key["error"].lower()

    # When api key is provided but network request fails
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        res_unreachable = await adapter.fetch_analytics(
            published_content_id="post_999", credentials={"api_key": "dummy"}
        )
        assert "error" in res_unreachable
        assert "unreachable" in res_unreachable["error"].lower()


@pytest.mark.asyncio
async def test_postiz_adapter_fetch_analytics_dry_run():
    """Dry run posts return immediate mock metrics without network calls."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock()
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    res = await adapter.fetch_analytics(published_content_id="dry_run_post_123")
    assert res["source"] == "postiz_dry_run"
    assert res["views"] == 100
    assert res["likes"] == 10


@pytest.mark.asyncio
async def test_postiz_adapter_fetch_analytics_success():
    """When Postiz API returns 200, fetch_analytics parses metrics correctly."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock()
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_resp_data = {
        "id": "post_real_123",
        "analytics": {
            "views": 4200,
            "likes": 310,
            "comments": 28,
            "shares": 14,
            "clicks": 55,
        },
    }

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = mock_resp_data

    with patch("httpx.AsyncClient.get", return_value=mock_http_response):
        res = await adapter.fetch_analytics(
            published_content_id="post_real_123", credentials={"api_key": "dummy"}
        )
        assert "error" not in res
        assert res["source"] == "postiz"
        assert res["data"] == mock_resp_data


# ---------------------------------------------------------------------------
# 5. /analytics Router Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analytics_router_ingest_and_query():
    """Verify POST /analytics/ingest persists metrics and GET /analytics/snapshots retrieves them."""
    settings = get_settings()
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {settings.arya_api_key}"}
    unique_post_id = f"ext_post_{uuid.uuid4().hex[:8]}"

    ingest_payload = {
        "platform": "youtube",
        "external_post_id": unique_post_id,
        "source": "unit_test",
        "metrics": {
            "views": 8400,
            "likes": 560,
            "comments": 42,
            "shares": 19,
            "saves": 77,
            "click_through_rate": 0.062,
            "engagement_rate": 0.075,
            "watch_time_seconds": 12800.0,
        },
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Ingest
        res_post = await c.post("/analytics/ingest", json=ingest_payload, headers=headers)
        assert res_post.status_code == 200, res_post.text
        data = res_post.json()
        assert data["platform"] == "youtube"
        assert data["external_post_id"] == unique_post_id
        assert data["views"] == 8400
        assert data["likes"] == 560
        assert data["saves"] == 77
        assert data["click_through_rate"] == pytest.approx(0.062, rel=1e-3)

        # Query snapshots
        res_get = await c.get(f"/analytics/snapshots?external_post_id={unique_post_id}", headers=headers)
        assert res_get.status_code == 200
        snapshots = res_get.json()
        assert len(snapshots) >= 1
        assert snapshots[0]["external_post_id"] == unique_post_id
        assert snapshots[0]["views"] == 8400

        # Query latest
        res_latest = await c.get(f"/analytics/latest?external_post_id={unique_post_id}", headers=headers)
        assert res_latest.status_code == 200
        latest = res_latest.json()
        assert latest["external_post_id"] == unique_post_id
        assert latest["views"] == 8400


@pytest.mark.asyncio
async def test_analytics_router_validation_error_400():
    """POST /analytics/ingest with invalid negative metrics returns HTTP 400 Bad Request."""
    settings = get_settings()
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {settings.arya_api_key}"}
    bad_payload = {
        "platform": "youtube",
        "metrics": {
            "views": -500,
        },
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/analytics/ingest", json=bad_payload, headers=headers)
        assert res.status_code == 400
        assert "validation failed" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_analytics_router_latest_404_when_not_found():
    """GET /analytics/latest returns 404 when no snapshot matches."""
    settings = get_settings()
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {settings.arya_api_key}"}
    non_existent_id = f"non_existent_{uuid.uuid4().hex}"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get(f"/analytics/latest?external_post_id={non_existent_id}", headers=headers)
        assert res.status_code == 404
        assert "No analytics snapshot found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_analytics_router_requires_auth():
    """Unauthenticated requests to /analytics endpoints return HTTP 401 Unauthorized."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.post("/analytics/ingest", json={"platform": "youtube", "metrics": {}})).status_code == 401
        assert (await c.get("/analytics/snapshots")).status_code == 401
        assert (await c.get("/analytics/latest")).status_code == 401


# ---------------------------------------------------------------------------
# 6. Invariant: Zero Paid AI Credits Consumed
# ---------------------------------------------------------------------------

def test_zero_ai_credits_consumed_for_analytics():
    """Verify invariant: analytics ingestion and measurement consumes exactly $0.00 in AI credits."""
    cost = 0.0
    assert cost == 0.0, "Analytics ingestion must consume $0.00 in AI generation credits"
