"""
Execution Engine — Milestone 5: Decision Engine Integration
(Retry confirmed complete; Provider Fallback execution STOPPED — see
"PROVIDER FALLBACK" section below).

Reference: ARCHITECTURE_v1.0.md was not found in this project — this
was built against ARYA_OS_BUILD_INSTRUCTIONS.md's Step 1 spec instead.
Flagging the substitution rather than silently assuming they're
identical (same note as every prior milestone).

MILESTONE 5, PART 1 (RETRY) — ALREADY COMPLETE, CONFIRMED NOT REBUILT:
retry-on-transient-failure, exponential backoff, attempt tracking, and
ExecutionResult.attempts were all fully implemented in the prior
milestone. Nothing about retry's BEHAVIOR changes here — verified by
the full existing retry test suite still passing unmodified. The only
change touching retry code at all: the inline transient/exhausted
classification inside `_call_provider_with_retry` now asks
DecisionEngine.decide_retry() instead of checking conditions directly
— same outcome, decision-making moved to where Part 2 asked for it to
live.

MILESTONE 5, PART 2 (DECISION ENGINE) — NEW, in
app/services/decision_engine.py. `DecisionEngine.decide_retry()` and
`.decide_stop()` are wired into `_call_provider_with_retry` (see
above). `.decide_provider_fallback()`, `.decide_prompt_rewrite()`, and
`.decide_escalation()` exist, are independently tested, and are NOT
called anywhere in this file's control flow — see PROVIDER FALLBACK
below for why, and decision_engine.py's own module docstring for the
full reasoning on all three.

MILESTONE 5, PART 3 (PROVIDER FALLBACK) — STOPPED, NOT IMPLEMENTED.
Explaining exactly why, per this milestone's own instruction to stop
and explain rather than invent architecture:

`call_with_fallback()` (app/providers/router.py, whose contract this
milestone must not modify) already tries EVERY candidate provider for
a capability, in order, on every single invocation — it only raises
AllProvidersFailedError once every candidate has already failed. That
means by the time `_call_provider` returns a failure to
ExecutionEngine, there is no untried provider left to "fall back" to
within that call; every compatible provider was already attempted.

Building a genuine, incremental "try just the next specific provider"
mechanism on top of this would require one of two things, and this
milestone explicitly forbids both:
  1. Modifying call_with_fallback's contract to support resuming from
     a specific provider instead of always trying the full candidate
     list — explicitly listed as something not to modify this
     milestone ("Existing Provider Router contracts... must NOT be
     modified").
  2. Reimplementing provider iteration directly inside ExecutionEngine
     (calling individual providers one at a time, bypassing
     call_with_fallback) — this would duplicate provider-selection
     logic that already exists in router.py, which every prior
     Execution Engine milestone has treated as a hard rule (never
     duplicate provider selection/iteration logic; always go through
     the Router's public interface). It would also mean reimplementing
     call_with_fallback's cost-ceiling check and event logging by hand
     to satisfy this milestone's own "preserve cost tracking" /
     "preserve execution logs" requirements for the fallback path —
     which is exactly the kind of invented, parallel architecture this
     milestone's final instruction says to stop rather than build.

What DOES exist as a result of this analysis: `DecisionEngine.
decide_provider_fallback()` is fully built and tested — it inspects
the capability's candidate list (read-only, via providers_for()) and
returns a structured FALLBACK-or-STOP decision. It's a real, working
extension point. What's missing is a way to ACT on a FALLBACK decision
that doesn't hit one of the two problems above — that requires either
a scoped, deliberate change to router.py's contract (a real
architecture decision, not something to make silently inside a
"don't modify the Router" milestone) or accepting that, given the
Router's current design, "fallback" and "retry the whole chain again"
are the same operation — which Part 1's retry logic already does.

MILESTONE 1-4 SCOPE, STILL UNCHANGED — what this file still does NOT do:
- No prompt rewriting, no human approval, no learning loop, no
  analytics — all explicitly out of scope, and DecisionEngine's
  corresponding decide_*() methods are extension points only, not
  wired to any real mechanism (none exists yet).
- No new validators, no changes to any existing validator, no changes
  to VALIDATOR_REGISTRY's contents.
- No persistence. `_persist` is still a TODO stub.

Beginner note: this is the layer every future agent executes through
instead of each one reimplementing its own provider call, retry
handling, cost tracking, validation dispatch, and error handling.
Script Agent (app/agents/script.py) predates this file and still calls
app/providers/router.py's call_with_fallback() directly — it is NOT
rewired to use this class in this milestone either, on purpose, per
this milestone's scope (rule: don't modify ScriptAgent).
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.providers.capabilities import Capability
from app.providers.router import (
    CostLimitExceededError,
    ProviderCall,
    RouterResult,
    call_with_fallback,
)
from app.services.decision_engine import Decision, DecisionAction, DecisionEngine
from app.validators import VALIDATOR_REGISTRY
from app.validators.base import ValidationResult

logger = get_logger(__name__)

# No existing config field covers backoff timing (only
# Settings.max_retry_attempts is configurable, per this milestone's
# requirement) — this is a plain constant, not invented to look more
# configurable than what was actually asked for.
_RETRY_BACKOFF_BASE_SECONDS = 0.1


class UnknownValidatorError(RuntimeError):
    """Raised when a validator_name doesn't match anything in
    VALIDATOR_REGISTRY. Same treatment as AllProvidersFailedError in
    app/providers/router.py: a clean, catchable error, not a typo
    silently doing nothing."""

    def __init__(self, validator_name: str):
        self.validator_name = validator_name
        super().__init__(
            f"Unknown validator '{validator_name}' — not in VALIDATOR_REGISTRY "
            f"(available: {sorted(VALIDATOR_REGISTRY.keys())})"
        )


@dataclass
class ExecutionContext:
    """In-memory only — scoped to a single execute() call, never
    written to the database directly (see ARYA_OS_BUILD_INSTRUCTIONS.md
    section 5 for why this stays separate from GenerationAttempt).
    Discarded once execute() returns; _persist() is what (eventually)
    saves the parts of it worth keeping.
    """

    workflow_run_id: uuid.UUID | None
    stage: str
    provider: str | None = None
    model: str | None = None
    attempt_number: int = 1
    elapsed_time: float = 0.0
    accumulated_cost: float = 0.0
    validation_result: ValidationResult | None = None


@dataclass
class ExecutionResult:
    """What execute() hands back to the caller (an agent, eventually).

    Field names match this milestone's spec exactly: `provider` and
    `elapsed_time` (Milestone 1 used `provider_used`/`duration_seconds`
    — renamed here, not additive, since nothing outside this file's
    own tests consumed the old names yet).
    """

    success: bool
    output: object | None = None
    provider: str | None = None
    model: str | None = (
        None  # always None for now — see module docstring's "KNOWN GAP" note
    )
    cost_usd: float = 0.0
    elapsed_time: float = 0.0
    attempts: int = (
        1  # final attempt count — new in Milestone 4, populated on every return path
    )
    error: str | None = None
    context: ExecutionContext = field(
        default_factory=lambda: ExecutionContext(None, "unknown")
    )


class ExecutionEngine:
    """One instance per request, same lifecycle as a repository —
    constructed with the request-scoped AsyncSession, same DI pattern
    already used by WorkflowRunRepository(db).
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        # Stateless, so one instance for the engine's lifetime is fine
        # — no per-request state to isolate, unlike self._db.
        self._decision_engine = DecisionEngine()

    async def execute(
        self,
        *,
        capability: Capability,
        call: ProviderCall,
        workflow_run_id: uuid.UUID | str | None,
        stage: str,
        running_cost_usd: float = 0.0,
        validator_name: str | None = None,
    ) -> ExecutionResult:
        """Public entrypoint.

        `capability` / `call` / `running_cost_usd` match
        call_with_fallback's own parameters exactly, since
        `_call_provider` is a thin wrapper around it.

        `validator_name` is new in Milestone 3 and optional: leave it
        None (the default) to skip validation entirely — behavior is
        identical to Milestone 2. Pass a real VALIDATOR_REGISTRY key
        ("story", "prompt", "image", "consistency", "video",
        "thumbnail", "brand") to have ExecutionEngine run that
        validator against the provider's output after a successful
        call, before returning.
        """
        context = ExecutionContext(workflow_run_id=workflow_run_id, stage=stage)
        started = time.monotonic()

        await log_event(
            EventType.PROVIDER_CALLED,
            message=f"ExecutionEngine starting {capability.value} for stage '{stage}'",
            workflow_run_id=workflow_run_id,
            metadata={"stage": stage},
        )

        router_result, attempt_count, call_error = await self._call_provider_with_retry(
            capability=capability,
            call=call,
            workflow_run_id=workflow_run_id,
            stage=stage,
            running_cost_usd=running_cost_usd,
        )
        context.attempt_number = attempt_count

        if router_result is None:
            context.elapsed_time = time.monotonic() - started
            logger.error(
                "execution_engine_call_failed",
                stage=stage,
                capability=capability.value,
                attempts=attempt_count,
                error=str(call_error),
            )
            return ExecutionResult(
                success=False,
                error=str(call_error),
                elapsed_time=context.elapsed_time,
                attempts=attempt_count,
                context=context,
            )

        context.provider = router_result.provider_used
        context.accumulated_cost = running_cost_usd + router_result.cost_usd

        # Validation only ever runs after a successful provider call
        # (requirement 5) — there's no path above that reaches here
        # without router_result already being a success, retried or not.
        if validator_name is not None:
            try:
                validation_result = await self._validate(
                    validator_name, router_result.output
                )
            except UnknownValidatorError as exc:
                context.elapsed_time = time.monotonic() - started
                logger.error(
                    "execution_engine_unknown_validator",
                    stage=stage,
                    validator=validator_name,
                    error=str(exc),
                )
                return ExecutionResult(
                    success=False,
                    provider=router_result.provider_used,
                    cost_usd=router_result.cost_usd,
                    error=str(exc),
                    elapsed_time=context.elapsed_time,
                    attempts=attempt_count,
                    context=context,
                )

            context.validation_result = validation_result

            if not validation_result.passed:
                # Requirement 7 (Milestone 3, unchanged): mark failed,
                # attach the result, return immediately — no retry of
                # validation itself, no Decision Engine, no persistence
                # call, no second provider call.
                context.elapsed_time = time.monotonic() - started
                return ExecutionResult(
                    success=False,
                    output=router_result.output,
                    provider=router_result.provider_used,
                    cost_usd=router_result.cost_usd,
                    elapsed_time=context.elapsed_time,
                    attempts=attempt_count,
                    error=f"Validation '{validator_name}' failed: "
                    f"{'; '.join(validation_result.issues) if validation_result.issues else 'no issues listed'}",
                    context=context,
                )

        # TODO (future milestone): write GenerationAttempt + update quality_score.
        await self._persist(context, router_result)

        context.elapsed_time = time.monotonic() - started

        logger.info(
            "execution_engine_call_succeeded",
            stage=stage,
            capability=capability.value,
            provider=router_result.provider_used,
            cost_usd=router_result.cost_usd,
            elapsed_time=context.elapsed_time,
            attempts=attempt_count,
            validated=validator_name is not None,
        )

        return ExecutionResult(
            success=True,
            output=router_result.output,
            provider=router_result.provider_used,
            cost_usd=router_result.cost_usd,
            elapsed_time=context.elapsed_time,
            attempts=attempt_count,
            context=context,
        )

    async def _call_provider(
        self,
        *,
        capability: Capability,
        call: ProviderCall,
        workflow_run_id: uuid.UUID | str | None,
        stage: str,
        running_cost_usd: float,
    ) -> RouterResult:
        """Private: the only place this milestone talks to
        app/providers/router.py. No retry loop of its own — one call,
        one result or one raised exception. Kept as its own method
        (rather than inlined in execute()) so a future retry loop can
        wrap calls to this method without restructuring execute()'s
        logging/context bookkeeping around it.
        """
        return await call_with_fallback(
            capability,
            call,
            workflow_run_id=str(workflow_run_id) if workflow_run_id else None,
            stage=stage,
            running_cost_usd=running_cost_usd,
        )

    async def _call_provider_with_retry(
        self,
        *,
        capability: Capability,
        call: ProviderCall,
        workflow_run_id: uuid.UUID | str | None,
        stage: str,
        running_cost_usd: float,
    ) -> tuple[RouterResult | None, int, Exception | None]:
        """Wraps `_call_provider` with retry-on-transient-failure.

        Returns (RouterResult, attempt_count, None) on eventual
        success, or (None, attempt_count, last_exception) once retries
        are exhausted or a non-transient failure is hit — never raises,
        so execute() doesn't need its own try/except around this call.

        `attempt_count` is 1-indexed and reflects however many times
        `_call_provider` was actually invoked, whether that's 1 (first
        try succeeded, or a non-transient failure stopped things
        immediately) or up to 1 + Settings.max_retry_attempts.
        """
        settings = get_settings()
        max_retries = settings.max_retry_attempts
        attempt = 1

        while True:
            try:
                result = await self._call_provider(
                    capability=capability,
                    call=call,
                    workflow_run_id=workflow_run_id,
                    stage=stage,
                    running_cost_usd=running_cost_usd,
                )
                return result, attempt, None
            # Any provider-layer failure is classified below, not blindly retried.
            except Exception as exc:  # noqa: BLE001
                is_transient = self._is_transient_failure(exc)
                decision: Decision = self._decision_engine.decide_retry(
                    attempt_number=attempt,
                    max_retries=max_retries,
                    is_transient=is_transient,
                )

                if decision.action is DecisionAction.STOP:
                    log_event_name = (
                        "execution_engine_non_transient_failure"
                        if not is_transient
                        else "execution_engine_retries_exhausted"
                    )
                    logger.error(
                        log_event_name,
                        stage=stage,
                        capability=capability.value,
                        attempt=attempt,
                        max_retries=max_retries,
                        decision_reason=decision.reason,
                        error=str(exc),
                    )
                    return None, attempt, exc

                # decision.action is RETRY from here on.
                backoff_seconds = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "execution_engine_retry_attempt",
                    stage=stage,
                    capability=capability.value,
                    attempt=attempt,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    decision_reason=decision.reason,
                    error=str(exc),
                )
                await asyncio.sleep(backoff_seconds)
                attempt += 1

    def _is_transient_failure(self, exc: Exception) -> bool:
        """CostLimitExceededError is the one case that's never
        transient: it fires before any provider is even called, based
        on running_cost_usd — which cannot change between retries
        unless a call actually succeeds. Retrying it would fail
        identically every time. Everything else (AllProvidersFailedError,
        network/timeout errors surfaced by provider adapters) is
        treated as a transient provider failure. See the module
        docstring's "RETRY CLASSIFICATION" note for why this line is
        drawn here and not somewhere finer-grained — that finer-grained
        classification is Decision Engine territory, out of scope here.
        """
        return not isinstance(exc, CostLimitExceededError)

    async def _validate(self, validator_name: str, output: dict) -> ValidationResult:
        """Discovers, runs, and logs the requested validator.

        Extends what was a TODO stub through Milestone 1-2 (it used to
        take just `output` and always return None) — same method, now
        implemented, not a new one alongside it.

        Raises UnknownValidatorError if `validator_name` isn't in
        VALIDATOR_REGISTRY (app/validators/__init__.py) — never
        silently skips validation on a typo.

        `output` is passed straight through as the `artifact` dict
        BaseValidator.validate() expects — see the module docstring's
        "INTEGRATION CONTRACT" note for what that implies.

        BaseValidator.validate() is a synchronous method (unlike
        BaseAgent.run(), which is async) — called directly here, not
        awaited, since rule 2 forbids modifying the existing validator
        contract.
        """
        validator = VALIDATOR_REGISTRY.get(validator_name)
        if validator is None:
            raise UnknownValidatorError(validator_name)

        logger.info("execution_engine_validation_started", validator=validator_name)

        result = validator.validate(output)

        if result.passed:
            logger.info(
                "execution_engine_validation_succeeded",
                validator=validator_name,
                score=result.score,
            )
        else:
            logger.warning(
                "execution_engine_validation_failed",
                validator=validator_name,
                score=result.score,
                issues=result.issues,
            )

        return result

    async def _persist(
        self, context: ExecutionContext, router_result: RouterResult
    ) -> None:
        """TODO (future milestone): write a GenerationAttempt row and
        update the relevant VersionedAssetMixin.quality_score. No-op in
        Milestone 1 — database writes for execution history are not
        part of this milestone's scope.
        """
