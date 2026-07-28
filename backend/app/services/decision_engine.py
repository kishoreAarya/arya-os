"""
Decision Engine.

Pure decision logic — never executes anything, never calls a
provider, never sleeps, never touches the database. Every method
takes plain data in and returns a Decision out. ExecutionEngine
(app/services/execution_engine.py) is the only thing that acts on a
Decision; DecisionEngine only decides.

Reference: ARCHITECTURE_v1.0.md was not found in this project (same
note as every prior Execution Engine milestone) — built against
ARYA_OS_BUILD_INSTRUCTIONS.md instead.

THIS MILESTONE'S INTEGRATION SCOPE — read before assuming more is
wired into ExecutionEngine's control flow than actually is:

- decide_retry / decide_stop ARE wired into
  ExecutionEngine._call_provider_with_retry. The classification logic
  that used to live inline there (a raw `if not is_transient` /
  `if attempt >= 1 + max_retries` check) now asks DecisionEngine
  instead — ExecutionEngine still owns the actual sleeping and
  looping, DecisionEngine only says retry-or-stop and why.

- decide_provider_fallback / decide_prompt_rewrite / decide_escalation
  exist as real, callable, independently-tested methods (this is
  what Part 2 of this milestone asked for) but are deliberately NOT
  called anywhere in ExecutionEngine's control flow yet:

  - decide_provider_fallback: see execution_engine.py's module
    docstring, "PROVIDER FALLBACK — STOPPED, NOT IMPLEMENTED" section,
    for the specific architectural reason acting on this safely isn't
    possible yet without either modifying the Provider Router's public
    contract or duplicating its provider-iteration logic — both
    explicitly off-limits this milestone.
  - decide_prompt_rewrite / decide_escalation: Prompt Rewriting and
    Human Approval are both explicitly listed as NOT to be implemented
    this milestone. These methods exist so the shape is right and
    tested, but nothing consumes their output yet — there is no
    prompt-rewrite mechanism and no human-approval/notification system
    for anything to hand an ESCALATE decision to.

These three are extension points, not decorative dead code: once
their surrounding architecture question is resolved, ExecutionEngine
gets a few lines added to call them — not a rewrite of this file.
"""

import enum
from dataclasses import dataclass, field

from app.providers.capabilities import Capability, providers_for


class DecisionAction(str, enum.Enum):
    RETRY = "retry"
    STOP = "stop"
    FALLBACK = "fallback"
    PROMPT_REWRITE = "prompt_rewrite"
    ESCALATE = "escalate"


@dataclass
class Decision:
    """What every decide_*() method returns. Plain data, no behavior —
    nothing on this object executes anything."""

    action: DecisionAction
    reason: str
    metadata: dict = field(default_factory=dict)


class DecisionEngine:
    """Stateless — every method is a pure function of its arguments.
    Kept as a class (not module-level functions) to match
    ExecutionEngine's shape and make a future stateful addition (e.g.
    per-run decision history) a non-breaking change rather than an API
    change.
    """

    def decide_retry(
        self, *, attempt_number: int, max_retries: int, is_transient: bool
    ) -> Decision:
        """Should the same provider chain be tried again? Pure policy
        — the caller (ExecutionEngine) still owns the actual sleep and
        loop; this only says whether to and why."""
        if not is_transient:
            return Decision(
                action=DecisionAction.STOP,
                reason="Failure is not transient — retrying would fail identically",
                metadata={"attempt_number": attempt_number},
            )

        if attempt_number >= 1 + max_retries:
            return Decision(
                action=DecisionAction.STOP,
                reason=f"Retry budget exhausted ({attempt_number}/{1 + max_retries} attempts used)",
                metadata={"attempt_number": attempt_number, "max_retries": max_retries},
            )

        return Decision(
            action=DecisionAction.RETRY,
            reason=f"Transient failure on attempt {attempt_number}, retries remaining",
            metadata={"attempt_number": attempt_number, "max_retries": max_retries},
        )

    def decide_stop(self, *, attempt_number: int, max_retries: int) -> Decision:
        """A direct stop confirmation, independent of transience —
        for a caller that already knows retrying isn't on the table
        (e.g. a non-transient failure, or fallback options exhausted)
        and just wants a formal, logged stop decision with a reason."""
        if attempt_number >= 1 + max_retries:
            return Decision(
                action=DecisionAction.STOP,
                reason=f"Attempt budget exhausted ({attempt_number}/{1 + max_retries})",
                metadata={"attempt_number": attempt_number, "max_retries": max_retries},
            )
        return Decision(
            action=DecisionAction.STOP,
            reason="Stop requested directly, not a retry-budget decision",
            metadata={"attempt_number": attempt_number, "max_retries": max_retries},
        )

    def decide_provider_fallback(
        self,
        *,
        capability: Capability,
        failed_provider: str | None,
        already_tried: list[str] | None = None,
    ) -> Decision:
        """Inspects the capability's candidate list — read-only, via
        providers_for(), never calling or executing any provider — and
        decides whether an untried provider exists to fall back to.

        NOT called anywhere in ExecutionEngine yet. See this file's
        module docstring and execution_engine.py's "PROVIDER FALLBACK"
        note for exactly why.
        """
        tried = set(already_tried or [])
        if failed_provider:
            tried.add(failed_provider)

        candidates = providers_for(capability)
        remaining = [p for p in candidates if p.name not in tried]

        if not remaining:
            return Decision(
                action=DecisionAction.STOP,
                reason=f"No untried providers remain for '{capability.value}'",
                metadata={"already_tried": sorted(tried)},
            )

        return Decision(
            action=DecisionAction.FALLBACK,
            reason=f"Untried provider available for '{capability.value}'",
            metadata={
                "next_provider": remaining[0].name,
                "already_tried": sorted(tried),
            },
        )

    def decide_prompt_rewrite(
        self, *, validation_issues: list[str] | None = None
    ) -> Decision:
        """Extension point only — Prompt Rewriting is explicitly out
        of scope this milestone. Always defers (never actually
        rewrites anything; this class never executes anything
        regardless of what it returns)."""
        return Decision(
            action=DecisionAction.STOP,
            reason="Prompt rewriting is not implemented — deferred, not attempted",
            metadata={"validation_issues": validation_issues or []},
        )

    def decide_escalation(
        self,
        *,
        attempt_number: int,
        max_retries: int,
        fallback_exhausted: bool = False,
    ) -> Decision:
        """Extension point only — Human Approval / escalation handling
        is explicitly out of scope this milestone. Returns ESCALATE
        once retry and fallback are both exhausted, but nothing in
        this codebase acts on that decision yet — there is no
        notification system and no human-approval workflow wired to
        receive it. Intentionally inert, not half-built."""
        if attempt_number >= 1 + max_retries and fallback_exhausted:
            return Decision(
                action=DecisionAction.ESCALATE,
                reason="Retry and fallback both exhausted — would need human review",
                metadata={"attempt_number": attempt_number},
            )
        return Decision(
            action=DecisionAction.STOP,
            reason="Escalation not yet warranted",
            metadata={"attempt_number": attempt_number},
        )
