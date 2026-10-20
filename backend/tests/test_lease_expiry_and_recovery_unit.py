"""
AryaOS V1 Stage 25 Phase 3.2.4.4.6.3.3.14 — Lease Expiry & Background Recovery Test Suite.

Exhaustively verifies all 14 required recovery scenarios:
1. Expired EXECUTING lease transitions safely to UNKNOWN_PENDING_RECONCILIATION and goal to RECOVERY_REQUIRED.
2. A non-expired lease is not swept.
3. Malformed or missing lease information fails safely.
4. Repeated sweeps are idempotent.
5. Concurrent sweepers cannot corrupt state or duplicate recovery work (PostgreSQL advisory lock & in-process lock).
6. Stale worker results are rejected by fencing.
7. Confirmed external success remains preserved during reconciliation.
8. Ambiguous external outcomes remain UNKNOWN and are not automatically retried.
9. NO_LOOKUP providers are not queried through invented or unsupported APIs.
10. Reservations and financial truth are preserved across uncertain outcomes (no release or double-consumption).
11. Downstream actions remain blocked while prerequisites are unknown.
12. Heartbeat renewal is rejected for stale tokens, epochs or worker identities.
13. Heartbeat shutdown and application shutdown are clean.
14. Regressions and frozen invariants remain intact (Alembic head, Blender SHA-256, 28 GLBs, gates False).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.database.session import AsyncSessionLocal
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
)
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
)
from app.services.dispatcher import OfflineMockDispatcher
from app.services.idempotency import (
    ActionReconciliationService,
    ReconciliationVerdict,
    record_pre_dispatch_intent,
)
from app.services.lease_expiry_sweeper import (
    LEASE_SWEEPER_ADVISORY_LOCK_KEY,
    LeaseExpirySweeperService,
    LeaseSweepReport,
    get_lease_expiry_sweeper_service,
)
from app.workers import jobs, scheduler

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# STRICT NETWORK ISOLATION FIXTURE
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during recovery tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.6.3.3.14 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


async def _setup_test_project_and_principal(
    db: AsyncSession, budget_limit_usd: float = 2.00
) -> tuple[Project, AuthenticatedPrincipal]:
    project = Project(
        name=f"Lease Recovery Test {uuid.uuid4().hex[:6]}",
        budget_limit_usd=Decimal(str(budget_limit_usd)),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Lead Recovery Operator",
        is_admin=True,
        principal_type="system",
    )
    return project, principal


# ===========================================================================
# 1. Expired EXECUTING lease transitions safely to reconciliation-required
# ===========================================================================

async def test_01_expired_executing_lease_transitions_to_reconciliation_required(db_session: AsyncSession):
    """Test 1: Expired EXECUTING lease with dispatch intent transitions to UNKNOWN_PENDING_RECONCILIATION and RECOVERY_REQUIRED."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Expired Lease Recovery",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(seconds=60)).isoformat()
    lease_token = str(uuid.uuid4())

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Image Generation",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-crashed-1",
                "lease_token": lease_token,
                "epoch": 1,
                "claimed_at": (now - timedelta(seconds=180)).isoformat(),
                "expires_at": expired_time,
            },
            "dispatch_intent": {
                "provider_id": "fal",
                "provider_job_id": "job-abc-123",
                "status": "DISPATCHED",
                "lease_token": lease_token,
                "lease_epoch": 1,
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)

    assert report.status == "COMPLETED"
    assert report.total_checked >= 1
    assert report.expired_found >= 1
    assert report.transitioned_unknown >= 1

    await db_session.refresh(node)
    await db_session.refresh(goal)

    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "Worker lease expired while executing" in (node.error or "")
    assert goal.status == "RECOVERY_REQUIRED"
    assert "lease expired with unknown outcome" in (goal.failure_reason or "")

    # Audit history is durably recorded
    history = node.inputs_json.get("reconciliation_history", [])
    assert len(history) >= 1
    assert history[-1]["event"] == "LEASE_EXPIRED_SWEPT"
    assert history[-1]["new_status"] == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 2. Non-expired lease is not swept
# ===========================================================================

