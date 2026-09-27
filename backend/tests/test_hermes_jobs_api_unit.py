"""Unit tests for the §9.6 Hermes invocation surface (V2).

Spec: operator decisions D1-D10 — additive API-key-protected route over
the canonical runner; 202 + threadpool background execution + polling;
§13 audit fallback; single-process F1 contract; no new authority.
"""
import asyncio
import threading
import uuid

import pytest
from app.core.config import get_settings
from app.main import app

RUN_ID = "550e8400-e29b-41d4-a716-446655440000"


def _submit_payload(**overrides):
    base = {"workflow_run_id": RUN_ID, "task_message": "do the thing", "user_id": "user-1"}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


@pytest.fixture
async def anon_client():
    from httpx import ASGITransport

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        import httpx

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


# ---------------------------------------------------------------------------
# 1. Authentication
# ---------------------------------------------------------------------------

async def test_submit_requires_api_key(anon_client):
    resp = await anon_client.post("/api/hermes/jobs", json=_submit_payload())
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_poll_requires_api_key(anon_client):
    resp = await anon_client.get(f"/api/hermes/jobs/{uuid.uuid4()}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Schema validation (extra="forbid" mirrors HermesRunnerCall)
# ---------------------------------------------------------------------------

async def test_schema_rejects_missing_and_empty_fields(client):
    for bad in (
        {"task_message": "t", "user_id": "u"},  # missing workflow_run_id
        {"workflow_run_id": RUN_ID, "user_id": "u"},  # missing task_message
        {"workflow_run_id": RUN_ID, "task_message": "", "user_id": "u"},  # empty task
        {"workflow_run_id": RUN_ID, "task_message": "t"},  # missing user_id
        {"workflow_run_id": RUN_ID, "task_message": "t", "user_id": "  "},  # blank user
    ):
        resp = await client.post("/api/hermes/jobs", json=bad)
        assert resp.status_code == 422, bad


async def test_schema_rejects_forbidden_authority_fields(client):
    """11: no provider/model/credential/platform/destination/approval/
    capability field can cross the boundary."""
    for injected in (
        "provider", "model", "api_key", "credentials", "platform",
        "integration_id", "dry_run", "approved", "checkpoint_id", "stage",
        "destination", "publish_type", "agent_id", "job_id",
    ):
        resp = await client.post(
            "/api/hermes/jobs", json=_submit_payload(**{injected: "x"})
        )
        assert resp.status_code == 422, injected


# ---------------------------------------------------------------------------
# 3. Submission (202 shape) + 5/6: runner result/admission passthrough
# ---------------------------------------------------------------------------

def _install_runner(monkeypatch, result):
    """Stub the runner boundary; capture calls and worker-thread identity."""
    import app.api.routers.hermes_jobs as surface

    calls: list = []

    def _stub(call):
        calls.append({"call": call, "thread": threading.current_thread().name})
        return result

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _stub)
    return calls


def _runner_result(status="completed", error_code=None, error_detail=None, final="ok", _runtime="runtime-id"):
    from app.hermes.runtime import HermesJobResult
    from app.services.hermes_job_runner import HermesRunnerResult

    return HermesRunnerResult(
        hermes=HermesJobResult(
            job_id=_runtime, status=status, final_response=final,
            error_code=error_code, error_detail=error_detail,
        ),
        job_id=_runtime, error_code=None, error_detail=None,
    )


def _admission_failure(code="runner_workflow_run_already_active", detail="busy"):
    from app.services.hermes_job_runner import HermesRunnerResult

    return HermesRunnerResult(hermes=None, job_id=None, error_code=code, error_detail=detail)


async def _submit_and_await(client, monkeypatch, result, timeout=5.0):
    """POST, wait for the background task to finish, return (submit, final)."""
    _install_runner(monkeypatch, result)
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert submit.status_code == 202, submit.text
    job_id = submit.json()["job_id"]
    deadline = asyncio.get_event_loop().time() + timeout
    final = None
    while asyncio.get_event_loop().time() < deadline:
        poll = await client.get(f"/api/hermes/jobs/{job_id}")
        assert poll.status_code == 200, poll.text
        if poll.json()["status"] not in ("submitted", "running"):
            final = poll.json()
            break
        await asyncio.sleep(0.01)
    return submit.json(), final, job_id


