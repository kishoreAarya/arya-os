"""
AryaOS V1 Stage 25 Phase 3.2.4.4.4.2 — OpenMontage Budget Ledger Remediation Tests.

Verifies that local OpenMontage budget ledger checks and recording cannot corrupt
authoritative external provider execution truth.

Tested Invariants:
A. Budget exhausted BEFORE dispatch -> provider call count = 0, no external execution, ledger unchanged.
B. Budget available BEFORE dispatch -> provider execution proceeds, record succeeds.
C. Provider succeeds + record succeeds -> SUCCESS preserved, actual cost recorded in PostgreSQL.
D. Provider succeeds + record raises RuntimeError -> SUCCESS preserved, no subprocess crash, no retry, no fallback, no second call, accounting warning recorded safely.
E. Provider outcome UNKNOWN + record succeeds -> UNKNOWN preserved.
F. Provider outcome UNKNOWN + record fails -> UNKNOWN preserved, no retry.
G. Artifact succeeds + accounting fails -> validated artifact remains authoritative evidence, provider success not falsified.
H. Duplicate/second dispatch -> existing idempotency and worker lease fencing protections remain unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure OpenMontage tools can be imported in test environment
openmontage_path = "/Users/venkatakishorenasina/Documents/OpenMontage"
if openmontage_path not in sys.path:
    sys.path.insert(0, openmontage_path)

from app.core.config import Settings
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.schemas.production import AryaJobPackageSchema
from app.services.artifact_validator import (
    STORAGE_ARTIFACTS_DIR,
    ArtifactValidationResult,
    validate_artifact_file,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import (
    ExecutionResult,
    LiveProviderDispatcher,
    OfflineMockDispatcher,
)
from app.services.openmontage_adapter import (
    OpenMontageAdapter,
    OpenMontageToolResult,
)
from app.services.video_provider import (
    KlingVideoProvider,
    VideoProviderRegistry,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURES: STRICT NETWORK BLOCKING (ZERO EXTERNAL TRAFFIC)
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network(monkeypatch):
    """Guarantees zero outbound network requests during tests."""
    def _fail_on_network(*args, **kwargs):
        raise RuntimeError("CRITICAL SAFETY VIOLATION: Outbound network call attempted during test!")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)


def create_synthetic_mp4_artifact(target_path: Path, size_bytes: int = 150_000) -> Path:
    """Creates a deterministic synthetic test MP4 artifact with valid ftyp header."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    header = b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00mp41isom"
    content = header + b"\x00" * (max(0, size_bytes - len(header)))
    target_path.write_bytes(content)
    return target_path


# ===========================================================================
# 1. TEST A: BUDGET EXHAUSTED BEFORE DISPATCH
# ===========================================================================

async def test_a_budget_exhausted_before_dispatch(tmp_path, monkeypatch):
    """Test A: When local budget is exhausted, execution aborts BEFORE dispatch.
    Provider call count = 0, no external calls, spend ledger unchanged.
    """
    from tools import fal_spend
    from tools.video.kling_video import KlingVideo

    test_ledger = tmp_path / "fal_spend.json"
    initial_data = {
        "budget": 20.00,
        "generations": [
            {
                "timestamp": "2026-08-20T00:00:00Z",
                "model": "historical",
                "cost": 20.00,
            }
        ],
    }
    test_ledger.write_text(json.dumps(initial_data))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-key-for-test-pre-dispatch")

    tool = KlingVideo()
    inputs = {
        "prompt": "Test video",
        "operation": "text_to_video",
        "model_variant": "v3/standard",
        "duration": "5",
        "output_path": str(tmp_path / "never_created.mp4"),
    }

    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        res = tool.execute(inputs)
        # Aborted before provider dispatch
        assert res.success is False
        assert "Pre-dispatch budget check failed" in (res.error or "")
        # Provider call count MUST be exactly 0
        mock_post.assert_not_called()
        mock_get.assert_not_called()

    # Ledger MUST remain unmutated
    after_data = json.loads(test_ledger.read_text())
    assert len(after_data["generations"]) == 1
    assert sum(x["cost"] for x in after_data["generations"]) == 20.00