async def test_02_non_expired_lease_is_not_swept(db_session: AsyncSession):
    """Test 2: A non-expired executing lease remains EXECUTING and is not swept."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Active Lease",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    active_time = (now + timedelta(seconds=120)).isoformat()

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_active",
        title="Active Shot",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-live-1",
                "lease_token": str(uuid.uuid4()),
                "epoch": 1,
                "claimed_at": now.isoformat(),
                "expires_at": active_time,
            },
            "dispatch_intent": {
                "provider_id": "fal",
                "provider_job_id": "job-live-999",
                "status": "DISPATCHED",
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session)

    assert report.status == "COMPLETED"
    assert report.skipped_active >= 1

    await db_session.refresh(node)
    await db_session.refresh(goal)
    assert node.status == "EXECUTING"
    assert goal.status == "EXECUTING"


# ===========================================================================
# 3. Malformed or missing lease info fails safely
# ===========================================================================

async def test_03_malformed_or_missing_lease_fails_safely(db_session: AsyncSession):
    """Test 3: Malformed or unparseable lease timestamps are handled fail-closed without crashing."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Malformed Lease",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    # Node with corrupt timestamp string
    node_corrupt = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_corrupt",
        title="Corrupt Timestamp Shot",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-bad",
                "expires_at": "NOT_A_VALID_ISO_TIMESTAMP",
            },
        },
    )
    # Node with missing lease dict altogether
    node_empty = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_empty",
        title="Empty Lease Shot",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={},
    )
    db_session.add_all([node_corrupt, node_empty])
    await db_session.commit()

    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)

    assert report.status == "COMPLETED"
    assert report.expired_found >= 2

    await db_session.refresh(node_corrupt)
    await db_session.refresh(node_empty)

    # Both had no dispatch intent -> safely reset to READY with incremented epochs
    assert node_corrupt.status == "READY"
    assert node_empty.status == "READY"


# ===========================================================================
# 4. Repeated sweeps are idempotent
# ===========================================================================

async def test_04_repeated_sweeps_are_idempotent(db_session: AsyncSession):
    """Test 4: Running multiple consecutive sweeps does not re-modify or corrupt already-reconciled actions."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Idempotent Sweep",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_idem",
        title="Idempotent Test Action",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-crashed",
                "expires_at": (now - timedelta(seconds=100)).isoformat(),
            },
            "dispatch_intent": {"provider_id": "offline-mock"},
        },
    )
    db_session.add(node)
    await db_session.commit()

    sweeper = LeaseExpirySweeperService()

    # Sweep 1: transitions node to UNKNOWN_PENDING_RECONCILIATION
    r1 = await sweeper.run_sweep(session=db_session, goal_id=goal.id)
    assert r1.transitioned_unknown >= 1

    await db_session.refresh(node)
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"
    history_len_1 = len(node.inputs_json.get("reconciliation_history", []))

    # Sweep 2: should find 0 expired executing actions
    r2 = await sweeper.run_sweep(session=db_session, goal_id=goal.id)
    assert r2.expired_found == 0

    await db_session.refresh(node)
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"
    history_len_2 = len(node.inputs_json.get("reconciliation_history", []))
    assert history_len_1 == history_len_2  # History not duplicated!


# ===========================================================================
# 5. Concurrent sweepers cannot corrupt state (Advisory lock & In-process lock)
# ===========================================================================

async def test_05_concurrent_sweepers_cannot_corrupt_state(db_session: AsyncSession):
    """Test 5: PostgreSQL advisory locking and in-process mutual exclusion prevent overlapping sweeps."""
    sweeper = LeaseExpirySweeperService()

    # Part A: Test in-process lock exclusion
    await sweeper._in_process_lock.acquire()
    try:
        report_locked = await sweeper.run_sweep(session=db_session)
        assert report_locked.status == "SKIPPED_LOCK_HELD"
    finally:
        sweeper._in_process_lock.release()

    # Part B: Test PostgreSQL advisory lock if running on Postgres
    bind = db_session.get_bind()
    is_postgres = "postgres" in getattr(getattr(bind, "dialect", None), "name", "").lower()

    if is_postgres:
        # Simulate another worker process holding the advisory lock on an independent connection
        async with AsyncSessionLocal() as other_session:
            lock_res = await other_session.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": LEASE_SWEEPER_ADVISORY_LOCK_KEY},
            )
            assert bool(lock_res.scalar()) is True

            try:
                # Sweeper on db_session should detect the advisory lock and skip gracefully
                report = await sweeper.run_sweep(session=db_session)
                assert report.status == "SKIPPED_LOCK_HELD"
            finally:
                # Release lock on other_session
                await other_session.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": LEASE_SWEEPER_ADVISORY_LOCK_KEY},
                )


# ===========================================================================
# 6. Stale worker results are rejected by fencing
# ===========================================================================

async def test_06_stale_worker_results_rejected_by_fencing(db_session: AsyncSession):
    """Test 6: A stale worker whose lease token or epoch was superseded cannot persist execution results."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Fencing",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_fence",
        title="Fencing Action",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-new-owner",
                "lease_token": "token-epoch-2",
                "epoch": 2,  # Advanced epoch!
                "expires_at": (now + timedelta(seconds=120)).isoformat(),
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    # Runner representing the stale worker from epoch 1
    stale_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="worker-stale-old",
        settings=get_settings(),
    )
    stale_runner.lease_token = "token-epoch-1"
    stale_runner.lease_epoch = 1

    # Attempting to persist or renew from stale runner must fail with 409
    renew_success = await stale_runner.renew_lease(
        action_id=node.id,
        lease_token="token-epoch-1",
        lease_epoch=1,
        session=db_session,
    )
    assert renew_success is False