async def test_submission_shape_and_result_passthrough(client, monkeypatch):
    submit, final, job_id = await _submit_and_await(client, monkeypatch, _runner_result())
    assert submit["status"] == "submitted" and submit["submitted_at"]
    assert submit["workflow_run_id"] == RUN_ID
    assert "task_message" not in submit and "user_id" not in submit
    assert final is not None and final["status"] == "completed"
    assert final["final_response"] == "ok"
    assert final["completed_at"] and final["job_id"] == job_id


async def test_awaiting_approval_passthrough(client, monkeypatch):
    _, final, _ = await _submit_and_await(
        client, monkeypatch,
        _runner_result(status="awaiting_approval", error_code="capability_pending_approval",
                       error_detail="stage=script checkpoint=x", final=None),
    )
    assert final["status"] == "awaiting_approval"
    assert final["error_code"] == "capability_pending_approval"
    assert "stage=script" in final["error_detail"]
    assert final["final_response"] is None  # populated only for completed


async def test_failed_passthrough_preserves_runner_errors(client, monkeypatch):
    _, final, _ = await _submit_and_await(
        client, monkeypatch,
        _runner_result(status="failed", error_code="chat_timeout",
                       error_detail="job exceeded hermes_max_execution_seconds=0.5", final=None),
    )
    assert final["status"] == "failed"
    assert final["error_code"] == "chat_timeout"
    assert "hermes_max_execution_seconds" in final["error_detail"]


async def test_runner_admission_failure_surfaced_verbatim(client, monkeypatch):
    _, final, _ = await _submit_and_await(client, monkeypatch, _admission_failure())
    assert final["status"] == "failed"
    assert final["error_code"] == "runner_workflow_run_already_active"
    assert final["error_detail"] == "busy"


# ---------------------------------------------------------------------------
# 4. Threadpool proof (runner never on the event-loop thread)
# ---------------------------------------------------------------------------

async def test_runner_executes_off_event_loop_thread(client, monkeypatch):
    loop_thread = threading.current_thread().name
    calls = _install_runner(monkeypatch, _runner_result())
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    job_id = submit.json()["job_id"]
    deadline = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < deadline:
        poll = await client.get(f"/api/hermes/jobs/{job_id}")
        if poll.json()["status"] not in ("submitted", "running"):
            break
        await asyncio.sleep(0.01)
    assert len(calls) == 1
    assert calls[0]["thread"] != loop_thread  # NOT the event-loop thread
    assert calls[0]["call"].task_message == "do the thing"
    assert calls[0]["call"].user_id == "user-1"
    assert str(calls[0]["call"].workflow_run_id) == RUN_ID


# ---------------------------------------------------------------------------
# 7. Live polling lifecycle submitted → running → terminal
# ---------------------------------------------------------------------------

async def test_live_lifecycle_transitions(client, monkeypatch):
    import app.api.routers.hermes_jobs as surface

    gate = threading.Event()
    release = threading.Event()
    statuses: list = []

    def _slow_stub(call):
        statuses.append("runner-started")
        gate.set()
        release.wait(timeout=5.0)
        return _runner_result()

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _slow_stub)
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    job_id = submit.json()["job_id"]
    assert (await client.get(f"/api/hermes/jobs/{job_id}")).json()["status"] in ("submitted", "running")
    assert gate.wait(timeout=5.0)  # runner is executing in the threadpool
    running = (await client.get(f"/api/hermes/jobs/{job_id}")).json()
    assert running["status"] == "running"
    release.set()
    deadline = asyncio.get_event_loop().time() + 5.0
    final = None
    while asyncio.get_event_loop().time() < deadline:
        final = (await client.get(f"/api/hermes/jobs/{job_id}")).json()
        if final["status"] not in ("submitted", "running"):
            break
        await asyncio.sleep(0.01)
    assert final["status"] == "completed"


# ---------------------------------------------------------------------------
# 8. §13 fallback (entry removed → audit reconstruction)
# ---------------------------------------------------------------------------

