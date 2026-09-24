"""Unit tests for the AryaOS-owned Hermes persistent audit — §13 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §13 (Observability:
structured logging plus persistent audit; decision ALLOW/BLOCK and policy
reason code; parameter digest; blocked/denied requests are first-class
audit events, not noise).
"""
import concurrent.futures
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.hermes.audit import (
    AuthorizationDecisionAuditRecord,
    FileAuditSink,
    InMemoryAuditSink,
    compute_parameter_digest,
    get_active_audit_sink,
    record_policy_decision,
    set_active_audit_sink,
)
from app.hermes.policy import (
    AuthorizationContext,
    PolicyDecision,
    evaluate_tool_request,
    make_pre_tool_call_hook,
)

CONTEXT = AuthorizationContext(
    user_id="user-123",
    project_id="project-abc",
    job_id="job-456",
    agent_id="agent-789",
    lineage_id="lineage-xyz",
)


# ---------------------------------------------------------------------------
# 1. Parameter digest computation
# ---------------------------------------------------------------------------

def test_compute_parameter_digest_deterministic():
    """Identical parameter dictionaries with different key orders must produce
    identical SHA-256 digests."""
    params_a = {"query": "viral hooks", "limit": 5, "filter": "recent"}
    params_b = {"filter": "recent", "limit": 5, "query": "viral hooks"}
    digest_a = compute_parameter_digest(params_a)
    digest_b = compute_parameter_digest(params_b)

    assert digest_a == digest_b
    assert len(digest_a) == 64
    assert all(c in "0123456789abcdef" for c in digest_a)


def test_compute_parameter_digest_distinct():
    """Different parameters produce distinct SHA-256 digests."""
    digest_1 = compute_parameter_digest({"topic": "ai"})
    digest_2 = compute_parameter_digest({"topic": "space"})
    assert digest_1 != digest_2


def test_compute_parameter_digest_none_and_empty():
    """None and empty dictionary produce deterministic digests without raising."""
    digest_none = compute_parameter_digest(None)
    digest_empty = compute_parameter_digest({})
    assert digest_none == digest_empty
    assert len(digest_none) == 64


def test_compute_parameter_digest_non_dict():
    """Non-dict inputs (strings, lists, etc.) fallback safely and never raise."""
    digest_str = compute_parameter_digest("some_raw_string")
    digest_list = compute_parameter_digest([1, 2, 3])
    assert len(digest_str) == 64
    assert len(digest_list) == 64


# ---------------------------------------------------------------------------
# 2. Audit record dataclass & serialization
# ---------------------------------------------------------------------------

def test_audit_record_construction_and_serialization():
    record = AuthorizationDecisionAuditRecord(
        user_id="u",
        project_id="p",
        job_id="j",
        agent_id="a",
        lineage_id="l",
        tool_name="research.search",
        decision="ALLOW",
        reason_code="allowed_typed_capability",
        parameter_digest="abcdef123456",
        parameters={"query": "test"},
    )
    assert record.decision == "ALLOW"
    assert record.reason_code == "allowed_typed_capability"
    assert record.audit_id
    assert record.occurred_at

    data = record.to_dict()
    assert data["tool_name"] == "research.search"
    assert data["decision"] == "ALLOW"
    assert data["reason_code"] == "allowed_typed_capability"
    assert data["parameter_digest"] == "abcdef123456"
    assert data["parameters"] == {"query": "test"}

    json_str = record.to_json()
    assert "research.search" in json_str

    restored = AuthorizationDecisionAuditRecord.from_dict(json.loads(json_str))
    assert restored.audit_id == record.audit_id
    assert restored.decision == record.decision
    assert restored.reason_code == record.reason_code
    assert restored.parameter_digest == record.parameter_digest
    assert restored.parameters == record.parameters


# ---------------------------------------------------------------------------
# 3. InMemoryAuditSink
# ---------------------------------------------------------------------------

def test_in_memory_audit_sink():
    sink = InMemoryAuditSink()
    assert sink.records() == []

    record = AuthorizationDecisionAuditRecord(
        user_id="u",
        project_id="p",
        job_id="j",
        agent_id="a",
        lineage_id="l",
        tool_name="research.search",
        decision="ALLOW",
        reason_code="allowed_typed_capability",
        parameter_digest="1234",
    )
    sink.record(record)
    records = sink.records()
    assert len(records) == 1
    assert records[0] == record

    # records() returns a defensive copy
    records.clear()
    assert len(sink.records()) == 1

    sink.clear()
    assert sink.records() == []


