"""
AryaOS V1 Stage 25 Phase 3.1 — Offline Autonomous Execution Runner Integration Tests.

Validates the Phase 3.1 Offline Runner Core and Execution Safeguards:
1. Valid DAG actions become ready only when dependencies succeed.
2. Failed or blocked prerequisites prevent downstream dispatch.
3. Cycles and malformed DAGs are rejected.
4. Duplicate execution requests do not create duplicate simulated dispatches (Idempotency).
5. Concurrent workers cannot both claim the same action (Lease and concurrency control).
6. Illegal lifecycle transitions are rejected.
7. Clients cannot force terminal success (COMPLETED / SUCCEEDED).
8. High-risk actions do not dispatch without valid human approval.
9. Unknown outcomes are never converted into success (Preservation of UNKNOWN).
10. Restart/recovery behavior does not blindly replay an ambiguous dispatch.
11. Project isolation is preserved (Cross-project IDOR protection).
12. Mock execution is explicitly identified as simulated (Watermark and flags).
13. The suite fails if any real network, provider, or subprocess dispatch is attempted.
14. Full goal DAG progression (root -> child -> goal COMPLETED).
"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    Mission,
)
from app.services.authorization_service import add_project_membership, create_api_key
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    OfflineMockDispatcher,
    SIMULATION_WATERMARK,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_external_network_and_subprocess(monkeypatch):
    """Guarantees zero network and zero subprocess calls occur during test execution."""

    def _block_call(*args, **kwargs):
        raise RuntimeError(
            "VIOLATION: External network or subprocess call attempted during Phase 3.1 offline execution!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _block_call)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _block_call)
    monkeypatch.setattr("subprocess.Popen", _block_call)


@pytest_asyncio.fixture(loop_scope="module")
async def phase3_auth_fixture(db_session: AsyncSession):
    """Provisions isolated projects with scoped API keys for Phase 3.1 testing."""
    settings = get_settings()
    original_auth_enabled = settings.api_auth_enabled
    settings.api_auth_enabled = True

    proj_a = Project(name=f"project-phase3-a-{uuid.uuid4()}", status="ACTIVE")
    proj_b = Project(name=f"project-phase3-b-{uuid.uuid4()}", status="ACTIVE")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    key_a_model, key_a_raw = await create_api_key(db_session, name="Key A Phase 3", is_admin=False)
    key_b_model, key_b_raw = await create_api_key(db_session, name="Key B Phase 3", is_admin=False)
    admin_model, admin_raw = await create_api_key(db_session, name="Admin Key Phase 3", is_admin=True)

    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="owner")
    await add_project_membership(db_session, project_id=proj_b.id, api_key_id=key_b_model.id, role="owner")

    yield {
        "proj_a_id": proj_a.id,
        "proj_b_id": proj_b.id,
        "key_a": key_a_raw,
        "key_b": key_b_raw,
        "key_admin": admin_raw,
        "key_a_id": key_a_model.id,
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
# 1. Dependency Ordering & Readiness Tests
# ===========================================================================

async def test_01_valid_dag_actions_become_ready_only_when_prerequisites_succeed(
    phase3_auth_fixture: dict,
):
    """Test 1: Child actions in a DAG remain PENDING until all prerequisites SUCCEED."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        # Create a 2-node DAG: act-01 -> act-02
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "DAG Dependency Ordering Test",
                "plan_dag_json": {
                    "nodes": ["act-01", "act-02"],
                    "edges": [{"source": "act-01", "target": "act-02"}],
                },
                "actions": [
                    {
                        "client_action_id": "act-01",
                        "title": "Prerequisite Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                    {
                        "client_action_id": "act-02",
                        "title": "Dependent Action",
                        "action_type": "SYNTHESIS",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                ],
            },
        )
        assert res.status_code == 201
        goal_data = res.json()
        goal_id = goal_data["id"]
        act_01_id = goal_data["actions"][0]["id"]
        act_02_id = goal_data["actions"][1]["id"]

        # Run first execution step: act-01 should become READY, execute, and SUCCEED
        # act-02 should transition PENDING -> READY after act-01 succeeds
        step_res = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert step_res.status_code == 200
        step_data = step_res.json()

        act_01 = next(a for a in step_data["actions"] if a["id"] == act_01_id)
        act_02 = next(a for a in step_data["actions"] if a["id"] == act_02_id)

        assert act_01["status"] == "SUCCEEDED"
        # act-02 was unblocked and is now READY (or executed if batch allowed)
        assert act_02["status"] in ("READY", "SUCCEEDED")


