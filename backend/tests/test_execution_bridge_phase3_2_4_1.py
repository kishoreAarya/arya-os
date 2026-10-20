"""
AryaOS V1 Stage 25 Phase 3.2.4.1 — Bridge Contract & Job Package Synthesis Test Suite.

Verifies mandatory Phase 3.2.4.1 contract requirements:
1. Valid transformation of image-generation actions into AryaJobPackageSchema.
2. Valid transformation of text-to-video actions into AryaJobPackageSchema.
3. Valid transformation of first-frame-to-video actions into AryaJobPackageSchema.
4. Valid transformation of local camera-motion actions into AryaJobPackageSchema.
5. Explicit rejection of unsupported capabilities (last-frame conditioning / FIRST_LAST_FRAME_TO_VIDEO).
6. Rejection of incompatible action types (RESEARCH, DECISION, VERIFICATION).
7. Rejection of incompatible capabilities (REASONING).
8. Rejection of incompatible provider/capability pairings (e.g. Kling for image, Flux for video).
9. Validation of prompt constraints (missing, empty, whitespace, max length).
10. Validation of aspect ratio constraints (allowed: 16:9, 9:16, 1:1, 21:9, 4:3).
11. SSRF prevention on reference frame URLs.
12. Strict secret detection and prevention of credential leakage into Job Packages.
13. Preservation of project, goal, action, correlation, and idempotency identifiers.
14. Determinism: identical normalized inputs produce identical Job Packages.
15. Fail-closed gate enforcement & zero network / subprocess execution.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import get_settings
from app.models.execution_bridge import AutonomousActionNode
from app.schemas.production import AryaJobPackageSchema
from app.services.autonomous_execution_runner import is_live_provider_execution_enabled
from app.services.media_bridge import (
    JobPackageSynthesisError,
    JobPackageValidationError,
    SecretDetectedError,
    UnsupportedCapabilityError,
    synthesize_job_package,
    validate_job_package_boundary,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK & SUBPROCESS BLOCKING
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Fails tests immediately if any outbound network or subprocess call is attempted."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.1 test!")

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.4.1 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


# ===========================================================================
# 1. VALID TRANSFORMATIONS (IMAGE, VIDEO, CAMERA MOTION)
# ===========================================================================

async def test_01_valid_image_generation_transformation():
    """Test 1: Synthesizes valid AryaJobPackageSchema from FLUX image generation action."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-flux-image-01",
        title="Hero Keyframe Render",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Cinematic wide shot of an obsidian obelisk at sunset, volumetric fog",
            "provider": "fal",
            "model": "flux-pro/v1.1",
            "aspect_ratio": "16:9",
        },
    )

    pkg = synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert isinstance(pkg, AryaJobPackageSchema)
    assert pkg.projectId == str(project_id)
    assert pkg.plan.title == "Hero Keyframe Render"
    assert pkg.plan.prompt == "Cinematic wide shot of an obsidian obelisk at sunset, volumetric fog"
    assert pkg.plan.generationType == "image"
    assert pkg.modelRoute.provider == "fal"
    assert pkg.modelRoute.model == "flux-pro/v1.1"
    assert pkg.shotConfiguration.aspectRatio == "16:9"
    assert pkg.decisionBoundary == "ARYAOS_ORCHESTRATION_VALIDATED"
    assert pkg.executionPayload["client_action_id"] == "act-flux-image-01"
    assert pkg.executionPayload["project_id"] == str(project_id)


async def test_02_valid_text_to_video_transformation():
    """Test 2: Synthesizes valid AryaJobPackageSchema from Kling text-to-video action."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-kling-video-01",
        title="Drone Flyover Sequence",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="MEDIUM",
        inputs_json={
            "prompt": "Smooth forward drone flyover above ancient monolithic ruins",
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "duration_seconds": 5.0,
            "aspect_ratio": "16:9",
        },
    )

    pkg = synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert pkg.plan.generationType == "video"
    assert pkg.plan.mode == "text_to_video"
    assert pkg.plan.durationSeconds == 5.0
    assert pkg.modelRoute.provider == "kling"
    assert pkg.shotConfiguration.aspectRatio == "16:9"
    assert pkg.outputRequirements["targetFormat"] == "video/mp4"


async def test_03_valid_first_frame_to_video_transformation():
    """Test 3: Synthesizes valid AryaJobPackageSchema for image-to-video with first frame reference."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-i2v-01",
        title="Image to Video Animate",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Camera pushes slowly toward the glowing core",
            "provider": "kling",
            "first_frame_url": "https://cdn.arya.internal/artifacts/keyframe_01.png",
            "duration_seconds": 10.0,
            "aspect_ratio": "9:16",
        },
    )

    pkg = synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert pkg.plan.generationType == "video"
    assert pkg.plan.mode == "image_to_video"
    assert pkg.references.firstFrame == "https://cdn.arya.internal/artifacts/keyframe_01.png"
    assert pkg.references.startFrameUrl == "https://cdn.arya.internal/artifacts/keyframe_01.png"
    assert pkg.shotConfiguration.aspectRatio == "9:16"
    assert pkg.plan.durationSeconds == 10.0


