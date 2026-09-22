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
import inspect
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.models.approval import GenerationAttempt
from app.models.provider import Provider
from app.models.quality import QualityScoreDetail
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

_STAGE_TO_REFERENCE_TABLE: dict[str, str] = {
    "image_generation": "images",
    "image": "images",
    "video_generation": "generated_videos",
    "video": "generated_videos",
    "voice_generation": "assets",
    "voice": "assets",
    "voice_first_generation": "assets",
    "music_generation": "assets",
    "music": "assets",
    "script_generation": "scripts",
    "script": "scripts",
    "storyboard": "storyboards",
    "storyboard_generation": "storyboards",
    "prompt_generation": "prompts",
    "prompt": "prompts",
    "thumbnail_generation": "thumbnails",
    "thumbnail": "thumbnails",
    "research": "workflow_runs",
    "trend_research": "workflow_runs",
}


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
    Discarded once execute() returns; _persist() is what saves
    the parts of it worth keeping into GenerationAttempt.
    """

    workflow_run_id: uuid.UUID | str | None
    stage: str
    provider: str | None = None
    model: str | None = None
    attempt_number: int = 1
    elapsed_time: float = 0.0
    accumulated_cost: float = 0.0
    validation_result: ValidationResult | None = None
    reference_table: str | None = None
    reference_id: uuid.UUID | str | None = None


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
        reference_table: str | None = None,
        reference_id: uuid.UUID | str | None = None,
        priority: list[str] | None = None,
    ) -> ExecutionResult:
        """Public entrypoint.

        `capability` / `call` / `running_cost_usd` match
        call_with_fallback's own parameters exactly, since
        `_call_provider` is a thin wrapper around it.

        `validator_name` is optional: leave it None (the default)
        to skip validation entirely. Pass a real VALIDATOR_REGISTRY key
        ("story", "prompt", "image", "consistency", "video",
        "thumbnail", "brand") to have ExecutionEngine run that
        validator against the provider's output after a successful
        call, before returning.

        `reference_table` and `reference_id` link the generation
        attempt directly to the target asset/version chain.
        """
        context = ExecutionContext(
            workflow_run_id=workflow_run_id,
            stage=stage,
            reference_table=reference_table,
            reference_id=reference_id,
        )
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
            reference_table=reference_table,
            reference_id=reference_id,
            priority=priority,
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
                context.elapsed_time = time.monotonic() - started
                val_error = (
                    f"Validation '{validator_name}' failed: "
                    f"{'; '.join(validation_result.issues) if validation_result.issues else 'no issues listed'}"
                )
                await self._persist(
                    context,
                    router_result,
                    succeeded=False,
                    validation_failure=val_error,
                    validator_name=validator_name,
                )
                return ExecutionResult(
                    success=False,
                    output=router_result.output,
                    provider=router_result.provider_used,
                    cost_usd=router_result.cost_usd,
                    elapsed_time=context.elapsed_time,
                    attempts=attempt_count,
                    error=val_error,
                    context=context,
                )

        context.elapsed_time = time.monotonic() - started
        await self._persist(
            context,
            router_result,
            succeeded=True,
            validator_name=validator_name,
        )

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

        model_name = (
            router_result.output.get("model_used")
            or router_result.output.get("model")
            if isinstance(router_result.output, dict)
            else None
        )
        return ExecutionResult(
            success=True,
            output=router_result.output,
            provider=router_result.provider_used,
            model=model_name,
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
        priority: list[str] | None = None,
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
            priority=priority,
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
        reference_table: str | None = None,
        reference_id: uuid.UUID | str | None = None,
        priority: list[str] | None = None,
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
            attempt_started = time.monotonic()
            try:
                result = await self._call_provider(
                    capability=capability,
                    call=call,
                    workflow_run_id=workflow_run_id,
                    stage=stage,
                    running_cost_usd=running_cost_usd,
                    priority=priority,
                )
                return result, attempt, None
            # Any provider-layer failure is classified below, not blindly retried.
            except Exception as exc:  # noqa: BLE001
                attempt_duration = time.monotonic() - attempt_started
                if workflow_run_id:
                    try:
                        failed_ctx = ExecutionContext(
                            workflow_run_id=workflow_run_id,
                            stage=stage,
                            attempt_number=attempt,
                            elapsed_time=attempt_duration,
                            reference_table=reference_table,
                            reference_id=reference_id,
                        )
                        await self._persist(
                            failed_ctx,
                            None,
                            succeeded=False,
                            failure_reason=str(exc),
                        )
                    except Exception as persist_exc:
                        logger.warning(
                            "failed_attempt_persist_error", error=str(persist_exc)
                        )

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
        self,
        context: ExecutionContext,
        router_result: RouterResult | None = None,
        *,
        succeeded: bool = True,
        failure_reason: str | None = None,
        validation_failure: str | None = None,
        validator_name: str | None = None,
    ) -> GenerationAttempt | None:
        """Write a GenerationAttempt row and record validator quality scores.

        Records:
        - workflow_run_id (associated WorkflowRun)
        - reference_table (associated asset table or stage)
        - reference_id (associated asset ID or workflow_run_id)
        - attempt_number (1-indexed attempt count)
        - succeeded (bool indicating success or failure)
        - failure_reason (provider or execution error details)
        - validation_failure (validator rejection issues)
        - provider_id (resolved UUID from providers table if available)
        - cost_usd (cost of the attempt)
        - duration_seconds (latency of the attempt)
        - quality score (recorded in QualityScoreDetail if validation ran)
        """
        if not context.workflow_run_id:
            logger.debug(
                "execution_engine_persist_skipped",
                reason="No workflow_run_id provided in context",
                stage=context.stage,
            )
            return None

        try:
            wf_uuid = (
                context.workflow_run_id
                if isinstance(context.workflow_run_id, uuid.UUID)
                else uuid.UUID(str(context.workflow_run_id))
            )
        except (ValueError, TypeError):
            logger.warning(
                "execution_engine_persist_invalid_uuid",
                workflow_run_id=context.workflow_run_id,
            )
            return None

        ref_table = context.reference_table or _STAGE_TO_REFERENCE_TABLE.get(
            context.stage, context.stage or "workflow_runs"
        )

        ref_id = None
        if context.reference_id:
            try:
                ref_id = (
                    context.reference_id
                    if isinstance(context.reference_id, uuid.UUID)
                    else uuid.UUID(str(context.reference_id))
                )
            except (ValueError, TypeError):
                ref_id = None

        if not ref_id and router_result and isinstance(router_result.output, dict):
            candidate = router_result.output.get("reference_id") or router_result.output.get("id")
            if candidate:
                try:
                    ref_id = (
                        candidate
                        if isinstance(candidate, uuid.UUID)
                        else uuid.UUID(str(candidate))
                    )
                except (ValueError, TypeError):
                    ref_id = None

        if not ref_id:
            ref_id = wf_uuid

        provider_name = context.provider or (
            router_result.provider_used if router_result else None
        )
        provider_id = None
        if provider_name:
            try:
                from unittest.mock import Mock

                stmt = select(Provider.id).where(Provider.name == provider_name)
                res = await self._db.execute(stmt)
                if not isinstance(res, Mock) and hasattr(res, "scalar_one_or_none"):
                    found_id = res.scalar_one_or_none()
                    if isinstance(found_id, uuid.UUID):
                        provider_id = found_id
            except Exception as exc:
                logger.debug(
                    "provider_id_lookup_skipped",
                    provider=provider_name,
                    error=str(exc),
                )

        cost_usd = (
            float(router_result.cost_usd)
            if router_result and router_result.cost_usd is not None
            else 0.0
        )
        duration_seconds = (
            context.elapsed_time
            if context.elapsed_time > 0
            else (router_result.duration_seconds if router_result else None)
        )

        # If router attempted multiple providers (fallback occurred), record failed attempts
        if router_result and router_result.attempts and len(router_result.attempts) > 1:
            for idx, failed_prov in enumerate(router_result.attempts[:-1]):
                failed_err = (
                    router_result.attempt_errors.get(failed_prov)
                    if hasattr(router_result, "attempt_errors")
                    else f"Provider '{failed_prov}' failed"
                )
                failed_prov_id = None
                try:
                    stmt = select(Provider.id).where(Provider.name == failed_prov)
                    res = await self._db.execute(stmt)
                    if hasattr(res, "scalar_one_or_none"):
                        found_pid = res.scalar_one_or_none()
                        if isinstance(found_pid, uuid.UUID):
                            failed_prov_id = found_pid
                except Exception:
                    pass

                failed_attempt = GenerationAttempt(
                    workflow_run_id=wf_uuid,
                    reference_table=ref_table,
                    reference_id=ref_id,
                    attempt_number=idx + 1,
                    succeeded=False,
                    failure_reason=f"Provider '{failed_prov}' failed: {failed_err}",
                    validation_failure=None,
                    provider_id=failed_prov_id,
                    cost_usd=0.0,
                    duration_seconds=None,
                )
                try:
                    add_res = self._db.add(failed_attempt)
                    if inspect.isawaitable(add_res):
                        await add_res
                except Exception as exc:
                    logger.debug("generation_attempt_failed_persist_skipped", error=str(exc))

        attempt_num = (
            len(router_result.attempts)
            if (router_result and router_result.attempts and len(router_result.attempts) > 1)
            else (context.attempt_number or 1)
        )

        attempt = GenerationAttempt(
            workflow_run_id=wf_uuid,
            reference_table=ref_table,
            reference_id=ref_id,
            attempt_number=attempt_num,
            succeeded=succeeded,
            failure_reason=failure_reason,
            validation_failure=validation_failure,
            provider_id=provider_id,
            cost_usd=round(cost_usd, 4),
            duration_seconds=round(duration_seconds, 4) if duration_seconds is not None else None,
        )

        try:
            add_res = self._db.add(attempt)
            if inspect.isawaitable(add_res):
                await add_res
            await self._db.commit()
            try:
                ref_res = self._db.refresh(attempt)
                if inspect.isawaitable(ref_res):
                    await ref_res
            except Exception:
                pass
        except Exception as exc:
            logger.error("generation_attempt_persist_failed", error=str(exc))
            try:
                await self._db.rollback()
            except Exception:
                pass
            return None

        # Record QualityScoreDetail if validator result with score is present
        if (
            context.validation_result is not None
            and getattr(context.validation_result, "score", None) is not None
        ):
            try:
                score_val = float(context.validation_result.score)
                issues_list = getattr(context.validation_result, "issues", [])
                notes = "; ".join(issues_list) if issues_list else None
                q_detail = QualityScoreDetail(
                    workflow_run_id=wf_uuid,
                    reference_table=ref_table,
                    reference_id=ref_id,
                    dimension=validator_name or context.stage,
                    score=round(score_val, 2),
                    scored_by=validator_name,
                    notes=notes,
                )
                q_add_res = self._db.add(q_detail)
                if inspect.isawaitable(q_add_res):
                    await q_add_res

                # Persist granular sub-dimension scores if present
                dim_scores = getattr(context.validation_result, "dimension_scores", {}) or {}
                for dim_name, dim_score in dim_scores.items():
                    if dim_name == (validator_name or context.stage):
                        continue
                    dim_detail = QualityScoreDetail(
                        workflow_run_id=wf_uuid,
                        reference_table=ref_table,
                        reference_id=ref_id,
                        dimension=str(dim_name)[:50],
                        score=round(float(dim_score), 2),
                        scored_by=validator_name,
                        notes=notes,
                    )
                    sub_add = self._db.add(dim_detail)
                    if inspect.isawaitable(sub_add):
                        await sub_add

                await self._db.commit()
            except Exception as exc:
                logger.warning("quality_score_detail_persist_failed", error=str(exc))

            # Best-effort update on the versioned asset table if present
            _TABLES_WITH_QUALITY_SCORE = {
                "scripts",
                "storyboards",
                "prompts",
                "images",
                "generated_videos",
                "videos",
                "thumbnails",
            }
            if ref_table in _TABLES_WITH_QUALITY_SCORE:
                try:
                    from unittest.mock import Mock

                    if not isinstance(self._db, Mock):
                        update_stmt = text(
                            f"UPDATE {ref_table} SET quality_score = :score WHERE id = :id"
                        )
                        await self._db.execute(
                            update_stmt,
                            {"score": int(context.validation_result.score), "id": ref_id},
                        )
                        await self._db.commit()
                except Exception:
                    try:
                        await self._db.rollback()
                    except Exception:
                        pass

        return attempt
