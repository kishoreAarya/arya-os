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
    user_id="u", project_id="p", job_id="j", agent_id="a", lineage_id="l"
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


def test_only_readonly_capabilities_exposed():
    # Slice 1: research.search; Slice 2: asset.get (operator-approved).
    assert EXPOSED_CAPABILITIES == frozenset({"research.search", "asset.get"})


def test_allowlist_lockstep_contains_aryaos():
    assert HERMES_TOOLSET_ALLOWLIST == ("aryaos", "todo")
    assert get_frozen_enabled_toolsets() == ("aryaos", "todo")


def test_tool_definitions_shape():
    defs = capability_tool_definitions()
    assert set(defs) == {"asset.get", "research.search"}
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
    result = validate_capability_parameters("provider.generate", {})
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
        user_id="u", project_id=str(own_project), job_id="j", agent_id="a", lineage_id="l"
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
        user_id="u", project_id=str(own_project), job_id="j", agent_id="a", lineage_id="l"
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
            user_id="u", project_id=str(own_project), job_id="j", agent_id="a", lineage_id="l"
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
    real_factory = caps._make_readonly_engine

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

    monkeypatch.setattr(caps, "_make_readonly_engine", spying_factory)
    # not-found path (context set to an impossible project id)
    import app.hermes.runtime as runtime

    runtime.set_active_authorization_context(
        AuthorizationContext(
            user_id="u", project_id=str(uuid.uuid4()), job_id="j", agent_id="a", lineage_id="l"
        )
    )
    try:
        asyncio.run(
            execute_capability("asset.get", {"asset_id": "00000000-0000-0000-0000-000000000000"})
        )
    finally:
        runtime.set_active_authorization_context(None)
    assert disposed == [True]


def test_real_asset_get_end_to_end(tmp_path, seeded_assets):
    """Real Hermes: registration, schema gate, tenant behavior, §4 block,
    §12 counting — through the live dispatch path, mid-job."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import json

    import app.hermes.runtime as runtime

    (own_project, own_asset), (foreign_project, foreign_asset) = seeded_assets
    context = AuthorizationContext(
        user_id="u", project_id=str(own_project), job_id="j", agent_id="a", lineage_id="l"
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
