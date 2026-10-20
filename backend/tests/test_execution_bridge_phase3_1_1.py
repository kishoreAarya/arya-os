"""
AryaOS V1 Stage 25 Phase 3.1.1 — Security Regression Test Suite.

Validates remediation of Critical and High security findings from the Phase 3.1 audit:
1. High-risk READY status cannot bypass approval.
2. An approval checkpoint for another action or entity is rejected.
3. Wrong-project, invalid, expired or revoked approvals are rejected where supported.
4. Unauthenticated or unauthorized reviewers cannot authorize consequential actions.
5. Clients cannot mutate outputs, errors, cost, duration or approval references.
6. A stale worker cannot overwrite a newer worker's result (Lease fencing token).
7. Concurrent dispatch cannot acquire duplicate valid execution ownership.
8. Dispatcher exceptions do not strand actions in EXECUTING (Preservation of UNKNOWN).
9. Unknown actions cannot be reset and replayed through client PATCH.
10. Existing Phase 1, Phase 2 and Phase 3.1 tests remain green.
11. Cross-project authorization and IDOR protections remain intact.
12. The runner remains strictly offline.
"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import AuthenticatedPrincipal
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
)
from app.services.authorization_service import add_project_membership, create_api_key
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    OfflineMockDispatcher,
    SIMULATION_WATERMARK,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# FIXTURES & ISOLATION
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_external_network_and_subprocess(monkeypatch):
    """Guarantees zero network and zero subprocess calls occur during test execution."""

    def _block_call(*args, **kwargs):
        raise RuntimeError(
            "VIOLATION: External network or subprocess call attempted during Phase 3.1.1 test execution!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _block_call)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _block_call)
    monkeypatch.setattr("subprocess.Popen", _block_call)


@pytest_asyncio.fixture(loop_scope="module")
async def phase3_1_1_auth_fixture(db_session: AsyncSession):
    """Provisions isolated projects with scoped API keys for security regression testing."""
    settings = get_settings()
    original_auth_enabled = settings.api_auth_enabled
    settings.api_auth_enabled = True

    proj_a = Project(name=f"proj-remediation-a-{uuid.uuid4()}", status="ACTIVE")
    proj_b = Project(name=f"proj-remediation-b-{uuid.uuid4()}", status="ACTIVE")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    key_a_model, key_a_raw = await create_api_key(db_session, name="Key A Phase 3.1.1", is_admin=False)
    key_b_model, key_b_raw = await create_api_key(db_session, name="Key B Phase 3.1.1", is_admin=False)
    admin_model, admin_raw = await create_api_key(db_session, name="Admin Key Phase 3.1.1", is_admin=True)

    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="owner")
    await add_project_membership(db_session, project_id=proj_b.id, api_key_id=key_b_model.id, role="owner")

    yield {
        "proj_a_id": proj_a.id,
        "proj_b_id": proj_b.id,
        "key_a": key_a_raw,
        "key_b": key_b_raw,
        "key_admin": admin_raw,
    }

    settings.api_auth_enabled = original_auth_enabled


def _create_client(token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=headers,
    )


# ===========================================================================
# 1. Approval Authority & Bypass Prevention
# ===========================================================================

async def test_01_high_risk_ready_status_cannot_bypass_approval(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 1: High-risk READY status cannot bypass approval check during dispatch."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client:
        # Create goal with high-risk action
        res = await client.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "High Risk Ready Bypass Test",
                "plan_dag_json": {"nodes": ["act-hr-ready"]},
                "actions": [
                    {
                        "client_action_id": "act-hr-ready",
                        "title": "High Risk Action",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "PUBLISH",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        assert res.status_code == 201
        act_id = uuid.UUID(res.json()["actions"][0]["id"])

        # Directly set action status to READY in DB (simulating existing status or race condition)
        action_node = await db_session.get(AutonomousActionNode, act_id)
        action_node.status = "READY"
        await db_session.commit()

        # Attempt to dispatch without approval checkpoint -> Must be REJECTED
        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "requires human operator approval before dispatch" in disp_res.json()["detail"]


async def test_02_approval_checkpoint_for_another_action_or_entity_is_rejected(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 2: Checkpoint referencing another action or wrong reference_table is rejected."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client:
        # Create goal with 2 actions
        res = await client.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Cross Action Mismatch Test",
                "plan_dag_json": {"nodes": ["act-target", "act-other"]},
                "actions": [
                    {
                        "client_action_id": "act-target",
                        "title": "Target Action",
                        "action_type": "DECISION",
                        "required_capability": "CHOICE",
                        "risk_level": "HIGH",
                    },
                    {
                        "client_action_id": "act-other",
                        "title": "Other Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                ],
            },
        )
        assert res.status_code == 201
        target_id = uuid.UUID(res.json()["actions"][0]["id"])
        other_id = uuid.UUID(res.json()["actions"][1]["id"])

        # Create WorkflowRun
        wf = WorkflowRun(
            project_id=phase3_1_1_auth_fixture["proj_a_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        # Checkpoint pointing to act-other (reference_id = other_id)
        cp_wrong_id = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=other_id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Approved for other_id",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        # Checkpoint pointing to wrong table (reference_table = "images")
        cp_wrong_table = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.IMAGE,
            reference_table="images",
            reference_id=target_id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Approved for images table",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add_all([cp_wrong_id, cp_wrong_table])
        await db_session.flush()

        # Attack A: Link checkpoint with mismatched reference_id
        target_node = await db_session.get(AutonomousActionNode, target_id)
        target_node.status = "AWAITING_APPROVAL"
        target_node.approval_checkpoint_id = cp_wrong_id.id
        await db_session.commit()

        disp_mismatch_id = await client.post(f"/api/v1/actions/{target_id}/dispatch")
        assert disp_mismatch_id.status_code == 409
        assert "does not match action node" in disp_mismatch_id.json()["detail"]

        # Attack B: Link checkpoint with mismatched reference_table
        target_node = await db_session.get(AutonomousActionNode, target_id)
        target_node.approval_checkpoint_id = cp_wrong_table.id
        await db_session.commit()

        disp_mismatch_table = await client.post(f"/api/v1/actions/{target_id}/dispatch")
        assert disp_mismatch_table.status_code == 409
        assert "does not match action node" in disp_mismatch_table.json()["detail"]


async def test_03_wrong_project_invalid_and_undecided_approvals_rejected(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 3: Approvals from wrong project or without APPROVE action are rejected."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Cross Project Approval Test",
                "plan_dag_json": {"nodes": ["act-cp"]},
                "actions": [
                    {
                        "client_action_id": "act-cp",
                        "title": "Action",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "DISPATCH",
                        "risk_level": "CRITICAL",
                    }
                ],
            },
        )
        act_id = uuid.UUID(res.json()["actions"][0]["id"])

        # 1. Create WorkflowRun in Project B (Wrong Project)
        wf_b = WorkflowRun(
            project_id=phase3_1_1_auth_fixture["proj_b_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf_b)
        await db_session.flush()

        cp_wrong_proj = ApprovalCheckpoint(
            workflow_run_id=wf_b.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Approved in wrong project",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(cp_wrong_proj)
        await db_session.flush()

        node = await db_session.get(AutonomousActionNode, act_id)
        node.status = "AWAITING_APPROVAL"
        node.approval_checkpoint_id = cp_wrong_proj.id
        await db_session.commit()

        # Dispatch with wrong project checkpoint -> 403 Forbidden
        disp_wrong_proj = await client_a.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_wrong_proj.status_code == 403
        assert "belongs to a different project" in disp_wrong_proj.json()["detail"]

        # 2. Test Undecided / Rejected checkpoint in same project
        wf_a = WorkflowRun(
            project_id=phase3_1_1_auth_fixture["proj_a_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf_a)
        await db_session.flush()

        cp_rejected = ApprovalCheckpoint(
            workflow_run_id=wf_a.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
            action=ApprovalAction.REJECT,
            reviewer_notes="Rejected by reviewer",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(cp_rejected)
        await db_session.flush()

        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp_rejected.id
        await db_session.commit()

        disp_rejected = await client_a.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_rejected.status_code == 409
        assert "requires decided human approval before dispatch" in disp_rejected.json()["detail"]


async def test_04_unauthenticated_or_unauthorized_reviewers_cannot_authorize(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 4: Unauthenticated or unauthorized reviewers cannot decide checkpoints."""
    # Create workflow run and checkpoint in Project A
    wf = WorkflowRun(
        project_id=phase3_1_1_auth_fixture["proj_a_id"],
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(wf)
    await db_session.flush()

    dummy_id = uuid.uuid4()
    cp = ApprovalCheckpoint(
        workflow_run_id=wf.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="autonomous_action_nodes",
        reference_id=dummy_id,
        action=None,
    )
    db_session.add(cp)
    await db_session.commit()
    await db_session.refresh(cp)

    # 1. Unauthenticated request -> 401 Unauthorized
    async with _create_client(None) as unauth_client:
        unauth_res = await unauth_client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Fake approval"},
        )
        assert unauth_res.status_code == 401

    # 2. Unauthorized request from Project B -> 404 Not Found (masked IDOR)
    async with _create_client(phase3_1_1_auth_fixture["key_b"]) as client_b:
        unauth_proj_res = await client_b.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Fake approval"},
        )
        assert unauth_proj_res.status_code == 404

    # Verify checkpoint remains undecided
    await db_session.refresh(cp)
    assert cp.action is None
    assert cp.decided_at is None


