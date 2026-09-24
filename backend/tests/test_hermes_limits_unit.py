"""Unit tests for the §12 per-job resource-limit ledger (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §12 (limits exist,
are configurable, are finite, and are enforced even if Hermes ignores or
misreports them), §11 (deny further calls on violation; job failed; no
silent continuation; malformed/blocked requests counted against the
job's limit).

Unit tests exercise the ledger and wrapper directly (no Hermes). The
integration tests run the REAL pinned Hermes through the registered
pre_tool_call hook and the runtime boundary. Per §16, a missing pinned
Hermes source is an explicit integration-environment FAILURE.
"""
import importlib.util
import os
import threading
from pathlib import Path

import pytest

from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.limits import (
    REASON_BLOCKED_LIMIT,
    REASON_LIMIT_CHECK_ERROR,
    REASON_PER_CAPABILITY_LIMIT,
    REASON_TOOL_CALL_LIMIT,
    JobLimitLedger,
    make_limit_enforcing_hook,
)
from app.hermes.policy import (
    POLICY_PLUGIN_MARKER,
    AuthorizationContext,
    make_pre_tool_call_hook,
)
from app.hermes.runtime import HermesJobRequest, run_hermes_job

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = REPO_ROOT / "backend" / "app" / "hermes" / "plugins"

CONTEXT = AuthorizationContext(
    user_id="u", project_id="p", job_id="j", agent_id="a", lineage_id="l"
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None


def _valid_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
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
    base.update(overrides)
    return Settings(**base)


def _request(job_id: str = "lim-1", task_message: str | None = None) -> HermesJobRequest:
    return HermesJobRequest(
        job_id=job_id,
        task_message=task_message,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )


def _base_hook():
    return make_pre_tool_call_hook(CONTEXT)


@pytest.fixture(autouse=True)
def _clean_hermes_env(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("HERMES_") or name.startswith("LANGFUSE_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# 1. Ledger counting semantics
# ---------------------------------------------------------------------------

def test_allowed_calls_counted_within_limits():
    ledger = JobLimitLedger(max_tool_calls=3, max_tool_calls_per_capability=2, max_blocked_requests=2)
    assert ledger.record("todo_list", allowed_by_policy=True) is None
    assert ledger.record("todo_list", allowed_by_policy=True) is None
    assert ledger.counts()["allowed_total"] == 2
    assert ledger.violation_code is None


def test_total_limit_blocks_nth_call_before_execution():
    ledger = JobLimitLedger(max_tool_calls=2, max_tool_calls_per_capability=10, max_blocked_requests=5)
    assert ledger.record("todo_list", True) is None
    assert ledger.record("research.search", True) is None
    third = ledger.record("research.get", True)
    assert third == REASON_TOOL_CALL_LIMIT
    assert ledger.violation_code == REASON_TOOL_CALL_LIMIT
    # Nothing was granted past the limit.
    assert ledger.counts()["allowed_total"] == 2
    # Every further request is denied with the violation code.
    assert ledger.record("todo_list", True) == REASON_TOOL_CALL_LIMIT


def test_per_capability_limit_partitioned_by_tool_name():
    ledger = JobLimitLedger(max_tool_calls=10, max_tool_calls_per_capability=2, max_blocked_requests=5)
    assert ledger.record("todo_list", True) is None
    assert ledger.record("research.search", True) is None  # separate bucket
    assert ledger.record("research.search", True) is None
    # todo_list still has its full budget — buckets are independent.
    assert ledger.record("todo_list", True) is None
    assert ledger.record("todo_list", True) is REASON_PER_CAPABILITY_LIMIT
    assert ledger.violation_code == REASON_PER_CAPABILITY_LIMIT
    # §11: after the violation every further request is denied.
    assert ledger.record("research.get", True) is REASON_PER_CAPABILITY_LIMIT


def test_blocked_requests_counted_against_own_limit():
    ledger = JobLimitLedger(max_tool_calls=10, max_tool_calls_per_capability=5, max_blocked_requests=2)
    assert ledger.record("shell", False) is None
    assert ledger.record("delegate_task", False) is None
    # Third blocked attempt trips the blocked-request limit; the caller
    # still returns the §4 directive verbatim (record returns None).
    assert ledger.record("unknown_tool", False) is None
    assert ledger.violation_code == REASON_BLOCKED_LIMIT
    # Blocked attempts never count as executed tool calls.
    assert ledger.counts()["allowed_total"] == 0
    assert ledger.counts()["blocked_total"] == 3


def test_after_violation_all_requests_denied():
    ledger = JobLimitLedger(max_tool_calls=1, max_tool_calls_per_capability=1, max_blocked_requests=1)
    assert ledger.record("todo_list", True) is None
    assert ledger.record("todo_list", True) == REASON_TOOL_CALL_LIMIT
    assert ledger.record("other", True) == REASON_TOOL_CALL_LIMIT
    assert ledger.record("shell", False) == REASON_TOOL_CALL_LIMIT


def test_non_positive_limits_rejected():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            JobLimitLedger(bad, 1, 1)
        with pytest.raises(ValueError):
            JobLimitLedger(1, bad, 1)
        with pytest.raises(ValueError):
            JobLimitLedger(1, 1, bad)


# ---------------------------------------------------------------------------
# 2. Fail-closed wrapper
# ---------------------------------------------------------------------------

def test_wrapper_allows_within_limits_and_preserves_section_4_blocks():
    ledger = JobLimitLedger(5, 5, 5)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)
    assert hook("todo_list", {"todos": []}) is None
    verdict = hook("shell", {})
    assert verdict is not None and verdict["action"] == "block"
    assert verdict["message"].strip()
    # The §4 message is passed through verbatim (same as the base hook).
    assert verdict == _base_hook()("shell", {})


def test_wrapper_blocks_nth_call_with_limit_reason():
    ledger = JobLimitLedger(max_tool_calls=1, max_tool_calls_per_capability=1, max_blocked_requests=3)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)
    assert hook("todo_list", {}) is None
    verdict = hook("todo_list", {})
    assert verdict["action"] == "block"
    assert REASON_TOOL_CALL_LIMIT in verdict["message"]
    assert verdict["message"].strip()


def test_wrapper_fail_closed_on_internal_error():
    class BrokenLedger(JobLimitLedger):
        def record(self, tool_name, allowed_by_policy):
            raise RuntimeError("ledger exploded")

    ledger = BrokenLedger(1, 1, 1)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)
    verdict = hook("todo_list", {})
    assert verdict["action"] == "block"
    assert REASON_LIMIT_CHECK_ERROR in verdict["message"]
    assert ledger.violation_code == REASON_LIMIT_CHECK_ERROR


