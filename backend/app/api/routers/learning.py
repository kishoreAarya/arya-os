"""
Arya OS V1 — Learning Feedback Router.

Provides authenticated read-only access to reusable performance insights
derived from published content analytics.
- GET /learning/feedback: Retrieve active learning feedback patterns.

MULTI-TENANCY LEARNING SCOPE REMAINS AN ARCHITECTURAL GAP:
PerformanceLearningFeedback currently has global scope across the instance.
No project-specific scoping column exists in the database schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.learning_repository import SqlAlchemyLearningRepository

router = APIRouter(prefix="/learning", tags=["learning"])


class LearningFeedbackResponse(BaseModel):
    id: uuid.UUID
    category: str
    insight: str
    confidence: float | None = None
    based_on_video_count: int = 1
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/feedback", response_model=list[LearningFeedbackResponse])
async def get_learning_feedback_endpoint(
    category: str | None = Query(
        default=None,
        description="Filter by feedback category ('topic', 'script', 'thumbnail', 'prompt', 'title')",
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold between 0.0 and 1.0",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Max feedback items to return (1-100)",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[LearningFeedbackResponse]:
    """Retrieve active learning feedback patterns for prompt and trend optimization."""
    repo = SqlAlchemyLearningRepository(db)
    items = await repo.get_active_feedback(
        category=category,
        min_confidence=min_confidence,
        limit=limit,
    )
    return [LearningFeedbackResponse.model_validate(item) for item in items]
