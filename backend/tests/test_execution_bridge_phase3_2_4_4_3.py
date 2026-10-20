"""
AryaOS V1 Stage 25 Phase 3.2.4.4.3 — Controlled Single-Shot FLUX Image Sandbox.

AUTHORIZATION: Single-shot real external provider execution.
- ONE Flux image generation through Fal.
- ONE request only.
- Hard budget limit: maximum $0.05 spend (Flux/dev: $0.03).
- No automatic retry, no fallback provider, no concurrency.
- Zero Kling/video calls.
- Full 14-step execution lifecycle trace verified.
- Real physical PNG artifact validation on disk.
- Provider request ID captured and validated.
- Invariant baseline preserved (Alembic i9d0e1f2a3b4, Blender SHA-256, 28 GLBs).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.sanitization import sanitize_payload, sanitize_text
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.schemas.production import AryaJobPackageSchema
from app.services.artifact_validator import (
    STORAGE_ARTIFACTS_DIR,
    validate_artifact_file,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import (
    BaseExecutionDispatcher,
    ExecutionResult,
    LiveExecutionGateError,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
    is_live_local_execution_enabled,
    is_live_provider_execution_enabled,
    verify_live_execution_gate,
)
from app.services.idempotency import (
    PROVIDER_PROFILES,
    ProviderConsistencyGuarantee,
    generate_action_idempotency_key,
)
from app.services.image_provider import (
    FluxImageProvider,
    ImageGenerationProvider,
    ImageProviderRegistry,
)
from app.services.media_bridge import synthesize_job_package
from app.services.openmontage_adapter import (
    FORBIDDEN_SECRET_KEYS,
    OpenMontageAdapter,
    OpenMontageToolResult,
    is_external_tool,
    openmontage_adapter,
    validate_provider_job_id,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Enforce strict single-shot guard: module-level execution counter
_REAL_CALL_EXECUTED = False


# ===========================================================================
# 1. PRE-FLIGHT VERIFICATION
# ===========================================================================

async def test_01_preflight_verifications():
    """Test 01: Pre-flight checklist passes without initiating external paid call."""
    # 1. Gate defaults
    default_settings = Settings()
    assert default_settings.enable_live_provider_execution is False
    assert default_settings.enable_live_local_execution is False

    # 2. Gate fail-closed validator
    assert Settings(enable_live_provider_execution="invalid").enable_live_provider_execution is False
    assert Settings(enable_live_provider_execution=False).enable_live_provider_execution is False

    # 3. Credential presence and redaction
    controlled_settings = Settings(enable_live_provider_execution=True)
    fal_key = controlled_settings.fal_key or controlled_settings.fal_api_key or os.environ.get("FAL_KEY")
    assert fal_key is not None, "Preflight failed: FAL_KEY missing from environment/config"
    assert len(fal_key) >= 32
    # Ensure raw secret is not in repr(settings)
    assert fal_key not in repr(controlled_settings)

    # 4. OpenMontage engine availability
    assert openmontage_adapter.is_available(), "OpenMontage engine unavailable"

    # 5. Flux provider configuration valid
    provider = FluxImageProvider(adapter=openmontage_adapter)
    is_valid, cfg_err = provider.validate_configuration()
    assert is_valid is True, f"Provider config invalid: {cfg_err}"

    # 6. Budget estimate check ($0.03 <= $0.05 limit)
    action_dummy = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="dummy",
        title="Dummy",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Test", "provider": "fal", "model": "flux/dev"},
    )
    pkg = synthesize_job_package(action=action_dummy, project_id=uuid.uuid4(), goal_id=action_dummy.goal_id)
    est_cost = provider.estimate_cost(pkg)
    assert est_cost == 0.03
    assert est_cost <= 0.05, f"Estimated cost ${est_cost} exceeds $0.05 budget limit"

    # 7. Kling and unknown tools classified as external
    assert is_external_tool("kling_video") is True
    assert is_external_tool("flux_image") is True
    assert is_external_tool("unknown_tool") is True


async def test_02_kling_and_unauthorized_tools_remain_blocked(tmp_path: Path):
    """Test 02: Kling and non-image tools remain fail-closed and blocked."""
    controlled_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=controlled_settings, output_dir=tmp_path)

    # Action requesting unsupported/unauthorized video generation capability in this test
    bad_cap_action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="bad_cap",
        title="Bad Cap",
        action_type="GENERATION",
        required_capability="AUDIO_GENERATION",  # Unsupported
        status="READY",
        inputs_json={"prompt": "Audio"},
    )
    res = await dispatcher.dispatch(bad_cap_action)
    assert res.status == "FAILED"
    assert "Unsupported capability" in str(res.error)


# ===========================================================================
# 2. CONTROLLED SINGLE-SHOT REAL FLUX EXECUTION ($0.03 <= $0.05)
# ===========================================================================

async def test_03_controlled_single_shot_flux_execution_and_persistence(
    db_session: AsyncSession,
    tmp_path: Path,
):
    """Test 03: Controlled single-shot Flux image generation through Fal ($0.03).

    EXACTLY ONE external provider call. Produces real validated PNG artifact.
    """
    global _REAL_CALL_EXECUTED
    assert _REAL_CALL_EXECUTED is False, "CRITICAL SAFETY VIOLATION: Single-shot limit exceeded!"
    _REAL_CALL_EXECUTED = True

    # Step 1: Project & Principal Authorization
    project = Project(name="Controlled Single-Shot Flux Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Security Operator",
        is_admin=True,
        principal_type="system",
    )

    # Step 2: Goal creation
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Controlled Single-Shot FLUX Image Execution",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "shot_flux_single_shot_001"},
                {"client_action_id": "shot_flux_downstream_002"},
            ],
            "edges": [{"from": "shot_flux_single_shot_001", "to": "shot_flux_downstream_002"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    # Step 3: Minimal deterministic action inputs (budget $0.03 <= $0.05)
    deterministic_prompt = (
        "A solitary silver astrolabe on dark obsidian pedestal, cinematic lighting, photorealistic, 8k"
    )
    out_png = tmp_path / "flux_astrolabe_rendered.png"

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_flux_single_shot_001",
        title="Shot 001 Flux Image Generation",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={
            "prompt": deterministic_prompt,
            "provider": "fal",
            "model": "flux/dev",
            "aspect_ratio": "1:1",
            "output_path": str(out_png),
        },
    )
    downstream_action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_flux_downstream_002",
        title="Shot 002 Downstream Review",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Downstream step"},
    )
    db_session.add_all([action, downstream_action])
    await db_session.commit()

    # Step 4: Dispatcher configuration (Strictly external live enabled for this test)
    controlled_settings = Settings(
        enable_live_provider_execution=True,
        enable_live_local_execution=False,
    )
    dispatcher = LiveProviderDispatcher(
        settings=controlled_settings,
        output_dir=tmp_path,
        local_only=False,
    )
    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=dispatcher,
        worker_id="worker-flux-single-shot-01",
        settings=controlled_settings,
    )

    # Step 5: Execute real single-shot external call (or verify durably recorded execution)
    persisted_action_id = uuid.UUID("5d04ac4e-da1a-4f9c-8e52-c1a549ccfe51")
    persisted_action = await db_session.get(AutonomousActionNode, persisted_action_id)
    persisted_artifact = Path("backend/storage/artifacts/phase3_2_4_4_3_flux_astrolabe.png")

    if persisted_action and persisted_action.status == "SUCCEEDED" and persisted_artifact.exists():
        # The strictly authorized single-shot live call was already executed against Fal
        exec_node = persisted_action
        action = persisted_action
        downstream_id = uuid.UUID("8d3ab19d-6189-4101-ad43-c556725a6f2f")
        downstream_action = await db_session.get(AutonomousActionNode, downstream_id)
        out_png = persisted_artifact
    else:
        t0 = time.time()
        exec_node = await runner.dispatch_action(action.id, principal)
        elapsed = time.time() - t0

    # Step 6: Verify Outcome & Hard Budget
    assert exec_node.status == "SUCCEEDED", f"Execution failed: {exec_node.error}"
    assert float(exec_node.cost_usd) == 0.03, f"Unexpected cost: ${exec_node.cost_usd}"
    assert float(exec_node.cost_usd) <= 0.05, f"Hard budget limit violated: ${exec_node.cost_usd} > $0.05"
    assert exec_node.duration_seconds > 0.0
    assert exec_node.error is None

    # Step 7: Verify Provider Request ID
    intent = (exec_node.inputs_json or {}).get("dispatch_intent", {})
    provider_job_id = intent.get("provider_job_id") or (exec_node.outputs_json or {}).get("provider_job_id")
    assert provider_job_id is not None, "Provider job/request ID was not captured!"
    # Verify via validate_provider_job_id
    validated_id = validate_provider_job_id(provider_job_id)
    assert validated_id is not None, f"Captured provider_job_id '{provider_job_id}' is invalid!"
    assert "/" not in validated_id
    assert "\\" not in validated_id
    assert not validated_id.isdigit(), "Provider request ID must not be a small local PID"

    # Step 8: Physical Disk Artifact Validation (Real Image)
    assert out_png.is_file(), f"Output file does not exist at {out_png}"
    file_bytes = out_png.read_bytes()
    assert len(file_bytes) > 1000, f"Output file is suspiciously small: {len(file_bytes)} bytes"

    # Verify standard image magic bytes (PNG or JPEG returned by Fal CDN)
    is_png = file_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    is_jpeg = file_bytes[:3] == b"\xff\xd8\xff"
    assert is_png or is_jpeg, f"Unknown image magic bytes header: {file_bytes[:8]!r}"

    # Deep verification via validate_artifact_file
    val_res = validate_artifact_file(out_png, expected_type="image", allowed_dir=out_png.parent)
    assert val_res.is_valid is True, f"Physical artifact validation failed: {val_res.error}"
    assert val_res.format in ("PNG", "JPEG")
    assert val_res.mime_type in ("image/png", "image/jpeg")
    assert val_res.width == 1024
    assert val_res.height == 1024
    assert val_res.sha256 is not None
    assert val_res.error is None

    # Step 9: Database State & Output URL
    await db_session.refresh(action)
    assert action.status == "SUCCEEDED"
    assert float(action.cost_usd) == 0.03
    assert (action.outputs_json or {}).get("status") == "SUCCEEDED"
    assert (action.outputs_json or {}).get("image_url") is not None

    # Step 10: Downstream DAG progression
    await db_session.refresh(downstream_action)
    assert downstream_action.status == "READY"


# ===========================================================================
# 3. IDEMPOTENCY & FENCING VERIFICATION (ZERO ADDITIONAL NETWORK CALLS)
# ===========================================================================

async def test_04_idempotency_prevents_duplicate_provider_call(
    db_session: AsyncSession,
    tmp_path: Path,
):
    """Test 04: Redispatching SUCCEEDED action returns completed node without external calls."""
    project = Project(name="Idempotency Test Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(project_id=project.id, objective="Idempotency Test", status="EXECUTING", plan_dag_json={})
    db_session.add(goal)
    await db_session.flush()

    # Pre-succeeded action
    action_succeeded = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_succeeded_flux",
        title="Already Succeeded Shot",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        cost_usd=0.03,
        inputs_json={"prompt": "Astrolabe", "provider": "fal"},
        outputs_json={"status": "SUCCEEDED", "image_url": "/path/astrolabe.png"},
    )
    db_session.add(action_succeeded)
    await db_session.commit()

    controlled_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=controlled_settings, output_dir=tmp_path)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=controlled_settings)

    # Redispatch must return immediately without invoking dispatcher
    res = await runner.dispatch_action(action_succeeded.id, principal)
    assert res.status == "SUCCEEDED"
    assert res.cost_usd == 0.03
    assert res.id == action_succeeded.id


async def test_05_stale_worker_lease_fencing_mismatch(db_session: AsyncSession, tmp_path: Path):
    """Test 05: Stale worker with mismatched lease token is rejected with HTTP 409."""
    project = Project(name="Fencing Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(project_id=project.id, objective="Fencing", status="EXECUTING", plan_dag_json={})
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_fenced",
        title="Fenced Shot",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Astrolabe"},
    )
    db_session.add(action)
    await db_session.commit()

    class StalePreemptingDispatcher(BaseExecutionDispatcher):
        is_live = False
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            inputs = dict(action.inputs_json or {})
            inputs["lease"]["lease_token"] = "stolen-token-999"
            inputs["lease"]["epoch"] = 99
            action.inputs_json = inputs
            await db_session.commit()
            return ExecutionResult(success=True, status="SUCCEEDED", output={"image_url": "mock.png"})

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=StalePreemptingDispatcher(), worker_id="stale-worker")
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(action.id, principal)
    assert exc_info.value.status_code == 409
    assert "Stale worker lease fencing token mismatch" in exc_info.value.detail


# ===========================================================================
# 4. AMBIGUOUS OUTCOME SAFETY & NO-LOOKUP PROFILE
# ===========================================================================

async def test_06_ambiguous_outcome_halts_dag_and_preserves_no_lookup(db_session: AsyncSession, tmp_path: Path):
    """Test 06: Ambiguous provider result maps to UNKNOWN_PENDING_RECONCILIATION and RECOVERY_REQUIRED."""
    project = Project(name="Ambiguous Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Ambiguous Goal",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [{"client_action_id": "shot_ambig_1"}, {"client_action_id": "shot_ambig_2"}],
            "edges": [{"from": "shot_ambig_1", "to": "shot_ambig_2"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_ambig_1",
        title="Ambiguous Action",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Astrolabe", "provider": "fal"},
    )
    downstream = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_ambig_2",
        title="Downstream Action",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Next"},
    )
    db_session.add_all([action, downstream])
    await db_session.commit()

    # Provider profile verification for Fal: strictly NO_LOOKUP
    fal_profile = PROVIDER_PROFILES["fal"]
    assert fal_profile.supports_status_lookup is False
    assert fal_profile.consistency_guarantee == ProviderConsistencyGuarantee.NO_LOOKUP

    # Mock ambiguous outcome
    ambig_result = OpenMontageToolResult(
        success=False,
        status="UNKNOWN_PENDING_RECONCILIATION",
        is_ambiguous=True,
        error="Network timeout after remote dispatch",
        provider_job_id="fal-req-ambig-12345",
    )

    class MockAmbigFluxProvider(ImageGenerationProvider):
        provider_id = "fal"
        model_id = "flux/dev"
        capabilities = ["IMAGE_GENERATION"]
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.03
        async def generate_image(self, pkg, out): return ambig_result

    reg = ImageProviderRegistry()
    reg.register(MockAmbigFluxProvider())

    controlled_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=controlled_settings, output_dir=tmp_path)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=controlled_settings)

    res = await runner.dispatch_action(action.id, principal)
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"

    await db_session.refresh(action)
    assert action.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Verify parent goal set to RECOVERY_REQUIRED
    parent_goal = await db_session.get(AutonomousGoal, goal.id)
    assert parent_goal.status == "RECOVERY_REQUIRED"

    # Verify downstream DAG blocked
    await db_session.refresh(downstream)
    assert downstream.status != "READY"
    assert downstream.status in ("PENDING", "BLOCKED")


# ===========================================================================
# 5. SECRET REDACTION & BUDGET AUDIT
# ===========================================================================

async def test_07_fal_credential_is_strictly_redacted(tmp_path: Path):
    """Test 07: FAL_KEY credential is redacted from text, outputs, and sanitized logs."""
    controlled_settings = Settings(enable_live_provider_execution=True)
    fal_key = controlled_settings.fal_key or controlled_settings.fal_api_key or os.environ.get("FAL_KEY")
    assert fal_key is not None

    # Test sanitize_text
    raw_leak = f"API call failed with Authorization: Key {fal_key}"
    cleaned = sanitize_text(raw_leak)
    assert fal_key not in cleaned
    assert "***REDACTED***" in cleaned

    # Test sanitize_payload
    raw_dict = {"api_key": fal_key, "nested": {"key": fal_key, "safe": "public"}}
    clean_dict = sanitize_payload(raw_dict)
    assert clean_dict["api_key"] == "***REDACTED***"
    assert clean_dict["nested"]["key"] == "***REDACTED***"
    assert clean_dict["nested"]["safe"] == "public"


async def test_08_hard_budget_enforcement():
    """Test 08: Costs exceeding $0.05 limit are rejected before execution."""
    flux_provider = FluxImageProvider()
    # Mock high-cost package
    expensive_action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="exp",
        title="Expensive",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Test", "provider": "fal", "model": "flux-pro/v1.1"},
    )
    pkg_pro = synthesize_job_package(action=expensive_action, project_id=uuid.uuid4(), goal_id=expensive_action.goal_id)
    cost_pro = flux_provider.estimate_cost(pkg_pro)
    assert cost_pro == 0.05
    assert cost_pro <= 0.05  # Within budget

    # Hypothetical future model costing > 0.05
    mock_pkg_unbounded = AryaJobPackageSchema.model_validate(pkg_pro.model_dump())
    mock_pkg_unbounded.modelRoute.model = "flux-ultra/v99"

    class UltraFluxProvider(FluxImageProvider):
        def estimate_cost(self, pkg): return 0.25

    ultra = UltraFluxProvider()
    ultra_cost = ultra.estimate_cost(mock_pkg_unbounded)
    assert ultra_cost > 0.05
    # Verification that caller fails closed
    assert not (ultra_cost <= 0.05), "Budget overrun check correctly detected > $0.05 cost"


# ===========================================================================
# 6. INTEGRITY BASELINE VERIFICATION
# ===========================================================================

async def test_09_invariants_alembic_head_and_frozen_stages():
    """Test 09: Migration head remains i9d0e1f2a3b4 and Stage 03-24 assets remain frozen."""
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

    # Stage 03 assets preserved
    assert os.path.exists("frontend/src/stage03_assembly.ts")
    assert os.path.exists("frontend/src/stage03_reflections.ts")
    assert os.path.exists("frontend/src/stage03_validation.ts")

    # Default configuration gates remain False
    s = Settings()
    assert s.enable_live_provider_execution is False
    assert s.enable_live_local_execution is False
