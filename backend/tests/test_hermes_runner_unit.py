"""Unit tests for the §3.1 production Hermes job-runner (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §3 (AryaOS drives
the loop), §9 bookkeeping, §12/§13. Locks the operator decisions D1-D6:
internal-only surface, no migration, one job per WorkflowRun, the single
get_settings() source, in-process concurrency, and fixed AryaOS-owned
model routing.
"""
import importlib.util
import uuid

import pytest
from app.core.config import get_settings
from app.hermes.runtime import HermesJobResult
from app.services.hermes_job_runner import (
    HermesRunnerCall,
    run_aryaos_hermes_job,
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None


async def _seed_run(project_name: str):
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
        run = WorkflowRun(project_id=project.id)
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


async def _run_state(run_id):
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

    from app.models.core import WorkflowRun

    async with _session() as session:
        run = await session.get(WorkflowRun, run_id)
        return (
            run.status,
            run.current_stage,
            float(run.total_cost_usd or 0),
            run.failure_reason,
        )


@pytest.fixture
async def seeded_run():
    own = await _seed_run("runner-own")
    other = await _seed_run("runner-other")
    yield own, other
    await _cleanup_runs(own, other)


def _install_stub(monkeypatch, *, result=None, requests=None, calls=None):
    """Stub the runner's external boundaries: the Hermes runtime it invokes
    and the model-credential lookup its admission performs. The credential
    is the file's fixed synthetic key — the real SecretsManager reads
    backend/.env, which CI intentionally does not provision. Tests that
    verify credential behavior install their own manager AFTER this call,
    which then takes precedence."""
    import app.services.hermes_job_runner as runner

    if result is None:
        result = HermesJobResult(
            job_id="stub", status="completed", final_response="ok",
            error_code=None, error_detail=None,
        )
    seen_settings: list = []

    def _stub(request, settings=None):
        seen_settings.append(settings)
        if requests is not None:
            requests.append(request)
        if calls is not None:
            calls.append(request.authorization_context)
        return result

    monkeypatch.setattr(runner, "run_hermes_job", _stub)
    monkeypatch.setattr(
        runner, "get_secrets_manager", lambda: _FakeKeyManager("sk-runner-test")
    )
    return seen_settings


# ---------------------------------------------------------------------------
# 1. Context derivation + 7/8/12: request construction, D4/D6
# ---------------------------------------------------------------------------

def test_context_and_request_derivation(monkeypatch, seeded_run):
    (project_id, run_id), _ = seeded_run
    requests: list = []
    _install_stub(monkeypatch, requests=requests)

    outcome = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="do the thing", user_id="user-1",
    ))

    assert outcome.admitted
    assert outcome.job_id and outcome.job_id != str(run_id)
    request = requests[0]
    context = request.authorization_context
    # Derivation: fresh job token, minted agent id, lineage default = run id,
    # project resolved from the verified run, caller identity preserved.
    assert context.job_id == outcome.job_id
    assert context.agent_id == f"hermes-{outcome.job_id}"
    assert context.lineage_id == str(run_id)
    assert context.workflow_run_id == str(run_id)
    assert context.project_id == str(project_id)
    assert context.user_id == "user-1"
    # Explicit lineage overrides the default.
    requests.clear()
    run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=str(run_id), task_message="t", user_id="user-1",
        lineage_id="lineage-9",
    ))
    assert requests[0].authorization_context.lineage_id == "lineage-9"
    # D6: fixed AryaOS-owned model routing — nothing task-controllable.
    assert request.provider == "openrouter"
    assert request.base_url == "https://openrouter.ai/api/v1"
    assert request.model == get_settings().default_llm_model
    assert request.api_key  # from SecretsManager; never from the call
    assert HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ).task_message == "t"  # no routing fields exist on the input contract


def test_d6_configuration_sources(monkeypatch, seeded_run):
    """api_key comes from SecretsManager against the fixed setting name;
    the call cannot inject provider/model/base_url/api_key."""
    import app.services.hermes_job_runner as runner

    (_project_id, run_id), _ = seeded_run
    requests: list = []
    captured: dict = {}

    class _FakeManager:
        def get(self, name, required=True):
            captured["name"] = name
            return "sk-test-key"

    _install_stub(monkeypatch, requests=requests)
    # After _install_stub so this test's own capturing manager wins.
    monkeypatch.setattr(runner, "get_secrets_manager", lambda: _FakeManager())
    run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert captured["name"] == "openrouter_api_key"
    assert requests[0].api_key == "sk-test-key"
    assert requests[0].provider == "openrouter"


