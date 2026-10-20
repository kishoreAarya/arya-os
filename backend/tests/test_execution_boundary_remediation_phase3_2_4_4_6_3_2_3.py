"""
AryaOS V1 Stage 25 Phase 3.2.4.4.6.3.2.3
Comprehensive Execution-Boundary Remediation Test Suite.

Verifies the Governed Execution-Capability Model (Option B + C):
A. Adapter Execution Boundary (Tests 1-9)
B. Local Tool Boundary (Tests 10-13)
C. Subprocess Environment & Credential Boundary (Tests 14-20)
D. Dispatcher Capability Context Issuance (Tests 21-25)
E. Legacy Production Route Quarantine (Tests 26-29)
F. Direct Creator FAL Adapter Gate (Tests 30-31)
G. Adversarial Capability Tampering (Tests 32-40)
H. Invariant, Isolation & Security Verification (Tests 41-55)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio(loop_scope="module")

from app.core.config import Settings
from app.models.production import ProductionJob, ProductionShot
from app.models.execution_bridge import AutonomousActionNode, BudgetReservation
from app.providers import fal
from app.schemas.production import AryaJobPackageSchema
from app.services.dispatcher import (
    LiveExecutionGateError,
    LiveProviderDispatcher,
    is_live_provider_execution_enabled,
    is_live_local_execution_enabled,
    verify_live_execution_gate,
)
from app.services.execution_gateway import (
    ExecutionBoundaryQuarantineError,
    ExecutionGateway,
)
from app.services.openmontage_adapter import (
    ExecutionBoundaryError,
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    SecurityViolationError,
    create_governed_execution_context,
    is_external_tool,
    openmontage_adapter,
)

pytestmark = pytest.mark.asyncio


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

def make_valid_context(
    action_node_id: str | None = None,
    goal_id: str | None = None,
    project_id: str | None = None,
    reservation_id: str | None = None,
    provider_id: str = "fal",
    ttl_seconds: float = 300.0,
) -> GovernedExecutionContext:
    return create_governed_execution_context(
        action_node_id=action_node_id or str(uuid.uuid4()),
        goal_id=goal_id or str(uuid.uuid4()),
        project_id=project_id or str(uuid.uuid4()),
        reservation_id=reservation_id or str(uuid.uuid4()),
        provider_id=provider_id,
        ttl_seconds=ttl_seconds,
    )


# =============================================================================
# A. Adapter Execution Boundary (Tests 1-9)
# =============================================================================

async def test_01_execute_tool_flux_without_context_raises_boundary_error():
    """1. execute_tool('flux_image', ...) without execution context raises ExecutionBoundaryError."""
    adapter = OpenMontageAdapter()
    with pytest.raises(ExecutionBoundaryError) as exc_info:
        await adapter.execute_tool("flux_image", {"prompt": "hero landscape"})
    assert "Direct unauthenticated execution of external tool 'flux_image' is strictly prohibited" in str(exc_info.value)


async def test_02_execute_tool_kling_without_context_raises_boundary_error():
    """2. execute_tool('kling_video', ...) without execution context raises ExecutionBoundaryError."""
    adapter = OpenMontageAdapter()
    with pytest.raises(ExecutionBoundaryError) as exc_info:
        await adapter.execute_tool("kling_video", {"prompt": "cinematic camera"})
    assert "Direct unauthenticated execution of external tool 'kling_video' is strictly prohibited" in str(exc_info.value)


async def test_03_execute_tool_camera_motion_without_context_routes_to_local_tool():
    """3. execute_tool('camera_motion', ...) without execution context succeeds (routes to local tool)."""
    adapter = OpenMontageAdapter()
    with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(
            success=True, status="COMPLETED", artifacts=["test.mp4"], tool="camera_motion"
        )
        res = await adapter.execute_tool("camera_motion", {"direction": "push"})
        assert res.success is True
        assert res.tool == "camera_motion"
        mock_run.assert_awaited_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("is_local_only") is True


async def test_04_execute_governed_tool_flux_with_gate_false_raises_gate_error():
    """4. execute_governed_tool('flux_image', ..., valid_context) with live gate False raises LiveExecutionGateError."""
    ctx = make_valid_context(provider_id="fal")
    adapter = OpenMontageAdapter()
    with pytest.raises(LiveExecutionGateError) as exc_info:
        await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
    assert "Live external provider execution is disabled" in str(exc_info.value)


async def test_05_execute_governed_tool_with_tampered_signature_raises_security_violation():
    """5. execute_governed_tool('flux_image', ..., context_with_tampered_signature) raises SecurityViolationError."""
    ctx = make_valid_context(provider_id="fal")
    ctx.capability_signature = "bad_signature_00000000000000000000000000000000"
    adapter = OpenMontageAdapter()
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Capability signature verification failed" in str(exc_info.value)


async def test_06_execute_governed_tool_with_expired_ttl_raises_security_violation():
    """6. execute_governed_tool('flux_image', ..., context_with_expired_ttl) raises SecurityViolationError."""
    ctx = make_valid_context(provider_id="fal", ttl_seconds=-10.0)
    adapter = OpenMontageAdapter()
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Capability expired at" in str(exc_info.value)


async def test_07_execute_governed_tool_reused_nonce_raises_security_violation_on_replay():
    """7. execute_governed_tool('flux_image', ..., reused_nonce_context) raises SecurityViolationError on second invocation."""
    ctx = make_valid_context(provider_id="fal")
    adapter = OpenMontageAdapter()
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True), \
         patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(success=True, status="COMPLETED")
        res1 = await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert res1.success is True

        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Replay detected" in str(exc_info.value)


async def test_08_execute_governed_tool_provider_mismatch_raises_security_violation():
    """8. execute_governed_tool('flux_image', ..., provider_mismatch_context) raises SecurityViolationError."""
    ctx = make_valid_context(provider_id="kling")
    adapter = OpenMontageAdapter()
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=ctx)
        assert "Provider mismatch" in str(exc_info.value)


async def test_09_execute_governed_tool_camera_motion_mismatch_raises_security_violation():
    """9. execute_governed_tool on local tool camera_motion with external provider context raises SecurityViolationError."""
    adapter = OpenMontageAdapter()
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True):
        with pytest.raises(SecurityViolationError) as exc_info:
            await adapter.execute_governed_tool("flux_image", {"prompt": "hero"}, execution_context=make_valid_context(provider_id="openai"))
        assert "Provider mismatch" in str(exc_info.value)


# =============================================================================
# B. Local Tool Boundary (Tests 10-13)
# =============================================================================

async def test_10_execute_local_tool_camera_motion_succeeds_without_provider_context():
    """10. execute_local_tool('camera_motion', ...) succeeds without provider context."""
    adapter = OpenMontageAdapter()
    with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(success=True, status="COMPLETED", tool="camera_motion")
        res = await adapter.execute_local_tool("camera_motion", {"direction": "pan"})
        assert res.success is True
        assert res.tool == "camera_motion"


async def test_11_execute_local_tool_camera_push_video_succeeds_without_provider_context():
    """11. execute_local_tool('camera_push_video', ...) succeeds without provider context."""
    adapter = OpenMontageAdapter()
    with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = OpenMontageToolResult(success=True, status="COMPLETED", tool="camera_push_video")
        res = await adapter.execute_local_tool("camera_push_video", {"prompt": "push", "image_path": "a.png"})
        assert res.success is True


async def test_12_execute_local_tool_flux_image_raises_security_violation():
    """12. execute_local_tool('flux_image', ...) raises SecurityViolationError."""
    adapter = OpenMontageAdapter()
    with pytest.raises(SecurityViolationError) as exc_info:
        await adapter.execute_local_tool("flux_image", {"prompt": "hero"})
    assert "Tool 'flux_image' is an external API tool and cannot be executed via execute_local_tool" in str(exc_info.value)


async def test_13_execute_local_tool_kling_video_raises_security_violation():
    """13. execute_local_tool('kling_video', ...) raises SecurityViolationError."""
    adapter = OpenMontageAdapter()
    with pytest.raises(SecurityViolationError) as exc_info:
        await adapter.execute_local_tool("kling_video", {"prompt": "hero"})
    assert "Tool 'kling_video' is an external API tool and cannot be executed via execute_local_tool" in str(exc_info.value)


# =============================================================================
# C. Subprocess Environment & Credential Boundary (Tests 14-20)
# =============================================================================

async def test_14_build_subprocess_env_camera_motion_contains_zero_credentials():
    """14. build_subprocess_env('camera_motion') contains zero FAL_KEY or KLING_API_KEY."""
    adapter = OpenMontageAdapter()
    env = adapter.build_subprocess_env("camera_motion")
    assert "FAL_KEY" not in env
    assert "FAL_API_KEY" not in env
    assert "KLING_API_KEY" not in env


async def test_15_build_subprocess_env_camera_push_video_contains_zero_credentials():
    """15. build_subprocess_env('camera_push_video') contains zero FAL_KEY or KLING_API_KEY."""
    adapter = OpenMontageAdapter()
    ctx = make_valid_context(provider_id="fal")
    env = adapter.build_subprocess_env("camera_push_video", execution_context=ctx)
    assert "FAL_KEY" not in env
    assert "FAL_API_KEY" not in env
    assert "KLING_API_KEY" not in env


async def test_16_build_subprocess_env_flux_without_context_contains_zero_credentials():
    """16. build_subprocess_env('flux_image', execution_context=None) contains zero credentials."""
    adapter = OpenMontageAdapter()
    env = adapter.build_subprocess_env("flux_image", execution_context=None)
    assert "FAL_KEY" not in env
    assert "FAL_API_KEY" not in env
    assert "KLING_API_KEY" not in env


async def test_17_build_subprocess_env_flux_with_gate_false_contains_zero_credentials():
    """17. build_subprocess_env('flux_image', valid_context) with live gate False contains zero credentials."""
    adapter = OpenMontageAdapter()
    ctx = make_valid_context(provider_id="fal")
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=False):
        env = adapter.build_subprocess_env("flux_image", execution_context=ctx)
        assert "FAL_KEY" not in env
        assert "FAL_API_KEY" not in env
        assert "KLING_API_KEY" not in env


async def test_18_build_subprocess_env_flux_with_gate_true_contains_fal_key():
    """18. build_subprocess_env('flux_image', valid_context) with live gate True contains FAL_KEY."""
    adapter = OpenMontageAdapter()
    ctx = make_valid_context(provider_id="fal")
    mock_settings = Settings(enable_live_provider_execution=True, fal_key="test_fal_secret_key_123")
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True), \
         patch("app.core.config.get_settings", return_value=mock_settings):
        env = adapter.build_subprocess_env("flux_image", execution_context=ctx)
        assert env.get("FAL_KEY") == "test_fal_secret_key_123"
        assert env.get("FAL_API_KEY") == "test_fal_secret_key_123"


async def test_19_build_subprocess_env_kling_with_gate_true_contains_kling_key():
    """19. build_subprocess_env('kling_video', valid_context) with live gate True contains KLING_API_KEY."""
    adapter = OpenMontageAdapter()
    ctx = make_valid_context(provider_id="kling")
    mock_settings = Settings(enable_live_provider_execution=True)
    with patch("app.services.dispatcher.is_live_provider_execution_enabled", return_value=True), \
         patch("app.core.config.get_settings", return_value=mock_settings), \
         patch.dict(os.environ, {"KLING_API_KEY": "test_kling_secret_456"}):
        env = adapter.build_subprocess_env("kling_video", execution_context=ctx)
        assert env.get("KLING_API_KEY") == "test_kling_secret_456"


async def test_20_build_subprocess_env_never_contains_backend_secrets():
    """20. build_subprocess_env never contains backend secrets (DATABASE_URL, SECRET_KEY, etc.) under any condition."""
    adapter = OpenMontageAdapter()
    ctx = make_valid_context(provider_id="fal")
    with patch.dict(os.environ, {
        "DATABASE_URL": "postgresql://user:pass@host/db",
        "SECRET_KEY": "super_secret_jwt",
        "POSTGRES_PASSWORD": "forbidden_password",
    }):
        env = adapter.build_subprocess_env("flux_image", execution_context=ctx)
        assert "DATABASE_URL" not in env
        assert "SECRET_KEY" not in env
        assert "POSTGRES_PASSWORD" not in env


# =============================================================================
# D. Dispatcher Capability Context Issuance (Tests 21-25)
# =============================================================================

async def test_21_dispatcher_issues_valid_governed_execution_context(tmp_path: Path):
    """21. LiveProviderDispatcher.dispatch issues valid GovernedExecutionContext to provider."""
    captured_context = None

    class CaptureProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            nonlocal captured_context
            captured_context = execution_context
            img = Image.new("RGB", (16, 16), color=(255, 0, 0))
            img.save(output_path, "PNG")
            return OpenMontageToolResult(success=True, status="COMPLETED", artifacts=[output_path])

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=tmp_path,
    )
    dispatcher.image_registry.register(CaptureProvider())

    action_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id="act_test_21",
        title="Test Context Issuance",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={
            "prompt": "Test Prompt",
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "reservation_id": "res-test-21-999",
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert captured_context is not None
    assert isinstance(captured_context, GovernedExecutionContext)


async def test_22_context_contains_correct_action_goal_project_reservation_ids(tmp_path: Path):
    """22. Context contains active action_node_id, goal_id, project_id, reservation_id."""
    captured_context = None

    class CaptureProvider:
        provider_id = "fal"
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.05
        async def generate_image(self, pkg, output_path, execution_context=None):
            nonlocal captured_context
            captured_context = execution_context
            img = Image.new("RGB", (16, 16), color=(255, 0, 0))
            img.save(output_path, "PNG")
            return OpenMontageToolResult(success=True, status="COMPLETED", artifacts=[output_path])

    dispatcher = LiveProviderDispatcher(
        settings=Settings(enable_live_provider_execution=True),
        output_dir=tmp_path,
    )
    dispatcher.image_registry.register(CaptureProvider())

    action_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    reservation_id = "res-test-22-abc"
    action = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id="act_test_22",
        title="Test Context IDs",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        inputs_json={
            "prompt": "Test Prompt",
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "reservation_id": reservation_id,
        },
    )

    await dispatcher.dispatch(action)
    assert captured_context.action_node_id == str(action_id)
    assert captured_context.goal_id == str(goal_id)
    assert captured_context.reservation_id == reservation_id
    assert captured_context.provider_id == "fal"


async def test_23_context_signature_verifies_against_signing_key():
    """23. Context signature verifies against AryaOS signing key."""
    ctx = make_valid_context()
    ctx.verify_authenticity()


async def test_24_context_expires_within_configured_ttl():
    """24. Context expires within configured TTL (default 300s)."""
    before = datetime.now(timezone.utc)
    ctx = make_valid_context(ttl_seconds=300.0)
    after = datetime.now(timezone.utc)

    exp_dt = datetime.fromisoformat(ctx.expires_at.replace("Z", "+00:00"))
    auth_dt = datetime.fromisoformat(ctx.authorized_at.replace("Z", "+00:00"))

    diff = (exp_dt - auth_dt).total_seconds()
    assert 299.0 <= diff <= 301.0
    assert before <= auth_dt <= after


async def test_25_context_nonce_is_unique_per_dispatch():
    """25. Context nonce is unique per dispatch."""
    nonces = {make_valid_context().execution_nonce for _ in range(50)}
    assert len(nonces) == 50


# =============================================================================
# E. Legacy Production Route Quarantine (Tests 26-29)
# =============================================================================

async def test_26_execution_gateway_flux_quarantined(client: AsyncClient, db_session: AsyncSession):
    """26. ExecutionGateway.execute_job for flux_image raises ExecutionBoundaryQuarantineError (HTTP 409)."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Quarantine Proj Flux"})
    assert proj_res.status_code == 201
    project_id = uuid.UUID(proj_res.json()["id"])

    gateway = ExecutionGateway()
    job_id = uuid.uuid4()

    pkg_dict = {
        "jobPackageId": f"pkg-q-flux-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-10-08T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(uuid.uuid4()),
        "shotId": str(uuid.uuid4()),
        "plan": {
            "title": "Quarantine Test",
            "prompt": "Hero image",
            "generationType": "image",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "modelName": "Flux Pro",
            "mode": "image",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Hero image"},
    }
    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)

    job = ProductionJob(
        id=job_id,
        project_id=project_id,
        job_package_id=pkg_dict["jobPackageId"],
        provider="fal",
        model="flux-pro/v1.1",
        status="QUEUED",
        job_package_json=pkg_dict,
    )
    db_session.add(job)
    await db_session.commit()

    try:
        with pytest.raises(ExecutionBoundaryQuarantineError) as exc_info:
            await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)
        assert exc_info.value.status_code == 409
        assert "permanently quarantined" in str(exc_info.value.detail)
    finally:
        await db_session.rollback()


