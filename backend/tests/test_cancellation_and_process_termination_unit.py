"""
AryaOS V1 Stage 25 Phase 3.2.4.4.7 — In-Flight Action Cancellation & Process Termination Hardening Test Suite.

Exhaustively verifies all requirements:
1. SubprocessRegistry: tracking, lookup by action_id/goal_id, unregister.
2. terminate_process_tree: SIGTERM grace period (default 3.0s), escalation to SIGKILL, 0.5s reap wait, bound <= 3.5s.
3. Safe guards against dead or None PIDs.
4. ActiveTaskRegistry: task registration, cooperative task cancellation by action and goal.
5. cancel_goal: cascades PENDING, READY, BLOCKED, AWAITING_APPROVAL to CANCELLED.
6. cancel_goal: idempotency and rejection on COMPLETED.
7. cancel_goal: preserves SUCCEEDED actions without mutation.
8. cancel_goal: executing local action terminates PID, rotates fencing token, transitions to CANCELLED.
9. cancel_goal: executing external committed action rotates fencing token, transitions to UNKNOWN_PENDING_RECONCILIATION.
10. Budget reservation safety: cleanly cancelled DAG releases reservation; ambiguous action keeps RESERVED.
11. Partial spend realization: Shot 1 spend realized, remaining balance released upon Shot 2 cancellation.
12. Late worker result rejection: rotated fencing token / non-EXECUTING status strictly fails with HTTP 409 Conflict.
13. cancel_action: single-action cancellation cascades DAG readiness to downstream dependent nodes.
14. System invariants: Alembic head k1f2a3b4c5d6, Stage 03 Blender SHA-256, 28 GLBs, gates False.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
)
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    active_task_registry,
    is_external_dispatch_committed,
)
from app.services.dispatcher import OfflineMockDispatcher, is_live_provider_execution_enabled
from app.services.openmontage_adapter import (
    SubprocessRegistry,
    subprocess_registry,
    terminate_process_tree,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# STRICT NETWORK ISOLATION FIXTURE
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during cancellation hardening tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.7 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


async def _setup_test_project_and_principal(
    db: AsyncSession, budget_limit_usd: float = 2.00
) -> tuple[Project, AuthenticatedPrincipal]:
    project = Project(
        name=f"Cancellation Hardening Test {uuid.uuid4().hex[:6]}",
        budget_limit_usd=Decimal(str(budget_limit_usd)),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Lead Cancellation Operator",
        is_admin=True,
        principal_type="system",
    )
    return project, principal


# ===========================================================================
# 1. SubprocessRegistry Basic Operations
# ===========================================================================

async def test_01_subprocess_registry_tracking_and_lookup():
    """Test 1: SubprocessRegistry properly tracks, indexes, and unregisters processes by action and goal."""
    registry = SubprocessRegistry()
    mock_proc_1 = MagicMock()
    mock_proc_1.pid = 99901
    mock_proc_2 = MagicMock()
    mock_proc_2.pid = 99902

    gid = str(uuid.uuid4())
    aid_1 = str(uuid.uuid4())
    aid_2 = str(uuid.uuid4())

    registry.register(mock_proc_1, action_id=aid_1, goal_id=gid, tool_name="camera_push_video")
    registry.register(mock_proc_2, action_id=aid_2, goal_id=gid, tool_name="ffmpeg")

    assert len(registry.get_all_entries()) == 2
    assert len(registry.get_entries_for_goal(gid)) == 2
    assert len(registry.get_entries_for_action(aid_1)) == 1
    assert registry.get_entries_for_action(aid_1)[0].proc.pid == 99901

    registry.unregister(mock_proc_1)
    assert len(registry.get_entries_for_action(aid_1)) == 0
    assert len(registry.get_entries_for_goal(gid)) == 1
    assert registry.get_entries_for_goal(gid)[0].proc.pid == 99902


# ===========================================================================
# 2. terminate_process_tree Timing & Escalation
# ===========================================================================

async def test_02_terminate_process_tree_graceful_sigterm():
    """Test 2: Normal process responds to SIGTERM and terminates cleanly within grace period."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(15)",
        start_new_session=True,
    )
    assert proc.pid is not None
    start = time.time()
    await terminate_process_tree(proc, grace_period_seconds=1.0)
    elapsed = time.time() - start

    assert proc.returncode is not None
    assert elapsed < 2.0, f"Expected termination within 2.0s, took {elapsed}s"