def test_settings_pass_through_none(monkeypatch, seeded_run):
    """D4: the runner always calls run_hermes_job(request, settings=None)."""
    (_project_id, run_id), _ = seeded_run
    seen_settings = _install_stub(monkeypatch)
    run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert seen_settings == [None]


def test_result_passthrough_unchanged(monkeypatch, seeded_run):
    (_project_id, run_id), _ = seeded_run
    exact = HermesJobResult(
        job_id="xyz", status="failed", final_response=None,
        error_code="chat_timeout", error_detail="job exceeded hermes_max_execution_seconds=0.5",
    )
    _install_stub(monkeypatch, result=exact)
    outcome = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert outcome.hermes is exact  # the very object, unchanged
    assert outcome.error_code is None and outcome.error_detail is None


# ---------------------------------------------------------------------------
# 2. Duplicate-run guard (D3) + 10. registry cleanup
# ---------------------------------------------------------------------------

def test_duplicate_run_guard_and_cleanup(monkeypatch, seeded_run):
    import app.services.hermes_job_runner as runner

    (_project_id, run_id), (_other_project, other_run) = seeded_run
    calls: list = []
    _install_stub(monkeypatch, calls=calls)

    # First invocation admitted; slot released afterwards.
    first = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert first.admitted and not runner._ACTIVE_RUNS

    # A different run can be admitted.
    second = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=other_run, task_message="t", user_id="u",
    ))
    assert second.admitted

    # While a run's slot is held, a second job for the SAME run fails
    # deterministically and never reaches the Hermes runtime.
    with runner._ACTIVE_RUNS_LOCK:
        runner._ACTIVE_RUNS.add(str(run_id))
    try:
        duplicate = run_aryaos_hermes_job(HermesRunnerCall(
            workflow_run_id=run_id, task_message="t", user_id="u",
        ))
        assert not duplicate.admitted
        assert duplicate.error_code == "runner_workflow_run_already_active"
        assert len(calls) == 2  # only the two admitted invocations
    finally:
        with runner._ACTIVE_RUNS_LOCK:
            runner._ACTIVE_RUNS.discard(str(run_id))

    # After release, the same run can run again (sequential retry is a new job).
    again = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert again.admitted and not runner._ACTIVE_RUNS


def test_registry_released_on_hermes_failure(monkeypatch, seeded_run):
    import app.services.hermes_job_runner as runner

    (_project_id, run_id), _ = seeded_run
    _install_stub(monkeypatch, result=HermesJobResult(
        job_id="f", status="failed", final_response=None,
        error_code="tool_call_limit_exceeded", error_detail="counters",
    ))
    outcome = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert outcome.admitted and outcome.hermes.error_code == "tool_call_limit_exceeded"
    assert not runner._ACTIVE_RUNS  # released in finally even on failure


# ---------------------------------------------------------------------------
# 3-5. Fail-closed admission (runtime never called)
# ---------------------------------------------------------------------------

def test_malformed_run_id_fails_closed(monkeypatch):
    requests: list = []
    _install_stub(monkeypatch, requests=requests)
    for bad in ("not-a-uuid", "", 7, None):
        outcome = run_aryaos_hermes_job(HermesRunnerCall(
            workflow_run_id=bad, task_message="t", user_id="u",
        ))
        assert not outcome.admitted, bad
        assert outcome.error_code == "runner_workflow_run_id_invalid"
    assert requests == []  # Hermes runtime never called


def test_input_validation_fails_closed(monkeypatch):
    _install_stub(monkeypatch)
    for bad in (HermesRunnerCall(workflow_run_id=uuid.uuid4(), task_message="", user_id="u"),
                HermesRunnerCall(workflow_run_id=uuid.uuid4(), task_message="t", user_id="  ")):
        outcome = run_aryaos_hermes_job(bad)
        assert not outcome.admitted
        assert outcome.error_code == "runner_input_invalid"


def test_nonexistent_and_foreign_run_fail_closed(monkeypatch, seeded_run):
    (project_id, run_id), (other_project, _other_run) = seeded_run
    requests: list = []
    _install_stub(monkeypatch, requests=requests)

    # Nonexistent run: uniform failure, no tenant oracle.
    missing = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id="00000000-0000-0000-0000-000000000000", task_message="t", user_id="u",
    ))
    assert not missing.admitted
    assert missing.error_code == "runner_workflow_run_not_found"

    # Foreign run (asserted project does not own it): SAME uniform code.
    foreign = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
        project_id=str(other_project),
    ))
    assert not foreign.admitted
    assert foreign.error_code == "runner_workflow_run_not_found"
    assert foreign.error_detail == missing.error_detail  # indistinguishable

    # Matching asserted project is admitted.
    ok = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
        project_id=str(project_id),
    ))
    assert ok.admitted
    assert len(requests) == 1  # only the admitted call reached the runtime