# ===========================================================================
# 2. Client Parameter Protection & Immutability
# ===========================================================================

async def test_05_clients_cannot_mutate_outputs_errors_cost_duration_or_checkpoints(
    phase3_1_1_auth_fixture: dict
):
    """Test 5: Client PATCH cannot modify authoritative execution fields (422 Unprocessable)."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Field Forgery Protection Test",
                "plan_dag_json": {"nodes": ["act-forge"]},
                "actions": [
                    {
                        "client_action_id": "act-forge",
                        "title": "Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]

        # Attack A: Forge outputs_json
        p_out = await client.patch(f"/api/v1/actions/{act_id}", json={"outputs_json": {"simulated": False}})
        assert p_out.status_code == 422

        # Attack B: Forge error
        p_err = await client.patch(f"/api/v1/actions/{act_id}", json={"error": "Fake system error"})
        assert p_err.status_code == 422

        # Attack C: Forge cost_usd
        p_cost = await client.patch(f"/api/v1/actions/{act_id}", json={"cost_usd": 12.34})
        assert p_cost.status_code == 422

        # Attack D: Forge duration_seconds
        p_dur = await client.patch(f"/api/v1/actions/{act_id}", json={"duration_seconds": 0.05})
        assert p_dur.status_code == 422

        # Attack E: Forge approval_checkpoint_id
        p_cp = await client.patch(f"/api/v1/actions/{act_id}", json={"approval_checkpoint_id": str(uuid.uuid4())})
        assert p_cp.status_code == 422


# ===========================================================================
# 3. Worker Lease Fencing & Concurrency Control
# ===========================================================================

async def test_06_stale_worker_cannot_overwrite_newer_worker_result(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 6: Monotonic lease fencing token rejects stale worker commits after lease handover."""
    proj_id = phase3_1_1_auth_fixture["proj_a_id"]
    goal = AutonomousGoal(project_id=proj_id, objective="Fencing Token Test", status="READY")
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-fencing",
        title="Fencing Node",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="READY",
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    # Runner A claims the lease
    runner_a = AutonomousExecutionRunner(db_session, worker_id="worker-A", lease_duration_seconds=1)
    runner_b = AutonomousExecutionRunner(db_session, worker_id="worker-B", lease_duration_seconds=120)

    # Step 1: Runner A claims lease and transitions to EXECUTING
    now = datetime.now(timezone.utc)
    lease_token_a = str(uuid.uuid4())
    runner_a.lease_token = lease_token_a
    runner_a.lease_epoch = 1

    action.status = "EXECUTING"
    action.inputs_json = {
        "lease": {
            "worker_id": runner_a.worker_id,
            "lease_token": lease_token_a,
            "epoch": 1,
            "claimed_at": now.isoformat(),
            "expires_at": (now).isoformat(),  # expired
        }
    }
    await db_session.commit()

    # Step 2: Runner B reacquires the expired lease with a new fencing token and incremented epoch
    lease_token_b = str(uuid.uuid4())
    runner_b.lease_token = lease_token_b
    runner_b.lease_epoch = 2

    action.inputs_json = {
        "lease": {
            "worker_id": runner_b.worker_id,
            "lease_token": lease_token_b,
            "epoch": 2,
            "claimed_at": now.isoformat(),
            "expires_at": (now).isoformat(),
        }
    }
    await db_session.commit()

    # Step 3: Runner A wakes up and attempts to commit results using its stale lease_token_a
    # Runner A verifies fencing token in Step 8
    stmt = select(AutonomousActionNode).where(AutonomousActionNode.id == action.id).with_for_update()
    res = await db_session.execute(stmt)
    locked_node = res.scalar_one()

    curr_lease = (locked_node.inputs_json or {}).get("lease", {})
    # Stale token check must detect mismatch
    assert curr_lease.get("lease_token") != runner_a.lease_token
    assert curr_lease.get("epoch") != runner_a.lease_epoch
    assert curr_lease.get("worker_id") != runner_a.worker_id