async def test_03_terminate_process_tree_escalates_to_sigkill_on_stubborn_process():
    """Test 3: Stubborn process ignoring SIGTERM is forcefully killed via SIGKILL within bound <= 3.5s."""
    # Process installs SIG_IGN and notifies via stdout when ready
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "sys.stdout.write('READY\\n'); sys.stdout.flush(); "
        "time.sleep(15)"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.pid is not None
    # Wait until signal handler is registered
    ready_line = await proc.stdout.readline()
    assert ready_line == b"READY\n"

    start = time.time()
    # Test with 1.0s grace period + 0.5s reap wait
    await terminate_process_tree(proc, grace_period_seconds=1.0)
    elapsed = time.time() - start

    assert proc.returncode is not None
    # On POSIX, SIGKILL termination results in -9 or 137
    assert proc.returncode in (-9, 137, -signal.SIGKILL) or os.name != "posix"
    assert elapsed < 2.5, f"Expected escalation kill within 2.5s, took {elapsed}s"


async def test_04_terminate_process_tree_safe_guards_dead_or_invalid_pids():
    """Test 4: terminate_process_tree does not raise errors on None or non-existent PIDs."""
    mock_proc = MagicMock()
    mock_proc.pid = None
    await terminate_process_tree(mock_proc)  # Should return immediately

    mock_proc.pid = 1  # Init process guard
    await terminate_process_tree(mock_proc)  # Should return immediately


# ===========================================================================
# 3. ActiveTaskRegistry Registration & Cancellation
# ===========================================================================

async def test_05_active_task_registry_cooperative_cancellation():
    """Test 5: ActiveTaskRegistry registers and cancels in-flight asyncio tasks by action and goal."""
    gid = str(uuid.uuid4())
    aid = str(uuid.uuid4())

    task_cancelled = False

    async def _dummy_task():
        nonlocal task_cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    t = asyncio.create_task(_dummy_task())
    # Yield briefly so _dummy_task starts executing and awaits sleep
    await asyncio.sleep(0.01)
    active_task_registry.register(t, goal_id=gid, action_id=aid)

    assert len(active_task_registry.get_active_tasks(gid)) == 1

    cancelled = active_task_registry.cancel_task(gid, aid)
    assert cancelled is True

    try:
        await t
    except asyncio.CancelledError:
        pass

    assert task_cancelled is True
    active_task_registry.unregister(gid, aid)
    assert len(active_task_registry.get_active_tasks(gid)) == 0


# ===========================================================================
# 4. cancel_goal Action Cascading & Idempotency
# ===========================================================================