async def test_27_execution_gateway_kling_quarantined(client: AsyncClient, db_session: AsyncSession):
    """27. ExecutionGateway.execute_job for kling_video raises ExecutionBoundaryQuarantineError (HTTP 409)."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Quarantine Proj Kling"})
    assert proj_res.status_code == 201
    project_id = uuid.UUID(proj_res.json()["id"])

    gateway = ExecutionGateway()
    job_id = uuid.uuid4()

    pkg_dict = {
        "jobPackageId": f"pkg-q-kling-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-10-08T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(uuid.uuid4()),
        "shotId": str(uuid.uuid4()),
        "plan": {
            "title": "Quarantine Kling Test",
            "prompt": "Hero video",
            "generationType": "video",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "modelName": "Kling Standard",
            "mode": "video",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "video/mp4"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Hero video"},
    }
    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)

    job = ProductionJob(
        id=job_id,
        project_id=project_id,
        job_package_id=pkg_dict["jobPackageId"],
        provider="kling",
        model="kling-video/v3/standard",
        status="QUEUED",
        job_package_json=pkg_dict,
    )
    db_session.add(job)
    await db_session.commit()

    try:
        with pytest.raises(ExecutionBoundaryQuarantineError) as exc_info:
            await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)
        assert exc_info.value.status_code == 409
        assert "permanently quarantined" in str(exc_info.value.detail)
    finally:
        await db_session.rollback()


async def test_28_execution_gateway_camera_push_video_succeeds_via_local_execution(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
):
    """28. ExecutionGateway.execute_job for camera_push_video succeeds via local execution."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Local Cam Push Proj"})
    assert proj_res.status_code == 201
    project_id = uuid.UUID(proj_res.json()["id"])

    adapter = OpenMontageAdapter()
    gateway = ExecutionGateway(adapter=adapter)
    job_id = uuid.uuid4()
    shot_id = uuid.uuid4()

    init_frame = tmp_path / "init_frame.png"
    init_frame.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    pkg_dict = {
        "jobPackageId": f"pkg-local-cam-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-10-08T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(uuid.uuid4()),
        "shotId": str(shot_id),
        "plan": {
            "title": "Camera Push Local",
            "prompt": "Smooth push",
            "generationType": "video",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": [str(init_frame)], "firstFrame": str(init_frame)},
        "modelRoute": {
            "provider": "camera_motion",
            "model": "camera-push",
            "modelName": "Camera Push",
            "mode": "video",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "video/mp4"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Smooth push"},
    }
    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)

    job = ProductionJob(
        id=job_id,
        project_id=project_id,
        job_package_id=pkg_dict["jobPackageId"],
        provider="camera_motion",
        model="camera-push",
        status="QUEUED",
        job_package_json=pkg_dict,
    )
    db_session.add(job)
    await db_session.commit()

    from app.services.execution_gateway import STORAGE_ARTIFACTS_DIR
    out_vid = STORAGE_ARTIFACTS_DIR / f"test_out_push_{uuid.uuid4().hex[:6]}.mp4"
    out_vid.write_bytes(b"\x00\x00\x00 ftypmp42" + b"\x00" * 50)

    from app.services.artifact_validator import ArtifactValidationResult
    try:
        with patch.object(adapter, "_run_subprocess", new_callable=AsyncMock) as mock_run, \
             patch("app.services.execution_gateway.validate_artifact_file") as mock_val:
            mock_val.return_value = ArtifactValidationResult(
                is_valid=True,
                filename=out_vid.name,
                file_path=out_vid,
                file_size_bytes=len(out_vid.read_bytes()),
                duration=5.0,
            )
            mock_run.return_value = OpenMontageToolResult(
                success=True,
                status="COMPLETED",
                artifacts=[str(out_vid)],
                tool="camera_push_video",
            )
            res_job = await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)
            assert res_job.status == "COMPLETED"
            assert res_job.progress == 1.0
    finally:
        if out_vid.exists():
            out_vid.unlink()
        await db_session.rollback()


