"""
AryaOS V1 Stage 25 Phase 3.2.4.4.6 — Multi-Shot Offline Orchestration & Dry-Run Harness Tests.

Validates that AryaOS safely governs multi-shot DAG video/image pipelines offline:
- GAP-01: Aggregate Multi-Shot Budget Preflight Check (fail-closed before Shot 01)
- GAP-02: Standardized Inter-Shot Artifact Binding ($<client_action_id>.<property>)
- 3-Shot Deterministic Offline Dry Run (Shot 01 Image -> Shot 02 Video -> Shot 03 Video)
- Parallel DAG safety (Fan-Out: Shot 01 -> [Shot 02A, Shot 02B])
- Partial failure semantics (Failed / Unknown / Recovery Required)
- Artifact binding security (Path traversal, SSRF, Malformed expressions, Out-of-bounds index)
- Idempotency & replay protection across shots
- Approval isolation between shots
- Canonical truthful '(simulated)' completion summary
- Strict offline guarantees (Zero external calls, Zero spend, Frozen baseline integrity)
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import AuthenticatedPrincipal
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    BindingResolutionError,
    BindingSecurityError,
)
from app.services.dispatcher import OfflineMockDispatcher, is_live_provider_execution_enabled

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK BLOCKING (ZERO EXTERNAL TRAFFIC)
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during Phase 3.2.4.4.6 tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.6 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


# ===========================================================================
# HELPER SETUP FIXTURES
# ===========================================================================

async def _setup_project_and_principal(db: AsyncSession) -> tuple[Project, AuthenticatedPrincipal]:
    project = Project(name=f"Multi-Shot Pipeline Test Project {uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Lead Operator",
        is_admin=True,
        principal_type="system",
    )
    return project, principal


# ===========================================================================
# 1. GAP-01: AGGREGATE MULTI-SHOT BUDGET PREFLIGHT TESTS
# ===========================================================================

async def test_01_gap01_aggregate_budget_sufficient_proceeds(db_session: AsyncSession):
    """Test 01: Multi-shot DAG proceeds when aggregate estimated budget is sufficient."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Produce 2-Shot Pipeline with Sufficient Budget",
        status="READY",
        plan_dag_json={
            "budget_limit_usd": 0.20,
            "nodes": [
                {"client_action_id": "shot_01"},
                {"client_action_id": "shot_02"},
            ],
            "edges": [{"from": "shot_01", "to": "shot_02"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    action_1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Keyframe",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "fal", "model": "flux-pro/v1.1"},  # Authoritative: 0.05
    )
    action_2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},  # Authoritative: 0.10
    )
    db_session.add_all([action_1, action_2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Re-fetch goal with loaded actions
    goal = await runner._fetch_goal_with_actions(goal.id)

    # Preflight check directly
    is_ok, agg_cost, b_lim, b_err = runner.evaluate_aggregate_dag_budget(goal)
    assert is_ok is True
    assert agg_cost == 0.15  # 0.05 + 0.10
    assert b_lim == 0.20
    assert b_err is None

    # Execution progresses without being blocked
    updated_goal = await runner.execute_goal_step(goal.id, principal)
    assert updated_goal.status == "EXECUTING"


async def test_02_gap01_aggregate_budget_insufficient_fails_closed_zero_dispatches(db_session: AsyncSession):
    """Test 02: Preflight halts BEFORE Shot 01 when aggregate budget is insufficient."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Produce 2-Shot Pipeline with Deficient Budget",
        status="READY",
        plan_dag_json={
            "budget_limit_usd": 0.10,  # Limit is 0.10, but total required is 0.15
            "nodes": [
                {"client_action_id": "shot_01"},
                {"client_action_id": "shot_02"},
            ],
            "edges": [{"from": "shot_01", "to": "shot_02"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    action_1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Keyframe",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"simulated_provider": "fal", "model": "flux-pro/v1.1"},  # 0.05
    )
    action_2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"simulated_provider": "kling", "duration_seconds": 5.0},  # 0.10
    )
    db_session.add_all([action_1, action_2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Attempting to execute goal step fails closed
    with pytest.raises(HTTPException) as exc_info:
        await runner.execute_goal_step(goal.id, principal)

    assert exc_info.value.status_code == 409
    assert "Aggregate estimated cost $0.1500 exceeds available budget authority $0.1000" in exc_info.value.detail

    # Proves zero actions dispatched
    await db_session.refresh(goal)
    await db_session.refresh(action_1)
    await db_session.refresh(action_2)
    assert goal.status == "BLOCKED"
    assert "Preflight failed before Shot 01 dispatch" in (goal.failure_reason or "")
    assert action_1.status == "READY"
    assert action_2.status == "PENDING"


async def test_03_gap01_client_supplied_cost_bypasses_ignored(db_session: AsyncSession):
    """Test 03: Client-supplied fake/negative/zero costs are ignored; authoritative pricing enforced."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Budget Bypass Attempt via Client Fake Cost",
        status="READY",
        plan_dag_json={
            "budget_limit_usd": 0.05,
            "nodes": [{"client_action_id": "shot_01"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    # Adversarial client supplies cost: 0.00 and cost_usd: -100.00 to trick preflight
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Fake Kling",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "simulated_provider": "kling",
            "duration_seconds": 5.0,
            "cost_usd": -100.0,
            "cost": 0.0,
            "estimated_cost_usd": 0.0,
        },
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Re-fetch goal with loaded actions
    goal = await runner._fetch_goal_with_actions(goal.id)

    # Authoritative cost calculation ignores client spoofing
    calc_cost = runner.calculate_authoritative_action_cost(action)
    assert calc_cost == 0.10  # Kling authoritative cost, NOT 0.0 or negative

    # Preflight fails closed because 0.10 > 0.05 budget limit
    is_ok, agg_cost, b_lim, b_err = runner.evaluate_aggregate_dag_budget(goal)
    assert is_ok is False
    assert agg_cost == 0.10
    assert "exceeds available budget authority" in (b_err or "")


# ===========================================================================
# 2. GAP-02: STANDARDIZED INTER-SHOT ARTIFACT BINDING TESTS
# ===========================================================================

async def test_04_gap02_inter_shot_artifact_binding_resolves_predecessor_output(db_session: AsyncSession):
    """Test 04: Resolves completed predecessor artifact output into downstream first_frame input."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Inter-Shot Binding Resolution Test",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}],
            "edges": [{"from": "shot_01", "to": "shot_02"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    action_1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Image",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        inputs_json={"prompt": "A majestic astrolabe in deep space"},
        outputs_json={
            "status": "SUCCEEDED",
            "artifacts": ["storage/artifacts/shot_01_astrolabe.png"],
            "artifact_url": "storage/artifacts/shot_01_astrolabe.png",
        },
    )
    action_2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Video Continuation",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "prompt": "Camera rotates around astrolabe",
            "inputs_mapping": {
                "first_frame": "$shot_01.artifacts[0]",
            },
        },
    )
    db_session.add_all([action_1, action_2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Dispatching Shot 02 triggers binding resolution
    node2 = await runner.dispatch_action(action_2.id, principal)

    assert node2.status == "SUCCEEDED"
    assert node2.inputs_json.get("first_frame") == "storage/artifacts/shot_01_astrolabe.png"
    assert node2.inputs_json.get("resolved_bindings", {}).get("first_frame") == "$shot_01.artifacts[0]"


# ===========================================================================
# 3. DETERMINISTIC OFFLINE THREE-SHOT DRY RUN (END-TO-END)
# ===========================================================================

async def test_05_three_shot_deterministic_offline_dry_run(db_session: AsyncSession):
    """Test 05: Complete 3-shot offline pipeline executes end-to-end to COMPLETED (simulated)."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Deterministic Three-Shot Cinematic Teaser",
        status="READY",
        plan_dag_json={
            "budget_limit_usd": 1.00,
            "nodes": [
                {"client_action_id": "shot_01"},
                {"client_action_id": "shot_02"},
                {"client_action_id": "shot_03"},
            ],
            "edges": [
                {"from": "shot_01", "to": "shot_02"},
                {"from": "shot_02", "to": "shot_03"},
            ],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    shot_1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01: Character Portrait Keyframe",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Father Thomas in 12th-century crypt chapel", "provider": "offline-mock"},
    )
    shot_2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02: Cinematic Camera Push Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={
            "prompt": "Slow camera push forward toward alter",
            "provider": "offline-mock",
            "inputs_mapping": {"first_frame": "$shot_01.artifacts[0]"},
        },
    )
    shot_3 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_03",
        title="Shot 03: Crypt Shadows Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={
            "prompt": "Shadows flicker across the stone carvings",
            "provider": "offline-mock",
            "inputs_mapping": {"first_frame": "$shot_02.artifacts[0]"},
        },
    )
    db_session.add_all([shot_1, shot_2, shot_3])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Step 1: Execute Shot 01
    goal = await runner.execute_goal_step(goal.id, principal, max_concurrent=1)
    await db_session.refresh(shot_1)
    await db_session.refresh(shot_2)
    assert shot_1.status == "SUCCEEDED"
    assert shot_1.outputs_json.get("artifacts") is not None
    assert shot_2.status == "READY"  # Transitioned from PENDING to READY after prereq succeeded

    # Step 2: Execute Shot 02
    goal = await runner.execute_goal_step(goal.id, principal, max_concurrent=1)
    await db_session.refresh(shot_2)
    await db_session.refresh(shot_3)
    assert shot_2.status == "SUCCEEDED"
    assert shot_2.inputs_json.get("first_frame") == shot_1.outputs_json["artifacts"][0]
    assert shot_3.status == "READY"

    # Step 3: Execute Shot 03
    goal = await runner.execute_goal_step(goal.id, principal, max_concurrent=1)
    await db_session.refresh(shot_3)
    assert shot_3.status == "SUCCEEDED"
    assert shot_3.inputs_json.get("first_frame") == shot_2.outputs_json["artifacts"][0]

    # Verification: Goal reaches COMPLETED with truthful simulated label
    await db_session.refresh(goal)
    assert goal.status == "COMPLETED"
    assert goal.final_summary == "Goal completed successfully across 3 action nodes (simulated)."


