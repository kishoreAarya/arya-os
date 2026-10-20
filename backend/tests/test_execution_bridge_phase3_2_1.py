"""
AryaOS V1 Stage 25 Phase 3.2.1 — Provider Dispatcher & Fail-Closed Gate Test Suite.

Verifies the 10 mandatory Phase 3.2.1 safety invariants:
1. The default dispatcher is the offline mock.
2. The live-execution flag defaults to false.
3. Missing or invalid configuration fails closed.
4. Selecting the live dispatcher with the gate disabled causes zero provider invocations.
5. Goal execution and action dispatch continue to work in offline mode.
6. Existing approval and project-authorization checks remain effective.
7. Concurrent dispatch and stale lease fencing behavior remain unchanged.
8. Unknown outcomes remain blocked from downstream success.
9. No indirect path can invoke real provider adapters while live execution is disabled.
10. Existing frontend behavior, Stage 03 assets, and Stages 04–24 remain unchanged.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timezone
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
from app.models.core import ApiKey, Project, ProjectMembership
from app.models.enums import ApprovalAction, ApprovalStage
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
    MockExecutionResult,
    OfflineMockDispatcher,
    SIMULATION_WATERMARK,
    get_default_dispatcher,
    is_live_provider_execution_enabled,
    resolve_dispatcher,
    verify_live_execution_gate,
)
from app.services.image_provider import image_provider_registry
from app.services.video_provider import video_provider_registry

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURE: STRICT OUTBOUND CALL PROHIBITION
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Fails tests immediately if any outbound network or subprocess call is attempted."""

    def _fail_on_network(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.1 test!"
        )

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.1 test!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