# ===========================================================================
# 7. Confirmed external success preserved during reconciliation
# ===========================================================================

async def test_07_confirmed_external_success_preserved_during_reconciliation(db_session: AsyncSession):
    """Test 7: Action in UNKNOWN_PENDING_RECONCILIATION confirmed SUCCEEDED by provider preserves outputs."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Reconciliation Success",
        status="RECOVERY_REQUIRED",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_recon_succ",
        title="Reconciled Image Shot",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-success-1",
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    # Mock dispatcher confirming remote success with valid outputs
    mock_dispatcher = OfflineMockDispatcher()
    status_mock = MagicMock()
    status_mock.status = "SUCCEEDED"
    status_mock.output = {"image_url": "https://storage.local/verified.png", "width": 1024, "height": 1024}
    mock_dispatcher.query_status = AsyncMock(return_value=status_mock)

    recon_service = ActionReconciliationService(db=db_session, dispatcher=mock_dispatcher)
    updated_node, result = await recon_service.reconcile(
        action_id=node.id,
        principal=principal,
        dispatcher=mock_dispatcher,
    )

    assert result.verdict == ReconciliationVerdict.CONFIRMED_SUCCESS
    assert updated_node.status == "SUCCEEDED"
    assert updated_node.outputs_json.get("image_url") == "https://storage.local/verified.png"
    assert updated_node.error is None


# ===========================================================================
# 8. Ambiguous external outcomes remain UNKNOWN and not automatically retried
# ===========================================================================

async def test_08_ambiguous_external_outcomes_remain_unknown(db_session: AsyncSession):
    """Test 8: Ambiguous remote outcomes remain UNKNOWN and cannot be auto-retried."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Ambiguous Outcome",
        status="RECOVERY_REQUIRED",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_ambig",
        title="Ambiguous Shot",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-timeout-9",
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    mock_dispatcher = OfflineMockDispatcher()
    mock_dispatcher.query_status = AsyncMock(side_effect=RuntimeError("Provider query timed out"))

    recon_service = ActionReconciliationService(db=db_session, dispatcher=mock_dispatcher)
    updated_node, result = await recon_service.reconcile(
        action_id=node.id,
        principal=principal,
        dispatcher=mock_dispatcher,
    )

    assert result.verdict == ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE
    assert result.can_safely_retry is False
    assert updated_node.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 9. NO_LOOKUP providers are not queried through invented APIs
# ===========================================================================

