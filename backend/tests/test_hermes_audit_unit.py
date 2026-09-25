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
    record_final_outcome,
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
# 5b. Final-outcome records (§13.1)
# ---------------------------------------------------------------------------

def test_record_final_outcome_to_active_sink():
    """§13.1 helper: additive final-outcome BLOCK with identity from the
    runtime-bound context, persisted to the active sink."""
    from app.hermes import runtime

    sink = InMemoryAuditSink()
    try:
        runtime.set_active_authorization_context(CONTEXT)
        set_active_audit_sink(sink)
        record = record_final_outcome("research.search", {"topic": "x"}, "capability_schema_invalid")
        assert record is not None
        assert record.decision == "BLOCK"
        assert record.reason_code == "capability_schema_invalid"
        assert record.tool_name == "research.search"
        assert record.user_id == CONTEXT.user_id
        assert record.job_id == CONTEXT.job_id
        assert record.project_id == CONTEXT.project_id
        assert record.lineage_id == CONTEXT.lineage_id
        assert record.parameters == {"topic": "x"}
        assert record.parameter_digest == compute_parameter_digest({"topic": "x"})
        assert sink.records() == [record]
    finally:
        runtime.set_active_authorization_context(None)
        set_active_audit_sink(None)


def test_record_final_outcome_explicit_sink_unknown_context():
    """Explicit sink wins over the active binding; a missing runtime
    context degrades identity to <unknown>, never an error."""
    sink = InMemoryAuditSink()
    record = record_final_outcome("todo_list", {}, "tool_call_limit_exceeded", sink=sink)
    assert record is not None
    assert record.decision == "BLOCK"
    assert record.reason_code == "tool_call_limit_exceeded"
    assert record.user_id == "<unknown>"
    assert record.job_id == "<unknown>"
    assert len(sink.records()) == 1


def test_record_final_outcome_total_on_broken_sink_and_odd_inputs():
    """§13.1 audit is best-effort: a raising sink and malformed inputs
    never raise into the caller."""
    from app.hermes.limits import REASON_TOOL_CALL_LIMIT

    class BrokenSink:
        def record(self, record):
            raise OSError("disk full")

    record = record_final_outcome(
        "research.search", {"bogus": 1}, "capability_schema_invalid", sink=BrokenSink()
    )
    assert record is not None
    assert record.decision == "BLOCK"
    for tool, params in ((None, None), (7, "args"), ("shell", [1, 2])):
        assert record_final_outcome(tool, params, REASON_TOOL_CALL_LIMIT, sink=BrokenSink()) is not None


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
# 6b. Final-outcome fidelity through the full §4 -> §9 -> §12 chain (§13.1)
# ---------------------------------------------------------------------------

def _final_outcome_chain(sink, ledger):
    """The production hook composition: §12 wrapper -> §9 wrapper -> §4 hook."""
    from app.hermes.capabilities import make_capability_validating_hook
    from app.hermes.limits import make_limit_enforcing_hook

    hook = make_pre_tool_call_hook(CONTEXT, audit_sink=sink)
    hook = make_capability_validating_hook(hook)
    return make_limit_enforcing_hook(hook, ledger)


def test_section_4_block_audit_unchanged_through_chain():
    """§4 BLOCK through the full chain emits exactly ONE record — the
    unchanged §4 BLOCK — and no spurious §9/§12 final-outcome record."""
    from app.hermes.limits import JobLimitLedger

    sink = InMemoryAuditSink()
    set_active_audit_sink(sink)
    try:
        hook = _final_outcome_chain(sink, JobLimitLedger(5, 5, 5))
        verdict = hook("shell", {"cmd": "id"})
        assert isinstance(verdict, dict) and verdict.get("action") == "block"
        records = sink.records()
        assert len(records) == 1
        assert records[0].decision == "BLOCK"
        assert records[0].reason_code == "blocked_unknown_tool"
        assert records[0].tool_name == "shell"
    finally:
        set_active_audit_sink(None)