def _seed_audit_file(tmp_path, job_id, outcome, error_code=None, with_end=True):
    from app.hermes.audit import (
        JOB_END,
        JOB_START,
        FileAuditSink,
        HermesJobAuditRecord,
    )

    sink = FileAuditSink(tmp_path / "audit" / "hermes_policy_audit.jsonl")
    start = HermesJobAuditRecord(
        event=JOB_START, user_id="u", project_id="p", job_id="j",
        agent_id="a", lineage_id="l", runtime_job_id=job_id,
        workflow_run_id=RUN_ID,
    )
    sink.record(start)
    if with_end:
        sink.record(HermesJobAuditRecord(
            event=JOB_END, user_id="u", project_id="p", job_id="j",
            agent_id="a", lineage_id="l", runtime_job_id=job_id,
            workflow_run_id=RUN_ID, outcome=outcome, error_code=error_code,
            duration_seconds=1.5,
        ))
    return sink


async def test_audit_fallback_reconstructs_terminal_states(client, monkeypatch, tmp_path):
    import app.api.routers.hermes_jobs as surface

    monkeypatch.setattr(surface, "_HERMES_JOBS", {})
    settings = get_settings()
    real_home = settings.hermes_home
    settings.hermes_home = str(tmp_path)
    try:
        # completed
        _seed_audit_file(tmp_path, "runtime-a", "completed")
        resp = await client.get("/api/hermes/jobs/runtime-a")
        assert resp.status_code == 200 and resp.json()["status"] == "completed"
        assert resp.json()["duration_seconds"] == 1.5
        # awaiting_approval
        _seed_audit_file(tmp_path, "runtime-b", "awaiting_approval", "capability_pending_approval")
        resp = await client.get("/api/hermes/jobs/runtime-b")
        assert resp.json()["status"] == "awaiting_approval"
        assert resp.json()["error_code"] == "capability_pending_approval"
        # failed with §12 code
        _seed_audit_file(tmp_path, "runtime-c", "failed", "tool_call_limit_exceeded")
        resp = await client.get("/api/hermes/jobs/runtime-c")
        assert resp.json()["status"] == "failed"
        assert resp.json()["error_code"] == "tool_call_limit_exceeded"
    finally:
        settings.hermes_home = real_home


async def test_audit_fallback_interrupted_job_deterministic(client, monkeypatch, tmp_path):
    """JOB_START without JOB_END -> deterministic interrupted-failure, never
    a fake completed state."""
    import app.api.routers.hermes_jobs as surface

    monkeypatch.setattr(surface, "_HERMES_JOBS", {})
    settings = get_settings()
    real_home = settings.hermes_home
    settings.hermes_home = str(tmp_path)
    try:
        _seed_audit_file(tmp_path, "runtime-x", "completed", with_end=False)
        resp = await client.get("/api/hermes/jobs/runtime-x")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "surface_job_interrupted"
        assert "JOB_START" in body["error_detail"]
        assert body["final_response"] is None
    finally:
        settings.hermes_home = real_home


# ---------------------------------------------------------------------------
# 9. Unknown job -> 404
# ---------------------------------------------------------------------------

