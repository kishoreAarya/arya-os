"""Unit tests for the §9 typed capability registry — Slice 1 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §9 (typed
capabilities, validated before execution), §4.5 (no god tool), §5.1
(allowlist lockstep: "aryaos"), §11 (malformed fails closed), §12
(counting at the boundary), §16 (real-Hermes integration without silent
skips).

Covers the 18 required areas: registry↔policy consistency; strict schema
validation; valid/missing/wrong-type/extra parameters; unknown
capability; delegate_task blocked; todo_list unchanged; exact real
surface; real registration; ALLOW→executes; BLOCK→not executed; schema
failure→BLOCK; §12 counting; no god tool; no dynamic registration;
plugin isolation.
"""
import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest

from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.capabilities import (
    CAPABILITY_REGISTRY,
    CAPABILITY_SCHEMA_INVALID,
    EXPOSED_CAPABILITIES,
    capability_tool_definitions,
    execute_capability,
    make_capability_tool_handler,
    make_capability_validating_hook,
    validate_capability_parameters,
)
from app.hermes.limits import JobLimitLedger, make_limit_enforcing_hook
from app.hermes.policy import (
    POLICY_PLUGIN_MARKER,
    TYPED_CAPABILITIES,
    AuthorizationContext,
    make_pre_tool_call_hook,
)
from app.hermes.runtime import HermesJobRequest, run_hermes_job
from app.hermes.toolsets import HERMES_TOOLSET_ALLOWLIST, get_frozen_enabled_toolsets

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = REPO_ROOT / "backend" / "app" / "hermes" / "plugins"

CONTEXT = AuthorizationContext(
    user_id="u", project_id="p", job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None


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


def _request(job_id: str = "cap-1", task_message: str | None = None) -> HermesJobRequest:
    return HermesJobRequest(
        job_id=job_id,
        task_message=task_message,
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


# ---------------------------------------------------------------------------
# 1. Registry <-> policy consistency; no god tool; exposure
# ---------------------------------------------------------------------------

def test_registry_matches_policy_typed_capabilities():
    assert frozenset(CAPABILITY_REGISTRY) == TYPED_CAPABILITIES


def test_no_god_tool_in_registry():
    for name in CAPABILITY_REGISTRY:
        assert name.count(".") == 1 and name.split(".")[0] in {
            "research", "story", "memory", "provider", "asset", "agent", "evaluation", "publishing"
        }, name


def test_exposed_capabilities_surface():
    # Slice 1: research.search (read-only); Slice 2: asset.get (read-only,
    # operator-approved); Slice 3 (§9.3): provider.generate (chargeable,
    # budget-gated); §5.4 slice: story.create + publishing.request
    # (approval-gated — gate machinery live, operations in later slices).
    assert EXPOSED_CAPABILITIES == frozenset(
        {"research.search", "asset.get", "provider.generate", "story.create", "publishing.request"}
    )


def test_allowlist_lockstep_contains_aryaos():
    assert HERMES_TOOLSET_ALLOWLIST == ("aryaos", "todo")
    assert get_frozen_enabled_toolsets() == ("aryaos", "todo")


def test_tool_definitions_shape():
    defs = capability_tool_definitions()
    assert set(defs) == {
        "asset.get", "provider.generate", "research.search", "story.create", "publishing.request",
    }
    schema = defs["research.search"]
    assert schema["name"] == "research.search"
    assert schema["description"].strip()
    params = schema["parameters"]
    assert params["type"] == "object"
    assert set(params["properties"]) == {"topic", "limit", "subreddit", "time_filter"}
    assert params.get("additionalProperties") is False  # strict, extra=forbid
    assert "topic" in params.get("required", [])


# ---------------------------------------------------------------------------
# 2. Strict schema validation (deterministic, fail-closed, value-free)
# ---------------------------------------------------------------------------

def test_valid_parameters_accepted():
    result = validate_capability_parameters("research.search", {"topic": "ai", "limit": 3})
    assert result.ok and result.validated is not None
    assert result.validated.topic == "ai" and result.validated.limit == 3


def test_defaults_applied():
    result = validate_capability_parameters("research.search", {"topic": "x"})
    assert result.ok
    assert result.validated.limit == 5 and result.validated.time_filter == "all"


def test_missing_required_parameter_blocked():
    result = validate_capability_parameters("research.search", {})
    assert not result.ok
    assert result.reason == CAPABILITY_SCHEMA_INVALID
    assert "topic" in result.detail


def test_wrong_type_blocked():
    result = validate_capability_parameters("research.search", {"topic": "x", "limit": "ten"})
    assert not result.ok and result.reason == CAPABILITY_SCHEMA_INVALID


def test_extra_parameter_blocked():
    result = validate_capability_parameters(
        "research.search", {"topic": "x", "unexpected_field": 1}
    )
    assert not result.ok and result.reason == CAPABILITY_SCHEMA_INVALID


def test_constraint_violations_blocked():
    for bad in ({"topic": ""}, {"topic": "x" * 600}, {"topic": "x", "limit": 0}, {"topic": "x", "limit": 99}, {"topic": "x", "time_filter": "fortnight"}):
        result = validate_capability_parameters("research.search", bad)
        assert not result.ok, bad


def test_unknown_capability_passes_through_to_section_4():
    """Unknown names are an authorization matter: validation adds nothing
    and §4 blocks them (verified in the chain tests)."""
    assert validate_capability_parameters("shell", {}).ok
    assert validate_capability_parameters("aryaos_api_call", {}).ok


def test_unschematized_capability_fails_closed():
    result = validate_capability_parameters("research.get", {})
    assert not result.ok
    assert result.reason == CAPABILITY_SCHEMA_INVALID
    assert result.detail == "capability_not_exposed_in_this_slice"


def test_non_dict_parameters_fail_closed():
    for bad in (None, "args", 7, [1]):
        result = validate_capability_parameters("research.search", bad)
        assert not result.ok, bad


def test_validation_details_never_contain_values():
    secret = "SECRET-TOPIC-VALUE-9f3a"
    result = validate_capability_parameters("research.search", {"topic": secret, "extra": secret})
    assert not result.ok
    assert secret not in (result.detail or "")


# ---------------------------------------------------------------------------
# 3. Hook chain: §4 -> §9 -> §12 (composition, markers, verbatim §4)
# ---------------------------------------------------------------------------

def _full_chain(ledger: JobLimitLedger):
    base = make_pre_tool_call_hook(CONTEXT)
    return make_limit_enforcing_hook(make_capability_validating_hook(base), ledger)


def test_chain_allows_valid_capability_request():
    ledger = JobLimitLedger(5, 5, 5)
    hook = _full_chain(ledger)
    assert hook("research.search", {"topic": "ai"}) is None
    assert ledger.counts()["allowed_total"] == 1


def test_chain_blocks_schema_invalid_before_execution_and_counts_blocked():
    ledger = JobLimitLedger(5, 5, 5)
    hook = _full_chain(ledger)
    verdict = hook("research.search", {})
    assert verdict["action"] == "block"
    assert CAPABILITY_SCHEMA_INVALID in verdict["message"]
    assert verdict["message"].strip()
    assert ledger.counts()["blocked_total"] == 1
    assert ledger.counts()["allowed_total"] == 0


def test_chain_preserves_section_4_blocks_verbatim():
    ledger = JobLimitLedger(5, 5, 5)
    base = make_pre_tool_call_hook(CONTEXT)
    chain = _full_chain(ledger)
    assert chain("shell", {}) == base("shell", {})
    assert chain("delegate_task", {"task": "x"})["action"] == "block"


def test_chain_todo_list_unchanged():
    ledger = JobLimitLedger(5, 5, 5)
    hook = _full_chain(ledger)
    assert hook("todo_list", {"todos": []}) is None  # native: no schema layer
    assert hook("todo_list", {"anything": 1}) is None  # §4 allows; native passthrough


def test_schema_rejection_final_outcome_audited_and_binding_not_executed(monkeypatch):
    """§13.1: §4 ALLOW + §9 schema rejection -> the §4 ALLOW audit record
    is preserved, an additive final BLOCK record carries
    capability_schema_invalid, and the binding never executes."""
    import app.hermes.capabilities as caps
    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink

    executed: list[dict] = []

    class _SpyService:
        async def discover_trends(self, *a, **k):
            executed.append({"topic": k.get("topic_hint", a[0] if a else None)})
            return []

    monkeypatch.setattr(caps, "_TREND_SERVICE", _SpyService())

    sink = InMemoryAuditSink()
    set_active_audit_sink(sink)
    try:
        ledger = JobLimitLedger(5, 5, 5)
        hook = make_limit_enforcing_hook(
            make_capability_validating_hook(make_pre_tool_call_hook(CONTEXT, audit_sink=sink)),
            ledger,
        )
        verdict = hook("research.search", {"topic": "x", "bogus": 1})
        assert verdict["action"] == "block"
        assert CAPABILITY_SCHEMA_INVALID in verdict["message"]
        records = sink.records()
        assert len(records) == 2
        assert records[0].decision == "ALLOW"  # §4 — unchanged
        assert records[0].reason_code == "allowed_typed_capability"
        assert records[0].tool_name == "research.search"
        assert records[1].decision == "BLOCK"  # §13.1 final outcome
        assert records[1].reason_code == CAPABILITY_SCHEMA_INVALID
        assert records[1].tool_name == "research.search"
        assert executed == []  # the binding did not execute
        assert ledger.counts()["allowed_total"] == 0
        assert ledger.counts()["blocked_total"] == 1
    finally:
        set_active_audit_sink(None)


def test_valid_capability_request_emits_no_final_outcome_record(monkeypatch):
    """Control: a §4-ALLOWed, schema-valid request emits only the §4 ALLOW
    record (no spurious final-outcome BLOCK)."""
    import app.hermes.capabilities as caps
    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink

    class _StubService:
        async def discover_trends(self, *a, **k):
            return []

    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())

    sink = InMemoryAuditSink()
    set_active_audit_sink(sink)
    try:
        ledger = JobLimitLedger(5, 5, 5)
        hook = make_limit_enforcing_hook(
            make_capability_validating_hook(make_pre_tool_call_hook(CONTEXT, audit_sink=sink)),
            ledger,
        )
        assert hook("research.search", {"topic": "ai"}) is None
        records = sink.records()
        assert [(r.decision, r.reason_code) for r in records] == [
            ("ALLOW", "allowed_typed_capability")
        ]
    finally:
        set_active_audit_sink(None)


def test_validation_wrapper_carries_marker_and_never_raises():
    wrapper = make_capability_validating_hook(make_pre_tool_call_hook(CONTEXT))
    assert getattr(wrapper, POLICY_PLUGIN_MARKER, False) is True
    for name, args in (("research.search", 7), (None, None), ("todo_list", None)):
        verdict = wrapper(name, args)
        assert verdict is None or verdict["action"] == "block"


def test_no_dynamic_registration_surface():
    """The registry is module-frozen state: no API accepts a name->binding
    from callers. (Structural: the only mutation path is editing the
    module; EXPOSED_CAPABILITIES derives solely from the registry.)"""
    import app.hermes.capabilities as caps

    assert not hasattr(caps, "register_capability")
    assert not hasattr(caps, "add_capability")
    with pytest.raises(TypeError):
        caps.CAPABILITY_REGISTRY["shell"] = None  # MappingProxyType: immutable


# ---------------------------------------------------------------------------
# 4. Binding execution (stubbed service; structured failures)
# ---------------------------------------------------------------------------

def test_execute_capability_valid_runs_binding(monkeypatch):
    from app.hermes.capabilities import _trend_discovery_service as _lazy  # noqa: F401
    import app.hermes.capabilities as caps

    class _Signal:
        def to_dict(self):
            return {"topic": "ai", "signal": "1.2M views"}

    class _StubService:
        async def discover_trends(self, topic_hint, feedback=None, limit=5, use_cache=True, subreddit=None, time_filter="all"):
            assert topic_hint == "ai" and limit == 3
            return [_Signal()]

    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())
    result = asyncio.run(execute_capability("research.search", {"topic": "ai", "limit": 3}))
    assert result["topic"] == "ai"
    assert result["results"][0]["signal"] == "1.2M views"


