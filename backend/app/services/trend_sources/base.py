"""Base interfaces and data structures for trend research sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TrendSignal:
    """Structured trend signal discovered from an external research source."""

    topic: str
    search_volume_or_signal: str  # e.g., "1.2M views", "Breakout query (+250%)"
    relevance: float  # 0.0 to 1.0 (relevance to requested topic)
    freshness: str  # e.g., ISO timestamp or relative freshness description
    competition: str | None = None  # "low", "medium", "high"
    source: str = "unknown"  # e.g., "youtube_data_api", "google_trends", "historical_feedback"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 0.5  # 0.0 to 1.0
    opportunity_score: float | None = None  # 0.0 to 100.0 composite opportunity score
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def signal(self) -> str:
        """Convenience alias for search_volume_or_signal."""
        return self.search_volume_or_signal

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a clean, JSON-compatible dictionary."""
        return {
            "topic": self.topic,
            "search_volume_or_signal": self.search_volume_or_signal,
            "signal": self.search_volume_or_signal,
            "relevance": round(float(self.relevance), 3),
            "freshness": self.freshness,
            "competition": self.competition,
            "source": self.source,
            "timestamp": (
                self.timestamp.isoformat()
                if hasattr(self.timestamp, "isoformat")
                else str(self.timestamp)
            ),
            "confidence": round(float(self.confidence), 3),
            "opportunity_score": (
                round(float(self.opportunity_score), 2)
                if self.opportunity_score is not None
                else None
            ),
            "metadata": dict(self.metadata),
        }


class BaseTrendSource(ABC):
    """Abstract base interface for all trend research sources."""

    name: str

    @abstractmethod
    async def fetch_trends(
        self, topic_hint: str, limit: int = 10
    ) -> list[TrendSignal]:
        """Fetch trend signals for a given topic or topic hint.

        Must return a list of TrendSignal.
        Must handle its own exceptions and return [] or log errors without crashing.
        """
        ...