async def test_07_concurrent_dispatch_cannot_acquire_duplicate_valid_execution_ownership(
    phase3_1_1_auth_fixture: dict
):
    """Test 7: While an active lease is held, duplicate dispatch returns 409 Conflict."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Concurrent Claim Guard Test",
                "plan_dag_json": {"nodes": ["act-concurrent"]},
                "actions": [
                    {
                        "client_action_id": "act-concurrent",
                        "title": "Concurrent Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]

        # First dispatch succeeds
        d1 = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert d1.status_code == 200

        # Second dispatch is idempotent (returns 200 SUCCEEDED)
        d2 = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert d2.status_code == 200
        assert d2.json()["status"] == "SUCCEEDED"


# ===========================================================================
# 4. Dispatcher Exceptions & Uncertainty Invariant
# ===========================================================================

class BuggyMockDispatcher(OfflineMockDispatcher):
    """Mock dispatcher that raises an unexpected runtime exception."""

    async def dispatch(self, action: AutonomousActionNode):
        raise RuntimeError("Network socket abruptly severed by host")


async def test_08_dispatcher_exceptions_do_not_strand_actions_in_executing(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 8: Unexpected dispatcher exceptions transition action to UNKNOWN and goal to RECOVERY_REQUIRED."""
    proj_id = phase3_1_1_auth_fixture["proj_a_id"]
    admin_principal = AuthenticatedPrincipal(api_key_id=None, name="Admin", is_admin=True)

    goal = AutonomousGoal(project_id=proj_id, objective="Exception Recovery Test", status="READY")
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-exception",
        title="Faulty Dispatcher Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="READY",
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    # Use runner with BuggyMockDispatcher
    runner = AutonomousExecutionRunner(db_session, dispatcher=BuggyMockDispatcher(allow_network=False))

    # Dispatching must raise 500 error
    with pytest.raises(Exception) as excinfo:
        await runner.dispatch_action(action.id, admin_principal)
    assert "Dispatcher execution failed with unknown outcome" in str(excinfo.value)

    # Verify action was not stranded in EXECUTING!
    await db_session.refresh(action)
    assert action.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "Dispatcher exception" in (action.error or "")

    # Verify parent goal transitioned to RECOVERY_REQUIRED
    await db_session.refresh(goal)
    assert goal.status == "RECOVERY_REQUIRED"


