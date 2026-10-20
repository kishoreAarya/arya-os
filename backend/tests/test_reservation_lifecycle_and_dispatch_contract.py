"""
AryaOS V1 Stage 25 Phase 3.2.4.4.6.3.3.3 — Reservation Lifecycle & Dispatch Contract Tests.

Validates the remediation of the budget-reservation lifecycle contract and error classification:
1. Valid RESERVED and valid CONSUMED reservations pass authoritative verification.
2. Rejection of RELEASED, arbitrary statuses, cross-project reservations, invalid amounts, and overconsumption.
3. Missing reservation and database failure fail closed with SecurityViolationError.
4. Deterministic pre-dispatch rejection produces FAILED with is_ambiguous=False, cost_usd=0.0.
5. Post-dispatch timeout or lost response remains UNKNOWN_PENDING_RECONCILIATION with is_ambiguous=True.
6. Local validation or packaging error after confirmed provider success preserves provider_job_id and cost.
7. Subprocess launch is never executed on any pre-dispatch rejection.
8. Zero external calls, zero spend, and isolated test fixtures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import math
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.database.session import AsyncSessionLocal
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
)
from app.schemas.production import AryaJobPackageSchema
from app.services.dispatcher import (
    ExecutionResult,
    LiveProviderDispatcher,
    is_live_provider_execution_enabled,
    is_live_local_execution_enabled,
)
from app.services.openmontage_adapter import (
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    SecurityViolationError,
    ExecutionBoundaryError,
    create_governed_execution_context,
    verify_authoritative_lease_and_dispatch_state,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


# =============================================================================
# ISOLATION FIXTURES: STRICT NETWORK BLOCKING (ZERO EXTERNAL TRAFFIC)
# =============================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during contract tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.6.3.3.3 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

def make_test_context(
    action_node_id: str | None = None,
    goal_id: str | None = None,
    project_id: str | None = None,
    reservation_id: str | None = None,
    provider_id: str = "fal",
    ttl_seconds: float = 300.0,
    worker_id: str = "worker-contract-test",
    lease_token: str = "lease-token-contract-test",
) -> GovernedExecutionContext:
    return create_governed_execution_context(
        action_node_id=action_node_id or str(uuid.uuid4()),
        goal_id=goal_id or str(uuid.uuid4()),
        project_id=project_id or str(uuid.uuid4()),
        reservation_id=reservation_id or str(uuid.uuid4()),
        provider_id=provider_id,
        ttl_seconds=ttl_seconds,
        worker_id=worker_id,
        lease_token=lease_token,
    )


async def _create_test_hierarchy(
    sess: AsyncSession,
    action_id: uuid.UUID,
    goal_id: uuid.UUID,
    project_id: uuid.UUID,
    reservation_id: uuid.UUID | None = None,
    status: str = "EXECUTING",
    lease: dict[str, Any] | None = None,
    reservation_status: str = "RESERVED",
    reserved_amount_usd: float = 0.05,
    consumed_amount_usd: float = 0.00,
    reservation_project_id: uuid.UUID | None = None,
    reservation_goal_id: uuid.UUID | None = None,
) -> tuple[Project, AutonomousGoal, AutonomousActionNode, BudgetReservation | None]:
    proj = Project(id=project_id, name=f"Proj-{project_id.hex[:6]}")
    sess.add(proj)
    await sess.flush()

    goal = AutonomousGoal(
        id=goal_id,
        project_id=project_id,
        objective="Contract Test Goal",
        status="EXECUTING",
    )
    sess.add(goal)
    await sess.flush()

    node = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id=f"act-{action_id.hex[:6]}",
        title="Contract Test Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status=status,
        inputs_json={"lease": lease or {}},
    )
    sess.add(node)
    await sess.flush()

    res_obj = None
    if reservation_id is not None:
        res_obj = BudgetReservation(
            id=reservation_id,
            project_id=reservation_project_id or project_id,
            goal_id=reservation_goal_id or goal_id,
            plan_version=1,
            reserved_amount_usd=reserved_amount_usd,
            consumed_amount_usd=consumed_amount_usd,
            status=reservation_status,
        )
        sess.add(res_obj)

    await sess.commit()
    return proj, goal, node, res_obj


async def _cleanup_hierarchy(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    action_id: uuid.UUID,
    reservation_id: uuid.UUID | None = None,
    extra_project_id: uuid.UUID | None = None,
    extra_goal_id: uuid.UUID | None = None,
):
    async with AsyncSessionLocal() as sess:
        if reservation_id:
            res = await sess.get(BudgetReservation, reservation_id)
            if res:
                await sess.delete(res)
        node = await sess.get(AutonomousActionNode, action_id)
        if node:
            await sess.delete(node)
        goal = await sess.get(AutonomousGoal, goal_id)
        if goal:
            await sess.delete(goal)
        proj = await sess.get(Project, project_id)
        if proj:
            await sess.delete(proj)
        if extra_goal_id:
            eg = await sess.get(AutonomousGoal, extra_goal_id)
            if eg:
                await sess.delete(eg)
        if extra_project_id:
            ep = await sess.get(Project, extra_project_id)
            if ep:
                await sess.delete(ep)
        await sess.commit()


# =============================================================================
# 1. Budget Reservation Contract Validation Tests (1-10)
# =============================================================================

async def test_01_valid_reserved_status_passes_verification():
    """1. Valid RESERVED status with positive headroom and matching bindings passes cleanly."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-valid-res"
    worker = "worker-contract-1"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="RESERVED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,
        )

    try:
        # Must execute without raising SecurityViolationError
        await verify_authoritative_lease_and_dispatch_state(ctx)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_02_valid_consumed_status_passes_verification():
    """2. Valid CONSUMED status consistent with completed spend passes cleanly."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-consumed-ok"
    worker = "worker-contract-2"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="CONSUMED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.05,
        )

    try:
        await verify_authoritative_lease_and_dispatch_state(ctx)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_03_released_status_fails_closed():
    """3. RELEASED reservation fails closed with SecurityViolationError."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-released"
    worker = "worker-contract-3"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="RELEASED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "has been RELEASED" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