def test_execute_capability_invalid_returns_structured_error():
    result = asyncio.run(execute_capability("research.search", {"limit": 3}))
    assert result["error"]["code"] == CAPABILITY_SCHEMA_INVALID


def test_execute_capability_binding_exception_is_structured_failure(monkeypatch):
    import app.hermes.capabilities as caps

    class _Boom:
        async def discover_trends(self, *a, **k):
            raise RuntimeError("service down")

    monkeypatch.setattr(caps, "_TREND_SERVICE", _Boom())
    result = asyncio.run(execute_capability("research.search", {"topic": "x"}))
    assert result["error"]["code"] == "capability_binding_failed"
    assert result["error"]["detail"] == "RuntimeError"
    assert "service down" not in str(result)  # no exception text leak


def test_tool_handler_wraps_execution():
    import json

    handler = make_capability_tool_handler("research.search")
    result = asyncio.run(handler({"topic": "x"}, session_id="s"))
    assert isinstance(result, str)  # Hermes tool-result contract: str
    payload = json.loads(result)
    assert "error" in payload or "results" in payload  # runs the real validation path


# ---------------------------------------------------------------------------
# 4b. asset.get: schema, uniform failure, tenant isolation, no fs access
# ---------------------------------------------------------------------------

def test_asset_get_schema_strictness():
    from pydantic import ValidationError

    from app.hermes.capabilities import AssetGetParams

    ok = AssetGetParams.model_validate({"asset_id": "550e8400-e29b-41d4-a716-446655440000"})
    assert ok.workflow_run_id is None
    ok2 = AssetGetParams.model_validate(
        {"asset_id": "550e8400-e29b-41d4-a716-446655440000", "workflow_run_id": "660e8400-e29b-41d4-a716-446655440001"}
    )
    assert ok2.workflow_run_id is not None
    for bad in (
        {},  # missing asset_id
        {"asset_id": "not-a-uuid"},
        {"asset_id": 123},
        {"asset_id": "550e8400-e29b-41d4-a716-446655440000", "extra": 1},
        {"asset_id": "550e8400-e29b-41d4-a716-446655440000", "workflow_run_id": "bad"},
    ):
        with pytest.raises(ValidationError):
            AssetGetParams.model_validate(bad)


def test_asset_get_unknown_capability_still_blocked_by_section_4():
    """Sanity: §4 blocks everything outside the registry — unchanged."""
    from app.hermes.policy import evaluate_tool_request

    decision = evaluate_tool_request("asset.delete", {}, CONTEXT)
    assert not decision.allowed


def test_asset_get_binding_no_filesystem_access():
    """STRICT boundary: the binding's response fields are metadata only —
    no file content, no read/open/dereference of storage_path."""
    import inspect

    import app.hermes.capabilities as caps

    source = inspect.getsource(caps._asset_get_binding)
    for forbidden in ("open(", "Path.read", "read_bytes", "http", "requests", "urlopen"):
        assert forbidden not in source, forbidden
    # Response shape (from the success path in source) is exactly the
    # approved metadata/reference fields.
    for field in ("asset_id", "workflow_run_id", "asset_type", "provider_name", "storage_path", "created_at"):
        assert f'"{field}"' in source