async def test_unknown_job_404(client, monkeypatch, tmp_path):
    import app.api.routers.hermes_jobs as surface

    monkeypatch.setattr(surface, "_HERMES_JOBS", {})
    settings = get_settings()
    real_home = settings.hermes_home
    settings.hermes_home = str(tmp_path)  # empty audit store
    try:
        resp = await client.get(f"/api/hermes/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404
    finally:
        settings.hermes_home = real_home


# ---------------------------------------------------------------------------
# 9.7b. R-s1 remediation: runtime job id propagation + restart recovery
# ---------------------------------------------------------------------------

async def _submit_with_runtime_id(client, monkeypatch, status="completed", error_code=None):
    """Submit a stubbed job; wait for terminal; return (surface_id,
    runtime_id, final_body). The stub returns a runner result whose
    job_id is a DISTINCT runtime id (mirroring the frozen runner)."""
    runtime_id = f"runtime-{uuid.uuid4().hex[:8]}"
    _install_runner(monkeypatch, _runner_result(status=status, error_code=error_code, _runtime=runtime_id))
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert submit.status_code == 202
    surface_id = submit.json()["job_id"]
    assert surface_id != runtime_id  # the two ids are distinct by design
    deadline = asyncio.get_event_loop().time() + 5.0
    body = None
    while asyncio.get_event_loop().time() < deadline:
        body = (await client.get(f"/api/hermes/jobs/{surface_id}")).json()
        if body["status"] not in ("submitted", "running"):
            return surface_id, runtime_id, body
        await asyncio.sleep(0.01)
    raise AssertionError(f"job never reached terminal state: {body}")


async def test_runtime_id_propagation_and_backward_compat(client, monkeypatch):
    """1/2/3: completed poll exposes runtime_job_id; surface id unchanged;
    submit response contract untouched (no new required fields)."""
    surface_id, runtime_id, body = await _submit_with_runtime_id(client, monkeypatch)
    assert body["job_id"] == surface_id            # public id preserved
    assert body["runtime_job_id"] == runtime_id    # runner id exposed
    assert body["status"] == "completed"
    # Submit response remains the original 4-field contract.
    _install_runner(monkeypatch, _runner_result())
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert set(submit.json()) == {"job_id", "workflow_run_id", "status", "submitted_at"}


async def test_runtime_id_propagates_for_failed_and_awaiting(client, monkeypatch):
    """4/5: failed and awaiting_approval results expose the runtime id
    whenever the runner produced one; existing semantics preserved."""
    _, _, failed = await _submit_with_runtime_id(
        client, monkeypatch, status="failed", error_code="chat_timeout"
    )
    assert failed["runtime_job_id"] and failed["error_code"] == "chat_timeout"
    _, _, awaiting = await _submit_with_runtime_id(
        client, monkeypatch, status="awaiting_approval", error_code="capability_pending_approval"
    )
    assert awaiting["runtime_job_id"]
    assert awaiting["status"] == "awaiting_approval"
    assert awaiting["error_code"] == "capability_pending_approval"


async def test_runtime_id_live_polling_by_runtime_id(client, monkeypatch):
    """Additive lookup: while the process is alive, polling BY the runtime
    id returns the same job (surface job_id preserved in the response)."""
    surface_id, runtime_id, body = await _submit_with_runtime_id(client, monkeypatch)
    by_runtime = (await client.get(f"/api/hermes/jobs/{runtime_id}")).json()
    assert by_runtime["job_id"] == surface_id
    assert by_runtime["runtime_job_id"] == runtime_id
    assert by_runtime["status"] == body["status"]


async def test_restart_recovery_via_runtime_id_and_fallback(client, monkeypatch, tmp_path):
    """6/7: after the live entry is lost (restart simulation), the §13
    fallback reconstructs the terminal record BY the runtime id; the
    surface id honestly 404s exactly as designed before this slice."""
    surface_id, runtime_id, _ = await _submit_with_runtime_id(client, monkeypatch)

    # Seed the durable §13 record keyed by the runtime id (the real
    # runtime writes these; the hermetic §9.6 pattern).
    import app.api.routers.hermes_jobs as surface

    settings = get_settings()
    real_home = settings.hermes_home
    settings.hermes_home = str(tmp_path)
    try:
        _seed_audit_file(tmp_path, runtime_id, "completed")
        # Restart: the in-memory registry (including the runtime-id link)
        # disappears.
        monkeypatch.setattr(surface, "_HERMES_JOBS", {})
        # Runtime-id polling recovers the terminal state from §13.
        recovered = await client.get(f"/api/hermes/jobs/{runtime_id}")
        assert recovered.status_code == 200
        body = recovered.json()
        assert body["status"] == "completed"
        assert body["runtime_job_id"] == runtime_id
        # The surface id remains honestly 404 post-restart (unchanged
        # R-s1 behavior for the surface id itself).
        gone = await client.get(f"/api/hermes/jobs/{surface_id}")
        assert gone.status_code == 404
    finally:
        settings.hermes_home = real_home


async def test_runtime_id_polling_still_requires_api_key(anon_client):
    """8: runtime-id polling sits behind the same API-key dependency."""
    resp = await anon_client.get("/api/hermes/jobs/runtime-xyz")
    assert resp.status_code == 401


async def test_real_runtime_smoke_exposes_real_runtime_job_id(client, monkeypatch, tmp_path):
    """Real-runner proof (hermetic, dead endpoint): the frozen runner's
    ACTUAL HermesRunnerResult.job_id propagates into the poll response —
    surface id != runtime id, both live-reachable."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    from app.core.config import HERMES_COMMIT_PIN, Settings

    settings = Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "backend" / "app" / "hermes" / "plugins"
        ),
        hermes_home=str(tmp_path / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
        openrouter_api_key="sk-rs1-smoke",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: settings)
    import app.services.hermes_job_runner as runner_module

    monkeypatch.setattr(runner_module, "_OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")

    from app.database.session import AsyncSessionLocal
    from app.models.core import Project, WorkflowRun

    async def _seed():
        async with AsyncSessionLocal() as session:
            project = Project(name="rs1-smoke")
            session.add(project)
            await session.flush()
            run = WorkflowRun(project_id=project.id)
            session.add(run)
            await session.commit()
            return project.id, run.id

    async def _cleanup(project_id, run_id):
        async with AsyncSessionLocal() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
            await session.commit()

    project_id, run_id = await _seed()
    try:
        submit = await client.post("/api/hermes/jobs", json=_submit_payload(
            workflow_run_id=str(run_id), task_message="say hi", user_id="rs1-test",
        ))
        assert submit.status_code == 202
        surface_id = submit.json()["job_id"]
        deadline = asyncio.get_event_loop().time() + 60.0
        final = None
        while asyncio.get_event_loop().time() < deadline:
            poll = await client.get(f"/api/hermes/jobs/{surface_id}")
            if poll.status_code == 200 and poll.json()["status"] not in ("submitted", "running"):
                final = poll.json()
                break
            await asyncio.sleep(0.05)
        assert final is not None
        # The REAL frozen runner's job id, propagated and distinct.
        assert final["runtime_job_id"]
        assert final["runtime_job_id"] != surface_id
        assert final["status"] == "failed"  # dead endpoint, deterministic

        # Live polling by the real runtime id returns the same job.
        by_runtime = await client.get(f"/api/hermes/jobs/{final['runtime_job_id']}")
        assert by_runtime.status_code == 200
        assert by_runtime.json()["job_id"] == surface_id
    finally:
        await _cleanup(project_id, run_id)


# ---------------------------------------------------------------------------
# 10. Job N / Job N+1 semantics via the surface
# ---------------------------------------------------------------------------

async def test_sequential_resubmission_gets_fresh_job_id(client, monkeypatch):
    """Job N (awaiting) then Job N+1: fresh surface job ids, no idempotency
    key anywhere in the contract, no checkpoint_id required."""
    _, n_final, n_id = await _submit_and_await(
        client, monkeypatch,
        _runner_result(status="awaiting_approval", error_code="capability_pending_approval",
                       error_detail="stage=thumbnail checkpoint=c1", final=None),
    )
    assert n_final["status"] == "awaiting_approval"
    _, n1_final, n1_id = await _submit_and_await(client, monkeypatch, _runner_result())
    assert n1_final["status"] == "completed"
    assert n1_id != n_id


async def test_concurrent_same_run_surfaces_registry_rejection(client, monkeypatch):
    """D10: a second submission while the first holds the run's active slot
    receives the runner's existing registry rejection verbatim."""
    import app.api.routers.hermes_jobs as surface

    release = threading.Event()
    started = threading.Event()

    def _stub(call):
        started.set()
        release.wait(timeout=5.0)
        return _runner_result()

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _stub)

    first = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert first.status_code == 202
    # Async wait (a blocking Event.wait would starve the background task).
    deadline = asyncio.get_event_loop().time() + 5.0
    while not started.is_set() and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert started.is_set()

    def _reject(call):
        return _admission_failure()

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _reject)
    second = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert second.status_code == 202  # admitted by the SURFACE, rejected by the RUNNER
    second_id = second.json()["job_id"]
    deadline = asyncio.get_event_loop().time() + 5.0
    final = None
    while asyncio.get_event_loop().time() < deadline:
        final = (await client.get(f"/api/hermes/jobs/{second_id}")).json()
        if final["status"] not in ("submitted", "running"):
            break
        await asyncio.sleep(0.01)
    release.set()
    assert final["status"] == "failed"
    assert final["error_code"] == "runner_workflow_run_already_active"


