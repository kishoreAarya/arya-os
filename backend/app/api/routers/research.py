"""Research and trend discovery API router for Arya OS V1.

Exposes normalized research signals across Reddit discussions, YouTube Data API,
and Google Trends with structured metadata and provenance persistence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.session import get_db
from app.models.system import SystemLog
from app.services.trend_sources.reddit import RedditTrendSource
from app.services.trend_sources.service import TrendDiscoveryService

logger = get_logger("arya.api.research")

router = APIRouter(prefix="/research", tags=["research"])

_SHARED_REDDIT_SOURCE = RedditTrendSource()
_SHARED_DISCOVERY_SERVICE = TrendDiscoveryService()


class RedditResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(default=None, description="Topic or keyword to search")
    subreddit: str | None = Field(default=None, description="Optional target subreddit")
    time_range: str = Field(default="all", description="Time filter: hour, day, week, month, year, all")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return (1-50)")
    workflow_run_id: uuid.UUID | None = Field(default=None, description="Optional WorkflowRun UUID to bind persistence")


class ResearchSignalItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str
    search_volume_or_signal: str
    relevance: float
    freshness: str
    competition: str | None = None
    source: str
    timestamp: str
    confidence: float
    opportunity_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchResponse(BaseModel):
    source: str
    query: dict[str, Any]
    total_results: int
    retrieved_at: str
    results: list[ResearchSignalItem]


@router.get("/reddit", response_model=ResearchResponse)
async def get_reddit_research(
    topic: str | None = Query(default=None, description="Topic or keyword to search"),
    subreddit: str | None = Query(default=None, description="Optional target subreddit"),
    time_range: str = Query(default="all", description="Time filter: hour, day, week, month, year, all"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results to return"),
    workflow_run_id: uuid.UUID | None = Query(default=None, description="Optional WorkflowRun ID"),
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Query Reddit discussions for research signals with topic and/or subreddit filter."""
    clean_topic = (topic or "").strip()
    clean_sub = (subreddit or "").strip().lstrip("r/").lstrip("/") or None

    if not clean_topic and not clean_sub:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one of 'topic' or 'subreddit' must be provided",
        )

    signals = await _SHARED_REDDIT_SOURCE.fetch_trends(
        topic_hint=clean_topic,
        limit=limit,
        subreddit=clean_sub,
        time_filter=time_range,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    raw_signals = [s.to_dict() for s in signals]

    # Persist research discovery provenance when workflow_run_id is attached
    if workflow_run_id is not None:
        try:
            from app.models.core import WorkflowRun
            db_run = await db.get(WorkflowRun, workflow_run_id)
            if db_run:
                db_log = SystemLog(
                    workflow_run_id=workflow_run_id,
                    event_type="RedditResearchDiscovered",
                    message=json.dumps(
                        {
                            "source": "reddit",
                            "topic": clean_topic,
                            "subreddit": clean_sub,
                            "time_range": time_range,
                            "signal_count": len(raw_signals),
                            "signals": raw_signals[:5],
                        }
                    ),
                    level="info",
                )
                db.add(db_log)
                await db.commit()
        except Exception as exc:
            logger.warning("reddit_research_persist_failed", error=str(exc))

    return ResearchResponse(
        source="reddit",
        query={
            "topic": clean_topic,
            "subreddit": clean_sub,
            "time_range": time_range,
            "limit": limit,
        },
        total_results=len(raw_signals),
        retrieved_at=now_iso,
        results=[ResearchSignalItem(**s) for s in raw_signals],
    )


@router.post("/reddit", response_model=ResearchResponse)
async def post_reddit_research(
    payload: RedditResearchRequest,
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Submit a structured Reddit research request with optional workflow persistence."""
    return await get_reddit_research(
        topic=payload.topic,
        subreddit=payload.subreddit,
        time_range=payload.time_range,
        limit=payload.limit,
        workflow_run_id=payload.workflow_run_id,
        db=db,
    )


@router.get("/trends", response_model=ResearchResponse)
async def get_multi_source_trends(
    topic: str = Query(..., min_length=1, description="Topic to discover trends for"),
    subreddit: str | None = Query(default=None, description="Optional target subreddit for Reddit signals"),
    time_range: str = Query(default="all", description="Time filter for time-sensitive sources"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results to return"),
    workflow_run_id: uuid.UUID | None = Query(default=None, description="Optional WorkflowRun ID"),
    db: AsyncSession = Depends(get_db),
) -> ResearchResponse:
    """Discover, rank, and blend signals across YouTube, Google Trends, and Reddit."""
    signals = await _SHARED_DISCOVERY_SERVICE.discover_trends(
        topic_hint=topic.strip(),
        limit=limit,
        subreddit=subreddit,
        time_filter=time_range,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    raw_signals = [s.to_dict() for s in signals]

    if workflow_run_id is not None:
        try:
            from app.models.core import WorkflowRun
            db_run = await db.get(WorkflowRun, workflow_run_id)
            if db_run:
                db_log = SystemLog(
                    workflow_run_id=workflow_run_id,
                    event_type="MultiSourceTrendsDiscovered",
                    message=json.dumps(
                        {
                            "topic": topic.strip(),
                            "count": len(raw_signals),
                            "sources": list({s.get("source") for s in raw_signals}),
                        }
                    ),
                    level="info",
                )
                db.add(db_log)
                await db.commit()
        except Exception as exc:
            logger.warning("trend_research_persist_failed", error=str(exc))

    return ResearchResponse(
        source="multi_source",
        query={
            "topic": topic.strip(),
            "subreddit": subreddit,
            "time_range": time_range,
            "limit": limit,
        },
        total_results=len(raw_signals),
        retrieved_at=now_iso,
        results=[ResearchSignalItem(**s) for s in raw_signals],
    )