async def _seed_asset(project_name: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed Project -> WorkflowRun -> Asset; return (project_id, asset_id)."""
    from app.database.session import AsyncSessionLocal
    from app.models.core import Project, WorkflowRun
    from app.models.media import Asset

    async with AsyncSessionLocal() as session:
        project = Project(name=project_name)
        session.add(project)
        await session.flush()
        run = WorkflowRun(project_id=project.id)
        session.add(run)
        await session.flush()
        asset = Asset(
            workflow_run_id=run.id,
            asset_type="voice",
            storage_path="storage://voices/test.wav",
            provider_name="elevenlabs",
        )
        session.add(asset)
        await session.commit()
        return project.id, asset.id


async def _cleanup_seeded(*pairs) -> None:

    from app.database.session import AsyncSessionLocal
    from app.models.core import Project, WorkflowRun
    from app.models.media import Asset

    async with AsyncSessionLocal() as session:
        for project_id, asset_id in pairs:
            asset = await session.get(Asset, asset_id)
            if asset is not None:
                run_id = asset.workflow_run_id
                await session.delete(asset)
                run = await session.get(WorkflowRun, run_id)
                if run is not None:
                    await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
        await session.commit()


@pytest.fixture
async def seeded_assets():
    """Two assets in two DIFFERENT projects; the foreign one proves tenant
    isolation. Yields (own, foreign, foreign_project_context)."""
    own = await _seed_asset("hermes-cap-own")
    foreign = await _seed_asset("hermes-cap-foreign")
    yield own, foreign
    await _cleanup_seeded(own, foreign)


def test_asset_get_matching_project_lookup(seeded_assets):
    import asyncio

    (own_project, own_asset), _ = seeded_assets
    import app.hermes.runtime as runtime

    context = AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
    )
    runtime.set_active_authorization_context(context)
    try:
        result = asyncio.run(execute_capability("asset.get", {"asset_id": str(own_asset)}))
    finally:
        runtime.set_active_authorization_context(None)
    assert "error" not in result, result
    assert result["asset_id"] == str(own_asset)
    assert result["asset_type"] == "voice"
    assert result["storage_path"] == "storage://voices/test.wav"


def test_asset_get_foreign_project_uniform_not_found(seeded_assets):
    import asyncio

    (own_project, _), (foreign_project, foreign_asset) = seeded_assets
    import app.hermes.runtime as runtime

    context = AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
    )
    runtime.set_active_authorization_context(context)
    try:
        foreign = asyncio.run(execute_capability("asset.get", {"asset_id": str(foreign_asset)}))
        nonexistent = asyncio.run(
            execute_capability("asset.get", {"asset_id": "00000000-0000-0000-0000-000000000000"})
        )
    finally:
        runtime.set_active_authorization_context(None)
    # Uniform failure category: foreign-project and nonexistent are
    # indistinguishable (no enumeration oracle).
    assert foreign == nonexistent
    assert foreign["error"]["code"] == "asset_not_found"


def test_asset_get_wrong_workflow_run_guard(seeded_assets):
    import asyncio

    (own_project, own_asset), _ = seeded_assets
    import app.hermes.runtime as runtime

    runtime.set_active_authorization_context(
        AuthorizationContext(
            user_id="u", project_id=str(own_project), job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
        )
    )
    try:
        result = asyncio.run(
            execute_capability(
                "asset.get",
                {"asset_id": str(own_asset), "workflow_run_id": "11111111-1111-1111-1111-111111111111"},
            )
        )
    finally:
        runtime.set_active_authorization_context(None)
    assert result["error"]["code"] == "asset_not_found"


def test_asset_get_missing_context_fails_closed():
    import asyncio

    result = asyncio.run(
        execute_capability("asset.get", {"asset_id": "550e8400-e29b-41d4-a716-446655440000"})
    )
    assert result["error"]["code"] == "asset_not_found"


def test_asset_get_engine_disposed_on_all_paths(monkeypatch):
    """Cleanup/session closure: the per-call disposable engine is disposed
    on success, not-found, and exception paths."""
    import asyncio

    import app.hermes.capabilities as caps

    disposed: list[bool] = []
    real_factory = caps._make_capability_engine

    class _EngineSpy:
        def __init__(self, engine):
            self._engine = engine

        async def dispose(self):
            disposed.append(True)
            return await self._engine.dispose()

        def __getattr__(self, item):
            return getattr(self._engine, item)

    def spying_factory():
        return _EngineSpy(real_factory())

    monkeypatch.setattr(caps, "_make_capability_engine", spying_factory)
    # not-found path (context set to an impossible project id)
    import app.hermes.runtime as runtime

    runtime.set_active_authorization_context(
        AuthorizationContext(
            user_id="u", project_id=str(uuid.uuid4()), job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
        )
    )
    try:
        asyncio.run(
            execute_capability("asset.get", {"asset_id": "00000000-0000-0000-0000-000000000000"})
        )
    finally:
        runtime.set_active_authorization_context(None)
    assert disposed == [True]


# ---------------------------------------------------------------------------
# 4c. §9.3 provider.generate (first CHARGEABLE capability, budget-gated)
# ---------------------------------------------------------------------------

async def _seed_run(project_name: str, total_cost_usd: float = 0.0):
    """Seed Project -> WorkflowRun with a chosen accumulated cost.

    Uses a fresh disposable engine per call (the capabilities.py loop-safety
    pattern): each asyncio.run() gets its own loop, and a shared pool's
    connections are loop-bound."""
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.core import Project, WorkflowRun

    async with _session() as session:
        project = Project(name=project_name)
        session.add(project)
        await session.flush()
        run = WorkflowRun(project_id=project.id, total_cost_usd=total_cost_usd)
        session.add(run)
        await session.commit()
        return project.id, run.id


async def _cleanup_runs(*pairs) -> None:
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.core import Project, WorkflowRun

    async with _session() as session:
        for project_id, run_id in pairs:
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
        await session.commit()


@pytest.fixture
async def seeded_run():
    """A WorkflowRun with accumulated spend AT the default test budget
    (1.0), plus a fresh empty one; yields (at_budget, empty)."""
    at_budget = await _seed_run("hermes-gen-at-budget", total_cost_usd=1.0)
    empty = await _seed_run("hermes-gen-empty", total_cost_usd=0.0)
    yield at_budget, empty
    await _cleanup_runs(at_budget, empty)


def _run_context(project_id, run_id) -> AuthorizationContext:
    return AuthorizationContext(
        user_id="u", project_id=str(project_id), job_id="j",
        workflow_run_id=str(run_id), agent_id="a", lineage_id="l",
    )


def _budget_settings(monkeypatch, budget: float):
    """Point the binding's get_settings() at a copy with the chosen §12
    Hermes generation budget (database_url and everything else real)."""
    from app.core.config import get_settings

    copy = get_settings().model_copy(update={"hermes_max_generation_budget_usd": budget})
    monkeypatch.setattr("app.core.config.get_settings", lambda: copy)
    return copy


class _StubExecutionResult:
    def __init__(self, *, success=True, cost_usd=0.2, error=None, output="generated text"):
        self.success = success
        self.output = output
        self.provider = "openrouter"
        self.cost_usd = cost_usd
        self.elapsed_time = 0.5
        self.attempts = 1
        self.error = error


def _install_engine_stub(monkeypatch, *, success=True, cost_usd=0.2, error=None) -> list:
    """Replace the ExecutionEngine boundary the binding invokes; the
    provider router itself stays untouched."""
    import app.services.execution_engine as engine_module

    calls: list[dict] = []

    class _StubEngine:
        def __init__(self, db):
            self._db = db
            calls.append({"db": db})

        async def execute(self, **kwargs):
            calls[-1].update(kwargs)
            return _StubExecutionResult(success=success, cost_usd=cost_usd, error=error)

    monkeypatch.setattr(engine_module, "ExecutionEngine", _StubEngine)
    return calls


def _install_dispatch_stub(monkeypatch) -> list:
    """Capture the prompt handed to the existing text dispatcher."""
    import app.providers.text_dispatch as dispatch_module

    prompts: list[str] = []

    def fake_build(prompt: str):
        prompts.append(prompt)

        async def _call(provider):
            return ("unused", 0.0)

        return _call

    monkeypatch.setattr(dispatch_module, "build_text_generation_call", fake_build)
    return prompts


def test_provider_generate_schema_strictness():
    """D1: TEXT_GENERATION only, prompt-only strict schema — no provider,
    model, credential, run-identity, or routing controls are accepted."""
    ok = validate_capability_parameters("provider.generate", {"prompt": "write a hook"})
    assert ok.ok and ok.validated.prompt == "write a hook"

    for bad in (
        {},  # missing prompt
        {"prompt": ""},  # empty
        {"prompt": "x" * 32_001},  # oversized
        {"prompt": "x", "provider": "openrouter"},  # routing control
        {"prompt": "x", "model": "gpt-9"},  # model control
        {"prompt": "x", "api_key": "sk-..."},  # credential
        {"prompt": "x", "workflow_run_id": "11111111-1111-1111-1111-111111111111"},  # run-identity override
        {"prompt": "x", "capability": "video_generation"},  # capability escape
        {"prompt": 7},  # wrong type
    ):
        result = validate_capability_parameters("provider.generate", bad)
        assert not result.ok and result.reason == CAPABILITY_SCHEMA_INVALID, bad

    # §4: the name is an authorized typed capability with a valid context.
    from app.hermes.policy import evaluate_tool_request

    decision = evaluate_tool_request("provider.generate", {"prompt": "x"}, CONTEXT)
    assert decision.allowed and decision.reason_code == "allowed_typed_capability"


def test_provider_generate_executes_via_execution_engine(monkeypatch, seeded_run):
    """Success path: validated prompt -> EXISTING dispatcher + ExecutionEngine
    boundary with the CONTEXT-derived run identity and the run's accumulated
    cost; the run total is updated caller-side (creator.py precedent)."""
    import asyncio

    from app.hermes import runtime
    from app.hermes.limits import JobLimitLedger

    (_at_budget_project, _), (empty_project, empty_run) = seeded_run
    _budget_settings(monkeypatch, budget=1.0)
    engine_calls = _install_engine_stub(monkeypatch, cost_usd=0.2)
    prompts = _install_dispatch_stub(monkeypatch)

    ledger = JobLimitLedger(5, 5, 5)
    runtime.set_active_authorization_context(_run_context(empty_project, empty_run))
    runtime.set_active_job_ledger(ledger)
    try:
        result = asyncio.run(execute_capability("provider.generate", {"prompt": "write a hook"}))
    finally:
        runtime.set_active_authorization_context(None)
        runtime.set_active_job_ledger(None)

    assert "error" not in result, result
    assert result["text"] == "generated text"
    assert result["provider"] == "openrouter"
    assert result["cost_usd"] == 0.2

    # The engine boundary received the existing dispatch machinery and the
    # context-derived identity — never model input.
    assert prompts == ["write a hook"]
    assert len(engine_calls) == 1
    call = engine_calls[0]
    from app.providers.capabilities import Capability

    assert call["capability"] is Capability.TEXT_GENERATION
    assert str(call["workflow_run_id"]) == str(empty_run)
    assert call["stage"] == "hermes_text_generation"
    assert call["running_cost_usd"] == 0.0

    # Caller-side run-total update through the existing accumulator
    # (fresh disposable engine: asyncpg pools are loop-bound).
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine
    from app.models.core import WorkflowRun

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    async def _reload():
        async with _session() as session:
            run = await session.get(WorkflowRun, empty_run)
            return float(run.total_cost_usd or 0)

    assert asyncio.run(_reload()) == pytest.approx(0.2)


def test_provider_generate_budget_boundaries(monkeypatch, seeded_run):
    """§12 USD budget, checked BEFORE execution with the router's own
    ceiling semantics: below -> allowed; at/over -> denied, engine never
    invoked, ledger violation recorded, structured error returned."""
    import asyncio

    from app.hermes import runtime
    from app.hermes.limits import REASON_GENERATION_BUDGET, JobLimitLedger

    (at_budget_project, at_budget_run), (empty_project, empty_run) = seeded_run
    _budget_settings(monkeypatch, budget=1.0)
    engine_calls = _install_engine_stub(monkeypatch)

    def _generate(project, run):
        ledger = JobLimitLedger(5, 5, 5)
        runtime.set_active_authorization_context(_run_context(project, run))
        runtime.set_active_job_ledger(ledger)
        try:
            return asyncio.run(execute_capability("provider.generate", {"prompt": "x"})), ledger
        finally:
            runtime.set_active_authorization_context(None)
            runtime.set_active_job_ledger(None)

    # 1. below budget (0.0 accumulated vs 1.0) -> allowed
    result, ledger = _generate(empty_project, empty_run)
    assert "error" not in result
    assert ledger.violation_code is None

    # 2./3. at budget and over budget -> denied before execution
    result, ledger = _generate(at_budget_project, at_budget_run)
    assert result["error"]["code"] == REASON_GENERATION_BUDGET
    assert ledger.violation_code == REASON_GENERATION_BUDGET

    over = asyncio.run(_seed_run("hermes-gen-over", total_cost_usd=1.5))
    try:
        result, ledger = _generate(over[0], over[1])
        assert result["error"]["code"] == REASON_GENERATION_BUDGET
        assert ledger.violation_code == REASON_GENERATION_BUDGET
    finally:
        asyncio.run(_cleanup_runs(over))

    # 4. the provider path was invoked exactly once (the allowed call only)
    assert len(engine_calls) == 1


def test_provider_generate_failure_mapping(monkeypatch, seeded_run):
    """§11: router failures surface as structured capability errors —
    AllProvidersFailedError -> provider_unavailable;
    CostLimitExceededError -> cost_limit_exceeded. Never a fake success."""
    import asyncio

    from app.hermes import runtime
    from app.hermes.limits import JobLimitLedger

    empty_project, empty_run = seeded_run[1]
    _budget_settings(monkeypatch, budget=1.0)

    for error_text, expected_code in (
        ("All providers for 'text_generation' failed or were skipped: ['openrouter']", "provider_unavailable"),
        ("Running cost $5.00 already at/over max_cost_per_video_usd=$5.00", "cost_limit_exceeded"),
    ):
        _install_engine_stub(monkeypatch, success=False, error=error_text)
        ledger = JobLimitLedger(5, 5, 5)
        runtime.set_active_authorization_context(_run_context(empty_project, empty_run))
        runtime.set_active_job_ledger(ledger)
        try:
            result = asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
        finally:
            runtime.set_active_authorization_context(None)
            runtime.set_active_job_ledger(None)
        assert result["error"]["code"] == expected_code, result
        assert ledger.violation_code is None  # provider failure is not a §12 violation


def test_provider_generate_context_guards(monkeypatch, seeded_run):
    """Fail-closed identity: out-of-runtime invocation, missing ledger,
    malformed context workflow_run_id, nonexistent run, and foreign-project
    run all deny with the uniform anti-enumeration code — the provider path
    is never reached, and an invalid §4 context still BLOCKs upstream."""
    import asyncio

    from app.hermes import runtime
    from app.hermes.limits import JobLimitLedger
    from app.hermes.policy import evaluate_tool_request

    (at_budget_project, _at_budget_run), (empty_project, empty_run) = seeded_run
    _budget_settings(monkeypatch, budget=1.0)
    engine_calls = _install_engine_stub(monkeypatch)

    # No context bound at all.
    runtime.set_active_job_ledger(JobLimitLedger(5, 5, 5))
    try:
        result = asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
    finally:
        runtime.set_active_job_ledger(None)
    assert result["error"]["code"] == "generation_run_unavailable"
    assert engine_calls == []

    ledger = JobLimitLedger(5, 5, 5)

    def _with_context(context):
        runtime.set_active_authorization_context(context)
        runtime.set_active_job_ledger(ledger)
        try:
            return asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
        finally:
            runtime.set_active_authorization_context(None)
            runtime.set_active_job_ledger(None)

    # No ledger bound.
    runtime.set_active_authorization_context(_run_context(empty_project, empty_run))
    try:
        result = asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
    finally:
        runtime.set_active_authorization_context(None)
    assert result["error"]["code"] == "generation_run_unavailable"

    # Malformed context workflow_run_id.
    bad_id_context = AuthorizationContext(
        user_id="u", project_id=str(empty_project), job_id="j",
        workflow_run_id="not-a-uuid", agent_id="a", lineage_id="l",
    )
    assert _with_context(bad_id_context)["error"]["code"] == "generation_run_unavailable"

    # Nonexistent run and foreign-project run: uniform failure (no oracle).
    foreign_context = _run_context(at_budget_project, empty_run)
    assert _with_context(foreign_context)["error"]["code"] == "generation_run_unavailable"
    missing_context = _run_context(empty_project, "00000000-0000-0000-0000-000000000000")
    assert _with_context(missing_context)["error"]["code"] == "generation_run_unavailable"

    assert engine_calls == []

    # §4 still blocks an invalid authorization context upstream (§11 row).
    invalid = evaluate_tool_request("provider.generate", {}, None)
    assert not invalid.allowed
    assert invalid.reason_code == "blocked_invalid_context_type"


def test_provider_generate_emits_execution_outcome_records(monkeypatch, seeded_run):
    """§13.2: every EXECUTED provider.generate call emits exactly one
    execution-outcome record — success carries engine duration + cost
    ESTIMATE + digest (never prompt values); provider failure and
    router cost-limit failure carry outcome=failure + reason. A broken
    audit sink changes none of the returned results."""
    import asyncio

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.limits import JobLimitLedger
    from app.hermes.runtime import (
        set_active_authorization_context,
        set_active_job_ledger,
    )

    empty_project, empty_run = seeded_run[1]
    _budget_settings(monkeypatch, budget=1.0)

    class _BrokenSink:
        def record(self, record):
            raise OSError("disk full")

    def _run(stub_sink, *, success=True, error=None):
        _install_engine_stub(monkeypatch, success=success, error=error, cost_usd=0.25)
        ledger = JobLimitLedger(5, 5, 5)
        set_active_authorization_context(_run_context(empty_project, empty_run))
        set_active_job_ledger(ledger)
        set_active_audit_sink(stub_sink)
        try:
            return asyncio.run(execute_capability("provider.generate", {"prompt": "p"}))
        finally:
            set_active_authorization_context(None)
            set_active_job_ledger(None)
            set_active_audit_sink(None)

    # Success: one execution record, estimate semantics, no parameter values.
    sink = InMemoryAuditSink()
    result = _run(sink)
    assert "error" not in result
    executions = sink.execution_records()
    assert len(executions) == 1
    record = executions[0]
    assert record.tool_name == "provider.generate" and record.outcome == "success"
    assert record.reason_code is None
    assert record.cost_estimate_usd == 0.25 and record.duration_seconds == 0.5
    assert record.workflow_run_id == str(empty_run)
    assert "p" != record.parameter_digest and len(record.parameter_digest) == 64
    assert "prompt" not in record.to_dict()  # values never duplicated

    # Provider failure: failure record with the deterministic reason.
    sink = InMemoryAuditSink()
    result = _run(sink, success=False, error="All providers for 'text_generation' failed: []")
    assert result["error"]["code"] == "provider_unavailable"
    executions = sink.execution_records()
    assert len(executions) == 1
    assert executions[0].outcome == "failure"
    assert executions[0].reason_code == "provider_unavailable"
    assert executions[0].cost_estimate_usd == 0.0

    # Router cost-limit failure: failure record with cost_limit_exceeded.
    sink = InMemoryAuditSink()
    result = _run(
        sink, success=False, error="Running cost $5.00 already at/over max_cost_per_video_usd=$5.00"
    )
    assert result["error"]["code"] == "cost_limit_exceeded"
    assert sink.execution_records()[0].reason_code == "cost_limit_exceeded"

    # Broken audit sink: results identical, nothing raises (best-effort).
    result = _run(_BrokenSink())
    assert "error" not in result
    result = _run(
        _BrokenSink(), success=False, error="All providers for 'text_generation' failed: []"
    )
    assert result["error"]["code"] == "provider_unavailable"


def test_provider_generate_denials_are_first_class_audit_events(monkeypatch, seeded_run):
    """§13.2: every generation_run_unavailable denial branch (no context,
    no ledger, malformed run id, missing/foreign run) emits a §13.1-class
    BLOCK final-outcome record — §4 said ALLOW, so the denial must not
    vanish from the audit trail."""
    import asyncio

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.limits import JobLimitLedger
    from app.hermes.runtime import (
        set_active_authorization_context,
        set_active_job_ledger,
    )

    (at_budget_project, _at_budget_run), (empty_project, empty_run) = seeded_run
    _budget_settings(monkeypatch, budget=1.0)
    engine_calls = _install_engine_stub(monkeypatch)

    sink = InMemoryAuditSink()

    # 1. No context bound.
    set_active_job_ledger(JobLimitLedger(5, 5, 5))
    set_active_audit_sink(sink)
    try:
        asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
    finally:
        set_active_job_ledger(None)
        set_active_audit_sink(None)

    def _with(context):
        set_active_authorization_context(context)
        set_active_job_ledger(JobLimitLedger(5, 5, 5))
        set_active_audit_sink(sink)
        try:
            return asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
        finally:
            set_active_authorization_context(None)
            set_active_job_ledger(None)
            set_active_audit_sink(None)

    # 2. No ledger.
    set_active_authorization_context(_run_context(empty_project, empty_run))
    set_active_audit_sink(sink)
    try:
        asyncio.run(execute_capability("provider.generate", {"prompt": "x"}))
    finally:
        set_active_authorization_context(None)
        set_active_audit_sink(None)

    # 3. Malformed run id; 4. foreign run; 5. nonexistent run.
    _with(AuthorizationContext(
        user_id="u", project_id=str(empty_project), job_id="j",
        workflow_run_id="not-a-uuid", agent_id="a", lineage_id="l",
    ))
    _with(_run_context(at_budget_project, empty_run))  # foreign project for this run
    _with(_run_context(empty_project, "00000000-0000-0000-0000-000000000000"))

    denials = [
        r for r in sink.records()
        if r.tool_name == "provider.generate" and r.decision == "BLOCK"
        and r.reason_code == "generation_run_unavailable"
    ]
    assert len(denials) == 5, [r.reason_code for r in sink.records()]
    assert engine_calls == []  # denials never executed the provider path
    assert sink.execution_records() == []  # nothing executed -> no execution records


def test_research_search_emits_execution_outcome(monkeypatch):
    """§13.3: research.search emits exactly one execution-outcome record —
    success (cost None) or failure (reason = the deterministic code the
    existing wrapper assigns) — with digest only, and a broken audit sink
    cannot alter the execution result."""
    import asyncio

    import app.hermes.capabilities as caps
    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink

    class _Signal:
        def to_dict(self):
            return {"topic": "ai"}

    class _StubService:
        async def discover_trends(self, *a, **k):
            return [_Signal()]

    class _Boom:
        async def discover_trends(self, *a, **k):
            raise RuntimeError("service down")

    class _BrokenSink:
        def record(self, record):
            raise OSError("disk full")

    async def _call():
        return await execute_capability("research.search", {"topic": "ai"})

    # Success: one record, cost None (D2″), digest only.
    sink = InMemoryAuditSink()
    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())
    set_active_audit_sink(sink)
    try:
        result = asyncio.run(_call())
    finally:
        set_active_audit_sink(None)
    assert "error" not in result
    records = sink.execution_records()
    assert len(records) == 1
    record = records[0]
    assert record.tool_name == "research.search" and record.outcome == "success"
    assert record.reason_code is None
    assert record.cost_estimate_usd is None  # non-chargeable: None, not 0.0
    assert isinstance(record.duration_seconds, float) and record.duration_seconds >= 0
    assert len(record.parameter_digest) == 64
    assert "topic" not in record.to_dict() and "parameters" not in record.to_dict()

    # Structured failure (binding raises -> wrapper's capability_binding_failed).
    sink = InMemoryAuditSink()
    monkeypatch.setattr(caps, "_TREND_SERVICE", _Boom())
    set_active_audit_sink(sink)
    try:
        result = asyncio.run(_call())
    finally:
        set_active_audit_sink(None)
    assert result["error"]["code"] == "capability_binding_failed"  # existing contract unchanged
    records = sink.execution_records()
    assert len(records) == 1
    assert records[0].outcome == "failure"
    assert records[0].reason_code == "capability_binding_failed"
    assert records[0].cost_estimate_usd is None

    # Broken audit sink: identical results, nothing raises (best-effort).
    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())
    set_active_audit_sink(_BrokenSink())
    try:
        result = asyncio.run(_call())
    finally:
        set_active_audit_sink(None)
    assert "error" not in result
    monkeypatch.setattr(caps, "_TREND_SERVICE", _Boom())
    set_active_audit_sink(_BrokenSink())
    try:
        result = asyncio.run(_call())
    finally:
        set_active_audit_sink(None)
    assert result["error"]["code"] == "capability_binding_failed"


def test_asset_get_emits_execution_outcome(seeded_assets):
    """§13.3: asset.get emits exactly one execution-outcome record for both
    the success and the uniform not-found paths, with cost None and the
    binding's own deterministic error code."""
    import asyncio

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.runtime import set_active_authorization_context

    (own_project, own_asset), _ = seeded_assets

    async def _call(asset_id):
        return await execute_capability("asset.get", {"asset_id": str(asset_id)})

    # Success.
    sink = InMemoryAuditSink()
    set_active_authorization_context(AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j",
        workflow_run_id="w", agent_id="a", lineage_id="l",
    ))
    set_active_audit_sink(sink)
    try:
        result = asyncio.run(_call(own_asset))
    finally:
        set_active_authorization_context(None)
        set_active_audit_sink(None)
    assert "error" not in result
    records = sink.execution_records()
    assert len(records) == 1
    record = records[0]
    assert record.tool_name == "asset.get" and record.outcome == "success"
    assert record.reason_code is None and record.cost_estimate_usd is None
    assert isinstance(record.duration_seconds, float) and record.duration_seconds >= 0
    assert len(record.parameter_digest) == 64
    assert "asset_id" not in record.to_dict() and "parameters" not in record.to_dict()

    # Uniform not-found failure: reason is the binding's own code.
    sink = InMemoryAuditSink()
    set_active_authorization_context(AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j",
        workflow_run_id="w", agent_id="a", lineage_id="l",
    ))
    set_active_audit_sink(sink)
    try:
        result = asyncio.run(_call("00000000-0000-0000-0000-000000000000"))
    finally:
        set_active_authorization_context(None)
        set_active_audit_sink(None)
    assert result["error"]["code"] == "asset_not_found"  # existing contract unchanged
    records = sink.execution_records()
    assert len(records) == 1
    assert records[0].outcome == "failure"
    assert records[0].reason_code == "asset_not_found"
    assert records[0].cost_estimate_usd is None


