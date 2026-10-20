"""
AryaOS V1 Stage 25 Phase 3.2.3 — Idempotency Engine & Durable Reconciliation Test Suite.

Verifies mandatory Phase 3.2.3 safety invariants:
1. Stable idempotency identities across retries and worker restarts.
2. Context binding: idempotency key bound to project, goal, and action identity; server authority cannot be overridden by client.
3. Pre-dispatch intent persistence before crossing the external execution boundary.
4. Ambiguous outcomes produce UNKNOWN_PENDING_RECONCILIATION; goal remains RECOVERY_REQUIRED.
5. Reconcile confirmed successful provider job (with output validation).
6. Reconcile output validation rejects empty or corrupt payloads.
7. Reconcile confirmed failed provider job (enabling safe retry).
8. Reconcile job still running on provider (keeps action blocked).
9. Reconcile provider without status lookup (remains ambiguous).
10. Eventually consistent provider 404 blocks automatic retry (AMBIGUOUS_RETRY_UNSAFE).
11. Strongly consistent provider 404 permits safe retry (CONFIRMED_NOT_STARTED -> READY).
12. Expired worker lease recovery.
13. Re-verification of approval validity and credential state during reconciliation.
14. Approval revocation blocks reconciliation or retry.
15. Audit trail recording and secret redaction during reconciliation.
16. DAG readiness propagation to downstream actions only after successful reconciliation.
17. Rejection of client attempts to force an ambiguous action to SUCCEEDED.
18. Fail-closed gate enforcement and network isolation (zero live calls).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    Mission,
)
from app.services.authorization_service import add_project_membership, create_api_key
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    BaseExecutionDispatcher,
    ExecutionResult,
    LiveExecutionGateError,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
    SIMULATION_WATERMARK,
    get_default_dispatcher,
    is_live_provider_execution_enabled,
    resolve_dispatcher,
    verify_live_execution_gate,
)
from app.services.dispatcher import OfflineMockDispatcher
from app.services.idempotency import (
    ActionReconciliationService,
    ProviderCapabilityProfile,
    ProviderConsistencyGuarantee,
    ReconciliationResult,
    ReconciliationVerdict,
    compute_action_fingerprint,
    generate_action_idempotency_key,
    record_pre_dispatch_intent,
    validate_action_outputs,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURE: STRICT OUTBOUND CALL PROHIBITION
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Fails tests immediately if any outbound network or subprocess call is attempted."""

    def _fail_on_network(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.3 test!"
        )

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.3 test!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


@pytest_asyncio.fixture(loop_scope="module")
async def phase3_2_3_auth_fixture(db_session: AsyncSession):
    """Provisions isolated projects and API keys for Phase 3.2.3 test verification."""
    settings = get_settings()
    settings.api_auth_enabled = True

    proj = Project(name=f"proj-phase-323-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    proj_unauth = Project(name=f"proj-unauth-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    db_session.add_all([proj, proj_unauth])
    await db_session.commit()
    await db_session.refresh(proj)
    await db_session.refresh(proj_unauth)

    human_key_model, human_key_raw = await create_api_key(
        db_session, name="Human Operator 3.2.3", is_admin=False, principal_type="human"
    )
    admin_key_model, admin_key_raw = await create_api_key(
        db_session, name="Admin Key 3.2.3", is_admin=True, principal_type="human"
    )

    await add_project_membership(db_session, proj.id, human_key_model.id, role="operator")
    await add_project_membership(db_session, proj.id, admin_key_model.id, role="admin")

    human_principal = AuthenticatedPrincipal(
        api_key_id=human_key_model.id,
        is_admin=False,
        principal_type="human",
        name="Human Operator 3.2.3",
    )
    admin_principal = AuthenticatedPrincipal(
        api_key_id=admin_key_model.id,
        is_admin=True,
        principal_type="human",
        name="Admin Key 3.2.3",
    )

    yield {
        "project": proj,
        "project_unauth": proj_unauth,
        "human_key_raw": human_key_raw,
        "human_key_model": human_key_model,
        "admin_key_raw": admin_key_raw,
        "admin_key_model": admin_key_model,
        "human_principal": human_principal,
        "admin_principal": admin_principal,
    }


def _create_client(raw_api_key: str | None = None) -> httpx.AsyncClient:
    headers = {}
    if raw_api_key:
        headers["Authorization"] = f"Bearer {raw_api_key}"
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers,
    )


# ===========================================================================
# 1. CANONICAL IDEMPOTENCY KEY & FINGERPRINTING
# ===========================================================================

