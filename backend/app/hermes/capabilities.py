"""
AryaOS typed capability registry — §9 Slice 1 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §9 ("Hermes acts
only through typed, capability-scoped operations exposed as tools... Each
maps to exactly one AryaOS operation surface"; "names are the tool names
Hermes sees"; "typed (Pydantic schema per capability), validated before
execution"), §4.5 (no god tool), §11 (malformed requests).

Slice 1 scope: the frozen registry, strict Pydantic v2 parameter schemas,
deterministic pre-execution validation, and the read-only binding
research.search -> TrendDiscoveryService.discover_trends
(app/services/trend_sources/service.py:95). Slice 2 added the read-only
binding asset.get -> the existing AryaOS assets table
(app/models/media.py:61) with tenant verification via WorkflowRun.
project_id against the job-bound AuthorizationContext (operator-approved
decisions A/B/C). Slice 3 (§9.3, operator decisions D1-D3) added the
first CHARGEABLE binding provider.generate -> the existing AryaOS
ExecutionEngine/provider router (TEXT_GENERATION only), with the §12
USD budget enforced BEFORE execution against the WorkflowRun's
authoritative accumulated total_cost_usd. Slice 4 (§13.3) added
execution-outcome audit records for the non-chargeable bindings
(research.search, asset.get): outcome/duration with cost_estimate_usd
None (not chargeable), reasons from the bindings' own structured error
contract. All other capabilities are
NAMES ONLY (authorized by §4's frozen TYPED_CAPABILITIES, but no schema
and no binding exist yet — they cannot be executed and are not exposed
to the model).

Security model:
- The registry is the ONLY source of exposed AryaOS capability tools.
  The model cannot select bindings, supply handlers, create
  capabilities, or reach a generic dispatcher: the plugin registers
  exactly the frozen registry's tools (toolset "aryaos", no override),
  §4 authorizes the name first, this module validates parameters second,
  §12 counts third, and only then may the binding execute.
- Validation is strict Pydantic v2 (extra="forbid"); unknown, missing,
  mistyped, or extra parameters, unknown capabilities, and validation
  exceptions all fail closed with the deterministic reason
  "capability_schema_invalid". Error details carry field locations and
  error types ONLY — never parameter values or secrets.
- A schema rejection on a §4-authorized capability additionally emits an
  additive §13.1 final-outcome audit record (BLOCK,
  "capability_schema_invalid") via app.hermes.audit.record_final_outcome;
  the §4 ALLOW record stands unchanged and the binding never executes.
  Audit is authorization-preserving and best-effort.
- Binding exceptions surface as structured tool-result failures
  ({"error": {...}}); they never widen authorization or counting.

policy.py is deliberately NOT modified: registry <-> TYPED_CAPABILITIES
consistency is proven by test, per the slice contract.
"""
import threading
import time
import types
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.logging import get_logger

logger = get_logger("arya.hermes.capabilities")

CAPABILITY_TOOLSET = "aryaos"
CAPABILITY_SCHEMA_INVALID = "capability_schema_invalid"
_BINDING_FAILURE = "capability_binding_failed"

_REDDIT_TIME_FILTERS = ("all", "day", "hour", "month", "week", "year")


class ResearchSearchParams(BaseModel):
    """§9 research.search — read-only research over AryaOS trend sources.

    Strict: unknown fields are forbidden; the internal AryaOS `feedback`
    input of TrendDiscoveryService.discover_trends is deliberately NOT
    model-controllable.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=5, ge=1, le=25)
    subreddit: str | None = Field(default=None, min_length=1, max_length=64)
    time_filter: Literal["all", "day", "hour", "month", "week", "year"] = "all"


class AssetGetParams(BaseModel):
    """§9 asset.get — read-only metadata lookup by ID from the AryaOS
    assets table (operator decisions A/C). Strict; the authoritative
    project scope comes from the job-bound AuthorizationContext, never
    from model input. The underlying file is NEVER read, opened, or
    dereferenced."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    workflow_run_id: uuid.UUID | None = None  # optional extra ownership guard


