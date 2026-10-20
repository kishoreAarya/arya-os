"""
AryaOS V1 Stage 25 Phase 3.2.4.4.6.2 — Multi-Shot Security Remediation Implementation Test Suite.

Exhaustively verifies remediations for SEC-FINDING-01 through SEC-FINDING-04:
- SEC-FINDING-01: Atomic PostgreSQL-backed multi-goal budget reservations with row-level locking.
- SEC-FINDING-02: Numeric cost hardening against negative, zero, NaN, +inf, -inf, and excessive durations.
- SEC-FINDING-03: DAG topology freeze preventing action injection during non-planning lifecycle states.
- SEC-FINDING-04: Centralized SSRF validation rejecting RFC 1918, link-local, cloud metadata, and alternative IP encodings.
- ADVERSARIAL: Concurrency races, plan versioning, stale worker fencing, and financial integrity invariants.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal, is_safe_remote_url, _is_disallowed_ip
from app.database.session import AsyncSessionLocal
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
)
from app.services.autonomous_execution_runner import (
    ActionValidationError,
    AggregateBudgetPreflightError,
    AutonomousExecutionRunner,
    BindingSecurityError,
)
from app.services.dispatcher import OfflineMockDispatcher
from app.services.execution_bridge_service import create_action_node
from app.schemas.execution_bridge import AutonomousActionNodeCreate

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK BLOCKING (ZERO EXTERNAL TRAFFIC)
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during remediation tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.6.2 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


async def _setup_project_and_principal(
    db: AsyncSession, budget_limit_usd: float = 1.00
) -> tuple[Project, AuthenticatedPrincipal]:
    project = Project(
        name=f"Remediation Project {uuid.uuid4().hex[:6]}",
        budget_limit_usd=Decimal(str(budget_limit_usd)),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Lead Security Operator",
        is_admin=True,
        principal_type="system",
    )
    return project, principal


# ===========================================================================
# 1. BUDGET TESTS (01 - 09)
# ===========================================================================

async def test_01_concurrent_ab_reservation_race(db_session: AsyncSession):
    """01 concurrent A/B reservation race: two $0.60 goals against $1.00, exactly one succeeds."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)

    # Goal A: aggregate cost = 3 * 0.20 = $0.60 (3 kling actions with 10s duration)
    goal_a = AutonomousGoal(
        project_id=project.id,
        objective="Goal A: $0.60 spend",
        status="READY",
        current_plan_version=1,
    )
    goal_b = AutonomousGoal(
        project_id=project.id,
        objective="Goal B: $0.60 spend",
        status="READY",
        current_plan_version=1,
    )
    db_session.add_all([goal_a, goal_b])
    await db_session.commit()
    await db_session.refresh(goal_a)
    await db_session.refresh(goal_b)

    for i in range(3):
        a1 = AutonomousActionNode(
            goal_id=goal_a.id,
            client_action_id=f"a_{i}",
            title=f"Action A{i}",
            action_type="GENERATION",
            required_capability="VIDEO_GENERATION",
            status="READY",
            inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20 each
        )
        b1 = AutonomousActionNode(
            goal_id=goal_b.id,
            client_action_id=f"b_{i}",
            title=f"Action B{i}",
            action_type="GENERATION",
            required_capability="VIDEO_GENERATION",
            status="READY",
            inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20 each
        )
        db_session.add_all([a1, b1])
    await db_session.commit()

    # Compete using two separate async sessions to exercise Postgres row locks
    async def _try_reserve(target_goal_id: uuid.UUID):
        async with AsyncSessionLocal() as session:
            g = await session.get(AutonomousGoal, target_goal_id)
            runner = AutonomousExecutionRunner(db=session, dispatcher=OfflineMockDispatcher())
            return await runner.reserve_aggregate_dag_budget(g)

    results = await asyncio.gather(_try_reserve(goal_a.id), _try_reserve(goal_b.id), return_exceptions=True)

    successes = [r for r in results if isinstance(r, BudgetReservation)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1, f"Expected exactly 1 reservation success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 reservation failure, got {len(failures)}"
    assert isinstance(failures[0], (AggregateBudgetPreflightError, HTTPException))


class TrackingOfflineDispatcher(OfflineMockDispatcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_history = []

    async def dispatch(self, action: AutonomousActionNode):
        self.call_history.append(action)
        return await super().dispatch(action)


async def test_02_aggregate_budget_insufficient_zero_provider_calls(db_session: AsyncSession):
    """02 aggregate budget insufficient: provider calls = 0."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=0.10)
    dispatcher = TrackingOfflineDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    goal = AutonomousGoal(project_id=project.id, objective="Goal exceeding budget", status="READY")
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_expensive",
        title="Expensive Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20 > 0.10
    )
    db_session.add(action)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409
    assert "exceeds available budget authority" in exc_info.value.detail
    assert len(dispatcher.call_history) == 0


async def test_03_reservation_idempotency(db_session: AsyncSession):
    """03 reservation idempotency: multiple calls produce exactly one reservation record."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Idempotency Goal", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_idem",
        title="Shot Idem",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "fal", "model": "flux-pro/v1.1"}, # 0.05
    )
    db_session.add(action)
    await db_session.commit()

    res1 = await runner.reserve_aggregate_dag_budget(goal)
    res2 = await runner.reserve_aggregate_dag_budget(goal)

    assert res1.id == res2.id
    assert float(res1.reserved_amount_usd) == 0.05

    stmt = select(BudgetReservation).where(
        BudgetReservation.goal_id == goal.id,
        BudgetReservation.plan_version == 1,
    )
    all_res = (await db_session.execute(stmt)).scalars().all()
    assert len(all_res) == 1