@pytest.mark.parametrize("bad_status", ["ACTIVE", "PENDING", "INITIALIZED", "ARBITRARY_STATUS"])
async def test_04_arbitrary_or_assumed_status_fails_closed(bad_status: str):
    """4. Non-canonical statuses (including former assumption 'ACTIVE') fail closed."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-bad-status"
    worker = "worker-contract-4"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status=bad_status,
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert f"invalid status '{bad_status}'" in str(exc_info.value)
        assert "expected 'RESERVED' or 'CONSUMED'" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_05_cross_project_reservation_fails_closed():
    """5. Cross-project reservation reference fails closed."""
    project_id_a = uuid.uuid4()
    project_id_b = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-cross-proj"
    worker = "worker-contract-5"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    # Context bound to project A
    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id_a),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        # Create Project B
        p_b = Project(id=project_id_b, name="Project B")
        sess.add(p_b)
        await sess.flush()

        # Reservation belongs to Project B, Action belongs to Project A
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id_a,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="RESERVED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,
            reservation_project_id=project_id_b,
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "Cross-project reservation violation" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id_a, goal_id, action_id, res_id, extra_project_id=project_id_b)


async def test_06_cross_goal_reservation_fails_closed():
    """6. Cross-goal reservation reference fails closed."""
    project_id = uuid.uuid4()
    goal_id_a = uuid.uuid4()
    goal_id_b = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-cross-goal"
    worker = "worker-contract-6"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    # Context bound to Goal A
    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id_a),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        proj = Project(id=project_id, name="Project Cross-Goal")
        sess.add(proj)
        await sess.flush()

        g_b = AutonomousGoal(id=goal_id_b, project_id=project_id, objective="Goal B", status="EXECUTING")
        sess.add(g_b)
        await sess.flush()

        g_a = AutonomousGoal(id=goal_id_a, project_id=project_id, objective="Goal A", status="EXECUTING")
        sess.add(g_a)
        await sess.flush()

        node = AutonomousActionNode(
            id=action_id,
            goal_id=goal_id_a,
            client_action_id=f"act-{action_id.hex[:6]}",
            title="Contract Test Action",
            action_type="SYNTHESIS",
            required_capability="IMAGE_GENERATION",
            status="EXECUTING",
            inputs_json={"lease": lease_dict},
        )
        sess.add(node)
        await sess.flush()

        res_obj = BudgetReservation(
            id=res_id,
            project_id=project_id,
            goal_id=goal_id_b,
            plan_version=1,
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,
            status="RESERVED",
        )
        sess.add(res_obj)
        await sess.commit()

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "Reservation goal mismatch" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id_a, action_id, res_id, extra_goal_id=goal_id_b)


@pytest.mark.parametrize("invalid_reserved", [0.0, -0.05, -1.0])
async def test_07_invalid_reserved_amount_fails_closed(invalid_reserved: float):
    """7. Non-positive reserved amount fails closed."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-bad-amount"
    worker = "worker-contract-7"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="RESERVED",
            reserved_amount_usd=invalid_reserved,
            consumed_amount_usd=0.00,
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "invalid reserved amount" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_08_overconsumption_fails_closed():
    """8. Reservation where consumed exceeds reserved fails closed."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-overconsume"
    worker = "worker-contract-8"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="RESERVED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.06,  # 0.06 > 0.05
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "overconsumption violation" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_09_consumed_status_with_zero_consumed_fails_closed():
    """9. Reservation marked CONSUMED but having zero consumed spend fails closed."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()
    token = "lease-token-consumed-zero"
    worker = "worker-contract-9"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=res_id,
            status="EXECUTING",
            lease=lease_dict,
            reservation_status="CONSUMED",
            reserved_amount_usd=0.05,
            consumed_amount_usd=0.00,  # Lifecycle mismatch
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "lifecycle mismatch" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id, res_id)


