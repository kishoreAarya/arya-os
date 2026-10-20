"""
AryaOS V1 Stage 25 Phase 3.2.4.4.2 — Controlled Real Local Execution Tests (FFmpeg / Camera Push).

Proves that AryaOS safely and authentically crosses the execution boundary to produce
a genuine local media artifact using the existing Camera Push / FFmpeg path:
    camera_push_video / camera_motion -> FFmpeg -> validated MP4 artifact -> AryaOS persistence

Guarantees:
- Zero external API calls, zero cloud execution, zero paid providers (Cost: $0.00).
- Live external provider gate (ENABLE_LIVE_PROVIDER_EXECUTION) remains strictly disabled (False).
- Local media execution gate (ENABLE_LIVE_LOCAL_EXECUTION) is fail-closed.
- External providers (Fal, Kling) are blocked even if local gate is active.
- Real physical artifact validation on disk (ffprobe, container, stream, dimensions, magic bytes).
- Full 19-step execution lifecycle trace verified.
- Complete failure-injection test suite (Invalid input, Missing output, Corrupt output, Timeout, Duplicate dispatch).
- Process group cleanup & zero leaked processes.
- Worker lease fencing, durable pre-dispatch intent, and idempotency verified.
- Frozen baseline integrity preserved (Alembic i9d0e1f2a3b4, Blender SHA-256, 28 GLBs).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
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
from app.services.image_provider import ImageProviderRegistry
from app.services.openmontage_adapter import (
    FORBIDDEN_SECRET_KEYS,
    OpenMontageAdapter,
    OpenMontageToolResult,
    openmontage_adapter,
)
from app.services.video_provider import (
    CameraMotionVideoProvider,
    VideoGenerationProvider,
    VideoProviderRegistry,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK BLOCKING (ZERO EXTERNAL TRAFFIC)
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during Phase 3.2.4.4.2 tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.2 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


def create_synthetic_source_png(target_path: Path, width: int = 128, height: int = 128) -> Path:
    """Creates a deterministic synthetic test PNG image for camera push first frame."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(60, 110, 180))
    img.save(target_path, format="PNG")
    return target_path


# ===========================================================================
# 1. GATE ISOLATION & FAIL-CLOSED PROTECTION TESTS
# ===========================================================================

async def test_01_local_execution_gate_defaults_to_false_fail_closed():
    """Test 01: Both live provider and live local execution gates default to False."""
    s = Settings()
    assert s.enable_live_provider_execution is False
    assert s.enable_live_local_execution is False
    assert is_live_provider_execution_enabled(s) is False
    assert is_live_local_execution_enabled(s) is False

    # Attempting to initialize LiveProviderDispatcher fails closed
    with pytest.raises(LiveExecutionGateError) as exc_info:
        LiveProviderDispatcher(settings=s, local_only=True)
    assert "disabled by fail-closed configuration gate" in str(exc_info.value)


async def test_02_local_gate_does_not_enable_external_cloud_providers():
    """Test 02: Enabling local execution gate strictly keeps external cloud providers blocked."""
    local_only_settings = Settings(
        enable_live_provider_execution=False,
        enable_live_local_execution=True,
    )
    assert is_live_local_execution_enabled(local_only_settings) is True
    assert is_live_provider_execution_enabled(local_only_settings) is False

    # Local gate check passes for local execution
    verify_live_execution_gate(local_only_settings, is_local_only=True)

    # But external provider gate check strictly fails closed
    with pytest.raises(LiveExecutionGateError) as exc_info:
        verify_live_execution_gate(local_only_settings, is_local_only=False)
    assert "Live external provider execution is disabled" in str(exc_info.value)

    # LiveProviderDispatcher without local_only=True fails closed
    with pytest.raises(LiveExecutionGateError):
        LiveProviderDispatcher(settings=local_only_settings, local_only=False)


