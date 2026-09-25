"""Explicit Hermes execution-path acceptance tests — §16 T3/T4 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §16 T3
(``test_hermes_invoke_tool_path_blocked``: a tool request routed via
Hermes' ``invoke_tool`` path with an unauthorized tool is BLOCKed) and T4
(``test_hermes_inline_executor_path_blocked``: the same via the inline /
managed sequential executor path), under §4.2 (every tool request,
regardless of call path, passes the AryaOS policy gate).

Pinned-source paths exercised (commit c0d7294769a38c17ceae51d8f7995e66e1dcae27):

- T3 — ``agent/agent_runtime_helpers.py:2364`` ``invoke_tool``: the
  concurrent-path invoker fires ``pre_tool_call`` via
  ``_pre_tool_block_message`` (:2348-2361 → hermes_cli/plugins
  ``_dispatch_pre_tool_call_hooks``) and, on a block, returns
  ``json.dumps({"error": block_message})`` at :2394-2402 — BEFORE any
  executor resolution (:2404) or registry dispatch (:2438).
- T4 — ``agent/tool_executor.py:1773`` ``execute_tool_calls_sequential``
  (the inline/managed sequential executor; the segmented dispatcher at
  ``run_agent.py:1336`` routes sequential segments here): parse (:451,
  scope only gates the Tool-Search bridge, :390-433) → dispatch resolution
  (:1600; INLINE_TOOL_EXECUTORS first, :1607-1611) →
  ``_run_agent_tool_execution_middleware`` (:723) →
  ``_dispatch_authorized_once`` (:668) → ``_pre_tool_block`` (:651-665 →
  the same plugin dispatch) → BLOCK synthesizes the result (:638-648)
  with the ``execute`` callable never invoked.

Both tests run the REAL pinned Hermes mid-job (the plugin registry, job
home, §12 ledger, and §13 audit sink are live), drive an authorized
control call through the same path (proving the path genuinely executes
when the gate allows), and prove via a registry-dispatch spy that the
unauthorized call never reaches execution. Per §16, a missing pinned
Hermes source is an explicit integration-environment FAILURE.
"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.audit import FileAuditSink
from app.hermes.policy import AuthorizationContext
from app.hermes.runtime import HermesJobRequest, run_hermes_job

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = REPO_ROOT / "backend" / "app" / "hermes" / "plugins"

CONTEXT = AuthorizationContext(
    user_id="u", project_id="p", job_id="j", agent_id="a", lineage_id="l"
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None

# The deterministic §4 BLOCK message for an unknown tool (policy.py _block).
_GATE_PREFIX = "Blocked by AryaOS policy gate"
_SHELL_BLOCK_REASON = f"{_GATE_PREFIX} (blocked_unknown_tool): 'shell'"


def _valid_settings(tmp_path: Path) -> Settings:
    return Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(PLUGIN_PATH),
        hermes_home=str(tmp_path / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
    )


def _request(job_id: str) -> HermesJobRequest:
    return HermesJobRequest(
        job_id=job_id,
        task_message=None,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )


@pytest.fixture(autouse=True)
def _clean_hermes_env(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("HERMES_") or name.startswith("LANGFUSE_"):
            monkeypatch.delenv(name, raising=False)


def _audit_trail(settings: Settings) -> list[tuple[str, str, str]]:
    """(tool_name, decision, reason_code) per §4/§13.1 record in the job's audit file."""
    audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
    assert audit_file.is_file()
    return [
        (r.tool_name, r.decision, r.reason_code) for r in FileAuditSink(audit_file).read_records()
    ]


def _spy_on_registry_dispatch(monkeypatch, dispatch_log: list[str]) -> None:
    """Record every name reaching model_tools.handle_function_call (the one
    registry dispatch point both paths fall through to when not blocked)."""
    import model_tools

    real = model_tools.handle_function_call

    def _recording(name, args, task_id, *extra, **kwargs):
        dispatch_log.append(name)
        return real(name, args, task_id, *extra, **kwargs)

    monkeypatch.setattr(model_tools, "handle_function_call", _recording)


# ---------------------------------------------------------------------------
# T3 — the invoke_tool call path (§16 T3)
# ---------------------------------------------------------------------------

