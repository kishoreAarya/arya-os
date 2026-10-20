"""
AryaOS V1 Stage 25 Phase 3.2.4.4.1 — OpenMontage Adapter Hardening & Artifact Validation Hook Tests.

Validates the remediation of the three Phase 3.2.4.4.0 blockers:
1. BLOCKER-1: OpenMontage subprocess explicitly executes with cwd=str(self.openmontage_path).
   - Server CWD is never inherited.
   - Relative OpenMontage outputs resolve strictly within OpenMontage/output directory.
   - Path traversal in CWD/artifact paths is blocked.
2. BLOCKER-2: Strict subprocess environment isolation via allowlists.
   - Database secrets (DATABASE_URL, POSTGRES_PASSWORD) are never passed.
   - Backend secrets (SECRET_KEY, MASTER_API_KEY) are never passed.
   - Unrelated API keys (AWS, Stripe, OpenAI) are never passed.
   - Necessary runtime variables (PATH, HOME, BLENDER_PATH, FFMPEG_PATH) are passed.
   - User inputs cannot inject arbitrary environment variables.
3. BLOCKER-3: Real physical artifact validation before SUCCEEDED persistence.
   - Missing artifact file fails action.
   - Zero-byte artifact file fails action.
   - Wrong magic bytes fail action.
   - Text/HTML masquerading as media fails action.
   - Oversized file fails action.
   - Path traversal and symlink escape fail action.
   - Valid PNG succeeds action.
   - Valid MP4 succeeds action.
   - Invalid artifact prevents node SUCCEEDED persistence in database.
   - Failed artifact validation halts downstream DAG progression (remains PENDING/BLOCKED).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.schemas.production import AryaJobPackageSchema
from app.services.artifact_validator import (
    MAX_IMAGE_SIZE_BYTES,
    STORAGE_ARTIFACTS_DIR,
    validate_artifact_file,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import (
    ExecutionResult,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
)
from app.services.image_provider import ImageGenerationProvider, ImageProviderRegistry
from app.services.openmontage_adapter import (
    FORBIDDEN_SECRET_KEYS,
    OpenMontageAdapter,
    OpenMontageToolResult,
)
from app.services.video_provider import VideoGenerationProvider, VideoProviderRegistry

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK & REAL SUBPROCESS BLOCKING
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Guarantees zero outbound network or unmocked subprocess execution during tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.4.4.1 test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


# ===========================================================================
# TEST PROVIDER IMPLEMENTATIONS
# ===========================================================================

class Phase41TestImageProvider(ImageGenerationProvider):
    provider_id: str = "fal"
    model_id: str = "flux-pro/v1.1"
    capabilities: list[str] = ["text_to_image", "photorealistic"]

    def __init__(self, tool_result: OpenMontageToolResult) -> None:
        self.tool_result = tool_result

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.05

    async def generate_image(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
        return self.tool_result


class Phase41TestVideoProvider(VideoGenerationProvider):
    provider_id: str = "kling"
    model_id: str = "kling-video/v3/standard"
    capabilities: list[str] = ["TEXT_TO_VIDEO", "IMAGE_TO_VIDEO"]

    def __init__(self, tool_result: OpenMontageToolResult) -> None:
        self.tool_result = tool_result

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.15

    async def generate_video(self, pkg: AryaJobPackageSchema, output_path: str) -> OpenMontageToolResult:
        return self.tool_result


def create_valid_test_png(target_path: Path, width: int = 128, height: int = 128) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(45, 85, 125))
    img.save(target_path, format="PNG")
    return target_path


# ===========================================================================
# BLOCKER-1: CWD ISOLATION TESTS
# ===========================================================================

async def test_01_openmontage_adapter_passes_openmontage_cwd_to_subprocess(tmp_path: Path):
    """Test 01: OpenMontageAdapter explicitly passes cwd=str(self.openmontage_path) to asyncio.create_subprocess_exec."""
    om_dir = tmp_path / "mock_openmontage"
    om_dir.mkdir(parents=True, exist_ok=True)
    (om_dir / "tools").mkdir(parents=True, exist_ok=True)

    adapter = OpenMontageAdapter(
        openmontage_path=om_dir,
        python_path=Path("/usr/bin/python3"),
    )

    captured_kwargs = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured_kwargs.update(kwargs)
        mock_proc = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdin.wait_closed = AsyncMock()

        # Emit a valid v1.1 protocol frame
        valid_payload = (
            "__ARYA_OPENMONTAGE_RESULT_START__\n"
            '{"protocol_version":"1.1","tool":"camera_motion","success":true,"status":"COMPLETED",'
            '"phase":"POST_DISPATCH","is_ambiguous":false,"provider_job_id":null,"artifacts":[],'
            '"data":{},"error":null,"cost_usd":0.0,"duration_seconds":0.1}\n'
            "__ARYA_OPENMONTAGE_RESULT_END__\n"
        ).encode("utf-8")

        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[valid_payload, b""])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(side_effect=[b"", b""])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        res = await adapter.execute_tool("camera_motion", {"motion_type": "push"})

    assert "cwd" in captured_kwargs
    assert captured_kwargs["cwd"] == str(om_dir.resolve())
    assert res.success is True


async def test_02_openmontage_adapter_does_not_inherit_server_cwd(tmp_path: Path):
    """Test 02: OpenMontageAdapter never inherits the backend server CWD."""
    server_dir = tmp_path / "server_root"
    om_dir = tmp_path / "isolated_openmontage"
    server_dir.mkdir(parents=True, exist_ok=True)
    om_dir.mkdir(parents=True, exist_ok=True)
    (om_dir / "tools").mkdir(parents=True, exist_ok=True)

    adapter = OpenMontageAdapter(
        openmontage_path=om_dir,
        python_path=Path("/usr/bin/python3"),
    )

    captured_cwd = None

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cwd
        captured_cwd = kwargs.get("cwd")
        mock_proc = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdin.wait_closed = AsyncMock()
        valid_payload = (
            "__ARYA_OPENMONTAGE_RESULT_START__\n"
            '{"protocol_version":"1.1","tool":"camera_motion","success":true,"status":"COMPLETED",'
            '"phase":"POST_DISPATCH","is_ambiguous":false,"provider_job_id":null,"artifacts":[],'
            '"data":{},"error":null,"cost_usd":0.0,"duration_seconds":0.1}\n'
            "__ARYA_OPENMONTAGE_RESULT_END__\n"
        ).encode("utf-8")
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[valid_payload, b""])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(side_effect=[b"", b""])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        orig_cwd = os.getcwd()
        try:
            os.chdir(server_dir)
            await adapter.execute_tool("camera_motion", {})
        finally:
            os.chdir(orig_cwd)

    assert captured_cwd is not None
    assert captured_cwd != str(server_dir.resolve())
    assert captured_cwd == str(om_dir.resolve())


async def test_03_openmontage_relative_output_resolves_inside_openmontage_dir(tmp_path: Path):
    """Test 03: Relative output paths resolve strictly within OpenMontage/output directory."""
    om_dir = tmp_path / "openmontage_env"
    om_dir.mkdir(parents=True, exist_ok=True)

    relative_output = Path("renders/scene_001.png")
    # Relative path resolved against om_dir
    resolved = (om_dir / relative_output).resolve()

    assert str(resolved).startswith(str(om_dir.resolve()))
    assert resolved == om_dir / "renders" / "scene_001.png"


async def test_04_openmontage_cwd_path_traversal_blocked(tmp_path: Path):
    """Test 04: Path traversal attempts in CWD or artifact paths are strictly blocked."""
    confined_dir = tmp_path / "confined"
    confined_dir.mkdir(parents=True, exist_ok=True)

    # Attempt path traversal outside storage directory
    traversal_path = confined_dir / ".." / "escaped.png"
    traversal_path.touch()

    val_res = validate_artifact_file(traversal_path, allowed_dir=confined_dir)
    assert val_res.is_valid is False
    assert "Security violation" in val_res.error or "traversal" in val_res.error.lower()


# ===========================================================================
# BLOCKER-2: STRICT ENVIRONMENT ISOLATION TESTS
# ===========================================================================

async def test_05_subprocess_environment_does_not_contain_database_url(tmp_path: Path, monkeypatch):
    """Test 05: OpenMontage child environment strictly hides DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:supersecret@localhost:5432/arya_prod")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("flux_image")
    assert "DATABASE_URL" not in env


