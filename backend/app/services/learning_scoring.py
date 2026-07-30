"""LearningScoring — pure scoring and threshold logic.

Extracted from LearningAnalyzer for independent reuse and testing.
This module contains ONLY deterministic, stateless scoring functions.
No database access, no async I/O, no external calls.

Usage:
    from app.services.learning_scoring import score_ctr, score_retention
    ctr_score = score_ctr(0.075, high_threshold=0.08, low_threshold=0.03)
"""


def score_ctr(
    ctr: float | None,
    *,
    high_threshold: float = 0.08,
    low_threshold: float = 0.03,
) -> float:
    """Score click-through rate on a 0-100 scale.

    Args:
        ctr: Click-through rate (0.0-1.0) or None.
        high_threshold: CTR considered excellent (default 8%).
        low_threshold: CTR considered poor (default 3%).

    Returns:
        Score from 0.0 to 100.0.
    """
    if ctr is None:
        return 50.0
    if ctr >= high_threshold:
        return 100.0
    if ctr <= low_threshold:
        return 0.0
    return 100.0 * (ctr - low_threshold) / (high_threshold - low_threshold)


def score_retention(
    retention: float | None,
    *,
    high_threshold: float = 0.50,
    low_threshold: float = 0.20,
) -> float:
    """Score audience retention on a 0-100 scale.

    Args:
        retention: Average view percentage (0.0-1.0) or None.
        high_threshold: Retention considered excellent (default 50%).
        low_threshold: Retention considered poor (default 20%).

    Returns:
        Score from 0.0 to 100.0.
    """
    if retention is None:
        return 50.0
    if retention >= high_threshold:
        return 100.0
    if retention <= low_threshold:
        return 0.0
    return 100.0 * (retention - low_threshold) / (high_threshold - low_threshold)


def score_engagement(
    like_rate: float,
    comment_rate: float,
    *,
    high_like_rate: float = 0.05,
    high_comment_rate: float = 0.01,
) -> float:
    """Score engagement on a 0-100 scale.

    Args:
        like_rate: Likes / views.
        comment_rate: Comments / views.
        high_like_rate: Like rate considered excellent (default 5%).
        high_comment_rate: Comment rate considered excellent (default 1%).

    Returns:
        Score from 0.0 to 100.0.
    """
    like_score = (
        min(100.0, (like_rate / high_like_rate) * 100.0)
        if high_like_rate > 0
        else 50.0
    )
    comment_score = (
        min(100.0, (comment_rate / high_comment_rate) * 100.0)
        if high_comment_rate > 0
        else 50.0
    )
    return round(like_score * 0.6 + comment_score * 0.4, 1)


def score_velocity(
    velocity: float,
    *,
    high_threshold: float = 1000.0,
    low_threshold: float = 50.0,
) -> float:
    """Score view velocity on a 0-100 scale.

    Args:
        velocity: Views per day.
        high_threshold: Velocity considered excellent (default 1000/day).
        low_threshold: Velocity considered poor (default 50/day).

    Returns:
        Score from 0.0 to 100.0.
    """
    if velocity >= high_threshold:
        return 100.0
    if velocity <= low_threshold:
        return 0.0
    return 100.0 * (velocity - low_threshold) / (high_threshold - low_threshold)


def compute_composite_score(
    ctr_score: float,
    retention_score: float,
    engagement_score: float,
    velocity_score: float,
    *,
    weight_ctr: float = 0.25,
    weight_retention: float = 0.30,
    weight_engagement: float = 0.25,
    weight_velocity: float = 0.20,
) -> float:
    """Compute weighted composite success score.

    Args:
        ctr_score: 0-100 score for CTR.
        retention_score: 0-100 score for retention.
        engagement_score: 0-100 score for engagement.
        velocity_score: 0-100 score for velocity.
        weight_ctr: Weight for CTR (default 25%).
        weight_retention: Weight for retention (default 30%).
        weight_engagement: Weight for engagement (default 25%).
        weight_velocity: Weight for velocity (default 20%).

    Returns:
        Composite score from 0.0 to 100.0.
    """
    total_weight = weight_ctr + weight_retention + weight_engagement + weight_velocity
    if total_weight == 0:
        return 0.0
    score = (
        ctr_score * weight_ctr
        + retention_score * weight_retention
        + engagement_score * weight_engagement
        + velocity_score * weight_velocity
    ) / total_weight
    return round(min(max(score, 0.0), 100.0), 1)


def compute_confidence(
    *,
    has_views: bool = False,
    has_likes: bool = False,
    has_title: bool = False,
    has_ctr: bool = False,
    has_retention: bool = False,
    has_duration: bool = False,
    has_comments: bool = False,
    has_shares: bool = False,
    has_subscribers: bool = False,
    has_retention_curve: bool = False,
) -> float:
    """Compute data completeness confidence score.

    Required fields (60% weight): views, likes, title.
    Optional fields (40% weight): ctr, retention, duration, comments,
                                   shares, subscribers, retention_curve.

    Returns:
        Confidence from 0.0 to 1.0.
    """
    required = [has_views, has_likes, has_title]
    optional = [
        has_ctr,
        has_retention,
        has_duration,
        has_comments,
        has_shares,
        has_subscribers,
        has_retention_curve,
    ]

    required_score = sum(1 for r in required if r) / len(required)
    optional_score = sum(1 for o in optional if o) / len(optional)

    return round(required_score * 0.6 + optional_score * 0.4, 2)


def classify_performance(
    score: float,
    *,
    excellent_threshold: float = 80.0,
    good_threshold: float = 60.0,
    poor_threshold: float = 30.0,
) -> str:
    """Classify a composite score into performance tier.

    Returns:
        "excellent", "good", "average", or "poor".
    """
    if score >= excellent_threshold:
        return "excellent"
    if score >= good_threshold:
        return "good"
    if score >= poor_threshold:
        return "average"
    return "poor"