async def test_01_canonical_idempotency_key_and_action_fingerprint(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 1: Generates stable, context-bound idempotency identity and fingerprint."""
    proj = phase3_2_3_auth_fixture["project"]
    goal_id = uuid.uuid4()
    act_id = uuid.uuid4()

    # 1. Canonical key format is arya:action:{project_id}:{goal_id}:{action_id}:{client_action_id}
    key1 = generate_action_idempotency_key(proj.id, goal_id, act_id, "act-step-1")
    key2 = generate_action_idempotency_key(proj.id, goal_id, act_id, "act-step-1")
    assert key1 == key2
    assert key1 == f"arya:action:{proj.id}:{goal_id}:{act_id}:act-step-1"

    # Context binding: different project or goal must yield distinct idempotency key
    key_other_proj = generate_action_idempotency_key(uuid.uuid4(), goal_id, act_id, "act-step-1")
    assert key1 != key_other_proj

    # 2. Action fingerprinting is deterministic and ignores ephemeral keys
    action = AutonomousActionNode(
        id=act_id,
        goal_id=goal_id,
        client_action_id="act-step-1",
        title="Generate Video",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "prompt": "sunset over mountains",
            "seed": 42,
            "lease": {"worker_id": "w1", "expires_at": "tomorrow"},
            "dispatch_intent": {"status": "DISPATCH_COMMITTED"},
            "dispatch_history": [{"attempt": 1}],
        },
    )
    fp1 = compute_action_fingerprint(action)
    assert isinstance(fp1, str) and len(fp1) == 64  # SHA-256 hex digest

    # Changing transient lease or dispatch intent does NOT alter the fingerprint
    action.inputs_json["lease"] = {"worker_id": "w2", "expires_at": "next_week"}
    action.inputs_json["dispatch_intent"] = {"status": "SUCCEEDED"}
    fp2 = compute_action_fingerprint(action)
    assert fp1 == fp2

    # Changing actual payload DOES alter the fingerprint
    action.inputs_json["prompt"] = "sunrise over ocean"
    fp3 = compute_action_fingerprint(action)
    assert fp1 != fp3


# ===========================================================================
# 2. PRE-DISPATCH INTENT PERSISTENCE
# ===========================================================================

async def test_02_pre_dispatch_intent_persisted_before_remote_boundary(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 2: Pre-dispatch intent is durably committed to inputs_json before execution boundary."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Pre-dispatch intent test",
        status="READY",
        plan_dag_json={"nodes": ["act-pre-intent"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-pre-intent",
        title="Pre-intent Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="READY",
        inputs_json={"test_param": "val"},
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    runner = AutonomousExecutionRunner(db=db_session, worker_id="worker-intent-01")
    dispatched_node = await runner.dispatch_action(action.id, principal)

    inputs = dispatched_node.inputs_json or {}
    assert "dispatch_intent" in inputs
    intent = inputs["dispatch_intent"]
    assert intent["worker_id"] == "worker-intent-01"
    assert intent["provider_id"] == "offline-mock"
    assert intent["idempotency_key"] == f"arya:action:{proj.id}:{goal.id}:{action.id}:act-pre-intent"
    assert intent["fingerprint"] is not None
    assert intent["lease_epoch"] >= 1
    assert "dispatched_at" in intent

    # Dispatch history appended
    assert "dispatch_history" in inputs
    assert len(inputs["dispatch_history"]) >= 1
    assert inputs["dispatch_history"][-1]["worker_id"] == "worker-intent-01"


# ===========================================================================
# 3. DISPATCHER EXCEPTION & UNKNOWN INVARIANT
# ===========================================================================

async def test_03_dispatcher_exception_produces_unknown_and_recovery_required(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 3: Dispatcher exception produces UNKNOWN_PENDING_RECONCILIATION and halts goal at RECOVERY_REQUIRED."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Exception isolation test",
        status="READY",
        plan_dag_json={
            "nodes": ["act-failing", "act-downstream"],
            "edges": [{"source": "act-failing", "target": "act-downstream"}],
        },
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    act_failing = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-failing",
        title="Failing Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="READY",
        inputs_json={},
    )
    act_downstream = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-downstream",
        title="Downstream Action",
        action_type="SYNTHESIS",
        required_capability="REASONING",
        status="PENDING",
        inputs_json={},
    )
    db_session.add_all([act_failing, act_downstream])
    await db_session.commit()

    # Create mock dispatcher that raises an unexpected connection error
    class BrokenDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            raise ConnectionResetError("Remote connection dropped abruptly during flight")

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=BrokenDispatcher(), worker_id="worker-crash-01")

    with pytest.raises(Exception) as exc_info:
        await runner.dispatch_action(act_failing.id, principal)
    assert exc_info.value.status_code == 500

    act_failing = await db_session.get(AutonomousActionNode, act_failing.id)
    act_downstream = await db_session.get(AutonomousActionNode, act_downstream.id)
    goal = await db_session.get(AutonomousGoal, goal.id)

    # Invariant: Must transition to UNKNOWN_PENDING_RECONCILIATION, never FAILED or SUCCEEDED
    assert act_failing.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "ConnectionResetError" in (act_failing.error or "")

    # Dispatch intent records ambiguous state
    intent = (act_failing.inputs_json or {}).get("dispatch_intent", {})
    assert intent.get("status") == "UNKNOWN_DISPATCH_ERROR"

    # Parent goal is halted at RECOVERY_REQUIRED
    assert goal.status == "RECOVERY_REQUIRED"

    # Downstream action must remain PENDING and NOT advance
    assert act_downstream.status == "PENDING"


# ===========================================================================
# 4. RECONCILIATION: CONFIRMED SUCCESS & OUTPUT VALIDATION
# ===========================================================================

async def test_04_reconciliation_confirmed_success_with_output_validation(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 4: Reconciles an ambiguous action to SUCCEEDED when provider confirms success and outputs pass validation."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Reconcile success test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-amb-succ"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-amb-succ",
        title="Ambiguous Success Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "worker_id": "worker-prev",
                "provider_id": "offline-mock",
                "provider_job_id": "job-offline-12345",
                "status": "UNKNOWN_PENDING_RECONCILIATION",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    # Dispatcher configured with successful status query
    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {
        "media_asset_id": "asset-valid-uuid-987",
        "duration_seconds": 5.0,
        "is_simulated": True,
    }

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.CONFIRMED_SUCCESS
    assert report.can_safely_retry is False
    assert node.status == "SUCCEEDED"
    assert node.outputs_json.get("media_asset_id") == "asset-valid-uuid-987"

    # Reconciliation audit recorded in dispatch_intent
    intent = (node.inputs_json or {}).get("dispatch_intent", {})
    audit = intent.get("reconciliation_audit", {})
    assert audit.get("verdict") == "CONFIRMED_SUCCESS"
    assert audit.get("reconciled_by_actor_type") == "human"

    # Goal is no longer RECOVERY_REQUIRED and completed
    goal = await db_session.get(AutonomousGoal, goal.id)
    assert goal.status == "COMPLETED"


# ===========================================================================
# 5. RECONCILIATION: OUTPUT VALIDATION REJECTS EMPTY/CORRUPT OUTPUT
# ===========================================================================

async def test_05_reconciliation_output_validation_rejects_empty_payload(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 5: Reconciliation fails closed to FAILED if provider claims success but outputs are empty or invalid."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Corrupt output test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-corrupt-out"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-corrupt-out",
        title="Synthesis Action with Empty Output",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-bad-out",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {}  # Empty outputs!

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    # Invariant: Empty output for SYNTHESIS must fail validation and transition to FAILED, not SUCCEEDED
    assert node.status == "FAILED"
    assert "Output validation failed" in (node.error or "")


# ===========================================================================
# 6. RECONCILIATION: CONFIRMED FAILURE & SAFE RETRY
# ===========================================================================

async def test_06_reconciliation_confirmed_failure_enables_safe_retry(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 6: Provider confirmed failure marks action FAILED and allows safe retry."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Failure reconciliation test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-prov-fail"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-prov-fail",
        title="Failed Remote Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-prov-failed",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "FAILED"
    dispatcher.mock_lookup_error = "Out of memory on provider worker"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.CONFIRMED_FAILURE
    assert report.can_safely_retry is True
    assert node.status == "FAILED"
    assert "Out of memory" in (node.error or "")


# ===========================================================================
# 7. RECONCILIATION: IN-PROGRESS KEEPS ACTION BLOCKED
# ===========================================================================

async def test_07_reconciliation_in_progress_keeps_action_blocked(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 7: Job still running on provider keeps node in UNKNOWN_PENDING_RECONCILIATION."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Running job reconciliation test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-running-job"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-running-job",
        title="Running Remote Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-still-running",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "RUNNING"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.CONFIRMED_IN_PROGRESS
    assert report.can_safely_retry is False
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 8. PROVIDER WITHOUT STATUS LOOKUP
# ===========================================================================

async def test_08_provider_without_status_lookup_remains_blocked(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 8: Reconciliation with a provider lacking status lookup capability remains ambiguous."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="No lookup test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-no-lookup"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-no-lookup",
        title="Action on No-Lookup Provider",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "unknown",  # "unknown" profile has supports_status_lookup=False
                "provider_job_id": "job-blind",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.LOOKUP_UNSUPPORTED
    assert report.can_safely_retry is False
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 9. EVENTUALLY CONSISTENT PROVIDER 404 BLOCKS RETRY
# ===========================================================================

async def test_09_eventually_consistent_provider_404_blocks_retry(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 9: 404 from eventually consistent provider is NOT proof of non-execution and blocks retry."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Eventual 404 test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-fal-404"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-fal-404",
        title="FAL Action 404",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "mock-eventual",  # mock-eventual has EVENTUALLY_CONSISTENT profile
                "provider_job_id": "fal-job-404",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "NOT_FOUND"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    # Invariant: Returning 404 on eventually consistent provider is ambiguous and unsafe to retry
    assert report.verdict == ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE
    assert report.can_safely_retry is False
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 10. STRONGLY CONSISTENT PROVIDER 404 ALLOWS SAFE RETRY
# ===========================================================================

async def test_10_strongly_consistent_provider_404_allows_safe_retry(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 10: 404 from strongly consistent provider proves job was not accepted and enables retry."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Strong 404 test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-strong-404"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-strong-404",
        title="Offline Mock 404",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",  # STRONGLY_CONSISTENT profile
                "provider_job_id": "mock-job-never-existed",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "NOT_FOUND"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.CONFIRMED_NOT_STARTED
    assert report.can_safely_retry is True
    assert node.status == "READY"


# ===========================================================================
# 11. EXPIRED WORKER LEASE RECOVERY
# ===========================================================================

async def test_11_expired_worker_lease_recovery(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 11: Action with an expired worker lease and no active remote job resets to READY."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Expired lease test",
        status="READY",
        plan_dag_json={"nodes": ["act-expired-lease"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-expired-lease",
        title="Expired Lease Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-crashed",
                "lease_token": "token-dead",
                "epoch": 1,
                "expires_at": expired_time,
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    node, report = await runner.reconcile_action(action.id, principal)

    assert report.verdict == ReconciliationVerdict.EXPIRED_LEASE_RESOLVED
    assert report.can_safely_retry is True
    assert node.status == "READY"


# ===========================================================================
# 12. APPROVAL RE-VERIFICATION & REVOCATION IN RECONCILIATION
# ===========================================================================

async def test_12_approval_revocation_blocks_reconciliation(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 12: Inactive or revoked approver credential blocks reconciliation of consequential actions."""
    proj = phase3_2_3_auth_fixture["project"]
    admin_principal = phase3_2_3_auth_fixture["admin_principal"]

    # Create temporary operator whose key will be deactivated
    temp_key_model, _ = await create_api_key(
        db_session, name="Temp Approver 3.2.3", is_admin=False, principal_type="human"
    )
    await add_project_membership(db_session, proj.id, temp_key_model.id, role="operator")

    run = WorkflowRun(
        project_id=proj.id,
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Approval Revocation Goal",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-consequential"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-consequential",
        title="High Risk Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="HIGH",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-revoked-key",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    checkpoint = ApprovalCheckpoint(
        workflow_run_id=run.id,
        reference_table="autonomous_action_nodes",
        reference_id=action.id,
        stage=ApprovalStage.VIDEO,
        action=ApprovalAction.APPROVE,
        decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        decided_by_principal_id=temp_key_model.id,
        decided_by_actor_type="human",
    )
    db_session.add(checkpoint)
    await db_session.commit()

    action.approval_checkpoint_id = checkpoint.id
    await db_session.commit()

    # Now revoke/deactivate the approving operator key!
    temp_key_model.is_active = False
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {"media_asset_id": "asset-should-fail", "duration_seconds": 1.0}

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, admin_principal)

    # Invariant: Inactive approver key invalidates reconciliation, forcing action to BLOCKED (not FAILED), preserving outputs
    assert node.status == "BLOCKED"
    assert report.verdict == ReconciliationVerdict.APPROVAL_REVOKED
    assert node.outputs_json is not None
    assert "revoked or deleted" in (node.error or "") or "invalidated" in (node.error or "")


# ===========================================================================
# 13. DAG PROPAGATION AFTER RECONCILIATION
# ===========================================================================

async def test_13_dag_cascade_downstream_unblocked_after_successful_reconciliation(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 13: Downstream action in DAG remains PENDING during unknown state and promotes to READY only after reconciliation succeeds."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="DAG Cascade Test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={
            "nodes": ["act-upstream", "act-downstream"],
            "edges": [{"source": "act-upstream", "target": "act-downstream"}],
        },
    )
    db_session.add(goal)
    await db_session.commit()

    upstream = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-upstream",
        title="Upstream Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-up-success",
            }
        },
    )
    downstream = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-downstream",
        title="Downstream Action",
        action_type="SYNTHESIS",
        required_capability="REASONING",
        status="PENDING",
        inputs_json={},
    )
    db_session.add_all([upstream, downstream])
    await db_session.commit()

    # Reconcile upstream to success
    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {"summary": "Research findings"}

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    await runner.reconcile_action(upstream.id, principal)

    upstream = await db_session.get(AutonomousActionNode, upstream.id)
    downstream = await db_session.get(AutonomousActionNode, downstream.id)

    assert upstream.status == "SUCCEEDED"
    # Invariant: Cascaded readiness update must promote downstream to READY!
    assert downstream.status == "READY"