# ---------------------------------------------------------------------------
# 12. F1: single-worker default remains pinned
# ---------------------------------------------------------------------------

def test_single_worker_default_remains_one():
    """D6: the existing operational contract (shared with APScheduler)."""
    assert get_settings().uvicorn_workers == 1


# ---------------------------------------------------------------------------
# 13. Real-runtime smoke test (no external services/credentials)
# ---------------------------------------------------------------------------

async def test_real_runtime_smoke_end_to_end(client, monkeypatch, tmp_path):
    """POST -> 202 -> REAL background runner (construction-only task) ->
    poll -> terminal Hermes result -> §13 JOB_START/JOB_END records."""
    import importlib.util

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    from app.core.config import HERMES_COMMIT_PIN, Settings

    repo_root = tmp_path
    settings = Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "backend" / "app" / "hermes" / "plugins"
        ),
        hermes_home=str(repo_root / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
        openrouter_api_key="sk-surface-smoke",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: settings)

    # Hermetic test: pin the runner's D6 base_url at a dead local endpoint
    # so the real chat path fails WITHOUT any outbound network traffic
    # (the §9.4-established pattern; no real providers, no real keys).
    import app.services.hermes_job_runner as runner_module

    monkeypatch.setattr(runner_module, "_OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")

    # Seed a WorkflowRun the runner can verify, then clean up.
    from app.database.session import AsyncSessionLocal
    from app.models.core import Project, WorkflowRun

    async def _seed():
        async with AsyncSessionLocal() as session:
            project = Project(name="surface-smoke")
            session.add(project)
            await session.flush()
            run = WorkflowRun(project_id=project.id)
            session.add(run)
            await session.commit()
            return project.id, run.id

    async def _cleanup(project_id, run_id):
        async with AsyncSessionLocal() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
            await session.commit()

    project_id, run_id = await _seed()
    try:
        submit = await client.post("/api/hermes/jobs", json=_submit_payload(
            workflow_run_id=str(run_id), task_message="say hi", user_id="surface-test",
        ))
        assert submit.status_code == 202, submit.text
        job_id = submit.json()["job_id"]
        deadline = asyncio.get_event_loop().time() + 60.0
        final = None
        while asyncio.get_event_loop().time() < deadline:
            poll = await client.get(f"/api/hermes/jobs/{job_id}")
            assert poll.status_code == 200, poll.text
            if poll.json()["status"] not in ("submitted", "running"):
                final = poll.json()
                break
            await asyncio.sleep(0.05)
        # Terminal Hermes result through the real runtime (chat against a
        # dead endpoint fails deterministically with the runtime's code).
        assert final is not None
        assert final["status"] == "failed"
        assert final["error_code"] in ("chat_failed", "chat_timeout")

        # §13: JOB_START/JOB_END recorded by the real runtime.
        from app.hermes.audit import FileAuditSink

        audit_file = repo_root / "hermes-root" / "audit" / "hermes_policy_audit.jsonl"
        jobs = FileAuditSink(audit_file).read_job_records()
        assert [r.event for r in jobs] == ["JOB_START", "JOB_END"]
        assert jobs[1].outcome == "failed"
    finally:
        await _cleanup(project_id, run_id)


