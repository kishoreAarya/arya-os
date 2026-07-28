"""
Execution Engine — Milestone 3: Validation Integration.

Reference: ARCHITECTURE_v1.0.md was not found in this project — this
was built against ARYA_OS_BUILD_INSTRUCTIONS.md's Step 1 spec instead.
Flagging the substitution rather than silently assuming they're
identical (same note as Milestones 1 and 2).

MILESTONE 3 DELTA: `_validate()` was a TODO stub returning None
unconditionally since Milestone 1 — this milestone implements it for
real, extending that same method rather than adding a new one.
Validation is opt-in per call via a new `validator_name` parameter on
execute(): pass None (the default) and nothing changes from Milestone
2's behavior. Pass a real key from VALIDATOR_REGISTRY
(app/validators/__init__.py — "story", "prompt", "image",
"consistency", "video", "thumbnail", "brand") and, after a successful
provider call, ExecutionEngine looks that validator up, runs it, and
folds the result into ExecutionResult.

INTEGRATION CONTRACT WORTH KNOWING: BaseValidator.validate() takes a
plain `artifact: dict` (e.g. StoryValidator expects
`artifact["content"]`). ExecutionEngine passes `router_result.output`
straight through as that artifact, unreshaped — it is the caller's
responsibility to make sure whatever the provider call returns is
already the shape the chosen validator expects. No agents exist yet
that call ExecutionEngine at all (ScriptAgent still calls
call_with_fallback directly, untouched — see below), so there is no
real caller to get this wrong yet; this will matter starting with
whichever agent is the first to pass a real validator_name.

KNOWN GAP CARRIED OVER FROM MILESTONE 2, NOT RE-LITIGATED HERE:
`ExecutionResult.model` still cannot be populated — see Milestone 2's
note, unchanged, still true, still not invented around.

MILESTONE 1/2 SCOPE, STILL UNCHANGED — what this file still does NOT do:
- No retry loop, anywhere, for any reason. A failed provider call or a
  failed validation both return immediately. call_with_fallback's own
  internal provider-to-provider fallback still applies (pre-existing,
  not new retry logic) — what's still deferred is retrying the SAME
  step again after a validation failure, which needs the Decision
  Engine (not built) to decide whether that's even the right move.
- No Decision Engine integration, no circuit breakers, no capability
  selection logic beyond what call_with_fallback already did, no
  prompt rewriting, no provider switching, no human approval, no
  analytics, no learning loop.
- No new validators, no changes to any existing validator, no changes
  to VALIDATOR_REGISTRY's contents — this milestone only calls what's
  already there.
- No persistence. `_persist` is still a TODO stub — no
  GenerationAttempt row is written yet, no quality_score is updated
  yet, even for a run that included a real validation result.

Beginner note: this is the layer every future agent executes through
instead of each one reimplementing its own provider call, cost
tracking, validation dispatch, and error handling. Script Agent
(app/agents/script.py) predates this file and still calls
app/providers/router.py's call_with_fallback() directly — it is NOT
rewired to use this class in this milestone either, on purpose, per
this milestone's scope (rule 12: don't modify ScriptAgent).
"""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.providers.capabilities import Capability
from app.providers.router import ProviderCall, RouterResult, call_with_fallback
from app.validators import VALIDATOR_REGISTRY
from app.validators.base import ValidationResult

logger = get_logger(__name__)


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

        try:
            router_result = await self._call_provider(
                capability=capability,
                call=call,
                workflow_run_id=workflow_run_id,
                stage=stage,
                running_cost_usd=running_cost_usd,
            )
        # Milestone 1-3: no retry/decision path yet - any failure here is terminal.
        except Exception as exc:  # noqa: BLE001
            context.elapsed_time = time.monotonic() - started
            logger.error(
                "execution_engine_call_failed",
                stage=stage,
                capability=capability.value,
                error=str(exc),
            )
            return ExecutionResult(
                success=False,
                error=str(exc),
                elapsed_time=context.elapsed_time,
                context=context,
            )

        context.provider = router_result.provider_used
        context.accumulated_cost = running_cost_usd + router_result.cost_usd

        # Validation only ever runs after a successful provider call
        # (requirement 5) — there's no path above that reaches here
        # without router_result already being a success.
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
                    context=context,
                )

            context.validation_result = validation_result

            if not validation_result.passed:
                # Requirement 7: mark failed, attach the result, return
                # immediately — no retry, no Decision Engine, no
                # persistence call, no second provider call.
                context.elapsed_time = time.monotonic() - started
                return ExecutionResult(
                    success=False,
                    output=router_result.output,
                    provider=router_result.provider_used,
                    cost_usd=router_result.cost_usd,
                    elapsed_time=context.elapsed_time,
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
            validated=validator_name is not None,
        )

        return ExecutionResult(
            success=True,
            output=router_result.output,
            provider=router_result.provider_used,
            cost_usd=router_result.cost_usd,
            elapsed_time=context.elapsed_time,
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