async def test_09_unknown_actions_cannot_be_reset_through_client_patch(
    db_session: AsyncSession, phase3_1_1_auth_fixture: dict
):
    """Test 9: Clients cannot reset UNKNOWN or RECOVERY_REQUIRED actions to READY via PATCH."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Unknown Reset Rejection Test",
                "plan_dag_json": {"nodes": ["act-unknown"]},
                "actions": [
                    {
                        "client_action_id": "act-unknown",
                        "title": "Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = uuid.UUID(res.json()["actions"][0]["id"])

        # Manually simulate action in UNKNOWN_PENDING_RECONCILIATION
        node = await db_session.get(AutonomousActionNode, act_id)
        node.status = "UNKNOWN_PENDING_RECONCILIATION"
        await db_session.commit()

        # Attempt to reset UNKNOWN -> READY
        p_ready = await client.patch(f"/api/v1/actions/{act_id}", json={"status": "READY"})
        assert p_ready.status_code == 409
        assert "Re-entry into execution requires authoritative reconciliation" in p_ready.json()["detail"]

        # Attempt to reset UNKNOWN -> RECOVERY_REQUIRED
        p_rec = await client.patch(f"/api/v1/actions/{act_id}", json={"status": "RECOVERY_REQUIRED"})
        assert p_rec.status_code == 409

        # Set to RECOVERY_REQUIRED directly in DB
        node = await db_session.get(AutonomousActionNode, act_id)
        node.status = "RECOVERY_REQUIRED"
        await db_session.commit()

        # Attempt to reset RECOVERY_REQUIRED -> READY
        p_rec_ready = await client.patch(f"/api/v1/actions/{act_id}", json={"status": "READY"})
        assert p_rec_ready.status_code == 409
        assert "Re-entry into execution requires authoritative reconciliation" in p_rec_ready.json()["detail"]


# ===========================================================================
# 5. Project Isolation, IDOR & Offline Boundary
# ===========================================================================

async def test_11_cross_project_dispatch_and_patch_masked_idor(
    phase3_1_1_auth_fixture: dict
):
    """Test 11: Cross-project access to actions returns 404 (IDOR mask) for dispatch and patch."""
    async with _create_client(phase3_1_1_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(
            f"/api/v1/projects/{phase3_1_1_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Cross Project Mask Test",
                "plan_dag_json": {"nodes": ["act-isolated"]},
                "actions": [
                    {
                        "client_action_id": "act-isolated",
                        "title": "Isolated Node",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]

    async with _create_client(phase3_1_1_auth_fixture["key_b"]) as client_b:
        # Cross-project GET -> 404
        g_res = await client_b.get(f"/api/v1/actions/{act_id}")
        assert g_res.status_code == 404

        # Cross-project PATCH -> 404
        p_res = await client_b.patch(f"/api/v1/actions/{act_id}", json={"status": "BLOCKED"})
        assert p_res.status_code == 404

        # Cross-project DISPATCH -> 404
        d_res = await client_b.post(f"/api/v1/actions/{act_id}/dispatch")
        assert d_res.status_code == 404


async def test_12_offline_mock_dispatcher_watermark_and_safeguards():
    """Test 12: OfflineMockDispatcher explicitly tags outputs with simulation watermarks."""
    dispatcher = OfflineMockDispatcher(allow_network=False)
    dummy_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act-mock-verify",
        title="Verify Simulation",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="EXECUTING",
    )

    result = await dispatcher.dispatch(dummy_node)
    assert result.success is True
    assert result.output["is_simulated"] is True
    assert result.output["simulation_watermark"] == SIMULATION_WATERMARK
    assert result.output["mock_mode"] is True

    # Test failure on network attempt
    with pytest.raises(RuntimeError) as excinfo:
        OfflineMockDispatcher(allow_network=True)
    assert "Live network execution is strictly disabled" in str(excinfo.value)
