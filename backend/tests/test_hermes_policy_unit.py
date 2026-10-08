"""Unit tests for the AryaOS-owned Hermes policy gate (V2), §4.

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §4.1–§4.5, §7, §9,
§10, §11. These tests exercise ONLY the AryaOS-owned decision core, the
Hermes-shaped hook adapter, and the §4.3 verification assertion. Hermes
is not imported, faked, or required. Agent-level acceptance tests
(T1–T5) require the §3 runtime adapter and are intentionally not here.
"""
import sys

import pytest

from app.hermes.policy import (
    EXPLICITLY_BLOCKED_TOOLS,
    SANCTIONED_NATIVE_TOOLS,
    TYPED_CAPABILITIES,
    AuthorizationContext,
    HermesPolicyPluginError,
    PolicyDecision,
    evaluate_tool_request,
    make_pre_tool_call_hook,
    register_policy_plugin,
    verify_policy_plugin_registered,
)
from app.hermes.toolsets import HERMES_TOOLSET_ALLOWLIST

CONTEXT = AuthorizationContext(
    user_id="user-1",
    project_id="project-1",
    job_id="job-1",
    workflow_run_id="run-1",
    agent_id="agent-1",
    lineage_id="lineage-1",
)


# ---------------------------------------------------------------------------
# 1. Frozen authorization universe
# ---------------------------------------------------------------------------

def test_typed_capabilities_match_spec_section_9_table():
    assert TYPED_CAPABILITIES == frozenset(
        {
            "research.search",
            "research.get",
            "story.create",
            "memory.retrieve",
            "provider.generate",
            "asset.get",
            "agent.request",
            "evaluation.run",
            "publishing.request",
        }
    )


def test_no_god_tool_in_capability_set():
    """§4.5: no generic aryaos_api_call / run_anything style entry."""
    for name in TYPED_CAPABILITIES:
        assert name.count(".") == 1, name  # <domain>.<operation>, nothing generic


def test_delegate_task_explicitly_blocked_by_name():
    """§7: explicit name-based block, independent of toolset config."""
    assert EXPLICITLY_BLOCKED_TOOLS == ("delegate_task",)
    assert evaluate_tool_request("delegate_task", {"task": "x"}, CONTEXT).reason_code == "blocked_explicit"


def test_sanctioned_native_tools_match_section_5_1_allowlist_resolution():
    """The native-tool sanction is exactly the tool surface of the §5.1
    frozen allowlist's STATIC entry ("todo" -> ["todo_list"], pinned
    toolsets.py:127). The allowlist also carries "aryaos" — the §9
    runtime-registered capability toolset, whose tools are NOT native
    (they are governed by the §9 registry, not SANCTIONED_NATIVE_TOOLS)."""
    assert SANCTIONED_NATIVE_TOOLS == frozenset({"todo_list"})
    assert HERMES_TOOLSET_ALLOWLIST == ("aryaos", "todo")


def test_authorization_universes_are_disjoint():
    assert not (TYPED_CAPABILITIES & SANCTIONED_NATIVE_TOOLS)
    assert not (TYPED_CAPABILITIES & set(EXPLICITLY_BLOCKED_TOOLS))
    assert not (SANCTIONED_NATIVE_TOOLS & set(EXPLICITLY_BLOCKED_TOOLS))


# ---------------------------------------------------------------------------
# 2. ALLOW only under all required conditions (§4.2)
# ---------------------------------------------------------------------------

def test_typed_capability_with_valid_context_allowed():
    for capability in sorted(TYPED_CAPABILITIES):
        decision = evaluate_tool_request(capability, {"query": "x"}, CONTEXT)
        assert decision.allowed, capability
        assert decision.reason_code == "allowed_typed_capability"


def test_sanctioned_native_tool_with_valid_context_allowed():
    decision = evaluate_tool_request("todo_list", {"todos": []}, CONTEXT)
    assert decision.allowed
    assert decision.reason_code == "allowed_sanctioned_native_tool"


