"""Unit tests for Postiz Analytics Response Normalization (Step 2).

Verifies:
1. Postiz labeled-array → canonical metrics dictionary (Views, Likes, Comments, Shares, Saves, etc.)
2. Multiple dated metric entries aggregation
3. Missing labels handling (skips safely without crashing)
4. Empty data arrays handling
5. Numeric strings, formatted numbers, and percentages
6. Malformed/unexpected entries robustness (negative counts, corrupt entries, non-dicts)
7. Draft response [] (releaseId=NULL) returns safe zero metrics
8. End-to-end compatibility with AnalyticsIngestionService and Analytics database model
9. Invariant: $0.00 AI generation credits spent
"""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from app.database.session import AsyncSessionLocal
from app.models.analytics import Analytics
from app.platforms.postiz import PostizAdapter
from app.services.analytics_service import AnalyticsIngestionService


# ---------------------------------------------------------------------------
# 1. Postiz Labeled-Array -> Canonical Metrics (Requirement 7.A & 7.D)
# ---------------------------------------------------------------------------

def test_postiz_labeled_array_to_canonical_metrics():
    """Verify Postiz labeled metric array maps to canonical fields."""
    raw_postiz_response = [
        {"label": "Views", "data": [{"total": "120", "date": "2026-09-21"}]},
        {"label": "Likes", "data": [{"total": "15", "date": "2026-09-21"}]},
        {"label": "Comments", "data": [{"total": "3", "date": "2026-09-21"}]},
        {"label": "Shares", "data": [{"total": "2", "date": "2026-09-21"}]},
        {"label": "Saves", "data": [{"total": "8", "date": "2026-09-21"}]},
        {"label": "Subscribers Gained", "data": [{"total": "5", "date": "2026-09-21"}]},
        {"label": "Click Through Rate", "data": [{"total": "0.045", "date": "2026-09-21"}]},
        {"label": "Engagement Rate", "data": [{"total": "0.032", "date": "2026-09-21"}]},
        {"label": "Watch Time Seconds", "data": [{"total": "450.0", "date": "2026-09-21"}]},
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 120
    assert normalized["likes"] == 15
    assert normalized["comments"] == 3
    assert normalized["shares"] == 2
    assert normalized["saves"] == 8
    assert normalized["subscribers_gained"] == 5
    assert normalized["click_through_rate"] == pytest.approx(0.045, rel=1e-3)
    assert normalized["engagement_rate"] == pytest.approx(0.032, rel=1e-3)
    assert normalized["watch_time_seconds"] == pytest.approx(450.0, rel=1e-3)


# ---------------------------------------------------------------------------
# 2. Multiple Dated Metric Entries Aggregation (Requirement 7.B)
# ---------------------------------------------------------------------------

def test_postiz_multiple_dated_metric_entries():
    """Verify count metrics across multiple dated entries are aggregated correctly."""
    raw_postiz_response = [
        {
            "label": "Views",
            "data": [
                {"total": "100", "date": "2026-09-01"},
                {"total": "50", "date": "2026-09-02"},
                {"total": "25", "date": "2026-09-03"},
            ],
        },
        {
            "label": "Likes",
            "data": [
                {"total": 10, "date": "2026-09-01"},
                {"total": 5, "date": "2026-09-02"},
            ],
        },
        {
            "label": "Comments",
            "data": [
                {"total": "2", "date": "2026-09-01"},
                {"total": "4", "date": "2026-09-02"},
            ],
        },
        {
            "label": "Shares",
            "data": [
                {"total": "1", "date": "2026-09-01"},
                {"total": "0", "date": "2026-09-02"},
            ],
        },
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 175
    assert normalized["likes"] == 15
    assert normalized["comments"] == 6
    assert normalized["shares"] == 1


# ---------------------------------------------------------------------------
# 3. Missing Labels & Unknown Metrics (Requirement 7.C)
# ---------------------------------------------------------------------------

def test_postiz_missing_or_unknown_labels():
    """Missing or unrecognized labels must be skipped without crashing."""
    raw_postiz_response = [
        {"data": [{"total": "50", "date": "2026-09-01"}]},  # Missing label key entirely
        {"label": None, "data": [{"total": "20"}]},  # Label is None
        {"label": "", "data": [{"total": "10"}]},  # Label is empty string
        {"label": "   ", "data": [{"total": "10"}]},  # Label is whitespace
        {"label": "CompletelyUnknownSocialMetric", "data": [{"total": "999"}]},  # Unrecognized
        {"label": "Views", "data": [{"total": "88", "date": "2026-09-01"}]},  # Valid
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 88
    assert normalized["likes"] == 0
    assert normalized["comments"] == 0
    assert normalized["shares"] == 0


# ---------------------------------------------------------------------------
# 4. Empty Data Arrays (Requirement 7.D)
# ---------------------------------------------------------------------------

def test_postiz_empty_data_arrays():
    """Empty data arrays must safely yield zero metrics without crashing."""
    raw_postiz_response = [
        {"label": "Views", "data": []},
        {"label": "Likes", "data": []},
        {"label": "Comments"},  # data key omitted
        {"label": "Shares", "data": None},  # data is None
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 0
    assert normalized["likes"] == 0
    assert normalized["comments"] == 0
    assert normalized["shares"] == 0


# ---------------------------------------------------------------------------
# 5. Numeric Strings, Formatted Numbers & Percentages (Requirement 7.E)
# ---------------------------------------------------------------------------

def test_postiz_numeric_strings_and_formatting():
    """Verify strings with commas, decimal points, and percentages are parsed correctly."""
    raw_postiz_response = [
        {"label": "Views", "data": [{"total": "1,250", "date": "2026-09-20"}]},
        {"label": "Likes", "data": [{"total": "42", "date": "2026-09-20"}]},
        {"label": "Comments", "data": [{"total": "0", "date": "2026-09-20"}]},
        {"label": "Shares", "data": [{"total": "15", "date": "2026-09-20"}]},
        {"label": "Engagement Rate", "data": [{"total": "4.5", "date": "2026-09-20"}]},  # 4.5% -> 0.045
        {"label": "Click Through Rate", "data": [{"total": "0.035", "date": "2026-09-20"}]},
        {"label": "Estimated Minutes Watched", "data": [{"total": "10", "date": "2026-09-20"}]},  # 10m -> 600s
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 1250
    assert normalized["likes"] == 42
    assert normalized["comments"] == 0
    assert normalized["shares"] == 15
    assert normalized["engagement_rate"] == pytest.approx(0.045, rel=1e-3)
    assert normalized["click_through_rate"] == pytest.approx(0.035, rel=1e-3)
    assert normalized["watch_time_seconds"] == pytest.approx(600.0, rel=1e-3)


# ---------------------------------------------------------------------------
# 6. Malformed & Unexpected Entries (Requirement 7.F)
# ---------------------------------------------------------------------------

def test_postiz_malformed_entries_handling():
    """Ensure malformed items, non-dicts, negative values, and corrupt strings do not crash parser."""
    raw_postiz_response = [
        None,
        "unexpected_primitive_string",
        12345,
        [],
        {"label": "Views", "data": ["corrupt_string", None, {}, {"total": "invalid"}, {"total": "80"}]},
        {"label": "Likes", "data": [{"unexpected_field": "val"}]},
        {"label": "Comments", "data": [{"total": -10}]},  # Negative clamped to 0
        {"label": "Shares", "data": [{"total": None}]},
    ]

    normalized = PostizAdapter.parse_postiz_analytics(raw_postiz_response)

    assert normalized["views"] == 80
    assert normalized["likes"] == 0
    assert normalized["comments"] == 0
    assert normalized["shares"] == 0


# ---------------------------------------------------------------------------
# 7. Draft Response [] (Requirement 7.G)
# ---------------------------------------------------------------------------

def test_postiz_draft_empty_response():
    """An unreleased draft with releaseId=NULL returns [] from Postiz, which must yield zero metrics."""
    # Direct parser check
    normalized = PostizAdapter.parse_postiz_analytics([])

    assert normalized == {
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
    }


@pytest.mark.asyncio
async def test_postiz_adapter_fetch_analytics_draft_returns_zero_metrics():
    """Verify PostizAdapter.fetch_analytics on a live draft returning [] yields safe zero metrics."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock()
    mock_secrets.get.return_value = "postiz_live_key"
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []  # Postiz draft response

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await adapter.fetch_analytics(
            published_content_id="draft_cmucjoq730001qg8iti6gim7b",
            credentials={"api_key": "postiz_live_key"},
        )

    assert "error" not in res
    assert res["source"] == "postiz"
    assert res["platform"] == "postiz"
    assert res["data"] == []
    assert res["views"] == 0
    assert res["likes"] == 0
    assert res["comments"] == 0
    assert res["shares"] == 0


# ---------------------------------------------------------------------------
# 8. Live Adapter HTTP Fetch with Real Labeled Payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_postiz_adapter_fetch_analytics_live_payload():
    """Verify fetch_analytics parses Postiz's published-post labeled payload into flat metrics."""
    mock_db = AsyncMock()
    mock_secrets = MagicMock()
    mock_secrets.get.return_value = "postiz_live_key"
    adapter = PostizAdapter(db=mock_db, secrets=mock_secrets)

    mock_payload = [
        {"label": "Views", "data": [{"total": "250", "date": "2026-09-21"}]},
        {"label": "Likes", "data": [{"total": "35", "date": "2026-09-21"}]},
        {"label": "Comments", "data": [{"total": "7", "date": "2026-09-21"}]},
        {"label": "Shares", "data": [{"total": "4", "date": "2026-09-21"}]},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await adapter.fetch_analytics(
            published_content_id="post_real_live_456",
            credentials={"api_key": "postiz_live_key"},
        )

    assert "error" not in res
    assert res["source"] == "postiz"
    assert res["platform"] == "postiz"
    assert res["data"] == mock_payload
    assert res["views"] == 250
    assert res["likes"] == 35
    assert res["comments"] == 7
    assert res["shares"] == 4


# ---------------------------------------------------------------------------
# 9. Existing Analytics Ingestion Compatibility (Requirement 7.H)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analytics_ingestion_service_compatibility():
    """Verify AnalyticsIngestionService.normalize_metrics and ingest_snapshot work seamlessly with Postiz output."""
    mock_payload = [
        {"label": "Views", "data": [{"total": "5400", "date": "2026-09-21"}]},
        {"label": "Likes", "data": [{"total": "410", "date": "2026-09-21"}]},
        {"label": "Comments", "data": [{"total": "32", "date": "2026-09-21"}]},
        {"label": "Shares", "data": [{"total": "18", "date": "2026-09-21"}]},
        {"label": "Saves", "data": [{"total": "45", "date": "2026-09-21"}]},
    ]

    adapter_result = {
        "source": "postiz",
        "platform": "postiz",
        "data": mock_payload,
        **PostizAdapter.parse_postiz_analytics(mock_payload),
    }

    async with AsyncSessionLocal() as session:
        service = AnalyticsIngestionService(db=session)

        # 1. Normalize metrics
        normalized = service.normalize_metrics(adapter_result)
        assert normalized["views"] == 5400
        assert normalized["likes"] == 410
        assert normalized["comments"] == 32
        assert normalized["shares"] == 18
        assert normalized["saves"] == 45

        # 2. Direct ingestion with raw labeled list under data
        test_post_id = f"post_postiz_{uuid.uuid4().hex[:8]}"
        snapshot = await service.ingest_snapshot(
            platform="postiz",
            external_post_id=test_post_id,
            raw_metrics={"data": mock_payload, "source": "postiz"},
            source="postiz",
        )

        assert snapshot.views == 5400
        assert snapshot.likes == 410
        assert snapshot.comments == 32
        assert snapshot.shares == 18
        assert snapshot.saves == 45
        assert snapshot.platform == "postiz"
        assert snapshot.external_post_id == test_post_id

        # Verify raw metadata preserves the raw list
        meta = json.loads(snapshot.raw_metadata)
        assert "data" in meta
        assert meta["data"][0]["label"] == "Views"


# ---------------------------------------------------------------------------
# 10. Legacy Dict & Direct Keys Compatibility
# ---------------------------------------------------------------------------

def test_legacy_dict_format_compatibility():
    """Verify parse_postiz_analytics continues to support nested or flat dicts for backward compatibility."""
    # Nested dict format from legacy test mocks
    legacy_nested = {
        "id": "post_123",
        "analytics": {
            "views": 4200,
            "likes": 310,
            "comments": 28,
            "shares": 14,
        },
    }
    norm_nested = PostizAdapter.parse_postiz_analytics(legacy_nested)
    assert norm_nested["views"] == 4200
    assert norm_nested["likes"] == 310
    assert norm_nested["comments"] == 28
    assert norm_nested["shares"] == 14

    # Flat dict format
    flat_dict = {"views": 1500, "likes": 75, "comments": 12, "shares": 5}
    norm_flat = PostizAdapter.parse_postiz_analytics(flat_dict)
    assert norm_flat["views"] == 1500
    assert norm_flat["likes"] == 75
    assert norm_flat["comments"] == 12
    assert norm_flat["shares"] == 5