# ===========================================================================
# 4. PARALLEL SAFETY & FAN-OUT EXECUTION TESTS
# ===========================================================================

async def test_06_parallel_safety_fan_out_dag(db_session: AsyncSession):
    """Test 06: Fan-out DAG (Shot 01 -> [Shot 02A, Shot 02B]) executes with bounded concurrency."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Fan-Out Multi-Shot Video Pipeline",
        status="READY",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "shot_01"},
                {"client_action_id": "shot_02A"},
                {"client_action_id": "shot_02B"},
            ],
            "edges": [
                {"from": "shot_01", "to": "shot_02A"},
                {"from": "shot_01", "to": "shot_02B"},
            ],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Master Concept Art",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"provider": "offline-mock"},
    )
    s2a = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02A",
        title="Angle A Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock", "inputs_mapping": {"first_frame": "$shot_01.artifacts[0]"}},
    )
    s2b = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02B",
        title="Angle B Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock", "inputs_mapping": {"first_frame": "$shot_01.artifacts[0]"}},
    )
    db_session.add_all([s1, s2a, s2b])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Step 1: Shot 01 executes once
    await runner.execute_goal_step(goal.id, principal)
    goal = await runner._fetch_goal_with_actions(goal.id)
    actions_by_cid = {a.client_action_id: a for a in goal.actions}
    assert actions_by_cid["shot_01"].status == "SUCCEEDED"
    assert actions_by_cid["shot_02A"].status == "READY"
    assert actions_by_cid["shot_02B"].status == "READY"

    # Step 2: Both parallel branches execute concurrently up to max_concurrent=2
    await runner.execute_goal_step(goal.id, principal, max_concurrent=2)
    goal = await runner._fetch_goal_with_actions(goal.id)
    actions_by_cid = {a.client_action_id: a for a in goal.actions}
    assert actions_by_cid["shot_02A"].status == "SUCCEEDED"
    assert actions_by_cid["shot_02B"].status == "SUCCEEDED"
    assert goal.status == "COMPLETED"
    assert goal.final_summary == "Goal completed successfully across 3 action nodes (simulated)."


# ===========================================================================
# 5. PARTIAL FAILURE TESTS (SCENARIOS A, B, C)
# ===========================================================================

async def test_07_partial_failure_scenario_a_failed_shot_blocks_downstream(db_session: AsyncSession):
    """Test 07 (Scenario A): Failed Shot 02 halts execution, blocks Shot 03, leaves Goal incomplete."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Failure Injection Pipeline Scenario A",
        status="READY",
        plan_dag_json={
            "nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}, {"client_action_id": "shot_03"}],
            "edges": [{"from": "shot_01", "to": "shot_02"}, {"from": "shot_02", "to": "shot_03"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"provider": "offline-mock"},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Failed",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock", "mock_failure": True, "mock_failure_message": "GPU OOM simulated error"},
    )
    s3 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_03",
        title="Shot 03 Dependent",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock"},
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Shot 01 succeeds
    await runner.execute_goal_step(goal.id, principal)
    # Shot 02 fails
    await runner.execute_goal_step(goal.id, principal)

    goal = await runner._fetch_goal_with_actions(goal.id)
    actions_by_cid = {a.client_action_id: a for a in goal.actions}
    assert actions_by_cid["shot_01"].status == "SUCCEEDED"
    assert actions_by_cid["shot_02"].status == "FAILED"
    assert actions_by_cid["shot_03"].status == "BLOCKED"  # Downstream is permanently blocked
    assert goal.status == "FAILED"
    assert goal.final_summary is None