# ===========================================================================
# 14. SECRET REDACTION IN RECONCILIATION AUDIT & OUTPUTS
# ===========================================================================

async def test_14_secret_redaction_in_reconciliation_audit_and_outputs(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 14: Sensitive credentials in provider status errors or outputs are redacted in audit records."""
    proj = phase3_2_3_auth_fixture["project"]
    principal = phase3_2_3_auth_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Secret Redaction Reconciliation",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-secret-leak"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-secret-leak",
        title="Action With Sensitive Provider Response",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-secret-leak",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    raw_secret = "sk-ant-api03-TOP_SECRET_RECONCILIATION_KEY_12345"
    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "FAILED"
    dispatcher.mock_lookup_error = f"Authentication failed with key: {raw_secret}"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, principal)

    assert raw_secret not in (node.error or "")
    assert ("***REDACTED***" in (node.error or "") or "[REDACTED]" in (node.error or ""))

    # Check persisted audit record in inputs_json
    intent = (node.inputs_json or {}).get("dispatch_intent", {})
    audit = intent.get("reconciliation_audit", {})
    audit_str = str(audit)
    assert raw_secret not in audit_str
    assert ("***REDACTED***" in audit_str or "[REDACTED]" in audit_str)


# ===========================================================================
# 15. CLIENT ATTEMPTS TO FORCE UNKNOWN STATE TO SUCCESS REJECTED
# ===========================================================================

async def test_15_client_cannot_force_unknown_state_to_success(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 15: Client PATCH mutation attempting to force UNKNOWN_PENDING_RECONCILIATION to SUCCEEDED is rejected."""
    proj = phase3_2_3_auth_fixture["project"]
    raw_key = phase3_2_3_auth_fixture["human_key_raw"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Client mutation boundary test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-tamper"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-tamper",
        title="Tamper Target Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={},
    )
    db_session.add(action)
    await db_session.commit()

    async with _create_client(raw_key) as client:
        # Attempt to patch status directly to SUCCEEDED
        patch_res = await client.patch(
            f"/api/v1/actions/{action.id}",
            json={"status": "SUCCEEDED"},
        )
        # Invariant: Client cannot force SUCCEEDED or mutate from UNKNOWN_PENDING_RECONCILIATION
        assert patch_res.status_code in (409, 422)

    action = await db_session.get(AutonomousActionNode, action.id)
    assert action.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 16. REST API: RECONCILE ENDPOINT ENFORCEMENT & IDOR MASKING
# ===========================================================================

async def test_16_reconcile_api_endpoint_authorization_and_idor(phase3_2_3_auth_fixture, db_session: AsyncSession):
    """Test 16: POST /api/v1/actions/{action_id}/reconcile masks unauthorized project actions as 404."""
    proj_unauth = phase3_2_3_auth_fixture["project_unauth"]
    raw_key = phase3_2_3_auth_fixture["human_key_raw"]

    goal = AutonomousGoal(
        project_id=proj_unauth.id,  # Other project!
        objective="IDOR Reconcile Test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-unauth"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-unauth",
        title="Unauthorized Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={},
    )
    db_session.add(action)
    await db_session.commit()

    async with _create_client(raw_key) as client:
        res = await client.post(f"/api/v1/actions/{action.id}/reconcile")
        assert res.status_code == 404