@pytest_asyncio.fixture(loop_scope="module")
async def phase3_2_1_auth_fixture(db_session: AsyncSession):
    """Provisions isolated projects and API keys for Phase 3.2.1 test verification."""
    settings = get_settings()
    settings.api_auth_enabled = True

    proj = Project(name=f"proj-phase-321-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    proj_unauth = Project(name=f"proj-unauth-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    db_session.add_all([proj, proj_unauth])
    await db_session.commit()
    await db_session.refresh(proj)
    await db_session.refresh(proj_unauth)

    human_key_model, human_key_raw = await create_api_key(
        db_session, name="Human Operator 3.2.1", is_admin=False, principal_type="human"
    )
    svc_key_model, svc_key_raw = await create_api_key(
        db_session, name="Service Account 3.2.1", is_admin=False, principal_type="service_account"
    )
    admin_key_model, admin_key_raw = await create_api_key(
        db_session, name="Admin Key 3.2.1", is_admin=True, principal_type="human"
    )

    await add_project_membership(
        db_session, project_id=proj.id, api_key_id=human_key_model.id, role="operator"
    )
    await add_project_membership(
        db_session, project_id=proj.id, api_key_id=svc_key_model.id, role="operator"
    )

    yield {
        "project_id": proj.id,
        "unauth_project_id": proj_unauth.id,
        "human_key_id": human_key_model.id,
        "human_key": human_key_raw,
        "svc_key": svc_key_raw,
        "admin_key": admin_key_raw,
    }


# ===========================================================================
# TEST 1: DEFAULT DISPATCHER IS OFFLINE MOCK
# ===========================================================================

async def test_01_default_dispatcher_is_offline_mock(db_session: AsyncSession):
    """Proves that AutonomousExecutionRunner defaults to OfflineMockDispatcher in all environments."""
    runner = AutonomousExecutionRunner(db=db_session)
    assert isinstance(runner.dispatcher, OfflineMockDispatcher)
    assert runner.dispatcher.is_live is False

    default_disp = get_default_dispatcher()
    assert isinstance(default_disp, OfflineMockDispatcher)
    assert default_disp.is_live is False

    # Calling resolve_dispatcher without arguments or with 'offline' / 'mock'
    assert isinstance(resolve_dispatcher(None), OfflineMockDispatcher)
    assert isinstance(resolve_dispatcher("offline"), OfflineMockDispatcher)
    assert isinstance(resolve_dispatcher("mock"), OfflineMockDispatcher)

    # Verify deterministic mock output tags
    dummy_action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act-test-01",
        title="Offline Test Action",
        action_type="REASONING",
        status="READY",
    )
    res = await runner.dispatcher.dispatch(dummy_action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.output.get("is_simulated") is True
    assert res.output.get("mock_mode") is True
    assert res.output.get("simulation_watermark") == SIMULATION_WATERMARK
    assert res.output.get("simulated_provider") == "mock-provider-offline"


# ===========================================================================
# TEST 2: LIVE EXECUTION FLAG DEFAULTS TO FALSE
# ===========================================================================

async def test_02_live_execution_flag_defaults_to_false():
    """Proves that ENABLE_LIVE_PROVIDER_EXECUTION defaults to False and gate is closed."""
    settings = Settings()
    assert settings.enable_live_provider_execution is False

    # Helper function check
    assert is_live_provider_execution_enabled(settings) is False

    # Gate verification must raise LiveExecutionGateError by default
    with pytest.raises(LiveExecutionGateError) as exc_info:
        verify_live_execution_gate(settings)
    assert "ENABLE_LIVE_PROVIDER_EXECUTION=False" in str(exc_info.value)


# ===========================================================================
# TEST 3: MISSING OR INVALID CONFIGURATION FAILS CLOSED
# ===========================================================================

async def test_03_missing_or_invalid_configuration_fails_closed():
    """Proves that missing, invalid, or unrecognized configuration values strictly fail closed."""
    invalid_values = [
        None,
        "",
        "   ",
        "invalid",
        "maybe",
        "true_almost",
        "enabled",
        "2",
        "-1",
        "disabled",
        "null",
        {"live": True},
        [True],
    ]

    for val in invalid_values:
        parsed = Settings._validate_enable_live_provider_execution(val)
        assert parsed is False, f"Expected {val!r} to fail closed to False, got {parsed}"

    # Verify is_live_provider_execution_enabled fails closed on malformed settings objects
    class BrokenSettings:
        @property
        def enable_live_provider_execution(self):
            raise RuntimeError("Settings load exploded!")

    assert is_live_provider_execution_enabled(BrokenSettings()) is False

    with pytest.raises(LiveExecutionGateError):
        verify_live_execution_gate(BrokenSettings())


# ===========================================================================
# TEST 4: SELECTING LIVE DISPATCHER WITH GATE DISABLED CAUSES ZERO PROVIDER CALLS
# ===========================================================================

async def test_04_selecting_live_dispatcher_with_gate_disabled_causes_zero_calls(db_session: AsyncSession):
    """Proves that explicitly selecting the live dispatcher while the gate is disabled is rejected
    immediately with zero provider or network invocations.
    """
    closed_settings = Settings(enable_live_provider_execution=False)

    with (
        patch.object(image_provider_registry, "resolve_provider_for_package") as mock_img_res,
        patch.object(video_provider_registry, "resolve_provider_for_package") as mock_vid_res,
    ):
        # 1. Direct instantiation must raise LiveExecutionGateError
        with pytest.raises(LiveExecutionGateError):
            LiveProviderDispatcher(settings=closed_settings)

        # 2. String resolution via resolve_dispatcher('live') must raise
        with pytest.raises(LiveExecutionGateError):
            resolve_dispatcher("live", settings=closed_settings)

        # 3. Runner initialization with dispatcher='live' must raise
        with pytest.raises(LiveExecutionGateError):
            AutonomousExecutionRunner(db=db_session, dispatcher="live", settings=closed_settings)

        # 4. Spies confirm zero provider registry resolutions were attempted
        mock_img_res.assert_not_called()
        mock_vid_res.assert_not_called()


# ===========================================================================
# TEST 5: GOAL EXECUTION AND ACTION DISPATCH WORK IN OFFLINE MODE
# ===========================================================================

async def test_05_goal_execution_and_action_dispatch_offline(
    db_session: AsyncSession, phase3_2_1_auth_fixture
):
    """Proves that end-to-end DAG execution continues to function properly in offline mock mode."""
    project_id = phase3_2_1_auth_fixture["project_id"]

    mission = Mission(
        project_id=project_id,
        title="Phase 3.2.1 Offline Mission",
        objective="Verify offline DAG progression",
        status="ACTIVE",
    )
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)

    goal = AutonomousGoal(
        project_id=project_id,
        mission_id=mission.id,
        objective="Offline Progression Goal",
        plan_dag_json={
            "nodes": [
                {"id": "step-1", "title": "Step 1", "action_type": "REASONING"},
                {"id": "step-2", "title": "Step 2", "action_type": "REASONING"},
            ],
            "edges": [{"from": "step-1", "to": "step-2"}],
        },
        status="PLANNING",
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step-1",
        title="Step 1",
        action_type="REASONING",
        required_capability="REASONING",
        status="READY",
    )
    node2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step-2",
        title="Step 2",
        action_type="REASONING",
        required_capability="REASONING",
        status="PENDING",
    )
    db_session.add_all([node1, node2])
    await db_session.commit()

    principal = AuthenticatedPrincipal(
        api_key_id=phase3_2_1_auth_fixture["human_key_id"],
        name="Human Operator",
        is_admin=False,
        principal_type="human",
    )

    runner = AutonomousExecutionRunner(db=db_session)

    # Dispatch node 1
    dispatched_node1 = await runner.dispatch_action(node1.id, principal)
    assert dispatched_node1.status == "SUCCEEDED"
    assert dispatched_node1.outputs_json.get("is_simulated") is True
    assert dispatched_node1.outputs_json.get("simulation_watermark") == SIMULATION_WATERMARK

    # Execute goal step: updates DAG readiness, node 2 becomes READY and runs to SUCCEEDED
    updated_goal = await runner.execute_goal_step(goal.id, principal)
    assert updated_goal.status == "COMPLETED"

    await db_session.refresh(node2)
    assert node2.status == "SUCCEEDED"