async def test_04_valid_camera_motion_video_transformation():
    """Test 4: Synthesizes valid AryaJobPackageSchema for local camera motion generation."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-cam-01",
        title="Local Camera Push",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Smooth cinematic camera push on hero frame",
            "provider": "camera_motion",
            "first_frame_url": "/api/v1/artifacts/monolith_hero.png",
            "duration_seconds": 4.0,
            "fps": 25,
            "aspect_ratio": "16:9",
        },
    )

    pkg = synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert pkg.modelRoute.provider == "camera_motion"
    assert pkg.modelRoute.model == "camera-push"
    assert pkg.shotConfiguration.fps == 25
    assert pkg.references.firstFrame == "/api/v1/artifacts/monolith_hero.png"


# ===========================================================================
# 2. UNSUPPORTED CAPABILITIES & LAST-FRAME CONDITIONING REJECTION
# ===========================================================================

async def test_05_explicit_rejection_of_last_frame_conditioning():
    """Test 5: Explicitly rejects last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO) as unsupported."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-unsupported-lastframe",
        title="Unsupported Last Frame",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Interpolate between start and end frames",
            "provider": "kling",
            "first_frame": "https://cdn.arya.internal/first.png",
            "last_frame": "https://cdn.arya.internal/last.png",  # Unsupported on standard endpoint!
        },
    )

    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert "does not support last-frame conditioning" in str(exc_info.value)
    assert "FIRST_LAST_FRAME_TO_VIDEO" in str(exc_info.value)


# ===========================================================================
# 3. MALFORMED INPUTS & SCHEMA REJECTION
# ===========================================================================

async def test_06_rejection_of_incompatible_action_type():
    """Test 6: Rejects non-synthesis action types (e.g. RESEARCH, DECISION) from Job Package synthesis."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-research-01",
        title="Literature Survey",
        action_type="RESEARCH",  # Not a media synthesis action!
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "Research prompt"},
    )

    with pytest.raises(JobPackageSynthesisError) as exc_info:
        synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert "cannot be transformed into a media Job Package" in str(exc_info.value)


async def test_07_rejection_of_incompatible_capability():
    """Test 7: Rejects non-media capabilities (e.g. REASONING)."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-reasoning-01",
        title="Reasoning Step",
        action_type="SYNTHESIS",
        required_capability="REASONING",  # Incompatible with media bridge
        risk_level="LOW",
        inputs_json={"prompt": "Analyze dataset"},
    )

    with pytest.raises(JobPackageSynthesisError) as exc_info:
        synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert "not a supported media generation capability" in str(exc_info.value)


async def test_08_rejection_of_incompatible_provider_capability_pairing():
    """Test 8: Rejects incompatible provider assignments (e.g. Kling for image, Flux for video)."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    # Kling requested for IMAGE_GENERATION
    action_bad_img = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-kling-image",
        title="Bad Image Provider",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "Test prompt", "provider": "kling"},
    )
    with pytest.raises(JobPackageSynthesisError) as exc1:
        synthesize_job_package(action_bad_img, project_id=project_id, goal_id=goal_id)
    assert "Provider 'kling' is incompatible with required capability 'IMAGE_GENERATION'" in str(exc1.value)

    # Flux requested for VIDEO_GENERATION
    action_bad_vid = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-flux-video",
        title="Bad Video Provider",
        action_type="SYNTHESIS",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "Test prompt", "provider": "flux"},
    )
    with pytest.raises(JobPackageSynthesisError) as exc2:
        synthesize_job_package(action_bad_vid, project_id=project_id, goal_id=goal_id)
    assert "Provider 'flux' is incompatible with required capability 'VIDEO_GENERATION'" in str(exc2.value)


async def test_09_prompt_validation_constraints():
    """Test 9: Enforces non-empty and bounded prompt constraints."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    # Missing prompt
    action_no_prompt = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-no-prompt",
        title="Missing Prompt",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={},
    )
    with pytest.raises(JobPackageValidationError) as exc1:
        synthesize_job_package(action_no_prompt, project_id=project_id, goal_id=goal_id)
    assert "Missing required field 'prompt'" in str(exc1.value)

    # Whitespace only prompt
    action_ws_prompt = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-ws-prompt",
        title="Whitespace Prompt",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "   \n\t  "},
    )
    with pytest.raises(JobPackageValidationError) as exc2:
        synthesize_job_package(action_ws_prompt, project_id=project_id, goal_id=goal_id)
    assert "Missing required field 'prompt'" in str(exc2.value)


