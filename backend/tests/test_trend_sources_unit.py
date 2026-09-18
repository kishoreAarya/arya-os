"""Unit tests for TrendSource interface, concrete sources, caching, ranking, and discovery service."""

import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.analytics import PerformanceLearningFeedback
from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import SimpleRateLimiter, TrendCache
from app.services.trend_sources.google_trends import GoogleTrendsSource
from app.services.trend_sources.ranker import rank_trend_signals
from app.services.trend_sources.service import TrendDiscoveryService
from app.services.trend_sources.youtube import YouTubeTrendSource


# ---------------------------------------------------------------------------
# 1. Base TrendSignal Tests
# ---------------------------------------------------------------------------

def test_trend_signal_serialization():
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
    sig = TrendSignal(
        topic="Quantum Computing Explained",
        search_volume_or_signal="1.5M views",
        relevance=0.88,
        freshness="2026-09-10T10:00:00Z",
        competition="high",
        source="youtube_data_api",
        timestamp=now,
        confidence=0.92,
        opportunity_score=78.5,
        metadata={"video_id": "vid123", "channel": "TechDaily"},
    )

    data = sig.to_dict()
    assert data["topic"] == "Quantum Computing Explained"
    assert data["search_volume_or_signal"] == "1.5M views"
    assert data["signal"] == "1.5M views"
    assert data["relevance"] == 0.88
    assert data["competition"] == "high"
    assert data["source"] == "youtube_data_api"
    assert data["confidence"] == 0.92
    assert data["opportunity_score"] == 78.5
    assert data["metadata"]["video_id"] == "vid123"
    assert "2026-09-11" in data["timestamp"]


# ---------------------------------------------------------------------------
# 2. TrendCache & RateLimiter Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trend_cache_get_set_ttl():
    cache = TrendCache[str](default_ttl_seconds=1)
    await cache.set("AI News", "cached_value")

    assert await cache.get("AI News") == "cached_value"
    assert await cache.get("ai news") == "cached_value"  # Case-insensitive
    assert await cache.get("Nonexistent") is None

    # Wait for TTL expiry
    await asyncio.sleep(1.05)
    assert await cache.get("AI News") is None


@pytest.mark.asyncio
async def test_trend_cache_clear():
    cache = TrendCache[str](default_ttl_seconds=60)
    await cache.set("Topic 1", "v1")
    await cache.set("Topic 2", "v2")
    assert cache.size == 2

    await cache.clear()
    assert cache.size == 0
    assert await cache.get("Topic 1") is None


@pytest.mark.asyncio
async def test_simple_rate_limiter():
    limiter = SimpleRateLimiter(min_interval_seconds=0.05)
    t0 = asyncio.get_event_loop().time()
    await limiter.acquire()
    await limiter.acquire()
    t1 = asyncio.get_event_loop().time()
    assert (t1 - t0) >= 0.04


# ---------------------------------------------------------------------------
# 3. YouTubeTrendSource Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_youtube_source_no_key_skips_cleanly():
    source = YouTubeTrendSource(api_key=None)
    source._api_key = None
    signals = await source.fetch_trends("python programming")
    assert signals == []