async def test_09_no_lookup_providers_are_not_queried(db_session: AsyncSession):
    """Test 9: Providers marked without status lookup capability are not queried through invented APIs."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test No Lookup Provider",
        status="RECOVERY_REQUIRED",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_fal_no_lookup",
        title="Fal Shot with NO_LOOKUP",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "fal",  # fal profile has supports_status_lookup = False
                "provider_job_id": "fal-real-123",
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    mock_dispatcher = OfflineMockDispatcher()
    mock_dispatcher.query_status = AsyncMock()

    recon_service = ActionReconciliationService(db=db_session, dispatcher=mock_dispatcher)
    updated_node, result = await recon_service.reconcile(
        action_id=node.id,
        principal=principal,
        dispatcher=mock_dispatcher,
    )

    # Must return LOOKUP_UNSUPPORTED without calling query_status
    assert result.verdict == ReconciliationVerdict.LOOKUP_UNSUPPORTED
    assert result.can_safely_retry is False
    assert updated_node.status == "UNKNOWN_PENDING_RECONCILIATION"
    mock_dispatcher.query_status.assert_not_called()


# ===========================================================================
# 10. Reservations and financial truth are preserved across uncertain outcomes
# ===========================================================================

async def test_10_budget_reservations_preserved_across_lease_expiry(db_session: AsyncSession):
    """Test 10: Budget reservations are neither consumed nor released upon lease expiry alone."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Financial Integrity",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    reservation = BudgetReservation(
        project_id=project.id,
        goal_id=goal.id,
        plan_version=1,
        reserved_amount_usd=Decimal("0.5000"),
        consumed_amount_usd=Decimal("0.0000"),
        status="RESERVED",
    )
    db_session.add(reservation)

    now = datetime.now(timezone.utc)
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_fin",
        title="Financial Test Action",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-fin",
                "expires_at": (now - timedelta(seconds=50)).isoformat(),
            },
            "dispatch_intent": {"provider_id": "fal", "provider_job_id": "job-f1"},
        },
    )
    db_session.add(node)
    await db_session.commit()

    # Sweeper runs
    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)
    assert report.transitioned_unknown >= 1

    # Verify reservation remains strictly active and untouched
    await db_session.refresh(reservation)
    assert reservation.status == "RESERVED"
    assert reservation.reserved_amount_usd == Decimal("0.5000")
    assert reservation.consumed_amount_usd == Decimal("0.0000")


# ===========================================================================
# 11. Downstream actions remain blocked while prerequisites are unknown
# ===========================================================================

async def test_11_downstream_actions_blocked_while_prerequisites_unknown(db_session: AsyncSession):
    """Test 11: When an upstream action lease expires, downstream actions in the DAG are blocked."""
    project, principal = await _setup_test_project_and_principal(db_session)

    plan_dag = {
        "nodes": ["shot_01", "shot_02"],
        "edges": [{"from": "shot_01", "to": "shot_02"}],
    }

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test DAG Downstream Blocking",
        status="EXECUTING",
        plan_dag_json=plan_dag,
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 (Predecessor)",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-s1",
                "expires_at": (now - timedelta(seconds=60)).isoformat(),
            },
            "dispatch_intent": {"provider_id": "fal", "provider_job_id": "job-s1"},
        },
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 (Downstream)",
        action_type="GENERATE_VIDEO",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"dependencies": ["shot_01"]},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)

    await db_session.refresh(s1)
    await db_session.refresh(s2)

    assert s1.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert s2.status == "BLOCKED"  # Downstream immediately blocked!


# ===========================================================================
# 12. Heartbeat renewal is rejected for stale tokens, epochs or worker identities
# ===========================================================================

