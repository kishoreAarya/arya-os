"""
Maintenance job bodies. Each is a plain async function — no framework
coupling beyond what it needs — so they're also callable directly from
a script or a test without going through the scheduler.

These are stubs: the shape is right (log start/end via the Event Log,
touch the DB session correctly), but the real YouTube Analytics pulls,
cost rollups, and learning-loop math are Sprint 4+ work, same as the
provider adapters in app/providers/.
"""
from app.core.logging import get_logger
from app.events.log import EventType, log_event

logger = get_logger(__name__)


async def collect_analytics() -> None:
    """Pull fresh YouTube Analytics snapshots for recently published
    videos and write Analytics rows. TODO(Sprint 4): call YouTube API."""
    await log_event(EventType.ANALYTICS_IMPORTED, "Scheduled analytics collection ran")
    logger.info("job_ran", job="collect_analytics")


async def aggregate_costs() -> None:
    """Roll up ProviderUsageLog rows into WorkflowRun.total_cost_usd
    for any runs where it's drifted. TODO(Sprint 4): implement rollup query."""
    logger.info("job_ran", job="aggregate_costs")


async def run_learning_update() -> None:
    """Re-derive PerformanceLearningFeedback from recent Analytics.
    TODO(Sprint 4+): implement the actual learning-loop logic."""
    await log_event(EventType.LEARNING_UPDATED, "Scheduled learning update ran")
    logger.info("job_ran", job="run_learning_update")


async def cleanup_temp_files() -> None:
    """Remove orphaned local temp files (rejected draft artifacts past
    a retention window). TODO(Sprint 4): implement retention policy."""
    logger.info("job_ran", job="cleanup_temp_files")
