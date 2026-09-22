"""TrendDiscoveryService — orchestrates sources, TTL caching, ranking, and graceful fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import TrendCache
from app.services.trend_sources.google_trends import GoogleTrendsSource
from app.services.trend_sources.ranker import rank_trend_signals
from app.services.trend_sources.reddit import RedditTrendSource
from app.services.trend_sources.youtube import YouTubeTrendSource

if TYPE_CHECKING:
    from app.models.analytics import PerformanceLearningFeedback

logger = get_logger("arya.trend_sources.service")


class TrendDiscoveryService:
    """Orchestrator for multi-source trend discovery with caching and fallback."""

    def __init__(
        self,
        sources: list[BaseTrendSource] | None = None,
        cache: TrendCache[list[TrendSignal]] | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._sources = (
            sources
            if sources is not None
            else [YouTubeTrendSource(), GoogleTrendsSource(), RedditTrendSource()]
        )
        self._cache = cache or TrendCache[list[TrendSignal]](default_ttl_seconds=ttl_seconds)

    def _generate_fallback_signals(
        self,
        topic_hint: str,
        feedback: list[PerformanceLearningFeedback] | None = None,
        limit: int = 5,
    ) -> list[TrendSignal]:
        """Gracefully generate contextual signals when external APIs are offline/unavailable."""
        signals: list[TrendSignal] = []
        clean_topic = topic_hint.strip() or "General"
        now_iso = datetime.now(timezone.utc).isoformat()

        active_feedback = [f for f in (feedback or []) if getattr(f, "is_active", True)]

        if active_feedback:
            for fb in active_feedback[:limit]:
                signals.append(
                    TrendSignal(
                        topic=clean_topic,
                        search_volume_or_signal=f"Channel insight: {fb.insight[:80]}",
                        relevance=0.85,
                        freshness=now_iso,
                        competition="medium",
                        source="historical_feedback",
                        confidence=float(fb.confidence or 0.75),
                        metadata={
                            "fallback": True,
                            "feedback_category": fb.category,
                            "based_on_video_count": fb.based_on_video_count,
                            "insight": fb.insight,
                        },
                    )
                )

        if not signals:
            signals.append(
                TrendSignal(
                    topic=clean_topic,
                    search_volume_or_signal="Target topic baseline research",
                    relevance=0.8,
                    freshness=now_iso,
                    competition="medium",
                    source="fallback_baseline",
                    confidence=0.6,
                    metadata={"fallback": True},
                )
            )

        logger.info(
            "trend_discovery_using_fallback",
            topic=clean_topic,
            fallback_count=len(signals),
            source="historical_feedback" if active_feedback else "fallback_baseline",
        )
        return signals

    async def discover_trends(
        self,
        topic_hint: str,
        feedback: list[PerformanceLearningFeedback] | None = None,
        limit: int = 5,
        use_cache: bool = True,
        subreddit: str | None = None,
        time_filter: str = "all",
    ) -> list[TrendSignal]:
        """Discover, blend, and rank trends for a given topic."""
        clean_topic = topic_hint.strip()
        cache_key = (
            f"{clean_topic}::{subreddit or ''}::{time_filter}"
            if (subreddit or time_filter != "all")
            else clean_topic
        )

        # 1. Check cache
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached:
                logger.info("trend_discovery_cache_hit", topic=clean_topic, count=len(cached))
                ranked_cached = rank_trend_signals(cached, feedback=feedback, topic_hint=clean_topic)
                return ranked_cached[:limit]

        # 2. Query external sources concurrently
        tasks = []
        for source in self._sources:
            if isinstance(source, RedditTrendSource):
                tasks.append(
                    source.fetch_trends(
                        clean_topic,
                        limit=limit,
                        subreddit=subreddit,
                        time_filter=time_filter,
                    )
                )
            else:
                tasks.append(source.fetch_trends(clean_topic, limit=limit))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_signals: list[TrendSignal] = []
        for src, res in zip(self._sources, results):
            if isinstance(res, Exception):
                logger.warning("trend_source_exception", source=src.name, error=str(res))
            elif isinstance(res, list):
                all_signals.extend(res)

        # 3. Fallback if all external sources failed or produced no signals
        if not all_signals:
            all_signals = self._generate_fallback_signals(
                topic_hint=clean_topic, feedback=feedback, limit=limit
            )

        # 4. Rank with PerformanceLearningFeedback
        ranked = rank_trend_signals(all_signals, feedback=feedback, topic_hint=clean_topic)

        # 5. Populate cache
        if use_cache and ranked:
            await self._cache.set(cache_key, ranked)

        return ranked[:limit]