# ---------------------------------------------------------------------------
# 4d. §5.4/§11 approval architecture (gated capabilities)
# ---------------------------------------------------------------------------

async def _seed_checkpoint(run_id, stage, action):
    """Directly write an ApprovalCheckpoint row (the external approval act)."""
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.approval import ApprovalCheckpoint
    from app.models.enums import ApprovalAction, ApprovalStage

    async with _session() as session:
        checkpoint = ApprovalCheckpoint(
            workflow_run_id=run_id,
            stage=ApprovalStage(stage),
            reference_table="workflow_runs",
            reference_id=run_id,
            action=(ApprovalAction(action) if action else None),
        )
        session.add(checkpoint)
        await session.commit()
        return checkpoint.id


async def _count_checkpoints(run_id, stage) -> int:
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.approval import ApprovalCheckpoint
    from app.models.enums import ApprovalStage
    from sqlalchemy import func, select

    async with _session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ApprovalCheckpoint)
            .where(
                ApprovalCheckpoint.workflow_run_id == run_id,
                ApprovalCheckpoint.stage == ApprovalStage(stage),
            )
        )
        return int(result.scalar() or 0)


async def _cleanup_checkpoints(*run_ids) -> None:
    """Delete test-created ApprovalCheckpoints so run-fixture teardown
    doesn't hit the FK constraint."""
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.approval import ApprovalCheckpoint
    from sqlalchemy import delete

    async with _session() as session:
        for run_id in run_ids:
            await session.execute(
                delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id)
            )
        await session.commit()