@pytest.mark.asyncio
async def test_youtube_source_fetches_and_parses_signals():
    search_payload = {
        "items": [
            {
                "id": {"videoId": "yt123"},
                "snippet": {
                    "title": "Top Python Tricks You Need to Know",
                    "channelTitle": "PythonMaster",
                    "publishedAt": "2026-09-01T10:00:00Z",
                    "description": "Essential python programming tips",
                },
            }
        ]
    }
    stats_payload = {
        "items": [
            {
                "id": "yt123",
                "snippet": {
                    "title": "Top Python Tricks You Need to Know",
                    "channelTitle": "PythonMaster",
                    "publishedAt": "2026-09-01T10:00:00Z",
                    "description": "Essential python programming tips",
                },
                "statistics": {
                    "viewCount": "450000",
                    "likeCount": "25000",
                    "commentCount": "1200",
                },
            }
        ]
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 200
        if "search" in url:
            resp.json.return_value = search_payload
        else:
            resp.json.return_value = stats_payload
        return resp

    mock_client.get = AsyncMock(side_effect=mock_get)

    source = YouTubeTrendSource(
        api_key="fake-test-key",
        client=mock_client,
        rate_limiter=SimpleRateLimiter(min_interval_seconds=0.0),
    )

    signals = await source.fetch_trends("python tricks", limit=5)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.topic == "Top Python Tricks You Need to Know"
    assert "450,000 views" in sig.search_volume_or_signal
    assert sig.competition == "medium"
    assert sig.source == "youtube_data_api"
    assert sig.metadata["video_id"] == "yt123"
    assert sig.metadata["channel"] == "PythonMaster"
    assert sig.metadata["view_count"] == 450000
    assert sig.confidence > 0.7


@pytest.mark.asyncio
async def test_youtube_source_handles_quota_exceeded():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    req = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/search")
    resp = httpx.Response(403, request=req)
    mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError("Quota Exceeded", request=req, response=resp))

    source = YouTubeTrendSource(api_key="fake-key", client=mock_client)
    signals = await source.fetch_trends("cats")
    assert signals == []


@pytest.mark.asyncio
async def test_youtube_source_handles_network_timeout():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("Timeout", request=MagicMock()))

    source = YouTubeTrendSource(api_key="fake-key", client=mock_client)
    signals = await source.fetch_trends("space exploration")
    assert signals == []


# ---------------------------------------------------------------------------
# 4. GoogleTrendsSource Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_trends_source_parses_rss_feed():
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:ht="https://trends.google.com/trends/trendingsearches/daily">
      <channel>
        <title>Daily Search Trends</title>
        <item>
          <title>Artificial Intelligence Breakthrough</title>
          <ht:approx_traffic>200,000+</ht:approx_traffic>
          <pubDate>Fri, 11 Sep 2026 08:00:00 -0400</pubDate>
          <ht:news_item>
            <ht:news_item_title>New AI Model Released</ht:news_item_title>
            <ht:news_item_snippet>Researchers announced breakthrough in robotics and artificial intelligence.</ht:news_item_snippet>
            <ht:news_item_url>https://news.example.com/ai</ht:news_item_url>
          </ht:news_item>
        </item>
        <item>
          <title>Championship Game Tonight</title>
          <ht:approx_traffic>1,000,000+</ht:approx_traffic>
          <pubDate>Fri, 11 Sep 2026 09:00:00 -0400</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.text = rss_xml
    mock_client.get = AsyncMock(return_value=resp)

    source = GoogleTrendsSource(
        client=mock_client,
        rate_limiter=SimpleRateLimiter(min_interval_seconds=0.0),
    )

    signals = await source.fetch_trends("artificial intelligence", limit=5)
    assert len(signals) == 2

    ai_sig = signals[0]
    assert ai_sig.topic == "Artificial Intelligence Breakthrough"
    assert "200,000+ searches" in ai_sig.search_volume_or_signal
    assert ai_sig.competition == "medium"
    assert ai_sig.source == "google_trends"
    assert ai_sig.relevance > 0.7
    assert ai_sig.metadata["headline"] == "New AI Model Released"

    sports_sig = signals[1]
    assert sports_sig.competition == "high"


@pytest.mark.asyncio
async def test_google_trends_source_handles_xml_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.text = "NOT XML <broken"
    mock_client.get = AsyncMock(return_value=resp)

    source = GoogleTrendsSource(client=mock_client)
    signals = await source.fetch_trends("tech")
    assert signals == []


# ---------------------------------------------------------------------------
# 5. Ranker & PerformanceLearningFeedback Blending Tests
# ---------------------------------------------------------------------------