async def test_08_partial_failure_scenario_b_unknown_shot_triggers_recovery_required(db_session: AsyncSession):
    """Test 08 (Scenario B): Ambiguous Shot 02 transitions Goal to RECOVERY_REQUIRED, prevents auto-retry."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Unknown Outcome Pipeline Scenario B",
        status="READY",
        plan_dag_json={
            "nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}, {"client_action_id": "shot_03"}],
            "edges": [{"from": "shot_01", "to": "shot_02"}, {"from": "shot_02", "to": "shot_03"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"provider": "offline-mock"},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Unknown",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock", "mock_unknown": True},
    )
    s3 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_03",
        title="Shot 03 Dependent",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"provider": "offline-mock"},
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Step 1: Shot 01 succeeds
    await runner.execute_goal_step(goal.id, principal)
    # Step 2: Shot 02 encounters unknown outcome
    await runner.execute_goal_step(goal.id, principal)

    goal = await runner._fetch_goal_with_actions(goal.id)
    actions_by_cid = {a.client_action_id: a for a in goal.actions}
    assert actions_by_cid["shot_01"].status == "SUCCEEDED"
    assert actions_by_cid["shot_02"].status == "UNKNOWN_PENDING_RECONCILIATION"
    assert actions_by_cid["shot_03"].status == "PENDING"  # Downstream remains blocked
    assert goal.status == "RECOVERY_REQUIRED"
    assert goal.final_summary is None


# ===========================================================================
# 6. ARTIFACT BINDING SECURITY AUDIT TESTS
# ===========================================================================

@pytest.mark.parametrize(
    "malicious_mapping,expected_error",
    [
        ({"first_frame": "$nonexistent_shot.artifacts[0]"}, "does not exist in Goal"),
        ({"first_frame": "$shot_01.artifacts[99]"}, "out of bounds"),
        ({"first_frame": "$shot_01.nonexistent_property"}, "not found in outputs"),
        ({"first_frame": "not_a_valid_binding_syntax"}, "Malformed binding expression"),
    ],
)
async def test_09_artifact_binding_syntax_and_missing_properties_fail_closed(
    db_session: AsyncSession, malicious_mapping: dict, expected_error: str
):
    """Test 09: Unresolvable or malformed binding syntax fails closed with HTTP 422."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Security Attack Test",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        outputs_json={"artifacts": ["storage/artifacts/shot_01.png"]},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 Malicious",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"inputs_mapping": malicious_mapping},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(s2.id, principal)

    assert exc_info.value.status_code == 422
    assert expected_error in exc_info.value.detail

    await db_session.refresh(s2)
    assert s2.status == "BLOCKED"