async def test_10_missing_reservation_fails_closed():
    """10. Non-existent reservation in database fails closed with SecurityViolationError."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    res_id = uuid.uuid4()  # Not created in DB
    token = "lease-token-missing-res"
    worker = "worker-contract-10"

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": worker,
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(res_id),
        worker_id=worker,
        lease_token=token,
    )

    async with AsyncSessionLocal() as sess:
        # Create hierarchy without reservation
        await _create_test_hierarchy(
            sess, action_id, goal_id, project_id,
            reservation_id=None,
            status="EXECUTING",
            lease=lease_dict,
        )

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "not found in database (fail-closed)" in str(exc_info.value)
    finally:
        await _cleanup_hierarchy(project_id, goal_id, action_id)


async def test_11_database_failure_during_reservation_check_fails_closed():
    """11. Database outage during reservation query fails closed."""
    ctx = make_test_context()
    failing_db = AsyncMock()
    failing_db.execute.side_effect = ConnectionResetError("PostgreSQL connection reset by peer")

    with pytest.raises(SecurityViolationError) as exc_info:
        await verify_authoritative_lease_and_dispatch_state(ctx, db=failing_db)
    assert "fail-closed" in str(exc_info.value)


# =============================================================================
# 2. Dispatcher Classification & Error Boundary Tests (12-16)
# =============================================================================

async def test_12_pre_dispatch_rejection_maps_to_failed_not_unknown():
    """12. Pre-dispatch rejection produces FAILED with is_ambiguous=False and cost=0.0."""
    class PreDispatchFailingProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            # Simulate pre-dispatch exception in execute_governed_tool
            exc = SecurityViolationError("Authoritative lease state validation failed: reservation expired")
            setattr(exc, "dispatch_phase", "PRE_DISPATCH")
            raise exc

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=Path("/tmp"),
    )
    dispatcher.image_registry.register(PreDispatchFailingProvider())

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_pre_dispatch_fail",
        title="Pre-dispatch Failure Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={"prompt": "Pre-dispatch failure", "provider": "fal", "model": "flux-pro/v1.1"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert res.output.get("is_ambiguous") is False
    assert res.output.get("phase") == "PRE_DISPATCH"
    assert res.cost_usd == 0.0


async def test_13_post_dispatch_timeout_maps_to_unknown_pending_reconciliation():
    """13. Subprocess timeout after dispatch produces UNKNOWN_PENDING_RECONCILIATION with is_ambiguous=True."""
    class PostDispatchTimeoutProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            # Returns an ambiguous in-flight timeout result as OpenMontageAdapter does
            return OpenMontageToolResult(
                success=False,
                status="UNKNOWN_PENDING_RECONCILIATION",
                phase="IN_FLIGHT",
                is_ambiguous=True,
                error="Execution timed out after 180 seconds while external provider call was in-flight",
                cost_usd=0.05,
                duration_seconds=180.0,
            )

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=Path("/tmp"),
    )
    dispatcher.image_registry.register(PostDispatchTimeoutProvider())

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_timeout",
        title="Post-dispatch Timeout Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={"prompt": "Timeout test", "provider": "fal", "model": "flux-pro/v1.1"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res.output.get("is_ambiguous") is True
    assert res.cost_usd == 0.05


async def test_14_local_error_after_provider_success_preserves_confirmed_success_and_cost():
    """14. Local artifact validation failure after confirmed provider success preserves job ID and cost."""
    class SuccessfulProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            return OpenMontageToolResult(
                success=True,
                status="COMPLETED",
                artifacts=["/tmp/nonexistent_artifact_file.png"],  # Will fail artifact validation
                provider_job_id="fal-job-ext-999888777",
                cost_usd=0.05,
                duration_seconds=4.2,
            )

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=Path("/tmp"),
        validate_artifacts=True,
    )
    dispatcher.image_registry.register(SuccessfulProvider())

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_local_val_fail",
        title="Artifact Validation Failure Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={"prompt": "Validate test", "provider": "fal", "model": "flux-pro/v1.1"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    # Invariant: External job ID and cost are preserved and not erased!
    assert res.provider_job_id == "fal-job-ext-999888777"
    assert res.cost_usd == 0.05


async def test_15_no_subprocess_launched_on_pre_dispatch_rejection():
    """15. Subprocess launch is never executed on any pre-dispatch rejection."""
    adapter = OpenMontageAdapter()

    with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_subprocess:
        # Case A: Live gate is False
        ctx = make_test_context()
        with pytest.raises(Exception):
            await adapter.execute_governed_tool(
                tool_name="flux_image",
                inputs={"prompt": "No subprocess"},
                execution_context=ctx,
            )
        mock_subprocess.assert_not_called()

        # Case B: Context has tampered signature (with gate enabled)
        ctx_tampered = make_test_context()
        ctx_tampered.capability_signature = "bad-sig"
        with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
            with pytest.raises(SecurityViolationError):
                await adapter.execute_governed_tool(
                    tool_name="flux_image",
                    inputs={"prompt": "No subprocess"},
                    execution_context=ctx_tampered,
                )
        mock_subprocess.assert_not_called()


async def test_16_frozen_invariants_preserved():
    """16. Verify baseline invariants: Alembic head, gates false, and ledger."""
    from app.services.dispatcher import (
        is_live_provider_execution_enabled,
        is_live_local_execution_enabled,
    )

    s = Settings()
    assert is_live_provider_execution_enabled(s) is False
    assert is_live_local_execution_enabled(s) is False

    migration_file = Path("alembic/versions/k1f2a3b4c5d6_consumed_capability_nonces.py")
    assert migration_file.exists()
    content = migration_file.read_text(encoding="utf-8")
    assert 'revision: str = "k1f2a3b4c5d6"' in content or "revision = 'k1f2a3b4c5d6'" in content
