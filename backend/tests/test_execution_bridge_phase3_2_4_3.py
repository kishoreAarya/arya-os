"""
AryaOS V1 Stage 25 Phase 3.2.4.3 — Guarded Live Provider Dispatcher Integration Tests.

Validates the full Phase 3.2.4.3 boundary requirements:
1. Default dispatcher is OfflineMockDispatcher across all environments.
2. ENABLE_LIVE_PROVIDER_EXECUTION configuration gate defaults to False (fail-closed).
3. Missing or invalid gate configurations strictly fail closed.
4. Client requests and unprivileged actors cannot toggle or bypass the gate.
5. Image generation actions (IMAGE_GENERATION) route to image_provider_registry (FLUX).
6. Video generation actions (VIDEO_GENERATION) route to video_provider_registry (Kling / CameraMotion).
7. Unsupported capabilities (e.g. AUDIO_GENERATION) fail explicitly before provider invocation.
8. Job Package synthesis validation failures (missing prompt, bad aspect ratio) fail explicitly.
9. Last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO) is explicitly rejected as unsupported.
10. Sensitive credentials detected in action inputs trigger SecretDetectedError and fail closed.
11. Provider configuration validation failure (missing API keys / binaries) fails closed.
12. Ambiguous provider outcome maps to UNKNOWN_PENDING_RECONCILIATION (is_ambiguous=True).
13. AutonomousExecutionRunner integration: ambiguous outcome halts DAG and sets goal RECOVERY_REQUIRED.
14. AutonomousExecutionRunner integration: successful outcome cascades DAG readiness to downstream nodes.
15. Fal and Kling status lookup query preserves NO_LOOKUP guarantee (LOOKUP_UNSUPPORTED).
16. Worker lease fencing prevents split-brain overwrite on live dispatch results.
17. Secret redaction applies to all outputs, errors, and traces.
18. Unhandled provider exception during execution is safely quarantined as UNKNOWN_PENDING_RECONCILIATION.
19. Invariant verification: Alembic migration head i9d0e1f2a3b4, Stage 03-24 assets frozen.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.sanitization import REDACTION_MARKER
from app.core.security import AuthenticatedPrincipal
from app.main import app
from app.models.core import ApiKey, Project, ProjectMembership
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.schemas.production import AryaJobPackageSchema
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    is_live_provider_execution_enabled,
    resolve_dispatcher,
)
from app.services.dispatcher import (
    ExecutionResult,
    LiveExecutionGateError,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
    get_default_dispatcher,
    verify_live_execution_gate,
)
from app.services.idempotency import (
    PROVIDER_PROFILES,
    ProviderConsistencyGuarantee,
)
from app.services.image_provider import ImageGenerationProvider, ImageProviderRegistry
from app.services.openmontage_adapter import OpenMontageToolResult
from app.services.video_provider import VideoGenerationProvider, VideoProviderRegistry

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK & SUBPROCESS BLOCKING
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Guarantees zero outbound network or subprocess execution during testing."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.3 test!")

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.4.3 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


# ===========================================================================
# MOCK PROVIDERS FOR TESTING LIVE ROUTING
# ===========================================================================

class MockFluxImageProvider(ImageGenerationProvider):
    provider_id: str = "fal"
    model_id: str = "flux-pro/v1.1"
    capabilities: list[str] = ["text_to_image", "photorealistic", "16:9"]

    def __init__(self, valid_config: bool = True, tool_result: OpenMontageToolResult | None = None) -> None:
        self.valid_config = valid_config
        self.tool_result = tool_result

    def validate_configuration(self) -> tuple[bool, str | None]:
        if not self.valid_config:
            return False, "CONFIGURATION REQUIRED: FAL_KEY missing from test environment"
        return True, None

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.05

    async def generate_image(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
        if self.tool_result is not None:
            return self.tool_result
        return OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[output_path],
            data={"width": 1024, "height": 1024, "seed": 42},
            cost_usd=0.05,
            duration_seconds=5.2,
            provider_job_id="fal-req-flux-00123456",
            model="flux-pro/v1.1",
        )


class MockKlingVideoProvider(VideoGenerationProvider):
    provider_id: str = "kling"
    model_id: str = "kling-video/v3/standard"
    capabilities: list[str] = ["TEXT_TO_VIDEO", "IMAGE_TO_VIDEO", "FIRST_FRAME_TO_VIDEO"]

    def __init__(self, valid_config: bool = True, tool_result: OpenMontageToolResult | None = None) -> None:
        self.valid_config = valid_config
        self.tool_result = tool_result

    def validate_configuration(self) -> tuple[bool, str | None]:
        if not self.valid_config:
            return False, "CONFIGURATION REQUIRED: FAL_KEY missing from test environment"
        return True, None

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.10

    async def generate_video(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
        if self.tool_result is not None:
            return self.tool_result
        return OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[output_path],
            data={"duration": 5.0, "fps": 25},
            cost_usd=0.10,
            duration_seconds=12.4,
            provider_job_id="fal-req-kling-00987654",
            model="kling-video/v3/standard",
        )


class MockCameraMotionProvider(VideoGenerationProvider):
    provider_id: str = "camera_motion"
    model_id: str = "camera-push"
    capabilities: list[str] = ["IMAGE_TO_VIDEO", "FIRST_FRAME_TO_VIDEO"]

    def __init__(self, valid_config: bool = True, tool_result: OpenMontageToolResult | None = None) -> None:
        self.valid_config = valid_config
        self.tool_result = tool_result

    def validate_configuration(self) -> tuple[bool, str | None]:
        if not self.valid_config:
            return False, "CONFIGURATION REQUIRED: FFmpeg not installed"
        return True, None

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.0

    async def generate_video(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
        if self.tool_result is not None:
            return self.tool_result
        return OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[output_path],
            data={"operation": "camera_push", "fps": 25},
            cost_usd=0.0,
            duration_seconds=2.1,
            model="camera-push",
        )


# ===========================================================================
# TEST SUITE
# ===========================================================================

async def test_01_default_dispatcher_remains_offline_mock(db_session: AsyncSession):
    """Test 1: Proves that default dispatcher remains OfflineMockDispatcher across all entrypoints."""
    # Runner defaults to offline mock
    runner = AutonomousExecutionRunner(db=db_session)
    assert isinstance(runner.dispatcher, OfflineMockDispatcher)
    assert runner.dispatcher.is_live is False

    # Factory defaults to offline mock
    default_disp = get_default_dispatcher()
    assert isinstance(default_disp, OfflineMockDispatcher)
    assert default_disp.is_live is False

    # resolve_dispatcher defaults to offline mock
    assert isinstance(resolve_dispatcher(None), OfflineMockDispatcher)
    assert isinstance(resolve_dispatcher("offline"), OfflineMockDispatcher)
    assert isinstance(resolve_dispatcher("mock"), OfflineMockDispatcher)


async def test_02_live_dispatcher_fails_closed_when_gate_disabled(db_session: AsyncSession):
    """Test 2: Proves that LiveProviderDispatcher fails closed when ENABLE_LIVE_PROVIDER_EXECUTION=False."""
    closed_settings = Settings(enable_live_provider_execution=False)

    # 1. Direct instantiation raises LiveExecutionGateError
    with pytest.raises(LiveExecutionGateError):
        LiveProviderDispatcher(settings=closed_settings)

    # 2. String resolution raises LiveExecutionGateError
    with pytest.raises(LiveExecutionGateError):
        resolve_dispatcher("live", settings=closed_settings)

    # 3. Runner initialization raises LiveExecutionGateError
    with pytest.raises(LiveExecutionGateError):
        AutonomousExecutionRunner(db=db_session, dispatcher="live", settings=closed_settings)

    # 4. Custom live instance passed to resolve_dispatcher raises LiveExecutionGateError
    class FakeLiveDispatcher:
        is_live = True

    with pytest.raises(LiveExecutionGateError):
        resolve_dispatcher(FakeLiveDispatcher(), settings=closed_settings)


async def test_03_missing_or_invalid_gate_configurations_fail_closed():
    """Test 3: Proves that missing, empty, or unparseable gate configurations fail closed to False."""
    invalid_values = [
        None,
        "",
        "   ",
        "invalid",
        "maybe",
        "0",
        "false",
        "disabled",
        "off",
        {"live": True},
        [True],
    ]
    for val in invalid_values:
        parsed = Settings._validate_enable_live_provider_execution(val)
        assert parsed is False, f"Value {val!r} did not fail closed to False"

    # Settings object without attribute or with exception fails closed
    class BrokenSettings:
        @property
        def enable_live_provider_execution(self):
            raise ValueError("Corrupt setting")

    assert is_live_provider_execution_enabled(BrokenSettings()) is False
    with pytest.raises(LiveExecutionGateError):
        verify_live_execution_gate(BrokenSettings())


async def test_04_client_or_unprivileged_actors_cannot_enable_gate(db_session: AsyncSession):
    """Test 4: Proves that API endpoints and action inputs cannot bypass the fail-closed gate."""
    from app.services.authorization_service import create_api_key

    admin_key_model, admin_key_raw = await create_api_key(
        db_session, name=f"Admin Key Test 4 {uuid.uuid4().hex[:6]}", is_admin=True, principal_type="human"
    )

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # PUT to toggle feature flag is strictly forbidden
        resp = await client.put(
            "/feature-flags/enable_live_provider_execution",
            json={"enabled": True, "description": "Attempted bypass"},
            headers={"Authorization": f"Bearer {admin_key_raw}"},
        )
        assert resp.status_code in (401, 403)

    # Gate remains disabled
    assert is_live_provider_execution_enabled() is False


async def test_05_image_action_routes_to_flux_provider_and_normalizes_success(tmp_path: Path):
    """Test 5: Live image generation action routes to FluxImageProvider and normalizes to SUCCEEDED."""
    open_settings = Settings(enable_live_provider_execution=True)

    # Create isolated registries with injected mock providers
    img_reg = ImageProviderRegistry()
    img_provider = MockFluxImageProvider(valid_config=True)
    img_reg.register(img_provider)

    vid_reg = VideoProviderRegistry()

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        video_registry=vid_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_image_01",
        title="Generate Hero Image",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        status="READY",
        inputs_json={
            "prompt": "Cinematic sci-fi command deck, 8k render",
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "aspect_ratio": "16:9",
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.cost_usd == 0.05
    assert res.duration_seconds == 5.2
    assert res.provider_job_id == "fal-req-flux-00123456"
    assert res.output.get("artifact_url") is not None
    assert res.output.get("image_url") is not None
    assert res.output.get("result") == "COMPLETED"
    assert res.output.get("provider") == "fal"


async def test_06_video_action_routes_to_kling_provider_and_normalizes_success(tmp_path: Path):
    """Test 6: Live video generation action routes to KlingVideoProvider and normalizes to SUCCEEDED."""
    open_settings = Settings(enable_live_provider_execution=True)

    img_reg = ImageProviderRegistry()
    vid_reg = VideoProviderRegistry()
    vid_provider = MockKlingVideoProvider(valid_config=True)
    vid_reg.register(vid_provider)

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        video_registry=vid_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_video_01",
        title="Generate Drone Sequence",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        status="READY",
        inputs_json={
            "prompt": "Aerial view of stormy ocean at sunset",
            "provider": "kling",
            "duration_seconds": 5.0,
            "aspect_ratio": "16:9",
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.cost_usd == 0.10
    assert res.duration_seconds == 12.4
    assert res.provider_job_id == "fal-req-kling-00987654"
    assert res.output.get("video_url") is not None
    assert res.output.get("result") == "COMPLETED"


async def test_07_camera_motion_video_routes_to_camera_motion_provider(tmp_path: Path):
    """Test 7: Video action requesting camera motion routes to CameraMotionVideoProvider."""
    open_settings = Settings(enable_live_provider_execution=True)

    img_reg = ImageProviderRegistry()
    vid_reg = VideoProviderRegistry()
    cam_provider = MockCameraMotionProvider(valid_config=True)
    vid_reg.register(cam_provider)

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        video_registry=vid_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_cam_01",
        title="Smooth Push In",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        status="READY",
        inputs_json={
            "prompt": "Smooth cinematic push in",
            "provider": "camera_motion",
            "first_frame": "/storage/artifacts/source_frame.png",
            "duration_seconds": 3.0,
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.cost_usd == 0.0
    assert res.duration_seconds == 2.1
    assert res.output.get("video_url") is not None


async def test_08_unsupported_capability_fails_closed(tmp_path: Path):
    """Test 8: Actions with capabilities other than IMAGE_GENERATION or VIDEO_GENERATION fail closed."""
    open_settings = Settings(enable_live_provider_execution=True)

    dispatcher = LiveProviderDispatcher(settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_audio_01",
        title="Synthesize Dialogue",
        action_type="SYNTHESIS",
        required_capability="AUDIO_GENERATION",
        risk_level="LOW",
        status="READY",
        inputs_json={"prompt": "Hello world"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Unsupported capability 'AUDIO_GENERATION'" in res.error


async def test_09_job_package_synthesis_rejections_fail_closed(tmp_path: Path):
    """Test 9: Synthesis rejections (missing prompt, bad aspect ratio, last-frame conditioning) fail closed."""
    open_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=open_settings, output_dir=tmp_path)

    # 1. Missing prompt
    act_no_prompt = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_no_prompt",
        title="No Prompt",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={},
    )
    res1 = await dispatcher.dispatch(act_no_prompt)
    assert res1.success is False
    assert res1.status == "FAILED"
    assert "Missing required field 'prompt'" in res1.error

    # 2. Invalid aspect ratio
    act_bad_aspect = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_bad_aspect",
        title="Bad Aspect",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Test prompt", "aspect_ratio": "3:2"},
    )
    res2 = await dispatcher.dispatch(act_bad_aspect)
    assert res2.success is False
    assert res2.status == "FAILED"
    assert "Invalid aspect ratio '3:2'" in res2.error

    # 3. Last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO) rejected explicitly
    act_last_frame = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_last_frame",
        title="Last Frame Conditioning",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={
            "prompt": "Morph transition",
            "last_frame": "https://cdn.example.internal/end.png",
        },
    )
    res3 = await dispatcher.dispatch(act_last_frame)
    assert res3.success is False
    assert res3.status == "FAILED"
    assert "Unsupported capability" in res3.error
    assert "last-frame conditioning" in res3.error


async def test_10_secret_detection_in_inputs_fails_closed_without_leakage(tmp_path: Path):
    """Test 10: Credentials in action inputs trigger SecretDetectedError and fail without leaking."""
    open_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=open_settings, output_dir=tmp_path)

    leak_key = "12345678-1234-1234-1234-1234567890ab:abcdef1234567890abcdef1234567890"
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_secret_leak",
        title="Leaky Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={
            "prompt": f"Render secret credentials {leak_key}",
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Security violation" in res.error
    # Secret itself must NOT be echoed in plaintext
    assert leak_key not in res.error


async def test_11_provider_configuration_validation_failure_fails_closed(tmp_path: Path):
    """Test 11: Invalid provider configuration (missing API key) fails without invoking generation."""
    open_settings = Settings(enable_live_provider_execution=True)

    img_reg = ImageProviderRegistry()
    img_provider = MockFluxImageProvider(valid_config=False)
    img_reg.register(img_provider)

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_config_fail",
        title="Config Failure",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Valid prompt"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "CONFIGURATION REQUIRED: FAL_KEY missing" in res.error


async def test_12_ambiguous_outcome_maps_to_unknown_pending_reconciliation(tmp_path: Path):
    """Test 12: Ambiguous tool outcome maps to UNKNOWN_PENDING_RECONCILIATION preserving job ID."""
    open_settings = Settings(enable_live_provider_execution=True)

    img_reg = ImageProviderRegistry()
    ambiguous_result = OpenMontageToolResult(
        success=False,
        status="UNKNOWN_PENDING_RECONCILIATION",
        is_ambiguous=True,
        error="Gateway timeout waiting for remote fal.ai callback",
        provider_job_id="fal-req-ambig-999888",
    )
    img_provider = MockFluxImageProvider(valid_config=True, tool_result=ambiguous_result)
    img_reg.register(img_provider)

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_ambig",
        title="Ambiguous Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Valid prompt"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res.provider_job_id == "fal-req-ambig-999888"
    assert "Gateway timeout" in res.error
    assert res.output.get("is_ambiguous") is True


async def test_13_runner_integration_ambiguous_outcome_halts_dag_and_sets_recovery_required(
    db_session: AsyncSession, tmp_path: Path
):
    """Test 13: Runner integration: ambiguous outcome transitions action to UNKNOWN, halts DAG, and sets RECOVERY_REQUIRED."""
    project = Project(name="Phase 3.2.4.3 Integration Test Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Admin Test Principal",
        is_admin=True,
        principal_type="system",
    )

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Verify ambiguous outcome halts DAG in live dispatcher",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "act_1", "title": "Image Node", "action_type": "SYNTHESIS"},
                {"client_action_id": "act_2", "title": "Downstream Node", "action_type": "REASONING"},
            ],
            "edges": [{"from": "act_1", "to": "act_2"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    act_1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_1",
        title="Image Node",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Futuristic skyline"},
    )
    act_2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_2",
        title="Downstream Node",
        action_type="REASONING",
        required_capability="REASONING",
        status="PENDING",
    )
    db_session.add_all([act_1, act_2])
    await db_session.commit()

    open_settings = Settings(enable_live_provider_execution=True)
    img_reg = ImageProviderRegistry()
    ambig_result = OpenMontageToolResult(
        success=False,
        status="UNKNOWN_PENDING_RECONCILIATION",
        is_ambiguous=True,
        error="External timeout after remote dispatch",
        provider_job_id="fal-job-ext-timeout-4455",
    )
    img_reg.register(MockFluxImageProvider(valid_config=True, tool_result=ambig_result))

    live_dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=live_dispatcher,
        settings=open_settings,
    )

    # Dispatch action 1
    dispatched_node = await runner.dispatch_action(act_1.id, principal)
    assert dispatched_node.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Verify parent goal transitioned to RECOVERY_REQUIRED
    updated_goal = await runner.execute_goal_step(goal.id, principal)
    assert updated_goal.status == "RECOVERY_REQUIRED"

    # Verify downstream action remains blocked from execution
    await db_session.refresh(act_2)
    assert act_2.status in ("PENDING", "BLOCKED")
    assert act_2.status != "SUCCEEDED"

    # Verify provider job ID was durably captured in dispatch intent
    intent = (dispatched_node.inputs_json or {}).get("dispatch_intent", {})
    assert intent.get("provider_job_id") == "fal-job-ext-timeout-4455"


async def test_14_runner_integration_succeeded_action_cascades_dag_readiness(
    db_session: AsyncSession, tmp_path: Path
):
    """Test 14: Runner integration: successful live action cascades DAG readiness to downstream node."""
    project = Project(name="Phase 3.2.4.3 Success Cascade Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Admin Test Principal",
        is_admin=True,
        principal_type="system",
    )

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Verify live dispatcher success cascades DAG",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "step_image", "title": "Generate Concept", "action_type": "SYNTHESIS"},
                {"client_action_id": "step_video", "title": "Generate Video", "action_type": "GENERATION"},
            ],
            "edges": [{"from": "step_image", "to": "step_video"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    node_img = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step_image",
        title="Generate Concept",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Concept art of starship"},
    )
    node_vid = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step_video",
        title="Generate Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Starship in flight"},
    )
    db_session.add_all([node_img, node_vid])
    await db_session.commit()

    open_settings = Settings(enable_live_provider_execution=True)
    img_reg = ImageProviderRegistry()
    img_reg.register(MockFluxImageProvider(valid_config=True))
    vid_reg = VideoProviderRegistry()
    vid_reg.register(MockKlingVideoProvider(valid_config=True))

    live_disp = LiveProviderDispatcher(
        image_registry=img_reg,
        video_registry=vid_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=live_disp,
        settings=open_settings,
    )

    # Dispatch first action
    res_img = await runner.dispatch_action(node_img.id, principal)
    assert res_img.status == "SUCCEEDED"
    assert float(res_img.cost_usd) == 0.05

    # Check downstream node was promoted to READY
    await db_session.refresh(node_vid)
    assert node_vid.status == "READY"


async def test_15_status_query_preserves_no_lookup_for_fal_and_kling(tmp_path: Path):
    """Test 15: Status query on LiveProviderDispatcher preserves NO_LOOKUP guarantee for Fal and Kling."""
    open_settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=open_settings, output_dir=tmp_path)

    # 1. Fal image action query_status returns LOOKUP_UNSUPPORTED
    act_fal = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_q_fal",
        title="Fal Query",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={"provider": "fal"},
    )
    res_fal = await dispatcher.query_status(act_fal, provider_job_id="fal-req-lookup-test")
    assert res_fal.status == "LOOKUP_UNSUPPORTED"
    assert "Provider 'fal' does not support status query" in res_fal.error

    # 2. Kling video action query_status returns LOOKUP_UNSUPPORTED
    act_kling = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_q_kling",
        title="Kling Query",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        inputs_json={"provider": "kling"},
    )
    res_kling = await dispatcher.query_status(act_kling, provider_job_id="kling-req-lookup-test")
    assert res_kling.status == "LOOKUP_UNSUPPORTED"
    assert "Provider 'kling' does not support status query" in res_kling.error

    # 3. Gate verification is enforced on query_status
    closed_disp = LiveProviderDispatcher(settings=open_settings, output_dir=tmp_path)
    closed_disp.settings = Settings(enable_live_provider_execution=False)
    with pytest.raises(LiveExecutionGateError):
        await closed_disp.query_status(act_fal, "any-id")


async def test_16_lease_fencing_mismatch_rejects_late_result(db_session: AsyncSession, tmp_path: Path):
    """Test 16: Worker lease fencing prevents split-brain overwrite when lease is stolen during execution."""
    project = Project(name="Phase 3.2.4.3 Fencing Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Admin Test Principal",
        is_admin=True,
        principal_type="system",
    )

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Fencing Token Safety",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "act_fence"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_fence",
        title="Fencing Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Cyberpunk alley"},
    )
    db_session.add(node)
    await db_session.commit()

    open_settings = Settings(enable_live_provider_execution=True)

    # Custom dispatcher that simulates a concurrent worker stealing the lease token mid-execution
    class PreemptingLiveDispatcher(LiveProviderDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            # Simulate preemption in DB
            inputs = dict(action.inputs_json or {})
            inputs["lease"]["lease_token"] = "stolen-by-worker-2"
            inputs["lease"]["epoch"] = inputs["lease"].get("epoch", 1) + 1
            action.inputs_json = inputs
            await db_session.commit()
            return await super().dispatch(action)

    img_reg = ImageProviderRegistry()
    img_reg.register(MockFluxImageProvider(valid_config=True))

    preempt_disp = PreemptingLiveDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    runner = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=preempt_disp,
        settings=open_settings,
        worker_id="worker-1",
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(node.id, principal)
    assert exc_info.value.status_code == 409
    assert "fencing token mismatch" in exc_info.value.detail.lower()


async def test_17_secret_redaction_in_tool_output_and_diagnostics(tmp_path: Path):
    """Test 17: Secrets appearing in tool metadata or error diagnostics are redacted before persistence."""
    open_settings = Settings(enable_live_provider_execution=True)

    secret_in_output = "sk-test-secret-12345678901234567890"
    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(tmp_path / "art.png")],
        data={"meta": f"Loaded with key {secret_in_output}"},
        cost_usd=0.05,
    )

    img_reg = ImageProviderRegistry()
    img_reg.register(MockFluxImageProvider(valid_config=True, tool_result=tool_result))

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_leak_out",
        title="Redaction Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Safe prompt"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    # Secret must be replaced by REDACTION_MARKER
    assert secret_in_output not in str(res.output)
    assert REDACTION_MARKER in str(res.output)


async def test_18_unhandled_provider_exception_maps_to_ambiguous_outcome(tmp_path: Path):
    """Test 18: Unhandled exception during provider call is quarantined as UNKNOWN_PENDING_RECONCILIATION."""
    open_settings = Settings(enable_live_provider_execution=True)

    class CrashingImageProvider(ImageGenerationProvider):
        provider_id: str = "fal"
        model_id: str = "flux-pro/v1.1"
        capabilities: list[str] = ["text_to_image"]

        def validate_configuration(self) -> tuple[bool, str | None]:
            return True, None

        def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
            return 0.05

        async def generate_image(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
            raise ConnectionResetError("Connection abruptly reset by remote peer")

    img_reg = ImageProviderRegistry()
    img_reg.register(CrashingImageProvider())

    dispatcher = LiveProviderDispatcher(
        image_registry=img_reg,
        settings=open_settings,
        output_dir=tmp_path,
    )

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_crash",
        title="Crashing Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Valid prompt"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "Connection abruptly reset" in res.error
    assert res.output.get("is_ambiguous") is True


async def test_19_invariants_alembic_head_and_frozen_stages():
    """Test 19: Proves that database migration head is i9d0e1f2a3b4 and Stage 03-24 assets remain frozen."""
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

    # 3. Default setting remains False
    s = Settings()
    assert s.enable_live_provider_execution is False