class ProviderGenerateParams(BaseModel):
    """§9 provider.generate — text generation through the AryaOS
    capability-based provider router (Slice 3, operator decision D1:
    TEXT_GENERATION only).

    Strict; the single field mirrors the ONLY input the existing text
    dispatcher accepts (providers/text_dispatch.py:52
    ``build_text_generation_call(prompt)``). Provider selection, model
    resolution, and credentials are resolved INTERNALLY by the
    dispatcher/SecretsManager — the model can never supply or control
    secrets, providers, endpoints, or routing. The authoritative run
    identity comes from the job-bound AuthorizationContext, never from
    model input."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=32_000)


@dataclass(frozen=True)
class CapabilitySpec:
    """One typed capability: name (the Hermes tool name), strict parameter
    schema, model-facing description, and the AryaOS binding executor that
    receives the VALIDATED parameters. `binding` is None for capabilities
    whose binding ships in a later slice — those are authorization-known
    (§4) but neither exposed nor executable."""

    name: str
    description: str
    schema_model: type[BaseModel] | None
    binding: Callable[[BaseModel], Any] | None


def _audit_readonly_execution(
    tool_name: str,
    params,
    duration_seconds: float,
    result: dict | None = None,
    *,
    failure_code: str | None = None,
) -> None:
    """§13.3 best-effort execution-outcome emission for the NON-chargeable
    bindings (research.search, asset.get), per operator decisions:

    - D1″: emitted inside the binding (§13.2 pattern), never from
      execute_capability; no generic capability-wide auditing.
    - D2″: cost_estimate_usd is None — these capabilities are not
      chargeable (semantically distinct from provider.generate's failure
      cost 0.0); no cost is invented and no accounting is touched.
    - D3″: the failure reason is the code of the binding's OWN existing
      structured error contract ({"error": {"code": ...}}), or the
      deterministic capability_binding_failed code the existing wrapper
      assigns when the binding raises (the binding emits-and-reraises;
      the wrapper's result is unchanged).

    Parameter VALUES are never recorded — only the digest of the
    validated parameters. Never raises (execution-preserving audit)."""
    try:
        from app.hermes.audit import record_execution_outcome

        if failure_code is not None:
            outcome, reason = "failure", failure_code
        elif isinstance(result, dict) and "error" in result:
            outcome, reason = "failure", str((result.get("error") or {}).get("code", ""))
        else:
            outcome, reason = "success", None
        record_execution_outcome(
            tool_name,
            params.model_dump(),
            outcome,
            duration_seconds=duration_seconds,
            cost_estimate_usd=None,
            reason_code=reason,
        )
    except Exception:
        pass  # execution-preserving, best-effort audit (§13.3)


async def _research_search_binding(params: ResearchSearchParams) -> dict:
    """Execute the research.search capability against the existing AryaOS
    trend_sources surface (read-only exemplar binding)."""
    started = time.monotonic()
    try:
        service = _trend_discovery_service()
        signals = await service.discover_trends(
            topic_hint=params.topic,
            limit=params.limit,
            subreddit=params.subreddit,
            time_filter=params.time_filter,
        )
        result = {
            "topic": params.topic,
            "results": [signal.to_dict() for signal in signals],
        }
    except BaseException:
        _audit_readonly_execution(
            "research.search", params, time.monotonic() - started, failure_code=_BINDING_FAILURE
        )
        raise
    _audit_readonly_execution("research.search", params, time.monotonic() - started, result)
    return result


_TREND_SERVICE = None


def _trend_discovery_service():
    """Lazy singleton: read-only service, cheap construction, shared cache."""
    global _TREND_SERVICE
    if _TREND_SERVICE is None:
        from app.services.trend_sources.service import TrendDiscoveryService

        _TREND_SERVICE = TrendDiscoveryService()
    return _TREND_SERVICE


# Uniform failure for nonexistent AND foreign-project assets: a single
# externally visible category avoids an enumeration oracle (operator
# decision B).
_ASSET_NOT_FOUND = {"error": {"code": "asset_not_found", "detail": "no such asset in this project"}}


def _make_capability_engine():
    """Per-call disposable async engine for capability bindings.

    Why not the global engine (app.database.session): Hermes async tool
    handlers execute on a fresh event loop per call
    (model_tools._run_async:92-122 at the pin), and asyncpg pool
    connections are loop-bound — sharing the global pool across loops is
    unsafe. A per-call engine created from the existing
    settings.database_url adds no global state and is disposed on every
    path (see the bindings' finally blocks). asset.get uses it read-only;
    the §9.3 provider.generate binding uses the same engine with a
    writable session for normal AryaOS bookkeeping (GenerationAttempt +
    WorkflowRun.total_cost_usd, caller-side update per the creator.py
    precedent)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings

    return create_async_engine(get_settings().database_url, echo=False)


async def _asset_get_binding(params: AssetGetParams) -> dict:
    """Execute the asset.get capability: read-only metadata lookup by ID
    with tenant verification through WorkflowRun.project_id against the
    job-bound AuthorizationContext (operator decisions A/B).

    STRICT boundary: returns metadata/reference fields only — the file at
    storage_path is never read, opened, resolved, or dereferenced.
    """
    started = time.monotonic()
    from app.hermes.runtime import get_active_authorization_context

    try:
        context = get_active_authorization_context()
    except RuntimeError:
        context = None
    if context is None:
        # No job-bound context can only mean an out-of-runtime invocation;
        # fail closed with the uniform not-found (no data leaves).
        result = dict(_ASSET_NOT_FOUND)
        _audit_readonly_execution("asset.get", params, time.monotonic() - started, result)
        return result
    expected_project = context.project_id.strip()

    from app.models.core import WorkflowRun
    from app.models.media import Asset

    engine = _make_capability_engine()
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            asset = await session.get(Asset, params.asset_id)
            if asset is None or (
                params.workflow_run_id is not None and params.workflow_run_id != asset.workflow_run_id
            ):
                result = dict(_ASSET_NOT_FOUND)
            else:
                run = await session.get(WorkflowRun, asset.workflow_run_id)
                if run is None or str(run.project_id) != expected_project:
                    result = dict(_ASSET_NOT_FOUND)
                else:
                    result = {
                        "asset_id": str(asset.id),
                        "workflow_run_id": str(asset.workflow_run_id),
                        "asset_type": asset.asset_type,
                        "provider_name": asset.provider_name,
                        "storage_path": asset.storage_path,  # reference only (decision C)
                        "created_at": asset.created_at.isoformat() if asset.created_at else None,
                    }
    except BaseException:
        _audit_readonly_execution(
            "asset.get", params, time.monotonic() - started, failure_code=_BINDING_FAILURE
        )
        raise
    finally:
        await engine.dispose()
    _audit_readonly_execution("asset.get", params, time.monotonic() - started, result)
    return result


# §9.3 provider.generate deterministic result/error codes (value-free
# details: never prompt text, exception payloads, or credentials).
_PROVIDER_UNAVAILABLE = "provider_unavailable"
_COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
_GENERATION_RUN_UNAVAILABLE = "generation_run_unavailable"

# §9.3 F1 correction: process-local per-job serialization of the chargeable
# critical section (read accumulated spend -> budget decision -> provider
# execution -> run-total update). Hermes runs registry tools in parallel
# tool segments on worker threads (agent/tool_executor.py:1504,
# _plan_tool_segments; provider.generate is not in _NEVER_PARALLEL_TOOLS),
# so two same-turn calls would otherwise both read the same stale
# WorkflowRun.total_cost_usd, both pass the budget check, and one
# run-total write would clobber the other. The runtime's _RUNTIME_LOCK
# guarantees at most ONE embedded Hermes job per process (runtime.py §3),
# which makes this module-level lock exactly job-scoped for the embedded
# runtime — the same threading.Lock primitive JobLimitLedger already uses.
# Multi-PROCESS Hermes execution is outside the current architecture
# (one job at a time per process, per the §3/§12 no-concurrency contract).
_GENERATION_CRITICAL_SECTION = threading.Lock()


async def _provider_generate_binding(params: ProviderGenerateParams) -> dict:
    """Execute the §9.3 provider.generate capability: text generation
    through the EXISTING AryaOS execution machinery (ExecutionEngine →
    provider router → adapter), never a parallel provider path.

    Security/bookkeeping contract:
    - The run identity comes from the job-bound AuthorizationContext
      (workflow_run_id + project_id tenant check); model input can never
      supply or override it.
    - The §12 USD budget is enforced BEFORE any chargeable execution,
      with the router's own ceiling semantics (router.py:89: accumulated
      spend at/over the configured maximum -> refuse; per-call cost is
      only knowable after execution). Denial notes the ledger violation
      (§11/§12: job fails, no silent continuation) and emits a §13.1
      final-outcome record; ExecutionEngine/router are never invoked.
    - Accumulated spend is the WorkflowRun's authoritative
      total_cost_usd — the same value the router's running_cost_usd
      contract defines — updated caller-side on success (creator.py
      precedent). Adapter costs are provider execution estimates.
    - execute() returns failures instead of raising; they map to the
      structured Hermes error contract by the router's frozen message
      contracts (CostLimitExceededError / AllProvidersFailedError).
    - F1: the whole read->decide->execute->update critical section is
      serialized per Hermes job (_GENERATION_CRITICAL_SECTION), so
      same-turn parallel provider.generate calls cannot both pass a
      stale budget check or lose a run-total update.
    """
    from app.hermes.limits import REASON_GENERATION_BUDGET
    from app.hermes.runtime import (
        get_active_authorization_context,
        get_active_job_ledger,
    )

    def _err(code: str, detail: str) -> dict:
        return {"error": {"code": code, "detail": detail}}

    def _audit_denial() -> None:
        """§13.2: a binding-level denial is a first-class §13.1 BLOCK event."""
        try:
            from app.hermes.audit import record_final_outcome

            record_final_outcome(
                "provider.generate", {"prompt": params.prompt}, _GENERATION_RUN_UNAVAILABLE
            )
        except Exception:
            pass  # authorization-preserving, best-effort audit (§13.2)

    def _audit_execution(outcome: str, reason: str | None, duration: float, cost: float) -> None:
        """§13.2: one execution-outcome record per EXECUTED call, from
        authoritative ExecutionResult data only (estimate, never billing)."""
        try:
            from app.hermes.audit import record_execution_outcome

            record_execution_outcome(
                "provider.generate",
                {"prompt": params.prompt},
                outcome,
                duration_seconds=duration,
                cost_estimate_usd=cost,
                reason_code=reason,
            )
        except Exception:
            pass  # execution-preserving, best-effort audit (§13.2)

    try:
        context = get_active_authorization_context()
    except RuntimeError:
        context = None
    ledger = get_active_job_ledger()
    if context is None or ledger is None:
        # Out-of-runtime invocation: a chargeable call never executes.
        _audit_denial()
        return _err(_GENERATION_RUN_UNAVAILABLE, "no active AryaOS authorization context")
    expected_project = context.project_id.strip()
    try:
        run_uuid = uuid.UUID(str(context.workflow_run_id))
    except (ValueError, TypeError):
        _audit_denial()
        return _err(_GENERATION_RUN_UNAVAILABLE, "workflow_run_id is not a valid identifier")
    from app.core.config import get_settings

    budget = get_settings().hermes_max_generation_budget_usd

    # §9.3 F1: the ENTIRE chargeable critical section — read accumulated
    # spend -> budget decision -> provider execution -> run-total update —
    # is serialized per Hermes job (see _GENERATION_CRITICAL_SECTION). A
    # concurrent same-turn call therefore re-reads the post-commit total
    # and can never pass a stale budget check or clobber the update.
    with _GENERATION_CRITICAL_SECTION:
        engine = _make_capability_engine()
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                from app.models.core import WorkflowRun

                run = await session.get(WorkflowRun, run_uuid)
                # Uniform failure for nonexistent AND foreign-project runs (the
                # asset.get anti-enumeration discipline).
                if run is None or str(run.project_id) != expected_project:
                    _audit_denial()
                    return _err(_GENERATION_RUN_UNAVAILABLE, "no such workflow run in this project")
                if budget is None:
                    # §12: unbounded chargeable execution is not permitted.
                    return _err(
                        REASON_GENERATION_BUDGET,
                        "hermes_max_generation_budget_usd is not configured; chargeable call denied",
                    )
                accumulated = float(run.total_cost_usd or 0.0)
                if accumulated >= float(budget):
                    ledger.note_generation_budget_exceeded()
                    try:
                        from app.hermes.audit import record_final_outcome

                        record_final_outcome(
                            "provider.generate", {"prompt": params.prompt}, REASON_GENERATION_BUDGET
                        )
                    except Exception:
                        pass  # authorization-preserving, best-effort audit
                    return _err(
                        REASON_GENERATION_BUDGET,
                        f"accumulated generation spend ${accumulated:.4f} is at/over "
                        f"hermes_max_generation_budget_usd; chargeable call denied before execution",
                    )

                from app.providers.capabilities import Capability
                from app.providers.text_dispatch import build_text_generation_call
                from app.services.execution_engine import ExecutionEngine

                result = await ExecutionEngine(session).execute(
                    capability=Capability.TEXT_GENERATION,
                    call=build_text_generation_call(params.prompt),
                    workflow_run_id=run_uuid,
                    stage="hermes_text_generation",
                    running_cost_usd=accumulated,
                )
                if not result.success:
                    error_text = result.error or ""
                    duration = float(result.elapsed_time or 0.0)
                    if "max_cost_per_video_usd" in error_text:
                        _audit_execution("failure", _COST_LIMIT_EXCEEDED, duration, 0.0)
                        return _err(_COST_LIMIT_EXCEEDED, "provider cost ceiling reached before execution")
                    _audit_execution("failure", _PROVIDER_UNAVAILABLE, duration, 0.0)
                    return _err(_PROVIDER_UNAVAILABLE, "all providers failed or errored")
                # Caller-side run-total update (creator.py precedent); the engine
                # already wrote and committed its GenerationAttempt.
                run.total_cost_usd = accumulated + float(result.cost_usd or 0.0)
                await session.commit()
                _audit_execution(
                    "success", None, float(result.elapsed_time or 0.0), float(result.cost_usd or 0.0)
                )
                return {
                    "text": str(result.output),
                    "provider": result.provider,
                    "cost_usd": float(result.cost_usd or 0.0),
                    "duration_seconds": float(result.elapsed_time or 0.0),
                    "attempts": int(result.attempts or 1),
                }
        finally:
            await engine.dispose()


_REGISTRY: dict[str, CapabilitySpec] = {
    "research.search": CapabilitySpec(
        name="research.search",
        description=(
            "Search AryaOS research/trend sources for signals relevant to a "
            "topic (read-only). Returns ranked trend signals."
        ),
        schema_model=ResearchSearchParams,
        binding=_research_search_binding,
    ),
    "asset.get": CapabilitySpec(
        name="asset.get",
        description=(
            "Read asset metadata/reference by ID from the AryaOS asset "
            "registry (read-only; returns metadata only, never file "
            "content)."
        ),
        schema_model=AssetGetParams,
        binding=_asset_get_binding,
    ),
    "research.get": CapabilitySpec(
        name="research.get",
        description="Fetch one research item by ID (binding arrives in a later slice).",
        schema_model=None,
        binding=None,
    ),
    "story.create": CapabilitySpec(
        name="story.create",
        description="Create/revise story drafts as proposals (later slice).",
        schema_model=None,
        binding=None,
    ),
    "memory.retrieve": CapabilitySpec(
        name="memory.retrieve",
        description="Read-only retrieval from AryaOS memory (later slice).",
        schema_model=None,
        binding=None,
    ),
    "provider.generate": CapabilitySpec(
        name="provider.generate",
        description=(
            "Generate text through the AryaOS provider router "
            "(text generation only; provider/model/credentials are "
            "AryaOS-internal)."
        ),
        schema_model=ProviderGenerateParams,
        binding=_provider_generate_binding,
    ),
    "agent.request": CapabilitySpec(
        name="agent.request",
        description="Request work from a registered AryaOS agent via the AryaOS queue (later slice).",
        schema_model=None,
        binding=None,
    ),
    "evaluation.run": CapabilitySpec(
        name="evaluation.run",
        description="Run an evaluator to produce evidence (later slice).",
        schema_model=None,
        binding=None,
    ),
    "publishing.request": CapabilitySpec(
        name="publishing.request",
        description="Request publishing for an AryaOS publish job (later slice).",
        schema_model=None,
        binding=None,
    ),
}

# Frozen registry: the only source of exposed AryaOS capability tools.
# MappingProxyType makes mutation fail loudly at runtime.
CAPABILITY_REGISTRY: Mapping[str, CapabilitySpec] = types.MappingProxyType(_REGISTRY)

# Capabilities exposed to the model in this slice: bound + schematized only.
EXPOSED_CAPABILITIES: frozenset[str] = frozenset(
    name for name, spec in _REGISTRY.items() if spec.schema_model is not None and spec.binding is not None
)


def _schema_error_detail(exc: ValidationError) -> str:
    """Deterministic, value-free error detail: field locations and error
    types only. Pydantic embeds input values in some messages, so only the
    sanitized loc/type pairs are used."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err.get("loc", ())) or "<root>"
        parts.append(f"{loc}:{err.get('type', 'invalid')}")
    return "; ".join(sorted(parts)) or "invalid"


@dataclass(frozen=True)
class CapabilityValidation:
    """Deterministic validation outcome (never an exception)."""

    ok: bool
    reason: str | None
    detail: str | None
    validated: BaseModel | None


def validate_capability_parameters(name: object, parameters: object) -> CapabilityValidation:
    """Validate one capability request's parameters (§9: validated before
    execution; §11: malformed fails closed).

    Never raises. Native sanctioned tools (not registry names) pass through
    — they are not capabilities and are governed by §5.1/§4 alone.
    """
    if not isinstance(name, str) or name not in CAPABILITY_REGISTRY:
        # Unknown capability is an authorization matter (§4 blocks it);
        # validation has nothing to add.
        return CapabilityValidation(ok=True, reason=None, detail=None, validated=None)
    spec = CAPABILITY_REGISTRY[name]
    if spec.schema_model is None:
        # Authorized name without a shipped schema/binding: it is not
        # exposed to the model in this slice, so a request for it cannot
        # arrive through the tool surface; treat any direct request as
        # schema-invalid (fail closed) rather than executable.
        return CapabilityValidation(
            ok=False,
            reason=CAPABILITY_SCHEMA_INVALID,
            detail="capability_not_exposed_in_this_slice",
            validated=None,
        )
    if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
        return CapabilityValidation(
            ok=False,
            reason=CAPABILITY_SCHEMA_INVALID,
            detail="parameters_not_a_json_object",
            validated=None,
        )
    try:
        validated = spec.schema_model.model_validate(parameters)
    except ValidationError as exc:
        return CapabilityValidation(
            ok=False,
            reason=CAPABILITY_SCHEMA_INVALID,
            detail=_schema_error_detail(exc),
            validated=None,
        )
    except BaseException:  # noqa: BLE001 — validation must never fail open
        return CapabilityValidation(
            ok=False,
            reason=CAPABILITY_SCHEMA_INVALID,
            detail="schema_validation_error",
            validated=None,
        )
    return CapabilityValidation(ok=True, reason=None, detail=None, validated=validated)


def make_capability_validating_hook(base_hook: Callable):
    """Wrap the §4 policy hook with §9 parameter validation.

    Chain order (approved): §4 authorization FIRST, then schema
    validation, with §12 outermost (limits.py). §4 BLOCK directives pass
    through verbatim; a schema-invalid request on an authorized
    capability is BLOCKed with the deterministic
    "capability_schema_invalid" reason and emits an additive §13.1
    final-outcome audit record (the §4 ALLOW record is preserved
    unchanged; §4 logic and ordering are untouched). Never raises; block
    messages carry names and reasons only — never parameter values.
    """
    from app.hermes.policy import POLICY_PLUGIN_MARKER

    def capability_validating_hook(tool_name: str, args: dict | None = None, **_hook_kwargs: Any):
        try:
            decision = base_hook(tool_name, args, **_hook_kwargs)
            if decision is not None:  # §4 BLOCK — authorization refused
                return decision
            validation = validate_capability_parameters(tool_name, args)
            if validation.ok:
                return None
            try:
                from app.hermes.audit import record_final_outcome

                record_final_outcome(tool_name, args, validation.reason)
            except Exception:
                pass  # authorization-preserving, best-effort audit (§13.1)
            return {
                "action": "block",
                "message": (
                    f"Blocked by AryaOS policy gate ({validation.reason}: "
                    f"{validation.detail}): {tool_name!r}"
                ),
            }
        except BaseException:  # noqa: BLE001 — never raise, fail closed
            return {
                "action": "block",
                "message": (
                    f"Blocked by AryaOS policy gate ({CAPABILITY_SCHEMA_INVALID}: "
                    f"schema_validation_error): {tool_name!r}"
                ),
            }

    setattr(capability_validating_hook, POLICY_PLUGIN_MARKER, True)
    return capability_validating_hook


def capability_tool_definitions() -> dict[str, dict]:
    """Hermes registration schemas for the EXPOSED capabilities only.

    Shape follows the pinned registry contract (tools/registry.py:655 —
    schema dict with a JSON-Schema "parameters" object; see TODO_SCHEMA,
    tools/todo_tool.py:221).
    """
    definitions: dict[str, dict] = {}
    for name in sorted(EXPOSED_CAPABILITIES):
        spec = CAPABILITY_REGISTRY[name]
        assert spec.schema_model is not None  # EXPOSED implies schematized
        definitions[name] = {
            "name": name,
            "description": spec.description,
            "parameters": spec.schema_model.model_json_schema(),
        }
    return definitions


async def execute_capability(name: str, parameters: dict) -> dict:
    """Execute one capability binding with validated parameters
    (defense in depth: validation repeats here even though the boundary
    already validated). Binding exceptions become structured failures —
    never an authorization change, never a raised exception.
    """
    validation = validate_capability_parameters(name, parameters)
    if not validation.ok or validation.validated is None:
        return {"error": {"code": validation.reason or CAPABILITY_SCHEMA_INVALID, "detail": validation.detail}}
    spec = CAPABILITY_REGISTRY[name]
    assert spec.binding is not None  # validated implies exposed
    try:
        return await spec.binding(validation.validated)
    except BaseException as exc:  # noqa: BLE001 — structured failure, never raise
        logger.warning(
            "hermes_capability_binding_failed",
            capability=name,
            error_type=type(exc).__name__,
        )
        return {
            "error": {
                "code": _BINDING_FAILURE,
                "detail": f"{type(exc).__name__}",
            }
        }


def make_capability_tool_handler(name: str) -> Callable:
    """Hermes tool handler for one exposed capability (is_async=True):
    receives the raw args dict, re-validates, executes the binding, and
    returns the result as a JSON string (the pinned registry contract
    accepts str or the multimodal envelope only — plain dicts are
    rejected as tool_result_contract errors, tools/registry.py:863)."""

    async def handler(args: dict, **_kwargs: Any) -> str:
        result = await execute_capability(name, args if isinstance(args, dict) else {})
        import json

        return json.dumps(result, ensure_ascii=False, default=str)

    return handler