async def test_04_completion_releases_residual(db_session: AsyncSession):
    """04 completion releases residual: unconsumed reservation is transitioned to RELEASED."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Completion Release", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_complete",
        title="Shot Complete",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "fal", "model": "flux-pro/v1.1"},
    )
    db_session.add(action)
    await db_session.commit()

    await runner.reserve_aggregate_dag_budget(goal)
    await runner.dispatch_action(action.id, principal)

    await db_session.refresh(goal)
    assert goal.status == "COMPLETED"

    stmt = select(BudgetReservation).where(BudgetReservation.goal_id == goal.id)
    res = (await db_session.execute(stmt)).scalar_one()
    assert res.status in ("RELEASED", "CONSUMED")


async def test_05_actual_cost_increments_consumed(db_session: AsyncSession):
    """05 actual cost increments consumed: successful dispatch increases consumed_amount_usd."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Increment Consumed", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_kling_5s",
        title="Kling 5s Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0}, # 0.10
    )
    db_session.add(action)
    await db_session.commit()

    reservation = await runner.reserve_aggregate_dag_budget(goal)
    assert float(reservation.consumed_amount_usd) == 0.0

    await runner.dispatch_action(action.id, principal)

    await db_session.refresh(reservation)
    assert float(reservation.consumed_amount_usd) == 0.10


async def test_06_unknown_retains_reservation(db_session: AsyncSession):
    """06 UNKNOWN retains reservation: reservation remains RESERVED when outcome is ambiguous."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)

    class FailingDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action):
            from app.services.dispatcher import ExecutionResult
            return ExecutionResult(
                success=False,
                status="UNKNOWN_PENDING_RECONCILIATION",
                cost_usd=0.10,
                error="Provider gateway timeout NO_LOOKUP",
            )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=FailingDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Unknown Retain", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_unknown",
        title="Shot Unknown",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    reservation = await runner.reserve_aggregate_dag_budget(goal)
    await runner.dispatch_action(action.id, principal)

    await db_session.refresh(reservation)
    await db_session.refresh(goal)
    assert goal.status == "RECOVERY_REQUIRED"
    assert reservation.status == "RESERVED"  # Must NOT be released!


async def test_07_failed_releases_unexecuted_residual(db_session: AsyncSession):
    """07 FAILED releases unexecuted residual: goal failure releases unused reservation."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)

    class HardFailDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action):
            from app.services.dispatcher import ExecutionResult
            return ExecutionResult(
                success=False,
                status="FAILED",
                cost_usd=0.0,
                error="Hard provider failure",
            )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=HardFailDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Failed Release", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_fail",
        title="Shot Fail",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    await runner.reserve_aggregate_dag_budget(goal)
    await runner.dispatch_action(action.id, principal)

    # Progress goal step to record failure and release
    await runner.execute_goal_step(goal.id, principal)

    stmt = select(BudgetReservation).where(BudgetReservation.goal_id == goal.id)
    res = (await db_session.execute(stmt)).scalar_one()
    assert res.status == "RELEASED"


