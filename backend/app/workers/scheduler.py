"""
Background Job Scheduler — internal maintenance only.

Beginner note: this is APScheduler running INSIDE the FastAPI process,
not a second orchestrator. n8n still owns the pipeline (trend -> script
-> ... -> publish). This scheduler exists for the handful of jobs that
aren't part of any single video's pipeline run: pulling analytics on a
timer, rolling up cost totals, running the learning-loop update,
sweeping old temp files. If a job needs to trigger pipeline logic
(agents, validators, approvals), it belongs in n8n — not here.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.workers import jobs

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.enable_background_scheduler:
        logger.info("scheduler_disabled")
        return

    scheduler = get_scheduler()
    # Add jobs here as they're implemented in app/workers/jobs.py.
    # Intervals are conservative defaults — tune via config, not code.
    scheduler.add_job(jobs.collect_analytics, "interval", hours=6, id="collect_analytics", replace_existing=True)
    scheduler.add_job(jobs.aggregate_costs, "interval", hours=1, id="aggregate_costs", replace_existing=True)
    scheduler.add_job(jobs.run_learning_update, "interval", hours=24, id="run_learning_update", replace_existing=True)
    scheduler.add_job(jobs.cleanup_temp_files, "interval", hours=12, id="cleanup_temp_files", replace_existing=True)
    scheduler.start()
    logger.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
