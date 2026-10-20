"""
AryaOS V1 Phase 3.2.4.4.6.3.3.14 — Lease Expiry & Background Recovery Sweeper Service.

Enforces crash-safe, bounded, idempotent detection and recovery of expired action leases:
- Periodically inspects authoritative persisted lease timestamps on EXECUTING actions.
- Uses PostgreSQL advisory locking for cross-process mutual exclusion across multiple workers.
- Defensively validates timestamps, malformed, or missing lease data fail-closed.
- Where external dispatch may have started (dispatch_intent present):
  transitions action to UNKNOWN_PENDING_RECONCILIATION and goal to RECOVERY_REQUIRED.
- Where external dispatch never occurred (no dispatch_intent):
  safely resets action to READY, incrementing epoch to prevent stale overwrite.
- Strictly preserves budget reservations and financial truth: never releases or consumes funds on expiry alone.
- Idempotent: non-EXECUTING actions are untouched; repeated sweeps do not alter reconciled state.
- Immediately blocks downstream actions in the DAG while prerequisites remain ambiguous.
- Clean application startup and shutdown integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.execution_bridge_service import (
    VALID_ACTION_STATES,
    VALID_ACTION_TRANSITIONS,
    VALID_GOAL_STATES,
    VALID_GOAL_TRANSITIONS,
    validate_state_transition,
)

logger = get_logger("arya.execution.lease_sweeper")

# Stable integer key for cross-process PostgreSQL advisory locking
LEASE_SWEEPER_ADVISORY_LOCK_KEY: int = 84729105


@dataclass
class LeaseSweepReport:
    """Detailed summary of a lease expiry sweep iteration."""

    total_checked: int = 0
    expired_found: int = 0
    transitioned_unknown: int = 0
    transitioned_ready: int = 0
    skipped_active: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "COMPLETED"  # "COMPLETED" | "DISABLED" | "SKIPPED_LOCK_HELD" | "ERROR"


class LeaseExpirySweeperService:
    """Authoritative background sweeper for detecting and recovering expired action leases."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._in_process_lock = asyncio.Lock()

    async def run_sweep(
        self,
        session: AsyncSession | None = None,
        batch_size: int | None = None,
        goal_id: uuid.UUID | None = None,
        action_id: uuid.UUID | None = None,
    ) -> LeaseSweepReport:
        """Executes a bounded, concurrency-safe maintenance sweep over executing action leases.

        Args:
            session: Optional existing AsyncSession for transactional/testing context.
            batch_size: Optional limit on the number of candidates to process per sweep.
            goal_id: Optional goal filter to restrict sweep to actions in a specific goal.
            action_id: Optional action filter to restrict sweep to a specific action.
        """
        if not getattr(self.settings, "enable_lease_expiry_sweeper", True):
            logger.info("lease_sweeper_disabled_by_config")
            return LeaseSweepReport(status="DISABLED")

        limit = batch_size or getattr(self.settings, "lease_expiry_batch_size", 50)

        # In-process mutual exclusion to prevent multiple concurrent tasks within this event loop
        if self._in_process_lock.locked():
            logger.info("lease_sweeper_in_process_lock_held_skipping")
            return LeaseSweepReport(status="SKIPPED_LOCK_HELD")

        async with self._in_process_lock:
            if session is not None:
                return await self._execute_sweep(
                    session, limit, goal_id=goal_id, action_id=action_id
                )
            async with AsyncSessionLocal() as managed_session:
                return await self._execute_sweep(
                    managed_session, limit, goal_id=goal_id, action_id=action_id
                )

    async def _execute_sweep(
        self,
        session: AsyncSession,
        batch_limit: int,
        goal_id: uuid.UUID | None = None,
        action_id: uuid.UUID | None = None,
    ) -> LeaseSweepReport:
        report = LeaseSweepReport()

        # 1. Distributed mutual exclusion via PostgreSQL advisory lock (cross-worker safety)
        bind = session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "").lower()
        is_postgres = "postgres" in dialect_name
        acquired_advisory = False

        if is_postgres:
            try:
                res = await session.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": LEASE_SWEEPER_ADVISORY_LOCK_KEY},
                )
                acquired_advisory = bool(res.scalar())
                if not acquired_advisory:
                    logger.info("lease_sweeper_advisory_lock_held_by_peer")
                    report.status = "SKIPPED_LOCK_HELD"
                    return report
            except Exception as exc:
                logger.warning("lease_sweeper_advisory_lock_attempt_failed", error=str(exc))

        try:
            # 2. Query candidate executing action nodes
            stmt = select(AutonomousActionNode).where(AutonomousActionNode.status == "EXECUTING")
            if goal_id is not None:
                stmt = stmt.where(AutonomousActionNode.goal_id == goal_id)
            if action_id is not None:
                stmt = stmt.where(AutonomousActionNode.id == action_id)
            stmt = stmt.order_by(AutonomousActionNode.updated_at.asc()).limit(batch_limit)
            res = await session.execute(stmt)
            candidates = list(res.scalars().all())
            report.total_checked = len(candidates)

            if not candidates:
                return report

            now_utc = datetime.now(timezone.utc)

            # 3. Evaluate each candidate defensively
            for candidate in candidates:
                try:
                    # Lock row first (HIGH-01) to prevent TOCTOU race with worker heartbeats
                    lock_stmt = (
                        select(AutonomousActionNode)
                        .where(AutonomousActionNode.id == candidate.id)
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    lock_res = await session.execute(lock_stmt)
                    node = lock_res.scalar_one_or_none()
                    if not node or node.status != "EXECUTING":
                        # Node was completed or transitioned concurrently
                        continue

                    # Refresh lease details authoritative from locked row
                    refreshed_inputs = dict(node.inputs_json or {})
                    lease = refreshed_inputs.get("lease") if isinstance(refreshed_inputs.get("lease"), dict) else None
                    expires_at_str = lease.get("expires_at") if lease else None

                    now_utc = datetime.now(timezone.utc)
                    is_expired = False
                    if not lease or not expires_at_str:
                        # Malformed or missing lease info -> fail closed by treating as expired
                        is_expired = True
                    else:
                        try:
                            exp_dt = datetime.fromisoformat(str(expires_at_str))
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                            if now_utc > exp_dt:
                                is_expired = True
                        except (ValueError, TypeError):
                            # Unparseable timestamp -> fail closed by treating as expired
                            is_expired = True

                    if not is_expired:
                        # Heartbeat renewed the lease before row lock was acquired!
                        report.skipped_active += 1
                        continue

                    report.expired_found += 1

                    dispatch_intent = refreshed_inputs.get("dispatch_intent")
                    has_dispatch_intent = isinstance(dispatch_intent, dict) and bool(dispatch_intent)

                    if has_dispatch_intent:
                        # Case A: External dispatch may have occurred or been scheduled
                        validate_state_transition(
                            "ActionNode",
                            node.status,
                            "UNKNOWN_PENDING_RECONCILIATION",
                            VALID_ACTION_STATES,
                            VALID_ACTION_TRANSITIONS,
                            is_authoritative_engine=True,
                        )
                        node.status = "UNKNOWN_PENDING_RECONCILIATION"
                        node.error = (
                            "Worker lease expired while executing; outcome unknown pending authoritative reconciliation."
                        )

                        # Invalidate stale worker authority (MED-02): advance epoch and rotate lease token
                        curr_epoch = lease.get("epoch", 0) if lease else 0
                        new_lease = dict(lease or {})
                        new_lease["epoch"] = curr_epoch + 1
                        new_lease["lease_token"] = str(uuid.uuid4())
                        new_lease["swept_at"] = now_utc.isoformat()
                        new_lease["invalidation_reason"] = "LEASE_EXPIRED_DISPATCHED"
                        new_lease["previous_worker_id"] = lease.get("worker_id") if lease else None
                        new_lease["previous_lease_token"] = lease.get("lease_token") if lease else None
                        refreshed_inputs["lease"] = new_lease

                        history = list(refreshed_inputs.get("reconciliation_history", []))
                        history.append({
                            "timestamp": now_utc.isoformat(),
                            "event": "LEASE_EXPIRED_SWEPT",
                            "previous_status": "EXECUTING",
                            "new_status": "UNKNOWN_PENDING_RECONCILIATION",
                            "reason": "Lease expired with active dispatch intent; requires authoritative reconciliation",
                            "worker_id": lease.get("worker_id") if lease else None,
                            "lease_token": lease.get("lease_token") if lease else None,
                            "epoch": lease.get("epoch") if lease else None,
                            "new_epoch": new_lease["epoch"],
                            "new_lease_token": new_lease["lease_token"],
                            "expires_at": str(expires_at_str),
                        })
                        refreshed_inputs["reconciliation_history"] = history
                        node.inputs_json = refreshed_inputs

                        # Transition parent goal to RECOVERY_REQUIRED
                        goal = await session.get(AutonomousGoal, node.goal_id, with_for_update=True)
                        if goal and goal.status in ("EXECUTING", "READY", "RUNNING"):
                            validate_state_transition(
                                "Goal",
                                goal.status,
                                "RECOVERY_REQUIRED",
                                VALID_GOAL_STATES,
                                VALID_GOAL_TRANSITIONS,
                                is_authoritative_engine=True,
                            )
                            goal.status = "RECOVERY_REQUIRED"
                            goal.failure_reason = (
                                f"Execution halted: action '{node.client_action_id}' lease expired with unknown outcome"
                            )

                        # Cascade DAG readiness updates to block downstream actions
                        if goal and goal.plan_dag_json:
                            stmt_all = (
                                select(AutonomousActionNode)
                                .where(AutonomousActionNode.goal_id == goal.id)
                                .with_for_update()
                            )
                            res_all = await session.execute(stmt_all)
                            goal_actions = list(res_all.scalars().all())

                            from app.services.autonomous_execution_runner import (
                                AutonomousExecutionRunner,
                            )

                            readiness_updates = AutonomousExecutionRunner.resolve_dag_readiness(
                                goal.plan_dag_json, goal_actions
                            )
                            for g_action in goal_actions:
                                if g_action.client_action_id in readiness_updates:
                                    tgt_status = readiness_updates[g_action.client_action_id]
                                    if tgt_status != g_action.status:
                                        validate_state_transition(
                                            "ActionNode",
                                            g_action.status,
                                            tgt_status,
                                            VALID_ACTION_STATES,
                                            VALID_ACTION_TRANSITIONS,
                                            is_authoritative_engine=True,
                                        )
                                        g_action.status = tgt_status

                        report.transitioned_unknown += 1

                    else:
                        # Case B: External dispatch was never initiated before worker disappeared
                        validate_state_transition(
                            "ActionNode",
                            node.status,
                            "READY",
                            VALID_ACTION_STATES,
                            VALID_ACTION_TRANSITIONS,
                            is_authoritative_engine=True,
                        )
                        node.status = "READY"
                        node.error = None

                        # Invalidate stale worker fencing token by incrementing epoch
                        curr_epoch = lease.get("epoch", 0) if lease else 0
                        new_lease = dict(lease or {})
                        new_lease["epoch"] = curr_epoch + 1
                        new_lease["lease_token"] = str(uuid.uuid4())
                        new_lease["cleared_by_sweeper_at"] = now_utc.isoformat()
                        refreshed_inputs["lease"] = new_lease

                        history = list(refreshed_inputs.get("reconciliation_history", []))
                        history.append({
                            "timestamp": now_utc.isoformat(),
                            "event": "LEASE_EXPIRED_PRE_DISPATCH_RESET",
                            "previous_status": "EXECUTING",
                            "new_status": "READY",
                            "detail": "Action lease expired before external dispatch; safely reset to READY.",
                        })
                        refreshed_inputs["reconciliation_history"] = history
                        node.inputs_json = refreshed_inputs

                        report.transitioned_ready += 1

                    # Important Invariant: budget reservations remain untouched!
                    await session.commit()

                except Exception as node_exc:
                    report.errors.append(f"Action {candidate.id}: {node_exc}")
                    logger.error(
                        "lease_sweeper_node_recovery_failed",
                        action_id=str(candidate.id),
                        error=str(node_exc),
                    )
                    await session.rollback()

            return report

        finally:
            # 4. Release PostgreSQL advisory lock
            if acquired_advisory and is_postgres:
                try:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": LEASE_SWEEPER_ADVISORY_LOCK_KEY},
                    )
                except Exception as exc:
                    logger.warning("lease_sweeper_advisory_unlock_failed", error=str(exc))


_sweeper_instance: LeaseExpirySweeperService | None = None


def get_lease_expiry_sweeper_service() -> LeaseExpirySweeperService:
    """Returns the singleton instance of LeaseExpirySweeperService."""
    global _sweeper_instance
    if _sweeper_instance is None:
        _sweeper_instance = LeaseExpirySweeperService()
    return _sweeper_instance