def test_schema_rejection_final_outcome_through_chain():
    """§4 ALLOW + §9 rejection: §4 record stays ALLOW; an additive final
    BLOCK record carries capability_schema_invalid."""
    from app.hermes.capabilities import CAPABILITY_SCHEMA_INVALID
    from app.hermes.limits import JobLimitLedger

    sink = InMemoryAuditSink()
    set_active_audit_sink(sink)
    try:
        hook = _final_outcome_chain(sink, JobLimitLedger(5, 5, 5))
        verdict = hook("research.search", {})  # missing required topic
        assert verdict["action"] == "block"
        assert CAPABILITY_SCHEMA_INVALID in verdict["message"]
        records = sink.records()
        assert [(r.decision, r.reason_code) for r in records] == [
            ("ALLOW", "allowed_typed_capability"),  # §4 — unchanged
            ("BLOCK", CAPABILITY_SCHEMA_INVALID),  # §13.1 final outcome
        ]
    finally:
        set_active_audit_sink(None)


def test_broken_audit_sink_never_alters_decisions():
    """§13.1 audit failures are non-fatal: with a raising sink on the §4
    closure AND the active binding, every decision is unchanged and the
    recorder never raises into the request path."""
    from app.hermes.limits import (
        REASON_PER_CAPABILITY_LIMIT,
        JobLimitLedger,
    )

    class BrokenSink:
        def record(self, record):
            raise OSError("disk full")

    broken = BrokenSink()
    set_active_audit_sink(broken)
    try:
        ledger = JobLimitLedger(5, 1, 5)
        hook = _final_outcome_chain(broken, ledger)
        assert hook("todo_list", {}) is None  # ALLOW stays ALLOW (executes)
        schema_verdict = hook("research.search", {"bogus": 1})  # schema rejection
        assert schema_verdict["action"] == "block"
        limit_verdict = hook("todo_list", {})  # per-capability denial
        assert limit_verdict["action"] == "block"
        assert REASON_PER_CAPABILITY_LIMIT in limit_verdict["message"]
        post_verdict = hook("research.search", {"topic": "x"})  # post-violation
        assert post_verdict["action"] == "block"
        block_verdict = hook("shell", {})  # BLOCK stays BLOCK
        assert block_verdict["action"] == "block"
        assert ledger.violation_code == REASON_PER_CAPABILITY_LIMIT
    finally:
        set_active_audit_sink(None)


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


# ---------------------------------------------------------------------------
# 9. Real Hermes final-outcome persistence integration (§13.1 / §16)
# ---------------------------------------------------------------------------

def _final_outcome_settings(tmp_path: Path, tag: str, **limit_overrides):
    """Settings for a §13.1 integration job (distinct hermes_home per job)."""
    from app.core.config import HERMES_COMMIT_PIN, Settings

    repo_root = Path(__file__).resolve().parents[2]
    base = {
        "hermes_enabled": True,
        "hermes_commit_pin": HERMES_COMMIT_PIN,
        "hermes_plugin_path": str(repo_root / "backend" / "app" / "hermes" / "plugins"),
        "hermes_home": str(tmp_path / f"hermes-root-{tag}"),
        "hermes_max_iterations": 5,
        "hermes_max_execution_seconds": 10.0,
        "hermes_max_tool_calls": 10,
        "hermes_max_tool_calls_per_capability": 5,
        "hermes_max_generation_budget_usd": 1.0,
        "hermes_max_context_tokens": 8_000,
        "hermes_max_blocked_requests": 3,
    }
    base.update(limit_overrides)
    return Settings(**base)


def _final_outcome_request(job_id: str):
    from app.hermes import runtime

    return runtime.HermesJobRequest(
        job_id=job_id,
        task_message=None,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )


