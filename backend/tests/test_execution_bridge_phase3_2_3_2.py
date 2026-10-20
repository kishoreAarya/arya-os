"""
AryaOS V1 Stage 25 Phase 3.2.3.2 — Execution Truth, Lease Safety & Provider Capability Remediation Suite.

Verifies the 4 mandatory security remediations:
1. Execution Truth & Governance Invalidation: Confirmed remote success is never falsified into FAILED;
   outputs, job ID, and costs are preserved while action transitions to BLOCKED; goal remains in RECOVERY_REQUIRED.
2. Lease Safety & Duplicate Dispatch Prevention: Expired EXECUTING actions cannot be re-dispatched directly;
   require authoritative reconciliation first. Safe reset to READY permitted only when no dispatch occurred.
3. Client State Machine Lockdown: Non-authoritative client requests cannot transition EXECUTING to READY
   for any risk level (LOW, MEDIUM, HIGH, CRITICAL), nor bypass UNKNOWN_PENDING_RECONCILIATION / RECOVERY_REQUIRED.
4. Truthful Provider Capability Declarations: Fal and Kling profiles declare supports_status_lookup=False
   and NO_LOOKUP; status queries fail closed to LOOKUP_UNSUPPORTED without blind retries.
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
from fastapi import HTTPException
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio(loop_scope="module")

from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.schemas.execution_bridge import AutonomousActionNodeUpdate
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import ExecutionResult, OfflineMockDispatcher
from app.services.execution_bridge_service import update_action_node
from app.services.idempotency import (
    ActionReconciliationService,
    ProviderConsistencyGuarantee,
    ReconciliationVerdict,
    get_provider_capability_profile,
    record_pre_dispatch_intent,
)


# -----------------------------------------------------------------------------
# Strict Network & Subprocess Isolation Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Fails tests immediately if any outbound network or subprocess call is attempted."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.3.2 test!"
        )

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.3.2 test!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


@pytest_asyncio.fixture(loop_scope="module")
async def phase3_2_3_2_fixture(db_session: AsyncSession):
    """Authentication and tenant fixtures for Phase 3.2.3.2 testing."""
    from app.services.authorization_service import add_project_membership, create_api_key

    settings = get_settings()
    settings.enable_live_provider_execution = False
    settings.api_auth_enabled = True

    proj = Project(name=f"proj-phase-3232-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)

    human_key_model, human_key_raw = await create_api_key(
        db_session, name="Human Operator 3.2.3.2", is_admin=False, principal_type="human"
    )
    admin_key_model, admin_key_raw = await create_api_key(
        db_session, name="Admin Key 3.2.3.2", is_admin=True, principal_type="human"
    )

    await add_project_membership(db_session, proj.id, human_key_model.id, role="operator")
    await add_project_membership(db_session, proj.id, admin_key_model.id, role="admin")

    human_principal = AuthenticatedPrincipal(
        api_key_id=human_key_model.id,
        is_admin=False,
        principal_type="human",
        name="Human Operator 3.2.3.2",
    )
    admin_principal = AuthenticatedPrincipal(
        api_key_id=admin_key_model.id,
        is_admin=True,
        principal_type="human",
        name="Admin Key 3.2.3.2",
    )

    yield {
        "project": proj,
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
# 1. REMEDIATION 1: EXECUTION TRUTH & APPROVAL REVOCATION
# ===========================================================================

async def test_01_confirmed_remote_success_plus_revoked_approver(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 1: Confirmed remote success is NEVER marked FAILED when approver key is revoked.
    Outputs, job ID, and costs are preserved; status becomes BLOCKED; goal stays in RECOVERY_REQUIRED.
    """
    proj = phase3_2_3_2_fixture["project"]
    admin_principal = phase3_2_3_2_fixture["admin_principal"]

    from app.services.authorization_service import add_project_membership, create_api_key
    temp_key_model, _ = await create_api_key(
        db_session, name="Temp Operator 3.2.3.2", is_admin=False, principal_type="human"
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
        objective="Execution Truth Test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-truth"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-truth",
        title="High Value Video Generation",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="HIGH",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-kling-expensive-999",
                "dispatch_state": "DISPATCH_COMMITTED",
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

    # Operator key is revoked after remote provider executed
    temp_key_model.is_active = False
    await db_session.commit()

    # Remote provider confirmed execution success with generated video
    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {
        "media_asset_id": "asset-video-4k-rendered",
        "video_url": "https://cdn.arya.internal/renders/asset-4k.mp4",
        "duration_seconds": 5.0,
        "cost_usd": 0.50,
    }

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, admin_principal)

    # Core Safety Invariant: NEVER falsify remote success into execution FAILED!
    assert node.status == "BLOCKED"
    assert node.status != "FAILED"
    assert report.verdict == ReconciliationVerdict.APPROVAL_REVOKED
    assert report.can_safely_retry is False

    # External execution truth is preserved!
    assert node.outputs_json is not None
    assert node.outputs_json["media_asset_id"] == "asset-video-4k-rendered"
    assert "Remote execution confirmed SUCCEEDED" in (node.error or "")
    assert "invalidated" in (node.error or "") or "revoked" in (node.error or "")

    # Goal remains safely in RECOVERY_REQUIRED
    updated_goal = await db_session.get(AutonomousGoal, goal.id)
    assert updated_goal.status == "RECOVERY_REQUIRED"