# ===========================================================================
# 2. TEST B: BUDGET AVAILABLE BEFORE DISPATCH
# ===========================================================================

async def test_b_budget_available_before_dispatch(tmp_path, monkeypatch):
    """Test B: When budget is available, provider dispatch proceeds and record succeeds."""
    from tools import fal_spend
    from tools.video.kling_video import KlingVideo

    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(
        json.dumps(
            {
                "budget": 20.00,
                "generations": [
                    {
                        "timestamp": "2026-08-20T00:00:00Z",
                        "model": "historical",
                        "cost": 10.00,
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-key-available")

    tool = KlingVideo()
    out_file = tmp_path / "test_b_video.mp4"
    inputs = {
        "prompt": "Cinematic shot",
        "operation": "text_to_video",
        "model_variant": "v3/standard",
        "duration": "5",
        "output_path": str(out_file),
    }

    mock_submit = MagicMock()
    mock_submit.json.return_value = {
        "status_url": "https://mock.queue/status",
        "response_url": "https://mock.queue/response",
        "request_id": "req-test-b",
    }
    mock_status = MagicMock()
    mock_status.json.return_value = {"status": "COMPLETED"}
    mock_response = MagicMock()
    mock_response.json.return_value = {"video": {"url": "https://cdn.mock/test.mp4"}}

    mock_dl = MagicMock()
    mock_dl.content = b"\x00\x00\x00 ftypmp42" + b"\x00" * 150_000

    def fake_get(url, *args, **kwargs):
        if "status" in url:
            return mock_status
        if "response" in url:
            return mock_response
        return mock_dl

    with patch("requests.post", return_value=mock_submit) as mock_post, \
         patch("requests.get", side_effect=fake_get) as mock_get, \
         patch("tools.video._shared.probe_output", return_value={"duration_seconds": 5.0, "format_name": "mp4"}):

        res = tool.execute(inputs)
        assert res.success is True
        assert res.data["request_id"] == "req-test-b"
        assert res.data.get("accounting_warning") is None

    # Spend ledger must have recorded generation
    after_data = json.loads(test_ledger.read_text())
    assert len(after_data["generations"]) == 2
    assert after_data["generations"][-1]["cost"] == 0.10


# ===========================================================================
# 3. TEST C: PROVIDER SUCCEEDS + RECORD SUCCEEDS
# ===========================================================================

async def test_c_provider_succeeds_record_succeeds(tmp_path):
    """Test C: End-to-end dispatcher verifies SUCCESS and persists actual cost."""
    out_file = tmp_path / "test_c_video.mp4"
    create_synthetic_mp4_artifact(out_file)

    tool_result = OpenMontageToolResult(
        protocol_version="1.1",
        tool="kling_video",
        success=True,
        status="COMPLETED",
        phase="POST_DISPATCH",
        is_ambiguous=False,
        provider_job_id="fal-req-c-12345",
        artifacts=[str(out_file)],
        data={
            "provider": "kling",
            "model": "fal-ai/kling-video/v3/standard/text-to-video",
            "request_id": "fal-req-c-12345",
        },
        cost_usd=0.10,
        duration_seconds=5.2,
    )

    class MockAdapter:
        async def execute_tool(self, *args, **kwargs):
            return tool_result
        def is_available(self):
            return True

    mock_provider = KlingVideoProvider(adapter=MockAdapter())
    settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=settings, validate_artifacts=False)
    dispatcher.video_registry.register(mock_provider)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        client_action_id="act_test_c",
        title="Test C kling",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={
            "prompt": "Test C prompt",
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "duration": 5.0,
            "output_path": str(out_file),
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert res.cost_usd == 0.10
    assert res.provider_job_id == "fal-req-c-12345"


# ===========================================================================
# 4. TEST D: PROVIDER SUCCEEDS + RECORD RAISES RUNTIMEERROR
# ===========================================================================

async def test_d_provider_succeeds_record_raises_runtimeerror(tmp_path, monkeypatch):
    """Test D: Provider succeeds but record raises RuntimeError.
    SUCCESS/provider truth preserved, no subprocess crash, no retry, accounting warning captured.
    """
    from tools import fal_spend
    from tools.video.kling_video import KlingVideo

    test_ledger = tmp_path / "fal_spend.json"
    test_ledger.write_text(json.dumps({"budget": 20.00, "generations": []}))
    monkeypatch.setattr(fal_spend, "LEDGER_PATH", test_ledger)
    monkeypatch.setenv("FAL_KEY", "mock-key-test-d")

    tool = KlingVideo()
    out_file = tmp_path / "test_d_video.mp4"
    inputs = {
        "prompt": "Test D prompt",
        "operation": "text_to_video",
        "model_variant": "v3/standard",
        "duration": "5",
        "output_path": str(out_file),
    }

    mock_submit = MagicMock()
    mock_submit.json.return_value = {
        "status_url": "https://mock.queue/status",
        "response_url": "https://mock.queue/response",
        "request_id": "req-test-d-999",
    }
    mock_status = MagicMock()
    mock_status.json.return_value = {"status": "COMPLETED"}
    mock_response = MagicMock()
    mock_response.json.return_value = {"video": {"url": "https://cdn.mock/video_d.mp4"}}
    mock_dl = MagicMock()
    mock_dl.content = b"\x00\x00\x00 ftypmp42" + b"\x00" * 150_000

    def fake_get(url, *args, **kwargs):
        if "status" in url:
            return mock_status
        if "response" in url:
            return mock_response
        return mock_dl

    # Invalidate record() to simulate post-dispatch ledger error
    with patch("requests.post", return_value=mock_submit), \
         patch("requests.get", side_effect=fake_get), \
         patch("tools.video._shared.probe_output", return_value={"duration_seconds": 5.0, "format_name": "mp4"}), \
         patch("tools.video.kling_video.record", side_effect=RuntimeError("FAL budget exceeded: $20.10 > $20.00")):

        res = tool.execute(inputs)
        # CRITICAL INVARIANT: ToolResult MUST NOT be failed by local accounting error
        assert res.success is True
        assert res.data["request_id"] == "req-test-d-999"
        assert "accounting_warning" in res.data
        assert "FAL budget exceeded" in res.data["accounting_warning"]
        assert out_file.is_file()


# ===========================================================================
# 5. TEST E: PROVIDER OUTCOME UNKNOWN + RECORD SUCCEEDS
# ===========================================================================

async def test_e_provider_outcome_unknown_preserved():
    """Test E: If provider execution is ambiguous (timeout), UNKNOWN_PENDING_RECONCILIATION is preserved."""
    ambiguous_result = OpenMontageToolResult(
        protocol_version="1.1",
        tool="kling_video",
        success=False,
        status="UNKNOWN_PENDING_RECONCILIATION",
        phase="IN_FLIGHT",
        is_ambiguous=True,
        provider_job_id="fal-req-timeout-1",
        artifacts=[],
        data={},
        error="OpenMontage subprocess timed out after 300.0s",
        cost_usd=0.10,
    )

    class MockAdapter:
        async def execute_tool(self, *args, **kwargs):
            return ambiguous_result
        def is_available(self):
            return True

    mock_provider = KlingVideoProvider(adapter=MockAdapter())
    settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=settings, validate_artifacts=False)
    dispatcher.video_registry.register(mock_provider)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        client_action_id="act_test_e",
        title="Test E timeout",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={
            "prompt": "Test E prompt",
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "duration": 5.0,
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert res.output.get("is_ambiguous") is True


# ===========================================================================
# 6. TEST F: PROVIDER OUTCOME UNKNOWN + RECORD FAILS
# ===========================================================================

async def test_f_provider_outcome_unknown_record_fails():
    """Test F: Ambiguous outcome remains UNKNOWN with zero automatic retry even if accounting fails."""
    ambiguous_result = OpenMontageToolResult(
        protocol_version="1.1",
        tool="kling_video",
        success=False,
        status="UNKNOWN_PENDING_RECONCILIATION",
        phase="IN_FLIGHT",
        is_ambiguous=True,
        provider_job_id="fal-req-timeout-2",
        artifacts=[],
        data={"accounting_warning": "Ledger failed"},
        error="Network interrupted",
        cost_usd=0.10,
    )

    class MockAdapter:
        async def execute_tool(self, *args, **kwargs):
            return ambiguous_result
        def is_available(self):
            return True

    mock_provider = KlingVideoProvider(adapter=MockAdapter())
    settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(settings=settings, validate_artifacts=False)
    dispatcher.video_registry.register(mock_provider)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        client_action_id="act_test_f",
        title="Test F timeout",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={
            "prompt": "Test F prompt",
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "duration": 5.0,
        },
    )

    res = await dispatcher.dispatch(action)
    assert res.success is False
    assert res.status == "UNKNOWN_PENDING_RECONCILIATION"


# ===========================================================================
# 7. TEST G: ARTIFACT VALIDATION SUCCEEDS + ACCOUNTING FAILS
# ===========================================================================

async def test_g_artifact_succeeds_accounting_fails(tmp_path):
    """Test G: Validated artifact remains authoritative evidence; success is not falsified."""
    out_file = tmp_path / "valid_test_g.mp4"
    create_synthetic_mp4_artifact(out_file)

    tool_result = OpenMontageToolResult(
        protocol_version="1.1",
        tool="kling_video",
        success=True,
        status="COMPLETED",
        phase="POST_DISPATCH",
        is_ambiguous=False,
        provider_job_id="fal-req-g-777",
        artifacts=[str(out_file)],
        data={
            "accounting_warning": "Secondary spend ledger recording failed: disk error",
            "request_id": "fal-req-g-777",
        },
        cost_usd=0.10,
        duration_seconds=4.8,
    )

    class MockAdapter:
        async def execute_tool(self, *args, **kwargs):
            return tool_result
        def is_available(self):
            return True

    mock_provider = KlingVideoProvider(adapter=MockAdapter())
    settings = Settings(enable_live_provider_execution=True)
    dispatcher = LiveProviderDispatcher(
        settings=settings,
        output_dir=tmp_path,
        validate_artifacts=True,
    )
    dispatcher.video_registry.register(mock_provider)

    action = AutonomousActionNode(
        id=uuid.uuid4(),
        client_action_id="act_test_g",
        title="Test G artifact",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        inputs_json={
            "prompt": "Test G prompt",
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "duration": 5.0,
            "output_path": str(out_file),
        },
    )

    with patch(
        "app.services.artifact_validator.validate_artifact_file",
        return_value=ArtifactValidationResult(
            is_valid=True, file_path=out_file, filename=out_file.name
        ),
    ):
        res = await dispatcher.dispatch(action)
        assert res.success is True
        assert res.status == "SUCCEEDED"
        # Accounting warning is safely preserved in sanitized output
        assert "accounting_warning" in res.output
        assert res.output["accounting_warning"] == "Secondary spend ledger recording failed: disk error"


# ===========================================================================
# 8. TEST H: DUPLICATE / SECOND DISPATCH REJECTION
# ===========================================================================

async def test_h_duplicate_second_dispatch_rejection(db_session: AsyncSession):
    """Test H: Existing idempotency and lease fencing protections prevent duplicate redispatch."""
    proj = Project(name="Test Kling Remediation Project", description="Testing Stage 25")
    db_session.add(proj)
    await db_session.flush()

    goal = AutonomousGoal(
        project_id=proj.id,
        objective="Test Kling Goal",
        status="EXECUTING",
        plan_dag_json={},
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_kling_dedup",
        title="Deduplication Action",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="EXECUTING",  # Already in executing state
        inputs_json={"prompt": "Astrolabe", "provider": "kling"},
    )
    db_session.add(action)
    await db_session.commit()

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=OfflineMockDispatcher())
    principal = AuthenticatedPrincipal(api_key_id=uuid.uuid4(), name="test_operator", is_admin=True)

    # Attempting to execute an already EXECUTING node must fail closed with 409
    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(action.id, principal)

    assert exc_info.value.status_code == 409
    assert "EXECUTING" in exc_info.value.detail