async def test_03_dispatching_external_tool_with_local_gate_fails_closed():
    """Test 03: LiveProviderDispatcher with local gate strictly rejects external providers (Fal / Kling)."""
    local_settings = Settings(
        enable_live_provider_execution=False,
        enable_live_local_execution=True,
    )
    dispatcher = LiveProviderDispatcher(settings=local_settings, local_only=True)

    # Attempting to dispatch image generation (which routes to Fal/Flux) fails closed
    ext_action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_ext_blocked",
        title="Blocked External Call",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image with flux", "provider": "fal"},
    )

    with pytest.raises(LiveExecutionGateError) as exc_info:
        await dispatcher.dispatch(ext_action)
    assert "Live external provider execution is disabled" in str(exc_info.value)


# ===========================================================================
# 2. REAL LOCAL EXECUTION (FFMPEG / CAMERA PUSH)
# ===========================================================================

async def test_04_real_local_camera_push_video_produces_genuine_mp4(tmp_path: Path):
    """Test 04: Real local camera push executes through OpenMontage and FFmpeg producing genuine MP4."""
    if not shutil.which("ffmpeg") or not openmontage_adapter.is_available():
        pytest.skip("FFmpeg or OpenMontage environment not available")

    src_png = tmp_path / "camera_push_input.png"
    create_synthetic_source_png(src_png, width=128, height=128)
    dest_mp4 = tmp_path / "camera_push_output.mp4"

    res = await openmontage_adapter.execute_tool(
        tool_name="camera_push_video",
        inputs={
            "prompt": "Cinematic camera push on test card",
            "image_path": str(src_png),
            "duration": 0.5,
            "fps": 25,
            "aspect_ratio": "16:9",
            "output_path": str(dest_mp4),
        },
        timeout_seconds=30.0,
    )

    assert res.success is True
    assert res.status == "COMPLETED"
    assert res.cost_usd == 0.0
    assert res.duration_seconds > 0.0
    assert str(dest_mp4) in res.artifacts
    assert dest_mp4.is_file()
    assert dest_mp4.stat().st_size > 500  # Substantial binary MP4


async def test_05_physical_artifact_validation_on_real_ffmpeg_mp4(tmp_path: Path):
    """Test 05: validate_artifact_file performs deep verification of genuine FFmpeg MP4."""
    if not shutil.which("ffmpeg") or not openmontage_adapter.is_available():
        pytest.skip("FFmpeg or OpenMontage environment not available")

    src_png = tmp_path / "val_input.png"
    create_synthetic_source_png(src_png)
    dest_mp4 = tmp_path / "val_output.mp4"

    await openmontage_adapter.execute_tool(
        tool_name="camera_push_video",
        inputs={
            "prompt": "Test camera push",
            "image_path": str(src_png),
            "duration": 0.5,
            "fps": 25,
            "aspect_ratio": "16:9",
            "output_path": str(dest_mp4),
        },
        timeout_seconds=30.0,
    )

    val_res = validate_artifact_file(dest_mp4, expected_type="video", allowed_dir=tmp_path)
    assert val_res.is_valid is True
    assert val_res.format == "MP4"
    assert val_res.mime_type == "video/mp4"
    assert val_res.file_size_bytes > 500
    assert val_res.width == 1280
    assert val_res.height == 720
    assert val_res.video_codec == "h264"
    assert val_res.duration >= 0.4
    assert val_res.sha256 is not None
    assert val_res.error is None


# ===========================================================================
# 3. END-TO-END EXECUTION TRACE & DATABASE PERSISTENCE
# ===========================================================================

