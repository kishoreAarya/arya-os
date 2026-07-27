"""
Central Event Log.

Beginner note: `SystemLog` (app/models/system.py) already IS the event
log table — Sprint 2 built it. What was missing was one shared place
that (a) names the event types so they can't typo-drift ("Retry" vs
"retry_triggered" vs "RETRIED") and (b) writes rows without every
caller re-deriving its own AsyncSession. This file is that place. It's
the debugging timeline for every video: filter system_logs by
workflow_run_id, get everything that happened, in order.
"""
import enum
import json
import uuid

from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.models.system import SystemLog

logger = get_logger(__name__)


class EventType(str, enum.Enum):
    WORKFLOW_STARTED = "workflow_started"
    STAGE_ADVANCED = "stage_advanced"
    PROVIDER_CALLED = "provider_called"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_PASSED = "validation_passed"
    RETRY_TRIGGERED = "retry_triggered"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    PUBLISHING_STARTED = "publishing_started"
    PUBLISHING_COMPLETED = "publishing_completed"
    PUBLISHING_FAILED = "publishing_failed"
    ANALYTICS_IMPORTED = "analytics_imported"
    LEARNING_UPDATED = "learning_updated"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    PIPELINE_RESUMED = "pipeline_resumed"


async def log_event(
    event_type: EventType,
    message: str,
    *,
    workflow_run_id: str | uuid.UUID | None = None,
    level: str = "info",
    metadata: dict | None = None,
) -> None:
    """Fire-and-forget event write. Never raises — a logging failure
    must never take down the pipeline step that triggered it."""
    full_message = message
    if metadata:
        try:
            full_message = f"{message} | {json.dumps(metadata, default=str)}"
        except TypeError:
            full_message = message

    try:
        async with AsyncSessionLocal() as session:
            entry = SystemLog(
                workflow_run_id=uuid.UUID(str(workflow_run_id)) if workflow_run_id else None,
                event_type=event_type.value,
                message=full_message,
                level=level,
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — logging must never break the caller
        logger.error("event_log_write_failed", event_type=event_type.value, error=str(exc))