async def _count_scripts(run_id) -> int:
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.content import Script
    from sqlalchemy import func, select

    async with _session() as session:
        result = await session.execute(
            select(func.count()).select_from(Script).where(Script.workflow_run_id == run_id)
        )
        return int(result.scalar() or 0)


async def _load_script(script_id):
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.content import Script

    async with _session() as session:
        return await session.get(Script, script_id)


async def _cleanup_scripts(*run_ids) -> None:
    from contextlib import asynccontextmanager

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.content import Script
    from sqlalchemy import delete

    async with _session() as session:
        for run_id in run_ids:
            await session.execute(delete(Script).where(Script.workflow_run_id == run_id))
        await session.commit()


async def _approve_checkpoint(checkpoint_id) -> None:
    """The external approval act: decide an EXISTING checkpoint (mirrors
    the approvals API's decide semantics: action=APPROVE + decided_at)."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    from app.hermes.capabilities import _make_capability_engine

    @asynccontextmanager
    async def _session():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    from app.models.approval import ApprovalCheckpoint
    from app.models.enums import ApprovalAction

    async with _session() as session:
        checkpoint = await session.get(ApprovalCheckpoint, checkpoint_id)
        checkpoint.action = ApprovalAction.APPROVE
        # The column is timestamp-without-timezone: store naive UTC (the
        # creator.py convention) to avoid aware/naive mixing on reload.
        checkpoint.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()


def test_approval_designation_is_frozen():
    """D1: exactly story.create and publishing.request are gated;
    provider.generate (and everything else) is not."""
    from app.hermes.capabilities import APPROVAL_GATED_CAPABILITIES

    assert APPROVAL_GATED_CAPABILITIES == frozenset({"story.create", "publishing.request"})
    assert "provider.generate" not in APPROVAL_GATED_CAPABILITIES
    assert "research.search" not in APPROVAL_GATED_CAPABILITIES
    assert "asset.get" not in APPROVAL_GATED_CAPABILITIES


def test_gated_capability_schemas_strict():
    """Gated schemas are strict; approval state can never be supplied or
    influenced through tool parameters (extra fields are forbidden)."""
    ok = validate_capability_parameters("story.create", {"content": "a draft"})
    assert ok.ok and ok.validated.content == "a draft"
    ok_pub = validate_capability_parameters(
        "publishing.request", {"artifact_id": "550e8400-e29b-41d4-a716-446655440000"}
    )
    assert ok_pub.ok
    for bad in (
        {"content": "x", "approved": True},  # approval injection
        {"content": "x", "action": "approve"},
        {"content": "x", "workflow_run_id": "11111111-1111-1111-1111-111111111111"},
        {},  # missing content
        {"content": ""},  # empty
        {"content": "x" * 32_001},
    ):
        result = validate_capability_parameters("story.create", bad)
        assert not result.ok and result.reason == CAPABILITY_SCHEMA_INVALID, bad
    for bad in ({"artifact_id": "not-a-uuid"}, {}, {"artifact_id": "x", "approved": True}):
        result = validate_capability_parameters("publishing.request", bad)
        assert not result.ok and result.reason == CAPABILITY_SCHEMA_INVALID, bad


def test_gated_capability_without_approval_pends(seeded_run):
    """No approval: the gate creates the pending checkpoint (correct run
    identity), signals the runtime, emits the §13.1 record, and the
    capability NEVER executes. Duplicate requests reuse the checkpoint."""
    import asyncio

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.runtime import (
        _clear_active_approval_pending,
        get_active_approval_pending,
        set_active_authorization_context,
    )

    (project_id, run_id), _ = seeded_run
    sink = InMemoryAuditSink()
    try:
        set_active_authorization_context(_run_context(project_id, run_id))
        set_active_audit_sink(sink)
        try:
            result = asyncio.run(execute_capability("story.create", {"content": "a draft"}))
        finally:
            set_active_authorization_context(None)
            set_active_audit_sink(None)

        pending_info = result.get("pending_approval")
        assert pending_info and pending_info["stage"] == "script"
        checkpoint_id = uuid.UUID(pending_info["checkpoint_id"])

        # D4/D5: checkpoint carries the run identity; pending action.
        from contextlib import asynccontextmanager

        from app.hermes.capabilities import _make_capability_engine
        from app.models.approval import ApprovalCheckpoint

        @asynccontextmanager
        async def _session():
            from sqlalchemy.ext.asyncio import async_sessionmaker

            engine = _make_capability_engine()
            try:
                async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                    yield session
            finally:
                await engine.dispose()

        async def _load():
            async with _session() as session:
                return await session.get(ApprovalCheckpoint, checkpoint_id)

        checkpoint = asyncio.run(_load())
        assert checkpoint is not None
        assert checkpoint.workflow_run_id == run_id
        assert checkpoint.reference_table == "workflow_runs" and checkpoint.reference_id == run_id
        assert checkpoint.action is None  # pending

        # The runtime pending signal is set with the checkpoint identity (D2).
        signal = get_active_approval_pending()
        assert signal == {"stage": "script", "checkpoint_id": pending_info["checkpoint_id"]}

        # §13.1-style final-outcome record: non-execution is first-class.
        trail = [(r.tool_name, r.decision, r.reason_code) for r in sink.records()]
        assert ("story.create", "BLOCK", "capability_pending_approval") in trail
        assert sink.execution_records() == []  # nothing executed
        assert asyncio.run(_count_scripts(run_id)) == 0  # §9.4: no Script on pending

        # Deterministic dedup: a second pending request reuses the checkpoint.
        set_active_authorization_context(_run_context(project_id, run_id))
        try:
            again = asyncio.run(execute_capability("story.create", {"content": "another"}))
        finally:
            set_active_authorization_context(None)
        assert again["pending_approval"]["checkpoint_id"] == pending_info["checkpoint_id"]
        assert asyncio.run(_count_checkpoints(run_id, "script")) == 1
    finally:
        # The runtime's finally normally clears the signal; direct-invocation
        # tests must do it themselves so later tests start clean.
        _clear_active_approval_pending()
        asyncio.run(_cleanup_checkpoints(run_id))


def test_approved_checkpoint_permits_job_n_plus_one(seeded_run):
    """§9.4 Option A, full Job N → approval → Job N+1 flow: Job N pends
    (no Script); the external approval; Job N+1 (FRESH job_id, same run)
    finds the approved checkpoint and persists the REAL Script proposal —
    with the §13.3 execution outcome representing the actual creation.
    Another run's approval never authorizes creation."""
    import asyncio

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.runtime import (
        _clear_active_approval_pending,
        get_active_approval_pending,
        set_active_authorization_context,
    )

    (project_id, run_id), (other_project, other_run) = seeded_run
    sink = InMemoryAuditSink()

    async def _run_total():
        from contextlib import asynccontextmanager

        from app.hermes.capabilities import _make_capability_engine

        @asynccontextmanager
        async def _s():
            from sqlalchemy.ext.asyncio import async_sessionmaker

            engine = _make_capability_engine()
            try:
                async with async_sessionmaker(bind=engine, expire_on_commit=False)() as s2:
                    yield s2
            finally:
                await engine.dispose()

        from app.models.core import WorkflowRun as _Run

        async with _s() as s2:
            row = await s2.get(_Run, run_id)
            return float(row.total_cost_usd or 0)

    spend_before = asyncio.run(_run_total())
    try:
        # ---- Job N: no approval → pending, NO Script, NO execution outcome.
        set_active_authorization_context(_run_context(project_id, run_id))
        set_active_audit_sink(sink)
        try:
            job_n = asyncio.run(execute_capability("story.create", {"content": "the proposal"}))
        finally:
            set_active_authorization_context(None)
        assert job_n["pending_approval"]["stage"] == "script"
        assert asyncio.run(_count_scripts(run_id)) == 0
        assert sink.execution_records() == []
        assert get_active_approval_pending() is not None
        # The runtime's finally normally clears the signal between jobs:
        _clear_active_approval_pending()

        # ---- External approval decides the EXACT pending checkpoint Job N
        # created (the existing approval act: action=APPROVE + decided_at).
        pending_id = uuid.UUID(job_n["pending_approval"]["checkpoint_id"])
        asyncio.run(_approve_checkpoint(pending_id))

        # ---- Job N+1: fresh job token, same workflow run.
        set_active_authorization_context(AuthorizationContext(
            user_id="u", project_id=str(project_id), job_id="fresh-job-n-plus-one",
            workflow_run_id=str(run_id), agent_id="hermes-fresh", lineage_id="l2",
        ))
        try:
            result = asyncio.run(execute_capability("story.create", {"content": "the proposal"}))
        finally:
            set_active_authorization_context(None)

        # The REAL operation: a Script row exists, run-scoped, content exact.
        assert "approval" not in result  # not merely "approval granted"
        assert result["workflow_run_id"] == str(run_id)
        assert result["status"] == "draft" and result["version"] == 1
        script = asyncio.run(_load_script(result["script_id"]))
        assert script is not None
        assert script.workflow_run_id == run_id
        assert script.content == "the proposal"
        assert script.word_count == len(["the", "proposal"])
        assert script.status.value == "draft"  # VersionedAssetMixin default

        # Job N+1 did NOT await approval; the checkpoint is reused, not duplicated.
        assert get_active_approval_pending() is None
        assert asyncio.run(_count_checkpoints(run_id, "script")) == 1
        assert str(script.id) == result["script_id"]

        # §13.3: the execution outcome represents the ACTUAL creation
        # (success, non-chargeable cost None).
        executions = sink.execution_records()
        assert len(executions) == 1
        record = executions[0]
        assert record.tool_name == "story.create" and record.outcome == "success"
        assert record.reason_code is None and record.cost_estimate_usd is None
        assert record.parameter_digest and "content" not in record.to_dict()

        # No LLM / no ExecutionEngine / no generation budget: the run's
        # accumulated spend is untouched by the proposal operation.
        assert asyncio.run(_run_total()) == spend_before

        # ---- Cross-run isolation: a run with NO approval of its own stays
        # pending even though another run IS approved; nothing is created.
        set_active_authorization_context(_run_context(other_project, other_run))
        try:
            isolated = asyncio.run(execute_capability("story.create", {"content": "d"}))
        finally:
            set_active_authorization_context(None)
        assert isolated["pending_approval"]["stage"] == "script"
        assert asyncio.run(_count_scripts(other_run)) == 0
        assert len(sink.execution_records()) == 1  # only the real creation
        _clear_active_approval_pending()
    finally:
        _clear_active_approval_pending()
        asyncio.run(_cleanup_scripts(run_id))
        asyncio.run(_cleanup_checkpoints(run_id, other_run))


