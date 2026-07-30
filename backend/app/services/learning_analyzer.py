"""LearningAnalyzer — pure analysis logic for video performance.

This module contains NO database access, NO async I/O, and NO external
API calls. It is a deterministic, synchronous service that takes
structured analytics input and produces structured learning output.

Design decisions:
- Synchronous (no I/O) — can be unit-tested without async machinery.
- Thresholds are configurable via constructor parameters (not hardcoded).
- Each analysis method is small, focused, and independently testable.
- No ML models, no external APIs — rule-based analysis only.

The analyzer evaluates performance across five categories:
  topic, script, thumbnail, prompt, title

It produces:
  - A composite success_score (0-100)
  - Strengths and weaknesses per category
  - Actionable recommendations
  - ReusablePatterns for future content generation
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.models.learning import AnalyticsInput, LearningResult, ReusablePattern

logger = get_logger(__name__)


@dataclass
class AnalysisThresholds:
    """Configurable thresholds for performance classification.

    All values have sensible defaults but can be overridden per
    deployment (e.g., stricter for established channels, looser for
    new channels).
    """

    # Engagement thresholds
    high_ctr: float = 0.08  # 8% CTR is strong
    low_ctr: float = 0.03  # 3% CTR needs improvement
    high_retention: float = 0.50  # 50% average view percentage
    low_retention: float = 0.20  # 20% is poor
    high_like_rate: float = 0.05  # 5% like-to-view ratio
    high_comment_rate: float = 0.01  # 1% comment-to-view ratio

    # View velocity thresholds (views per day since upload)
    high_velocity: float = 1000.0
    low_velocity: float = 50.0

    # Composite score weights
    weight_ctr: float = 0.25
    weight_retention: float = 0.30
    weight_engagement: float = 0.25
    weight_velocity: float = 0.20


class LearningAnalyzer:
    """Analyzes video analytics and extracts reusable learning insights."""

    def __init__(self, thresholds: AnalysisThresholds | None = None):
        self._thresholds = thresholds or AnalysisThresholds()

    def analyze(self, data: AnalyticsInput) -> LearningResult:
        """Run the full analysis pipeline on analytics data."""
        logger.info(
            "learning_analyzer_started",
            video_id=data.video_id,
            title=data.title,
            topic=data.topic,
        )

        # Compute derived metrics
        velocity = self._compute_velocity(data)
        engagement_rate = self._compute_engagement_rate(data)
        like_rate = self._compute_like_rate(data)
        comment_rate = self._compute_comment_rate(data)

        # Score components
        ctr_score = self._score_ctr(data.ctr)
        retention_score = self._score_retention(data.average_view_percentage)
        engagement_score = self._score_engagement(engagement_rate, like_rate, comment_rate)
        velocity_score = self._score_velocity(velocity)

        # Composite success score (0-100)
        t = self._thresholds
        success_score = round(
            ctr_score * t.weight_ctr
            + retention_score * t.weight_retention
            + engagement_score * t.weight_engagement
            + velocity_score * t.weight_velocity,
            1,
        )

        # Extract insights
        strengths = self._extract_strengths(data, ctr_score, retention_score, engagement_score, velocity_score)
        weaknesses = self._extract_weaknesses(data, ctr_score, retention_score, engagement_score, velocity_score)
        recommendations = self._generate_recommendations(data, strengths, weaknesses)
        patterns = self._extract_patterns(data, strengths, weaknesses)

        # Confidence based on data completeness
        confidence = self._compute_confidence(data)

        result = LearningResult(
            video_id=data.video_id,
            success_score=min(max(success_score, 0.0), 100.0),
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            reusable_patterns=patterns,
            confidence=confidence,
            metadata={
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "velocity_per_day": velocity,
                "engagement_rate": engagement_rate,
                "like_rate": like_rate,
                "comment_rate": comment_rate,
                "ctr_score": ctr_score,
                "retention_score": retention_score,
                "engagement_score": engagement_score,
                "velocity_score": velocity_score,
                "thresholds_applied": {
                    "high_ctr": t.high_ctr,
                    "low_ctr": t.low_ctr,
                    "high_retention": t.high_retention,
                    "low_retention": t.low_retention,
                },
            },
        )

        logger.info(
            "learning_analyzer_complete",
            video_id=data.video_id,
            success_score=result.success_score,
            confidence=result.confidence,
            pattern_count=len(patterns),
        )

        return result

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    def _compute_velocity(self, data: AnalyticsInput) -> float:
        """Views per day since upload."""
        if not data.upload_date:
            return 0.0
        days_since_upload = max(
            (datetime.now(timezone.utc) - data.upload_date).days, 1
        )
        return round(data.views / days_since_upload, 2)

    def _compute_engagement_rate(self, data: AnalyticsInput) -> float:
        """Total engagements (likes + comments + shares) / views."""
        if data.views <= 0:
            return 0.0
        total = data.likes + data.comments + data.shares
        return round(total / data.views, 4)

    def _compute_like_rate(self, data: AnalyticsInput) -> float:
        if data.views <= 0:
            return 0.0
        return round(data.likes / data.views, 4)

    def _compute_comment_rate(self, data: AnalyticsInput) -> float:
        if data.views <= 0:
            return 0.0
        return round(data.comments / data.views, 4)

    # ------------------------------------------------------------------
    # Scoring (0-100 each)
    # ------------------------------------------------------------------

    def _score_ctr(self, ctr: float | None) -> float:
        if ctr is None:
            return 50.0  # neutral if unknown
        t = self._thresholds
        if ctr >= t.high_ctr:
            return 100.0
        if ctr <= t.low_ctr:
            return 0.0
        # Linear interpolation
        return 100.0 * (ctr - t.low_ctr) / (t.high_ctr - t.low_ctr)

    def _score_retention(self, retention: float | None) -> float:
        if retention is None:
            return 50.0
        t = self._thresholds
        if retention >= t.high_retention:
            return 100.0
        if retention <= t.low_retention:
            return 0.0
        return 100.0 * (retention - t.low_retention) / (t.high_retention - t.low_retention)

    def _score_engagement(
        self, engagement_rate: float, like_rate: float, comment_rate: float
    ) -> float:
        """Composite engagement score based on rate benchmarks."""
        t = self._thresholds
        like_score = min(100.0, (like_rate / t.high_like_rate) * 100.0) if t.high_like_rate > 0 else 50.0
        comment_score = min(100.0, (comment_rate / t.high_comment_rate) * 100.0) if t.high_comment_rate > 0 else 50.0
        return round((like_score * 0.6 + comment_score * 0.4), 1)

    def _score_velocity(self, velocity: float) -> float:
        t = self._thresholds
        if velocity >= t.high_velocity:
            return 100.0
        if velocity <= t.low_velocity:
            return 0.0
        return 100.0 * (velocity - t.low_velocity) / (t.high_velocity - t.low_velocity)

    # ------------------------------------------------------------------
    # Insight extraction
    # ------------------------------------------------------------------

    def _extract_strengths(
        self,
        data: AnalyticsInput,
        ctr_score: float,
        retention_score: float,
        engagement_score: float,
        velocity_score: float,
    ) -> list[str]:
        strengths = []
        if ctr_score >= 80:
            strengths.append(
                f"Strong click-through rate ({data.ctr:.1%}): thumbnail/title combination is effective"
            )
        if retention_score >= 80:
            strengths.append(
                f"High audience retention ({data.average_view_percentage:.0%}): content holds attention"
            )
        if engagement_score >= 80:
            strengths.append(
                f"Strong engagement: {data.likes} likes, {data.comments} comments"
            )
        if velocity_score >= 80:
            strengths.append(
                f"High view velocity: {self._compute_velocity(data)} views/day"
            )
        if data.subscribers_gained > 0:
            strengths.append(
                f"Audience growth: +{data.subscribers_gained} subscribers"
            )
        return strengths

    def _extract_weaknesses(
        self,
        data: AnalyticsInput,
        ctr_score: float,
        retention_score: float,
        engagement_score: float,
        velocity_score: float,
    ) -> list[str]:
        weaknesses = []
        if ctr_score <= 30:
            weaknesses.append(
                f"Low click-through rate ({data.ctr:.1%}): thumbnail or title needs improvement"
            )
        if retention_score <= 30:
            weaknesses.append(
                f"Poor audience retention ({data.average_view_percentage:.0%}): hook or pacing issues"
            )
        if engagement_score <= 30:
            weaknesses.append(
                f"Low engagement: {data.likes} likes, {data.comments} comments — consider stronger CTAs"
            )
        if velocity_score <= 30:
            weaknesses.append(
                f"Slow view accumulation: {self._compute_velocity(data)} views/day — topic may be too niche"
            )
        if data.audience_drop_off_notes:
            weaknesses.append(
                f"Audience drop-off: {data.audience_drop_off_notes}"
            )
        return weaknesses

    def _generate_recommendations(
        self, data: AnalyticsInput, strengths: list[str], weaknesses: list[str]
    ) -> list[str]:
        recommendations = []

        if any("click-through" in w.lower() for w in weaknesses):
            recommendations.append(
                "Test A/B thumbnails with high-contrast faces or bold text overlays"
            )
            recommendations.append(
                "Refine title to include curiosity gap or specific numbers"
            )

        if any("retention" in w.lower() for w in weaknesses):
            recommendations.append(
                "Front-load value: deliver the core promise within first 15 seconds"
            )
            recommendations.append(
                "Add pattern interrupts every 30 seconds to maintain attention"
            )

        if any("engagement" in w.lower() for w in weaknesses):
            recommendations.append(
                "Add explicit call-to-action: ask a question in the first 60 seconds"
            )
            recommendations.append(
                "Pin a comment to seed discussion"
            )

        if any("velocity" in w.lower() for w in weaknesses):
            recommendations.append(
                "Research trending topics in the same niche with higher search volume"
            )
            recommendations.append(
                "Consider cross-promotion on related community posts"
            )

        if strengths and not weaknesses:
            recommendations.append(
                "Double down: replicate this exact format/topic combination"
            )
            recommendations.append(
                "Create a sequel or follow-up while audience is warm"
            )

        return recommendations

    def _extract_patterns(
        self,
        data: AnalyticsInput,
        strengths: list[str],
        weaknesses: list[str],
    ) -> list[ReusablePattern]:
        """Extract reusable patterns from strengths/weaknesses."""
        patterns = []

        # Topic pattern
        if data.topic:
            if any("velocity" in s.lower() for s in strengths):
                patterns.append(
                    ReusablePattern(
                        category="topic",
                        pattern=f"Topic '{data.topic}' demonstrates strong audience demand",
                        evidence=f"{data.views} views at {self._compute_velocity(data)} views/day",
                        confidence=0.75 if data.views > 1000 else 0.55,
                        conditions=["same topic", "similar format"],
                    )
                )
            elif any("velocity" in w.lower() for w in weaknesses):
                patterns.append(
                    ReusablePattern(
                        category="topic",
                        pattern=f"Topic '{data.topic}' shows limited audience demand",
                        evidence=f"Only {data.views} views at {self._compute_velocity(data)} views/day",
                        confidence=0.70 if data.views < 100 else 0.50,
                        conditions=["avoid similar topics without differentiation"],
                    )
                )

        # Title pattern
        if data.title:
            if any("click-through" in s.lower() for s in strengths):
                patterns.append(
                    ReusablePattern(
                        category="title",
                        pattern=f"Title structure '{data.title}' drives high CTR",
                        evidence=f"CTR: {data.ctr:.1%}",
                        confidence=min(0.85, 0.5 + (data.ctr or 0)),
                        conditions=["similar emotional trigger", "comparable topic"],
                    )
                )

        # Thumbnail pattern
        if data.thumbnail_description:
            if any("click-through" in s.lower() for s in strengths):
                patterns.append(
                    ReusablePattern(
                        category="thumbnail",
                        pattern=f"Thumbnail style drives clicks: {data.thumbnail_description}",
                        evidence=f"CTR: {data.ctr:.1%}",
                        confidence=min(0.80, 0.5 + (data.ctr or 0)),
                        conditions=["same visual style", "similar subject"],
                    )
                )

        # Script pattern
        if data.script_summary:
            if any("retention" in s.lower() for s in strengths):
                patterns.append(
                    ReusablePattern(
                        category="script",
                        pattern=f"Script structure retains audience: {data.script_summary[:100]}",
                        evidence=f"Retention: {data.average_view_percentage:.0%}",
                        confidence=min(0.80, 0.5 + (data.average_view_percentage or 0)),
                        conditions=["similar pacing", "comparable hook structure"],
                    )
                )

        # Prompt pattern
        if data.prompt_text:
            if any("retention" in s.lower() for s in strengths) or any("engagement" in s.lower() for s in strengths):
                patterns.append(
                    ReusablePattern(
                        category="prompt",
                        pattern=f"Generation prompt produces engaging output: {data.prompt_text[:100]}",
                        evidence=f"Engagement rate: {self._compute_engagement_rate(data):.1%}",
                        confidence=0.65,
                        conditions=["same model", "similar parameters"],
                    )
                )

        return patterns

    def _compute_confidence(self, data: AnalyticsInput) -> float:
        """Confidence score based on data completeness (0.0-1.0)."""
        required_fields = [data.views, data.likes, data.title]
        optional_fields = [
            data.ctr,
            data.average_view_percentage,
            data.average_view_duration_seconds,
            data.comments,
            data.shares,
            data.subscribers_gained,
            data.retention,
        ]

        required_score = sum(1 for f in required_fields if f is not None and f != "") / len(required_fields)
        optional_score = sum(1 for f in optional_fields if f is not None) / len(optional_fields)

        return round(required_score * 0.6 + optional_score * 0.4, 2)
