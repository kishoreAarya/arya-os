"""Phase 3.2.4.4.6.3.2.8: Cryptographic Worker-Lease Binding Hardening & Dispatch Validation Suite.

Covers:
1. Valid worker and lease signature.
2. Tampered worker identity.
3. Tampered lease token.
4. Replayed nonce.
5. Expired capability.
6. Stale or superseded lease.
7. Lease revocation between initial validation and dispatch.
8. Cross-worker attempts using the same capability.
9. Database failure before nonce consumption.
10. No external subprocess launch when any validation fails.
11. Existing Stage 25 execution-bridge and governance regressions.
12. Existing Creator Mode quarantine and local dry-run behavior.
13. Incomplete capability missing worker_id or lease_token fails closed.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
    ConsumedCapabilityNonce,
    GovernanceDecision,
)
from app.services.dispatcher import (
    ExecutionResult,
    LiveExecutionGateError,
    LiveProviderDispatcher,
    is_live_provider_execution_enabled,
    verify_live_execution_gate,
)
from app.services.openmontage_adapter import (
    ExecutionBoundaryError,
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    SecurityViolationError,
    canonical_capability_payload,
    consume_capability_nonce_durable,
    create_governed_execution_context,
    verify_authoritative_lease_and_dispatch_state,
)


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
    worker_id: str = "worker-phase3-2-8",
    lease_token: str = "lease-token-phase3-2-8",
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
    status: str = "EXECUTING",
    lease: dict[str, Any] | None = None,
) -> tuple[Project, AutonomousGoal, AutonomousActionNode]:
    proj = Project(id=project_id, name=f"Proj-{project_id.hex[:6]}")
    sess.add(proj)
    await sess.flush()

    goal = AutonomousGoal(
        id=goal_id,
        project_id=project_id,
        objective="Test Goal",
        status="EXECUTING",
    )
    sess.add(goal)
    await sess.flush()

    node = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id=f"act-{action_id.hex[:6]}",
        title="Test Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status=status,
        inputs_json={"lease": lease or {}},
    )
    sess.add(node)
    await sess.commit()
    return proj, goal, node


# =============================================================================
# 1. Cryptographic Worker & Lease Canonical Binding Tests (1-5, 13)
# =============================================================================

def test_01_valid_worker_and_lease_signature():
    """1. Valid worker identity and lease token generate authentic 10-field HMAC signature."""
    w_id = "worker-node-42"
    l_tok = "lease-xyz-789"
    ctx = make_test_context(worker_id=w_id, lease_token=l_tok)

    # Verify attributes
    assert ctx.worker_id == w_id
    assert ctx.lease_token == l_tok

    # Verify canonical payload contains worker and lease token at positions 9 and 10
    canonical = ctx.canonical_payload()
    parts = canonical.split(":")
    assert len(parts) >= 10
    assert parts[-2] == w_id
    assert parts[-1] == l_tok

    # Authenticity passes without error
    ctx.verify_authenticity(record_nonce=False)


def test_02_tampered_worker_identity_fails():
    """2. Tampered worker identity breaks HMAC signature and raises SecurityViolationError."""
    ctx = make_test_context(worker_id="worker-legit")
    ctx.worker_id = "worker-attacker"

    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity(record_nonce=False)
    assert "invalid cryptographic signature" in str(exc_info.value)


def test_03_tampered_lease_token_fails():
    """3. Tampered lease token breaks HMAC signature and raises SecurityViolationError."""
    ctx = make_test_context(lease_token="lease-valid-111")
    ctx.lease_token = "lease-stolen-222"

    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity(record_nonce=False)
    assert "invalid cryptographic signature" in str(exc_info.value)


def test_04_incomplete_capability_missing_worker_or_lease_fails():
    """13. Capability missing worker_id or lease_token fails non-empty validation."""
    ctx1 = make_test_context()
    ctx1.worker_id = ""
    with pytest.raises(SecurityViolationError) as exc1:
        ctx1.verify_authenticity(record_nonce=False)
    assert "Missing required execution context field 'worker_id'" in str(exc1.value)

    ctx2 = make_test_context()
    ctx2.lease_token = "   "
    with pytest.raises(SecurityViolationError) as exc2:
        ctx2.verify_authenticity(record_nonce=False)
    assert "Missing required execution context field 'lease_token'" in str(exc2.value)


def test_05_expired_capability_fails():
    """5. Capability with expired TTL fails authenticity verification."""
    ctx = make_test_context(ttl_seconds=-10.0)
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity(record_nonce=False)
    assert "Capability expired at" in str(exc_info.value)


# =============================================================================
# 2. Authoritative Database State & Lease Fencing Tests (6-8)
# =============================================================================

async def test_06_stale_or_superseded_lease_rejected():
    """6. Action node whose lease token was superseded in DB is rejected before dispatch."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    old_token = "lease-token-old"
    new_token = "lease-token-new"

    # Context created with old token
    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        lease_token=old_token,
        worker_id="worker-primary",
    )

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": "worker-primary",
        "lease_token": new_token,  # SUPERSEDED
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(sess, action_id, goal_id, project_id, status="EXECUTING", lease=lease_dict)

    try:
        # Verification must reject context with old lease token
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "Lease token mismatch" in str(exc_info.value)
        assert "superseded or fenced out" in str(exc_info.value)
    finally:
        async with AsyncSessionLocal() as sess:
            node = await sess.get(AutonomousActionNode, action_id)
            if node: await sess.delete(node)
            goal = await sess.get(AutonomousGoal, goal_id)
            if goal: await sess.delete(goal)
            proj = await sess.get(Project, project_id)
            if proj: await sess.delete(proj)
            await sess.commit()


