"""Shared stage execution utilities for Arya OS workflows."""

from __future__ import annotations

import dataclasses
import inspect
import time
from datetime import datetime, timezone
from typing import Any

from app.agents.base import AgentResult
from app.agents.registry import AGENT_REGISTRY
from app.core.logging import get_logger
from app.workflows.models import StageResult

logger = get_logger("arya.workflows.stage_executor")


async def execute_stage(
    stage_key: str,
    context: dict[str, Any],
    db: Any,
    max_retries: int = 3,
) -> StageResult:
    """Execute a single stage through the agent registry with retry logic.

    Looks up the agent in AGENT_REGISTRY, instantiates it (injecting the
    DB session when required), runs it, and returns a fully-populated
    StageResult.  This is the single execution path shared by
    Orchestrator and ShotExecutor.
    """
    stage_start = time.perf_counter()
    started_at = datetime.now(timezone.utc)

    agent_cls = AGENT_REGISTRY.get(stage_key)
    if agent_cls is None:
        return StageResult(
            stage=stage_key,
            success=False,
            output={},
            error=f"No agent registered for key '{stage_key}'",
            started_at=started_at,
            execution_time_ms=round((time.perf_counter() - stage_start) * 1000, 3),
        )

    sig = inspect.signature(agent_cls.__init__)
    needs_db = len(sig.parameters) > 1
    agent = agent_cls(db) if needs_db else agent_cls()

    last_error: str | None = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.warning(
                "stage_retry",
                stage=stage_key,
                attempt=attempt,
                max_retries=max_retries,
            )

        try:
            maybe_result = agent.run(context)
            if inspect.isawaitable(maybe_result):
                result: AgentResult = await maybe_result
            else:
                result = maybe_result

            execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)

            return StageResult(
                stage=stage_key,
                success=result.success,
                output=_serialize_output(result.output),
                error=result.error,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
                provider_used=result.provider_used,
                cost_usd=result.cost_usd,
            )

        except NotImplementedError as exc:
            execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
            return StageResult(
                stage=stage_key,
                success=False,
                output={},
                error=f"Agent not implemented: {exc}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                execution_time_ms=execution_time_ms,
            )

        except Exception as exc:
            last_error = str(exc)
            logger.exception(
                "stage_execution_failed",
                stage=stage_key,
                attempt=attempt,
                error=last_error,
            )
            if attempt < max_retries:
                continue

    execution_time_ms = round((time.perf_counter() - stage_start) * 1000, 3)
    return StageResult(
        stage=stage_key,
        success=False,
        output={},
        error=last_error,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        execution_time_ms=execution_time_ms,
    )


def _merge_context(
    existing: dict[str, Any],
    new_output: dict[str, Any],
) -> dict[str, Any]:
    """Shallow-merge stage output into the running execution context."""
    merged = existing.copy()
    merged.update(new_output)
    return merged


def _serialize_output(output: Any) -> dict[str, Any]:
    """Recursively serialize dataclass instances to plain dicts."""
    if dataclasses.is_dataclass(output) and not isinstance(output, type):
        return {
            k: _serialize_output(v)
            for k, v in dataclasses.asdict(output).items()
        }
    if isinstance(output, dict):
        return {k: _serialize_output(v) for k, v in output.items()}
    if isinstance(output, (list, tuple)):
        return [_serialize_output(v) for v in output]  # type: ignore[return-value]
    return output  # type: ignore[return-value]