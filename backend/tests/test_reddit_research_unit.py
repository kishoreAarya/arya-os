"""Unit tests for Reddit research, discussion scraping, signal normalization, and API endpoints.

Zero AI generation credits are consumed by these tests.
"""

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest
from httpx import AsyncClient, ASGITransport

from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.system import SystemLog
from app.services.trend_sources.base import TrendSignal
from app.services.trend_sources.reddit import (
    RedditTrendSource,
    _clean_text_content,
    _extract_discussion_themes,
)
from app.services.trend_sources.service import TrendDiscoveryService


# ---------------------------------------------------------------------------
# Fixture data: realistic Reddit API JSON response
# ---------------------------------------------------------------------------

SAMPLE_REDDIT_RESPONSE = {
    "kind": "Listing",
    "data": {
        "after": "t3_sample",
        "dist": 2,
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "1abcde",
                    "name": "t3_1abcde",
                    "title": "How to optimize LangChain agents for production latency?",
                    "selftext": "We are struggling with high latency in our agent loop. Any advice or best recommendations for prompt caching and latency reduction?",
                    "author": "dev_researcher",
                    "score": 1420,
                    "num_comments": 185,
                    "permalink": "/r/MachineLearning/comments/1abcde/how_to_optimize_langchain/",
                    "url": "https://www.reddit.com/r/MachineLearning/comments/1abcde/how_to_optimize_langchain/",
                    "created_utc": 1726000000.0,
                    "subreddit": "MachineLearning",
                    "upvote_ratio": 0.94,
                    "over_18": False,
                    "is_self": True,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "2fghij",
                    "name": "t3_2fghij",
                    "title": "PyTorch vs JAX in 2026: Benchmark and comparison analysis",
                    "selftext": "Here is our thorough comparison of throughput across H100 clusters.",
                    "author": "cluster_lead",
                    "score": 3890,
                    "num_comments": 412,
                    "permalink": "/r/LocalLLaMA/comments/2fghij/pytorch_vs_jax_2026/",
                    "url": "https://github.com/benchmark/pytorch-vs-jax",
                    "created_utc": 1726050000.0,
                    "subreddit": "LocalLLaMA",
                    "upvote_ratio": 0.98,
                    "over_18": False,
                    "is_self": False,
                },
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# 1. Query Normalization & URL Construction Tests
# ---------------------------------------------------------------------------

def test_reddit_query_normalization_global_search():
    source = RedditTrendSource()
    url, params = source._build_request_params(
        topic_hint="AI Video Generation",
        limit=15,
        subreddit=None,
        time_filter="month",
        sort="top",
    )
    assert url == "https://www.reddit.com/search.json"
    assert params["q"] == "AI Video Generation"
    assert params["limit"] == 15
    assert params["t"] == "month"
    assert params["sort"] == "top"


def test_reddit_query_normalization_subreddit_scoped():
    source = RedditTrendSource()
    url, params = source._build_request_params(
        topic_hint="flux prompt",
        limit=10,
        subreddit="r/StableDiffusion",
        time_filter="week",
    )
    assert url == "https://www.reddit.com/r/StableDiffusion/search.json"
    assert params["q"] == "flux prompt"
    assert params["restrict_sr"] == 1
    assert params["t"] == "week"


def test_reddit_query_normalization_subreddit_listing_empty_topic():
    source = RedditTrendSource()
    # When topic is empty, fetch top/hot listing directly from subreddit
    url, params = source._build_request_params(
        topic_hint="",
        limit=20,
        subreddit="MachineLearning",
        time_filter="day",
    )
    assert url == "https://www.reddit.com/r/MachineLearning/top.json"
    assert params["limit"] == 20
    assert params["t"] == "day"


def test_reddit_query_clamping_and_sanitization():
    source = RedditTrendSource()
    # Limit clamp max 50, min 1
    _, params1 = source._build_request_params("test", limit=999)
    assert params1["limit"] == 50

    _, params2 = source._build_request_params("test", limit=-5)
    assert params2["limit"] == 1

    # Invalid time_filter falls back to 'all'
    _, params3 = source._build_request_params("test", limit=10, time_filter="invalid_filter")
    assert params3["t"] == "all"


# ---------------------------------------------------------------------------
# 2. Result Normalization & Metadata Provenance Tests
# ---------------------------------------------------------------------------

def test_reddit_result_normalization_provenance():
    source = RedditTrendSource()
    raw_post = SAMPLE_REDDIT_RESPONSE["data"]["children"][0]["data"]
    retrieved_at = datetime.now(timezone.utc).isoformat()

    sig = source._normalize_post_item(raw_post, "LangChain", retrieved_at)
    assert sig is not None

    # Top-level TrendSignal properties
    assert sig.source == "reddit"
    assert sig.topic == "How to optimize LangChain agents for production latency?"
    assert "1,420 upvotes" in sig.search_volume_or_signal
    assert "185 comments" in sig.search_volume_or_signal
    assert sig.competition == "medium"
    assert sig.confidence >= 0.9
    assert sig.opportunity_score is not None
    assert sig.opportunity_score > 0

    # Detailed metadata fields
    meta = sig.metadata
    assert meta["source"] == "reddit"
    assert meta["subreddit"] == "MachineLearning"
    assert meta["post_id"] == "1abcde"
    assert meta["title"] == "How to optimize LangChain agents for production latency?"
    assert meta["url"] == "https://www.reddit.com/r/MachineLearning/comments/1abcde/how_to_optimize_langchain/"
    assert meta["permalink"].startswith("https://www.reddit.com/r/MachineLearning/comments/")
    assert meta["score"] == 1420
    assert meta["comment_count"] == 185
    assert meta["author"] == "dev_researcher"
    assert meta["upvote_ratio"] == 0.94
    assert meta["retrieved_at"] == retrieved_at
    assert "how_to_inquiry" in meta["extracted_themes"]
    assert "pain_point_troubleshooting" in meta["extracted_themes"]

    # Serialization to dict
    d = sig.to_dict()
    assert d["source"] == "reddit"
    assert d["metadata"]["post_id"] == "1abcde"


def test_theme_extraction_and_cleaning():
    text = "[Documentation Link](https://example.com) for **PyTorch vs JAX** comparison."
    cleaned = _clean_text_content(text)
    assert "Documentation Link" in cleaned
    assert "https://example.com" not in cleaned

    themes = _extract_discussion_themes(
        "PyTorch vs JAX in 2026: Benchmark and comparison analysis",
        "Which framework is best for training?",
    )
    assert "comparison_analysis" in themes
    assert "user_question" in themes


# ---------------------------------------------------------------------------
# 3. Successful Fetch with Mock Client Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reddit_fetch_trends_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_REDDIT_RESPONSE
    mock_resp.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("LangChain", limit=5)

    assert len(signals) == 2
    assert signals[0].metadata["subreddit"] == "MachineLearning"
    assert signals[1].metadata["subreddit"] == "LocalLLaMA"
    assert signals[0].source == "reddit"


# ---------------------------------------------------------------------------
# 4. Error Handling & Edge Cases Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reddit_empty_results_handling():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"kind": "Listing", "data": {"children": []}}
    mock_resp.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("completely_unique_topic_xyz123")
    assert signals == []


@pytest.mark.asyncio
async def test_reddit_malformed_response_handling():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"unexpected": "payload", "error": 400}
    mock_resp.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("topic")
    assert signals == []