def test_ranker_applies_positive_and_negative_feedback():
    signals = [
        TrendSignal(
            topic="Deep Learning Tutorial",
            search_volume_or_signal="100K searches",
            relevance=0.8,
            freshness="2026-09-11T00:00:00Z",
            competition="low",
            confidence=0.75,
        ),
        TrendSignal(
            topic="Celebrity Gossip Daily",
            search_volume_or_signal="1M searches",
            relevance=0.8,
            freshness="2026-09-11T00:00:00Z",
            competition="high",
            confidence=0.75,
        ),
    ]

    feedback = [
        PerformanceLearningFeedback(
            category="topic",
            insight="Deep Learning tutorials achieved 35% higher retention",
            confidence=0.9,
            is_active=True,
        ),
        PerformanceLearningFeedback(
            category="topic",
            insight="Avoid celebrity gossip due to low watch time drop-off",
            confidence=0.85,
            is_active=True,
        ),
        PerformanceLearningFeedback(
            category="topic",
            insight="Stale feedback that should be ignored",
            confidence=0.99,
            is_active=False,  # inactive!
        ),
    ]

    ranked = rank_trend_signals(signals, feedback=feedback, topic_hint="tutorial")
    assert len(ranked) == 2

    top = ranked[0]
    second = ranked[1]

    assert top.topic == "Deep Learning Tutorial"
    assert top.opportunity_score > second.opportunity_score
    assert "Boost: Deep Learning tutorials" in top.metadata.get("learning_feedback_applied", [])[0]
    assert "Penalty: Avoid celebrity gossip" in second.metadata.get("learning_feedback_applied", [])[0]


# ---------------------------------------------------------------------------
# 6. TrendDiscoveryService Multi-Source & Fallback Tests
# ---------------------------------------------------------------------------

class MockTrendSource(BaseTrendSource):
    def __init__(self, name: str, signals: list[TrendSignal]):
        self.name = name
        self._signals = signals

    async def fetch_trends(self, topic_hint: str, limit: int = 10) -> list[TrendSignal]:
        return self._signals


@pytest.mark.asyncio
async def test_discovery_service_aggregates_and_caches():
    sig1 = TrendSignal(
        topic="Electric Vehicles 2026",
        search_volume_or_signal="500K views",
        relevance=0.9,
        freshness="today",
        source="src1",
        confidence=0.8,
    )
    sig2 = TrendSignal(
        topic="Battery Technology Breakthrough",
        search_volume_or_signal="250K searches",
        relevance=0.85,
        freshness="today",
        source="src2",
        confidence=0.75,
    )

    src1 = MockTrendSource("src1", [sig1])
    src2 = MockTrendSource("src2", [sig2])
    cache = TrendCache[list[TrendSignal]](default_ttl_seconds=60)

    service = TrendDiscoveryService(sources=[src1, src2], cache=cache)

    results = await service.discover_trends("electric vehicles", limit=5)
    assert len(results) == 2
    assert {s.topic for s in results} == {"Electric Vehicles 2026", "Battery Technology Breakthrough"}

    # Subsequent call should hit cache without calling sources
    src1.fetch_trends = AsyncMock(side_effect=RuntimeError("Should not be called"))
    cached_results = await service.discover_trends("electric vehicles", limit=5)
    assert len(cached_results) == 2


@pytest.mark.asyncio
async def test_discovery_service_graceful_fallback_when_sources_offline():
    failing_source = MagicMock(spec=BaseTrendSource)
    failing_source.name = "offline_source"
    failing_source.fetch_trends = AsyncMock(return_value=[])

    feedback = [
        PerformanceLearningFeedback(
            category="topic",
            insight="Tech teardowns have proven 2x subscriber growth",
            confidence=0.88,
            based_on_video_count=5,
            is_active=True,
        )
    ]

    service = TrendDiscoveryService(
        sources=[failing_source],
        cache=TrendCache[list[TrendSignal]](default_ttl_seconds=10),
    )

    # All external sources return empty -> should gracefully fall back to historical feedback
    signals = await service.discover_trends("hardware teardown", feedback=feedback, limit=3)

    assert len(signals) >= 1
    fallback_sig = signals[0]
    assert fallback_sig.source == "historical_feedback"
    assert fallback_sig.metadata.get("fallback") is True
    assert fallback_sig.confidence >= 0.88
    assert fallback_sig.relevance >= 0.8