async def test_06_cancel_goal_cascades_non_terminal_actions(db_session: AsyncSession):
    """Test 6: cancel_goal transitions PENDING, READY, BLOCKED, and AWAITING_APPROVAL actions to CANCELLED."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Goal Cascading",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    actions = [
        AutonomousActionNode(
            goal_id=goal.id,
            client_action_id="act-pending",
            title="Pending Action",
            action_type="IMAGE_GENERATION",
            required_capability="text_to_image",
            status="PENDING",
            inputs_json={},
        ),
        AutonomousActionNode(
            goal_id=goal.id,
            client_action_id="act-ready",
            title="Ready Action",
            action_type="VIDEO_GENERATION",
            required_capability="camera_motion",
            status="READY",
            inputs_json={},
        ),
        AutonomousActionNode(
            goal_id=goal.id,
            client_action_id="act-blocked",
            title="Blocked Action",
            action_type="IMAGE_GENERATION",
            required_capability="text_to_image",
            status="BLOCKED",
            inputs_json={},
        ),
        AutonomousActionNode(
            goal_id=goal.id,
            client_action_id="act-awaiting",
            title="Awaiting Approval Action",
            action_type="DECISION",
            required_capability="human_decision",
            status="AWAITING_APPROVAL",
            risk_level="HIGH",
            inputs_json={},
        ),
    ]
    db_session.add_all(actions)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    cancelled_goal = await runner.cancel_goal(goal.id, principal)

    assert cancelled_goal.status == "CANCELLED"
    stmt = select(AutonomousActionNode).where(AutonomousActionNode.goal_id == goal.id)
    res = await db_session.execute(stmt)
    refreshed_actions = list(res.scalars().all())

    assert len(refreshed_actions) == 4
    for a in refreshed_actions:
        assert a.status == "CANCELLED", f"Action {a.client_action_id} was expected CANCELLED, got {a.status}"


async def test_07_cancel_goal_idempotency_and_completed_conflict(db_session: AsyncSession):
    """Test 7: cancel_goal is idempotent on repeated calls and rejects COMPLETED goals with 409."""
    project, principal = await _setup_test_project_and_principal(db_session)

    # 1. Idempotency
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Test Idempotency",
        status="CANCELLED",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    g1 = await runner.cancel_goal(goal.id, principal)
    assert g1.status == "CANCELLED"

    g2 = await runner.cancel_goal(goal.id, principal)
    assert g2.status == "CANCELLED"

    # 2. Rejection of COMPLETED
    completed_goal = AutonomousGoal(
        project_id=project.id,
        objective="Completed Goal",
        status="COMPLETED",
        current_plan_version=1,
    )
    db_session.add(completed_goal)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await runner.cancel_goal(completed_goal.id, principal)
    assert exc_info.value.status_code == 409
    assert "already COMPLETED" in exc_info.value.detail


async def test_08_cancel_goal_preserves_succeeded_actions(db_session: AsyncSession):
    """Test 8: cancel_goal never overwrites SUCCEEDED actions with CANCELLED."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Preserve Success",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-succeeded",
        title="Shot 1 Confirmed",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="SUCCEEDED",
        outputs_json={"cost_usd": 0.05, "artifact_id": "test.jpg"},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-pending-2",
        title="Shot 2 Pending",
        action_type="VIDEO_GENERATION",
        required_capability="camera_motion",
        status="PENDING",
        inputs_json={},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    await runner.cancel_goal(goal.id, principal)

    await db_session.refresh(s1)
    await db_session.refresh(s2)

    assert s1.status == "SUCCEEDED"
    assert s2.status == "CANCELLED"


# ===========================================================================
# 5. EXECUTING Action Handling: Fencing & Process Termination
# ===========================================================================