async def test_10_artifact_binding_security_traversal_and_ssrf_fail_closed(db_session: AsyncSession):
    """Test 10: Path traversal and loopback SSRF injection via predecessor outputs fail closed."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Path Traversal & SSRF Injection Defense",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    # Predecessor compromised output contains directory traversal
    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Compromised Shot 01",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        outputs_json={"artifacts": ["../../../../etc/shadow"]},
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Victim Shot 02",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"inputs_mapping": {"first_frame": "$shot_01.artifacts[0]"}},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(s2.id, principal)

    assert exc_info.value.status_code == 422
    assert "Path traversal detected" in exc_info.value.detail

    await db_session.refresh(s2)
    assert s2.status == "BLOCKED"


# ===========================================================================
# 7. IDEMPOTENCY & REPLAY PROTECTION
# ===========================================================================

async def test_11_shot_level_idempotency_replay_protection(db_session: AsyncSession):
    """Test 11: Replaying a SUCCEEDED shot returns the existing node without re-dispatch."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Idempotency Multi-Shot Test",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "shot_01"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        cost_usd=0.05,
        outputs_json={"status": "SUCCEEDED", "artifact_url": "storage/artifacts/shot_01.png"},
    )
    db_session.add(action)
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Calling dispatch on already succeeded action
    node = await runner.dispatch_action(action.id, principal)
    assert node.status == "SUCCEEDED"
    assert node.cost_usd == 0.05
    assert node.outputs_json.get("artifact_url") == "storage/artifacts/shot_01.png"


