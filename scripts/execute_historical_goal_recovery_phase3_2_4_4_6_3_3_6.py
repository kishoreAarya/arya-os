"""AryaOS Stage 25 — Phase 3.2.4.4.6.3.3.6 Authorized Historical Goal Recovery Script.

Authorized changes:
1. Re-read all target records inside a transaction with deterministic row locks.
2. Verify every expected precondition against the current database.
3. Reconcile Shot 01 from UNKNOWN_PENDING_RECONCILIATION to FAILED ($0.0000 cost).
4. Mark Shot 02 BLOCKED ($0.0000 cost, outputs=None).
5. Release unconsumed $0.0500 reservation (RESERVED -> RELEASED).
6. Mark Goal FAILED (RECOVERY_REQUIRED -> FAILED).
7. Commit atomically.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import uuid

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
    ConsumedCapabilityNonce,
)
from app.services.dispatcher import (
    is_live_local_execution_enabled,
    is_live_provider_execution_enabled,
)
from app.services.execution_bridge_service import (
    VALID_ACTION_STATES,
    VALID_ACTION_TRANSITIONS,
    VALID_GOAL_STATES,
    VALID_GOAL_TRANSITIONS,
    validate_state_transition,
)


GOAL_UUID = uuid.UUID("fc3101ef-8a25-4bcd-aad3-77138b8e8168")
SHOT_01_UUID = uuid.UUID("01b71b65-f5df-441f-bbe4-285be152f8d0")
SHOT_02_UUID = uuid.UUID("4a3142d4-7e5d-4df6-86fd-69dc7d5bbc84")
RESERVATION_UUID = uuid.UUID("9c3de71b-a70c-4491-97ae-4c8d981df8cf")
EXPECTED_UNCONSUMED_NONCE = "c7d1e8ef-3543-42e6-9467-fba2ba72db2e"


async def run_recovery():
    print("=" * 80)
    print("PHASE 3.2.4.4.6.3.3.6: AUTHORIZED HISTORICAL GOAL RECOVERY TRANSACTION")
    print("=" * 80)

    # 1. Preflight safety invariants check
    if is_live_provider_execution_enabled():
        raise RuntimeError("Safety violation: ENABLE_LIVE_PROVIDER_EXECUTION must be False")
    if is_live_local_execution_enabled():
        raise RuntimeError("Safety violation: ENABLE_LIVE_LOCAL_EXECUTION must be False")

    now = datetime.now(timezone.utc)
    before_state = {}
    after_state = {}

    # 2. Atomic recovery transaction
    async with AsyncSessionLocal() as session:
        async with session.begin():
            print("[1/5] Acquiring deterministic row locks...")
            stmt_goal = select(AutonomousGoal).where(AutonomousGoal.id == GOAL_UUID).with_for_update()
            goal = (await session.execute(stmt_goal)).scalar_one_or_none()
            if not goal:
                raise RuntimeError(f"Goal {GOAL_UUID} not found")

            stmt_s1 = select(AutonomousActionNode).where(AutonomousActionNode.id == SHOT_01_UUID).with_for_update()
            shot_01 = (await session.execute(stmt_s1)).scalar_one_or_none()
            if not shot_01:
                raise RuntimeError(f"Shot 01 {SHOT_01_UUID} not found")

            stmt_s2 = select(AutonomousActionNode).where(AutonomousActionNode.id == SHOT_02_UUID).with_for_update()
            shot_02 = (await session.execute(stmt_s2)).scalar_one_or_none()
            if not shot_02:
                raise RuntimeError(f"Shot 02 {SHOT_02_UUID} not found")

            stmt_res = select(BudgetReservation).where(BudgetReservation.id == RESERVATION_UUID).with_for_update()
            reservation = (await session.execute(stmt_res)).scalar_one_or_none()
            if not reservation:
                raise RuntimeError(f"Reservation {RESERVATION_UUID} not found")

            # Record before state
            before_state = {
                "goal": {"id": str(goal.id), "status": goal.status, "failure_reason": goal.failure_reason},
                "shot_01": {"id": str(shot_01.id), "status": shot_01.status, "cost_usd": str(shot_01.cost_usd), "error": shot_01.error},
                "shot_02": {"id": str(shot_02.id), "status": shot_02.status, "cost_usd": str(shot_02.cost_usd), "outputs": shot_02.outputs_json},
                "reservation": {
                    "id": str(reservation.id),
                    "status": reservation.status,
                    "reserved_amount_usd": str(reservation.reserved_amount_usd),
                    "consumed_amount_usd": str(reservation.consumed_amount_usd),
                },
            }

            print("[2/5] Verifying preconditions...")
            # Check nonce
            stmt_nonce = select(ConsumedCapabilityNonce).where(ConsumedCapabilityNonce.execution_nonce == EXPECTED_UNCONSUMED_NONCE)
            nonce_rec = (await session.execute(stmt_nonce)).scalar_one_or_none()
            if nonce_rec is not None:
                raise RuntimeError(f"Safety violation: Nonce {EXPECTED_UNCONSUMED_NONCE} was already consumed!")

            # Verify statuses
            if goal.status != "RECOVERY_REQUIRED":
                raise RuntimeError(f"Precondition failed: Goal status '{goal.status}' != 'RECOVERY_REQUIRED'")
            if shot_01.status != "UNKNOWN_PENDING_RECONCILIATION":
                raise RuntimeError(f"Precondition failed: Shot 01 status '{shot_01.status}' != 'UNKNOWN_PENDING_RECONCILIATION'")
            if shot_02.status != "PENDING":
                raise RuntimeError(f"Precondition failed: Shot 02 status '{shot_02.status}' != 'PENDING'")
            if reservation.status != "RESERVED":
                raise RuntimeError(f"Precondition failed: Reservation status '{reservation.status}' != 'RESERVED'")
            if Decimal(str(reservation.consumed_amount_usd or 0)) != Decimal("0.0000"):
                raise RuntimeError(f"Precondition failed: Reservation consumed_amount_usd is {reservation.consumed_amount_usd}")
            if Decimal(str(shot_01.cost_usd or 0)) != Decimal("0.0000"):
                raise RuntimeError(f"Precondition failed: Shot 01 cost is {shot_01.cost_usd}")
            if Decimal(str(shot_02.cost_usd or 0)) != Decimal("0.0000"):
                raise RuntimeError(f"Precondition failed: Shot 02 cost is {shot_02.cost_usd}")
            if shot_01.production_job_id is not None:
                raise RuntimeError(f"Precondition failed: Shot 01 has unexpected production_job_id {shot_01.production_job_id}")

            s1_inputs = dict(shot_01.inputs_json or {})
            s1_intent = s1_inputs.get("dispatch_intent", {})
            if s1_intent.get("provider_job_id") is not None:
                raise RuntimeError(f"Precondition failed: Shot 01 has provider_job_id {s1_intent.get('provider_job_id')}")

            print("[3/5] Applying governed state transitions...")
            # Shot 01 transition
            validate_state_transition(
                "ActionNode",
                shot_01.status,
                "FAILED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            shot_01.status = "FAILED"
            shot_01.cost_usd = Decimal("0.0000")
            s1_outputs = dict(shot_01.outputs_json or {})
            s1_outputs.update({
                "status": "FAILED",
                "is_ambiguous": False,
                "reconciled": True,
                "reconciled_at": now.isoformat(),
                "reconciliation_reason": "Pre-dispatch reservation lifecycle contract mismatch verified: halted prior to subprocess launch, credential access, or provider dispatch.",
            })
            shot_01.outputs_json = s1_outputs
            if "dispatch_intent" in s1_inputs and isinstance(s1_inputs["dispatch_intent"], dict):
                s1_inputs["dispatch_intent"]["status"] = "FAILED"
                s1_inputs["dispatch_intent"]["dispatch_state"] = "FAILED_PRE_DISPATCH"
                s1_inputs["dispatch_intent"]["is_ambiguous"] = False
                shot_01.inputs_json = s1_inputs
            shot_01.updated_at = now

            # Shot 02 transition
            validate_state_transition(
                "ActionNode",
                shot_02.status,
                "BLOCKED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            shot_02.status = "BLOCKED"
            shot_02.cost_usd = Decimal("0.0000")
            shot_02.error = "Prerequisite action 'shot_01' failed pre-dispatch; downstream execution blocked."
            shot_02.outputs_json = None
            shot_02.updated_at = now

            # Budget Reservation release
            reservation.status = "RELEASED"
            reservation.updated_at = now

            # Goal transition
            validate_state_transition(
                "Goal",
                goal.status,
                "FAILED",
                VALID_GOAL_STATES,
                VALID_GOAL_TRANSITIONS,
                is_authoritative_engine=True,
            )
            goal.status = "FAILED"
            goal.failure_reason = "Execution failed pre-dispatch: Shot 01 halted on reservation contract mismatch. Reconciled authoritatively with zero spend."
            goal.updated_at = now

            print("[4/5] Committing transaction atomically...")

    # 3. Post-commit verification in a separate session
    print("[5/5] Re-reading target records for post-commit verification...")
    async with AsyncSessionLocal() as session:
        v_goal = (await session.execute(select(AutonomousGoal).where(AutonomousGoal.id == GOAL_UUID))).scalar_one()
        v_s1 = (await session.execute(select(AutonomousActionNode).where(AutonomousActionNode.id == SHOT_01_UUID))).scalar_one()
        v_s2 = (await session.execute(select(AutonomousActionNode).where(AutonomousActionNode.id == SHOT_02_UUID))).scalar_one()
        v_res = (await session.execute(select(BudgetReservation).where(BudgetReservation.id == RESERVATION_UUID))).scalar_one()

        v_nonce = (await session.execute(select(ConsumedCapabilityNonce).where(ConsumedCapabilityNonce.execution_nonce == EXPECTED_UNCONSUMED_NONCE))).scalar_one_or_none()

        after_state = {
            "goal": {
                "id": str(v_goal.id),
                "status": v_goal.status,
                "failure_reason": v_goal.failure_reason,
                "updated_at": v_goal.updated_at.isoformat() if v_goal.updated_at else None,
            },
            "shot_01": {
                "id": str(v_s1.id),
                "status": v_s1.status,
                "cost_usd": str(v_s1.cost_usd),
                "error": v_s1.error,
                "outputs_json": v_s1.outputs_json,
                "updated_at": v_s1.updated_at.isoformat() if v_s1.updated_at else None,
            },
            "shot_02": {
                "id": str(v_s2.id),
                "status": v_s2.status,
                "cost_usd": str(v_s2.cost_usd),
                "error": v_s2.error,
                "outputs_json": v_s2.outputs_json,
                "updated_at": v_s2.updated_at.isoformat() if v_s2.updated_at else None,
            },
            "reservation": {
                "id": str(v_res.id),
                "status": v_res.status,
                "reserved_amount_usd": str(v_res.reserved_amount_usd),
                "consumed_amount_usd": str(v_res.consumed_amount_usd),
                "updated_at": v_res.updated_at.isoformat() if v_res.updated_at else None,
            },
            "nonce_consumed": v_nonce is not None,
        }

        # Assertions on post-commit state
        assert v_goal.status == "FAILED", f"Goal status mismatch: {v_goal.status}"
        assert v_s1.status == "FAILED", f"Shot 01 status mismatch: {v_s1.status}"
        assert Decimal(str(v_s1.cost_usd)) == Decimal("0.0000"), f"Shot 01 cost mismatch: {v_s1.cost_usd}"
        assert v_s1.outputs_json.get("is_ambiguous") is False, "Shot 01 is_ambiguous mismatch"
        assert v_s2.status == "BLOCKED", f"Shot 02 status mismatch: {v_s2.status}"
        assert Decimal(str(v_s2.cost_usd)) == Decimal("0.0000"), f"Shot 02 cost mismatch: {v_s2.cost_usd}"
        assert v_s2.outputs_json is None, "Shot 02 outputs_json mismatch"
        assert v_res.status == "RELEASED", f"Reservation status mismatch: {v_res.status}"
        assert v_nonce is None, "Nonce was consumed!"

    print("\nSUCCESS: Recovery transaction executed and verified atomically.")
    print("BEFORE STATE:")
    print(json.dumps(before_state, indent=2))
    print("AFTER STATE:")
    print(json.dumps(after_state, indent=2))


if __name__ == "__main__":
    asyncio.run(run_recovery())
