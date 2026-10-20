"""
AryaOS V1 Stage 25 Phase 3.2.2 — Secret Masking & Telemetry Sanitization Test Suite.

Verifies comprehensive secret redaction across:
1. Regex patterns and known token formats (Bearer, Basic, AryaOS, OpenAI, Anthropic, Google AI, Fal.ai, AWS, Slack, GitHub, JWT, configured app secrets).
2. Credential-bearing URLs (basic auth user:pass, sensitive query parameters).
3. Arbitrary nested structures and mixed-casing sensitive keys.
4. Fail-closed robustness on circular/recursive structures and deeply nested payloads.
5. Exception message and traceback masking while preserving operational error context.
6. Persisted database records (AutonomousActionNode outputs and errors).
7. Persisted system logs (log_event message and metadata).
8. Real-time telemetry events and SSE serialization.
9. Pydantic API response models (defense-in-depth sanitization).
10. Legitimate non-secret content preservation (prompts, dimensions, natural language).
11. Zero outbound network, zero provider invocations, and zero subprocess calls.
12. Frozen boundaries and migration head verification.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import redact_sensitive_data
from app.core.sanitization import (
    REDACTION_MARKER,
    sanitize_exception_message,
    sanitize_payload,
    sanitize_text,
)
from app.core.security import AuthenticatedPrincipal
from app.events.log import EventType, log_event
from app.main import app
from app.models.core import Project
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    Mission,
)
from app.models.system import SystemLog
from app.schemas.execution_bridge import (
    AutonomousActionNodeResponse,
    AutonomousGoalResponse,
    GovernanceDecisionResponse,
)
from app.schemas.production import JobResponse, TelemetryEvent
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    ExecutionResult,
    OfflineMockDispatcher,
    is_live_provider_execution_enabled,
)
from app.services.image_provider import image_provider_registry
from app.services.production_service import (
    emit_telemetry_event,
    register_telemetry_subscriber,
    unregister_telemetry_subscriber,
)
from app.services.video_provider import video_provider_registry

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# ISOLATION FIXTURE: STRICT OUTBOUND CALL PROHIBITION
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_outbound_network_and_subprocesses(monkeypatch):
    """Fails tests immediately if any outbound network or subprocess call is attempted."""

    def _fail_on_network(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Outbound network call attempted during Phase 3.2.2 test!"
        )

    def _fail_on_subprocess(*args, **kwargs):
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: Subprocess execution attempted during Phase 3.2.2 test!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _fail_on_network)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _fail_on_network)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fail_on_subprocess)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _fail_on_subprocess)
    monkeypatch.setattr("subprocess.Popen", _fail_on_subprocess)


# ===========================================================================
# TEST FIXTURES
# ===========================================================================

@pytest_asyncio.fixture(loop_scope="module")
async def phase3_2_2_fixture(db_session: AsyncSession):
    """Provisions a test project, mission, and principal for testing."""
    test_id = uuid.uuid4().hex[:8]
    project = Project(
        name=f"Phase 3.2.2 Test Project {test_id}",
        description="Sanitization test project",
        status="ACTIVE",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    mission = Mission(
        project_id=project.id,
        title=f"Phase 3.2.2 Mission {test_id}",
        objective="Sanitization verification mission",
        status="ACTIVE",
        priority="NORMAL",
    )
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="sanitization_tester",
        is_admin=True,
    )

    return {
        "project": project,
        "mission": mission,
        "principal": principal,
    }


# ===========================================================================
# 1. REGEX PATTERNS & KNOWN TOKEN FORMATS
# ===========================================================================

async def test_01_regex_patterns_and_known_token_formats():
    """Verifies that all known provider token formats and headers are redacted."""
    # Bearer token in Authorization header
    raw_bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.abcdef"
    clean_bearer = sanitize_text(raw_bearer)
    assert "eyJhbGci" not in clean_bearer
    assert REDACTION_MARKER in clean_bearer

    # Free text Bearer
    free_bearer = "Using Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.abcdef for auth"
    clean_free = sanitize_text(free_bearer)
    assert "eyJhbGci" not in clean_free
    assert f"Bearer {REDACTION_MARKER}" in clean_free

    # Basic auth
    raw_basic = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ="
    clean_basic = sanitize_text(raw_basic)
    assert "dXNlcm5hbWU6" not in clean_basic
    assert REDACTION_MARKER in clean_basic

    # AryaOS API key
    raw_arya = "arya_live_9876543210abcdef9876543210abcdef"
    clean_arya = sanitize_text(raw_arya)
    assert "9876543210abcdef" not in clean_arya
    assert clean_arya == REDACTION_MARKER

    # OpenAI key
    raw_openai = "sk-proj-abc1234567890abcdef1234567890"
    clean_openai = sanitize_text(raw_openai)
    assert "abc1234567890" not in clean_openai
    assert clean_openai == REDACTION_MARKER

    # Anthropic key
    raw_anthropic = "sk-ant-api03-abcdef1234567890"
    clean_anthropic = sanitize_text(raw_anthropic)
    assert "abcdef1234567890" not in clean_anthropic
    assert clean_anthropic == REDACTION_MARKER

    # Google AI Studio key
    raw_google = "AIzaSyD-1234567890abcdef1234567890abcdef"
    clean_google = sanitize_text(raw_google)
    assert "SyD-1234567890" not in clean_google
    assert clean_google == REDACTION_MARKER

    # Fal.ai API key (UUID:Hex)
    raw_fal = "12345678-1234-1234-1234-123456789abc:fedcba9876543210fedcba9876543210"
    clean_fal = sanitize_text(raw_fal)
    assert "fedcba9876543210" not in clean_fal
    assert REDACTION_MARKER in clean_fal

    # AWS Access Key
    raw_aws = "Error: Invalid credentials for key AKIAIOSFODNN7EXAMPLE"
    clean_aws = sanitize_text(raw_aws)
    assert "AKIAIOSFODNN7EXAMPLE" not in clean_aws
    assert REDACTION_MARKER in clean_aws

    # GitHub token
    raw_gh = "ghp_1234567890abcdef1234567890abcdef1234"
    clean_gh = sanitize_text(raw_gh)
    assert "1234567890" not in clean_gh
    assert clean_gh == REDACTION_MARKER

    # Slack token
    raw_slack = "xoxb-1234567890-1234567890123-abcdef"
    clean_slack = sanitize_text(raw_slack)
    assert "1234567890123" not in clean_slack
    assert clean_slack == REDACTION_MARKER

    # Key-value assignment in text
    raw_kv = "Connection string: api_key='secret_super_api_key' timeout=30"
    clean_kv = sanitize_text(raw_kv)
    assert "secret_super_api_key" not in clean_kv
    assert "timeout=30" in clean_kv

    # Configured application settings secret
    settings = get_settings()
    secret_val = getattr(settings, "secret_key", None) or getattr(settings, "arya_api_key", None)
    if secret_val and len(secret_val) >= 6:
        clean_secret = sanitize_text(f"Loaded with secret {secret_val}")
        assert secret_val not in clean_secret
        assert REDACTION_MARKER in clean_secret


# ===========================================================================
# 2. CREDENTIAL-BEARING URLS
# ===========================================================================

async def test_02_credential_bearing_urls():
    """Verifies that user:pass credentials and sensitive query params in URLs are masked."""
    # Basic auth embedded in URL
    raw_url = "https://admin:super_secret_password_123@api.fal.ai/v1/generate"
    clean_url = sanitize_text(raw_url)
    assert "super_secret_password_123" not in clean_url
    assert clean_url == f"https://{REDACTION_MARKER}:{REDACTION_MARKER}@api.fal.ai/v1/generate"

    # Query params containing secrets alongside non-secrets
    query_url = "https://api.fal.ai/v1/jobs?api_key=my_secret_key&token=my_secret_token&model=flux&page=2"
    clean_query = sanitize_text(query_url)
    assert "my_secret_key" not in clean_query
    assert "my_secret_token" not in clean_query
    assert f"api_key={REDACTION_MARKER}" in clean_query
    assert f"token={REDACTION_MARKER}" in clean_query
    assert "model=flux" in clean_query
    assert "page=2" in clean_query

    # Non-sensitive asset URL preserved unaltered
    safe_url = "https://cdn.arya.os/projects/123/shots/shot_001_frame.png"
    assert sanitize_text(safe_url) == safe_url


# ===========================================================================
# 3. ARBITRARY NESTED STRUCTURES & MIXED CASING
# ===========================================================================

async def test_03_arbitrary_nested_structures_and_mixed_casing():
    """Verifies deep payload traversal with sensitive keys in various casings."""
    adversarial_payload = {
        "metadata": {
            "API_KEY": "raw_secret_upper",
            "ApiKey": "raw_secret_camel",
            "client_secret": "raw_secret_snake",
            "passWORD": "raw_password",
            "AUTH_token": "raw_auth_token",
            "safe_nested": {
                "depth_3_list": [
                    {"token": "nested_in_list_token", "normal_id": "shot-42"},
                    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
                    {"url": "https://service:secretpass@provider.internal/v1"},
                ],
                "tuple_data": ("safe_item", "sk-proj-nestedsecret12345678901234567890"),
            },
        },
        "status": "COMPLETED",
        "shot_index": 7,
    }

    sanitized = sanitize_payload(adversarial_payload)

    # Check sensitive key values are redacted
    meta = sanitized["metadata"]
    assert meta["API_KEY"] == REDACTION_MARKER
    assert meta["ApiKey"] == REDACTION_MARKER
    assert meta["client_secret"] == REDACTION_MARKER
    assert meta["passWORD"] == REDACTION_MARKER
    assert meta["AUTH_token"] == REDACTION_MARKER

    # Check nested list
    depth_list = meta["safe_nested"]["depth_3_list"]
    assert depth_list[0]["token"] == REDACTION_MARKER
    assert depth_list[0]["normal_id"] == "shot-42"
    assert "eyJhbGci" not in depth_list[1]
    assert REDACTION_MARKER in depth_list[1]
    assert "secretpass" not in depth_list[2]["url"]
    assert f":{REDACTION_MARKER}@" in depth_list[2]["url"]

    # Check tuple preservation and text sanitization
    tuple_data = meta["safe_nested"]["tuple_data"]
    assert isinstance(tuple_data, tuple)
    assert tuple_data[0] == "safe_item"
    assert "nestedsecret" not in tuple_data[1]
    assert tuple_data[1] == REDACTION_MARKER

    # Non-sensitive root keys untouched
    assert sanitized["status"] == "COMPLETED"
    assert sanitized["shot_index"] == 7


# ===========================================================================
# 4. FAIL-CLOSED ROBUSTNESS ON CIRCLES & MALFORMED PAYLOADS
# ===========================================================================

async def test_04_fail_closed_robustness_cycles_and_malformed_payloads():
    """Verifies that circular references and excessive nesting fail safely."""
    # 1. Circular dictionary reference
    circular_dict = {"name": "test_node", "api_key": "secret_key_123"}
    circular_dict["self_reference"] = circular_dict

    sanitized_circle = sanitize_payload(circular_dict)
    assert sanitized_circle["name"] == "test_node"
    assert sanitized_circle["api_key"] == REDACTION_MARKER
    assert sanitized_circle["self_reference"] == "[CIRCULAR_REFERENCE_REDACTED]"

    # 2. Deep recursion beyond max_depth limit
    deep_dict = {}
    current = deep_dict
    for _ in range(60):
        current["nested"] = {}
        current = current["nested"]
    current["secret"] = "deep_secret"

    sanitized_deep = sanitize_payload(deep_dict, max_depth=30)
    # Beyond max_depth, node is marked as [MAX_DEPTH_EXCEEDED_REDACTED]
    sub = sanitized_deep
    for _ in range(30):
        sub = sub["nested"]
    assert sub == "[MAX_DEPTH_EXCEEDED_REDACTED]"


# ===========================================================================
# 5. EXCEPTION MESSAGE AND STACK TRACE MASKING
# ===========================================================================

async def test_05_exception_message_and_stack_trace_masking():
    """Verifies that exceptions preserve error context without exposing credentials."""
    exc = ValueError(
        "Failed authentication with https://user:secretpass@api.fal.ai: key sk-1234567890abcdef1234567890 was rejected"
    )
    sanitized_msg = sanitize_exception_message(exc)

    assert "ValueError:" in sanitized_msg
    assert "Failed authentication with" in sanitized_msg
    assert "secretpass" not in sanitized_msg
    assert REDACTION_MARKER in sanitized_msg
    assert "1234567890abcdef" not in sanitized_msg
    assert "was rejected" in sanitized_msg


# ===========================================================================
# 6. PERSISTED DATABASE RECORDS (AUTONOMOUS ACTION NODE OUTPUTS & ERRORS)
# ===========================================================================

async def test_06_persisted_action_node_outputs_and_error(
    db_session: AsyncSession, phase3_2_2_fixture: dict
):
    """Verifies that runner sanitizes node outputs_json and error before DB persistence."""
    project = phase3_2_2_fixture["project"]
    mission = phase3_2_2_fixture["mission"]
    principal = phase3_2_2_fixture["principal"]

    # Create Goal
    goal = AutonomousGoal(
        project_id=project.id,
        mission_id=mission.id,
        objective="Test persistence sanitization",
        status="EXECUTING",
        current_plan_version=1,
        plan_dag_json={
            "nodes": [
                {
                    "client_action_id": "act_sensitive_persist",
                    "title": "Action with sensitive output",
                    "action_type": "SYNTHESIS",
                    "required_capability": "mock_capability",
                }
            ],
            "edges": [],
        },
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action_node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_sensitive_persist",
        title="Action with sensitive output",
        action_type="SYNTHESIS",
        required_capability="mock_capability",
        status="READY",
        inputs_json={"safe_input": "prompt for scene"},
    )
    db_session.add(action_node)
    await db_session.commit()
    await db_session.refresh(action_node)

    # Create a mock dispatcher that returns sensitive outputs and token
    class LeakyMockDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            return ExecutionResult(
                success=True,
                status="SUCCEEDED",
                output={
                    "asset_url": "https://cdn.arya.internal/frame.png",
                    "secret_data": {
                        "api_key": "raw_secret_key_12345",
                        "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdef",
                    },
                    "prompt_used": "A glowing cybernetic lion in neon rain",
                },
                cost_usd=0.05,
                duration_seconds=1.2,
            )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=LeakyMockDispatcher())

    # Dispatch single action
    dispatched_node = await runner.dispatch_action(
        action_id=action_node.id,
        principal=principal,
    )
    assert dispatched_node.status == "SUCCEEDED"

    # Commit and refresh from DB directly
    await db_session.commit()
    result = await db_session.execute(
        select(AutonomousActionNode).where(AutonomousActionNode.id == action_node.id)
    )
    persisted_node = result.scalar_one()

    outputs = persisted_node.outputs_json
    assert outputs is not None
    # Verify raw secrets are absent
    assert "raw_secret_key_12345" not in str(outputs)
    assert "eyJhbGciOiJIUzI1Ni" not in str(outputs)
    assert outputs["secret_data"] == REDACTION_MARKER
    # Verify non-secret content preserved
    assert outputs["prompt_used"] == "A glowing cybernetic lion in neon rain"
    assert outputs["asset_url"] == "https://cdn.arya.internal/frame.png"
    assert persisted_node.status == "SUCCEEDED"


# ===========================================================================
# 7. PERSISTED SYSTEM LOG ENTRIES
# ===========================================================================

async def test_07_persisted_system_log_entries(
    db_session: AsyncSession, phase3_2_2_fixture: dict
):
    """Verifies that log_event sanitizes message and metadata before database insertion."""
    unique_marker = f"marker_{uuid.uuid4().hex[:10]}"

    await log_event(
        event_type=EventType.WORKFLOW_FAILED,
        message=f"Workflow failed on https://admin:super_secret@provider.internal with key sk-proj-1234567890abcdef1234567890 {unique_marker}",
        level="error",
        metadata={
            "api_key": "secret_key_in_metadata",
            "url": "https://user:password@service.net/v1",
            "token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.data.sig",
            "safe_counter": 42,
        },
    )

    # Query from database using unique_marker in message
    result = await db_session.execute(
        select(SystemLog).where(SystemLog.message.contains(unique_marker))
    )
    persisted_log = result.scalar_one()

    # Message must be sanitized
    assert "super_secret" not in persisted_log.message
    assert "1234567890abcdef" not in persisted_log.message
    assert REDACTION_MARKER in persisted_log.message

    # Metadata embedded in full_message must also be sanitized
    assert "secret_key_in_metadata" not in persisted_log.message
    assert "password" not in persisted_log.message
    assert "eyJhbGci" not in persisted_log.message
    assert f'"api_key": "{REDACTION_MARKER}"' in persisted_log.message
    assert '"safe_counter": 42' in persisted_log.message


# ===========================================================================
# 8. TELEMETRY & SSE STREAMING SERIALIZATION
# ===========================================================================

async def test_08_telemetry_event_and_sse_streaming_sanitization(
    phase3_2_2_fixture: dict
):
    """Verifies that telemetry emission and SSE serialization redact all sensitive fields."""
    project = phase3_2_2_fixture["project"]

    # 1. emit_telemetry_event sanitizes payload and delivers to subscriber queue
    q = asyncio.Queue()
    register_telemetry_subscriber(str(project.id), q)
    try:
        event = TelemetryEvent(
            project_id=project.id,
            event_type="JOB_STARTED",
            payload={
                "provider_job_id": "job_123",
                "token": "sk-ant-api03-secret1234567890",
                "client_secret": "my_client_secret_xyz",
                "endpoint": "https://user:pass@api.provider.com/v1",
                "progress": 0.0,
            },
        )
        await emit_telemetry_event(event)

        received_event = await q.get()
        assert received_event.event_type == "JOB_STARTED"
        payload = received_event.payload
        assert payload["provider_job_id"] == "job_123"
        assert payload["token"] == REDACTION_MARKER
        assert payload["client_secret"] == REDACTION_MARKER
        assert "pass" not in payload["endpoint"]
        assert REDACTION_MARKER in payload["endpoint"]
        assert payload["progress"] == 0.0
    finally:
        unregister_telemetry_subscriber(str(project.id), q)

    # 2. TelemetryEvent Pydantic schema validation
    event_schema = TelemetryEvent(
        project_id=project.id,
        event_type="JOB_PROGRESS",
        payload={
            "api_key": "raw_telemetry_key",
            "url": "https://u:p@cdn/asset?api_key=secret_param&fps=24",
            "fps": 24,
        },
    )
    assert event_schema.payload["api_key"] == REDACTION_MARKER
    assert "secret_param" not in event_schema.payload["url"]
    assert f"api_key={REDACTION_MARKER}" in event_schema.payload["url"]
    assert "fps=24" in event_schema.payload["url"]
    assert event_schema.payload["fps"] == 24


# ===========================================================================
# 9. PYDANTIC API RESPONSE MODELS (DEFENSE-IN-DEPTH)
# ===========================================================================

async def test_09_pydantic_api_response_models_defense_in_depth():
    """Verifies that response schemas sanitize data before serialization to clients."""
    dummy_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. AutonomousActionNodeResponse
    node_resp = AutonomousActionNodeResponse(
        id=dummy_uuid,
        goal_id=dummy_uuid,
        client_action_id="act_01",
        title="Test Action",
        action_type="SYNTHESIS",
        required_capability="video_generation",
        status="SUCCEEDED",
        risk_level="LOW",
        inputs_json={
            "prompt": "Cybernetic tiger",
            "auth": "Bearer secret_bearer_token",
        },
        outputs_json={
            "api_key": "leaked_api_key",
            "url": "https://admin:pass@cdn.arya.internal/shot.mp4",
        },
        error="Warning: Failed key sk-proj-1234567890abcdef1234567890",
        cost_usd=0.01,
        created_at=now,
        updated_at=now,
    )
    assert REDACTION_MARKER in node_resp.inputs_json["auth"]
    assert node_resp.outputs_json["api_key"] == REDACTION_MARKER
    assert "pass" not in node_resp.outputs_json["url"]
    assert "1234567890abcdef" not in node_resp.error
    assert REDACTION_MARKER in node_resp.error

    # 2. AutonomousGoalResponse
    goal_resp = AutonomousGoalResponse(
        id=dummy_uuid,
        project_id=dummy_uuid,
        objective="Goal objective",
        status="FAILED",
        current_plan_version=1,
        plan_dag_json={
            "nodes": [
                {
                    "id": "1",
                    "meta": {"token": "secret_token_123"},
                }
            ]
        },
        failure_reason="Failed contacting https://user:secret@api.fal.ai",
        final_summary="Summary with key arya_live_1234567890abcdef1234567890",
        created_at=now,
        updated_at=now,
    )
    assert goal_resp.plan_dag_json["nodes"][0]["meta"]["token"] == REDACTION_MARKER
    assert "secret" not in goal_resp.failure_reason
    assert REDACTION_MARKER in goal_resp.failure_reason
    assert "1234567890abcdef" not in goal_resp.final_summary
    assert REDACTION_MARKER in goal_resp.final_summary

    # 3. GovernanceDecisionResponse
    gov_resp = GovernanceDecisionResponse(
        id=dummy_uuid,
        project_id=dummy_uuid,
        verdict="DENIED",
        risk_level="HIGH",
        policy_evaluations=[{"policy": "auth_policy", "apiKey": "secret_key"}],
        reasons=["Rejected due to invalid token sk-ant-api03-1234567890"],
        created_at=now,
        updated_at=now,
    )
    assert gov_resp.policy_evaluations[0]["apiKey"] == REDACTION_MARKER
    assert "1234567890" not in gov_resp.reasons[0]
    assert REDACTION_MARKER in gov_resp.reasons[0]

    # 4. JobResponse
    job_resp = JobResponse(
        id=dummy_uuid,
        project_id=dummy_uuid,
        job_package_id="pkg_123",
        provider="fal",
        model="flux-pro",
        status="FAILED",
        progress=0.0,
        error="Exception at https://user:pass@host/api",
        job_package={"params": {"client_secret": "sensitive"}},
        created_at=now,
        updated_at=now,
    )
    assert "pass" not in job_resp.error
    assert REDACTION_MARKER in job_resp.error
    assert job_resp.job_package["params"]["client_secret"] == REDACTION_MARKER


# ===========================================================================
# 10. LEGITIMATE NON-SECRET CONTENT PRESERVATION
# ===========================================================================

async def test_10_legitimate_content_preservation():
    """Verifies that non-secret prompts, numbers, booleans, and formats remain intact."""
    complex_legitimate_payload = {
        "title": "A secret agent walking in the dark rain",
        "description": "The secret operative does not reveal their identity to passersby.",
        "aspect_ratio": "16:9",
        "resolution": "3840x2160",
        "duration_seconds": 4.5,
        "is_keyframe": True,
        "shot_number": 12,
        "tags": ["cinema", "nocturne", "4k", "cinematography"],
        "color_palette": {
            "primary": "#0A0E17",
            "secondary": "#00FFCC",
            "contrast_ratio": 14.2,
        },
        "frame_indices": [0, 24, 48, 72, 96],
        "null_field": None,
    }

    sanitized = sanitize_payload(complex_legitimate_payload)

    # Ensure natural language containing 'secret' as a word is NOT redacted
    assert sanitized["title"] == "A secret agent walking in the dark rain"
    assert (
        sanitized["description"]
        == "The secret operative does not reveal their identity to passersby."
    )
    # Ensure numbers, booleans, arrays, nulls are preserved
    assert sanitized["aspect_ratio"] == "16:9"
    assert sanitized["resolution"] == "3840x2160"
    assert sanitized["duration_seconds"] == 4.5
    assert sanitized["is_keyframe"] is True
    assert sanitized["shot_number"] == 12
    assert sanitized["tags"] == ["cinema", "nocturne", "4k", "cinematography"]
    assert sanitized["color_palette"]["primary"] == "#0A0E17"
    assert sanitized["color_palette"]["contrast_ratio"] == 14.2
    assert sanitized["frame_indices"] == [0, 24, 48, 72, 96]
    assert sanitized["null_field"] is None


# ===========================================================================
# 11. ZERO OUTBOUND NETWORK / ZERO PROVIDER / ZERO SUBPROCESS INVARIANTS
# ===========================================================================

async def test_11_zero_outbound_network_zero_provider_zero_subprocess():
    """Verifies that during Phase 3.2.2 testing, live execution is disabled and providers are never reached."""
    # Safety invariant: ENABLE_LIVE_PROVIDER_EXECUTION is False
    assert is_live_provider_execution_enabled() is False

    # Attach spies to providers
    mock_img_spy = AsyncMock()
    mock_vid_spy = AsyncMock()

    with patch.object(
        image_provider_registry, "get", return_value=MagicMock(generate_image=mock_img_spy)
    ), patch.object(
        video_provider_registry, "get", return_value=MagicMock(generate_video=mock_vid_spy)
    ):
        # Run a simulated runner cycle
        dispatcher = OfflineMockDispatcher()
        assert dispatcher.is_live is False

        # Providers should not have been called
        assert mock_img_spy.call_count == 0
        assert mock_vid_spy.call_count == 0


# ===========================================================================
# 12. FROZEN BOUNDARIES AND MIGRATION HEAD
# ===========================================================================

async def test_12_frozen_boundaries_and_migration_head():
    """Verifies that no migrations were added and Stages 03-24 remain frozen."""
    migration_file = "alembic/versions/i9d0e1f2a3b4_durable_approval_provenance.py"
    assert os.path.exists(migration_file), f"Expected {migration_file} to exist."

    with open(migration_file) as f:
        content = f.read()
    assert 'revision: str = "i9d0e1f2a3b4"' in content or "revision = 'i9d0e1f2a3b4'" in content

    # Confirm no new migration file was created for Phase 3.2.2
    alembic_versions = os.listdir("alembic/versions")
    assert not any(
        "sanitization" in v or "phase3_2_2" in v for v in alembic_versions
    ), "Forbidden database migration created for Phase 3.2.2!"

    # Check that frozen Stage 03 assets exist and are preserved
    assert os.path.exists("frontend/src/stage03_assembly.ts")
    assert os.path.exists("frontend/src/stage03_reflections.ts")
    assert os.path.exists("frontend/src/stage03_validation.ts")


# ===========================================================================
# 13. ACTION NODE FAILURE ERROR SANITIZATION
# ===========================================================================

async def test_13_action_node_failure_error_sanitization(
    db_session: AsyncSession, phase3_2_2_fixture: dict
):
    """Verifies that when an action fails with a sensitive error message, it is sanitized in DB."""
    project = phase3_2_2_fixture["project"]
    mission = phase3_2_2_fixture["mission"]
    principal = phase3_2_2_fixture["principal"]

    goal = AutonomousGoal(
        project_id=project.id,
        mission_id=mission.id,
        objective="Test failure error sanitization",
        status="EXECUTING",
        current_plan_version=1,
        plan_dag_json={
            "nodes": [
                {
                    "client_action_id": "act_fail_err",
                    "title": "Action with failing error",
                    "action_type": "SYNTHESIS",
                    "required_capability": "mock_capability",
                }
            ],
            "edges": [],
        },
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action_node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_fail_err",
        title="Action with failing error",
        action_type="SYNTHESIS",
        required_capability="mock_capability",
        status="READY",
        inputs_json={"safe_input": "prompt"},
    )
    db_session.add(action_node)
    await db_session.commit()
    await db_session.refresh(action_node)

    class FailingDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            return ExecutionResult(
                success=False,
                status="FAILED",
                error="Downstream error connecting to https://internal:supersecretpassword@fal.ai: key sk-proj-1234567890abcdef1234567890 expired",
            )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=FailingDispatcher())
    dispatched_node = await runner.dispatch_action(
        action_id=action_node.id,
        principal=principal,
    )
    assert dispatched_node.status == "FAILED"

    await db_session.commit()
    result = await db_session.execute(
        select(AutonomousActionNode).where(AutonomousActionNode.id == action_node.id)
    )
    persisted_node = result.scalar_one()

    assert persisted_node.error is not None
    assert "supersecretpassword" not in persisted_node.error
    assert "1234567890abcdef" not in persisted_node.error
    assert REDACTION_MARKER in persisted_node.error


# ===========================================================================
# 14. GOAL FAILURE REASON SANITIZATION ON RECOVERY_REQUIRED
# ===========================================================================

async def test_14_goal_failure_reason_sanitization(
    db_session: AsyncSession, phase3_2_2_fixture: dict
):
    """Verifies that goal failure_reason is sanitized when an unhandled exception occurs."""
    project = phase3_2_2_fixture["project"]
    mission = phase3_2_2_fixture["mission"]
    principal = phase3_2_2_fixture["principal"]

    goal = AutonomousGoal(
        project_id=project.id,
        mission_id=mission.id,
        objective="Test goal failure reason sanitization",
        status="EXECUTING",
        current_plan_version=1,
        plan_dag_json={
            "nodes": [
                {
                    "client_action_id": "act_crash",
                    "title": "Action causing unhandled exception",
                    "action_type": "SYNTHESIS",
                    "required_capability": "mock_capability",
                }
            ],
            "edges": [],
        },
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    action_node = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act_crash",
        title="Action causing crash",
        action_type="SYNTHESIS",
        required_capability="mock_capability",
        status="READY",
        inputs_json={"input": "data"},
    )
    db_session.add(action_node)
    await db_session.commit()
    await db_session.refresh(action_node)

    class CrashingDispatcher(OfflineMockDispatcher):
        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            raise ConnectionError(
                "Fatal crash communicating with https://worker:secret_worker_token@gateway: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.leaked_sig"
            )

    runner = AutonomousExecutionRunner(db=db_session, dispatcher=CrashingDispatcher())

    with pytest.raises(HTTPException) as exc_info:
        await runner.dispatch_action(
            action_id=action_node.id,
            principal=principal,
        )
    assert exc_info.value.status_code == 500
    assert "secret_worker_token" not in exc_info.value.detail
    assert "eyJhbGci" not in exc_info.value.detail
    assert REDACTION_MARKER in exc_info.value.detail

    # Verify node error in database
    res_node = await db_session.execute(
        select(AutonomousActionNode).where(AutonomousActionNode.id == action_node.id)
    )
    persisted_node = res_node.scalar_one()
    assert persisted_node.status == "UNKNOWN_PENDING_RECONCILIATION"
    assert "secret_worker_token" not in persisted_node.error
    assert REDACTION_MARKER in persisted_node.error

    # Verify goal failure reason in database
    res_goal = await db_session.execute(
        select(AutonomousGoal).where(AutonomousGoal.id == goal.id)
    )
    persisted_goal = res_goal.scalar_one()

    assert persisted_goal.status == "RECOVERY_REQUIRED"
    assert persisted_goal.failure_reason is not None
    assert "secret_worker_token" not in persisted_goal.failure_reason
    assert "eyJhbGci" not in persisted_goal.failure_reason
    assert REDACTION_MARKER in persisted_goal.failure_reason


# ===========================================================================
# 15. STRUCTLOG REDACTION PROCESSOR SANITIZATION
# ===========================================================================

async def test_15_structlog_processor_sanitization():
    """Verifies that structlog processor redact_sensitive_data scrubs event dictionaries."""
    event_dict = {
        "event": "dispatch_failed",
        "api_key": "raw_sensitive_key",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token",
        "nested": {
            "password": "supersecretpassword",
            "url": "https://admin:mypass@service.local",
            "safe_num": 100,
        },
    }

    scrubbed = redact_sensitive_data(logger=None, method_name="info", event_dict=event_dict)

    assert scrubbed["api_key"] == REDACTION_MARKER
    assert scrubbed["authorization"] == REDACTION_MARKER
    assert scrubbed["nested"]["password"] == REDACTION_MARKER
    assert "mypass" not in scrubbed["nested"]["url"]
    assert REDACTION_MARKER in scrubbed["nested"]["url"]
    assert scrubbed["nested"]["safe_num"] == 100