async def test_02_failed_prerequisites_block_downstream_dispatch(
    phase3_auth_fixture: dict,
):
    """Test 2: Failure in a prerequisite action transitions downstream nodes to BLOCKED."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        # Create DAG: act-fail -> act-dependent
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Failure Blocking Test",
                "plan_dag_json": {
                    "nodes": ["act-fail", "act-dependent"],
                    "edges": [{"source": "act-fail", "target": "act-dependent"}],
                },
                "actions": [
                    {
                        "client_action_id": "act-fail",
                        "title": "Failing Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                        "inputs_json": {"mock_failure": True, "mock_failure_message": "Upstream error"},
                    },
                    {
                        "client_action_id": "act-dependent",
                        "title": "Downstream Action",
                        "action_type": "SYNTHESIS",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                ],
            },
        )
        assert res.status_code == 201
        goal_data = res.json()
        goal_id = goal_data["id"]
        fail_id = goal_data["actions"][0]["id"]
        dep_id = goal_data["actions"][1]["id"]

        # Execute goal step: act-fail executes and FAILS
        step_res = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert step_res.status_code == 200
        data = step_res.json()

        act_fail = next(a for a in data["actions"] if a["id"] == fail_id)
        act_dep = next(a for a in data["actions"] if a["id"] == dep_id)

        assert act_fail["status"] == "FAILED"
        assert act_dep["status"] == "BLOCKED"

        # Attempting to dispatch act_dep directly must be rejected with 409 Conflict
        disp_res = await client.post(f"/api/v1/actions/{dep_id}/dispatch")
        assert disp_res.status_code == 409
        assert "BLOCKED" in disp_res.json()["detail"]


# ===========================================================================
# 2. Cycle Detection & Malformed DAG Rejection
# ===========================================================================

async def test_03_cycles_and_malformed_dags_are_rejected(phase3_auth_fixture: dict):
    """Test 3: Cyclic DAGs or edges referencing undeclared nodes are rejected."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        # A. Self-cycle
        res1 = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Cycle Test",
                "plan_dag_json": {
                    "nodes": ["act-01"],
                    "edges": [{"source": "act-01", "target": "act-01"}],
                },
                "actions": [
                    {
                        "client_action_id": "act-01",
                        "title": "Self Cycle",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        assert res1.status_code == 422
        assert "Self-dependency" in res1.json()["detail"]

        # B. 2-node cycle (A -> B -> A)
        res2 = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "2-Cycle Test",
                "plan_dag_json": {
                    "nodes": ["a", "b"],
                    "edges": [
                        {"source": "a", "target": "b"},
                        {"source": "b", "target": "a"},
                    ],
                },
                "actions": [
                    {"client_action_id": "a", "title": "A", "action_type": "RESEARCH", "required_capability": "REASONING"},
                    {"client_action_id": "b", "title": "B", "action_type": "RESEARCH", "required_capability": "REASONING"},
                ],
            },
        )
        assert res2.status_code == 422
        assert "Cyclic dependency" in res2.json()["detail"]


# ===========================================================================
# 3. Idempotency & Concurrency Lease Control
# ===========================================================================