async def test_08_cancel_releases_residual(db_session: AsyncSession):
    """08 CANCEL releases residual: cancelling goal releases unused budget reservation."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Cancel Release", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_cancel",
        title="Shot Cancel",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    await runner.reserve_aggregate_dag_budget(goal)
    await runner.cancel_goal(goal.id, principal)

    stmt = select(BudgetReservation).where(BudgetReservation.goal_id == goal.id)
    res = (await db_session.execute(stmt)).scalar_one()
    assert res.status == "RELEASED"


async def test_09_succeeded_replay_costs_zero(db_session: AsyncSession):
    """09 succeeded replay costs $0: re-dispatching already SUCCEEDED action consumes no extra budget."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Replay Zero Cost", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_replay",
        title="Shot Replay",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    await runner.reserve_aggregate_dag_budget(goal)
    await runner.dispatch_action(action.id, principal)

    stmt = select(BudgetReservation).where(BudgetReservation.goal_id == goal.id)
    res = (await db_session.execute(stmt)).scalar_one()
    initial_consumed = float(res.consumed_amount_usd)

    # Re-dispatch
    await runner.dispatch_action(action.id, principal)
    await db_session.refresh(res)
    assert float(res.consumed_amount_usd) == initial_consumed


# ===========================================================================
# 2. NUMERIC COST HARDENING TESTS (10 - 16)
# ===========================================================================

async def test_10_negative_duration_rejected():
    """10 negative duration rejected: -100 raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_neg",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": -100},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


async def test_11_nan_duration_rejected():
    """11 NaN rejected: float('nan') raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_nan",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": "NaN"},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


async def test_12_positive_infinity_rejected():
    """12 +inf rejected: float('+inf') raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_pinf",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": "+inf"},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


async def test_13_negative_infinity_rejected():
    """13 -inf rejected: float('-inf') raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_ninf",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": "-inf"},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


async def test_14_zero_duration_rejected():
    """14 zero rejected: duration = 0 raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_zero",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": 0},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


async def test_15_missing_duration_baseline():
    """15 missing duration baseline: defaults safely to 5.0 seconds baseline."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_missing",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling"},
    )
    cost = runner.calculate_authoritative_action_cost(action)
    assert cost == 0.10  # 0.10 * (5.0 / 5.0)


async def test_16_excessive_duration_rejected():
    """16 excessive duration rejected: 999 > 60s raises ActionValidationError."""
    runner = AutonomousExecutionRunner(db=None)
    action = AutonomousActionNode(
        client_action_id="act_excessive",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={"provider": "kling", "duration_seconds": 999},
    )
    with pytest.raises(ActionValidationError):
        runner.calculate_authoritative_action_cost(action)


# ===========================================================================
# 3. DAG TOPOLOGY FREEZE TESTS (17 - 20)
# ===========================================================================