def test_allow_requires_valid_context():
    """An authorized tool name with a missing/invalid context is BLOCK
    (§11 'Invalid authorization context')."""
    bad_contexts = [
        None,
        {},
        "context",
        AuthorizationContext(user_id="", project_id="p", job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"),
        AuthorizationContext(user_id="u", project_id=" ", job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"),
        AuthorizationContext(user_id="u", project_id="p", job_id=None, workflow_run_id="w", agent_id="a", lineage_id="l"),
    ]
    for bad in bad_contexts:
        decision = evaluate_tool_request("research.search", {}, bad)
        assert not decision.allowed, bad
        assert decision.reason_code.startswith("blocked_invalid_context")
        assert decision.message


# ---------------------------------------------------------------------------
# 2b. §10.1 workflow_run_id (identity field, fail-closed like the rest)
# ---------------------------------------------------------------------------

def test_workflow_run_id_valid_context_authorizes_unchanged():
    """A repository-conforming workflow_run_id (non-empty string — the same
    contract as project_id, itself a DB-UUID identifier) changes no §4
    semantics: the existing decisions and reason codes are identical."""
    for run_id in ("run-789", "550e8400-e29b-41d4-a716-446655440000"):
        context = AuthorizationContext(
            user_id="u", project_id="p", job_id="j",
            workflow_run_id=run_id, agent_id="a", lineage_id="l",
        )
        allowed = evaluate_tool_request("research.search", {}, context)
        assert allowed.allowed and allowed.reason_code == "allowed_typed_capability"
        native = evaluate_tool_request("todo_list", {}, context)
        assert native.allowed and native.reason_code == "allowed_sanctioned_native_tool"
        blocked = evaluate_tool_request("shell", {}, context)
        assert not blocked.allowed and blocked.reason_code == "blocked_unknown_tool"


def test_workflow_run_id_missing_empty_or_wrong_type_blocks():
    """§10/§11: a missing, empty, blank, or wrong-typed workflow_run_id is
    an invalid authorization context -> BLOCK with the deterministic field
    reason code (same fail-closed pattern as the other identity fields)."""
    for bad_run in (None, "", "   ", 7, []):
        context = AuthorizationContext(
            user_id="u", project_id="p", job_id="j",
            workflow_run_id=bad_run, agent_id="a", lineage_id="l",
        )
        decision = evaluate_tool_request("research.search", {}, context)
        assert not decision.allowed, bad_run
        assert decision.reason_code == "blocked_invalid_context_field:workflow_run_id"
        assert decision.message


def test_authorization_context_is_frozen():
    """Immutability (§10): every identity field — workflow_run_id included —
    rejects mutation identically after construction."""
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        CONTEXT.workflow_run_id = "other-run"
    with pytest.raises(dataclasses.FrozenInstanceError):
        CONTEXT.user_id = "other-user"


# ---------------------------------------------------------------------------
# 3. BLOCK universe (§4.2/§4.5 — everything else)
# ---------------------------------------------------------------------------

def test_unknown_and_dangerous_tools_blocked():
    """T1-style: tools outside the authorized universe -> BLOCK. Includes
    every dangerous category representative and god-tool attempts."""
    for name in (
        "shell",
        "terminal",
        "file_write",
        "write_file",
        "browser_navigate",
        "execute_code",
        "cronjob_manage",
        "memory",
        "session_search",
        "manage_connections",
        "aryaos_api_call",
        "run_anything",
        "http_request",
        "todo",
        "todo_list_extra",
        "",
        "   ",
        123,
        None,
        ["research.search"],
    ):
        decision = evaluate_tool_request(name, {}, CONTEXT)
        assert not decision.allowed, name
        assert decision.reason_code in ("blocked_unknown_tool", "blocked_malformed_tool_name")
        assert decision.message


def test_malformed_parameters_blocked():
    for bad in ("args", 42, ["a"], ("a",), {1: 2}):
        decision = evaluate_tool_request("research.search", bad, CONTEXT)
        assert not decision.allowed
        assert decision.reason_code == "blocked_malformed_parameters"


def test_parameters_none_is_well_formed():
    decision = evaluate_tool_request("research.get", None, CONTEXT)
    assert decision.allowed


def test_block_messages_never_contain_parameter_values():
    secret = "SECRET-PARAMETER-VALUE"
    decision = evaluate_tool_request("shell", {"password": secret}, CONTEXT)
    assert not decision.allowed
    assert secret not in decision.message


# ---------------------------------------------------------------------------
# 4. Fail-closed evaluation (§4.4) — never raises
# ---------------------------------------------------------------------------

def test_evaluation_never_raises():
    """Hostile inputs and a context whose introspection could fail must all
    produce PolicyDecisions, not exceptions (a raising callback would fail
    OPEN through Hermes' dispatch wrapper, model_tools.py:780 at the pin).
    Note: parameter VALUES are not schema-validated at this layer (§9
    binding work); structure (dict with str keys) is."""
    hostile_contexts = [None, {}, "context", object(), 7]
    for ctx in hostile_contexts:
        decision = evaluate_tool_request("research.search", {}, ctx)
        assert isinstance(decision, PolicyDecision)
        assert not decision.allowed
    for tool_name in (object(), 123, None, ["research.search"]):
        decision = evaluate_tool_request(tool_name, {}, CONTEXT)
        assert isinstance(decision, PolicyDecision)
        assert not decision.allowed
    # Weird parameter values must not raise either (decision shape only).
    assert isinstance(evaluate_tool_request("research.search", {"x": object()}, CONTEXT), PolicyDecision)
    assert isinstance(evaluate_tool_request(object(), object(), object()), PolicyDecision)


def test_internal_failure_blocks(monkeypatch):
    """A crashing internal check must surface as blocked_internal_error,
    never as an exception (§4.4)."""
    import app.hermes.policy as policy

    monkeypatch.setattr(policy, "_context_violation", None)  # not callable -> TypeError inside
    decision = policy.evaluate_tool_request("research.search", {}, CONTEXT)
    assert not decision.allowed
    assert decision.reason_code == "blocked_internal_error"


# ---------------------------------------------------------------------------
# 5. Determinism / repeated invocation
# ---------------------------------------------------------------------------

def test_deterministic_and_repeatable():
    for _ in range(3):
        assert evaluate_tool_request("research.search", {"q": 1}, CONTEXT) == evaluate_tool_request(
            "research.search", {"q": 1}, CONTEXT
        )
        assert evaluate_tool_request("shell", {}, CONTEXT) == evaluate_tool_request("shell", {}, CONTEXT)


# ---------------------------------------------------------------------------
# 6. Hermes-shaped hook adapter (pinned contract)
# ---------------------------------------------------------------------------

class _RecordingContext:
    def __init__(self):
        self.registrations = []

    def register_hook(self, hook_name, callback):
        self.registrations.append((hook_name, callback))
        return None


def test_hook_returns_none_for_allow():
    hook = make_pre_tool_call_hook(CONTEXT)
    assert hook("research.search", {"query": "x"}, session_id="s", turn_id="t") is None
    assert hook("todo_list", {"todos": []}) is None


def test_hook_returns_block_directive_with_non_empty_message():
    """Pinned contract: block requires {"action": "block", "message": str};
    a message-less block directive is IGNORED by Hermes (plugins.py:1890)
    — i.e. would fail open. Every BLOCK must carry a message."""
    hook = make_pre_tool_call_hook(CONTEXT)
    result = hook("shell", {}, session_id="s")
    assert set(result) == {"action", "message"}
    assert result["action"] == "block"
    assert isinstance(result["message"], str) and result["message"].strip()


def test_hook_never_returns_modify_or_approve():
    hook = make_pre_tool_call_hook(CONTEXT)
    for name in ("shell", "delegate_task", "unknown", "research.search", "todo_list", ""):
        result = hook(name, {} if name else None)
        assert result is None or (isinstance(result, dict) and result.get("action") == "block"), name


def test_hook_tolerates_extra_identity_kwargs():
    hook = make_pre_tool_call_hook(CONTEXT)
    assert hook(
        "research.search",
        {},
        task_id="t",
        session_id="s",
        tool_call_id="c",
        turn_id="u",
        api_request_id="a",
        middleware_trace=[],
    ) is None


def test_register_policy_plugin_registers_pre_tool_call():
    ctx = _RecordingContext()
    register_policy_plugin(ctx, CONTEXT)
    assert len(ctx.registrations) == 1
    hook_name, callback = ctx.registrations[0]
    assert hook_name == "pre_tool_call"
    assert callable(callback)


# ---------------------------------------------------------------------------
# 7. §4.3 fail-closed plugin registration assertion
# ---------------------------------------------------------------------------

def test_verification_passes_with_registered_policy_callback():
    hook = make_pre_tool_call_hook(CONTEXT)
    verify_policy_plugin_registered([hook])
    verify_policy_plugin_registered((hook,))
    verify_policy_plugin_registered([some_foreign_callback, hook])


def some_foreign_callback(**_kwargs):  # pragma: no cover - test fixture
    return None


def test_verification_fails_on_absent_silent_skip_or_foreign_only():
    """§4.3: plugin dir misconfigured, load failure, or silent skip all
    surface as policy_plugin_missing — the caller refuses to start."""
    for callbacks in ([], (), None, "not-a-list", [some_foreign_callback], [object()]):
        with pytest.raises(HermesPolicyPluginError) as exc_info:
            verify_policy_plugin_registered(callbacks)
        codes = {code for code, _ in exc_info.value.violations}
        assert codes == {"policy_plugin_missing"}


def test_verification_fails_on_hostile_introspection():
    class Hostile:
        def __iter__(self):
            raise RuntimeError("boom")

    with pytest.raises(HermesPolicyPluginError):
        verify_policy_plugin_registered(Hostile())


# ---------------------------------------------------------------------------
# 8. Side-effect freedom / no Hermes import
# ---------------------------------------------------------------------------

def test_no_hermes_import_and_no_side_effects():
    """Import the policy module in a FRESH process and assert the import is
    side-effect free. (Previously this reloaded the module in-process; the
    reload re-executes the module and replaces AuthorizationContext with a
    new class object, breaking every isinstance() check — including the
    policy gate's own context validation — for the rest of the test
    process. Never reload app.hermes.policy in-process.)"""
    import subprocess

    code = (
        "import os, sys\n"
        "sys.path.insert(0, 'backend')\n"
        "before = dict(os.environ)\n"
        "import app.hermes.policy\n"
        "assert dict(os.environ) == before, 'policy import mutated the environment'\n"
        "assert not any(m == 'model_tools' or m.startswith(('hermes', 'hermes_', 'hermes_cli', 'plugins'))\n"
        "               for m in sys.modules), 'policy import pulled in Hermes'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