def test_real_hermes_persists_schema_and_total_limit_final_outcomes(tmp_path: Path):
    """§13.1 integration: §9 schema rejection and §12 total-limit /
    post-violation denials persist additive final-outcome BLOCK records
    with deterministic reasons; §4 records remain unchanged."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime

    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        hook = next(iter(iter_hook_callbacks("pre_tool_call")))
        schema_verdict = hook("research.search", {})  # §4 ALLOW -> §9 BLOCK
        assert schema_verdict["action"] == "block"
        assert "capability_schema_invalid" in schema_verdict["message"]
        assert hook("research.search", {"topic": "a"}) is None  # allowed (1/2)
        assert hook("todo_list", {}) is None  # allowed (2/2)
        limit_verdict = hook("research.search", {"topic": "b"})  # total limit
        assert limit_verdict["action"] == "block"
        assert "tool_call_limit_exceeded" in limit_verdict["message"]
        post_verdict = hook("todo_list", {})  # post-violation denial
        assert post_verdict["action"] == "block"
        assert "tool_call_limit_exceeded" in post_verdict["message"]
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _final_outcome_settings(
            tmp_path,
            "total",
            hermes_max_tool_calls=2,
            hermes_max_tool_calls_per_capability=2,
            hermes_max_blocked_requests=5,
        )
        res = runtime.run_hermes_job(_final_outcome_request("audit-final-1"), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert

    # §11: the mid-job limit violation fails the job — no silent continuation.
    assert res.status == "failed"
    assert res.error_code == "tool_call_limit_exceeded"

    audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
    assert audit_file.is_file()
    trail = [
        (r.tool_name, r.decision, r.reason_code) for r in FileAuditSink(audit_file).read_records()
    ]
    assert trail == [
        ("research.search", "ALLOW", "allowed_typed_capability"),  # §4 — unchanged
        ("research.search", "BLOCK", "capability_schema_invalid"),  # §13.1 §9 final
        ("research.search", "ALLOW", "allowed_typed_capability"),
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),
        ("research.search", "ALLOW", "allowed_typed_capability"),  # §4 allowed the denied request
        ("research.search", "BLOCK", "tool_call_limit_exceeded"),  # §13.1 §12 final
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),  # §4 unchanged post-violation
        ("todo_list", "BLOCK", "tool_call_limit_exceeded"),  # §13.1 §12 post-violation final
    ]


def test_real_hermes_persists_per_capability_limit_final_outcome(tmp_path: Path):
    """§13.1 integration: the §12 per-capability limit denial and the
    post-violation denial persist final-outcome BLOCK records."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime

    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        hook = next(iter(iter_hook_callbacks("pre_tool_call")))
        assert hook("research.search", {"topic": "a"}) is None  # per-capability 1/1
        verdict = hook("research.search", {"topic": "b"})  # per-capability exceeded
        assert verdict["action"] == "block"
        assert "tool_call_per_capability_limit_exceeded" in verdict["message"]
        post_verdict = hook("todo_list", {})  # post-violation denial
        assert post_verdict["action"] == "block"
        assert "tool_call_per_capability_limit_exceeded" in post_verdict["message"]
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _final_outcome_settings(
            tmp_path, "percap", hermes_max_tool_calls=5, hermes_max_tool_calls_per_capability=1
        )
        res = runtime.run_hermes_job(_final_outcome_request("audit-final-2"), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert

    assert res.status == "failed"
    assert res.error_code == "tool_call_per_capability_limit_exceeded"

    audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
    trail = [
        (r.tool_name, r.decision, r.reason_code) for r in FileAuditSink(audit_file).read_records()
    ]
    assert trail == [
        ("research.search", "ALLOW", "allowed_typed_capability"),
        ("research.search", "ALLOW", "allowed_typed_capability"),  # §4 allowed the denied request
        ("research.search", "BLOCK", "tool_call_per_capability_limit_exceeded"),  # §13.1 final
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),  # §4 unchanged post-violation
        ("todo_list", "BLOCK", "tool_call_per_capability_limit_exceeded"),  # §13.1 post-violation
    ]