def test_in_memory_audit_sink_thread_safe():
    sink = InMemoryAuditSink()

    def _worker(idx: int):
        rec = AuthorizationDecisionAuditRecord(
            user_id="u",
            project_id="p",
            job_id=f"j-{idx}",
            agent_id="a",
            lineage_id="l",
            tool_name="research.search",
            decision="ALLOW",
            reason_code="allowed_typed_capability",
            parameter_digest="1234",
        )
        sink.record(rec)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(_worker, range(50)))

    assert len(sink.records()) == 50


# ---------------------------------------------------------------------------
# 4. FileAuditSink
# ---------------------------------------------------------------------------

def test_file_audit_sink_persists_json_lines(tmp_path: Path):
    audit_file = tmp_path / "deep" / "nested" / "audit.jsonl"
    sink = FileAuditSink(audit_file)

    rec1 = AuthorizationDecisionAuditRecord(
        user_id="u1",
        project_id="p1",
        job_id="j1",
        agent_id="a1",
        lineage_id="l1",
        tool_name="research.search",
        decision="ALLOW",
        reason_code="allowed_typed_capability",
        parameter_digest="d1",
        parameters={"q": "apple"},
    )
    rec2 = AuthorizationDecisionAuditRecord(
        user_id="u2",
        project_id="p2",
        job_id="j2",
        agent_id="a2",
        lineage_id="l2",
        tool_name="shell",
        decision="BLOCK",
        reason_code="blocked_unknown_tool",
        parameter_digest="d2",
        parameters={"cmd": "ls"},
    )

    sink.record(rec1)
    sink.record(rec2)

    assert audit_file.is_file()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    records = sink.read_records()
    assert len(records) == 2
    assert records[0].tool_name == "research.search"
    assert records[0].decision == "ALLOW"
    assert records[1].tool_name == "shell"
    assert records[1].decision == "BLOCK"
    assert records[1].reason_code == "blocked_unknown_tool"


# ---------------------------------------------------------------------------
# 5. record_policy_decision function
# ---------------------------------------------------------------------------

def test_record_policy_decision_allow():
    sink = InMemoryAuditSink()
    decision = PolicyDecision(allowed=True, reason_code="allowed_typed_capability", message="")

    record = record_policy_decision(
        authorization_context=CONTEXT,
        tool_name="research.search",
        parameters={"topic": "space"},
        decision=decision,
        sink=sink,
    )

    assert record is not None
    assert record.decision == "ALLOW"
    assert record.reason_code == "allowed_typed_capability"
    assert record.tool_name == "research.search"
    assert record.user_id == CONTEXT.user_id
    assert record.job_id == CONTEXT.job_id
    assert record.project_id == CONTEXT.project_id
    assert record.lineage_id == CONTEXT.lineage_id
    assert record.parameters == {"topic": "space"}

    stored = sink.records()
    assert len(stored) == 1
    assert stored[0] == record


def test_record_policy_decision_block():
    sink = InMemoryAuditSink()
    decision = PolicyDecision(
        allowed=False,
        reason_code="blocked_explicit",
        message="Blocked by AryaOS policy gate: delegate_task",
    )

    record = record_policy_decision(
        authorization_context=CONTEXT,
        tool_name="delegate_task",
        parameters={"subagent": "worker"},
        decision=decision,
        sink=sink,
    )

    assert record is not None
    assert record.decision == "BLOCK"
    assert record.reason_code == "blocked_explicit"
    assert record.tool_name == "delegate_task"

    stored = sink.records()
    assert len(stored) == 1
    assert stored[0] == record


def test_record_policy_decision_with_invalid_context():
    """Malformed or None authorization context still records an audit entry with <unknown>."""
    sink = InMemoryAuditSink()
    decision = PolicyDecision(
        allowed=False,
        reason_code="blocked_invalid_context_type",
        message="Blocked invalid context",
    )

    record = record_policy_decision(
        authorization_context=None,
        tool_name="research.search",
        parameters={},
        decision=decision,
        sink=sink,
    )

    assert record is not None
    assert record.decision == "BLOCK"
    assert record.user_id == "<unknown>"
    assert record.reason_code == "blocked_invalid_context_type"
    assert len(sink.records()) == 1