async def test_04_duplicate_execution_requests_are_idempotent(phase3_auth_fixture: dict):
    """Test 4: Re-dispatching an already SUCCEEDED action returns cached result without re-executing."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        # Create single action goal
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Idempotency Test",
                "plan_dag_json": {"nodes": ["act-single"]},
                "actions": [
                    {
                        "client_action_id": "act-single",
                        "title": "Single Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]
        goal_id = res.json()["id"]

        # First dispatch -> SUCCEEDED
        disp1 = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp1.status_code == 200
        data1 = disp1.json()
        assert data1["status"] == "SUCCEEDED"
        output_ts = data1["outputs_json"]["timestamp"]

        # Second dispatch -> must return same result idempotently
        disp2 = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp2.status_code == 200
        data2 = disp2.json()
        assert data2["status"] == "SUCCEEDED"
        assert data2["outputs_json"]["timestamp"] == output_ts


async def test_05_concurrent_worker_leases_prevent_duplicate_claims(
    db_session: AsyncSession, phase3_auth_fixture: dict
):
    """Test 5: When an action has an active unexpired worker lease, another worker is rejected with 409."""
    from app.core.security import AuthenticatedPrincipal

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="test-operator",
        is_admin=True,
    )

    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Lease Test",
                "plan_dag_json": {"nodes": ["act-lease"]},
                "actions": [
                    {
                        "client_action_id": "act-lease",
                        "title": "Leased Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = uuid.UUID(res.json()["actions"][0]["id"])

    # Worker A claims action
    runner_a = AutonomousExecutionRunner(db=db_session, worker_id="worker-alpha")
    runner_b = AutonomousExecutionRunner(db=db_session, worker_id="worker-bravo")

    # Manually transition to EXECUTING with worker-alpha's unexpired lease
    action = await db_session.get(AutonomousActionNode, act_id)
    action.status = "EXECUTING"
    action.inputs_json = {
        "lease": {
            "worker_id": "worker-alpha",
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc).replace(year=2030)).isoformat(),
        }
    }
    await db_session.commit()

    # Worker B attempts to dispatch -> must raise 409 Conflict
    with pytest.raises(Exception) as exc_info:
        await runner_b.dispatch_action(act_id, principal)

    assert "currently claimed by worker" in str(exc_info.value)
    assert exc_info.value.status_code == 409


# ===========================================================================
# 4. State Machine Transition & Terminal Success Guards
# ===========================================================================

async def test_06_illegal_lifecycle_transitions_rejected(phase3_auth_fixture: dict):
    """Test 6: Illegal transitions (e.g. SUCCEEDED -> READY) are rejected with 409."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Illegal Transition Test",
                "plan_dag_json": {"nodes": ["act-trans"]},
                "actions": [
                    {
                        "client_action_id": "act-trans",
                        "title": "Transition Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]

        # Complete the action
        await client.post(f"/api/v1/actions/{act_id}/dispatch")

        # Try to transition SUCCEEDED back to READY
        patch_res = await client.patch(
            f"/api/v1/actions/{act_id}",
            json={"status": "READY"},
        )
        assert patch_res.status_code == 409
        assert "Illegal ActionNode state transition" in patch_res.json()["detail"]


async def test_07_clients_cannot_force_terminal_success(phase3_auth_fixture: dict):
    """Test 7: Client PATCH requests cannot force SUCCEEDED or COMPLETED directly."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Terminal Guard Test",
                "plan_dag_json": {"nodes": ["act-guard"]},
                "actions": [
                    {
                        "client_action_id": "act-guard",
                        "title": "Guarded Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        goal_id = res.json()["id"]
        act_id = res.json()["actions"][0]["id"]

        # Attempt to force action to SUCCEEDED
        p_act = await client.patch(f"/api/v1/actions/{act_id}", json={"status": "SUCCEEDED"})
        assert p_act.status_code == 409
        assert "Client cannot directly force ActionNode into terminal state 'SUCCEEDED'" in p_act.json()["detail"]

        # Attempt to force goal to COMPLETED
        p_goal = await client.patch(f"/api/v1/goals/{goal_id}", json={"status": "COMPLETED"})
        assert p_goal.status_code == 409
        assert "Client cannot directly force Goal into terminal state 'COMPLETED'" in p_goal.json()["detail"]


# ===========================================================================
# 5. Governance & High-Risk Human Approval
# ===========================================================================

async def test_08_high_risk_actions_require_human_approval_before_dispatch(
    db_session: AsyncSession, phase3_auth_fixture: dict
):
    """Test 8: Actions with risk_level == HIGH halt at AWAITING_APPROVAL and cannot dispatch without signoff."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "High Risk Approval Test",
                "plan_dag_json": {"nodes": ["act-high-risk"]},
                "actions": [
                    {
                        "client_action_id": "act-high-risk",
                        "title": "Consequential Production Action",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "PRODUCTION_DISPATCH",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        goal_id = res.json()["id"]
        act_id = uuid.UUID(res.json()["actions"][0]["id"])

        # Execute goal step: the runner must transition node to AWAITING_APPROVAL (not READY)
        step_res = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert step_res.status_code == 200
        step_data = step_res.json()
        assert step_data["status"] == "AWAITING_APPROVAL"
        act_node = step_data["actions"][0]
        assert act_node["status"] == "AWAITING_APPROVAL"

        # Attempting dispatch directly must be rejected
        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "requires human operator approval" in disp_res.json()["detail"]

        # Now link a valid approved ApprovalCheckpoint with human provenance
        # Create a WorkflowRun to satisfy ApprovalCheckpoint FK
        wf = WorkflowRun(
            project_id=phase3_auth_fixture["proj_a_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        from app.models.core import ApiKey
        key_a_obj = await db_session.get(ApiKey, phase3_auth_fixture["key_a_id"])
        key_a_obj.principal_type = "human"
        await db_session.commit()

        checkpoint = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Approved by human director",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
            decided_by_principal_id=key_a_obj.id,
            decided_by_actor_type="human",
            decided_by_principal_name=key_a_obj.name,
        )
        db_session.add(checkpoint)
        await db_session.flush()

        action_record = await db_session.get(AutonomousActionNode, act_id)
        action_record.approval_checkpoint_id = checkpoint.id
        await db_session.commit()

        # Now dispatch must succeed
        disp_ok = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_ok.status_code == 200
        assert disp_ok.json()["status"] == "SUCCEEDED"


# ===========================================================================
# 6. Preservation of UNKNOWN & Recovery Protection
# ===========================================================================

async def test_09_unknown_outcomes_are_never_converted_to_success(phase3_auth_fixture: dict):
    """Test 9: Ambiguous outcomes transition to UNKNOWN_PENDING_RECONCILIATION, never SUCCEEDED."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Unknown Outcome Test",
                "plan_dag_json": {
                    "nodes": ["act-ambiguous", "act-downstream"],
                    "edges": [{"source": "act-ambiguous", "target": "act-downstream"}],
                },
                "actions": [
                    {
                        "client_action_id": "act-ambiguous",
                        "title": "Ambiguous Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "inputs_json": {"mock_unknown": True},
                    },
                    {
                        "client_action_id": "act-downstream",
                        "title": "Blocked Downstream",
                        "action_type": "SYNTHESIS",
                        "required_capability": "REASONING",
                    },
                ],
            },
        )
        goal_id = res.json()["id"]
        amb_id = res.json()["actions"][0]["id"]
        down_id = res.json()["actions"][1]["id"]

        # Dispatch ambiguous action
        disp_res = await client.post(f"/api/v1/actions/{amb_id}/dispatch")
        assert disp_res.status_code == 200
        amb_data = disp_res.json()

        assert amb_data["status"] == "UNKNOWN_PENDING_RECONCILIATION"
        assert amb_data["status"] != "SUCCEEDED"
        assert amb_data["outputs_json"]["epistemic_status"] == "UNKNOWN"

        # Downstream action must NOT be unblocked
        down_res = await client.get(f"/api/v1/actions/{down_id}")
        assert down_res.json()["status"] == "PENDING"


async def test_10_recovery_does_not_blindly_replay_ambiguous_dispatch(phase3_auth_fixture: dict):
    """Test 10: Re-running goal progression on an action in UNKNOWN state does not replay or mark successful."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Recovery Guard Test",
                "plan_dag_json": {"nodes": ["act-unknown-recheck"]},
                "actions": [
                    {
                        "client_action_id": "act-unknown-recheck",
                        "title": "Unknown Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "inputs_json": {"mock_unknown": True},
                    }
                ],
            },
        )
        goal_id = res.json()["id"]
        act_id = res.json()["actions"][0]["id"]

        # First dispatch -> UNKNOWN_PENDING_RECONCILIATION
        await client.post(f"/api/v1/actions/{act_id}/dispatch")

        # Execute goal step again
        step_res = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert step_res.status_code == 200
        node = step_res.json()["actions"][0]

        # Must remain in UNKNOWN_PENDING_RECONCILIATION
        assert node["status"] == "UNKNOWN_PENDING_RECONCILIATION"
        assert step_res.json()["status"] != "COMPLETED"


# ===========================================================================
# 7. Project Isolation & Security
# ===========================================================================

async def test_11_project_isolation_prevents_cross_project_dispatch(phase3_auth_fixture: dict):
    """Test 11: Principal B cannot dispatch or execute goals belonging to Project A."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Isolation Test",
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
        goal_id = res.json()["id"]
        act_id = res.json()["actions"][0]["id"]

    # Principal B tries to execute Project A's goal
    async with _create_client(phase3_auth_fixture["key_b"]) as client_b:
        exec_b = await client_b.post(f"/api/v1/goals/{goal_id}/execute")
        assert exec_b.status_code == 404

        disp_b = await client_b.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_b.status_code == 404


# ===========================================================================
# 8. Truthful Simulation & Watermarking
# ===========================================================================

async def test_12_mock_execution_is_explicitly_watermarked_and_simulated(phase3_auth_fixture: dict):
    """Test 12: Outputs explicitly state is_simulated=True and include the offline watermark."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "Watermark Test",
                "plan_dag_json": {"nodes": ["act-watermark"]},
                "actions": [
                    {
                        "client_action_id": "act-watermark",
                        "title": "Watermarked Action",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                    }
                ],
            },
        )
        act_id = res.json()["actions"][0]["id"]

        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 200
        outputs = disp_res.json()["outputs_json"]

        assert outputs["is_simulated"] is True
        assert outputs["mock_mode"] is True
        assert outputs["simulation_watermark"] == SIMULATION_WATERMARK
        assert outputs["simulated_provider"] == "mock-provider-offline"


# ===========================================================================
# 9. Offline-Only Enforcement & Live Attempt Failure
# ===========================================================================

async def test_13_runner_fails_closed_if_live_execution_attempted(phase3_auth_fixture: dict):
    """Test 13: Attempting to instantiate an offline dispatcher with live execution enabled raises RuntimeError."""
    with pytest.raises(RuntimeError) as exc_info:
        OfflineMockDispatcher(allow_network=True)
    assert "Live network execution is strictly disabled" in str(exc_info.value)


# ===========================================================================
# 10. End-to-End Goal DAG Progression
# ===========================================================================

async def test_14_end_to_end_goal_dag_progression_to_completed(phase3_auth_fixture: dict):
    """Test 14: Multi-step goal DAG runs to completion in offline simulated mode."""
    async with _create_client(phase3_auth_fixture["key_a"]) as client:
        # Create DAG: step1 -> step2
        res = await client.post(
            f"/api/v1/projects/{phase3_auth_fixture['proj_a_id']}/goals",
            json={
                "objective": "E2E Goal Offline Progression",
                "plan_dag_json": {
                    "nodes": ["step1", "step2"],
                    "edges": [{"source": "step1", "target": "step2"}],
                },
                "actions": [
                    {
                        "client_action_id": "step1",
                        "title": "Step 1: Background Analysis",
                        "action_type": "RESEARCH",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                    {
                        "client_action_id": "step2",
                        "title": "Step 2: Synthesis Document",
                        "action_type": "SYNTHESIS",
                        "required_capability": "REASONING",
                        "risk_level": "LOW",
                    },
                ],
            },
        )
        assert res.status_code == 201
        goal_id = res.json()["id"]

        # Run step 1: step1 runs and completes
        res_step1 = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert res_step1.status_code == 200
        goal_s1 = res_step1.json()
        assert goal_s1["status"] in ("EXECUTING", "COMPLETED")

        # Run step 2 if not completed yet
        if goal_s1["status"] != "COMPLETED":
            res_step2 = await client.post(f"/api/v1/goals/{goal_id}/execute")
            assert res_step2.status_code == 200
            goal_s2 = res_step2.json()
            assert goal_s2["status"] == "COMPLETED"
            assert "completed successfully" in goal_s2["final_summary"]
        else:
            assert "completed successfully" in goal_s1["final_summary"]
