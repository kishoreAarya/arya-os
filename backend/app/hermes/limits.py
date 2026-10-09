"""
AryaOS-owned per-job resource-limit ledger — §12 enforcement (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §12 ("Max tool calls
per job (total), and per capability", "Max malformed/blocked tool requests
tolerated before job abort", "enforced even if Hermes ignores or
misreports them (defense in depth: AryaOS-side counters and timers own
the truth") and §11 ("Budget violation → deny further calls; job →
failed; no silent continuation"; "Malformed tool request → BLOCK; counted
against the job's malformed-request limit").

Enforcement point: the §4 pre_tool_call boundary. Every tool request —
regardless of call path — traverses the hook exactly once before
execution (pinned single-fire contract: model_tools.py:775,
agent/tool_executor.py:652-657, agent/agent_runtime_helpers.py:2351-2352),
so a wrapper around the §4 hook counts every attempt. Hermes-side
counters are never consulted.

Counting semantics (deterministic, per job):
- A request the §4 policy ALLOWS consumes one unit of the TOTAL counter
  and one unit of its PER-NAME counter (the per-capability limit of §12,
  bucketed by the authorized tool's name — §9 capability names ARE tool
  names, and native sanctioned tools get the same per-name bucket so the
  limit is uniform; the total counter independently bounds everything).
- A request the §4 policy BLOCKS (unknown tool, malformed request,
  delegate_task, invalid context, ...) consumes one unit of the BLOCKED
  counter and is NOT counted as a tool call (it never executes).
- Limits are checked BEFORE the allowance is granted: the request that
  would exceed a limit is itself BLOCKED and execution is prevented.
- Once a limit is violated, every further request is denied with the
  violation's reason code (§11 "deny further ... no silent continuation")
  and the runtime marks the job failed via ledger.violation_code.
- Any error inside the ledger/wrapper is fail-closed: the request is
  BLOCKED with "blocked_limit_check_error" and the violation is recorded.

§13.1 final-outcome audit (additive observability only): every §12
denial — total limit, per-capability limit, a fresh blocked-request
limit trip, post-violation denials, and the fail-closed internal-error
block — emits a best-effort BLOCK audit record with the deterministic
reason code via app.hermes.audit.record_final_outcome. Counting
semantics, thresholds, ordering, and failure behavior are unchanged,
and audit failures never alter any decision. The §12 USD-budget
violation (generation_budget_exceeded, §9.3) is noted on the ledger
here but recorded/emitted by the provider.generate binding at the
point of denial, before any chargeable execution.

Out of scope by spec-ordered deferral: USD generation budget (§9
provider.generate + router cost accounting) and the context-token cap
(§5.2 model-config completion). No concurrency support: one ledger per
job, one job at a time (§3 runtime lock); the ledger is nevertheless
thread-safe because Hermes may invoke hooks from worker threads.
"""
import threading
from typing import Any, Callable

from app.hermes.policy import POLICY_PLUGIN_MARKER

REASON_TOOL_CALL_LIMIT = "tool_call_limit_exceeded"
REASON_PER_CAPABILITY_LIMIT = "tool_call_per_capability_limit_exceeded"
REASON_BLOCKED_LIMIT = "blocked_request_limit_exceeded"
REASON_LIMIT_CHECK_ERROR = "blocked_limit_check_error"
REASON_GENERATION_BUDGET = "generation_budget_exceeded"