def test_gated_publishing_request_follows_same_gate(seeded_run):
    """publishing.request uses the same architecture at the thumbnail stage."""
    import asyncio

    from app.hermes.runtime import (
        _clear_active_approval_pending,
        set_active_authorization_context,
    )

    (project_id, run_id), _ = seeded_run
    try:
        set_active_authorization_context(_run_context(project_id, run_id))
        try:
            result = asyncio.run(execute_capability(
                "publishing.request", {"artifact_id": "550e8400-e29b-41d4-a716-446655440000"}
            ))
        finally:
            set_active_authorization_context(None)
        assert result["pending_approval"]["stage"] == "thumbnail"
        assert asyncio.run(_count_checkpoints(run_id, "thumbnail")) == 1

        asyncio.run(_seed_checkpoint(run_id, "thumbnail", "approve"))
        set_active_authorization_context(_run_context(project_id, run_id))
        try:
            result = asyncio.run(execute_capability(
                "publishing.request", {"artifact_id": "550e8400-e29b-41d4-a716-446655440000"}
            ))
        finally:
            set_active_authorization_context(None)
        assert result["approval"] == "granted" and result["stage"] == "thumbnail"
    finally:
        _clear_active_approval_pending()
        asyncio.run(_cleanup_checkpoints(run_id))


def test_gated_context_guards_create_nothing(seeded_run):
    """Fail-closed identity: no-context, malformed run id, missing run, and
    foreign run all deny uniformly AND create no checkpoint."""
    import asyncio

    from app.hermes.runtime import set_active_authorization_context

    (project_id, run_id), (other_project, _other_run) = seeded_run

    async def _call():
        return await execute_capability("story.create", {"content": "x"})

    # No context bound.
    result = asyncio.run(_call())
    assert result["error"]["code"] == "approval_run_unavailable"

    set_active_authorization_context(AuthorizationContext(
        user_id="u", project_id=str(project_id), job_id="j",
        workflow_run_id="not-a-uuid", agent_id="a", lineage_id="l",
    ))
    try:
        result = asyncio.run(_call())
    finally:
        set_active_authorization_context(None)
    assert result["error"]["code"] == "approval_run_unavailable"

    for project, run in ((str(project_id), "00000000-0000-0000-0000-000000000000"),
                         (str(other_project), run_id)):  # foreign run for this project
        set_active_authorization_context(AuthorizationContext(
            user_id="u", project_id=project, job_id="j",
            workflow_run_id=str(run), agent_id="a", lineage_id="l",
        ))
        try:
            result = asyncio.run(_call())
        finally:
            set_active_authorization_context(None)
        assert result["error"]["code"] == "approval_run_unavailable"

    # Nothing was created on any denial path.
    assert asyncio.run(_count_checkpoints(run_id, "script")) == 0
    assert asyncio.run(_count_checkpoints(run_id, "thumbnail")) == 0


def test_schema_rejection_creates_no_checkpoint(seeded_run):
    """Pre-execution §9 rejection never reaches the gate: no checkpoint."""
    result = validate_capability_parameters("story.create", {"content": ""})
    assert not result.ok
    (_project_id, run_id), _ = seeded_run
    import asyncio

    assert asyncio.run(_count_checkpoints(run_id, "script")) == 0