# ---------------------------------------------------------------------------
# 13. §9.9 test hardening: T1 failed-job API contract, R-s3 exception path
# ---------------------------------------------------------------------------


async def test_t1_api_level_failed_job_contract(client, monkeypatch, tmp_path):
    """§9.9 T1: formalize the COMPLETE externally observable contract of a
    real failed job through the HTTP surface (chat against the pinned dead
    endpoint — deterministic, hermetic). Pins: submit contract preserved
    (202 shape), failed poll semantics (status/error_code/error_detail/
    final_response=None), surface+runtime job identity, timestamps, and
    consistency with §13 JOB_START/JOB_END semantics."""
    import importlib.util
    from pathlib import Path

    if importlib.util.find_spec("run_agent") is None:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    from app.core.config import HERMES_COMMIT_PIN, Settings

    settings = Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(
            Path(__file__).resolve().parents[2] / "backend" / "app" / "hermes" / "plugins"
        ),
        hermes_home=str(tmp_path / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
        openrouter_api_key="sk-t1-surface",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: settings)
    import app.services.hermes_job_runner as runner_module

    monkeypatch.setattr(runner_module, "_OPENROUTER_BASE_URL", "http://127.0.0.1:9/v1")

    from app.database.session import AsyncSessionLocal
    from app.models.core import Project, WorkflowRun

    async def _seed():
        async with AsyncSessionLocal() as session:
            project = Project(name="t1-failed-contract")
            session.add(project)
            await session.flush()
            run = WorkflowRun(project_id=project.id)
            session.add(run)
            await session.commit()
            return project.id, run.id

    async def _cleanup(project_id, run_id):
        async with AsyncSessionLocal() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
            await session.commit()

    project_id, run_id = await _seed()
    try:
        # Submit contract preserved: exactly the frozen four fields, 202.
        submit = await client.post("/api/hermes/jobs", json=_submit_payload(
            workflow_run_id=str(run_id), task_message="will fail", user_id="t1-test",
        ))
        assert submit.status_code == 202
        assert set(submit.json()) == {"job_id", "workflow_run_id", "status", "submitted_at"}
        assert submit.json()["status"] == "submitted"
        assert submit.json()["workflow_run_id"] == str(run_id)
        job_id = submit.json()["job_id"]

        # Poll to terminal failure (bounded).
        deadline = asyncio.get_event_loop().time() + 60.0
        final = None
        while asyncio.get_event_loop().time() < deadline:
            poll = await client.get(f"/api/hermes/jobs/{job_id}")
            assert poll.status_code == 200
            if poll.json()["status"] not in ("submitted", "running"):
                final = poll.json()
                break
            await asyncio.sleep(0.05)
        assert final is not None

        # FAILED-JOB CONTRACT (the formalization this test pins):
        assert final["job_id"] == job_id                      # surface identity
        assert final["workflow_run_id"] == str(run_id)        # run anchor
        assert final["status"] == "failed"                     # terminal state
        # §9.10 exact pin (source-traced + 6/6 empirical probe): at the pinned
        # dead endpoint with hermes_max_execution_seconds=10.0, Hermes' outer
        # provider-unavailable retry cycle (>=17s waits) can NEVER complete
        # inside the AryaOS watchdog, so the terminal code is deterministically
        # chat_timeout and the detail is the runtime's deterministic
        # settings-derived string (runtime.py chat_timeout branch) — no
        # volatile network-library content.
        assert final["error_code"] == "chat_timeout"
        assert final["error_detail"] == "job exceeded hermes_max_execution_seconds=10.0"
        assert final["final_response"] is None                 # only completed jobs carry it
        assert final["runtime_job_id"]                         # R-s1 id present
        assert final["runtime_job_id"] != job_id               # and distinct by design
        assert final["completed_at"]                           # terminal timestamp
        # §9.10: the existing timestamp contract — surface wall timestamps are
        # ISO-8601 and the terminal one is never before submission.
        from datetime import datetime as _datetime

        assert _datetime.fromisoformat(final["submitted_at"])
        completed_ts = _datetime.fromisoformat(final["completed_at"])
        assert completed_ts >= _datetime.fromisoformat(final["submitted_at"])
        assert final["duration_seconds"] is None or isinstance(final["duration_seconds"], float)

        # §13 consistency: the same runtime identity carries JOB_START/END
        # with the failed outcome — the HTTP view IS the §13 view.
        from app.hermes.audit import FileAuditSink

        audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
        jobs = FileAuditSink(audit_file).read_job_records()
        assert [j.event for j in jobs] == ["JOB_START", "JOB_END"]
        assert jobs[0].runtime_job_id == final["runtime_job_id"]
        assert jobs[1].runtime_job_id == final["runtime_job_id"]
        assert jobs[1].outcome == "failed"
        assert jobs[1].error_code == final["error_code"]
        assert jobs[1].violation_code is None                  # runtime failure, not §12

        # Post-restart-equivalent recovery BY the runtime id (§13 fallback).
        import app.api.routers.hermes_jobs as surface

        monkeypatch.setattr(surface, "_HERMES_JOBS", {})
        recovered = await client.get(f"/api/hermes/jobs/{final['runtime_job_id']}")
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "failed"
        assert recovered.json()["error_code"] == final["error_code"]
    finally:
        await _cleanup(project_id, run_id)


