"""
Maintenance job bodies. Each is a plain async function — no framework
coupling beyond what it needs — so they're also callable directly from
a script or a test without going through the scheduler.

These are stubs: the shape is right (log start/end via the Event Log,
touch the DB session correctly), but the real YouTube Analytics pulls,
cost rollups, and learning-loop math are Sprint 4+ work, same as the
provider adapters in app/providers/.
"""
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.events.log import EventType, log_event
from app.models.analytics import Analytics
from app.models.core import WorkflowRun
from app.models.learning import AnalyticsInput
from app.models.media import Video
from app.repositories.learning_repository import SqlAlchemyLearningRepository
from app.services.learning_analyzer import LearningAnalyzer

logger = get_logger(__name__)


async def collect_analytics() -> None:
    """Pull fresh YouTube Analytics snapshots for recently published
    videos and write Analytics rows. TODO(Sprint 4): call YouTube API."""
    await log_event(EventType.ANALYTICS_IMPORTED, "Scheduled analytics collection ran")
    logger.info("job_ran", job="collect_analytics")


async def aggregate_costs(
    db: AsyncSession | None = None,
) -> int:
    """Roll up ProviderUsageLog rows into WorkflowRun.total_cost_usd
    for any runs where cost has drifted.

    Returns:
        The count of WorkflowRun rows whose total_cost_usd was reconciled.
    """
    if db is not None:
        return await _execute_cost_aggregation(db)

    async with AsyncSessionLocal() as session:
        return await _execute_cost_aggregation(session)


async def _execute_cost_aggregation(session: AsyncSession) -> int:
    from decimal import Decimal
    from sqlalchemy import func
    from app.models.provider import ProviderUsageLog

    stmt = (
        select(
            ProviderUsageLog.workflow_run_id,
            func.coalesce(func.sum(ProviderUsageLog.cost_usd), 0).label("calculated_cost"),
        )
        .group_by(ProviderUsageLog.workflow_run_id)
    )
    result = await session.execute(stmt)
    cost_map = {row.workflow_run_id: Decimal(str(round(row.calculated_cost, 4))) for row in result}

    if not cost_map:
        logger.info("aggregate_costs_completed", updated_runs=0)
        return 0

    runs_stmt = select(WorkflowRun).where(WorkflowRun.id.in_(list(cost_map.keys())))
    runs_res = await session.execute(runs_stmt)
    runs = runs_res.scalars().all()

    updated_count = 0
    for run in runs:
        calc_cost = cost_map.get(run.id, Decimal("0.0000"))
        current_cost = Decimal(str(round(run.total_cost_usd or 0, 4)))
        if current_cost != calc_cost:
            logger.info(
                "reconciling_workflow_run_cost",
                run_id=str(run.id),
                previous_cost=str(current_cost),
                reconciled_cost=str(calc_cost),
            )
            run.total_cost_usd = calc_cost
            updated_count += 1

    if updated_count > 0:
        await session.commit()

    logger.info("aggregate_costs_completed", updated_runs=updated_count)
    return updated_count



