"""Learning Repository — persistence layer for learning feedback.

Provides an abstract base for pluggable backends and a concrete
SQLAlchemy implementation for PostgreSQL/SQLite. Future backends
(e.g., vector databases for semantic similarity search) can be added
without changing callers.

Design decisions:
- Repository ABC defines the contract.
- SqlAlchemyLearningRepository is the production implementation.
- All methods are async (I/O bound).
- Uses the existing PerformanceLearningFeedback model
  (app/models/analytics.py) — no new database tables.
- Merge logic: if an equivalent insight already exists, increment
  based_on_video_count instead of creating a duplicate row.
"""
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.analytics import PerformanceLearningFeedback

logger = get_logger(__name__)


class LearningRepository(ABC):
    """Abstract base for learning feedback persistence."""

    @abstractmethod
    async def save_feedback(
        self,
        *,
        video_id: str,
        category: str,
        insight: str,
        confidence: float,
        based_on_video_count: int = 1,
    ) -> PerformanceLearningFeedback:
        """Save or update a learning insight.

        If an equivalent insight (same category + similar text)
        already exists, increment based_on_video_count and update
        confidence. Otherwise create a new row.

        Returns:
            The saved or updated PerformanceLearningFeedback row.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_active_feedback(
        self,
        *,
        category: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[PerformanceLearningFeedback]:
        """Retrieve active learning insights.

        Args:
            category: Filter by category ("topic", "script", etc.).
                If None, returns all categories.
            min_confidence: Minimum confidence threshold.
            limit: Maximum rows to return.

        Returns:
            List of active PerformanceLearningFeedback rows.
        """
        raise NotImplementedError

    @abstractmethod
    async def deactivate_feedback(self, feedback_id: str) -> bool:
        """Deactivate (soft-delete) a learning insight.

        Args:
            feedback_id: The UUID of the insight to deactivate.

        Returns:
            True if found and deactivated, False if not found.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_feedback_for_video(
        self, video_id: str
    ) -> list[PerformanceLearningFeedback]:
        """Retrieve all feedback associated with a specific video.

        Note: The PerformanceLearningFeedback model does not have a
        direct video_id FK. This method uses a heuristic: it looks
        for insights created around the time the video was published
        and with based_on_video_count == 1 (first observation).

        For a more precise link, a junction table would be needed.
        This is a pragmatic implementation for the current schema.
        """
        raise NotImplementedError


class SqlAlchemyLearningRepository(LearningRepository):
    """SQLAlchemy implementation of LearningRepository.

    Uses the existing PerformanceLearningFeedback table
    (app/models/analytics.py).
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def save_feedback(
        self,
        *,
        video_id: str,
        category: str,
        insight: str,
        confidence: float,
        based_on_video_count: int = 1,
    ) -> PerformanceLearningFeedback:
        """Save or merge a learning insight.

        Merge heuristic: if an active insight with the same category
        and identical insight text exists, increment
        based_on_video_count and update confidence to the average.
        Otherwise create a new row.
        """
        # Look for an exact match
        result = await self._db.execute(
            select(PerformanceLearningFeedback)
            .where(
                PerformanceLearningFeedback.is_active.is_(True),
                PerformanceLearningFeedback.category == category,
                PerformanceLearningFeedback.insight == insight,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Merge: increment count, update confidence (weighted average)
            old_count = existing.based_on_video_count
            new_count = old_count + based_on_video_count
            existing.based_on_video_count = new_count
            existing.confidence = round(
                (existing.confidence * old_count + confidence * based_on_video_count)
                / new_count,
                3,
            )
            await self._db.commit()
            await self._db.refresh(existing)
            logger.info(
                "learning_feedback_merged",
                feedback_id=str(existing.id),
                category=category,
                new_count=new_count,
                new_confidence=existing.confidence,
            )
            return existing

        # Create new
        feedback = PerformanceLearningFeedback(
            category=category,
            insight=insight,
            confidence=confidence,
            based_on_video_count=based_on_video_count,
            is_active=True,
        )
        self._db.add(feedback)
        await self._db.commit()
        await self._db.refresh(feedback)
        logger.info(
            "learning_feedback_created",
            feedback_id=str(feedback.id),
            category=category,
            confidence=confidence,
        )
        return feedback

    async def get_active_feedback(
        self,
        *,
        category: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[PerformanceLearningFeedback]:
        """Retrieve active learning insights."""
        query = (
            select(PerformanceLearningFeedback)
            .where(
                PerformanceLearningFeedback.is_active.is_(True),
                PerformanceLearningFeedback.confidence >= min_confidence,
            )
            .order_by(PerformanceLearningFeedback.confidence.desc())
            .limit(limit)
        )

        if category:
            query = query.where(
                PerformanceLearningFeedback.category == category
            )

        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def deactivate_feedback(self, feedback_id: str) -> bool:
        """Soft-delete a learning insight."""
        result = await self._db.execute(
            select(PerformanceLearningFeedback).where(
                PerformanceLearningFeedback.id == feedback_id
            )
        )
        feedback = result.scalar_one_or_none()
        if not feedback:
            return False

        feedback.is_active = False
        await self._db.commit()
        logger.info("learning_feedback_deactivated", feedback_id=feedback_id)
        return True

    async def get_feedback_for_video(
        self, video_id: str
    ) -> list[PerformanceLearningFeedback]:
        """Best-effort retrieval of feedback for a specific video.

        Since PerformanceLearningFeedback has no video_id FK, this
        returns recently created feedback with based_on_video_count==1
        as a heuristic. For precise tracking, add a junction table.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await self._db.execute(
            select(PerformanceLearningFeedback)
            .where(
                PerformanceLearningFeedback.is_active.is_(True),
                PerformanceLearningFeedback.based_on_video_count == 1,
                PerformanceLearningFeedback.created_at >= cutoff,
            )
            .order_by(PerformanceLearningFeedback.created_at.desc())
            .limit(20)
        )
        return list(result.scalars().all())