async def test_r3_surface_exception_path(client, monkeypatch):
    """§9.9 R-s3: the surface-level BaseException containment branch —
    a raising runner (monkeypatched to raise deterministically; the ONLY
    stub, replacing an external dependency boundary) becomes the
    structured surface_execution_error failure; the request path never
    sees an exception; no audit mutation, no persisted job state, and
    the surface identity remains queryable."""
    import app.api.routers.hermes_jobs as surface

    def _exploding_runner(call):
        raise RuntimeError("runner exploded")

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _exploding_runner)
    submit = await client.post("/api/hermes/jobs", json=_submit_payload())
    assert submit.status_code == 202
    job_id = submit.json()["job_id"]
    deadline = asyncio.get_event_loop().time() + 5.0
    final = None
    while asyncio.get_event_loop().time() < deadline:
        poll = await client.get(f"/api/hermes/jobs/{job_id}")
        assert poll.status_code == 200
        if poll.json()["status"] not in ("submitted", "running"):
            final = poll.json()
            break
        await asyncio.sleep(0.01)
    assert final is not None
    assert final["status"] == "failed"
    assert final["error_code"] == "surface_execution_error"
    assert final["error_detail"] == "RuntimeError"           # type name only, no message
    assert final["final_response"] is None
    assert final["runtime_job_id"] is None                    # runner never minted one
    assert final["completed_at"]
    # "runner exploded" (the exception MESSAGE) must never leak to callers.
    assert "exploded" not in str(final)