async def run_learning_update(
    db: AsyncSession | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Re-derive PerformanceLearningFeedback from recent Analytics.

    Processes recent Analytics records, evaluates performance via LearningAnalyzer,
    and stores reusable feedback patterns into PerformanceLearningFeedback via
    SqlAlchemyLearningRepository.
    """
    if db is not None:
        return await _execute_learning_update(db, limit=limit)

    async with AsyncSessionLocal() as session:
        return await _execute_learning_update(session, limit=limit)


async def _execute_learning_update(
    session: AsyncSession,
    limit: int = 100,
) -> dict[str, int]:
    stats = {
        "records_examined": 0,
        "records_analyzed": 0,
        "feedback_generated": 0,
        "feedback_persisted": 0,
        "records_skipped": 0,
        "errors": 0,
    }

    try:
        stmt = select(Analytics).order_by(Analytics.snapshot_at.desc()).limit(limit)
        res = await session.execute(stmt)
        records = list(res.scalars().all())
    except Exception as exc:
        stats["errors"] += 1
        logger.error("learning_update_query_failed", error=str(exc))
        return stats

    stats["records_examined"] = len(records)
    if not records:
        logger.info("learning_update_completed", **stats)
        await log_event(
            EventType.LEARNING_UPDATED,
            "Scheduled learning update ran: 0 records examined",
        )
        return stats

    # Batch pre-fetch associated Video and WorkflowRun records to avoid N+1 queries
    video_ids = {r.video_id for r in records if r.video_id is not None}
    videos_by_id = {}
    if video_ids:
        try:
            v_res = await session.execute(select(Video).where(Video.id.in_(video_ids)))
            for v in v_res.scalars().all():
                videos_by_id[v.id] = v
        except Exception as exc:
            logger.warning("learning_update_video_prefetch_failed", error=str(exc))

    run_ids = {r.workflow_run_id for r in records if r.workflow_run_id is not None}
    for v in videos_by_id.values():
        if v.workflow_run_id is not None:
            run_ids.add(v.workflow_run_id)

    runs_by_id = {}
    if run_ids:
        try:
            r_res = await session.execute(
                select(WorkflowRun).where(WorkflowRun.id.in_(run_ids))
            )
            for r in r_res.scalars().all():
                runs_by_id[r.id] = r
        except Exception as exc:
            logger.warning("learning_update_run_prefetch_failed", error=str(exc))

    analyzer = LearningAnalyzer()
    repo = SqlAlchemyLearningRepository(session)
    seen_targets: set[str] = set()

    for record in records:
        try:
            # Deduplicate multiple snapshots for the same target in a single run:
            # Keep only the freshest snapshot (since records are sorted DESC by snapshot_at)
            target_key = str(
                record.video_id
                or record.workflow_run_id
                or record.external_post_id
                or record.id
            )
            if target_key in seen_targets:
                stats["records_skipped"] += 1
                continue
            seen_targets.add(target_key)

            raw_meta = {}
            if record.raw_metadata:
                try:
                    raw_meta = json.loads(record.raw_metadata)
                except Exception:
                    raw_meta = {}

            video_obj = videos_by_id.get(record.video_id)
            run_obj = runs_by_id.get(record.workflow_run_id)
            if not run_obj and video_obj and video_obj.workflow_run_id:
                run_obj = runs_by_id.get(video_obj.workflow_run_id)

            title = (
                (video_obj.title if video_obj and video_obj.title else None)
                or raw_meta.get("title")
                or (run_obj.topic if run_obj and run_obj.topic else None)
                or (
                    f"Post {record.external_post_id}"
                    if record.external_post_id
                    else f"Video {record.video_id or record.id}"
                )
            )

            topic = (
                (run_obj.topic if run_obj and run_obj.topic else None)
                or raw_meta.get("topic")
                or (video_obj.title if video_obj else None)
            )

            upload_dt = None
            if record.snapshot_at:
                upload_dt = record.snapshot_at
            elif video_obj and video_obj.created_at:
                upload_dt = video_obj.created_at

            # Ensure upload_date has timezone info for LearningAnalyzer's datetime subtraction
            if upload_dt is not None and upload_dt.tzinfo is None:
                upload_dt = upload_dt.replace(tzinfo=timezone.utc)

            analytics_input = AnalyticsInput(
                video_id=target_key,
                title=str(title),
                topic=str(topic) if topic else None,
                views=int(record.views or 0),
                impressions=raw_meta.get("impressions") or raw_meta.get("impression_count"),
                ctr=float(record.click_through_rate)
                if record.click_through_rate is not None
                else None,
                watch_time_seconds=float(record.watch_time_seconds)
                if record.watch_time_seconds is not None
                else None,
                average_view_duration_seconds=record.average_view_duration_seconds,
                average_view_percentage=float(record.average_view_percentage)
                if record.average_view_percentage is not None
                else None,
                retention=raw_meta.get("retention"),
                likes=int(record.likes or 0),
                comments=int(record.comments or 0),
                shares=int(record.shares or 0),
                subscribers_gained=int(record.subscribers_gained or 0),
                upload_date=upload_dt,
                audience_drop_off_notes=record.audience_drop_off_notes,
                thumbnail_description=raw_meta.get("thumbnail_description"),
                script_summary=raw_meta.get("script_summary")
                or (video_obj.description if video_obj else None),
                prompt_text=raw_meta.get("prompt_text"),
            )

            result = analyzer.analyze(analytics_input)
            stats["records_analyzed"] += 1

            feedback_rows = result.to_feedback_rows()
            stats["feedback_generated"] += len(feedback_rows)

            for row in feedback_rows:
                try:
                    await repo.save_feedback(
                        video_id=analytics_input.video_id,
                        category=row["category"],
                        insight=row["insight"],
                        confidence=row["confidence"],
                        based_on_video_count=row.get("based_on_video_count", 1),
                    )
                    stats["feedback_persisted"] += 1
                except Exception as row_exc:
                    stats["errors"] += 1
                    await session.rollback()
                    logger.warning(
                        "learning_feedback_save_failed",
                        video_id=analytics_input.video_id,
                        category=row.get("category"),
                        error=str(row_exc),
                    )

        except Exception as rec_exc:
            stats["errors"] += 1
            logger.warning(
                "learning_record_processing_failed",
                record_id=str(record.id) if hasattr(record, "id") else "unknown",
                error=str(rec_exc),
            )

    logger.info("learning_update_completed", **stats)
    await log_event(
        EventType.LEARNING_UPDATED,
        f"Scheduled learning update ran: {stats['records_analyzed']} analyzed, {stats['feedback_persisted']} feedback persisted",
    )
    return stats


async def cleanup_temp_files() -> Any:
    """Remove orphaned local temp files (rejected draft artifacts past
    a retention window). Phase 3.2.4.4.6.3.3.12 implementation (MED-04)."""
    from app.services.artifact_retention_service import get_artifact_retention_service

    service = get_artifact_retention_service()
    report = await service.run_retention_sweep()
    logger.info(
        "job_ran",
        job="cleanup_temp_files",
        dry_run=report.dry_run,
        enabled=report.enabled,
        total_scanned=report.total_files_scanned,
        evaluated=report.total_candidates_evaluated,
        pruned=report.pruned_count,
        retained=report.retained_count,
    )
    return report


async def sweep_expired_leases(db: AsyncSession | None = None) -> Any:
    """Identify and safely recover expired action leases.
    Phase 3.2.4.4.6.3.3.14 implementation (Task A)."""
    from app.services.lease_expiry_sweeper import get_lease_expiry_sweeper_service

    service = get_lease_expiry_sweeper_service()
    report = await service.run_sweep(session=db)
    logger.info(
        "job_ran",
        job="sweep_expired_leases",
        total_checked=report.total_checked,
        expired_found=report.expired_found,
        transitioned_unknown=report.transitioned_unknown,
        transitioned_ready=report.transitioned_ready,
        skipped_active=report.skipped_active,
        status=report.status,
    )
    return report