@pytest.mark.asyncio
async def test_reddit_rate_limit_429():
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.headers = {"retry-after": "60"}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("topic")
    assert signals == []


@pytest.mark.asyncio
async def test_reddit_forbidden_403_and_401():
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("topic")
    assert signals == []


@pytest.mark.asyncio
async def test_reddit_network_timeout():
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")

    source = RedditTrendSource(client=mock_client)
    signals = await source.fetch_trends("topic")
    assert signals == []


# ---------------------------------------------------------------------------
# 5. TrendDiscoveryService Orchestration Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trend_discovery_service_includes_reddit():
    service = TrendDiscoveryService()
    source_names = [s.name for s in service._sources]
    assert "reddit" in source_names
    assert "youtube_data_api" in source_names
    assert "google_trends" in source_names


# ---------------------------------------------------------------------------
# 6. API Endpoint Tests (/research/reddit and /research/trends)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_research_api_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Without auth header -> 401 Unauthorized
        resp = await c.get("/research/reddit?topic=python")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_research_api_rejects_empty_query():
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer arya_dev_secret_key_change_in_production"}
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Neither topic nor subreddit provided -> 422
        resp = await c.get("/research/reddit", headers=headers)
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_research_api_get_success_mocked():
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer arya_dev_secret_key_change_in_production"}

    sample_signal = TrendSignal(
        topic="FastAPI v2 release",
        search_volume_or_signal="800 upvotes, 95 comments",
        relevance=0.92,
        freshness="2026-09-20T10:00:00Z",
        competition="medium",
        source="reddit",
        confidence=0.88,
        opportunity_score=82.0,
        metadata={"subreddit": "Python", "post_id": "fastapi_v2"},
    )

    with patch("app.api.routers.research._SHARED_REDDIT_SOURCE.fetch_trends", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [sample_signal]

        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/research/reddit?topic=FastAPI&subreddit=Python", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["source"] == "reddit"
            assert data["total_results"] == 1
            assert data["query"]["topic"] == "FastAPI"
            assert data["query"]["subreddit"] == "Python"
            assert data["results"][0]["topic"] == "FastAPI v2 release"
            assert data["results"][0]["metadata"]["subreddit"] == "Python"


@pytest.mark.asyncio
async def test_research_api_post_with_persistence():
    from app.models.core import Project, WorkflowRun
    from app.models.enums import WorkflowMode, WorkflowStatus

    # Create a real WorkflowRun record to satisfy the foreign key constraint
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(Project).limit(1))
        proj = res.scalar_one_or_none()
        if not proj:
            proj = Project(name="Test Research Project", description="Test")
            session.add(proj)
            await session.commit()
            await session.refresh(proj)

        run = WorkflowRun(
            project_id=proj.id,
            topic="Test Research Run",
            mode=WorkflowMode.ASSISTED,
            status=WorkflowStatus.PENDING,
            current_stage="research",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        test_run_id = run.id

    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer arya_dev_secret_key_change_in_production"}

    sample_signal = TrendSignal(
        topic="Claude Code vs Codex",
        search_volume_or_signal="1,200 upvotes, 300 comments",
        relevance=0.95,
        freshness="2026-09-21T08:00:00Z",
        competition="high",
        source="reddit",
        confidence=0.91,
        opportunity_score=85.0,
        metadata={"subreddit": "artificial", "post_id": "post_999"},
    )

    with patch("app.api.routers.research._SHARED_REDDIT_SOURCE.fetch_trends", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [sample_signal]

        async with AsyncClient(transport=transport, base_url="http://test") as c:
            payload = {
                "topic": "Claude Code",
                "subreddit": "artificial",
                "time_range": "month",
                "limit": 5,
                "workflow_run_id": str(test_run_id),
            }
            resp = await c.post("/research/reddit", json=payload, headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_results"] == 1

        # Verify persistence in PostgreSQL SystemLog
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            q = await session.execute(
                select(SystemLog).where(SystemLog.workflow_run_id == test_run_id)
            )
            logs = q.scalars().all()
            assert len(logs) >= 1
            assert logs[0].event_type == "RedditResearchDiscovered"
            logged_data = json.loads(logs[0].message)
            assert logged_data["source"] == "reddit"
            assert logged_data["topic"] == "Claude Code"
            assert logged_data["subreddit"] == "artificial"


# ---------------------------------------------------------------------------
# 7. Paid Generation Credits Invariance Verification
# ---------------------------------------------------------------------------

def test_zero_paid_generation_credits_invariance():
    """Verify that Reddit research capability introduces no paid generation cost."""
    source = RedditTrendSource()
    # Source metadata is pure research data
    assert source.name == "reddit"
    # Cost tier for research is 0
    raw_post = SAMPLE_REDDIT_RESPONSE["data"]["children"][0]["data"]
    sig = source._normalize_post_item(raw_post, "topic", "2026-09-22T00:00:00Z")
    assert sig is not None
    # No provider cost exists for research signals
    assert sig.metadata.get("cost_usd") is None or sig.metadata.get("cost_usd") == 0.0