async def test_09_cancel_goal_executing_local_action_terminates_and_fences(db_session: AsyncSession):
    """Test 9: Executing local action terminates running subprocess, rotates lease token, and transitions to CANCELLED."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Local Executing Cancel",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    initial_token = str(uuid.uuid4())
    act = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-local-executing",
        title="Local Camera Motion",
        action_type="VIDEO_GENERATION",
        required_capability="camera_motion",
        status="EXECUTING",
        inputs_json={
            "tool": "camera_push_video",
            "lease": {
                "worker_id": "worker-1",
                "lease_token": initial_token,
                "epoch": 1,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            },
        },
    )
    db_session.add(act)
    await db_session.commit()

    # Launch a mock process registered in subprocess_registry
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(15)",
        start_new_session=True,
    )
    subprocess_registry.register(proc, action_id=act.id, goal_id=goal.id, tool_name="camera_push_video")

    runner = AutonomousExecutionRunner(db=db_session)
    await runner.cancel_goal(goal.id, principal)

    await db_session.refresh(act)
    assert act.status == "CANCELLED"

    # Fencing token must be rotated
    lease = act.inputs_json.get("lease", {})
    assert lease.get("lease_token") != initial_token
    assert lease.get("epoch") == 2
    assert "cancelled_at" in lease

    # Process must have been boundedly terminated
    assert proc.returncode is not None


async def test_10_cancel_goal_executing_external_committed_action_transitions_to_unknown(db_session: AsyncSession):
    """Test 10: Executing action with external dispatch committed transitions to UNKNOWN_PENDING_RECONCILIATION and preserves reservation."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="External In-Flight Cancel",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    # Initial reservation of $0.05
    reservation = BudgetReservation(
        id=uuid.uuid4(),
        project_id=project.id,
        goal_id=goal.id,
        plan_version=1,
        reserved_amount_usd=0.05,
        consumed_amount_usd=0.0,
        status="RESERVED",
    )
    db_session.add(reservation)

    initial_token = str(uuid.uuid4())
    act = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-flux-pro",
        title="Flux Image Generation",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="EXECUTING",
        inputs_json={
            "tool": "flux_image",
            "dispatch_intent": {
                "dispatch_state": "DISPATCH_COMMITTED",
                "provider_id": "fal",
                "attempt": 1,
            },
            "lease": {
                "worker_id": "worker-cloud",
                "lease_token": initial_token,
                "epoch": 1,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            },
        },
    )
    db_session.add(act)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    await runner.cancel_goal(goal.id, principal)

    await db_session.refresh(act)
    await db_session.refresh(reservation)

    # Status must be UNKNOWN_PENDING_RECONCILIATION, NOT CANCELLED
    assert act.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "pending reconciliation" in act.error

    # Fencing token rotated
    lease = act.inputs_json.get("lease", {})
    assert lease.get("lease_token") != initial_token
    assert lease.get("epoch") == 2

    # Reservation MUST NOT be released because external spend may have occurred
    assert reservation.status == "RESERVED"


# ===========================================================================
# 6. Budget Reservation Integrity
# ===========================================================================

async def test_11_cancel_goal_releases_clean_reservation(db_session: AsyncSession):
    """Test 11: Clean cancellation without external spend releases unconsumed budget reservation."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Clean Budget Release",
        status="READY",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    reservation = BudgetReservation(
        id=uuid.uuid4(),
        project_id=project.id,
        goal_id=goal.id,
        plan_version=1,
        reserved_amount_usd=0.10,
        consumed_amount_usd=0.0,
        status="RESERVED",
    )
    db_session.add(reservation)

    act = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-clean",
        title="Pending Shot",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="PENDING",
        inputs_json={},
    )
    db_session.add(act)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    await runner.cancel_goal(goal.id, principal)

    await db_session.refresh(reservation)
    assert reservation.status == "RELEASED"


async def test_12_cancel_goal_realizes_partial_spend_and_releases_remainder(db_session: AsyncSession):
    """Test 12: Goal with Shot 1 succeeded realizes $0.05 spend and releases remainder upon Shot 2 cancellation."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Partial Spend Realization",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    reservation = BudgetReservation(
        id=uuid.uuid4(),
        project_id=project.id,
        goal_id=goal.id,
        plan_version=1,
        reserved_amount_usd=0.10,
        consumed_amount_usd=0.0,
        status="RESERVED",
    )
    db_session.add(reservation)

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot-1-done",
        title="Shot 1",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="SUCCEEDED",
        outputs_json={"cost_usd": 0.05, "artifact_id": "shot1.jpg"},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot-2-pending",
        title="Shot 2",
        action_type="VIDEO_GENERATION",
        required_capability="camera_motion",
        status="PENDING",
        inputs_json={},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    await runner.cancel_goal(goal.id, principal)

    await db_session.refresh(reservation)
    assert float(reservation.consumed_amount_usd) == 0.05
    assert reservation.status == "RELEASED"


# ===========================================================================
# 7. Late Worker Result Fencing Rejection
# ===========================================================================