def test_real_hermes_persists_blocked_request_limit_final_outcome(tmp_path: Path):
    """§13.1 integration: a fresh §12 blocked-request-limit trip persists a
    final-outcome BLOCK record while §4 BLOCK records pass through unchanged."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime

    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        hook = next(iter(iter_hook_callbacks("pre_tool_call")))
        assert hook("shell", {})["action"] == "block"  # blocked 1/1 — no trip yet
        assert hook("delegate_task", {})["action"] == "block"  # trips 2 > 1
        post_verdict = hook("todo_list", {})  # post-violation denial
        assert post_verdict["action"] == "block"
        assert "blocked_request_limit_exceeded" in post_verdict["message"]
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _final_outcome_settings(tmp_path, "blocked", hermes_max_blocked_requests=1)
        res = runtime.run_hermes_job(_final_outcome_request("audit-final-3"), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert

    assert res.status == "failed"
    assert res.error_code == "blocked_request_limit_exceeded"

    audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
    trail = [
        (r.tool_name, r.decision, r.reason_code) for r in FileAuditSink(audit_file).read_records()
    ]
    assert trail == [
        ("shell", "BLOCK", "blocked_unknown_tool"),  # §4 — unchanged
        ("delegate_task", "BLOCK", "blocked_explicit"),  # §4 — unchanged
        ("delegate_task", "BLOCK", "blocked_request_limit_exceeded"),  # §13.1 §12 trip
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),  # §4 unchanged post-violation
        ("todo_list", "BLOCK", "blocked_request_limit_exceeded"),  # §13.1 post-violation
    ]


# ---------------------------------------------------------------------------
# 10. Job-boundary records (§13)
# ---------------------------------------------------------------------------

def test_hermes_job_audit_record_serialization_round_trip():
    """HermesJobAuditRecord serializes deterministically and reconstructs."""
    from app.hermes.audit import JOB_BOUNDARY_RECORD_TYPE, HermesJobAuditRecord

    record = HermesJobAuditRecord(
        event="JOB_START",
        user_id="u",
        project_id="p",
        job_id="j",
        agent_id="a",
        lineage_id="l",
        runtime_job_id="runtime-job-1",
        hermes_commit="c" * 40,
        hermes_tree="t" * 40,
        hermes_git_verified=True,
        config_sha256="a" * 64,
        plugin_verification="pending",
        limits_snapshot={"allowed_total": 0, "max_tool_calls": 10},
    )
    data = record.to_dict()
    assert data["record_type"] == JOB_BOUNDARY_RECORD_TYPE
    assert data["event"] == "JOB_START"
    assert data["limits_snapshot"] == {"allowed_total": 0, "max_tool_calls": 10}

    restored = HermesJobAuditRecord.from_dict(json.loads(record.to_json()))
    assert restored.event == record.event
    assert restored.audit_id == record.audit_id
    assert restored.hermes_commit == record.hermes_commit
    assert restored.hermes_git_verified is True
    assert restored.limits_snapshot == record.limits_snapshot
    assert restored.duration_seconds is None  # absent -> None, never a crash
    restored_end = HermesJobAuditRecord.from_dict(
        {**data, "event": "JOB_END", "duration_seconds": 1.5, "outcome": "completed"}
    )
    assert restored_end.duration_seconds == 1.5 and restored_end.outcome == "completed"


def test_file_sink_routes_job_and_request_records(tmp_path: Path):
    """The shared store holds both shapes; per-request readers never see
    job-boundary lines and read_job_records() returns only those."""
    from app.hermes.audit import (
        JOB_BOUNDARY_RECORD_TYPE,
        JOB_END,
        JOB_START,
        HermesJobAuditRecord,
    )

    sink = FileAuditSink(tmp_path / "audit" / "mixed.jsonl")
    tool = AuthorizationDecisionAuditRecord(
        user_id="u", project_id="p", job_id="j", agent_id="a", lineage_id="l",
        tool_name="research.search", decision="ALLOW",
        reason_code="allowed_typed_capability", parameter_digest="d",
    )
    start = HermesJobAuditRecord(
        event=JOB_START, user_id="u", project_id="p", job_id="j",
        agent_id="a", lineage_id="l", runtime_job_id="r1",
    )
    end = HermesJobAuditRecord(
        event=JOB_END, user_id="u", project_id="p", job_id="j",
        agent_id="a", lineage_id="l", runtime_job_id="r1", outcome="completed",
        duration_seconds=2.0,
    )
    sink.record(start)
    sink.record(tool)
    sink.record(end)

    requests = sink.read_records()
    assert len(requests) == 1 and requests[0].tool_name == "research.search"
    jobs = sink.read_job_records()
    assert [r.event for r in jobs] == [JOB_START, JOB_END]
    assert jobs[1].outcome == "completed" and jobs[1].duration_seconds == 2.0
    assert JOB_BOUNDARY_RECORD_TYPE in (tmp_path / "audit" / "mixed.jsonl").read_text()

    memory = InMemoryAuditSink()
    memory.record(tool)
    memory.record(end)
    assert len(memory.records()) == 1 and memory.records()[0] == tool
    assert [r.event for r in memory.job_records()] == [JOB_END]


def test_record_job_boundary_writes_and_is_total():
    """record_job_boundary persists to the sink, degrades identity for a
    missing context, and never raises — including on a broken sink."""
    from app.hermes.audit import (
        HermesJobAuditRecord,
        InMemoryAuditSink,
        record_job_boundary,
    )

    class BrokenSink:
        def record(self, record):
            raise OSError("disk full")

    sink = InMemoryAuditSink()
    record = record_job_boundary(
        "JOB_END",
        CONTEXT,
        sink=sink,
        runtime_job_id="r9",
        plugin_verification="verified",
        limits_snapshot={"allowed_total": 1},
        duration_seconds=1.23456789,
        outcome="failed",
        error_code="chat_timeout",
        violation_code=None,
    )
    assert record is not None
    assert record.event == "JOB_END" and record.runtime_job_id == "r9"
    assert record.duration_seconds == 1.234568  # stable numeric rounding
    assert sink.job_records() == [record]
    assert isinstance(sink.job_records()[0], HermesJobAuditRecord)

    # Missing context degrades to <unknown>; broken sink never raises.
    degraded = record_job_boundary("JOB_START", None, sink=BrokenSink())
    assert degraded is not None and degraded.user_id == "<unknown>"
    assert record_job_boundary("JOB_START", None, sink=BrokenSink()) is not None


def test_job_boundary_records_for_successful_job(tmp_path: Path):
    """§13 job-boundary integration: a completed job persists JOB_START and
    JOB_END with full identity, verified pin, config hash, plugin
    verification, ledger snapshots, duration, and outcome — while the
    per-request reader is unaffected by the job lines."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    import hashlib

    from app.core.config import HERMES_COMMIT_PIN, HERMES_TREE_PIN
    from app.hermes import runtime
    from app.hermes.audit import JOB_END, JOB_START

    settings = _final_outcome_settings(tmp_path, "jobstart")
    res = runtime.run_hermes_job(_final_outcome_request("audit-job-1"), settings=settings)
    assert res.status == "completed", (res.error_code, res.error_detail)

    sink = FileAuditSink(Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl")
    jobs = sink.read_job_records()
    assert [r.event for r in jobs] == [JOB_START, JOB_END]
    start, end = jobs

    for record in (start, end):  # job identity block matches §4 records
        assert record.user_id == CONTEXT.user_id
        assert record.project_id == CONTEXT.project_id
        assert record.job_id == CONTEXT.job_id
        assert record.agent_id == CONTEXT.agent_id
        assert record.lineage_id == CONTEXT.lineage_id
        assert record.runtime_job_id == "audit-job-1"
        assert record.occurred_at

    # JOB_START: verified source identity, deterministic config digest,
    # honest pending plugin state, initial (zeroed) ledger snapshot.
    assert start.hermes_commit == HERMES_COMMIT_PIN
    assert start.hermes_tree == HERMES_TREE_PIN
    assert isinstance(start.hermes_git_verified, bool)
    assert start.config_sha256 == hashlib.sha256(
        runtime.render_config_yaml().encode("utf-8")
    ).hexdigest()
    assert start.plugin_verification == "pending"
    assert start.limits_snapshot == {
        "allowed_total": 0,
        "blocked_total": 0,
        "max_tool_calls": 10,
        "max_tool_calls_per_capability": 5,
        "max_blocked_requests": 3,
    }

    # JOB_END: real outcome, actual verification result, duration, counters.
    assert end.outcome == "completed" and end.error_code is None
    assert end.violation_code is None
    assert end.plugin_verification == "verified"
    assert isinstance(end.duration_seconds, float) and end.duration_seconds >= 0
    assert end.limits_snapshot == start.limits_snapshot  # nothing executed

    # Per-request reader unaffected by the job-boundary lines.
    assert sink.read_records() == []


def test_job_boundary_records_for_failed_limit_job(tmp_path: Path):
    """A §12-violation failure persists JOB_START/JOB_END with the failure
    outcome, the violation code, and the FINAL ledger state — and the §4 /
    §13.1 per-request trail remains exactly as before this slice."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime
    from app.hermes.audit import JOB_END, JOB_START

    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        hook = next(iter(iter_hook_callbacks("pre_tool_call")))
        assert hook("todo_list", {}) is None  # 1/1 allowed
        verdict = hook("todo_list", {})  # total limit exceeded
        assert verdict["action"] == "block"
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _final_outcome_settings(
            tmp_path,
            "jobfail",
            hermes_max_tool_calls=1,
            hermes_max_tool_calls_per_capability=1,
            hermes_max_blocked_requests=5,
        )
        res = runtime.run_hermes_job(_final_outcome_request("audit-job-2"), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert

    assert res.status == "failed"
    assert res.error_code == "tool_call_limit_exceeded"

    sink = FileAuditSink(Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl")
    jobs = sink.read_job_records()
    assert [r.event for r in jobs] == [JOB_START, JOB_END]
    start, end = jobs
    assert start.plugin_verification == "pending"
    assert end.outcome == "failed"
    assert end.error_code == "tool_call_limit_exceeded"
    assert end.violation_code == "tool_call_limit_exceeded"
    assert end.plugin_verification == "verified"
    assert isinstance(end.duration_seconds, float) and end.duration_seconds >= 0
    assert end.limits_snapshot == {
        "allowed_total": 1,
        "blocked_total": 0,
        "max_tool_calls": 1,
        "max_tool_calls_per_capability": 1,
        "max_blocked_requests": 5,
    }

    # §4 + §13.1 per-request records: unchanged, exactly the §13.1 trail.
    trail = [(r.tool_name, r.decision, r.reason_code) for r in sink.read_records()]
    assert trail == [
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),
        ("todo_list", "ALLOW", "allowed_sanctioned_native_tool"),
        ("todo_list", "BLOCK", "tool_call_limit_exceeded"),
    ]


def test_job_end_persisted_before_cleanup_on_timeout(tmp_path: Path):
    """A watchdog-timeout job still persists JOB_END BEFORE sink cleanup and
    job-home deletion — the record outlives the disposable Hermes state."""
    import importlib.util
    import os
    import time as _time

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime
    from app.hermes.audit import JOB_END, JOB_START

    class _BlockingAgent:
        # Immutable stub attributes: nothing in the stubbed path reads them;
        # the runtime only calls .chat()/.close() on the returned agent.
        enabled_toolsets = ("todo",)
        valid_tool_names = frozenset({"todo_list"})
        api_key = "aryaos-explicit-test-key"
        base_url = "http://127.0.0.1:9/v1"

        def chat(self, _message):
            _time.sleep(30)
            return "never"

        def close(self):
            pass

    original_construct = runtime._construct_agent
    runtime._construct_agent = lambda request, config, baseline_threads: _BlockingAgent()
    try:
        settings = _final_outcome_settings(
            tmp_path, "jobtimeout", hermes_max_execution_seconds=0.5
        )
        timeout_request = runtime.HermesJobRequest(
            job_id="audit-job-3",
            task_message="never returns",  # the chat path must actually run
            authorization_context=CONTEXT,
            provider="openai",
            base_url="http://127.0.0.1:9/v1",
            api_key="aryaos-explicit-test-key",
            model="aryaos-test-model",
        )
        res = runtime.run_hermes_job(timeout_request, settings=settings)
    finally:
        runtime._construct_agent = original_construct

    assert res.status == "failed"
    assert res.error_code == "chat_timeout"

    # JOB_END was persisted (before cleanup) with the timeout outcome.
    sink = FileAuditSink(Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl")
    jobs = sink.read_job_records()
    assert [r.event for r in jobs] == [JOB_START, JOB_END]
    end = jobs[1]
    assert end.outcome == "failed" and end.error_code == "chat_timeout"
    assert end.plugin_verification == "verified"  # construction stub ran post-verification
    assert end.duration_seconds >= 0.4  # the watchdog fired, then JOB_END

    # Normal Hermes job-home cleanup still occurred; runtime env cleared.
    assert not (Path(settings.hermes_home) / "jobs" / "audit-job-3").exists()
    assert "HERMES_HOME" not in os.environ
    assert "HERMES_BUNDLED_PLUGINS" not in os.environ


def test_job_boundary_audit_failure_is_not_fatal(tmp_path: Path, monkeypatch):
    """A persistently failing audit sink changes nothing: the job completes,
    cleanup runs, and no audit error escapes into the job result."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime
    from app.hermes.audit import FileAuditSink as _FileSink

    def _raising_record(self, record):
        raise OSError("disk full")

    monkeypatch.setattr(_FileSink, "record", _raising_record)
    settings = _final_outcome_settings(tmp_path, "jobsink")
    res = runtime.run_hermes_job(_final_outcome_request("audit-job-4"), settings=settings)
    assert res.status == "completed", (res.error_code, res.error_detail)
    # Cleanup still ran (job home deleted) despite every audit write failing.
    assert not (Path(settings.hermes_home) / "jobs" / "audit-job-4").exists()


def test_job_boundary_records_contain_no_secrets(tmp_path: Path):
    """The persisted job-boundary records carry the config as a SHA-256
    digest only: no API keys, no raw config.yaml contents, no env values."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes import runtime

    canary_key = "aryaos-secret-canary-4f8a1c"
    request = runtime.HermesJobRequest(
        job_id="audit-job-5",
        task_message=None,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key=canary_key,
        model="aryaos-test-model",
    )
    settings = _final_outcome_settings(tmp_path, "jobsecret")
    res = runtime.run_hermes_job(request, settings=settings)
    assert res.status == "completed", (res.error_code, res.error_detail)

    audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
    raw = audit_file.read_text(encoding="utf-8")
    assert canary_key not in raw  # no credentials ever persisted
    assert "tirith_fail_open" not in raw  # config contents stay out; digest only
    assert "plugins:" not in raw
    jobs = FileAuditSink(audit_file).read_job_records()
    assert [r.event for r in jobs] == ["JOB_START", "JOB_END"]
    start_digest = jobs[0].config_sha256
    assert isinstance(start_digest, str) and len(start_digest) == 64
    assert all(c in "0123456789abcdef" for c in start_digest)