def test_record_policy_decision_fail_closed_on_sink_error():
    """An exception raised by the sink is caught and logged; it never propagates or fails open."""

    class BrokenSink:
        def record(self, record):
            raise OSError("Disk full")

    decision = PolicyDecision(allowed=True, reason_code="allowed_typed_capability", message="")
    # Should not raise
    record = record_policy_decision(
        authorization_context=CONTEXT,
        tool_name="research.search",
        parameters={},
        decision=decision,
        sink=BrokenSink(),
    )
    assert record is not None
    assert record.decision == "ALLOW"


# ---------------------------------------------------------------------------
# 6. Hook Integration
# ---------------------------------------------------------------------------

def test_hook_records_decision_to_sink():
    sink = InMemoryAuditSink()
    hook = make_pre_tool_call_hook(CONTEXT, audit_sink=sink)

    # 1. Allowed call
    res_allow = hook("research.search", {"topic": "ai"})
    assert res_allow is None
    assert len(sink.records()) == 1
    assert sink.records()[0].decision == "ALLOW"
    assert sink.records()[0].tool_name == "research.search"

    # 2. Blocked unknown tool
    res_block = hook("shell", {"cmd": "id"})
    assert isinstance(res_block, dict) and res_block.get("action") == "block"
    assert len(sink.records()) == 2
    assert sink.records()[1].decision == "BLOCK"
    assert sink.records()[1].tool_name == "shell"
    assert sink.records()[1].reason_code == "blocked_unknown_tool"

    # 3. Blocked explicit delegation (§7)
    res_delegate = hook("delegate_task", {"agent": "x"})
    assert isinstance(res_delegate, dict) and res_delegate.get("action") == "block"
    assert len(sink.records()) == 3
    assert sink.records()[2].decision == "BLOCK"
    assert sink.records()[2].tool_name == "delegate_task"
    assert sink.records()[2].reason_code == "blocked_explicit"


def test_active_audit_sink_binding():
    sink = InMemoryAuditSink()
    try:
        set_active_audit_sink(sink)
        assert get_active_audit_sink() is sink

        hook = make_pre_tool_call_hook(CONTEXT)  # sink omitted -> uses active sink
        hook("todo_list", {"todos": []})

        records = sink.records()
        assert len(records) == 1
        assert records[0].decision == "ALLOW"
        assert records[0].tool_name == "todo_list"
        assert records[0].reason_code == "allowed_sanctioned_native_tool"
    finally:
        set_active_audit_sink(None)
        assert get_active_audit_sink() is None


# ---------------------------------------------------------------------------
# 7. Module import purity
# ---------------------------------------------------------------------------

def test_audit_module_never_imports_hermes():
    """app.hermes.audit must not import Hermes in a clean Python process."""
    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "import app.hermes.audit\n"
        "assert not any(\n"
        "    m == 'run_agent' or m.startswith(('agent.', 'hermes_cli', 'model_tools', 'toolsets'))\n"
        "    for m in sys.modules), 'audit module imported Hermes at import time'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 8. Real Hermes runtime persistence integration (§13 / §16)
# ---------------------------------------------------------------------------

def test_real_hermes_runtime_persists_audit_file(tmp_path: Path):
    """Integration test: during run_hermes_job, tool calls traversed through
    the policy gate are persisted to the FileAuditSink, and survive
    job home cleanup."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")

    from app.core.config import HERMES_COMMIT_PIN, Settings
    import app.hermes.runtime as runtime

    repo_root = Path(__file__).resolve().parents[2]
    plugin_path = repo_root / "backend" / "app" / "hermes" / "plugins"
    hermes_home = tmp_path / "hermes-root"

    settings = Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(plugin_path),
        hermes_home=str(hermes_home),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
    )

    request = runtime.HermesJobRequest(
        job_id="audit-job-1",
        task_message=None,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )

    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        hook = list(iter_hook_callbacks("pre_tool_call"))[0]
        hook("research.search", {"topic": "ai"})
        hook("shell", {"cmd": "whoami"})
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        res = runtime.run_hermes_job(request, settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert

    assert res.status == "completed"

    # Per-job home is deleted (§6)
    assert not (hermes_home / "jobs" / "audit-job-1").exists()

    # BUT the persistent audit log in hermes_home / audit / hermes_policy_audit.jsonl SURVIVES (§13)
    audit_file = hermes_home / "audit" / "hermes_policy_audit.jsonl"
    assert audit_file.is_file()

    sink = FileAuditSink(audit_file)
    records = sink.read_records()
    assert len(records) >= 2
    tool_names = [r.tool_name for r in records]
    decisions = [r.decision for r in records]
    assert "research.search" in tool_names
    assert "shell" in tool_names
    assert "ALLOW" in decisions
    assert "BLOCK" in decisions