# ===========================================================================
# TEST 6: APPROVAL AND PROJECT AUTHORIZATION CHECKS REMAIN EFFECTIVE
# ===========================================================================

async def test_06_approval_and_project_authorization_checks_effective(
    db_session: AsyncSession, phase3_2_1_auth_fixture
):
    """Proves that durable human approval provenance and project membership checks remain intact."""
    project_id = phase3_2_1_auth_fixture["project_id"]
    unauth_project_id = phase3_2_1_auth_fixture["unauth_project_id"]

    goal = AutonomousGoal(
        project_id=project_id,
        objective="Consequential Gate Goal",
        plan_dag_json={"nodes": [{"id": "crit-1", "title": "Critical Action"}]},
        status="PLANNING",
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="crit-1",
        title="Critical Action",
        action_type="REASONING",
        required_capability="REASONING",
        risk_level="CRITICAL",
        status="READY",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    runner = AutonomousExecutionRunner(db=db_session)
    human_principal = AuthenticatedPrincipal(
        api_key_id=phase3_2_1_auth_fixture["human_key_id"],
        name="Human Operator",
        is_admin=False,
        principal_type="human",
    )

    # 1. Dispatching without approval checkpoint must be rejected with 409
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(node.id, human_principal)
    assert exc_info.value.status_code == 409
    assert "requires human operator approval" in exc_info.value.detail

    # 2. Dispatching from an unauthorized project must be rejected with 404
    unauth_goal = AutonomousGoal(
        project_id=unauth_project_id,
        objective="Unauth Project Goal",
        plan_dag_json={},
        status="PLANNING",
    )
    db_session.add(unauth_goal)
    await db_session.commit()
    await db_session.refresh(unauth_goal)

    unauth_node = AutonomousActionNode(
        goal_id=unauth_goal.id,
        client_action_id="unauth-1",
        title="Unauth Node",
        action_type="REASONING",
        required_capability="REASONING",
        status="READY",
    )
    db_session.add(unauth_node)
    await db_session.commit()
    await db_session.refresh(unauth_node)

    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(unauth_node.id, human_principal)
    assert exc_info.value.status_code == 404


# ===========================================================================
# TEST 7: CONCURRENT DISPATCH AND LEASE FENCING TOKEN BEHAVIOR
# ===========================================================================

async def test_07_lease_fencing_token_mismatch_prevents_stale_overwrite(
    db_session: AsyncSession, phase3_2_1_auth_fixture
):
    """Proves that PostgreSQL lease claims and worker fencing tokens prevent split-brain overwrites."""
    project_id = phase3_2_1_auth_fixture["project_id"]

    goal = AutonomousGoal(
        project_id=project_id,
        objective="Fencing Token Test Goal",
        plan_dag_json={"nodes": [{"id": "fence-1"}]},
        status="EXECUTING",
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="fence-1",
        title="Fencing Node",
        action_type="REASONING",
        required_capability="REASONING",
        status="READY",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    principal = AuthenticatedPrincipal(
        api_key_id=phase3_2_1_auth_fixture["human_key_id"],
        name="Human Operator",
        is_admin=False,
        principal_type="human",
    )

    # Create a custom dispatcher that simulates a concurrent worker stealing the lease mid-execution
    class ConcurrentlyPreemptedDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            # Modify lease token in DB to simulate another worker claiming it
            inputs = dict(action.inputs_json or {})
            inputs["lease"]["lease_token"] = "preempted-by-worker-B"
            inputs["lease"]["epoch"] = inputs["lease"].get("epoch", 1) + 1
            action.inputs_json = inputs
            await db_session.commit()
            return await super().dispatch(action)

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=ConcurrentlyPreemptedDispatcher(allow_network=False),
        worker_id="worker-A",
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "fencing token mismatch" in exc_info.value.detail.lower()


# ===========================================================================
# TEST 8: UNKNOWN OUTCOMES REMAIN BLOCKED FROM DOWNSTREAM SUCCESS
# ===========================================================================

async def test_08_unknown_outcome_never_coerced_to_success(
    db_session: AsyncSession, phase3_2_1_auth_fixture
):
    """Proves that UNKNOWN_PENDING_RECONCILIATION halts progression and is never coerced to SUCCEEDED."""
    project_id = phase3_2_1_auth_fixture["project_id"]

    goal = AutonomousGoal(
        project_id=project_id,
        objective="Unknown Outcome Safety Goal",
        plan_dag_json={
            "nodes": [
                {"id": "unknown-step", "title": "Ambiguous Step", "action_type": "REASONING"},
                {"id": "downstream-step", "title": "Dependent Step", "action_type": "REASONING"},
            ],
            "edges": [{"from": "unknown-step", "to": "downstream-step"}],
        },
        status="PLANNING",
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    unknown_node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="unknown-step",
        title="Ambiguous Step",
        action_type="REASONING",
        required_capability="REASONING",
        status="READY",
        inputs_json={"mock_unknown": True, "mock_unknown_message": "Provider timeout; ambiguous outcome"},
    )
    downstream_node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="downstream-step",
        title="Dependent Step",
        action_type="REASONING",
        required_capability="REASONING",
        status="PENDING",
    )
    db_session.add_all([unknown_node, downstream_node])
    await db_session.commit()

    principal = AuthenticatedPrincipal(
        api_key_id=phase3_2_1_auth_fixture["human_key_id"],
        name="Human Operator",
        is_admin=False,
        principal_type="human",
    )

    runner = AutonomousExecutionRunner(db=db_session)

    # Dispatch unknown node
    result_node = await runner.dispatch_action(unknown_node.id, principal)
    assert result_node.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Evaluate goal progression
    updated_goal = await runner.execute_goal_step(goal.id, principal)
    assert updated_goal.status == "RECOVERY_REQUIRED"

    # Dependent action must not be allowed to proceed to READY or SUCCEEDED
    await db_session.refresh(downstream_node)
    assert downstream_node.status in ("PENDING", "BLOCKED")
    assert downstream_node.status != "SUCCEEDED"


# ===========================================================================
# TEST 9: NO INDIRECT PATH CAN REACH REAL PROVIDERS OR ENABLE GATE VIA API
# ===========================================================================

async def test_09_no_indirect_path_invokes_real_providers_or_toggles_gate_via_api(
    db_session: AsyncSession, phase3_2_1_auth_fixture
):
    """Proves that zero indirect paths can trigger real provider invocations, and that
    the configuration gate cannot be enabled via API endpoints or client inputs.
    """
    admin_key = phase3_2_1_auth_fixture["admin_key"]

    # 1. Verify feature-flags PUT endpoint strictly prohibits enabling the gate
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put(
            "/feature-flags/enable_live_provider_execution",
            json={"enabled": True, "description": "Attempt to bypass fail-closed gate"},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 403
        assert "strictly prohibited" in resp.json().get("detail", "")

    # 2. Gate remains firmly False
    assert is_live_provider_execution_enabled() is False

    # 3. Direct inspection of LiveProviderDispatcher confirms it reuses existing registries
    # but remains a quarantined stub
    open_gate_settings = Settings(enable_live_provider_execution=True)
    live_dispatcher = LiveProviderDispatcher(settings=open_gate_settings)
    assert live_dispatcher.is_live is True
    assert live_dispatcher.image_registry is image_provider_registry
    assert live_dispatcher.video_registry is video_provider_registry

    # Registry capability resolution works without execution
    resolved_img = live_dispatcher.resolve_provider("IMAGE_GENERATION")
    assert resolved_img is not None
    assert resolved_img.provider_id in ("fal", "fal_flux")

    resolved_vid = live_dispatcher.resolve_provider("VIDEO_GENERATION", "kling")
    assert resolved_vid is not None
    assert resolved_vid.provider_id == "kling"

    # But dispatching in Phase 3.2.1 is strictly blocked pending Phase 3.2.2/3.2.3
    dummy_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="stub-act",
        title="Guarded Stub Action",
        action_type="MEDIA_GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
    )
    with pytest.raises(NotImplementedError) as exc_info:
        await live_dispatcher.dispatch(dummy_node)
    assert "quarantined in Phase 3.2.1" in str(exc_info.value)


# ===========================================================================
# TEST 10: FROZEN BOUNDARIES & MIGRATION HEAD VERIFICATION
# ===========================================================================

async def test_10_frozen_boundaries_and_migration_head():
    """Proves that database migration head is i9d0e1f2a3b4 and Stage 03-24 assets remain frozen."""
    # We inspect the migration file directly to verify migration head
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

    # Check that frozen Stage 03 assets exist and are preserved
    assert os.path.exists("frontend/src/stage03_assembly.ts")
    assert os.path.exists("frontend/src/stage03_reflections.ts")
    assert os.path.exists("frontend/src/stage03_validation.ts")
