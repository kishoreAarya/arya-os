"""Ranking and blending engine combining live trend signals with PerformanceLearningFeedback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.trend_sources.base import TrendSignal

if TYPE_CHECKING:
    from app.models.analytics import PerformanceLearningFeedback

logger = get_logger("arya.trend_sources.ranker")

_POSITIVE_INDICATORS = {
    "high", "higher", "top", "best", "increase", "boost", "strong",
    "retention", "ctr", "popular", "great", "engaged", "growth", "works"
}
_NEGATIVE_INDICATORS = {
    "avoid", "low", "lower", "poor", "weak", "drop", "drop-off",
    "decline", "fall", "bad", "decrease", "unpopular"
}


def rank_trend_signals(
    signals: list[TrendSignal],
    feedback: list[PerformanceLearningFeedback] | None = None,
    topic_hint: str = "",
) -> list[TrendSignal]:
    """Rank and adjust trend signals based on past channel performance learning.

    Combines:
    - Base keyword relevance (0-50 pts)
    - Signal statistical confidence (0-30 pts)
    - Competition opportunity modifier (0-10 pts)
    - Historical PerformanceLearningFeedback boost/penalty (+/- 15 pts per match)
    """
    if not signals:
        return []

    active_feedback = [f for f in (feedback or []) if getattr(f, "is_active", True)]

    ranked: list[TrendSignal] = []
    for sig in signals:
        # Base score from relevance and confidence
        score = (float(sig.relevance) * 50.0) + (float(sig.confidence) * 30.0)

        # Competition bonus: low competition presents higher opportunity
        comp = (sig.competition or "").lower()
        if comp == "low":
            score += 10.0
        elif comp == "medium":
            score += 5.0

        applied_insights: list[str] = []

        # Check against channel learning feedback
        sig_text = f"{sig.topic} {sig.metadata.get("snippet", "")} {sig.metadata.get("channel", "")}".lower()
        sig_words = set(re.findall(r"\w+", sig_text))

        for fb in active_feedback:
            insight_text = fb.insight.lower()
            insight_words = set(re.findall(r"\w+", insight_text))

            overlap = sig_words.intersection(insight_words)
            # Remove very common words from overlap consideration
            meaningful_overlap = {w for w in overlap if len(w) > 3 and w not in {"with", "that", "this", "from", "have"}}

            conf = float(fb.confidence or 0.7)

            if meaningful_overlap:
                has_negative = any(neg in insight_words for neg in _NEGATIVE_INDICATORS)
                has_positive = any(pos in insight_words for pos in _POSITIVE_INDICATORS)

                if has_negative and not has_positive:
                    penalty = conf * 15.0
                    score -= penalty
                    applied_insights.append(f"Penalty: {fb.insight}")
                else:
                    boost = conf * 15.0
                    score += boost
                    sig.relevance = min(1.0, sig.relevance + 0.05)
                    sig.confidence = min(1.0, sig.confidence + 0.05)
                    applied_insights.append(f"Boost: {fb.insight}")

        sig.opportunity_score = round(max(0.0, min(100.0, score)), 2)
        if applied_insights:
            sig.metadata["learning_feedback_applied"] = applied_insights

        ranked.append(sig)

    # Sort descending by opportunity_score, then confidence, then relevance
    ranked.sort(
        key=lambda s: (
            s.opportunity_score if s.opportunity_score is not None else 0.0,
            s.confidence,
            s.relevance,
        ),
        reverse=True,
    )

    return ranked