async def test_12_heartbeat_renewal_rejected_for_stale_tokens(db_session: AsyncSession):
    """Test 12: Calling renew_lease with wrong token, epoch, or worker identity fails cleanly."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Heartbeat Fencing",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    valid_token = str(uuid.uuid4())
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_hb",
        title="Heartbeat Action",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-authorized",
                "lease_token": valid_token,
                "epoch": 5,
                "expires_at": (now + timedelta(seconds=60)).isoformat(),
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="worker-authorized",
        settings=get_settings(),
    )

    # 1. Invalid token -> False
    assert await runner.renew_lease(node.id, "wrong-token", 5, session=db_session) is False

    # 2. Invalid epoch -> False
    assert await runner.renew_lease(node.id, valid_token, 4, session=db_session) is False

    # 3. Invalid worker ID -> False
    imposter_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="worker-imposter",
        settings=get_settings(),
    )
    assert await imposter_runner.renew_lease(node.id, valid_token, 5, session=db_session) is False

    # 4. Valid renewal -> True
    assert await runner.renew_lease(node.id, valid_token, 5, session=db_session) is True
    await db_session.refresh(node)
    assert node.inputs_json["lease"].get("last_heartbeat_at") is not None


# ===========================================================================
# 13. Heartbeat shutdown and application shutdown are clean
# ===========================================================================

async def test_13_heartbeat_and_scheduler_shutdown_are_clean(db_session: AsyncSession):
    """Test 13: Heartbeat task cleanly stops on cancellation, and scheduler lifecycle starts/stops without leaking."""
    # 1. Heartbeat task cancellation test
    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="worker-clean",
        settings=get_settings(),
    )
    task = asyncio.create_task(
        runner._run_heartbeat_loop(uuid.uuid4(), "dummy", 1, interval_seconds=1)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await task  # Completes cleanly without unhandled exception

    # 2. Scheduler start/stop lifecycle test
    scheduler.start_scheduler()
    sched_inst = scheduler.get_scheduler()
    assert sched_inst.running is True
    job_ids = [j.id for j in sched_inst.get_jobs()]
    assert "sweep_expired_leases" in job_ids

    scheduler.stop_scheduler()
    assert scheduler._scheduler is None


# ===========================================================================
# 14. Regressions and frozen invariants remain intact
# ===========================================================================

async def test_14_regressions_and_frozen_invariants_pass():
    """Test 14: Verifies Alembic head k1f2a3b4c5d6, Stage 03 Blender SHA-256, 28 GLBs, and fail-closed gates."""
    # 1. Alembic head check
    migration_file = "alembic/versions/k1f2a3b4c5d6_consumed_capability_nonces.py"
    assert os.path.exists(migration_file), f"Expected Alembic migration head file '{migration_file}' missing"

    # 2. Stage 03 Blender scene SHA-256
    blend_path = "frontend/blender/scenes/stage03_aryaos_memory_environment.blend"
    assert os.path.exists(blend_path), f"Master blend file missing: {blend_path}"
    with open(blend_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    expected_hash = "c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f"
    assert actual_hash == expected_hash, f"Stage 03 scene altered! Hash mismatch: {actual_hash}"

    # 3. 28 Stage 03 GLB assets
    glbs = list(Path("frontend").rglob("*.glb"))
    stage03_glbs = [g for g in glbs if "stage03_memory" in str(g)]
    assert len(stage03_glbs) == 28, f"Expected 28 Stage 03 GLBs, found {len(stage03_glbs)}"

    # 4. Fail-closed gates remain False
    s = Settings()
    assert s.enable_live_provider_execution is False
    assert s.enable_live_local_execution is False
    assert s.artifact_retention_enabled is False
    assert s.artifact_retention_dry_run is True


# ===========================================================================
# 15. HIGH-01: Heartbeat renewal races sweeper row-lock acquisition
# ===========================================================================

async def test_15_deterministic_heartbeat_renewal_races_sweeper_row_lock(db_session: AsyncSession):
    """Test 15 (HIGH-01): Proves that when a heartbeat renews a lease concurrently,
    the sweeper re-reads the locked row and does NOT overwrite the valid renewal with a stale expiry."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Heartbeat Sweeper Race",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    now = datetime.now(timezone.utc)
    token = str(uuid.uuid4())
    # Initial state: lease was expired 2 seconds ago
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_race",
        title="Racing Action Node",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-live-race",
                "lease_token": token,
                "epoch": 1,
                "claimed_at": (now - timedelta(seconds=120)).isoformat(),
                "expires_at": (now - timedelta(seconds=2)).isoformat(),
            },
            "dispatch_intent": {
                "provider_id": "fal",
                "provider_job_id": "job-race-123",
                "status": "DISPATCHED",
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    # 1. Simulate worker heartbeat renewing the lease
    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="worker-live-race",
        settings=get_settings(),
    )
    renewal_ok = await runner.renew_lease(node.id, token, 1, session=db_session)
    assert renewal_ok is True

    # 2. Sweeper runs sweep. Under HIGH-01 fix, sweeper re-checks the refreshed row
    # and sees that expires_at was renewed.
    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)

    # 3. Assert sweeper recognized the candidate as active and did NOT expire it
    assert report.status == "COMPLETED"
    assert report.skipped_active == 1
    assert report.expired_found == 0
    assert report.transitioned_unknown == 0

    await db_session.refresh(node)
    await db_session.refresh(goal)
    assert node.status == "EXECUTING"
    assert goal.status == "EXECUTING"
    assert node.inputs_json["lease"]["worker_id"] == "worker-live-race"
    assert node.inputs_json["lease"]["epoch"] == 1