def test_wrapper_fail_closed_if_base_hook_raises():
    def raising_base(tool_name, args=None, **kwargs):
        raise RuntimeError("base exploded")

    ledger = JobLimitLedger(2, 2, 2)
    hook = make_limit_enforcing_hook(raising_base, ledger)
    verdict = hook("todo_list", {})
    assert verdict["action"] == "block"
    assert REASON_LIMIT_CHECK_ERROR in verdict["message"]


def test_wrapper_carries_policy_plugin_marker():
    hook = make_limit_enforcing_hook(_base_hook(), JobLimitLedger(1, 1, 1))
    assert getattr(hook, POLICY_PLUGIN_MARKER, False) is True
    from app.hermes.policy import verify_policy_plugin_registered

    verify_policy_plugin_registered([hook])  # §4.3 still passes


def test_wrapper_never_modifies_or_approves():
    ledger = JobLimitLedger(1, 1, 1)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)
    for name in ("todo_list", "shell", "research.search", "delegate_task", "", 7, None):
        result = hook(name, {} if isinstance(name, str) and name else None)
        assert result is None or (
            isinstance(result, dict) and result.get("action") == "block" and result["message"].strip()
        ), name


# ---------------------------------------------------------------------------
# 3. Thread-safety / determinism
# ---------------------------------------------------------------------------

def test_thread_safe_and_deterministic_totals():
    ledger = JobLimitLedger(max_tool_calls=5000, max_tool_calls_per_capability=5000, max_blocked_requests=5000)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)

    def hammer():
        for _ in range(200):
            hook("todo_list", {})
            hook("shell", {})

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    counts = ledger.counts()
    assert counts["allowed_total"] == 8 * 200
    assert counts["blocked_total"] == 8 * 200
    assert ledger.violation_code is None