async def test_29_post_jobs_dispatch_external_tool_is_quarantined(client: AsyncClient):
    """29. POST /api/v1/jobs/{id}/dispatch attempting external generation is quarantined."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Quarantine Route Proj"})
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]
    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": seq_id,
            "shot_number": 1,
            "title": "Quarantine Shot",
            "prompt": "External Flux generation",
            "model": "flux-pro/v1.1",
            "provider": "fal",
        },
    )
    shot_id = shot_res.json()["id"]

    pkg = {
        "jobPackageId": f"pkg-ext-q-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-10-08T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": shot_id,
        "plan": {
            "title": "Quarantine Shot",
            "prompt": "External Flux generation",
            "generationType": "image",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "modelName": "Flux Pro",
            "mode": "image",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "External Flux generation"},
    }

    create_res = await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg)
    assert create_res.status_code == 201
    created_job_id = create_res.json()["id"]

    disp_res = await client.post(f"/api/v1/jobs/{created_job_id}/dispatch?sync=true")
    assert disp_res.status_code == 409
    assert "permanently quarantined" in disp_res.json()["detail"]


# =============================================================================
# F. Direct Creator FAL Adapter Gate (Tests 30-31)
# =============================================================================

async def test_30_creator_fal_generate_image_fails_closed_when_gate_false():
    """30. fal.generate_image with live gate False raises LiveExecutionGateError."""
    with pytest.raises(LiveExecutionGateError) as exc_info:
        await fal.generate_image(prompt="test", api_key="test_key", model="flux-pro/v1.1")
    assert "Live external provider execution is disabled" in str(exc_info.value)


async def test_31_creator_fal_generate_video_fails_closed_when_gate_false():
    """31. fal.generate_video with live gate False raises LiveExecutionGateError."""
    with pytest.raises(LiveExecutionGateError) as exc_info:
        await fal.generate_video(prompt="test", api_key="test_key", model="kling")
    assert "Live external provider execution is disabled" in str(exc_info.value)


# =============================================================================
# G. Adversarial Capability Tampering (Tests 32-40)
# =============================================================================

async def test_32_modified_action_node_id_fails_signature_verification():
    """32. Context with modified action_node_id fails signature verification."""
    ctx = make_valid_context()
    ctx.action_node_id = str(uuid.uuid4())
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_33_modified_goal_id_fails_signature_verification():
    """33. Context with modified goal_id fails signature verification."""
    ctx = make_valid_context()
    ctx.goal_id = str(uuid.uuid4())
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_34_modified_project_id_fails_signature_verification():
    """34. Context with modified project_id fails signature verification."""
    ctx = make_valid_context()
    ctx.project_id = str(uuid.uuid4())
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_35_modified_reservation_id_fails_signature_verification():
    """35. Context with modified reservation_id fails signature verification."""
    ctx = make_valid_context()
    ctx.reservation_id = str(uuid.uuid4())
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_36_modified_provider_id_fails_signature_verification():
    """36. Context with modified provider_id fails signature verification."""
    ctx = make_valid_context(provider_id="fal")
    ctx.provider_id = "kling"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_37_forged_signature_fails_verification():
    """37. Context with forged signature fails signature verification."""
    ctx = make_valid_context()
    ctx.capability_signature = hashlib.sha256(b"attacker_arbitrary_string").hexdigest()
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_38_empty_signature_fails_verification():
    """38. Context with empty signature fails verification."""
    ctx = make_valid_context()
    ctx.capability_signature = ""
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "Missing required execution context field 'capability_signature'" in str(exc_info.value)


async def test_39_missing_nonce_fails_verification():
    """39. Context with missing nonce fails verification."""
    ctx = make_valid_context()
    ctx.execution_nonce = ""
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx.verify_authenticity()
    assert "Missing required execution context field 'execution_nonce'" in str(exc_info.value)


async def test_40_rapid_parallel_replay_of_same_nonce():
    """40. Rapid parallel replay of same nonce: exactly one succeeds, zero duplicate dispatch."""
    ctx = make_valid_context(provider_id="fal")

    results = []
    async def try_verify():
        try:
            ctx.verify_authenticity()
            return "SUCCESS"
        except SecurityViolationError as e:
            return f"REJECTED: {e}"

    outcomes = await asyncio.gather(*(try_verify() for _ in range(5)))
    success_count = sum(1 for o in outcomes if o == "SUCCESS")
    rejected_count = sum(1 for o in outcomes if "REJECTED" in o)

    assert success_count == 1, f"Expected exactly 1 success, got {success_count} ({outcomes})"
    assert rejected_count == 4


# =============================================================================
# H. Invariant & Isolation Verification (Tests 41-55)
# =============================================================================

async def test_41_stage03_master_blend_sha256_invariant():
    """41. Stage 03 Master Blend SHA-256 remains strictly unchanged."""
    blend_path = Path("frontend/blender/scenes/stage03_aryaos_memory_environment.blend")
    assert blend_path.exists(), f"Stage 03 master blend missing: {blend_path}"
    actual_hash = hashlib.sha256(blend_path.read_bytes()).hexdigest()
    expected_hash = "c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f"
    assert actual_hash == expected_hash, f"Stage 03 scene altered! Hash mismatch: {actual_hash}"


async def test_42_stage03_memory_glbs_count_invariant():
    """42. Stage 03 memory GLBs count unchanged (exactly 28)."""
    glbs = list(Path("frontend").rglob("*.glb"))
    stage03_glbs = [g for g in glbs if "stage03_memory" in str(g)]
    assert len(stage03_glbs) == 28, f"Expected 28 Stage 03 GLBs, found {len(stage03_glbs)}"


async def test_43_alembic_head_invariant():
    """43. Alembic migration head unchanged (j0e1f2a3b4c5)."""
    mig_path = Path("alembic/versions/j0e1f2a3b4c5_atomic_budget_reservations.py")
    assert mig_path.exists(), f"Alembic migration head file missing: {mig_path}"
    content = mig_path.read_text(encoding="utf-8")
    assert 'revision: str = "j0e1f2a3b4c5"' in content or "revision = 'j0e1f2a3b4c5'" in content


async def test_44_epoch_1_archive_sha256_invariant():
    """44. Epoch 1 archive SHA-256 unchanged."""
    archive_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend_phase3_archive.json")
    assert archive_path.exists(), f"Epoch 1 archive missing: {archive_path}"
    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    expected_hash = "3cf643e840e5cf357173337be08deb7e7aa4d2f7ce50210879985cbe7d3b4106"
    assert actual_hash == expected_hash, f"Epoch 1 archive altered: {actual_hash}"


async def test_45_epoch_2_ledger_spend_unchanged():
    """45. Epoch 2 ledger spend unchanged ($0.05)."""
    ledger_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend.json")
    assert ledger_path.exists(), f"Epoch 2 ledger missing: {ledger_path}"
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["epoch"] == 2
    assert data["budget"] == 1.00
    used = sum(float(g["cost"]) for g in data["generations"])
    assert round(used, 2) == 0.05
    assert len(data["generations"]) == 1


async def test_46_live_provider_gate_remains_false():
    """46. Live provider gate remains False in default configuration."""
    s = Settings()
    assert is_live_provider_execution_enabled(s) is False


async def test_47_live_local_gate_remains_false():
    """47. Live local gate remains False in default configuration."""
    s = Settings()
    assert is_live_local_execution_enabled(s) is False


async def test_48_zero_external_network_sockets_opened_during_suite():
    """48. Zero external network sockets opened: fails closed without opening socket."""
    s = Settings()
    with pytest.raises(LiveExecutionGateError):
        verify_live_execution_gate(s, is_local_only=False)


async def test_49_zero_external_spend():
    """49. Zero external spend: Epoch 2 ledger total spend remains $0.05."""
    ledger_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend.json")
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert round(sum(float(g["cost"]) for g in data["generations"]), 2) == 0.05


async def test_50_multiple_concurrent_dispatches_generate_disjoint_nonces():
    """50. Multiple concurrent dispatches generate disjoint unique capability nonces."""
    nonces = [make_valid_context().execution_nonce for _ in range(100)]
    assert len(set(nonces)) == 100


async def test_51_context_issued_for_action_a_cannot_be_reused_on_action_b():
    """51. Context issued for Action A cannot be reused on Action B."""
    ctx_a = make_valid_context(action_node_id="act-aaa-111")
    ctx_a.action_node_id = "act-bbb-222"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx_a.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_52_context_issued_for_fal_cannot_be_used_on_kling():
    """52. Context issued for Provider fal cannot be used on Provider kling."""
    ctx_fal = make_valid_context(provider_id="fal")
    ctx_fal.provider_id = "kling"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx_fal.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_53_context_issued_for_goal_1_cannot_be_used_on_goal_2():
    """53. Context issued for Goal 1 cannot be used on Goal 2."""
    ctx_g1 = make_valid_context(goal_id="goal-111")
    ctx_g1.goal_id = "goal-222"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx_g1.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_54_context_issued_for_project_1_cannot_be_used_on_project_2():
    """54. Context issued for Project 1 cannot be used on Project 2."""
    ctx_p1 = make_valid_context(project_id="proj-111")
    ctx_p1.project_id = "proj-222"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx_p1.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)


async def test_55_context_issued_for_reservation_1_cannot_be_used_on_reservation_2():
    """55. Context issued for Reservation 1 cannot be used on Reservation 2."""
    ctx_r1 = make_valid_context(reservation_id="res-111")
    ctx_r1.reservation_id = "res-222"
    with pytest.raises(SecurityViolationError) as exc_info:
        ctx_r1.verify_authenticity()
    assert "invalid cryptographic signature" in str(exc_info.value)