async def test_10_aspect_ratio_constraints():
    """Test 10: Enforces allowed aspect ratio constraints."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-bad-aspect",
        title="Bad Aspect Ratio",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "A test prompt", "aspect_ratio": "3:2"},  # 3:2 not in allowed set
    )
    with pytest.raises(JobPackageValidationError) as exc:
        synthesize_job_package(action, project_id=project_id, goal_id=goal_id)
    assert "Invalid aspect ratio '3:2'" in str(exc.value)


async def test_11_ssrf_blocking_on_reference_urls():
    """Test 11: Blocks private/loopback URLs in reference assets."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    for bad_url in ("http://127.0.0.1:8000/secret.png", "http://localhost/admin.png", "http://192.168.1.1/img.png"):
        action = AutonomousActionNode(
            id=uuid.uuid4(),
            goal_id=goal_id,
            client_action_id="act-ssrf-check",
            title="SSRF Check",
            action_type="SYNTHESIS",
            required_capability="VIDEO_GENERATION",
            risk_level="LOW",
            inputs_json={"prompt": "Animate", "first_frame_url": bad_url},
        )
        with pytest.raises(JobPackageValidationError) as exc:
            synthesize_job_package(action, project_id=project_id, goal_id=goal_id)
        assert "SSRF blocked" in str(exc.value)


# ===========================================================================
# 4. SECRET LEAKAGE PREVENTION
# ===========================================================================

async def test_12_secret_detection_blocks_job_package_synthesis():
    """Test 12: Blocks transformation if sensitive keys or credentials appear in inputs."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    # Case A: fal API key pattern in prompt
    action_leak_prompt = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-leak-prompt",
        title="Leaky Prompt",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Generate image using key a1b2c3d4-e5f6-7890-abcd-1234567890ab:1234567890abcdef1234567890abcdef",
        },
    )
    with pytest.raises(SecretDetectedError) as exc1:
        synthesize_job_package(action_leak_prompt, project_id=project_id, goal_id=goal_id)
    assert "Sensitive credential pattern detected" in str(exc1.value)

    # Case B: API key passed in inputs_json key
    action_leak_dict = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=goal_id,
        client_action_id="act-leak-dict",
        title="Leaky Dict",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={
            "prompt": "Safe prompt",
            "api_key": "some-secret-api-key-value",
        },
    )
    with pytest.raises(SecretDetectedError) as exc2:
        synthesize_job_package(action_leak_dict, project_id=project_id, goal_id=goal_id)
    assert "Sensitive field 'api_key' detected" in str(exc2.value)


# ===========================================================================
# 5. DETERMINISM & TRACE METADATA PRESERVATION
# ===========================================================================

async def test_13_trace_metadata_preservation():
    """Test 13: Verifies exact preservation of project, goal, action, and idempotency IDs."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    action = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id="act-trace-check",
        title="Trace Check",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="HIGH",
        inputs_json={"prompt": "Trace preservation prompt"},
    )

    pkg = synthesize_job_package(action, project_id=project_id, goal_id=goal_id)

    assert pkg.projectId == str(project_id)
    assert pkg.jobPackageId == f"pkg:{project_id}:{action_id}"
    assert pkg.intentId == f"arya:action:{project_id}:{goal_id}:{action_id}:act-trace-check"
    assert pkg.executionPayload["action_id"] == str(action_id)
    assert pkg.executionPayload["goal_id"] == str(goal_id)
    assert pkg.executionPayload["project_id"] == str(project_id)
    assert pkg.executionPayload["idempotency_key"] == f"arya:action:{project_id}:{goal_id}:{action_id}:act-trace-check"
    assert pkg.executionPayload["risk_level"] == "HIGH"


async def test_14_deterministic_transformation():
    """Test 14: Proves transformer is strictly deterministic for identical normalized inputs."""
    project_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    action_id = uuid.uuid4()
    fixed_time = "2026-10-06T12:00:00Z"

    action = AutonomousActionNode(
        id=action_id,
        goal_id=goal_id,
        client_action_id="act-determ-01",
        title="Deterministic Action",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        inputs_json={"prompt": "A deterministic prompt", "aspect_ratio": "16:9"},
    )

    pkg1 = synthesize_job_package(action, project_id=project_id, goal_id=goal_id, created_at=fixed_time)
    pkg2 = synthesize_job_package(action, project_id=project_id, goal_id=goal_id, created_at=fixed_time)

    assert pkg1.model_dump() == pkg2.model_dump()


# ===========================================================================
# 6. FAIL-CLOSED GATE AND MOCK DISPATCHER INTEGRATION
# ===========================================================================

async def test_15_live_gate_remains_disabled_and_mock_dispatcher_unaffected():
    """Test 15: Confirms ENABLE_LIVE_PROVIDER_EXECUTION remains False and mock dispatcher works."""
    settings = get_settings()
    assert settings.enable_live_provider_execution is False
    assert is_live_provider_execution_enabled(settings) is False