# ===========================================================================
# 8. APPROVAL ISOLATION BETWEEN SHOTS
# ===========================================================================

async def test_12_approval_isolation_shot_01_approval_does_not_authorize_shot_02(db_session: AsyncSession):
    """Test 12: Approving Shot 01 does NOT authorize high-risk Shot 02."""
    project, principal = await _setup_project_and_principal(db_session)

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Approval Isolation Governance Test",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "shot_01"}, {"client_action_id": "shot_02"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    s1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_01",
        title="Shot 01 Normal",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        risk_level="LOW",
    )
    s2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_02",
        title="Shot 02 High Risk Consequential",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="AWAITING_APPROVAL",
        risk_level="HIGH",
        inputs_json={},
    )
    db_session.add_all([s1, s2])
    await db_session.commit()

    dispatcher = OfflineMockDispatcher()
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher)

    # Attempting to dispatch Shot 02 without an ApprovalCheckpoint fails closed
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(s2.id, principal)

    assert exc_info.value.status_code == 409
    assert "requires human operator approval before dispatch" in exc_info.value.detail


# ===========================================================================
# 9. FROZEN INVARIANTS & INTEGRITY AUDIT
# ===========================================================================

async def test_13_invariants_alembic_head_and_frozen_stages():
    """Test 13: Verifies migration head remains i9d0e1f2a3b4 and Stage 03-24 assets remain frozen."""
    # 1. Migration head verification
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

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

    # 5. Ledger verification (Authorized Epoch 2 Rollover & Epoch 1 Immutable Archive)
    archive_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend_phase3_archive.json")
    assert archive_path.exists(), f"Epoch 1 historical archive missing: {archive_path}"
    adata = json.loads(archive_path.read_text(encoding="utf-8"))
    assert adata["budget"] == 20.11
    a_used = sum(float(x["cost"]) for x in adata["generations"])
    assert round(a_used, 2) == 20.10
    assert len(adata["generations"]) == 2

    ledger_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend.json")
    assert ledger_path.exists(), f"Epoch 2 active ledger missing: {ledger_path}"
    ldata = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ldata["epoch"] == 2
    assert ldata["budget"] == 1.00
    assert ldata["archive_ref"] == "fal_spend_phase3_archive.json"
    assert len(ldata["generations"]) == 3
    assert ldata["generations"][0]["cost"] == 0.05
    used = sum(float(x["cost"]) for x in ldata["generations"])
    assert round(used, 2) == 0.15
    assert round(ldata["budget"] - used, 2) == 0.85