def test_section_12_violation_precedes_awaiting_approval(tmp_path, monkeypatch, seeded_run):
    """D4 gap closure: a job that requests approval AND then exceeds a §12
    limit ends FAILED with the §12 reason — never awaiting_approval (the
    runtime checks the violation strictly before the pending signal)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")

    from app.core.config import Settings
    from app.hermes import runtime as hermes_runtime

    (project_id, run_id), _ = seeded_run

    class _ApprovalThenLimitsAgent:
        enabled_toolsets = ("todo",)
        valid_tool_names = frozenset({"todo_list"})
        api_key = "aryaos-explicit-test-key"
        base_url = "http://127.0.0.1:9/v1"

        def chat(self, _message):
            import model_tools
            from hermes_cli.plugins import iter_hook_callbacks

            # 1) Request approval (sets the pending signal, 1 allowed call).
            model_tools.handle_function_call("story.create", {"content": "draft"}, "t1")
            # 2) Then blow the total tool-call limit (max=2: the story.create
            #    call above consumed 1; two more allowed-calls exceed it).
            hook = next(iter(iter_hook_callbacks("pre_tool_call")))
            hook("todo_list", {})
            hook("todo_list", {})
            return "model wraps up"

        def close(self):
            pass

    settings = Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(PLUGIN_PATH),
        hermes_home=str(tmp_path / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=2,
        hermes_max_tool_calls_per_capability=2,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
    )
    original_construct = hermes_runtime._construct_agent
    hermes_runtime._construct_agent = lambda request, config, baseline_threads: _ApprovalThenLimitsAgent()
    try:
        result = run_hermes_job(
            HermesJobRequest(
                job_id="approval-prec-1",
                task_message="draft then burn",
                authorization_context=_run_context(project_id, run_id),
                provider="openai",
                base_url="http://127.0.0.1:9/v1",
                api_key="aryaos-explicit-test-key",
                model="aryaos-test-model",
            ),
            settings=settings,
        )
    finally:
        hermes_runtime._construct_agent = original_construct

    # §12 wins: FAILED with the limit reason, never awaiting_approval.
    assert result.status == "failed"
    assert result.error_code == "tool_call_limit_exceeded"
    import asyncio

    asyncio.run(_cleanup_checkpoints(run_id))
    asyncio.run(_cleanup_scripts(run_id))


def test_multiple_gated_calls_first_wins_deterministic(seeded_run):
    """D4 gap closure: story.create + publishing.request in BOTH orders —
    each stage keeps its own checkpoint; the job's pending signal is the
    FIRST requested stage in either order (deterministic); the second
    gated call still runs its own gate."""
    import asyncio

    from app.hermes.runtime import (
        _clear_active_approval_pending,
        get_active_approval_pending,
        set_active_authorization_context,
    )

    (project_id, run_id), _ = seeded_run

    def _drive(order):
        _clear_active_approval_pending()
        set_active_authorization_context(_run_context(project_id, run_id))
        try:
            results = []
            for name, args in order:
                results.append(asyncio.run(execute_capability(name, args)))
            return results
        finally:
            set_active_authorization_context(None)
        # signal cleared by caller

    try:
        # Order 1: story.create then publishing.request
        first, second = _drive([
            ("story.create", {"content": "draft"}),
            ("publishing.request", {"artifact_id": "550e8400-e29b-41d4-a716-446655440000"}),
        ])
        assert first["pending_approval"]["stage"] == "script"
        assert second["pending_approval"]["stage"] == "thumbnail"
        signal = get_active_approval_pending()
        assert signal == {"stage": "script", "checkpoint_id": first["pending_approval"]["checkpoint_id"]}
        assert asyncio.run(_count_checkpoints(run_id, "script")) == 1
        assert asyncio.run(_count_checkpoints(run_id, "thumbnail")) == 1
        assert asyncio.run(_count_scripts(run_id)) == 0  # nothing executed

        # Order 2: publishing.request then story.create — signal flips to
        # the FIRST stage in that order; determinism holds.
        first, second = _drive([
            ("publishing.request", {"artifact_id": "550e8400-e29b-41d4-a716-446655440000"}),
            ("story.create", {"content": "draft"}),
        ])
        assert first["pending_approval"]["stage"] == "thumbnail"
        assert second["pending_approval"]["stage"] == "script"
        signal = get_active_approval_pending()
        assert signal == {"stage": "thumbnail", "checkpoint_id": first["pending_approval"]["checkpoint_id"]}
        # Dedup held across both orders.
        assert asyncio.run(_count_checkpoints(run_id, "script")) == 1
        assert asyncio.run(_count_checkpoints(run_id, "thumbnail")) == 1
    finally:
        _clear_active_approval_pending()
        asyncio.run(_cleanup_checkpoints(run_id))


def test_real_job_awaiting_approval_end_to_end(tmp_path, monkeypatch, seeded_run):
    """§5.4/§11 end-to-end through the REAL runtime: a job whose chat invokes
    the gated capability ends in status "awaiting_approval" (never failed),
    with JOB_START/JOB_END carrying the outcome, the §13.1 record in the
    audit store, and the WorkflowRun untouched."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")

    from app.core.config import Settings
    from app.hermes import runtime as hermes_runtime
    from app.hermes.audit import FileAuditSink

    (project_id, run_id), _ = seeded_run

    class _ApprovalRequestingAgent:
        enabled_toolsets = ("todo",)
        valid_tool_names = frozenset({"todo_list"})
        api_key = "aryaos-explicit-test-key"
        base_url = "http://127.0.0.1:9/v1"

        def chat(self, _message):
            import model_tools

            model_tools.handle_function_call(
                "story.create", {"content": "a draft proposal"}, "t"
            )
            return "model wraps up"

        def close(self):
            pass

    settings = Settings(
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
    original_construct = hermes_runtime._construct_agent
    hermes_runtime._construct_agent = lambda request, config, baseline_threads: _ApprovalRequestingAgent()
    try:
        result = run_hermes_job(
            HermesJobRequest(
                job_id="approval-it-1",
                task_message="draft a story",
                authorization_context=_run_context(project_id, run_id),
                provider="openai",
                base_url="http://127.0.0.1:9/v1",
                api_key="aryaos-explicit-test-key",
                model="aryaos-test-model",
            ),
            settings=settings,
        )
    finally:
        hermes_runtime._construct_agent = original_construct

    # D2: the explicit awaiting state — NOT an ordinary failure.
    assert result.status == "awaiting_approval"
    assert result.error_code == "capability_pending_approval"
    assert "stage=script" in result.error_detail

    # §13 lifecycle: JOB_START/JOB_END with the awaiting outcome + the
    # §13.1 non-execution record — all through existing mechanisms.
    audit_file = tmp_path / "hermes-root" / "audit" / "hermes_policy_audit.jsonl"
    jobs = FileAuditSink(audit_file).read_job_records()
    assert [r.event for r in jobs] == ["JOB_START", "JOB_END"]
    assert jobs[1].outcome == "awaiting_approval"
    trail = [
        (r.tool_name, r.decision, r.reason_code)
        for r in FileAuditSink(audit_file).read_records()
    ]
    assert ("story.create", "ALLOW", "allowed_typed_capability") in trail
    assert ("story.create", "BLOCK", "capability_pending_approval") in trail

    # The checkpoint exists; the pending signal is cleared post-job.
    import asyncio

    assert asyncio.run(_count_checkpoints(run_id, "script")) == 1
    assert hermes_runtime.get_active_approval_pending() is None  # cleared in finally
    asyncio.run(_cleanup_checkpoints(run_id))



def test_provider_generate_concurrent_budget_enforcement(monkeypatch):
    """§9.3 F1 regression: two CONCURRENT provider.generate calls for the
    same workflow/job (separate threads + event loops, the shape Hermes'
    parallel tool segments produce) with a budget permitting exactly one
    call. Exactly one executes; the other is denied before execution with
    generation_budget_exceeded; the §12 violation is noted; no run-total
    update is lost; the §13.1 denial audit record is produced."""
    import asyncio
    import threading

    from app.hermes.audit import InMemoryAuditSink, set_active_audit_sink
    from app.hermes.limits import REASON_GENERATION_BUDGET, JobLimitLedger
    from app.hermes.runtime import (
        set_active_authorization_context,
        set_active_job_ledger,
    )

    async def _seed():
        return await _seed_run("hermes-gen-concurrent", total_cost_usd=0.0)

    seeded = asyncio.run(_seed())
    try:
        project_id, run_id = seeded
        # Budget 0.2, per-call (stubbed) cost 0.2: the first call passes the
        # pre-execution check (0.0 < 0.2); after its update the total is 0.2,
        # which must deny the second call.
        _budget_settings(monkeypatch, budget=0.2)
        engine_calls = _install_engine_stub(monkeypatch, cost_usd=0.2)

        ledger = JobLimitLedger(5, 5, 5)
        sink = InMemoryAuditSink()
        set_active_authorization_context(_run_context(project_id, run_id))
        set_active_job_ledger(ledger)
        set_active_audit_sink(sink)
        barrier = threading.Barrier(2)
        outcomes: list[dict] = []

        def _worker():
            outcomes.append(asyncio.run(_barrier_then_generate()))

        async def _barrier_then_generate():
            # Wait inside the coroutine so both threads have entered their
            # event loops and are provably concurrent at the boundary.
            await asyncio.get_running_loop().run_in_executor(None, barrier.wait)
            return await execute_capability("provider.generate", {"prompt": "concurrent"})

        try:
            threads = [threading.Thread(target=_worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            assert not any(t.is_alive() for t in threads), "concurrent calls must not deadlock"
        finally:
            set_active_authorization_context(None)
            set_active_job_ledger(None)
            set_active_audit_sink(None)

        # Exactly one call executed the provider path...
        assert len(engine_calls) == 1, engine_calls
        # ...and both workers returned: one success, one pre-execution denial.
        allowed = [r for r in outcomes if "error" not in r]
        denied = [r for r in outcomes if "error" in r]
        assert len(allowed) == 1 and len(denied) == 1, outcomes
        assert denied[0]["error"]["code"] == REASON_GENERATION_BUDGET

        # §12: the violation is recorded (job-failure mechanism input).
        assert ledger.violation_code == REASON_GENERATION_BUDGET

        # No lost update: the authoritative total reflects exactly one call.
        from app.models.core import WorkflowRun

        async def _reload_total():
            from contextlib import asynccontextmanager

            from app.hermes.capabilities import _make_capability_engine

            @asynccontextmanager
            async def _session():
                from sqlalchemy.ext.asyncio import async_sessionmaker

                engine = _make_capability_engine()
                try:
                    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as s:
                        yield s
                finally:
                    await engine.dispose()

            async with _session() as s:
                run = await s.get(WorkflowRun, run_id)
                return float(run.total_cost_usd or 0)

        assert asyncio.run(_reload_total()) == pytest.approx(0.2)

        # §13.1: the denial is a first-class final-outcome audit record.
        trail = [(r.tool_name, r.decision, r.reason_code) for r in sink.records()]
        assert ("provider.generate", "BLOCK", REASON_GENERATION_BUDGET) in trail

        # §13.2: exactly ONE execution-outcome record (the single successful
        # call — the denied call never executed, so it has none) and its
        # cost estimate equals the recorded run-total delta.
        executions = sink.execution_records()
        assert len(executions) == 1, executions
        assert executions[0].outcome == "success"
        assert executions[0].cost_estimate_usd == pytest.approx(0.2)
        assert executions[0].reason_code is None
    finally:
        asyncio.run(_cleanup_runs(seeded))


def test_real_asset_get_end_to_end(tmp_path, seeded_assets):
    """Real Hermes: registration, schema gate, tenant behavior, §4 block,
    §12 counting — through the live dispatch path, mid-job."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import json

    import app.hermes.runtime as runtime

    (own_project, own_asset), (foreign_project, foreign_asset) = seeded_assets
    context = AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
    )
    request = HermesJobRequest(
        job_id="cap-it-3",
        task_message=None,
        authorization_context=context,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )
    captured: dict = {}
    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        import model_tools
        from hermes_cli.plugins import iter_hook_callbacks

        captured["hook"] = list(iter_hook_callbacks("pre_tool_call"))[0]
        ok = model_tools.handle_function_call("asset.get", {"asset_id": str(own_asset)}, "t")
        captured["ok"] = json.loads(ok)
        foreign = model_tools.handle_function_call("asset.get", {"asset_id": str(foreign_asset)}, "t")
        captured["foreign"] = json.loads(foreign)
        nonexistent = model_tools.handle_function_call(
            "asset.get", {"asset_id": "00000000-0000-0000-0000-000000000000"}, "t"
        )
        captured["nonexistent"] = json.loads(nonexistent)
        bad_schema = model_tools.handle_function_call("asset.get", {"asset_id": "not-a-uuid"}, "t")
        captured["bad_schema"] = json.loads(bad_schema)
        blocked = model_tools.handle_function_call("shell", {}, "t")
        captured["blocked"] = json.loads(blocked)
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        result = run_hermes_job(request, settings=_valid_settings(tmp_path))
    finally:
        runtime._assert_plugin_surface = original_assert
    assert result.status == "completed", (result.error_code, result.error_detail)

    assert "error" not in captured["ok"], captured["ok"]
    assert captured["ok"]["asset_id"] == str(own_asset)
    assert captured["foreign"] == captured["nonexistent"]
    assert captured["foreign"]["error"]["code"] == "asset_not_found"
    assert captured["bad_schema"]["error"]  # schema-invalid -> blocked result
    assert captured["blocked"]["error"]

    # §12 per-capability counting: 2 allowed asset.get calls consumed the
    # job's per-capability budget of 5; verify via the live hook.
    verdict = None
    for _ in range(4):
        verdict = captured["hook"]("asset.get", {"asset_id": str(own_asset)})
    assert verdict is not None and verdict["action"] == "block"
    assert "tool_call_per_capability_limit_exceeded" in verdict["message"]


# ---------------------------------------------------------------------------
# 5. REAL Hermes integration (§16 — no silent skips)
# ---------------------------------------------------------------------------

def test_real_surface_registration_and_execution(tmp_path, monkeypatch):
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.capabilities as caps
    import app.hermes.runtime as runtime

    executed: list[dict] = []

    class _Signal:
        def to_dict(self):
            return {"topic": "ai", "signal": "ok"}

    class _StubService:
        async def discover_trends(self, topic_hint, feedback=None, limit=5, use_cache=True, subreddit=None, time_filter="all"):
            executed.append({"topic": topic_hint})
            return [_Signal()]

    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())
    captured: dict = {}
    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        # Runs MID-JOB, after discovery and before construction: the job's
        # plugin scope, environment, and registry entries are live here.
        # (Dispatching after the job would fall back to the default scope
        # and a stale registry — tool entries are scoped per home.)
        import json

        import model_tools
        from hermes_cli.plugins import get_plugin_manager, iter_hook_callbacks

        captured["plugins"] = {p["key"]: p for p in get_plugin_manager().list_plugins()}
        captured["callbacks"] = list(iter_hook_callbacks("pre_tool_call"))

        # ALLOW -> the real registry handler executes the binding.
        allowed = model_tools.handle_function_call("research.search", {"topic": "ai"}, "t")
        payload = json.loads(allowed)
        assert "error" not in payload, payload
        assert payload["results"][0]["signal"] == "ok"
        captured["executed"] = list(executed)

        # §4 BLOCK -> binding does NOT execute.
        before = len(executed)
        blocked = model_tools.handle_function_call("shell", {}, "t")
        assert "error" in json.loads(blocked)
        assert len(executed) == before

        # Schema failure at the boundary -> BLOCK, no execution.
        invalid = model_tools.handle_function_call(
            "research.search", {"topic": "x", "bogus": 1}, "t"
        )
        assert "error" in json.loads(invalid)
        assert len(executed) == before
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        result = run_hermes_job(
            _request(job_id="cap-it-1", task_message=None), settings=_valid_settings(tmp_path)
        )
    finally:
        runtime._assert_plugin_surface = original_assert
    assert result.status == "completed", (result.error_code, result.error_detail)
    assert captured["executed"] == [{"topic": "ai"}]

    # Plugin isolation remains exactly {aryaos-policy}.
    assert set(captured["plugins"]) == {"aryaos-policy"}


def test_real_capability_counts_against_section_12(tmp_path, monkeypatch):
    """§12 counters observe capability requests at the policy boundary."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.capabilities as caps
    import app.hermes.runtime as runtime

    class _StubService:
        async def discover_trends(self, *a, **k):
            return []

    monkeypatch.setattr(caps, "_TREND_SERVICE", _StubService())
    captured: dict = {}
    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import iter_hook_callbacks

        captured["hook"] = list(iter_hook_callbacks("pre_tool_call"))[0]
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        settings = _valid_settings(tmp_path)
        settings = settings.model_copy(
            update={"hermes_max_tool_calls": 2, "hermes_max_tool_calls_per_capability": 1}
        )
        result = run_hermes_job(_request(job_id="cap-it-2", task_message=None), settings=settings)
    finally:
        runtime._assert_plugin_surface = original_assert
    assert result.status == "completed", (result.error_code, result.error_detail)
    hook = captured["hook"]
    assert hook("research.search", {"topic": "a"}) is None  # 1st: per-capability budget 1
    verdict = hook("research.search", {"topic": "b"})  # 2nd: per-capability exceeded
    assert verdict["action"] == "block"
    assert "tool_call_per_capability_limit_exceeded" in verdict["message"]


def test_real_provider_generate_budget_denial_fails_job(tmp_path, monkeypatch):
    """§9.3/§11/§12 end-to-end: through the REAL pinned Hermes dispatch
    path, a chargeable provider.generate call whose run is already at the
    §12 USD budget is denied BEFORE execution (engine never invoked),
    emits a §13.1 final-outcome record, and the JOB FAILS via the
    existing §12 violation mechanism — no silent continuation."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import asyncio
    import json as _json

    from app.hermes import runtime
    from app.hermes.audit import FileAuditSink

    seeded = asyncio.run(_seed_run("hermes-gen-it", total_cost_usd=1.0))
    try:
        context = _run_context(*seeded)
        settings = _valid_settings(tmp_path)  # hermes_max_generation_budget_usd=1.0
        # The binding resolves the budget from get_settings(); point it at
        # the same settings object the job validates (production coherence).
        monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
        engine_calls = _install_engine_stub(monkeypatch)

        request = HermesJobRequest(
            job_id="cap-gen-1",
            task_message=None,
            authorization_context=context,
            provider="openai",
            base_url="http://127.0.0.1:9/v1",
            api_key="aryaos-explicit-test-key",
            model="aryaos-test-model",
        )
        captured: dict = {}
        original_assert = runtime._assert_plugin_surface

        def capturing_assert():
            import model_tools

            captured["result"] = _json.loads(
                model_tools.handle_function_call("provider.generate", {"prompt": "hi"}, "t")
            )
            original_assert()

        runtime._assert_plugin_surface = capturing_assert
        try:
            result = run_hermes_job(request, settings=settings)
        finally:
            runtime._assert_plugin_surface = original_assert

        # Denied before execution with the deterministic §12 code.
        assert captured["result"]["error"]["code"] == "generation_budget_exceeded"
        assert engine_calls == []  # ExecutionEngine/provider router never invoked

        # §11/§12: the job fails through the existing violation mechanism.
        assert result.status == "failed"
        assert result.error_code == "generation_budget_exceeded"

        # §13.1: the denial is a first-class final-outcome audit record.
        audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
        trail = [
            (r.tool_name, r.decision, r.reason_code) for r in FileAuditSink(audit_file).read_records()
        ]
        assert ("provider.generate", "ALLOW", "allowed_typed_capability") in trail
        assert ("provider.generate", "BLOCK", "generation_budget_exceeded") in trail
    finally:
        asyncio.run(_cleanup_runs(seeded))
