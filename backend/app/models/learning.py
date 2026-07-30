"""Learning Feedback dataclasses.

These are NOT database models — they are structured input/output
objects for the Learning Feedback module. Database persistence is
handled by LearningRepository (app/repositories/learning_repository.py)
against the existing PerformanceLearningFeedback model
(app/models/analytics.py).

Design decisions:
- Pure dataclasses, no SQLAlchemy — keeps analysis logic portable.
- AnalyticsInput mirrors what AnalyticsAgent produces.
- LearningResult is what LearningFeedbackAgent returns.
- ReusablePattern captures insights that future agents can query.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AnalyticsInput:
    """Structured input to LearningFeedbackAgent.

    Mirrors the metrics that AnalyticsAgent retrieves from
    PlatformAdapter and stores in the Analytics model.
    """

    video_id: str
    title: str
    topic: str | None = None
    views: int = 0
    impressions: int | None = None
    ctr: float | None = None  # click-through rate (0.0-1.0)
    watch_time_seconds: float | None = None
    average_view_duration_seconds: float | None = None
    average_view_percentage: float | None = None  # 0.0-1.0
    retention: dict[str, float] | None = None  # {"0-30s": 0.8, "30-60s": 0.6, ...}
    likes: int = 0
    comments: int = 0
    shares: int = 0
    subscribers_gained: int = 0
    upload_date: datetime | None = None
    audience_drop_off_notes: str | None = None
    thumbnail_description: str | None = None
    script_summary: str | None = None
    prompt_text: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalyticsInput":
        """Build from a flat dict (e.g., from AnalyticsAgent output)."""
        return cls(
            video_id=str(data.get("video_id", "")),
            title=str(data.get("title", "")),
            topic=data.get("topic"),
            views=int(data.get("views", 0)),
            impressions=data.get("impressions"),
            ctr=_parse_float(data.get("ctr")),
            watch_time_seconds=_parse_float(data.get("watch_time_seconds")),
            average_view_duration_seconds=_parse_float(
                data.get("average_view_duration_seconds")
            ),
            average_view_percentage=_parse_float(
                data.get("average_view_percentage")
            ),
            retention=data.get("retention"),
            likes=int(data.get("likes", 0)),
            comments=int(data.get("comments", 0)),
            shares=int(data.get("shares", 0)),
            subscribers_gained=int(data.get("subscribers_gained", 0)),
            upload_date=_parse_datetime(data.get("upload_date")),
            audience_drop_off_notes=data.get("audience_drop_off_notes"),
            thumbnail_description=data.get("thumbnail_description"),
            script_summary=data.get("script_summary"),
            prompt_text=data.get("prompt_text"),
        )


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class ReusablePattern:
    """A single reusable insight extracted from analytics."""

    category: str  # "topic" | "script" | "thumbnail" | "prompt" | "title"
    pattern: str  # e.g., "Close-up thumbnails with faces get 2x CTR"
    evidence: str  # e.g., "Video X: face thumbnail, CTR=12%. Video Y: no face, CTR=4%"
    confidence: float  # 0.0-1.0
    conditions: list[str] = field(default_factory=list)  # when this pattern applies


@dataclass
class LearningResult:
    """Output of LearningFeedbackAgent.run()."""

    video_id: str
    success_score: float  # 0.0-100.0 composite score
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    reusable_patterns: list[ReusablePattern] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0 based on data completeness
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_feedback_rows(self) -> list[dict[str, Any]]:
        """Convert to dicts ready for LearningRepository.save_feedback().

        Each reusable pattern becomes one PerformanceLearningFeedback row.
        """
        rows = []
        for pattern in self.reusable_patterns:
            rows.append({
                "category": pattern.category,
                "insight": pattern.pattern,
                "confidence": pattern.confidence,
                "based_on_video_count": 1,  # incremented by repository on merge
                "is_active": True,
            })
        return rows