def test_repeated_invocation_deterministic():
    ledger = JobLimitLedger(2, 1, 1)
    hook = make_limit_enforcing_hook(_base_hook(), ledger)
    first = [hook("todo_list", {}) for _ in range(3)]
    ledger2 = JobLimitLedger(2, 1, 1)
    hook2 = make_limit_enforcing_hook(_base_hook(), ledger2)
    second = [hook2("todo_list", {}) for _ in range(3)]
    assert first == second
    assert [v is None for v in first] == [True, False, False]


# ---------------------------------------------------------------------------
# 4. REAL Hermes integration (§16 — no silent skips)
# ---------------------------------------------------------------------------

def test_real_registered_hook_enforces_limits(tmp_path):
    """Through the REAL pinned Hermes plugin registry: the registered
    pre_tool_call callback is the §12-wrapped §4 hook, and the Nth call
    is denied while §4 blocks pass through verbatim."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.runtime as runtime

    captured: dict = {}
    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        captured["callbacks"] = list(iter_hook_callbacks("pre_tool_call"))
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _valid_settings(
            tmp_path,
            hermes_max_tool_calls=2,
            hermes_max_tool_calls_per_capability=2,
            hermes_max_blocked_requests=1,
        )
        result = run_hermes_job(_request(job_id="lim-it-1", task_message=None), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert
    assert result.status == "completed", (result.error_code, result.error_detail)
    hook = captured["callbacks"][0]
    assert getattr(hook, POLICY_PLUGIN_MARKER, False) is True
    assert hook("todo_list", {}) is None  # 1st allowed
    assert hook("todo_list", {}) is None  # 2nd allowed
    verdict = hook("todo_list", {})  # 3rd — over the total limit
    assert verdict["action"] == "block"
    assert REASON_TOOL_CALL_LIMIT in verdict["message"]
    assert hook("shell", {})["action"] == "block"  # still denied post-violation


def test_real_runtime_fails_job_after_limit_violation(tmp_path):
    """§11/§12: a chat loop that exceeds a limit ends with the job marked
    failed (never silently continuing) and cleanup still runs."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.runtime as runtime

    settings = _valid_settings(
        tmp_path, hermes_max_tool_calls=1, hermes_max_tool_calls_per_capability=1
    )
    original = runtime._construct_agent

    def agent_that_burns_limits(request, config, baseline_threads):
        agent = _LimitBurningAgent()
        return agent

    runtime._construct_agent = agent_that_burns_limits
    try:
        result = run_hermes_job(
            _request(job_id="lim-it-2", task_message="burn limits"), settings=settings
        )
    finally:
        runtime._construct_agent = original
    assert result.status == "failed"
    assert result.error_code == REASON_TOOL_CALL_LIMIT
    assert "'max_tool_calls': 1" in result.error_detail
    # Cleanup after violation: home deleted, runtime env cleared.
    assert not (Path(settings.hermes_home) / "jobs" / "lim-it-2").exists()
    assert "HERMES_HOME" not in os.environ
    assert "HERMES_BUNDLED_PLUGINS" not in os.environ


class _LimitBurningAgent:
    """Stub agent whose chat drives the REAL registered hook past the
    total-limit while the runtime watchdog and lifecycle stay real."""

    enabled_toolsets = ["todo"]
    valid_tool_names = {"todo_list"}
    api_key = "aryaos-explicit-test-key"
    base_url = "http://127.0.0.1:9/v1"

    def chat(self, _message):
        from hermes_cli.plugins import iter_hook_callbacks

        hook = list(iter_hook_callbacks("pre_tool_call"))[0]
        results = [hook("todo_list", {}) for _ in range(3)]
        assert results[0] is None  # first allowed
        assert results[1] is not None  # second denied (limit 1)
        return "model thinks everything is fine"

    def close(self):
        pass


def test_construction_only_job_has_no_violation(tmp_path):
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    result = run_hermes_job(
        _request(job_id="lim-it-3", task_message=None), settings=_valid_settings(tmp_path)
    )
    assert result.status == "completed", (result.error_code, result.error_detail)