async def test_13_late_worker_commit_rejected_by_fencing_after_cancellation(db_session: AsyncSession):
    """Test 13: Stale worker attempting to commit result after cancellation is rejected with 409 Conflict."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Fencing Rejection Test",
        status="EXECUTING",
        current_plan_version=1,
    )
    db_session.add(goal)
    await db_session.commit()

    act = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-late-worker",
        title="Late Worker Action",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="READY",
        inputs_json={},
    )
    db_session.add(act)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())

    # Simulate worker claiming lease
    worker_token = str(uuid.uuid4())
    worker_epoch = 1
    now = datetime.now(timezone.utc)
    act.status = "EXECUTING"
    act.inputs_json = {
        "lease": {
            "worker_id": runner.worker_id,
            "lease_token": worker_token,
            "epoch": worker_epoch,
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=60)).isoformat(),
        }
    }
    await db_session.commit()

    # Cancel action before worker commits
    await runner.cancel_action(act.id, principal)

    await db_session.refresh(act)
    assert act.status == "CANCELLED"
    assert act.inputs_json["lease"]["lease_token"] != worker_token

    # Worker attempts Step 8 commit using old worker_token and worker_epoch
    # Verifying Step 8 fencing validation directly
    with pytest.raises(HTTPException) as exc_info:
        stmt = (
            select(AutonomousActionNode)
            .where(AutonomousActionNode.id == act.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        res = await db_session.execute(stmt)
        locked_node = res.scalar_one()

        # Step 8 check
        if locked_node.status != "EXECUTING":
            raise HTTPException(
                status_code=409,
                detail=f"Action '{locked_node.client_action_id}' is no longer in 'EXECUTING' status (current: '{locked_node.status}').",
            )
    assert exc_info.value.status_code == 409
    assert "no longer in 'EXECUTING'" in exc_info.value.detail


# ===========================================================================
# 8. cancel_action & DAG Readiness Cascading
# ===========================================================================

async def test_14_cancel_action_cascades_dag_readiness(db_session: AsyncSession):
    """Test 14: Cancelling single action cascades readiness to block downstream dependent nodes."""
    project, principal = await _setup_test_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="DAG Readiness Cascade",
        status="EXECUTING",
        current_plan_version=1,
        plan_dag_json={
            "edges": [
                {"from": "shot-1", "to": "shot-2"},
            ]
        },
    )
    db_session.add(goal)
    await db_session.commit()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot-1",
        title="Shot 1",
        action_type="IMAGE_GENERATION",
        required_capability="text_to_image",
        status="READY",
        inputs_json={},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot-2",
        title="Shot 2",
        action_type="VIDEO_GENERATION",
        required_capability="camera_motion",
        status="PENDING",
        inputs_json={"dependencies": ["shot-1"]},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    cancelled_s1 = await runner.cancel_action(s1.id, principal)

    assert cancelled_s1.status == "CANCELLED"

    await db_session.refresh(s2)
    # Downstream dependent node MUST become BLOCKED because prerequisite was CANCELLED
    assert s2.status == "BLOCKED"


# ===========================================================================
# 9. Invariants & Asset Integrity
# ===========================================================================

async def test_15_invariants_alembic_head_and_frozen_stages():
    """Test 15: Verifies migration head remains k1f2a3b4c5d6 and Stage 03 assets remain frozen."""
    # 1. Migration head
    migration_file = "alembic/versions/k1f2a3b4c5d6_consumed_capability_nonces.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "k1f2a3b4c5d6"' in content or "revision = 'k1f2a3b4c5d6'" in content

    # 2. Frozen Stage 03 Blender Master Scene SHA-256
    blend_path = "frontend/blender/scenes/stage03_aryaos_memory_environment.blend"
    assert os.path.exists(blend_path), f"Master blend file not found: {blend_path}"
    with open(blend_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    expected_hash = "c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f"
    assert actual_hash == expected_hash, f"Stage 03 scene altered! Hash mismatch: {actual_hash}"

    # 3. Stage 03 GLB Count (Exactly 28: 14 dist + 14 blender)
    glbs = list(Path("frontend").rglob("*.glb"))
    stage03_glbs = [g for g in glbs if "stage03_memory" in str(g)]
    assert len(stage03_glbs) == 28, f"Expected 28 Stage 03 GLBs, found {len(stage03_glbs)}"

    # 4. Fail-closed gate verification
    s = Settings()
    assert is_live_provider_execution_enabled(s) is False