async def test_r3_surface_exception_no_audit_or_state_mutation(client, monkeypatch, tmp_path):
    """R-s3 authority/state proof: the exception branch writes NO §13
    record (no runtime job ever ran) and leaves no runner-side state; the
    in-memory entry is the only trace and a fresh submission on the same
    run is still admitted normally afterwards."""
    import app.api.routers.hermes_jobs as surface

    def _exploding_runner(call):
        raise RuntimeError("boom")

    monkeypatch.setattr(surface, "run_aryaos_hermes_job", _exploding_runner)
    settings = get_settings()
    real_home = settings.hermes_home
    settings.hermes_home = str(tmp_path)
    try:
        submit = await client.post("/api/hermes/jobs", json=_submit_payload())
        job_id = submit.json()["job_id"]
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            poll = await client.get(f"/api/hermes/jobs/{job_id}")
            if poll.json()["status"] not in ("submitted", "running"):
                break
            await asyncio.sleep(0.01)
        # No §13 audit file was created: the runtime never ran, so no
        # JOB_START/JOB_END exists and nothing was persisted.
        from pathlib import Path as _P

        audit_file = _P(tmp_path) / "audit" / "hermes_policy_audit.jsonl"
        assert not audit_file.exists()
        # No partial-persisted surface job state: entry exists in memory
        # only (queryable), and the registry admits a fresh submission.
        verdicts = [surface._HERMES_JOBS[job_id]["status"]]
        assert verdicts == ["failed"]
        # A normal (stubbed-success) submission afterwards works — no lock
        # leak, no stuck registry slot.
        _install_runner(monkeypatch, _runner_result())
        second = await client.post("/api/hermes/jobs", json=_submit_payload())
        assert second.status_code == 202
        second_id = second.json()["job_id"]
        deadline = asyncio.get_event_loop().time() + 5.0
        second_final = None
        while asyncio.get_event_loop().time() < deadline:
            poll = await client.get(f"/api/hermes/jobs/{second_id}")
            if poll.json()["status"] not in ("submitted", "running"):
                second_final = poll.json()
                break
            await asyncio.sleep(0.01)
        assert second_final["status"] == "completed"
    finally:
        settings.hermes_home = real_home