class JobLimitLedger:
    """Per-job §12 counters. Owned by AryaOS; Hermes never sees or reports
    these numbers. All methods are thread-safe and deterministic."""

    def __init__(self, max_tool_calls: int, max_tool_calls_per_capability: int, max_blocked_requests: int):
        if max_tool_calls < 1 or max_tool_calls_per_capability < 1 or max_blocked_requests < 1:
            raise ValueError("§12 limits must be positive integers")
        self._max_tool_calls = max_tool_calls
        self._max_tool_calls_per_capability = max_tool_calls_per_capability
        self._max_blocked_requests = max_blocked_requests
        self._allowed_total = 0
        self._allowed_per_name: dict[str, int] = {}
        self._blocked_total = 0
        self._violation_code: str | None = None
        self._lock = threading.Lock()

    @property
    def violation_code(self) -> str | None:
        """The reason code of the first limit violation, if any. The runtime
        fails the job when this is set (§11: no silent continuation)."""
        with self._lock:
            return self._violation_code

    def counts(self) -> dict[str, int]:
        """Deterministic snapshot of the counters (audit/test use)."""
        with self._lock:
            return {
                "allowed_total": self._allowed_total,
                "blocked_total": self._blocked_total,
                "max_tool_calls": self._max_tool_calls,
                "max_tool_calls_per_capability": self._max_tool_calls_per_capability,
                "max_blocked_requests": self._max_blocked_requests,
            }

    def note_internal_error(self) -> None:
        """Record a fail-closed internal error as a job-level violation."""
        with self._lock:
            if self._violation_code is None:
                self._violation_code = REASON_LIMIT_CHECK_ERROR

    def note_generation_budget_exceeded(self) -> None:
        """Record a §12 USD-budget violation (§9.3 chargeable-call gate):
        the WorkflowRun's authoritative accumulated spend reached the
        configured hermes_max_generation_budget_usd BEFORE a chargeable
        provider.generate call was executed. First violation wins, exactly
        like note_internal_error; the runtime fails the job through the
        existing §11/§12 violation path — no silent continuation."""
        with self._lock:
            if self._violation_code is None:
                self._violation_code = REASON_GENERATION_BUDGET

    def record(self, tool_name: str, allowed_by_policy: bool) -> str | None:
        """Account one tool request and decide whether it may proceed.

        Returns None when the request may proceed unchanged, or a
        deterministic reason code when it must be BLOCKED. Never raises.

        - allowed_by_policy=False (the §4 gate already blocks it): counts
          against the blocked-request limit; returns None so the caller
          keeps the §4 block directive and its message verbatim.
        - allowed_by_policy=True: checks the total and per-name limits
          BEFORE granting; the request that would exceed a limit is
          denied with the violation reason code and nothing executes.
        - After a violation, every further request is denied with the
          recorded reason code.
        """
        try:
            with self._lock:
                if self._violation_code is not None:
                    return self._violation_code
                if not allowed_by_policy:
                    self._blocked_total += 1
                    if self._blocked_total > self._max_blocked_requests:
                        self._violation_code = REASON_BLOCKED_LIMIT
                    return None  # the §4 block directive stands unchanged
                if self._allowed_total + 1 > self._max_tool_calls:
                    self._violation_code = REASON_TOOL_CALL_LIMIT
                    return self._violation_code
                name = tool_name if isinstance(tool_name, str) else "<invalid>"
                if self._allowed_per_name.get(name, 0) + 1 > self._max_tool_calls_per_capability:
                    self._violation_code = REASON_PER_CAPABILITY_LIMIT
                    return self._violation_code
                self._allowed_total += 1
                self._allowed_per_name[name] = self._allowed_per_name.get(name, 0) + 1
                return None
        except BaseException:  # counters must never fail open
            try:
                self.note_internal_error()
            except Exception:
                pass
            return REASON_LIMIT_CHECK_ERROR


def _audit_final_outcome(tool_name: object, args: object, reason: str) -> None:
    """Best-effort §13.1 final-outcome audit record (§12 layer). Never
    raises into the request path; a recording failure changes nothing."""
    try:
        from app.hermes.audit import record_final_outcome

        record_final_outcome(tool_name, args, reason)
    except Exception:
        pass  # authorization-preserving, best-effort audit (§13.1)


def make_limit_enforcing_hook(base_hook: Callable, ledger: JobLimitLedger) -> Callable:
    """Wrap the §4 pre_tool_call hook with §12 limit enforcement.

    Behavior contract preserved from §4: returns None to proceed or a
    {"action": "block", "message": <non-empty str>} directive; never
    returns "modify"/"approve"; NEVER raises (a raising callback would
    fail open through Hermes' dispatch wrapper, model_tools.py:780). §4
    block directives are returned verbatim; limit denials carry their own
    deterministic reason code. Every §12 denial additionally emits a
    best-effort §13.1 final-outcome audit record (§4 records unchanged).
    The wrapper carries the AryaOS policy plugin marker so §4.3
    registration verification still passes.
    """

    def limit_enforcing_hook(tool_name: str, args: dict | None = None, **_hook_kwargs: Any):
        try:
            decision = base_hook(tool_name, args, **_hook_kwargs)
            if decision is not None:  # §4 BLOCK — count, preserve verbatim
                violation_before = ledger.violation_code
                ledger.record(tool_name, allowed_by_policy=False)
                if violation_before is None and ledger.violation_code == REASON_BLOCKED_LIMIT:
                    # This request exhausted the blocked-request budget (§12
                    # job-level denial); the §4 block directive still stands.
                    _audit_final_outcome(tool_name, args, REASON_BLOCKED_LIMIT)
                return decision
            reason = ledger.record(tool_name, allowed_by_policy=True)
            if reason is None:
                return None
            _audit_final_outcome(tool_name, args, reason)
            name = tool_name if isinstance(tool_name, str) and tool_name else "<invalid>"
            return {"action": "block", "message": f"Blocked by AryaOS policy gate ({reason}): {name!r}"}
        except BaseException:  # §12/§4: never raise, fail closed
            try:
                ledger.note_internal_error()
            except Exception:
                pass
            _audit_final_outcome(tool_name, args, REASON_LIMIT_CHECK_ERROR)
            name = tool_name if isinstance(tool_name, str) and tool_name else "<invalid>"
            return {
                "action": "block",
                "message": f"Blocked by AryaOS policy gate ({REASON_LIMIT_CHECK_ERROR}): {name!r}",
            }

    setattr(limit_enforcing_hook, POLICY_PLUGIN_MARKER, True)
    return limit_enforcing_hook