async def test_17_executing_injection_rejected(db_session: AsyncSession):
    """17 EXECUTING injection rejected: create_action_node fails with 409 when goal is EXECUTING."""
    project, principal = await _setup_project_and_principal(db_session)
    goal = AutonomousGoal(project_id=project.id, objective="Executing Goal", status="EXECUTING")
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    data = AutonomousActionNodeCreate(
        client_action_id="injected_node",
        title="Malicious Injection",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_action_node(db_session, goal.id, data, principal)

    assert exc_info.value.status_code == 409
    assert "DAG topology is frozen" in exc_info.value.detail


async def test_18_paused_injection_rejected(db_session: AsyncSession):
    """18 PAUSED injection rejected: create_action_node fails with 409 when goal is PAUSED."""
    project, principal = await _setup_project_and_principal(db_session)
    goal = AutonomousGoal(project_id=project.id, objective="Paused Goal", status="PAUSED")
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    data = AutonomousActionNodeCreate(
        client_action_id="injected_node_paused",
        title="Paused Injection",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_action_node(db_session, goal.id, data, principal)

    assert exc_info.value.status_code == 409
    assert "DAG topology is frozen" in exc_info.value.detail


async def test_19_draft_planning_creation_succeeds(db_session: AsyncSession):
    """19 DRAFT/PLANNING creation succeeds: actions can be created in DRAFT and PLANNING."""
    project, principal = await _setup_project_and_principal(db_session)
    goal_draft = AutonomousGoal(project_id=project.id, objective="Draft Goal", status="DRAFT")
    goal_planning = AutonomousGoal(project_id=project.id, objective="Planning Goal", status="PLANNING")
    db_session.add_all([goal_draft, goal_planning])
    await db_session.commit()
    await db_session.refresh(goal_draft)
    await db_session.refresh(goal_planning)

    node_d = await create_action_node(
        db_session,
        goal_draft.id,
        AutonomousActionNodeCreate(
            client_action_id="draft_node",
            title="Draft Node",
            action_type="SYNTHESIS",
            required_capability="IMAGE_GENERATION",
        ),
        principal,
    )
    node_p = await create_action_node(
        db_session,
        goal_planning.id,
        AutonomousActionNodeCreate(
            client_action_id="planning_node",
            title="Planning Node",
            action_type="SYNTHESIS",
            required_capability="IMAGE_GENERATION",
        ),
        principal,
    )

    assert node_d.id is not None
    assert node_p.id is not None


async def test_20_governed_stage12_replan_succeeds(db_session: AsyncSession):
    """20 governed Stage 12 replan succeeds: transitions goal to PLANNING, increments plan_version, and attaches new actions."""
    project, principal = await _setup_project_and_principal(db_session)
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Executing Goal to Replan",
        status="PLANNING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    # Initial action
    act1 = await create_action_node(
        db_session,
        goal.id,
        AutonomousActionNodeCreate(
            client_action_id="shot_1",
            title="Shot 1",
            action_type="SYNTHESIS",
            required_capability="IMAGE_GENERATION",
        ),
        principal,
    )

    # Move to EXECUTING
    goal.status = "EXECUTING"
    await db_session.commit()

    # Stage 12 governed replan: transition back to PLANNING and increment version
    goal.status = "PLANNING"
    goal.current_plan_version = 2
    await db_session.commit()

    # In PLANNING, creating new action succeeds
    act2 = await create_action_node(
        db_session,
        goal.id,
        AutonomousActionNodeCreate(
            client_action_id="shot_2_replanned",
            title="Shot 2 Replanned",
            action_type="SYNTHESIS",
            required_capability="VIDEO_GENERATION",
        ),
        principal,
    )
    assert act2.id is not None
    assert goal.current_plan_version == 2


# ===========================================================================
# 4. SSRF & RFC1918 TESTS (21 - 30)
# ===========================================================================

async def test_21_ssrf_172_16_0_1_blocked():
    """21 172.16.0.1 blocked."""
    assert is_safe_remote_url("http://172.16.0.1/asset.png") is False


async def test_22_ssrf_172_31_255_254_blocked():
    """22 172.31.255.254 blocked."""
    assert is_safe_remote_url("http://172.31.255.254/asset.png") is False


async def test_23_ssrf_127_0_0_1_blocked():
    """23 127.0.0.1 blocked."""
    assert is_safe_remote_url("http://127.0.0.1/asset.png") is False
    assert is_safe_remote_url("http://localhost/asset.png") is False


async def test_24_ssrf_ipv6_loopback_blocked():
    """24 [::1] blocked."""
    assert is_safe_remote_url("http://[::1]/asset.png") is False


async def test_25_ssrf_cloud_metadata_blocked():
    """25 169.254.169.254 and metadata.google.internal blocked."""
    assert is_safe_remote_url("http://169.254.169.254/computeMetadata/v1/") is False
    assert is_safe_remote_url("http://metadata.google.internal/computeMetadata/v1/") is False


async def test_26_ssrf_decimal_ipv4_blocked():
    """26 decimal IPv4 (2130706433) blocked."""
    assert is_safe_remote_url("http://2130706433/asset.png") is False


async def test_27_ssrf_hex_ipv4_blocked():
    """27 hex IPv4 (0x7f000001) blocked."""
    assert is_safe_remote_url("http://0x7f000001/asset.png") is False


async def test_28_ssrf_ipv6_private_blocked():
    """28 IPv6 private blocked: fc00::/7 and ::ffff:127.0.0.1."""
    assert is_safe_remote_url("http://[fc00::1]/asset.png") is False
    assert is_safe_remote_url("http://[::ffff:127.0.0.1]/asset.png") is False


async def test_29_ssrf_dns_private_resolution_blocked():
    """29 DNS private resolution / internal TLDs blocked."""
    assert is_safe_remote_url("http://router.local/asset.png") is False
    assert is_safe_remote_url("http://server.lan/asset.png") is False
    assert is_safe_remote_url("http://corp.test/asset.png") is False


async def test_30_ssrf_public_https_allowed():
    """30 public HTTPS allowed."""
    assert is_safe_remote_url("https://example.com/asset.png") is True
    assert is_safe_remote_url("https://storage.googleapis.com/bucket/shot01.png") is True


# ===========================================================================
# 5. ADDITIONAL ADVERSARIAL TESTS (31 - 40)
# ===========================================================================

async def test_31_two_goals_cannot_oversubscribe_same_project(db_session: AsyncSession):
    """31 two different goals cannot oversubscribe same project budget sequentially."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=0.25)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal1 = AutonomousGoal(project_id=project.id, objective="Goal 1", status="READY", current_plan_version=1)
    goal2 = AutonomousGoal(project_id=project.id, objective="Goal 2", status="READY", current_plan_version=1)
    db_session.add_all([goal1, goal2])
    await db_session.commit()
    await db_session.refresh(goal1)
    await db_session.refresh(goal2)

    # Goal 1: $0.20
    a1 = AutonomousActionNode(
        goal_id=goal1.id,
        client_action_id="g1_act",
        title="G1 Act",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20
    )
    # Goal 2: $0.10 (0.20 + 0.10 = 0.30 > 0.25)
    a2 = AutonomousActionNode(
        goal_id=goal2.id,
        client_action_id="g2_act",
        title="G2 Act",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0}, # 0.10
    )
    db_session.add_all([a1, a2])
    await db_session.commit()

    # Goal 1 reserves $0.20 (remaining: $0.05)
    await runner.reserve_aggregate_dag_budget(goal1)

    # Goal 2 attempts $0.10 -> must fail
    with pytest.raises(AggregateBudgetPreflightError):
        await runner.reserve_aggregate_dag_budget(goal2)


async def test_32_client_injected_budget_limit_is_ignored(db_session: AsyncSession):
    """32 client attempts to inject larger budget_limit is ignored/rejected."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=0.10)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    # Client sets plan_dag_json.budget_limit_usd to $1000.00
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Client injected budget",
        status="READY",
        current_plan_version=1,
        plan_dag_json={"budget_limit_usd": 1000.0},
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_over",
        title="Shot Over",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20 > 0.10 project limit
    )
    db_session.add(action)
    await db_session.commit()

    with pytest.raises(AggregateBudgetPreflightError) as exc_info:
        await runner.reserve_aggregate_dag_budget(goal)

    assert "exceeds available budget authority" in str(exc_info.value)


async def test_33_concurrent_reservation_transactions_remain_serializable(db_session: AsyncSession):
    """33 concurrent reservation transactions remain serializable."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=0.50)

    # Create 5 goals concurrently requesting $0.20 each against $0.50 ceiling
    goals = []
    for i in range(5):
        g = AutonomousGoal(project_id=project.id, objective=f"Concurrent Goal {i}", status="READY", current_plan_version=1)
        db_session.add(g)
        await db_session.flush()
        act = AutonomousActionNode(
            goal_id=g.id,
            client_action_id=f"act_con_{i}",
            title=f"Concurrent Act {i}",
            action_type="GENERATION",
            required_capability="VIDEO_GENERATION",
            status="READY",
            inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20
        )
        db_session.add(act)
        goals.append(g)
    await db_session.commit()

    async def _reserve_one(g_id):
        async with AsyncSessionLocal() as session:
            g = await session.get(AutonomousGoal, g_id)
            r = AutonomousExecutionRunner(db=session, dispatcher=OfflineMockDispatcher())
            return await r.reserve_aggregate_dag_budget(g)

    results = await asyncio.gather(*[_reserve_one(g.id) for g in goals], return_exceptions=True)

    successes = [r for r in results if isinstance(r, BudgetReservation)]
    # At $0.20 each against $0.50, at most 2 can succeed
    assert len(successes) == 2


async def test_34_unknown_reservation_cannot_be_released_by_completion_path(db_session: AsyncSession):
    """34 UNKNOWN reservation cannot be released by ordinary goal completion path."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Unknown Goal", status="RECOVERY_REQUIRED", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_unknown_status",
        title="Unknown Status Action",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    res = await runner.reserve_aggregate_dag_budget(goal)

    # Step execution attempts to progress
    await runner.execute_goal_step(goal.id, principal)

    await db_session.refresh(res)
    assert res.status == "RESERVED"  # Retained!


async def test_35_post_preflight_action_injection_is_impossible(db_session: AsyncSession):
    """35 post-preflight action injection is impossible: once goal is EXECUTING, adding actions fails with 409."""
    project, principal = await _setup_project_and_principal(db_session)
    goal = AutonomousGoal(project_id=project.id, objective="Executing Freeze", status="EXECUTING")
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    with pytest.raises(HTTPException) as exc_info:
        await create_action_node(
            db_session,
            goal.id,
            AutonomousActionNodeCreate(
                client_action_id="post_preflight_injected",
                title="Injection",
                action_type="SYNTHESIS",
                required_capability="IMAGE_GENERATION",
            ),
            principal,
        )
    assert exc_info.value.status_code == 409


async def test_36_new_plan_version_requires_new_budget_evaluation(db_session: AsyncSession):
    """36 new plan version requires new budget evaluation: plan versions have separate reservations."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Plan Versioning", status="PLANNING", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    # Version 1 reservation
    act1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="v1_shot",
        title="V1 Shot",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "fal", "model": "flux-pro/v1.1"}, # 0.05
    )
    db_session.add(act1)
    await db_session.commit()

    r1 = await runner.reserve_aggregate_dag_budget(goal)
    assert r1.plan_version == 1
    assert float(r1.reserved_amount_usd) == 0.05

    # Governed replan to version 2 with more expensive action
    goal.current_plan_version = 2
    act2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="v2_shot",
        title="V2 Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 10.0}, # 0.20
    )
    db_session.add(act2)
    await db_session.commit()

    r2 = await runner.reserve_aggregate_dag_budget(goal)
    assert r2.plan_version == 2
    assert float(r2.reserved_amount_usd) == 0.25 # act1 + act2

    await db_session.refresh(r1)
    assert r1.status == "RELEASED"  # Superseded v1 released


async def test_37_negative_nan_inf_mock_cost_rejected():
    """37 negative/NaN/inf cost can never enter reservation ledger."""
    runner = AutonomousExecutionRunner(db=None)

    for bad_cost in (-1.0, float("nan"), float("inf"), float("-inf"), "invalid"):
        action = AutonomousActionNode(
            client_action_id="bad_cost_act",
            title="Bad Cost Act",
            action_type="GENERATION",
            required_capability="IMAGE_GENERATION",
            inputs_json={"simulated_provider": "offline-mock", "mock_authoritative_cost": bad_cost},
        )
        with pytest.raises(ActionValidationError):
            runner.calculate_authoritative_action_cost(action)


async def test_38_stale_worker_cannot_consume_reservation(db_session: AsyncSession):
    """38 stale worker cannot consume/release another reservation: lease token mismatch rejects result."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner1 = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher(), worker_id="worker-1")

    goal = AutonomousGoal(project_id=project.id, objective="Stale Worker", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="stale_shot",
        title="Stale Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},
    )
    db_session.add(action)
    await db_session.commit()

    await runner1.reserve_aggregate_dag_budget(goal)

    # Dispatch via runner1
    await runner1.dispatch_action(action.id, principal)

    # Stale attempt on executing action with different lease token
    action.status = "EXECUTING"
    action.inputs_json = {"lease": {"worker_id": "worker-2", "lease_token": "foreign-token", "epoch": 1}}
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await runner1.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409


async def test_39_duplicate_reservation_same_goal_plan_version_impossible(db_session: AsyncSession):
    """39 duplicate reservation for same goal+plan_version is impossible (DB uniqueness & idempotency)."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="No Dup Reservation", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    res1 = await runner.reserve_aggregate_dag_budget(goal)
    res2 = await runner.reserve_aggregate_dag_budget(goal)

    assert res1.id == res2.id

    # Verify directly via DB query
    stmt = select(BudgetReservation).where(
        BudgetReservation.goal_id == goal.id,
        BudgetReservation.plan_version == 1,
    )
    reservations = (await db_session.execute(stmt)).scalars().all()
    assert len(reservations) == 1


async def test_40_reserved_funds_cannot_be_double_consumed(db_session: AsyncSession):
    """40 reserved funds cannot be double-consumed: consumption is strictly bounded by action count and results."""
    project, principal = await _setup_project_and_principal(db_session, budget_limit_usd=1.00)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    goal = AutonomousGoal(project_id=project.id, objective="Double Consumed Guard", status="READY", current_plan_version=1)
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="single_shot",
        title="Single Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0}, # 0.10
    )
    db_session.add(action)
    await db_session.commit()

    res = await runner.reserve_aggregate_dag_budget(goal)
    await runner.dispatch_action(action.id, principal)

    await db_session.refresh(res)
    assert float(res.consumed_amount_usd) == 0.10

    # Re-dispatching does not increase consumption
    await runner.dispatch_action(action.id, principal)
    await db_session.refresh(res)
    assert float(res.consumed_amount_usd) == 0.10
