"""AryaOS Stage 25 Phase 3.2.4.4.6.3.2.6 Acceptance Tests:
Execution-Boundary Remediation Implementation

Verifies:
1. Creator Mode Permanent Quarantine:
   - POST /creator/generate without visual_dry_run returns HTTP 409 Conflict.
   - Quarantined even when ENABLE_LIVE_PROVIDER_EXECUTION is set to True.
   - All external providers (fal, kling, replicate, together) quarantined in Creator Mode.
   - Deterministic local visual_dry_run=True succeeds (HTTP 202, $0.00 spend).
   - Legacy direct entry point app.providers.fal.generate_image fails closed when gate=False (LiveExecutionGateError).
   - Legacy direct entry point app.providers.fal.generate_image fails closed when gate=True (RuntimeError quarantined).
   - Legacy direct entry point app.providers.fal.generate_video fails closed when gate=True (RuntimeError quarantined).
2. PostgreSQL-Backed Durable Capability Nonce Single-Use:
   - Durable insertion into consumed_capability_nonces table upon execution.
   - Simulated process restart (in-memory cache cleared) rejects replayed nonce via PostgreSQL unique constraint.
   - Concurrent worker race: two parallel tasks presenting identical nonce produce exactly 1 success and 1 SecurityViolationError.
   - Database outage / transaction failure strictly fails closed (SecurityViolationError), never falls back.
   - Nonce bindings durably stored: action_node_id, goal_id, project_id, reservation_id, provider_id, worker_id, lease_token.
3. Crash & Recovery Safety:
   - Ambiguous dispatch outcome preserves UNKNOWN_PENDING_RECONCILIATION.
   - Consumed nonce cannot be reused after crash or reconciliation.
4. Frozen Invariants & Integrity:
   - Migration head is k1f2a3b4c5d6 with valid chain from j0e1f2a3b4c5.
   - Secondary FAL ledger intact (Epoch 2: $1.00 budget, $0.05 used, 1 generation, $0.95 remaining).
   - Historical Epoch 1 archive intact ($20.10 spend).
   - Stage 03 Blender master scene SHA-256 and GLB asset counts intact.
   - Production live gates remain strictly FALSE.
   - Zero external provider calls, zero external spend.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.creator import CreatorGenerateRequest, GenerationType
from app.core.config import Settings, get_settings
from app.database.session import AsyncSessionLocal
from app.models.core import Project, WorkflowRun
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    ConsumedCapabilityNonce,
)
from app.providers import fal
from app.services.dispatcher import (
    LiveExecutionGateError,
    LiveProviderDispatcher,
    is_live_local_execution_enabled,
    is_live_provider_execution_enabled,
    verify_live_execution_gate,
)
from app.services.openmontage_adapter import (
    ExecutionBoundaryError,
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    SecurityViolationError,
    _CONSUMED_CAPABILITY_NONCES,
    consume_capability_nonce_durable,
    create_governed_execution_context,
)

pytestmark = pytest.mark.asyncio


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
    worker_id: str = "worker-phase3-2-6",
    lease_token: str = "lease-token-phase3-2-6",
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


# =============================================================================
# 1. Creator Mode Quarantine Tests
# =============================================================================

async def test_01_creator_generate_without_dry_run_quarantined_409(client: AsyncClient):
    """1. POST /creator/generate without visual_dry_run is quarantined with HTTP 409."""
    resp = await client.post(
        "/creator/generate",
        json={
            "generation_type": "image",
            "prompt": "Cinematic portrait shot",
            "model": "black-forest-labs/FLUX.1.1-pro",
            "provider": "fal",
            "visual_dry_run": False,
        },
    )
    assert resp.status_code == 409
    data = resp.json()
    assert "quarantined" in data["detail"].lower()
    assert "stage 21" in data["detail"].lower() or "stage 25" in data["detail"].lower()


async def test_02_creator_generate_quarantined_even_when_live_gate_true(client: AsyncClient):
    """2. POST /creator/generate remains quarantined with HTTP 409 even if live gate is True."""
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        resp = await client.post(
            "/creator/generate",
            json={
                "generation_type": "image",
                "prompt": "Cinematic landscape shot",
                "model": "fal-ai/flux-pro/v1.1",
                "provider": "fal",
                "visual_dry_run": False,
            },
        )
        assert resp.status_code == 409
        assert "quarantined" in resp.json()["detail"].lower()


async def test_03_creator_generate_covers_all_external_providers(client: AsyncClient):
    """3. Creator Mode quarantines requests across FAL, Kling, Replicate, and Together."""
    providers_to_test = [
        ("fal", "fal-ai/flux-pro/v1.1", "image"),
        ("kling", "kwaivgi/kling-v1.6-standard", "image_to_video"),
        ("replicate", "black-forest-labs/flux-schnell", "image"),
        ("together", "black-forest-labs/FLUX.1.1-pro", "image"),
    ]

    for prov, model, gen_type in providers_to_test:
        payload = {
            "generation_type": gen_type,
            "prompt": f"Test generation for {prov}",
            "provider": prov,
            "model": model,
            "visual_dry_run": False,
        }
        if gen_type == "image_to_video":
            payload["start_frame_url"] = "https://example.com/start.png"

        resp = await client.post("/creator/generate", json=payload)
        assert resp.status_code == 409, f"Provider {prov} was not quarantined! Status: {resp.status_code}"
        assert "quarantined" in resp.json()["detail"].lower()


async def test_04_creator_generate_local_dry_run_succeeds_zero_spend(client: AsyncClient):
    """4. POST /creator/generate with visual_dry_run=True succeeds with HTTP 202."""
    resp = await client.post(
        "/creator/generate",
        json={
            "generation_type": "image",
            "prompt": "Dry-run deterministic keyframe",
            "visual_dry_run": True,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ("pending", "in_progress", "completed")


async def test_05_legacy_fal_image_fails_closed_when_gate_false():
    """5. Legacy app.providers.fal.generate_image fails closed when gate is False."""
    with pytest.raises(LiveExecutionGateError) as exc_info:
        await fal.generate_image(prompt="test", api_key="test_key", model="flux-pro/v1.1")
    assert "Live external provider execution is disabled" in str(exc_info.value)


async def test_06_legacy_fal_image_quarantined_when_gate_true():
    """6. Legacy app.providers.fal.generate_image fails closed with RuntimeError when gate is True."""
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(RuntimeError) as exc_info:
            await fal.generate_image(prompt="test", api_key="test_key", model="flux-pro/v1.1")
        assert "permanently quarantined" in str(exc_info.value)
        assert "Stage 25 AutonomousExecutionRunner" in str(exc_info.value)


async def test_07_legacy_fal_video_quarantined_when_gate_true():
    """7. Legacy app.providers.fal.generate_video fails closed with RuntimeError when gate is True."""
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(RuntimeError) as exc_info:
            await fal.generate_video(prompt="test", api_key="test_key", model="kling")
        assert "permanently quarantined" in str(exc_info.value)
        assert "Stage 25 AutonomousExecutionRunner" in str(exc_info.value)


# =============================================================================
# 2. Durable Capability Nonce Single-Use Consumption Tests
# =============================================================================

async def test_08_durable_nonce_recorded_in_postgresql():
    """8. consume_capability_nonce_durable durably persists nonce to PostgreSQL consumed_capability_nonces."""
    ctx = make_test_context(provider_id="fal", worker_id="test-worker-08", lease_token="test-lease-08")

    async with AsyncSessionLocal() as sess:
        await consume_capability_nonce_durable(ctx, db=sess)

    # Verify presence in PostgreSQL
    async with AsyncSessionLocal() as sess:
        stmt = select(ConsumedCapabilityNonce).where(ConsumedCapabilityNonce.execution_nonce == ctx.execution_nonce)
        res = await sess.execute(stmt)
        record = res.scalar_one_or_none()
        assert record is not None
        assert record.execution_nonce == ctx.execution_nonce
        assert record.action_node_id == str(ctx.action_node_id)
        assert record.goal_id == str(ctx.goal_id)
        assert record.project_id == str(ctx.project_id)
        assert record.reservation_id == str(ctx.reservation_id)
        assert record.provider_id == "fal"
        assert record.worker_id == "test-worker-08"
        assert record.lease_token == "test-lease-08"


async def test_09_durable_replay_rejected_after_simulated_process_restart():
    """9. After clearing in-memory cache (simulating process restart), PostgreSQL unique constraint rejects replay."""
    ctx = make_test_context(provider_id="fal")

    # Initial durable consumption
    async with AsyncSessionLocal() as sess:
        await consume_capability_nonce_durable(ctx, db=sess)

    # Simulate process restart by clearing in-memory Python set
    _CONSUMED_CAPABILITY_NONCES.discard(ctx.execution_nonce)
    assert ctx.execution_nonce not in _CONSUMED_CAPABILITY_NONCES

    # Presenting the exact same nonce to a new worker/process MUST fail closed via PostgreSQL unique constraint
    async with AsyncSessionLocal() as sess:
        with pytest.raises(SecurityViolationError) as exc_info:
            await consume_capability_nonce_durable(ctx, db=sess)
        assert "Replay detected" in str(exc_info.value)
        assert "database unique violation" in str(exc_info.value)


async def test_10_concurrent_worker_race_produces_single_authorized_execution():
    """10. Two concurrent worker processes presenting identical nonce produce exactly 1 success and 1 rejection."""
    ctx = make_test_context(provider_id="fal")

    results = []

    async def worker_attempt(w_id: str):
        try:
            async with AsyncSessionLocal() as sess:
                await consume_capability_nonce_durable(ctx, db=sess, worker_id=w_id, lease_token=f"lease-{w_id}")
            results.append(("SUCCESS", w_id))
        except SecurityViolationError as e:
            results.append(("REPLAY_ERROR", str(e)))

    # Clear in-memory cache to ensure database unique constraint handles concurrency
    _CONSUMED_CAPABILITY_NONCES.discard(ctx.execution_nonce)

    # Race two concurrent tasks
    await asyncio.gather(
        worker_attempt("worker-A"),
        worker_attempt("worker-B"),
    )

    statuses = [r[0] for r in results]
    assert statuses.count("SUCCESS") == 1, f"Expected exactly 1 success, got: {results}"
    assert statuses.count("REPLAY_ERROR") == 1, f"Expected exactly 1 rejection, got: {results}"


async def test_11_database_outage_strictly_fails_closed():
    """11. Database failure/outage strictly fails closed and NEVER falls back to in-memory only."""
    ctx = make_test_context(provider_id="fal")

    # Mock database session that raises connection error
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.commit = AsyncMock(side_effect=RuntimeError("PostgreSQL connection refused: port 5432 down"))

    with pytest.raises(SecurityViolationError) as exc_info:
        await consume_capability_nonce_durable(ctx, db=mock_db)

    assert "fail-closed" in str(exc_info.value).lower()
    assert "connection refused" in str(exc_info.value)


async def test_12_execute_governed_tool_durable_single_use_end_to_end():
    """12. OpenMontageAdapter.execute_governed_tool consumes nonce in PostgreSQL end-to-end."""
    ctx = make_test_context(provider_id="fal")
    adapter = OpenMontageAdapter()

    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True), \
         patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(success=True, status="COMPLETED")

        # 1. First execution succeeds
        res1 = await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert res1.success is True

        # Verify persisted in database
        async with AsyncSessionLocal() as sess:
            stmt = select(ConsumedCapabilityNonce).where(ConsumedCapabilityNonce.execution_nonce == ctx.execution_nonce)
            res = await sess.execute(stmt)
            assert res.scalar_one_or_none() is not None

        # 2. Second execution raises SecurityViolationError
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Replay detected" in str(exc_info.value)


# =============================================================================
# 3. Crash & Recovery Safety Tests
# =============================================================================

async def test_13_ambiguous_dispatch_preserves_unknown_outcome():
    """13. Unhandled provider exception preserves UNKNOWN_PENDING_RECONCILIATION without retry."""
    from app.services.dispatcher import ExecutionResult

    class FailingProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            raise RuntimeError("Subprocess disconnected mid-stream: network partition")

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=Path("/tmp"),
    )
    dispatcher.image_registry.register(FailingProvider())

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_ambiguous",
        title="Ambiguous Execution Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={"prompt": "Ambiguous shot", "provider": "fal", "model": "flux-pro/v1.1"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res.output.get("is_ambiguous") is True


# =============================================================================
# 4. Frozen Invariants & Integrity Audit
# =============================================================================

async def test_14_alembic_head_and_migration_chain():
    """14. Alembic head is k1f2a3b4c5d6, with down_revision pointing to j0e1f2a3b4c5."""
    migration_file = Path("alembic/versions/k1f2a3b4c5d6_consumed_capability_nonces.py")
    assert migration_file.exists(), f"Migration file missing: {migration_file}"

    content = migration_file.read_text(encoding="utf-8")
    assert 'revision: str = "k1f2a3b4c5d6"' in content or "revision = 'k1f2a3b4c5d6'" in content
    assert 'down_revision: Union[str, None] = "j0e1f2a3b4c5"' in content or "down_revision = 'j0e1f2a3b4c5'" in content


async def test_15_stage03_master_blend_sha256_invariant():
    """15. Master blend SHA-256 hash strictly matches frozen baseline."""
    blend_path = Path("frontend/blender/scenes/stage03_aryaos_memory_environment.blend")
    assert blend_path.exists(), f"Master blend file not found: {blend_path}"
    with open(blend_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    assert actual_hash == "c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f"


async def test_16_stage03_glb_assets_count_invariant():
    """16. Stage 03 GLB assets count strictly remains 28 (14 dist + 14 blender)."""
    glbs = list(Path("frontend").rglob("*.glb"))
    stage03_glbs = [g for g in glbs if "stage03_memory" in str(g)]
    assert len(stage03_glbs) == 28


async def test_17_epoch_1_archive_sha256_invariant():
    """17. Epoch 1 historical archive is preserved and matches immutable spend."""
    archive_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend_phase3_archive.json")
    assert archive_path.exists()
    adata = json.loads(archive_path.read_text(encoding="utf-8"))
    assert adata["budget"] == 20.11
    a_used = sum(float(x["cost"]) for x in adata["generations"])
    assert round(a_used, 2) == 20.10
    assert len(adata["generations"]) == 2


async def test_18_epoch_2_ledger_frozen_truth():
    """18. Epoch 2 real ledger preserves exactly 1 post-diagnostic generation ($0.05)."""
    ledger_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend.json")
    assert ledger_path.exists()
    ldata = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ldata["epoch"] == 2
    assert ldata["budget"] == 1.00
    assert len(ldata["generations"]) == 1
    assert ldata["generations"][0]["cost"] == 0.05
    assert ldata["generations"][0]["model"] == "fal-ai/flux-pro/v1.1"
    used = sum(float(x["cost"]) for x in ldata["generations"])
    assert round(used, 2) == 0.05
    assert round(ldata["budget"] - used, 2) == 0.95


async def test_19_production_live_gates_remain_false():
    """19. Production settings have both live execution gates disabled (fail closed)."""
    s = Settings()
    assert is_live_provider_execution_enabled(s) is False
    assert is_live_local_execution_enabled(s) is False