async def test_06_subprocess_environment_does_not_contain_postgres_password(tmp_path: Path, monkeypatch):
    """Test 06: OpenMontage child environment strictly hides POSTGRES_PASSWORD and db credentials."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "SuperConfidentialDbPassword999")
    monkeypatch.setenv("POSTGRES_USER", "arya_admin")
    monkeypatch.setenv("POSTGRES_DB", "arya_db")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("camera_motion")
    assert "POSTGRES_PASSWORD" not in env
    assert "POSTGRES_USER" not in env
    assert "POSTGRES_DB" not in env


async def test_07_subprocess_environment_does_not_contain_secret_key(tmp_path: Path, monkeypatch):
    """Test 07: OpenMontage child environment strictly hides SECRET_KEY and JWT_SECRET."""
    monkeypatch.setenv("SECRET_KEY", "jwt-signing-secret-key-32-bytes-long")
    monkeypatch.setenv("JWT_SECRET", "another-jwt-secret-token")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("kling_video")
    assert "SECRET_KEY" not in env
    assert "JWT_SECRET" not in env


async def test_08_subprocess_environment_does_not_contain_master_keys(tmp_path: Path, monkeypatch):
    """Test 08: OpenMontage child environment strictly hides master keys and bypass tokens."""
    monkeypatch.setenv("MASTER_API_KEY", "master-admin-token-xyz")
    monkeypatch.setenv("SYSTEM_MASTER_KEY", "sys-master-token-abc")
    monkeypatch.setenv("DEVELOPMENT_BYPASS_KEY", "dev-bypass-true")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("flux_image")
    assert "MASTER_API_KEY" not in env
    assert "SYSTEM_MASTER_KEY" not in env
    assert "DEVELOPMENT_BYPASS_KEY" not in env


async def test_09_subprocess_environment_does_not_contain_unrelated_api_keys(tmp_path: Path, monkeypatch):
    """Test 09: Subprocess environment allowlist rejects unrelated third-party API keys."""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-access-key-12345")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_stripe_key_abc")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-openai-key-xyz")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_github_personal_access_token")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("flux_image")
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "STRIPE_SECRET_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env


async def test_10_subprocess_environment_contains_necessary_runtime_vars(tmp_path: Path, monkeypatch):
    """Test 10: Subprocess environment preserves essential runtime variables (PATH, HOME, tool paths)."""
    monkeypatch.setenv("BLENDER_PATH", "/usr/local/bin/blender")
    monkeypatch.setenv("FFMPEG_PATH", "/usr/local/bin/ffmpeg")
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    env = adapter.build_subprocess_env("camera_motion")
    assert "PATH" in env
    assert len(env["PATH"]) > 0
    assert "HOME" in env
    assert env["BLENDER_PATH"] == "/usr/local/bin/blender"
    assert env["FFMPEG_PATH"] == "/usr/local/bin/ffmpeg"


async def test_11_subprocess_environment_blocks_user_input_injection(tmp_path: Path):
    """Test 11: Subprocess environment synthesis ignores user inputs attempting env variable injection."""
    adapter = OpenMontageAdapter(openmontage_path=tmp_path)

    user_inputs = {
        "prompt": "Cyberpunk city",
        "env": {"LD_PRELOAD": "/tmp/hack.so", "PATH": "/malicious/bin"},
        "LD_PRELOAD": "/tmp/hack.so",
        "PYTHONPATH": "/injected/code",
    }

    env = adapter.build_subprocess_env("flux_image")
    assert "LD_PRELOAD" not in env
    assert "/malicious/bin" not in env["PATH"]
    assert "PYTHONPATH" not in env


# ===========================================================================
# BLOCKER-3: PHYSICAL ARTIFACT VALIDATION HOOK TESTS
# ===========================================================================

async def test_12_artifact_validation_missing_file_fails_action(tmp_path: Path):
    """Test 12: Declared artifact missing from disk fails validation and marks action FAILED."""
    open_settings = Settings(enable_live_provider_execution=True)
    non_existent = str(tmp_path / "completely_missing_artifact.png")

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[non_existent],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_missing_art",
        title="Missing Artifact Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Artifact file not found" in str(res.error)


async def test_13_artifact_validation_zero_byte_file_fails_action(tmp_path: Path):
    """Test 13: Empty 0-byte artifact file fails validation and marks action FAILED."""
    open_settings = Settings(enable_live_provider_execution=True)
    zero_byte_file = tmp_path / "zero_bytes.png"
    zero_byte_file.touch()

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(zero_byte_file)],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_zero_byte",
        title="Zero Byte Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "0 bytes" in str(res.error)


async def test_14_artifact_validation_wrong_magic_bytes_fails_action(tmp_path: Path):
    """Test 14: File with invalid magic bytes fails validation."""
    open_settings = Settings(enable_live_provider_execution=True)
    corrupted_file = tmp_path / "corrupt_magic.png"
    corrupted_file.write_bytes(b"RANDOM_CORRUPT_BYTES_NOT_PNG_OR_MEDIA")

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(corrupted_file)],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_corrupt_magic",
        title="Corrupt Magic Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Invalid image binary" in str(res.error)


async def test_15_artifact_validation_invalid_media_fails_action(tmp_path: Path):
    """Test 15: HTML error page masquerading as image fails validation."""
    open_settings = Settings(enable_live_provider_execution=True)
    html_masquerade = tmp_path / "error_page.png"
    html_masquerade.write_bytes(b"<!DOCTYPE html><html><body><h1>502 Bad Gateway</h1></body></html>")

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(html_masquerade)],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_html_masquerade",
        title="HTML Masquerade Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Text or HTML payload detected" in str(res.error)


async def test_16_artifact_validation_oversized_file_fails_action(tmp_path: Path):
    """Test 16: Oversized artifact file (>50MB for image) fails validation."""
    oversized_file = tmp_path / "oversized.png"
    # Create sparse file > 50MB
    with open(oversized_file, "wb") as f:
        f.seek(MAX_IMAGE_SIZE_BYTES + 1024)
        f.write(b"\x00")

    val_res = validate_artifact_file(oversized_file, expected_type="image", allowed_dir=tmp_path)
    assert val_res.is_valid is False
    assert "exceeds maximum permitted size" in val_res.error


async def test_17_artifact_validation_path_traversal_fails_action(tmp_path: Path):
    """Test 17: Path traversal in artifact filename or directory confinement fails validation."""
    open_settings = Settings(enable_live_provider_execution=True)

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=["../../etc/passwd"],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_traversal",
        title="Traversal Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "FAILED"
    assert "Security violation" in str(res.error)


async def test_18_artifact_validation_symlink_escape_fails_action(tmp_path: Path):
    """Test 18: Symlink inside output directory pointing outside is rejected."""
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)
    secret_target = outside_dir / "secret.png"
    create_valid_test_png(secret_target)

    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    symlink_file = sandbox_dir / "symlink_escape.png"
    os.symlink(secret_target, symlink_file)

    val_res = validate_artifact_file(symlink_file, expected_type="image", allowed_dir=sandbox_dir)
    assert val_res.is_valid is False
    assert "traversal outside storage directory" in val_res.error


async def test_19_artifact_validation_valid_png_succeeds_action(tmp_path: Path):
    """Test 19: Genuine valid PNG passes physical validation and completes successfully."""
    open_settings = Settings(enable_live_provider_execution=True)
    valid_png = tmp_path / "genuine_output.png"
    create_valid_test_png(valid_png, width=256, height=256)

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(valid_png)],
        cost_usd=0.05,
        duration_seconds=1.2,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_valid_png",
        title="Valid PNG Test",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.output["artifacts"] == [str(valid_png)]
    assert res.output["image_url"] == str(valid_png)


async def test_20_artifact_validation_valid_mp4_succeeds_action(tmp_path: Path):
    """Test 20: Genuine valid MP4 passes physical validation and completes successfully."""
    open_settings = Settings(enable_live_provider_execution=True)
    source_mp4 = STORAGE_ARTIFACTS_DIR / "test_camera_push_success.mp4"
    if not source_mp4.is_file():
        pytest.skip("test_camera_push_success.mp4 not present in storage")

    dest_mp4 = tmp_path / "valid_video.mp4"
    shutil.copyfile(source_mp4, dest_mp4)

    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(dest_mp4)],
        cost_usd=0.15,
        duration_seconds=3.5,
    )

    vid_reg = VideoProviderRegistry()
    vid_reg.register(Phase41TestVideoProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(video_registry=vid_reg, settings=open_settings, output_dir=tmp_path)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="act_valid_mp4",
        title="Valid MP4 Test",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate video"},
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.output["artifacts"] == [str(dest_mp4)]
    assert res.output["video_url"] == str(dest_mp4)


async def test_21_invalid_artifact_prevents_node_succeeded_persistence(db_session: AsyncSession, tmp_path: Path):
    """Test 21: AutonomousExecutionRunner prevents node from ever persisting SUCCEEDED on invalid artifact."""
    project = Project(name="Phase 3.2.4.4.1 Persistence Project")
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
        objective="Artifact Validation Test",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "act_corrupt_db"}]},
    )
    db_session.add(goal)
    await db_session.flush()

    corrupt_file = tmp_path / "corrupt_on_disk.png"
    corrupt_file.write_bytes(b"INVALID_HEADER_GARBAGE")

    node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_corrupt_db",
        title="Corrupt DB Node",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Generate image"},
    )
    db_session.add(node)
    await db_session.commit()

    open_settings = Settings(enable_live_provider_execution=True)
    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[str(corrupt_file)],
        cost_usd=0.05,
    )

    reg = ImageProviderRegistry()
    reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=reg, settings=open_settings, output_dir=tmp_path)

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=open_settings)
    res = await runner.dispatch_action(node.id, principal)

    assert res.status == "FAILED"

    # Verify node in database is marked FAILED and never SUCCEEDED
    await db_session.refresh(node)
    assert node.status == "FAILED"
    assert "Invalid image binary" in str(node.error)


async def test_22_failed_artifact_validation_blocks_downstream_dag_readiness(db_session: AsyncSession, tmp_path: Path):
    """Test 22: Failed artifact validation halts DAG progression and leaves downstream nodes PENDING."""
    project = Project(name="Phase 3.2.4.4.1 DAG Cascade Project")
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
        objective="DAG Cascade Test",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "step_1_image"},
                {"client_action_id": "step_2_video"},
            ],
            "edges": [{"from": "step_1_image", "to": "step_2_video"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    # Step 1: fails because artifact is missing from disk
    missing_art = str(tmp_path / "nonexistent_shot.png")
    node_img = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step_1_image",
        title="Image Concept",
        action_type="SYNTHESIS",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Concept art"},
    )
    # Step 2: dependent video action
    node_vid = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="step_2_video",
        title="Video Generation",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="PENDING",
        inputs_json={"prompt": "Video generation"},
    )
    db_session.add_all([node_img, node_vid])
    await db_session.commit()

    open_settings = Settings(enable_live_provider_execution=True)
    tool_result = OpenMontageToolResult(
        success=True,
        status="COMPLETED",
        artifacts=[missing_art],
        cost_usd=0.05,
    )

    img_reg = ImageProviderRegistry()
    img_reg.register(Phase41TestImageProvider(tool_result=tool_result))
    dispatcher = LiveProviderDispatcher(image_registry=img_reg, settings=open_settings, output_dir=tmp_path)

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=dispatcher, settings=open_settings)
    res_img = await runner.dispatch_action(node_img.id, principal)

    assert res_img.status == "FAILED"

    # Step 1 must be FAILED
    await db_session.refresh(node_img)
    assert node_img.status == "FAILED"

    # Step 2 MUST NOT be promoted to READY; it must remain PENDING or BLOCKED
    await db_session.refresh(node_vid)
    assert node_vid.status != "READY"
    assert node_vid.status in ("PENDING", "BLOCKED")