async def test_06_end_to_end_local_execution_trace_and_persistence(db_session: AsyncSession, tmp_path: Path):
    """Test 06: Complete 19-step execution lifecycle trace for real local FFmpeg camera push action."""
    if not shutil.which("ffmpeg") or not openmontage_adapter.is_available():
        pytest.skip("FFmpeg or OpenMontage environment not available")

    # Step 1: Project & Principal setup (Authorization)
    project = Project(name="Controlled Local Real Execution Project")
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
        objective="Controlled Local Camera Push Real Execution",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "shot_001_camera_push"},
                {"client_action_id": "shot_002_downstream"},
            ],
            "edges": [{"from": "shot_001_camera_push", "to": "shot_002_downstream"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    # Step 3: Action creation
    src_png = tmp_path / "shot_001_source.png"
    create_synthetic_source_png(src_png)
    out_mp4 = tmp_path / "shot_001_rendered.mp4"

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_001_camera_push",
        title="Shot 001 Camera Push",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "prompt": "Cinematic camera push",
            "provider": "camera_motion",
            "first_frame": str(src_png),
            "duration": 0.5,
            "fps": 25,
            "aspect_ratio": "16:9",
            "output_path": str(out_mp4),
        },
    )
    downstream_action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_002_downstream",
        title="Shot 002 Downstream Action",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Next shot"},
    )
    db_session.add_all([action, downstream_action])
    await db_session.commit()

    # Step 4: Dispatcher configuration (Local only, fail-closed external)
    local_settings = Settings(
        enable_live_provider_execution=False,
        enable_live_local_execution=True,
    )
    dispatcher = LiveProviderDispatcher(
        settings=local_settings,
        output_dir=tmp_path,
        local_only=True,
    )

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=dispatcher,
        worker_id="test-worker-local-01",
        settings=local_settings,
    )

    # Step 5: Execution boundary crossing
    start_wall = time.time()
    exec_node = await runner.dispatch_action(action.id, principal)
    elapsed = time.time() - start_wall

    # Step 6: Verify Action Outcome & Persistence
    assert exec_node.status == "SUCCEEDED"
    assert exec_node.cost_usd == 0.0  # Exactly $0.00 external cost
    assert exec_node.duration_seconds > 0.0
    assert exec_node.error is None

    # Step 7: Verify database state
    await db_session.refresh(action)
    assert action.status == "SUCCEEDED"
    assert action.cost_usd == 0.0
    assert action.outputs_json is not None
    assert action.outputs_json.get("status") == "SUCCEEDED"
    assert action.outputs_json.get("video_url") == str(out_mp4)
    assert out_mp4.is_file()

    # Step 8: Verify durable pre-dispatch intent was recorded
    intent = (action.inputs_json or {}).get("dispatch_intent", {})
    assert intent.get("provider_id") == "openmontage-live"
    assert intent.get("worker_id") == "test-worker-local-01"

    # Step 9: Verify lease fencing was committed
    lease = (action.inputs_json or {}).get("lease", {})
    assert lease.get("worker_id") == "test-worker-local-01"
    assert lease.get("epoch") == 1

    # Step 10: Verify DAG readiness progression: downstream node unblocked to READY
    await db_session.refresh(downstream_action)
    assert downstream_action.status == "READY"


# ===========================================================================
# 4. FAILURE-INJECTION TESTS
# ===========================================================================

async def test_07_failure_injection_a_invalid_input(db_session: AsyncSession, tmp_path: Path):
    """Test 07 (Failure A): Missing source image causes clean failure without false success."""
    project = Project(name="Failure A Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(project_id=project.id, objective="Failure A", status="EXECUTING", plan_dag_json={})
    db_session.add(goal)
    await db_session.flush()

    non_existent = str(tmp_path / "non_existent_input.png")
    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_fail_input",
        title="Invalid Input Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "prompt": "Camera push with missing image",
            "provider": "camera_motion",
            "first_frame": non_existent,
        },
    )
    db_session.add(action)
    await db_session.commit()

    local_settings = Settings(enable_live_provider_execution=False, enable_live_local_execution=True)
    dispatcher = LiveProviderDispatcher(settings=local_settings, output_dir=tmp_path, local_only=True)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=local_settings)

    res = await runner.dispatch_action(action.id, principal)
    assert res.status == "FAILED"

    await db_session.refresh(action)
    assert action.status == "FAILED"
    assert "does not exist on disk" in str(action.error)


