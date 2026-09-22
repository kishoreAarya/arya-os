"""Trend research sources and discovery package."""

from app.services.trend_sources.base import BaseTrendSource, TrendSignal
from app.services.trend_sources.cache import SimpleRateLimiter, TrendCache
from app.services.trend_sources.google_trends import GoogleTrendsSource
from app.services.trend_sources.ranker import rank_trend_signals
from app.services.trend_sources.reddit import RedditTrendSource
from app.services.trend_sources.service import TrendDiscoveryService
from app.services.trend_sources.youtube import YouTubeTrendSource

__all__ = [
    "BaseTrendSource",
    "TrendSignal",
    "TrendCache",
    "SimpleRateLimiter",
    "YouTubeTrendSource",
    "GoogleTrendsSource",
    "RedditTrendSource",
    "rank_trend_signals",
    "TrendDiscoveryService",
]