def test_credentials_missing_fails_closed(monkeypatch, seeded_run):
    import app.services.hermes_job_runner as runner

    (_project_id, run_id), _ = seeded_run
    requests: list = []
    _install_stub(monkeypatch, requests=requests)

    class _Missing:
        def get(self, name, required=True):
            raise RuntimeError("secret not configured")

    monkeypatch.setattr(runner, "get_secrets_manager", lambda: _Missing())
    outcome = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert not outcome.admitted
    assert outcome.error_code == "runner_model_credentials_missing"
    assert requests == []


# ---------------------------------------------------------------------------
# 6. hermes_enabled=false passthrough (REAL runtime, D4 single source)
# ---------------------------------------------------------------------------

def test_hermes_disabled_passthrough_real_runtime(monkeypatch, seeded_run):
    """Real run_hermes_job with the default (disabled) cached settings:
    the existing hermes_disabled result passes through untouched. The
    synthetic credential lets admission pass without backend/.env (absent
    in CI); the disabled runtime never uses it."""
    import app.services.hermes_job_runner as runner

    monkeypatch.setattr(
        runner, "get_secrets_manager", lambda: _FakeKeyManager("sk-runner-test")
    )
    (_project_id, run_id), _ = seeded_run
    outcome = run_aryaos_hermes_job(HermesRunnerCall(
        workflow_run_id=run_id, task_message="t", user_id="u",
    ))
    assert outcome.admitted
    assert outcome.hermes.status == "failed"
    assert outcome.hermes.error_code == "hermes_disabled"
    assert not runner._ACTIVE_RUNS


# ---------------------------------------------------------------------------
# 9. Lifecycle/audit observability (REAL job) + 11. no WorkflowRun mutation
# ---------------------------------------------------------------------------

def test_real_job_records_lifecycle_and_never_mutates_run(tmp_path, monkeypatch, seeded_run):
    """A runner-driven REAL job: JOB_START/JOB_END land in the §13 store
    with the run + job identity, and the WorkflowRun row is untouched."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.services.hermes_job_runner as runner
    from app.hermes.audit import FileAuditSink

    (_project_id, run_id), _ = seeded_run
    before = _run_state_sync(run_id)

    settings = get_settings().model_copy(update={
        "hermes_enabled": True,
        "hermes_home": str(tmp_path / "hermes-root"),
        "hermes_plugin_path": str(_plugin_path()),
        "hermes_max_iterations": 5,
        "hermes_max_execution_seconds": 10.0,
        "hermes_max_tool_calls": 10,
        "hermes_max_tool_calls_per_capability": 5,
        "hermes_max_generation_budget_usd": 1.0,
        "hermes_max_context_tokens": 8_000,
        "hermes_max_blocked_requests": 3,
        "openrouter_api_key": "sk-runner-test",
    })
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: settings)
    monkeypatch.setattr(
        runner, "get_secrets_manager",
        lambda: _FakeKeyManager("sk-runner-test"),
    )
    # Hermetic test: point the runner's D6 base_url at a dead local endpoint
    # so the real chat path fails without any outbound network traffic.
    monkeypatch.setattr(runner, "_OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")
    outcome = runner.run_aryaos_hermes_job(runner.HermesRunnerCall(
        workflow_run_id=run_id, task_message="say hi", user_id="u",
    ))
    assert outcome.admitted
    # The chat targets the real (unreachable) endpoint — the job fails with
    # the runtime's own code; lifecycle records still exist (D2).
    assert outcome.hermes.status == "failed"
    assert outcome.hermes.error_code in ("chat_failed", "chat_timeout")

    audit_file = tmp_path / "hermes-root" / "audit" / "hermes_policy_audit.jsonl"
    jobs = FileAuditSink(audit_file).read_job_records()
    assert [r.event for r in jobs] == ["JOB_START", "JOB_END"]
    for record in jobs:
        assert record.workflow_run_id == str(run_id)
        assert record.runtime_job_id == outcome.job_id
    assert jobs[1].outcome == "failed"

    # 11: the WorkflowRun row is byte-for-byte unchanged by the runner.
    assert _run_state_sync(run_id) == before


def _plugin_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "backend" / "app" / "hermes" / "plugins"


class _FakeKeyManager:
    """Yields a fixed credential so the real job can construct its request."""

    def __init__(self, key: str):
        self._key = key

    def get(self, name, required=True):
        return self._key


def _run_state_sync(run_id):
    import asyncio

    return asyncio.run(_run_state(run_id))