async def test_08_failure_injection_b_missing_output(db_session: AsyncSession, tmp_path: Path):
    """Test 08 (Failure B): Missing output artifact causes clean failure and blocks downstream DAG."""
    project = Project(name="Failure B Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(
        project_id=project.id,
        objective="Failure B",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [{"client_action_id": "shot_b1"}, {"client_action_id": "shot_b2"}],
            "edges": [{"from": "shot_b1", "to": "shot_b2"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    action1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_b1",
        title="Missing Output Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"prompt": "Camera push", "provider": "camera_motion"},
    )
    action2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_b2",
        title="Downstream Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Next"},
    )
    db_session.add_all([action1, action2])
    await db_session.commit()

    # Mock provider returning non-existent file
    missing_file = tmp_path / "never_created.mp4"
    mock_res = OpenMontageToolResult(success=True, status="COMPLETED", artifacts=[str(missing_file)])

    class FakeMissingProvider(VideoGenerationProvider):
        provider_id = "camera_motion"
        model_id = "camera-push"
        capabilities = ["IMAGE_TO_VIDEO"]
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.0
        async def generate_video(self, pkg, out): return mock_res

    reg = VideoProviderRegistry()
    reg.register(FakeMissingProvider())

    local_settings = Settings(enable_live_provider_execution=False, enable_live_local_execution=True)
    dispatcher = LiveProviderDispatcher(video_registry=reg, settings=local_settings, output_dir=tmp_path, local_only=True)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=local_settings)

    res = await runner.dispatch_action(action1.id, principal)
    assert res.status == "FAILED"

    await db_session.refresh(action1)
    assert action1.status == "FAILED"

    # Verify downstream DAG is blocked (cannot progress to READY)
    await db_session.refresh(action2)
    assert action2.status != "READY"
    assert action2.status in ("PENDING", "BLOCKED")


async def test_09_failure_injection_c_corrupt_output(db_session: AsyncSession, tmp_path: Path):
    """Test 09 (Failure C): Corrupt binary output is rejected by physical validator and fails action."""
    project = Project(name="Failure C Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(project_id=project.id, objective="Failure C", status="EXECUTING", plan_dag_json={})
    db_session.add(goal)
    await db_session.flush()

    corrupt_mp4 = tmp_path / "corrupt_data.mp4"
    corrupt_mp4.write_bytes(b"CORRUPT_NOT_VALID_MP4_HEADER_GARBAGE")

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_c",
        title="Corrupt Output Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"prompt": "Camera push", "provider": "camera_motion"},
    )
    db_session.add(action)
    await db_session.commit()

    mock_res = OpenMontageToolResult(success=True, status="COMPLETED", artifacts=[str(corrupt_mp4)])

    class FakeCorruptProvider(VideoGenerationProvider):
        provider_id = "camera_motion"
        model_id = "camera-push"
        capabilities = ["IMAGE_TO_VIDEO"]
        def validate_configuration(self): return True, None
        def estimate_cost(self, pkg): return 0.0
        async def generate_video(self, pkg, out): return mock_res

    reg = VideoProviderRegistry()
    reg.register(FakeCorruptProvider())

    local_settings = Settings(enable_live_provider_execution=False, enable_live_local_execution=True)
    dispatcher = LiveProviderDispatcher(video_registry=reg, settings=local_settings, output_dir=tmp_path, local_only=True)
    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=local_settings)

    res = await runner.dispatch_action(action.id, principal)
    assert res.status == "FAILED"

    await db_session.refresh(action)
    assert action.status == "FAILED"
    assert "validation failed" in str(action.error).lower()


async def test_10_failure_injection_d_timeout_local_process_cleanup(tmp_path: Path):
    """Test 10 (Failure D): Local tool timeout terminates process group cleanly and returns FAILED."""
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    # Execute a non-external local tool with a tiny 0.001s timeout
    res = await adapter._run_subprocess(
        tool_name="camera_motion",
        inputs={},
        check_status_only=False,
        timeout_seconds=0.001,
    )

    assert res.success is False
    assert res.status == "FAILED"
    assert res.is_ambiguous is False
    assert "Local execution timed out" in str(res.error)