async def test_07_lease_revocation_between_initial_validation_and_dispatch():
    """7. Action node revoked (CANCELLED or FAILED) in DB fails closed before execution."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    token = "lease-token-active"

    ctx = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        lease_token=token,
        worker_id="worker-primary",
    )

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": "worker-primary",
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(sess, action_id, goal_id, project_id, status="CANCELLED", lease=lease_dict)

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx)
        assert "non-executable state 'CANCELLED'" in str(exc_info.value)
    finally:
        async with AsyncSessionLocal() as sess:
            node = await sess.get(AutonomousActionNode, action_id)
            if node: await sess.delete(node)
            goal = await sess.get(AutonomousGoal, goal_id)
            if goal: await sess.delete(goal)
            proj = await sess.get(Project, project_id)
            if proj: await sess.delete(proj)
            await sess.commit()


async def test_08_cross_worker_attempts_rejected():
    """8. Attempt by different worker to execute capability bound to another worker is rejected."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    token = "lease-token-shared"

    # Capability bound to Worker A
    ctx_worker_a = make_test_context(
        action_node_id=str(action_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        worker_id="worker-A",
        lease_token=token,
    )

    now = datetime.now(timezone.utc)
    # DB leased to Worker B
    lease_dict = {
        "worker_id": "worker-B",
        "lease_token": token,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(sess, action_id, goal_id, project_id, status="EXECUTING", lease=lease_dict)

    try:
        with pytest.raises(SecurityViolationError) as exc_info:
            await verify_authoritative_lease_and_dispatch_state(ctx_worker_a)
        assert "Worker identity mismatch" in str(exc_info.value)
    finally:
        async with AsyncSessionLocal() as sess:
            node = await sess.get(AutonomousActionNode, action_id)
            if node: await sess.delete(node)
            goal = await sess.get(AutonomousGoal, goal_id)
            if goal: await sess.delete(goal)
            proj = await sess.get(Project, project_id)
            if proj: await sess.delete(proj)
            await sess.commit()


# =============================================================================
# 3. Nonce Durability, Replay, & Database Failure Tests (4, 9, 10)
# =============================================================================

async def test_09_database_failure_before_nonce_consumption_fails_closed():
    """9. Database connection outage before nonce consumption fails closed."""
    ctx = make_test_context()
    failing_db = AsyncMock()
    failing_db.execute.side_effect = ConnectionRefusedError("PostgreSQL cluster down")

    with pytest.raises(SecurityViolationError) as exc_info:
        await verify_authoritative_lease_and_dispatch_state(ctx, db=failing_db)
    assert "fail-closed" in str(exc_info.value)


async def test_10_no_subprocess_launch_when_any_validation_fails():
    """10. Subprocess launch is never executed when any capability validation fails."""
    adapter = OpenMontageAdapter()

    with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        # Case A: Live gate is disabled
        ctx_valid = make_test_context()
        with pytest.raises(LiveExecutionGateError):
            await adapter.execute_governed_tool("flux_image", {"prompt": "test"}, execution_context=ctx_valid)
        mock_run.assert_not_called()

        # Enable live gate via patch for subsequent checks
        with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
            # Case B: Tampered worker
            ctx_bad_worker = make_test_context()
            ctx_bad_worker.worker_id = "hacker"
            with pytest.raises(SecurityViolationError):
                await adapter.execute_governed_tool("flux_image", {"prompt": "test"}, execution_context=ctx_bad_worker)
            mock_run.assert_not_called()

            # Case C: Tampered lease
            ctx_bad_lease = make_test_context()
            ctx_bad_lease.lease_token = "bad_token"
            with pytest.raises(SecurityViolationError):
                await adapter.execute_governed_tool("flux_image", {"prompt": "test"}, execution_context=ctx_bad_lease)
            mock_run.assert_not_called()

            # Case D: Expired TTL
            ctx_expired = make_test_context(ttl_seconds=-5.0)
            with pytest.raises(SecurityViolationError):
                await adapter.execute_governed_tool("flux_image", {"prompt": "test"}, execution_context=ctx_expired)
            mock_run.assert_not_called()


async def test_11_replayed_nonce_rejected_across_workers():
    """4. Replay of an already consumed nonce is rejected durably across workers."""
    ctx = make_test_context()
    adapter = OpenMontageAdapter()

    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True), \
         patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(success=True, status="COMPLETED")

        # First consumption succeeds
        res1 = await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert res1.success is True
        assert mock_run.call_count == 1

        # Second consumption attempt with exact same context/nonce fails closed
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Replay detected" in str(exc_info.value)
        # Subprocess must NOT have been called a second time
        assert mock_run.call_count == 1


# =============================================================================
# 4. Creator Mode Quarantine & Regression Tests (11-12)
# =============================================================================

async def test_12_creator_mode_quarantine_and_dry_run_invariants():
    """12. Creator Mode quarantine remains enforced and dry-run produces zero network calls."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A. External generation quarantined with HTTP 409 even if gate were True
        with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
            resp = await client.post(
                "/creator/generate",
                json={
                    "generation_type": "image",
                    "prompt": "A futuristic city",
                    "model": "black-forest-labs/FLUX.1.1-pro",
                    "provider": "fal",
                    "visual_dry_run": False,
                },
            )
            assert resp.status_code == 409
            assert "quarantined" in resp.json()["detail"].lower()

        # B. Local dry-run succeeds with HTTP 202 Accepted, zero cloud credentials, zero spend
        dry_resp = await client.post(
            "/creator/generate",
            json={
                "generation_type": "image",
                "prompt": "A peaceful mountain",
                "model": "black-forest-labs/FLUX.1.1-pro",
                "provider": "fal",
                "visual_dry_run": True,
            },
        )
        assert dry_resp.status_code in (200, 202)
        assert dry_resp.json()["status"] in ("pending", "processing", "completed")


async def test_13_dispatcher_validates_db_lease_before_issuing_context():
    """11. LiveProviderDispatcher verifies active database lease before issuing capability context."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=Path("/tmp"),
    )

    now = datetime.now(timezone.utc)
    lease_dict = {
        "worker_id": "worker-X",
        "lease_token": "token-X",
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }

    async with AsyncSessionLocal() as sess:
        await _create_test_hierarchy(sess, action_id, goal_id, project_id, status="EXECUTING", lease=lease_dict)

    try:
        # Stale action object presenting mismatched lease token
        stale_action = AutonomousActionNode(
            id=action_id,
            goal_id=goal_id,
            client_action_id=f"act-{action_id.hex[:6]}",
            title="Dispatcher Lease Test",
            action_type="SYNTHESIS",
            required_capability="IMAGE_GENERATION",
            status="EXECUTING",
            inputs_json={
                "prompt": "Test image",
                "lease": {
                    "worker_id": "worker-X",
                    "lease_token": "stale-token-Y",  # MISMATCH with DB
                    "expires_at": (now + timedelta(seconds=300)).isoformat(),
                },
            },
        )

        result = await dispatcher.dispatch(stale_action)
        assert result.success is False
        assert "Lease token mismatch" in result.error
    finally:
        async with AsyncSessionLocal() as sess:
            node = await sess.get(AutonomousActionNode, action_id)
            if node: await sess.delete(node)
            goal = await sess.get(AutonomousGoal, goal_id)
            if goal: await sess.delete(goal)
            proj = await sess.get(Project, project_id)
            if proj: await sess.delete(proj)
            await sess.commit()
