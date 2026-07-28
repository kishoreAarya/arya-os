"""
Execution Engine — Milestone 2: Provider Execution Integration.

Reference: ARCHITECTURE_v1.0.md was not found in this project — this
was built against ARYA_OS_BUILD_INSTRUCTIONS.md's Step 1 spec instead.
Flagging the substitution rather than silently assuming they're
identical (same note as Milestone 1).

MILESTONE 2 DELTA (most of "integrate the Provider Router" was already
done in Milestone 1, since _call_provider() was built as a real
wrapper rather than a stub from the start — this milestone adds only
what was genuinely still missing):
- An explicit "execution succeeded" log line (Milestone 1 only logged
  start and failure).
- Field names on ExecutionResult aligned to this milestone's spec:
  `provider_used` -> `provider`, `duration_seconds` -> `elapsed_time`
  (the latter also now matches ExecutionContext's field name, fixing
  a naming inconsistency Milestone 1 introduced between the two
  dataclasses).
- A `model` field on ExecutionResult, per spec — but see the note on
  it below. Nothing else about provider selection, retries, or
  fallback changed; that logic already existed in
  app/providers/router.py before Milestone 1 and is untouched here.

KNOWN GAP, NOT INVENTED AROUND: `model` cannot actually be populated
yet. Neither RouterResult (app/providers/router.py) nor
openrouter.generate_text()'s return value carries which model was
used — only the caller happens to know, because it chose the model
itself before calling. Populating this for real means extending
RouterResult's shape, which is a change to the Provider Router's own
contract, not something in this milestone's scope ("integrate through
its public interface only, do not bypass it" — extending its return
shape is a design decision for a future milestone, not this one). The
field exists on ExecutionResult now, per spec, and is always None
until that decision is made.

MILESTONE 1 SCOPE, STILL UNCHANGED — what this file still does NOT do:
- No retry loop. `_call_provider` makes exactly one call to
  call_with_fallback and returns or raises. call_with_fallback's own
  internal provider-to-provider fallback still applies (that already
  existed and isn't new retry logic) — what's deferred is retrying
  the SAME step again after a validation failure, which needs the
  Decision Engine to decide whether that's even the right move.
- No Decision Engine integration, no circuit breakers, no capability
  selection logic beyond what call_with_fallback already did, no
  human approval, no analytics, no learning loop.
- No real validation. `_validate` is a TODO stub returning None.
- No persistence. `_persist` is a TODO stub — no GenerationAttempt
  row is written yet, no quality_score is updated yet.

Beginner note: this is the layer every future agent executes through
instead of each one reimplementing its own provider call, cost
tracking, and error handling. Script Agent (app/agents/script.py)
predates this file and still calls app/providers/router.py's
call_with_fallback() directly — it is NOT rewired to use this class in
this milestone, on purpose, per this milestone's scope (rule 9: don't
modify ScriptAgent). That's a follow-up milestone, once ExecutionEngine
has proven itself on a second agent (Storyboard) first.
"""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.log import EventType, log_event
from app.providers.capabilities import Capability
from app.providers.router import ProviderCall, RouterResult, call_with_fallback
from app.validators.base import ValidationResult

logger = get_logger(__name__)


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
    ) -> ExecutionResult:
        """Public entrypoint. Milestone 1: one provider call, no retry
        loop, no Decision Engine, validation/persistence are no-ops.

        `capability` / `call` / `running_cost_usd` match
        call_with_fallback's own parameters exactly, since this
        milestone's `_call_provider` is a thin wrapper around it — see
        the module docstring for why nothing beyond that is built yet.
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
        # Milestone 1: no retry/decision path yet - any failure here is terminal.
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

        # TODO (future milestone): real validation against a BaseValidator.
        context.validation_result = await self._validate(router_result.output)

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

    async def _validate(self, output: object) -> ValidationResult | None:
        """TODO (future milestone): call the matching BaseValidator
        (app/validators/base.py) on `output` and return its
        ValidationResult. Deliberately a no-op in Milestone 1 — no
        validator is implemented yet, and wiring one in here without
        a Decision Engine to act on a failed result would have
        nowhere to route a failure anyway.
        """
        return None

    async def _persist(
        self, context: ExecutionContext, router_result: RouterResult
    ) -> None:
        """TODO (future milestone): write a GenerationAttempt row and
        update the relevant VersionedAssetMixin.quality_score. No-op in
        Milestone 1 — database writes for execution history are not
        part of this milestone's scope.
        """