def test_hermes_invoke_tool_path_blocked(tmp_path: Path, monkeypatch):
    """An unauthorized tool request routed through Hermes' invoke_tool path
    is intercepted by the registered AryaOS policy gate: BLOCK is the tool
    result, the registry is never dispatched for it, and the request is
    audited — while an authorized control call through the SAME path
    executes (the path is live, not vacuously blocking)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.capabilities as caps
    from app.hermes import runtime

    executed: list[dict] = []

    class _SpyService:
        async def discover_trends(self, topic_hint, *a, **k):
            executed.append({"topic": topic_hint})
            return []

    monkeypatch.setattr(caps, "_TREND_SERVICE", _SpyService())

    captured: dict = {}
    dispatch_log: list[str] = []
    original_construct = runtime._construct_agent

    def constructing_agent(request, config, baseline_threads):
        agent = original_construct(request, config, baseline_threads)
        _spy_on_registry_dispatch(monkeypatch, dispatch_log)
        from agent.agent_runtime_helpers import invoke_tool

        # Unauthorized tool via the invoke_tool path (concurrent invoker).
        captured["blocked_result"] = invoke_tool(
            agent, "shell", {"cmd": "id"}, "t3-shell-task", tool_call_id="t3-shell-call"
        )
        # Authorized control through the SAME path: §4 allows, §9 validates,
        # the real registry handler executes the (stubbed) binding.
        captured["allowed_result"] = invoke_tool(
            agent, "research.search", {"topic": "ai"}, "t3-allowed-task", tool_call_id="t3-allowed-call"
        )
        return agent

    runtime._construct_agent = constructing_agent
    try:
        settings = _valid_settings(tmp_path)
        result = run_hermes_job(_request("paths-t3"), settings=settings)
    finally:
        runtime._construct_agent = original_construct

    assert result.status == "completed", (result.error_code, result.error_detail)

    # The gate's BLOCK message is the invoke_tool result (returned at
    # agent_runtime_helpers.py:2394-2402, before any executor resolution).
    import json

    blocked_payload = json.loads(captured["blocked_result"])
    assert blocked_payload["error"] == _SHELL_BLOCK_REASON

    # The authorized control executed through the same path (path is live);
    # the unauthorized name NEVER reached the one registry dispatch point.
    allowed_payload = json.loads(captured["allowed_result"])
    assert "error" not in allowed_payload
    assert executed == [{"topic": "ai"}]
    assert dispatch_log == ["research.search"], dispatch_log

    # The blocked request reached the AryaOS gate: §4 audit trail records it.
    trail = _audit_trail(settings)
    assert ("shell", "BLOCK", "blocked_unknown_tool") in trail
    assert ("research.search", "ALLOW", "allowed_typed_capability") in trail


# ---------------------------------------------------------------------------
# T4 — the inline executor / managed sequential path (§16 T4)
# ---------------------------------------------------------------------------

def test_hermes_inline_executor_path_blocked(tmp_path: Path, monkeypatch):
    """An unauthorized tool request routed through Hermes' inline/managed
    sequential executor is intercepted by the registered AryaOS policy gate:
    the BLOCK message becomes the tool result, the execute callable is never
    invoked for it, and the request is audited — while an authorized
    inline-executor tool (todo_list, INLINE_TOOL_EXECUTORS) in the SAME
    batch executes normally (the path is live, not vacuously blocking)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    from app.hermes import runtime

    captured: dict = {}
    dispatch_log: list[str] = []
    original_construct = runtime._construct_agent

    def constructing_agent(request, config, baseline_threads):
        agent = original_construct(request, config, baseline_threads)
        _spy_on_registry_dispatch(monkeypatch, dispatch_log)
        from agent.tool_executor import execute_tool_calls_sequential

        # One real assistant turn batch: the unauthorized call first, the
        # authorized inline-executor control second (OpenAI tool-call shape).
        assistant = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="t4-shell-call",
                    type="function",
                    function=SimpleNamespace(name="shell", arguments='{"cmd": "id"}'),
                ),
                SimpleNamespace(
                    id="t4-todo-call",
                    type="function",
                    function=SimpleNamespace(name="todo_list", arguments="{}"),
                ),
            ]
        )
        messages: list = []
        execute_tool_calls_sequential(agent, assistant, messages, "t4-task")
        captured["messages"] = messages
        return agent

    runtime._construct_agent = constructing_agent
    try:
        settings = _valid_settings(tmp_path)
        result = run_hermes_job(_request("paths-t4"), settings=settings)
    finally:
        runtime._construct_agent = original_construct

    assert result.status == "completed", (result.error_code, result.error_detail)

    # One tool-result message per assistant tool call (role alternation).
    messages = captured["messages"]
    assert len(messages) == 2
    shell_msg, todo_msg = messages
    assert shell_msg["role"] == "tool" and shell_msg["tool_name"] == "shell"
    assert todo_msg["role"] == "tool" and todo_msg["tool_name"] == "todo_list"

    # The unauthorized call's result IS the gate's BLOCK message
    # (tool_executor.py:638-648 _blocked_tool_result; execute never ran).
    import json

    blocked_payload = json.loads(shell_msg["content"])
    assert blocked_payload["error"] == _SHELL_BLOCK_REASON

    # The authorized control executed through the inline executor
    # (INLINE_TOOL_EXECUTORS["todo_list"]): a real todo_list result, not a
    # gate block — proving the batch's execution machinery ran.
    todo_payload = json.loads(todo_msg["content"])
    assert "todos" in todo_payload and "summary" in todo_payload

    # Neither call reached the registry dispatch point: shell was blocked
    # before dispatch, and todo_list ran through the INLINE executor.
    assert dispatch_log == [], dispatch_log

    # Both requests reached the AryaOS gate: §4 audit trail records the
    # block and the allow.
    trail = _audit_trail(settings)
    assert ("shell", "BLOCK", "blocked_unknown_tool") in trail
    assert ("todo_list", "ALLOW", "allowed_sanctioned_native_tool") in trail