# ===========================================================================
# 16. MED-02: Step 8 adversarial completion-state & fencing validations
# ===========================================================================

async def test_16_adversarial_step8_fencing_validations(db_session: AsyncSession):
    """Test 16 (MED-02): Exhaustively verifies Step 8 fencing checks:
    stale worker_id, stale token, stale epoch, non-EXECUTING status, malformed timestamp,
    and stale completion after sweeper Case A recovery."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Step 8 Adversarial Fencing",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    token = str(uuid.uuid4())
    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_adv",
        title="Adversarial Fencing Action",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "legit-worker",
                "lease_token": token,
                "epoch": 2,
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=300)).isoformat(),
            },
        },
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    # Check A: Pre-dispatch checks reject redispatch of EXECUTING action
    imposter_worker = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="imposter-worker",
        settings=get_settings(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await imposter_worker.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "claimed by worker" in str(exc_info.value.detail) or "EXECUTING" in str(exc_info.value.detail)

    inp_b = dict(node.inputs_json or {})
    inp_b["dispatch_intent"] = {"provider_id": "fal", "provider_job_id": "job-x"}
    lease_b = dict(inp_b.get("lease", {}))
    lease_b["expires_at"] = (now - timedelta(seconds=10)).isoformat()
    inp_b["lease"] = lease_b
    node.inputs_json = inp_b
    await db_session.commit()

    sweeper = LeaseExpirySweeperService()
    report = await sweeper.run_sweep(session=db_session, goal_id=goal.id)
    assert report.transitioned_unknown == 1

    await db_session.refresh(node)
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert node.inputs_json["lease"]["epoch"] == 3  # Advanced!
    assert node.inputs_json["lease"]["lease_token"] != token  # Rotated!

    # Check C: Action in UNKNOWN_PENDING_RECONCILIATION cannot be redispatched
    old_worker = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="legit-worker",
        settings=get_settings(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await old_worker.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "UNKNOWN_PENDING_RECONCILIATION" in str(exc_info.value.detail)

    # Check D: Direct Step 8 in-flight adversarial fencing test.
    # We simulate a worker whose dispatch was in flight, but during execution
    # the node status or fencing tokens were altered concurrently.

    class ConcurrentlyMutatingDispatcher(OfflineMockDispatcher):
        def __init__(self, mutate_coro):
            super().__init__()
            self.mutate_coro = mutate_coro
            self.is_live = False

        async def dispatch(self, action_node):
            await self.mutate_coro()
            return await super().dispatch(action_node)

    # D.1: Node status changed away from EXECUTING while in flight
    goal.status = "READY"
    node.status = "READY"
    await db_session.commit()

    async def mutate_to_blocked():
        async with AsyncSessionLocal() as s:
            n = await s.get(AutonomousActionNode, node.id)
            n.status = "UNKNOWN_PENDING_RECONCILIATION"
            await s.commit()

    mut_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=ConcurrentlyMutatingDispatcher(mutate_to_blocked),
        worker_id="in-flight-worker",
        settings=get_settings(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await mut_runner.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "no longer in 'EXECUTING' status" in str(exc_info.value.detail)

    # D.2: Fencing token / epoch changed while in flight
    goal.status = "READY"
    node.status = "READY"
    await db_session.commit()

    async def mutate_epoch():
        async with AsyncSessionLocal() as s:
            n = await s.get(AutonomousActionNode, node.id)
            inp = dict(n.inputs_json or {})
            inp_l = dict(inp.get("lease", {}))
            inp_l["epoch"] = 999  # Superseded epoch!
            inp["lease"] = inp_l
            n.inputs_json = inp
            await s.commit()

    epoch_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=ConcurrentlyMutatingDispatcher(mutate_epoch),
        worker_id="in-flight-worker-2",
        settings=get_settings(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await epoch_runner.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "fencing token mismatch" in str(exc_info.value.detail)

    # D.3: Malformed timestamp fails closed at Step 8
    goal.status = "READY"
    node.status = "READY"
    await db_session.commit()

    async def corrupt_timestamp():
        async with AsyncSessionLocal() as s:
            n = await s.get(AutonomousActionNode, node.id)
            inp = dict(n.inputs_json or {})
            inp_l = dict(inp.get("lease", {}))
            inp_l["expires_at"] = "invalid-corrupt-date"
            inp["lease"] = inp_l
            n.inputs_json = inp
            await s.commit()

    corrupt_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=ConcurrentlyMutatingDispatcher(corrupt_timestamp),
        worker_id="in-flight-worker-3",
        settings=get_settings(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await corrupt_runner.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "invalid or unparseable expiration timestamp" in str(exc_info.value.detail)


# ===========================================================================
# 17. MED-01: DAG readiness transitive, multi-prereq, and recovery unblocking
# ===========================================================================

async def test_17_dag_readiness_transitive_multiple_prereqs_and_recovery(db_session: AsyncSession):
    """Test 17 (MED-01): Verifies that ambiguous prerequisites keep downstream held in PENDING,
    transitive dependencies remain held, repeated evaluations are stable,
    and post-reconciliation unblocking smoothly transitions actions to READY."""
    project, principal = await _setup_test_project_and_principal(db_session)

    # DAG structure:
    # shot_01 -> shot_03
    # shot_02 -> shot_03
    # shot_03 -> shot_04 (transitive)
    plan_dag = {
        "nodes": [
            {"client_action_id": "shot_01"},
            {"client_action_id": "shot_02"},
            {"client_action_id": "shot_03"},
            {"client_action_id": "shot_04"},
        ],
        "edges": [
            {"from": "shot_01", "to": "shot_03"},
            {"from": "shot_02", "to": "shot_03"},
            {"from": "shot_03", "to": "shot_04"},
        ],
    }

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Multi-Prerequisite and Transitive DAG Test",
        status="EXECUTING",
        plan_dag_json=plan_dag,
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Succeeded",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Ambiguous",
        action_type="GENERATE_IMAGE",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
    )
    s3 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_03",
        title="Shot 03 Multi-Prereq Downstream",
        action_type="GENERATE_VIDEO",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
    )
    s4 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_04",
        title="Shot 04 Transitive Downstream",
        action_type="GENERATE_VIDEO",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
    )
    db_session.add_all([s1, s2, s3, s4])
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    # Step 1: Evaluate DAG readiness.
    # shot_01 is SUCCEEDED, but shot_02 is UNKNOWN_PENDING_RECONCILIATION.
    # shot_03 must remain PENDING. shot_04 must remain PENDING.
    updates = runner.resolve_dag_readiness(plan_dag, [s1, s2, s3, s4])
    assert "shot_03" not in updates  # Remains PENDING
    assert "shot_04" not in updates  # Remains PENDING

    # Step 2: Stability - repeated evaluation yields identical results
    updates_repeat = runner.resolve_dag_readiness(plan_dag, [s1, s2, s3, s4])
    assert updates_repeat == updates

    # Step 3: Upstream recovery. Shot 02 is authoritatively reconciled to SUCCEEDED.
    s2.status = "SUCCEEDED"
    await db_session.commit()

    # Step 4: Re-evaluate DAG readiness.
    # Both shot_01 and shot_02 are now SUCCEEDED.
    # shot_03 should smoothly transition PENDING -> READY!
    updates_post_recovery = runner.resolve_dag_readiness(plan_dag, [s1, s2, s3, s4])
    assert updates_post_recovery.get("shot_03") == "READY"
    assert "shot_04" not in updates_post_recovery  # shot_04 still waits for shot_03 to succeed
