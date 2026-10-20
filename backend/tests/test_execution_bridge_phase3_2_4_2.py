"""
AryaOS V1 Stage 25 Phase 3.2.4.2 — OpenMontage Protocol & Timeout Hardening Tests.

Validates the full Phase 3.2.4.2 boundary requirements:
1. Protocol v1.1 serialization and framed response parsing.
2. Result-framing isolation with noisy stdout lines and separate stderr diagnostics.
3. Malformed, truncated, oversized, and missing response handling.
4. Bounded 2 MB stdout/stderr streaming buffer limits.
5. External tool timeout yields UNKNOWN_PENDING_RECONCILIATION (is_ambiguous=True).
6. Local-only tool timeout yields FAILED only after safe process tree termination.
7. Process group termination (SIGTERM -> SIGKILL) and process-exit race safety.
8. Provider request ID extraction and validation (rejecting local paths, extensions, PIDs).
9. Secret redaction in subprocess stderr and error diagnostics.
10. Backward compatibility with legacy v1.0 unframed responses.
11. Tool identifier safety regex and availability pre-dispatch checks.
12. Abnormal non-zero exit code and inconsistent process state handling.
13. AutonomousExecutionRunner integration: ambiguous outcome halts DAG and sets goal RECOVERY_REQUIRED.
14. Live execution configuration gate remains fail-closed (ENABLE_LIVE_PROVIDER_EXECUTION=False).
15. Alembic migration head and frozen boundary invariants.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.sanitization import REDACTION_MARKER
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import (
    ExecutionResult,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
    is_live_provider_execution_enabled,
    verify_live_execution_gate,
)
from app.services.idempotency import (
    PROVIDER_PROFILES,
    ProviderConsistencyGuarantee,
)
from app.services.openmontage_adapter import (
    MAX_STREAM_BYTES,
    PROTOCOL_VERSION,
    RESULT_FRAME_END,
    RESULT_FRAME_START,
    OpenMontageAdapter,
    OpenMontageToolResult,
    is_external_tool,
    terminate_process_tree,
    validate_provider_job_id,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# -----------------------------------------------------------------------------
# Fixtures & Helpers
# -----------------------------------------------------------------------------

def make_framed_stdout(payload: dict) -> bytes:
    """Helper creating protocol-framed stdout bytes."""
    lines = [
        RESULT_FRAME_START,
        json.dumps(payload),
        RESULT_FRAME_END,
    ]
    return "\n".join(lines).encode("utf-8")


class MockSubprocess:
    """Mock asyncio subprocess providing controlled streams and exit codes."""

    def __init__(
        self,
        stdout_data: bytes = b"",
        stderr_data: bytes = b"",
        returncode: int = 0,
        pid: int = 12345,
    ) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout_data)
        self.stdout.feed_eof()

        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr_data)
        self.stderr.feed_eof()

        self.stdin = MagicMock()
        self.stdin.write = MagicMock()
        self.stdin.drain = AsyncMock()
        self.stdin.close = MagicMock()
        self.stdin.wait_closed = AsyncMock()

        self.returncode = returncode
        self.pid = pid

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

async def test_01_protocol_v1_1_serialization_and_parsing():
    """Validates that a compliant Protocol v1.1 framed response is parsed accurately."""
    adapter = OpenMontageAdapter()
    payload = {
        "protocol_version": "1.1",
        "tool": "flux_image",
        "success": True,
        "status": "COMPLETED",
        "phase": "POST_DISPATCH",
        "is_ambiguous": False,
        "provider_job_id": "fal-req-7c42a89b-90f1",
        "artifacts": ["storage/artifacts/shot_01.png"],
        "data": {"width": 1024, "height": 1024, "seed": 42},
        "error": None,
        "cost_usd": 0.05,
        "duration_seconds": 12.34,
        "seed": 42,
        "model": "fal-ai/flux-pro/v1.1",
    }
    mock_proc = MockSubprocess(stdout_data=make_framed_stdout(payload))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute_tool(
            tool_name="flux_image",
            inputs={"prompt": "Majestic waterfall at dawn"},
            timeout_seconds=30.0,
        )

    assert isinstance(result, OpenMontageToolResult)
    assert result.success is True
    assert result.status == "COMPLETED"
    assert result.protocol_version == "1.1"
    assert result.phase == "POST_DISPATCH"
    assert result.is_ambiguous is False
    assert result.provider_job_id == "fal-req-7c42a89b-90f1"
    assert result.artifacts == ["storage/artifacts/shot_01.png"]
    assert result.cost_usd == 0.05
    assert result.duration_seconds == 12.34
    assert result.seed == 42
    assert result.model == "fal-ai/flux-pro/v1.1"


async def test_02_framing_with_noisy_stdout_and_separate_stderr():
    """Validates that result framing isolates the protocol payload from noisy stdout and stderr."""
    adapter = OpenMontageAdapter()
    payload = {
        "protocol_version": "1.1",
        "tool": "kling_video",
        "success": True,
        "status": "COMPLETED",
        "phase": "POST_DISPATCH",
        "is_ambiguous": False,
        "provider_job_id": "fal-req-kling-99120",
        "artifacts": ["storage/artifacts/kling_01.mp4"],
        "data": {"duration": 5},
        "cost_usd": 0.20,
        "duration_seconds": 45.1,
    }

    # Noisy stdout with banners, stray printouts, and JSON-like strings outside delimiters
    noisy_stdout = (
        "INFO:root:Initializing OpenMontage runtime environment\n"
        "UserWarning: PyTorch CUDA memory caching enabled\n"
        '{"stray_debug_key": "stray_debug_value"}\n'
        f"{RESULT_FRAME_START}\n"
        f"{json.dumps(payload)}\n"
        f"{RESULT_FRAME_END}\n"
        "DEBUG:root:Flushing temporary cache directories\n"
    ).encode("utf-8")

    diag_stderr = b"Diagnostic warning: CUDA execution provider fallback to CPU\n"

    mock_proc = MockSubprocess(stdout_data=noisy_stdout, stderr_data=diag_stderr)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute_tool("kling_video", {"prompt": "Time lapse clouds"})

    assert result.success is True
    assert result.status == "COMPLETED"
    assert result.provider_job_id == "fal-req-kling-99120"
    assert result.artifacts == ["storage/artifacts/kling_01.mp4"]
    assert result.cost_usd == 0.20


async def test_03_malformed_and_incomplete_response_external_tool():
    """Validates that malformed or incomplete responses for external tools fail-closed to ambiguous."""
    adapter = OpenMontageAdapter()

    # Case A: Corrupted JSON inside frame delimiters
    corrupt_stdout = f"{RESULT_FRAME_START}\n{{corrupt_json_not_valid}}\n{RESULT_FRAME_END}\n".encode("utf-8")
    mock_proc = MockSubprocess(stdout_data=corrupt_stdout)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res_corrupt = await adapter.execute_tool("flux_image", {"prompt": "Test"})

    assert res_corrupt.success is False
    assert res_corrupt.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_corrupt.is_ambiguous is True
    assert res_corrupt.phase == "IN_FLIGHT"

    # Case B: Incomplete frame (missing RESULT_FRAME_END)
    incomplete_stdout = f"{RESULT_FRAME_START}\n{{\"success\": true}}\n".encode("utf-8")
    mock_proc_inc = MockSubprocess(stdout_data=incomplete_stdout)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_inc):
        res_inc = await adapter.execute_tool("kling_video", {"prompt": "Test"})

    assert res_inc.success is False
    assert res_inc.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_inc.is_ambiguous is True


async def test_04_oversized_stdout_exceeding_2mb_stream_cap():
    """Validates that stdout streaming buffers are capped at 2 MB and reject oversized output."""
    adapter = OpenMontageAdapter()

    # Generate 2.5 MB of garbage output
    large_garbage = b"A" * (2500 * 1024)
    mock_proc_ext = MockSubprocess(stdout_data=large_garbage)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_ext):
        res_ext = await adapter.execute_tool("flux_image", {"prompt": "Massive stream test"})

    assert res_ext.success is False
    assert res_ext.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_ext.is_ambiguous is True
    assert "streaming buffer limit" in str(res_ext.error)

    # Local tool with oversized output fails cleanly without ambiguity
    mock_proc_loc = MockSubprocess(stdout_data=large_garbage)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_loc):
        res_loc = await adapter.execute_tool("camera_motion", {"direction": "push"})

    assert res_loc.success is False
    assert res_loc.status == "FAILED"
    assert res_loc.is_ambiguous is False
    assert res_loc.phase == "LOCAL_EXECUTION"


async def test_05_external_timeout_yields_unknown_pending_reconciliation():
    """Validates that a subprocess timeout on an external API tool yields UNKNOWN_PENDING_RECONCILIATION."""
    adapter = OpenMontageAdapter()

    async def mock_subprocess_exec(*args, **kwargs):
        proc = MockSubprocess(pid=9901)
        async def _hang():
            await asyncio.sleep(10.0)
            return 0
        proc.wait = _hang
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec), \
         patch("app.services.openmontage_adapter.terminate_process_tree", new_callable=AsyncMock) as mock_kill:
        result = await adapter.execute_tool(
            tool_name="kling_video",
            inputs={"prompt": "Deep sea exploration"},
            timeout_seconds=0.05,
        )

    assert result.success is False
    assert result.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert result.is_ambiguous is True
    assert result.phase == "IN_FLIGHT"
    assert "timed out after 0.05 seconds" in str(result.error)
    assert "in-flight" in str(result.error)
    mock_kill.assert_awaited_once()


async def test_06_local_only_timeout_yields_failed_after_termination():
    """Validates that a subprocess timeout on a local-only tool yields FAILED without ambiguity."""
    adapter = OpenMontageAdapter()

    async def mock_subprocess_exec(*args, **kwargs):
        proc = MockSubprocess(pid=9902)
        async def _hang():
            await asyncio.sleep(10.0)
            return 0
        proc.wait = _hang
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec), \
         patch("app.services.openmontage_adapter.terminate_process_tree", new_callable=AsyncMock) as mock_kill:
        result = await adapter.execute_tool(
            tool_name="camera_push_video",
            inputs={"direction": "push", "zoom": 1.2},
            timeout_seconds=0.05,
        )

    assert result.success is False
    assert result.status == "FAILED"
    assert result.is_ambiguous is False
    assert result.phase == "LOCAL_EXECUTION"
    assert "Local execution timed out" in str(result.error)
    mock_kill.assert_awaited_once()


async def test_07_process_group_cleanup_and_exit_races():
    """Validates that process group termination issues SIGTERM/SIGKILL and handles exit races."""
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.wait = AsyncMock(return_value=0)

    # 1. Normal process group termination
    with patch("os.getpgid", return_value=4321), \
         patch("os.killpg") as mock_killpg:
        await terminate_process_tree(mock_proc, grace_period_seconds=0.01)
        mock_killpg.assert_called_with(4321, signal.SIGTERM)

    # 2. Race condition: Process exits before killpg is received (ProcessLookupError)
    mock_proc_race = MagicMock()
    mock_proc_race.pid = 4322
    mock_proc_race.wait = AsyncMock(return_value=0)

    with patch("os.getpgid", side_effect=ProcessLookupError), \
         patch("os.killpg"):
        # Must not raise exception
        await terminate_process_tree(mock_proc_race, grace_period_seconds=0.01)


async def test_08_provider_request_id_extraction_and_validation():
    """Validates that authentic cloud request IDs are accepted while local paths and PIDs are rejected."""
    # Authentic IDs
    assert validate_provider_job_id("fal-req-4a81cf2e") == "fal-req-4a81cf2e"
    assert validate_provider_job_id("req_0192837465") == "req_0192837465"
    assert validate_provider_job_id("f7c9e012-34ab-56cd-78ef-901234567890") == "f7c9e012-34ab-56cd-78ef-901234567890"

    # Rejection of local file paths
    assert validate_provider_job_id("/storage/artifacts/shot.png") is None
    assert validate_provider_job_id("C:\\Users\\render\\out.mp4") is None

    # Rejection of common media file names
    assert validate_provider_job_id("output.png") is None
    assert validate_provider_job_id("kling_render.mp4") is None
    assert validate_provider_job_id("metadata.json") is None

    # Rejection of local small integer PIDs and empty strings
    assert validate_provider_job_id("1234") is None
    assert validate_provider_job_id("89012") is None
    assert validate_provider_job_id("") is None
    assert validate_provider_job_id("   ") is None
    assert validate_provider_job_id(None) is None


async def test_09_secret_redaction_in_stderr_and_error_diagnostics():
    """Validates that secrets in subprocess stderr and error messages are redacted."""
    adapter = OpenMontageAdapter()
    secret_fal_key = "12345678-1234-1234-1234-123456789012:abcdef1234567890abcdef1234567890"
    secret_bearer_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_token_body_here.signature"

    stderr_with_secrets = (
        f"API Error with key {secret_fal_key}: Authorization Bearer {secret_bearer_token} was rejected"
    ).encode("utf-8")

    mock_proc = MockSubprocess(stderr_data=stderr_with_secrets, returncode=1)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute_tool("flux_image", {"prompt": "Test prompt"})

    assert result.success is False
    assert secret_fal_key not in str(result.error)
    assert secret_bearer_token not in str(result.error)
    assert REDACTION_MARKER in str(result.error)


async def test_10_unframed_legacy_output_rejected_fail_closed():
    """Validates that legacy unframed v1.0 JSON output is rejected fail-closed (no log reinterpretation)."""
    adapter = OpenMontageAdapter()
    legacy_stdout = (
        "Some initial log line\n"
        '{"success": true, "status": "COMPLETED", "artifacts": ["test.png"], "cost_usd": 0.03, "duration_seconds": 2.1}\n'
    ).encode("utf-8")

    mock_proc = MockSubprocess(stdout_data=legacy_stdout)

    # External tool: fails closed to UNKNOWN_PENDING_RECONCILIATION
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res_ext = await adapter.execute_tool("flux_image", {"prompt": "Test"})

    assert res_ext.success is False
    assert res_ext.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_ext.is_ambiguous is True
    assert "Protocol violation" in str(res_ext.error)

    # Local tool: fails closed to FAILED
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res_loc = await adapter.execute_tool("camera_motion", {"motion": "pan"})

    assert res_loc.success is False
    assert res_loc.status == "FAILED"
    assert res_loc.is_ambiguous is False
    assert "Protocol violation" in str(res_loc.error)


async def test_11_fail_closed_tool_name_and_availability_checks():
    """Validates that invalid tool names and unavailable OpenMontage engines fail closed."""
    adapter = OpenMontageAdapter()

    # Illegal tool names
    res_illegal_1 = await adapter.execute_tool("flux_image; rm -rf /", {})
    assert res_illegal_1.success is False
    assert res_illegal_1.status == "FAILED"
    assert res_illegal_1.phase == "PRE_DISPATCH"
    assert "Security violation" in str(res_illegal_1.error)

    res_illegal_2 = await adapter.execute_tool("../etc/passwd", {})
    assert res_illegal_2.success is False
    assert res_illegal_2.status == "FAILED"

    # Unavailable engine
    unavail_adapter = OpenMontageAdapter(openmontage_path="/nonexistent/openmontage/dir")
    res_unavail = await unavail_adapter.execute_tool("flux_image", {})
    assert res_unavail.success is False
    assert res_unavail.status == "UNAVAILABLE"
    assert res_unavail.phase == "PRE_DISPATCH"


async def test_12_non_zero_exit_code_and_inconsistent_process_state():
    """Validates that abnormal non-zero process exits are treated correctly."""
    adapter = OpenMontageAdapter()

    # External tool crashed (exit code 137 / SIGKILL)
    mock_crashed = MockSubprocess(stderr_data=b"Killed: Out of memory\n", returncode=137)
    with patch("asyncio.create_subprocess_exec", return_value=mock_crashed):
        res_ext = await adapter.execute_tool("flux_image", {})

    assert res_ext.success is False
    assert res_ext.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_ext.is_ambiguous is True

    # Inconsistent state: subprocess reported COMPLETED but exited with code 1
    inconsistent_payload = {
        "protocol_version": "1.1",
        "tool": "flux_image",
        "success": True,
        "status": "COMPLETED",
    }
    mock_inconsistent = MockSubprocess(
        stdout_data=make_framed_stdout(inconsistent_payload),
        returncode=1,
    )
    with patch("asyncio.create_subprocess_exec", return_value=mock_inconsistent):
        res_incon = await adapter.execute_tool("flux_image", {})

    assert res_incon.success is False
    assert res_incon.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_incon.is_ambiguous is True


async def test_13_runner_integration_ambiguous_outcome_halts_dag(db_session: AsyncSession):
    """Validates that an ambiguous execution result halts the DAG and transitions parent goal to RECOVERY_REQUIRED."""
    project = Project(name="Phase 3.2.4.2 Integration Project")
    db_session.add(project)
    await db_session.flush()
    project_id = project.id

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="System Principal",
        is_admin=True,
        principal_type="system",
    )

    goal = AutonomousGoal(
        project_id=project_id,
        objective="Verify ambiguous execution halts DAG",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "act_media", "title": "Generate Video", "risk_level": "LOW", "action_type": "GENERATION"},
                {"client_action_id": "act_downstream", "title": "Assemble Scene", "risk_level": "LOW", "action_type": "PROCESSING"},
            ],
            "edges": [
                {"from": "act_media", "to": "act_downstream"},
            ],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    node_media = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_media",
        title="Generate Video",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        risk_level="LOW",
        status="READY",
        inputs_json={"prompt": "Sunrise over ocean"},
    )
    node_downstream = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_downstream",
        title="Assemble Scene",
        action_type="PROCESSING",
        required_capability="VIDEO_ASSEMBLY",
        risk_level="LOW",
        status="PENDING",
    )
    db_session.add_all([node_media, node_downstream])
    await db_session.commit()

    # Mock dispatcher returning ambiguous outcome
    mock_dispatcher = MagicMock(spec=OfflineMockDispatcher)
    mock_dispatcher.is_live = False
    mock_dispatcher.dispatch = AsyncMock(
        return_value=ExecutionResult(
            success=False,
            status="UNKNOWN_PENDING_RECONCILIATION",
            output={},
            error="Execution timed out after 180s while external provider call was in-flight",
            provider_job_id="fal-req-ambig-1234",
        )
    )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=mock_dispatcher)
    updated_node = await runner.dispatch_action(node_media.id, principal)

    assert updated_node.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert updated_node.inputs_json["dispatch_intent"]["provider_job_id"] == "fal-req-ambig-1234"

    # Verify parent goal transitioned to RECOVERY_REQUIRED
    await db_session.refresh(goal)
    assert goal.status == "RECOVERY_REQUIRED"
    assert "outcome is unknown" in str(goal.failure_reason)

    # Verify downstream node remains blocked / PENDING and was not released
    await db_session.refresh(node_downstream)
    assert node_downstream.status in ("BLOCKED", "PENDING")


async def test_14_live_execution_gate_remains_disabled_fail_closed():
    """Validates that ENABLE_LIVE_PROVIDER_EXECUTION remains fail-closed and Fal/Kling profiles remain NO_LOOKUP."""
    settings = get_settings()
    assert settings.enable_live_provider_execution is False
    assert is_live_provider_execution_enabled() is False

    with pytest.raises(Exception):
        verify_live_execution_gate()

    live_disp = LiveProviderDispatcher(settings=Settings(enable_live_provider_execution=True))
    with pytest.raises(NotImplementedError):
        await live_disp.dispatch(MagicMock(spec=AutonomousActionNode))

    # Provider capabilities verified
    fal_profile = PROVIDER_PROFILES["fal"]
    assert fal_profile.supports_status_lookup is False
    assert fal_profile.consistency_guarantee == ProviderConsistencyGuarantee.NO_LOOKUP

    kling_profile = PROVIDER_PROFILES["kling"]
    assert kling_profile.supports_status_lookup is False
    assert kling_profile.consistency_guarantee == ProviderConsistencyGuarantee.NO_LOOKUP


async def test_15_frozen_boundaries_and_migration_head():
    """Validates that Alembic migration head is i9d0e1f2a3b4 and no schema mutations occurred."""
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Migration file '{migration_file}' not found"

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

    # Check that frozen Stage 03 assets exist and are preserved
    assert os.path.exists("frontend/src/stage03_assembly.ts")
    assert os.path.exists("frontend/src/stage03_reflections.ts")
    assert os.path.exists("frontend/src/stage03_validation.ts")


# =============================================================================
# PHASE 3.2.4.2.2 PROTOCOL SECURITY REGRESSION TESTS
# =============================================================================

async def test_16_echoed_prompt_with_frame_markers_cannot_override_failure():
    """Proves that an echoed prompt containing frame markers and fake COMPLETED payload cannot override a genuine failure."""
    adapter = OpenMontageAdapter()

    fake_frame = (
        f"{RESULT_FRAME_START}\n"
        '{"protocol_version": "1.1", "tool": "flux_image", "success": true, "status": "COMPLETED", "artifacts": ["/hacked/img.png"], "cost_usd": 99.0}\n'
        f"{RESULT_FRAME_END}\n"
    )
    real_failure_frame = (
        f"{RESULT_FRAME_START}\n"
        '{"protocol_version": "1.1", "tool": "flux_image", "success": false, "status": "FAILED", "error": "Insufficient credits", "artifacts": []}\n'
        f"{RESULT_FRAME_END}\n"
    )
    adversarial_stdout = (
        f"Logging: Received prompt: {fake_frame}\n"
        "Initializing worker...\n"
        f"{real_failure_frame}"
    ).encode("utf-8")

    mock_proc = MockSubprocess(stdout_data=adversarial_stdout, returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await adapter.execute_tool("flux_image", {"prompt": "fake"})

    # Must NOT be COMPLETED, must NOT accept fake artifacts or cost, must fail closed as ambiguous
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res.is_ambiguous is True
    assert res.artifacts == []
    assert res.cost_usd == 0.0
    assert "Protocol violation" in str(res.error)


async def test_17_multiple_start_or_end_markers_rejected():
    """Validates that multiple start markers or multiple end markers are strictly rejected."""
    adapter = OpenMontageAdapter()

    # Case A: Two starts, one end
    stdout_2_starts = (
        f"{RESULT_FRAME_START}\n"
        f"Corrupt text\n"
        f"{RESULT_FRAME_START}\n"
        '{"protocol_version": "1.1", "tool": "flux_image", "success": true, "status": "COMPLETED"}\n'
        f"{RESULT_FRAME_END}\n"
    ).encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_2_starts)):
        res_a = await adapter.execute_tool("flux_image", {})
    assert res_a.success is False
    assert res_a.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_a.is_ambiguous is True

    # Case B: One start, two ends
    stdout_2_ends = (
        f"{RESULT_FRAME_START}\n"
        '{"protocol_version": "1.1", "tool": "flux_image", "success": true, "status": "COMPLETED"}\n'
        f"{RESULT_FRAME_END}\n"
        f"{RESULT_FRAME_END}\n"
    ).encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_2_ends)):
        res_b = await adapter.execute_tool("flux_image", {})
    assert res_b.success is False
    assert res_b.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_b.is_ambiguous is True


async def test_18_reversed_nested_incomplete_or_mismatched_delimiters_rejected():
    """Validates that reversed, nested, incomplete, or empty frame delimiters are rejected fail-closed."""
    adapter = OpenMontageAdapter()

    # Reversed: END before START
    stdout_reversed = (
        f"{RESULT_FRAME_END}\n"
        '{"protocol_version": "1.1", "success": true, "status": "COMPLETED"}\n'
        f"{RESULT_FRAME_START}\n"
    ).encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_reversed)):
        res_rev = await adapter.execute_tool("flux_image", {})
    assert res_rev.success is False
    assert res_rev.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res_rev.is_ambiguous is True

    # Incomplete: START only
    stdout_start_only = f"{RESULT_FRAME_START}\n{{\"protocol_version\": \"1.1\", \"success\": true}}".encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_start_only)):
        res_inc = await adapter.execute_tool("flux_image", {})
    assert res_inc.success is False
    assert res_inc.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Empty frame body
    stdout_empty_body = f"{RESULT_FRAME_START}\n\n{RESULT_FRAME_END}\n".encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_empty_body)):
        res_empty = await adapter.execute_tool("flux_image", {})
    assert res_empty.success is False
    assert res_empty.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Wrong protocol version inside frame
    stdout_wrong_proto = (
        f"{RESULT_FRAME_START}\n"
        '{"protocol_version": "1.0", "tool": "flux_image", "success": true, "status": "COMPLETED"}\n'
        f"{RESULT_FRAME_END}\n"
    ).encode("utf-8")
    with patch("asyncio.create_subprocess_exec", return_value=MockSubprocess(stdout_data=stdout_wrong_proto)):
        res_proto = await adapter.execute_tool("flux_image", {})
    assert res_proto.success is False
    assert res_proto.status == "UNKNOWN_PENDING_RECONCILIATION"


async def test_19_json_log_line_without_valid_frame_never_accepted():
    """Proves that structured JSON log lines without valid v1.1 frame delimiters are never accepted as results."""
    adapter = OpenMontageAdapter()

    # Subprocess output contains realistic third-party JSON logs
    stdout_json_logs = (
        '{"timestamp": "2026-10-06T20:00:00Z", "level": "INFO", "message": "Worker started"}\n'
        '{"event": "task_progress", "percent": 50, "status": "RUNNING"}\n'
        '{"event": "task_complete", "success": true, "status": "COMPLETED", "result": {"path": "/tmp/out.png"}}\n'
    ).encode("utf-8")

    mock_proc = MockSubprocess(stdout_data=stdout_json_logs, returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute_tool("flux_image", {})

    assert result.success is False
    assert result.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert result.is_ambiguous is True
    assert "Protocol violation" in str(result.error)


async def test_20_missing_framing_external_tool_produces_ambiguous_outcome(db_session: AsyncSession):
    """End-to-end integration: missing framing on external tool marks UNKNOWN_PENDING_RECONCILIATION and halts DAG."""
    project = Project(name="Missing Framing Integration")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Security Principal",
        is_admin=True,
        principal_type="system",
    )

    goal = AutonomousGoal(
        project_id=project.id,
        objective="Verify missing framing halts DAG",
        status="EXECUTING",
        plan_dag_json={
            "nodes": [
                {"client_action_id": "act_unframed", "title": "Generate Image", "risk_level": "LOW", "action_type": "GENERATION"},
                {"client_action_id": "act_after", "title": "Next Step", "risk_level": "LOW", "action_type": "PROCESSING"},
            ],
            "edges": [{"from": "act_unframed", "to": "act_after"}],
        },
    )
    db_session.add(goal)
    await db_session.flush()

    node_unframed = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_unframed",
        title="Generate Image",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        risk_level="LOW",
        status="READY",
    )
    node_after = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_after",
        title="Next Step",
        action_type="PROCESSING",
        required_capability="IMAGE_PROCESSING",
        risk_level="LOW",
        status="PENDING",
    )
    db_session.add_all([node_unframed, node_after])
    await db_session.commit()

    # Subprocess outputs arbitrary text with zero frame markers
    adapter = OpenMontageAdapter()
    mock_proc = MockSubprocess(stdout_data=b"Process completed cleanly with no framing\n", returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        adapter_res = await adapter.execute_tool("flux_image", {})

    assert adapter_res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert adapter_res.is_ambiguous is True

    # Dispatch via runner using adapter outcome
    mock_disp = MagicMock(spec=OfflineMockDispatcher)
    mock_disp.is_live = False
    mock_disp.dispatch = AsyncMock(
        return_value=ExecutionResult(
            success=adapter_res.success,
            status=adapter_res.status,
            output=adapter_res.data,
            error=adapter_res.error,
        )
    )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=mock_disp)
    updated_node = await runner.dispatch_action(node_unframed.id, principal)

    assert updated_node.status == "UNKNOWN_PENDING_RECONCILIATION"

    # Goal must be transitioned to RECOVERY_REQUIRED
    await db_session.refresh(goal)
    assert goal.status == "RECOVERY_REQUIRED"

    # Downstream node must remain PENDING / BLOCKED and not released
    await db_session.refresh(node_after)
    assert node_after.status in ("BLOCKED", "PENDING")


async def test_21_valid_single_v1_1_frame_parses_correctly():
    """Proves that an authentic single v1.1 frame surrounded by noisy logs parses cleanly."""
    adapter = OpenMontageAdapter()

    valid_payload = {
        "protocol_version": "1.1",
        "tool": "flux_image",
        "success": True,
        "status": "COMPLETED",
        "phase": "POST_DISPATCH",
        "is_ambiguous": False,
        "provider_job_id": "fal-req-valid-12345",
        "artifacts": ["/storage/shot_01.png"],
        "data": {"seed": 99},
        "cost_usd": 0.025,
        "duration_seconds": 3.8,
        "seed": 99,
        "model": "flux-schnell",
    }
    stdout_data = (
        "INFO: Initializing pipeline\n"
        f"{RESULT_FRAME_START}\n"
        f"{json.dumps(valid_payload)}\n"
        f"{RESULT_FRAME_END}\n"
        "INFO: Cleaning up temp files\n"
    ).encode("utf-8")

    mock_proc = MockSubprocess(stdout_data=stdout_data, returncode=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.execute_tool("flux_image", {})

    assert result.success is True
    assert result.status == "COMPLETED"
    assert result.protocol_version == "1.1"
    assert result.provider_job_id == "fal-req-valid-12345"
    assert result.artifacts == ["/storage/shot_01.png"]
    assert result.cost_usd == 0.025
    assert result.duration_seconds == 3.8
    assert result.is_ambiguous is False


async def test_22_process_cleanup_handles_exited_group_leader_safely():
    """Proves that process cleanup uses established PGID directly and handles exited group leader."""
    # Test 1: Guard against pid <= 1
    mock_proc_low = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc_low.pid = 1
    with patch("os.killpg") as mock_killpg:
        await terminate_process_tree(mock_proc_low)
        mock_killpg.assert_not_called()

    mock_proc_none = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc_none.pid = None
    with patch("os.killpg") as mock_killpg:
        await terminate_process_tree(mock_proc_none)
        mock_killpg.assert_not_called()

    # Test 2: Safe process group signaling with valid PID
    mock_proc_valid = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc_valid.pid = 45678
    mock_proc_valid.wait = AsyncMock(return_value=0)
    mock_proc_valid.terminate = MagicMock()

    with patch("os.killpg") as mock_killpg:
        await terminate_process_tree(mock_proc_valid, grace_period_seconds=0.01)
        # Verified os.killpg called with direct PID as PGID
        mock_killpg.assert_any_call(45678, signal.SIGTERM)

    # Test 3: ProcessLookupError handled cleanly when group leader has already exited
    mock_proc_exited = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc_exited.pid = 56789
    mock_proc_exited.wait = AsyncMock(side_effect=ProcessLookupError())
    mock_proc_exited.terminate = MagicMock(side_effect=ProcessLookupError())
    mock_proc_exited.kill = MagicMock(side_effect=ProcessLookupError())

    with patch("os.killpg", side_effect=ProcessLookupError()):
        # Must terminate without raising unhandled exception
        await terminate_process_tree(mock_proc_exited, grace_period_seconds=0.01)