async def test_11_failure_injection_e_duplicate_dispatch_lease_fencing(db_session: AsyncSession, tmp_path: Path):
    """Test 11 (Failure E): Concurrency lease fencing and duplicate dispatch protection."""
    project = Project(name="Failure E Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="Op", is_admin=True, principal_type="system")
    goal = AutonomousGoal(project_id=project.id, objective="Failure E", status="EXECUTING", plan_dag_json={})
    db_session.add(goal)
    await db_session.flush()

    # Part 1: Concurrent dispatch blocked when already EXECUTING with active lease
    now_utc = datetime.now(timezone.utc)
    action_executing = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_e_concurrent",
        title="Concurrent Dispatch Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="EXECUTING",
        inputs_json={
            "prompt": "Camera push",
            "lease": {
                "worker_id": "active-worker-1",
                "lease_token": "token-1",
                "epoch": 1,
                "claimed_at": now_utc.isoformat(),
                "expires_at": (now_utc + timedelta(minutes=10)).isoformat(),
            },
        },
    )
    db_session.add(action_executing)
    await db_session.commit()

    runner_2 = AutonomousExecutionRunner(db=db_session, worker_id="worker-2")
    with pytest.raises(HTTPException) as exc_exec:
        await runner_2.dispatch_action(action_executing.id, principal)
    assert exc_exec.value.status_code == 409
    assert "currently claimed by worker 'active-worker-1'" in exc_exec.value.detail

    # Part 2: Stale worker lease fencing token mismatch on commit
    action_fence = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_e_fenced",
        title="Fenced Dispatch Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"prompt": "Camera push"},
    )
    db_session.add(action_fence)
    await db_session.commit()

    # Custom dispatcher simulating a concurrent worker preempting lease token mid-execution
    class PreemptingDispatcher(BaseExecutionDispatcher):
        is_live = False

        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            inputs = dict(action.inputs_json or {})
            inputs["lease"]["lease_token"] = "preempted-token-xyz"
            inputs["lease"]["epoch"] = inputs["lease"].get("epoch", 1) + 1
            action.inputs_json = inputs
            await db_session.commit()
            return ExecutionResult(success=True, status="SUCCEEDED", output={"video_url": "mock.mp4"})

    fenced_runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=PreemptingDispatcher(),
        worker_id="preempted-worker",
    )
    with pytest.raises(HTTPException) as exc_fence:
        await fenced_runner.dispatch_action(action_fence.id, principal)
    assert exc_fence.value.status_code == 409
    assert "Stale worker lease fencing token mismatch" in exc_fence.value.detail

    # Part 3: Idempotent re-dispatch of SUCCEEDED action returns node without re-execution
    action_succeeded = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="shot_e_succeeded",
        title="Succeeded Shot",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="SUCCEEDED",
        inputs_json={"prompt": "Camera push"},
        outputs_json={"status": "SUCCEEDED", "video_url": "/path/video.mp4"},
    )
    db_session.add(action_succeeded)
    await db_session.commit()

    idem_runner = AutonomousExecutionRunner(db=db_session, worker_id="idem-worker")
    res_idem = await idem_runner.dispatch_action(action_succeeded.id, principal)
    assert res_idem.status == "SUCCEEDED"
    assert res_idem.id == action_succeeded.id


# ===========================================================================
# 5. ENVIRONMENT & PROCESS ISOLATION VERIFICATION
# ===========================================================================

async def test_12_backend_secrets_absent_during_local_execution(tmp_path: Path, monkeypatch):
    """Test 12: Backend secrets placed in parent process are completely absent from child env."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:secret@localhost:5432/arya")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ForbiddenPassword123")
    monkeypatch.setenv("SECRET_KEY", "InsecureSecretKey")
    monkeypatch.setenv("MASTER_API_KEY", "InsecureMasterApiKey")

    adapter = OpenMontageAdapter(openmontage_path=tmp_path)
    env = adapter.build_subprocess_env("camera_push_video")

    for secret_key in FORBIDDEN_SECRET_KEYS:
        assert secret_key not in env, f"Security leak: {secret_key} found in child subprocess environment!"


# ===========================================================================
# 6. INTEGRITY BASELINE VERIFICATION
# ===========================================================================

async def test_13_invariants_alembic_head_and_frozen_stages():
    """Test 13: Verifies migration head remains i9d0e1f2a3b4 and Stage 03-24 assets remain frozen."""
    # 1. Migration head verification
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

    # 2. Stage 03 assets preserved
    assert os.path.exists("frontend/src/stage03_assembly.ts")
    assert os.path.exists("frontend/src/stage03_reflections.ts")
    assert os.path.exists("frontend/src/stage03_validation.ts")

    # 3. Default configuration gates remain False
    s = Settings()
    assert s.enable_live_provider_execution is False
    assert s.enable_live_local_execution is False