async def test_02_unknown_remote_outcome_plus_revoked_approver(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 2: When remote outcome is unknown and approver is revoked, outcome remains UNKNOWN_PENDING_RECONCILIATION."""
    proj = phase3_2_3_2_fixture["project"]
    admin_principal = phase3_2_3_2_fixture["admin_principal"]

    from app.services.authorization_service import add_project_membership, create_api_key
    temp_key_model, _ = await create_api_key(
        db_session, name="Temp Operator Revoked", is_admin=False, principal_type="human"
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
        objective="Unknown Outcome Test",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-unknown"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-unknown",
        title="Unknown Outcome Action",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="HIGH",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "provider_job_id": "job-unknown",
                "dispatch_state": "DISPATCH_COMMITTED",
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
    temp_key_model.is_active = False
    await db_session.commit()

    # Provider status lookup service unavailable / error
    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "ERROR"

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(action.id, admin_principal)

    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert report.verdict == ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE
    assert report.can_safely_retry is False


# ===========================================================================
# 2. REMEDIATION 2: PREVENT DUPLICATE DISPATCH AFTER LEASE EXPIRY
# ===========================================================================

async def test_03_expired_lease_with_dispatch_intent_blocks_direct_redispatch(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 3: An EXECUTING action whose lease expired CANNOT be directly re-dispatched via dispatch_action."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Expired Lease Dispatch Guard",
        status="EXECUTING",
        plan_dag_json={"nodes": ["act-expired-exec"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    # Expired 10 minutes ago
    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-expired-exec",
        title="Expired Executing Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="LOW",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-crashed",
                "expires_at": expired_time,
            },
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "dispatch_state": "DISPATCH_COMMITTED",
            },
        },
    )
    db_session.add(action)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session, worker_id="worker-new")

    # Invariant: Must raise 409 Conflict prohibiting direct redispatch without reconciliation
    with pytest.raises(Exception) as exc_info:
        await runner.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409
    assert "Direct redispatch is prohibited" in str(exc_info.value.detail) or "reconciled" in str(exc_info.value.detail)


async def test_04_expired_lease_without_dispatch_intent_safely_resets_to_ready(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 4: Action with expired lease where no dispatch occurred safely resets to READY upon reconciliation."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Safe Reset Test",
        status="READY",
        plan_dag_json={"nodes": ["act-no-dispatch"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-no-dispatch",
        title="No Dispatch Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="LOW",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-died-early",
                "expires_at": expired_time,
            }
            # No dispatch_intent! Proves external boundary was never crossed.
        },
    )
    db_session.add(action)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    node, report = await runner.reconcile_action(action.id, principal)

    assert node.status == "READY"
    assert report.verdict == ReconciliationVerdict.EXPIRED_LEASE_RESOLVED
    assert report.can_safely_retry is True


async def test_05_second_worker_cannot_claim_ambiguous_action(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 5: A second worker cannot claim an action in EXECUTING with an active lease."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Concurrent Worker Lease Guard",
        status="EXECUTING",
        plan_dag_json={"nodes": ["act-leased"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    active_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-leased",
        title="Active Leased Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="LOW",
        status="EXECUTING",
        inputs_json={
            "lease": {
                "worker_id": "worker-primary",
                "expires_at": active_time,
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    runner_secondary = AutonomousExecutionRunner(db=db_session, worker_id="worker-secondary")

    with pytest.raises(Exception) as exc_info:
        await runner_secondary.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409
    assert "claimed by worker 'worker-primary'" in str(exc_info.value.detail)


# ===========================================================================
# 3. REMEDIATION 3: BLOCK CLIENT OVERRIDES OF EXECUTING ACTIONS
# ===========================================================================

@pytest.mark.parametrize("risk_level", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
async def test_06_client_cannot_reset_executing_to_ready_across_all_risk_levels(
    phase3_2_3_2_fixture, db_session: AsyncSession, risk_level: str
):
    """Test 6: Client update_action_node rejects EXECUTING -> READY across all risk levels."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective=f"Risk Test {risk_level}",
        status="EXECUTING",
        plan_dag_json={"nodes": [f"act-{risk_level.lower()}"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id=f"act-{risk_level.lower()}",
        title=f"Action {risk_level}",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level=risk_level,
        status="EXECUTING",
    )
    db_session.add(action)
    await db_session.commit()

    # Attempt client transition via update_action_node (is_authoritative_engine=False)
    with pytest.raises(Exception) as exc_info:
        await update_action_node(
            db=db_session,
            action_id=action.id,
            data=AutonomousActionNodeUpdate(status="READY"),
            principal=principal,
            is_authoritative_engine=False,
        )

    assert exc_info.value.status_code == 409
    assert "Client cannot directly transition" in str(exc_info.value.detail) or "cannot be transitioned" in str(exc_info.value.detail)


async def test_07_client_cannot_reset_unknown_pending_reconciliation_or_recovery_required(
    phase3_2_3_2_fixture, db_session: AsyncSession
):
    """Test 7: Client cannot bypass UNKNOWN_PENDING_RECONCILIATION or RECOVERY_REQUIRED."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Client Bypass Guard",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-ambiguous"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-ambiguous",
        title="Ambiguous Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        status="UNKNOWN_PENDING_RECONCILIATION",
    )
    db_session.add(action)
    await db_session.commit()

    # Client attempts to reset to READY
    with pytest.raises(Exception) as exc1:
        await update_action_node(
            db=db_session,
            action_id=action.id,
            data=AutonomousActionNodeUpdate(status="READY"),
            principal=principal,
            is_authoritative_engine=False,
        )
    assert exc1.value.status_code == 409
    assert "UNKNOWN_PENDING_RECONCILIATION" in str(exc1.value.detail)

    # Client attempts to force to SUCCEEDED
    with pytest.raises(Exception) as exc2:
        await update_action_node(
            db=db_session,
            action_id=action.id,
            data=AutonomousActionNodeUpdate(status="SUCCEEDED"),
            principal=principal,
            is_authoritative_engine=False,
        )
    assert exc2.value.status_code == 409


# ===========================================================================
# 4. REMEDIATION 4: TRUTHFUL PROVIDER CAPABILITIES (FAL & KLING)
# ===========================================================================

async def test_08_fal_and_kling_profiles_fail_closed_without_status_lookup(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 8: Fal and Kling profiles declare NO_LOOKUP; reconciliation fails closed to LOOKUP_UNSUPPORTED."""
    # 1. Profile check
    fal_prof = get_provider_capability_profile("fal")
    assert fal_prof.supports_status_lookup is False
    assert fal_prof.consistency_guarantee == ProviderConsistencyGuarantee.NO_LOOKUP

    kling_prof = get_provider_capability_profile("kling")
    assert kling_prof.supports_status_lookup is False
    assert kling_prof.consistency_guarantee == ProviderConsistencyGuarantee.NO_LOOKUP

    # 2. Reconciliation check
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Fal Status Guard",
        status="RECOVERY_REQUIRED",
        plan_dag_json={"nodes": ["act-fal"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-fal",
        title="Fal Generation",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={
            "dispatch_intent": {
                "provider_id": "fal",
                "dispatch_state": "DISPATCH_COMMITTED",
            }
        },
    )
    db_session.add(action)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session)
    node, report = await runner.reconcile_action(action.id, principal)

    # Invariant: Must fail closed to LOOKUP_UNSUPPORTED without retrying or guessing
    assert report.verdict == ReconciliationVerdict.LOOKUP_UNSUPPORTED
    assert report.can_safely_retry is False
    assert node.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 5. FENCING AND DAG PROGRESSION REGRESSIONS
# ===========================================================================

async def test_09_stale_worker_cannot_overwrite_reconciled_state(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 9: Stale worker fencing prevents a slow/crashed worker from writing results after reconciliation."""
    proj = phase3_2_3_2_fixture["project"]
    principal = phase3_2_3_2_fixture["human_principal"]

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Fencing Guard",
        status="EXECUTING",
        plan_dag_json={"nodes": ["act-fenced"], "edges": []},
    )
    db_session.add(goal)
    await db_session.commit()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-fenced",
        title="Fenced Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="LOW",
        status="READY",
    )
    db_session.add(action)
    await db_session.commit()

    # Create a custom dispatcher that simulates a concurrent worker stealing the lease mid-execution
    class ConcurrentlyPreemptedDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            # Modify lease token in DB to simulate another worker claiming it
            from sqlalchemy.orm.attributes import flag_modified
            inputs = dict(action.inputs_json or {})
            lease = dict(inputs.get("lease", {}))
            lease["lease_token"] = "preempted-by-worker-B"
            lease["epoch"] = lease.get("epoch", 1) + 1
            inputs["lease"] = lease
            action.inputs_json = inputs
            flag_modified(action, "inputs_json")
            await db_session.commit()
            return await super().dispatch(action)

    runner_a = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=ConcurrentlyPreemptedDispatcher(allow_network=False),
        worker_id="worker-stale",
    )

    with pytest.raises(HTTPException) as exc_info:
        await runner_a.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409
    assert "fencing token mismatch" in exc_info.value.detail.lower()


async def test_10_downstream_dag_remains_blocked_after_governance_invalidation(phase3_2_3_2_fixture, db_session: AsyncSession):
    """Test 10: Dependent DAG node remains BLOCKED when upstream node is BLOCKED due to approval revocation."""
    proj = phase3_2_3_2_fixture["project"]
    admin_principal = phase3_2_3_2_fixture["admin_principal"]

    from app.services.authorization_service import add_project_membership, create_api_key
    temp_key_model, _ = await create_api_key(
        db_session, name="Temp Approver Revoked 2", is_admin=False, principal_type="human"
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
        objective="DAG Governance Cascade",
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
        title="Consequential Upstream",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="HIGH",
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
        title="Dependent Downstream",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="LOW",
        status="PENDING",
    )
    db_session.add_all([upstream, downstream])
    await db_session.commit()

    checkpoint = ApprovalCheckpoint(
        workflow_run_id=run.id,
        reference_table="autonomous_action_nodes",
        reference_id=upstream.id,
        stage=ApprovalStage.IMAGE,
        action=ApprovalAction.APPROVE,
        decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        decided_by_principal_id=temp_key_model.id,
        decided_by_actor_type="human",
    )
    db_session.add(checkpoint)
    await db_session.commit()
    upstream.approval_checkpoint_id = checkpoint.id
    temp_key_model.is_active = False
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    dispatcher.mock_lookup_status = "SUCCEEDED"
    dispatcher.mock_lookup_output = {"media_asset_id": "asset-up", "image_url": "https://cdn.arya.internal/img.png"}

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)
    node, report = await runner.reconcile_action(upstream.id, admin_principal)

    assert node.status == "BLOCKED"
    assert report.verdict == ReconciliationVerdict.APPROVAL_REVOKED

    # Downstream action must NOT be promoted to READY!
    await db_session.refresh(downstream)
    assert downstream.status in ("PENDING", "BLOCKED")
    assert downstream.status != "READY"
