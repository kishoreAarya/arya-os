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
decisions A/B/C). All other capabilities are NAMES ONLY (authorized by
§4's frozen TYPED_CAPABILITIES, but no schema and no binding exist yet —
they cannot be executed and are not exposed to the model).

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
- Binding exceptions surface as structured tool-result failures
  ({"error": {...}}); they never widen authorization or counting.

policy.py is deliberately NOT modified: registry <-> TYPED_CAPABILITIES
consistency is proven by test, per the slice contract.
"""
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


async def _research_search_binding(params: ResearchSearchParams) -> dict:
    """Execute the research.search capability against the existing AryaOS
    trend_sources surface (read-only exemplar binding)."""
    service = _trend_discovery_service()
    signals = await service.discover_trends(
        topic_hint=params.topic,
        limit=params.limit,
        subreddit=params.subreddit,
        time_filter=params.time_filter,
    )
    return {
        "topic": params.topic,
        "results": [signal.to_dict() for signal in signals],
    }


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


def _make_readonly_engine():
    """Per-call disposable async engine for the read-only asset lookup.

    Why not the global engine (app.database.session): Hermes async tool
    handlers execute on a fresh event loop per call
    (model_tools._run_async:92-122 at the pin), and asyncpg pool
    connections are loop-bound — sharing the global pool across loops is
    unsafe. A per-call engine created from the existing
    settings.database_url adds no global state and is disposed on every
    path (see _asset_get_binding's finally)."""
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
    from app.hermes.runtime import get_active_authorization_context

    try:
        context = get_active_authorization_context()
    except RuntimeError:
        context = None
    if context is None:
        # No job-bound context can only mean an out-of-runtime invocation;
        # fail closed with the uniform not-found (no data leaves).
        return dict(_ASSET_NOT_FOUND)
    expected_project = context.project_id.strip()

    from app.models.core import WorkflowRun
    from app.models.media import Asset

    engine = _make_readonly_engine()
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            asset = await session.get(Asset, params.asset_id)
            if asset is None:
                return dict(_ASSET_NOT_FOUND)
            if params.workflow_run_id is not None and params.workflow_run_id != asset.workflow_run_id:
                return dict(_ASSET_NOT_FOUND)
            run = await session.get(WorkflowRun, asset.workflow_run_id)
            if run is None or str(run.project_id) != expected_project:
                return dict(_ASSET_NOT_FOUND)
            return {
                "asset_id": str(asset.id),
                "workflow_run_id": str(asset.workflow_run_id),
                "asset_type": asset.asset_type,
                "provider_name": asset.provider_name,
                "storage_path": asset.storage_path,  # reference only (decision C)
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
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
        description="Request generation through the AryaOS provider router (later slice).",
        schema_model=None,
        binding=None,
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
    "capability_schema_invalid" reason. Never raises; block messages
    carry names and reasons only — never parameter values.
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
