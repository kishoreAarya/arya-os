"""Real-runtime scripted-model tests: harness self-test + T7/T11/T12/T13/T15/T16 (V2).

The ONLY scripted component is the model/provider response (the
operator-authorized harness, tests/hermes_scripted_model.py). Everything
else is REAL: Hermes runtime, §4 policy gate, §9 schema validation,
§12 ledger/budget, approval checkpoints, capability bindings, §13 audit.

Actual layered semantics proven here (source-backed):
- A tool name OUTSIDE the agent's valid_tool_names (shell,
  delegate_task) is refused by Hermes' own pre-dispatch validation
  (agent/turn_tool_validation.py:99) — it never reaches §4; the model
  sees an invalid-name error result and NO execution occurs.
- A VALID capability name with hostile arguments (approval injection,
  credential injection) traverses the REAL §4 gate (ALLOW audited) and
  is BLOCKed by the REAL §9 schema layer (capability_schema_invalid
  audited); the block message returns to the model as the tool result.
- Iterations are capped by Hermes' native loop condition
  (agent/conversation_loop.py:1535) with §12 owning execution bounds.
"""
from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import UTC
from pathlib import Path

import pytest
from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.policy import AuthorizationContext
from app.hermes.runtime import HermesJobRequest, run_hermes_job

from tests.hermes_scripted_model import (
    ScriptedModelServer,
    final_response,
    repeat_tool_calls,
    tool_call,
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None
PLUGIN_PATH = Path(__file__).resolve().parents[1] / "app" / "hermes" / "plugins"


# ---------------------------------------------------------------------------
# Harness plumbing
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "hermes_enabled": True,
        "hermes_commit_pin": HERMES_COMMIT_PIN,
        "hermes_plugin_path": str(PLUGIN_PATH),
        "hermes_home": str(tmp_path / "hermes-root"),
        "hermes_max_iterations": 10,
        "hermes_max_execution_seconds": 60.0,
        "hermes_max_tool_calls": 20,
        "hermes_max_tool_calls_per_capability": 20,
        "hermes_max_generation_budget_usd": 1.0,
        "hermes_max_context_tokens": 64_000,
        "hermes_max_blocked_requests": 20,
        "openrouter_api_key": "sk-scripted-test",
    }
    base.update(overrides)
    return Settings(**base)


def _request(pair, task_message="proceed"):
    project_id, run_id = pair
    return HermesJobRequest(
        job_id=f"scripted-{uuid.uuid4().hex[:8]}",
        task_message=task_message,
        authorization_context=AuthorizationContext(
            user_id="u", project_id=str(project_id), job_id="j",
            workflow_run_id=str(run_id), agent_id="a", lineage_id="l",
        ),
        provider="openai",
        base_url="http://127.0.0.1:9/v1",  # replaced by the harness
        api_key="sk-scripted-test",
        model="aryaos-test-model",
    )


class _Harness:
    """Binds a ScriptedModelServer to the REAL runtime for one job run.
    Only the model endpoint is scripted; the runtime constructs the REAL
    agent (with the documented _disable_streaming test carve-out)."""

    def __init__(self, monkeypatch, tmp_path, script, overrides=None):
        from app.hermes import runtime

        self.runtime = runtime
        self.settings = _settings(tmp_path, **(overrides or {}))
        self.server = ScriptedModelServer(script)
        monkeypatch.setattr("app.core.config.get_settings", lambda: self.settings)
        monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: self.settings)
        original_construct = runtime._construct_agent

        def constructing(request, config, baseline_threads):
            agent = original_construct(request, config, baseline_threads)
            agent._disable_streaming = True  # documented test carve-out
            return agent

        monkeypatch.setattr(runtime, "_construct_agent", constructing)

    def __enter__(self):
        self.server.__enter__()
        return self

    def __exit__(self, *_exc):
        self.server.__exit__()

    def run(self, req: HermesJobRequest):
        req = HermesJobRequest(
            job_id=req.job_id,
            task_message=req.task_message,
            authorization_context=req.authorization_context,
            provider=req.provider,
            base_url=self.server.base_url,  # loopback harness endpoint
            api_key=req.api_key,
            model=req.model,
        )
        return run_hermes_job(req, settings=None)

    def audit(self):
        from app.hermes.audit import FileAuditSink

        audit_file = Path(self.settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
        sink = FileAuditSink(audit_file)
        return (
            [(r.tool_name, r.decision, r.reason_code) for r in sink.read_records()],
            sink.read_job_records(),
        )


# --- DB helpers (disposable-engine pattern; self-contained) ----------------


async def _seed_run(project_name: str, total_cost_usd: float = 0.0):
    from app.hermes.capabilities import _make_capability_engine
    from app.models.core import Project, WorkflowRun
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            project = Project(name=project_name)
            session.add(project)
            await session.flush()
            run = WorkflowRun(project_id=project.id, total_cost_usd=total_cost_usd)
            session.add(run)
            await session.commit()
            return project.id, run.id
    finally:
        await engine.dispose()


async def _cleanup_run(pair) -> None:
    from app.hermes.capabilities import _make_capability_engine
    from app.models.approval import ApprovalCheckpoint
    from app.models.content import Script
    from app.models.core import Project, WorkflowRun
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    project_id, run_id = pair
    engine = _make_capability_engine()
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            await session.execute(delete(Script).where(Script.workflow_run_id == run_id))
            await session.execute(
                delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id)
            )
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, project_id)
            if project is not None:
                await session.delete(project)
            await session.commit()
    finally:
        await engine.dispose()


def _cleanup(pair):
    asyncio.run(_cleanup_run(pair))


def _pending_checkpoint_id(run_id):
    from app.hermes.capabilities import _make_capability_engine
    from app.models.approval import ApprovalCheckpoint
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _find():
        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                rows = (
                    (
                        await session.execute(
                            select(ApprovalCheckpoint)
                            .where(
                                ApprovalCheckpoint.workflow_run_id == run_id,
                                ApprovalCheckpoint.stage == "script",
                            )
                            .order_by(ApprovalCheckpoint.created_at.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    if row.action is None:
                        return row.id
                raise AssertionError("no pending script checkpoint found")
        finally:
            await engine.dispose()

    return asyncio.run(_find())


def _approve_checkpoint(checkpoint_id):
    from datetime import datetime

    from app.hermes.capabilities import _make_capability_engine
    from app.models.approval import ApprovalCheckpoint
    from app.models.enums import ApprovalAction
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _decide():
        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                checkpoint = await session.get(ApprovalCheckpoint, checkpoint_id)
                checkpoint.action = ApprovalAction.APPROVE
                checkpoint.decided_at = datetime.now(UTC).replace(tzinfo=None)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_decide())


def _script_rows(run_id):
    from app.hermes.capabilities import _make_capability_engine
    from app.models.content import Script
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _count():
        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(func.count()).select_from(Script).where(Script.workflow_run_id == run_id)
                )
                return int(result.scalar() or 0)
        finally:
            await engine.dispose()

    return asyncio.run(_count())


# ---------------------------------------------------------------------------
# 0. Harness self-test (hermetic, no runtime)
# ---------------------------------------------------------------------------


def test_harness_self_test_serves_scripted_openai_wire():
    script = [tool_call("todo_list", {}), final_response("done")]
    with ScriptedModelServer(script) as server:
        import httpx

        for expected_finish, expected_name in (("tool_calls", "todo_list"), ("stop", None)):
            resp = httpx.post(
                f"{server.base_url}/chat/completions",
                json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                timeout=5.0,
            )
            assert resp.status_code == 200
            choice = resp.json()["choices"][0]
            assert choice["finish_reason"] == expected_finish
            if expected_name:
                fn = choice["message"]["tool_calls"][0]["function"]
                assert fn["name"] == expected_name and fn["arguments"] == "{}"
            else:
                assert choice["message"]["content"] == "done"
        assert server.turns_served == 2
        assert server.base_url.startswith("http://127.0.0.1:")  # loopback, dynamic port

    # Non-chat probes never consume script turns.
    with ScriptedModelServer([final_response("done")]) as server:
        import httpx

        probe = httpx.post(f"{server.base_url}/models", json={}, timeout=5.0)
        assert probe.status_code == 200
        assert server.turns_served == 0


def test_harness_is_deterministic():
    with ScriptedModelServer([tool_call("todo_list", {"x": 1})]) as a, ScriptedModelServer(
        [tool_call("todo_list", {"x": 1})]
    ) as b:
        import httpx

        ra = httpx.post(f"{a.base_url}/chat/completions", json={}, timeout=5.0).json()
        rb = httpx.post(f"{b.base_url}/chat/completions", json={}, timeout=5.0).json()
        assert ra["choices"][0]["message"]["tool_calls"] == rb["choices"][0]["message"]["tool_calls"]


# ---------------------------------------------------------------------------
# T11 — adversarial model behavior through the REAL runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script,blocked_name,blocked_reason",
    [
        # approval-state injection on a VALID capability name
        (
            [tool_call("research.search", {"topic": "x", "approved": True}), final_response("ok")],
            "research.search",
            "capability_schema_invalid",
        ),
        # credential injection on a VALID capability name
        (
            [
                tool_call("provider.generate", {"prompt": "x", "api_key": "sk-stolen"}),
                final_response("ok"),
            ],
            "provider.generate",
            "capability_schema_invalid",
        ),
        # approval/checkpoint field injection on the gated capability
        (
            [
                tool_call("story.create", {"content": "x", "checkpoint_id": "c1"}),
                final_response("ok"),
            ],
            "story.create",
            "capability_schema_invalid",
        ),
    ],
)
def test_t11_injection_on_valid_names_blocked_by_real_gates(
    tmp_path, monkeypatch, script, blocked_name, blocked_reason
):
    """T11 core: the scripted ADVERSARIAL model calls VALID capability
    names with hostile arguments; the REAL §4 gate ALLOWs the name and
    the REAL §9 layer BLOCKs the request — audited as first-class BLOCK
    events, block result returned to the model, no execution."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t11-{uuid.uuid4().hex[:6]}"))
        with _Harness(monkeypatch, tmp_path, script) as h:
            result = h.run(_request(pair))
            assert result.status == "completed", (result.error_code, result.error_detail)
            assert result.final_response == "ok"
            records, _ = h.audit()
            assert (blocked_name, "ALLOW", "allowed_typed_capability") in records
            assert (blocked_name, "BLOCK", blocked_reason) in records
    finally:
        if pair:
            _cleanup(pair)


def test_t11_invalid_names_refused_before_dispatch(tmp_path, monkeypatch):
    """T11 (layered semantics): tool names outside the agent's surface
    (shell, delegate_task) are refused by Hermes' OWN pre-dispatch
    validation (turn_tool_validation.py:99) — they never reach §4, never
    execute, and produce NO §4 audit record; the model observes an
    invalid-name error and the job completes normally."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t11n-{uuid.uuid4().hex[:6]}"))
        script = [
            tool_call("shell", {"cmd": "whoami"}),
            tool_call("delegate_task", {"task": "x"}),
            final_response("nothing worked"),
        ]
        with _Harness(monkeypatch, tmp_path, script) as h:
            result = h.run(_request(pair))
            assert result.status == "completed"
            assert result.final_response == "nothing worked"
            records, _ = h.audit()
            # The ONLY audited tool requests are for valid names — shell
            # and delegate_task never reached the §4 gate at all.
            audited = {r[0] for r in records}
            assert "shell" not in audited and "delegate_task" not in audited
    finally:
        if pair:
            _cleanup(pair)


def test_t11_block_result_is_model_visible(tmp_path, monkeypatch):
    """The §9 BLOCK message returns to the MODEL as the tool result —
    proving the request traversed the real dispatch path, and no
    execution occurred (research never ran)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t11v-{uuid.uuid4().hex[:6]}"))
        script = [
            tool_call("research.search", {"topic": "x", "approved": True}),
            final_response("gave up"),
        ]
        with _Harness(monkeypatch, tmp_path, script) as h:
            result = h.run(_request(pair))
            assert result.final_response == "gave up"
            assert h.server.turns_served == 2
            msgs = h.server.requests[-1].get("messages", [])
            roles = [m.get("role") for m in msgs]
            assert "assistant" in roles and "tool" in roles  # real tool round
            tool_results = [m for m in msgs if m.get("role") == "tool"]
            assert any("Blocked by AryaOS policy gate" in str(m.get("content", "")) for m in tool_results)
    finally:
        if pair:
            _cleanup(pair)


# ---------------------------------------------------------------------------
# T12 — iteration cap via scripted model
# ---------------------------------------------------------------------------


def test_t12_iteration_cap_enforced(tmp_path, monkeypatch):
    """T12 (actual semantics): a model that ALWAYS requests tool calls is
    stopped by Hermes' native loop cap (conversation_loop.py:1535
    ``while api_call_count < max_iterations``) — no model request beyond
    the cap; executed tool calls stay within the §12 ledger; the job
    terminates deterministically with a complete §13 lifecycle."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t12-{uuid.uuid4().hex[:6]}"))
        script = repeat_tool_calls("todo_list", {}, 50)  # model wants 50 turns
        with _Harness(monkeypatch, tmp_path, script, {"hermes_max_iterations": 3}) as h:
            result = h.run(_request(pair))
            # ACTUAL pinned semantics (source-verified): exactly
            # max_iterations=3 main-loop iterations EXECUTE (3 executed
            # todo_list rounds); Hermes then appends its iteration-limit
            # user message and may issue the documented budget-grace call
            # (conversation_loop.py:1535), i.e. at most max_iterations + 2
            # model requests in total.
            assert h.server.turns_served <= 5, h.server.turns_served
            # No execution beyond the cap: exactly 3 ALLOWed tool rounds.
            records, jobs = h.audit()
            allowed = [r for r in records if r[0] == "todo_list" and r[1] == "ALLOW"]
            assert len(allowed) == 3, allowed
            assert not [r for r in records if r[0] == "todo_list" and r[1] == "BLOCK"]
            # Deterministic terminal behavior: Hermes' own iteration-limit
            # handling ends the turn; no §12 violation; job completes.
            assert result.status == "completed", (result.error_code, result.error_detail)
            assert "iteration limit" in (result.final_response or "").lower()
            assert [j.event for j in jobs] == ["JOB_START", "JOB_END"]
            assert jobs[1].outcome == "completed"
            assert jobs[1].violation_code is None
    finally:
        if pair:
            _cleanup(pair)


# ---------------------------------------------------------------------------
# T15 — chat-path memory-artifact absence (§9.9; harness-driven)
# ---------------------------------------------------------------------------


def test_t15_chat_path_creates_no_memory_artifacts(tmp_path, monkeypatch):
    """T15 (§9.9): the §6 memory invariant asserted on the ACTUAL chat
    path — a scripted-model job with REAL tool rounds (model driven,
    tools executed, final response returned) leaves no memory/session/
    recall artifacts anywhere under the Hermes home, and the home tree is
    exactly the §13 audit store plus the empty jobs root. The runtime
    constructs the agent with skip_memory/skip_context_files/
    skip_background_review=True (runtime.py:373-375) — this proves the
    invariant survives real model turns, not just construction."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t15-{uuid.uuid4().hex[:6]}"))
        script = [
            tool_call("todo_list", {}),          # real executed tool round
            tool_call("research.search", {"topic": "memory-check"}),  # real capability
            final_response("chat path complete"),
        ]
        with _Harness(monkeypatch, tmp_path, script) as h:
            result = h.run(_request(pair, task_message="drive the chat path"))
            # The chat path genuinely ran: two executed tool rounds and a
            # real model final response.
            assert result.status == "completed", (result.error_code, result.error_detail)
            assert result.final_response == "chat path complete"
            records, _ = h.audit()
            assert ("todo_list", "ALLOW", "allowed_sanctioned_native_tool") in records
            assert ("research.search", "ALLOW", "allowed_typed_capability") in records

            home = Path(h.settings.hermes_home)
            # Exact-tree invariant (strongest repository-supported form):
            # ONLY the §13 audit store + the empty jobs root survive.
            tree = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
            assert tree == ["audit", "audit/hermes_policy_audit.jsonl", "jobs"], tree
            assert list((home / "jobs").iterdir()) == []
            # Memory-artifact absence on the chat path (§6): no file or
            # directory with a memory/session/recall token anywhere.
            forbidden = [
                p for p in home.rglob("*")
                if any(token in p.name.lower() for token in ("memory", "session", "recall"))
            ]
            assert forbidden == [], forbidden
            assert not list(home.rglob(".env"))
    finally:
        if pair:
            _cleanup(pair)


def test_t15_chat_path_leaves_no_artifacts_outside_hermes_home(tmp_path, monkeypatch):
    """T15 companion: the chat-path job writes nothing outside the Hermes
    home — an external canary tree in the test sandbox is byte-identical
    after a real model-driven job with executed tool rounds."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    canary_dir = tmp_path / "outside-hermes"
    canary_dir.mkdir()
    canaries = {}
    for name, payload in (
        ("state.json", '{"canary": true}\n'),
        ("nested/data.txt", "canary"),
    ):
        target = canary_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
        canaries[target] = payload

    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t15o-{uuid.uuid4().hex[:6]}"))
        script = [tool_call("todo_list", {}), final_response("done")]
        with _Harness(monkeypatch, tmp_path / "home", script) as h:
            result = h.run(_request(pair))
            assert result.status == "completed"
        tree = sorted(str(p.relative_to(canary_dir)) for p in canary_dir.rglob("*"))
        assert tree == ["nested", "nested/data.txt", "state.json"]
        for target, payload in canaries.items():
            assert target.read_text() == payload
    finally:
        if pair:
            _cleanup(pair)


# ---------------------------------------------------------------------------
# T7 — runtime activation violation branch (§9.10 test-only fault injection)
# ---------------------------------------------------------------------------


def test_t7_runtime_activation_violation_fails_closed(tmp_path, monkeypatch):
    """T7 (§9.10): the frozen runtime's cron-activation guard
    (_assert_no_runtime_activation, runtime.py) actually FAILS CLOSED.
    Test-only fault injection: the ONLY patched thing is the vendor
    scheduler's running-job REPORT (cron.scheduler.get_running_job_ids)
    made to report one fake id — no cron is ever created or run, no
    thread is spawned, no network is touched. The REAL runtime then
    constructs the agent, hits the guard, and must return a typed
    cron_activated failure with a complete consistent §13 lifecycle and
    full cleanup (per-job home removed, runtime bindings unbound)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    import threading

    import cron.scheduler as cron_scheduler

    original_running = cron_scheduler.get_running_job_ids
    monkeypatch.setattr(
        cron_scheduler, "get_running_job_ids", lambda: frozenset({"t7-fake-cron-job"})
    )

    settings = _settings(tmp_path / "home")
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.hermes.runtime.get_settings", lambda: settings)

    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t7-{uuid.uuid4().hex[:6]}"))
        result = run_hermes_job(_request(pair), settings=None)

        # Fail closed with the exact frozen error contract (runtime.py
        # cron_activated branch): typed code + deterministic detail built
        # from OUR sentinel — nothing else leaks into the detail.
        assert result.status == "failed"
        assert result.error_code == "cron_activated"
        assert result.error_detail == (
            "Hermes cron jobs are running during an embedded job: ['t7-fake-cron-job']"
        )
        assert result.final_response is None

        # The violation is observable through the §13 contract: JOB_START
        # (pre-construction) + JOB_END carry the SAME runtime id, the failed
        # outcome, the same error code, and no §12 violation.
        from app.hermes.audit import FileAuditSink

        audit_file = Path(settings.hermes_home) / "audit" / "hermes_policy_audit.jsonl"
        jobs = FileAuditSink(audit_file).read_job_records()
        assert [j.event for j in jobs] == ["JOB_START", "JOB_END"]
        assert {j.runtime_job_id for j in jobs} == {result.job_id}
        assert jobs[1].outcome == "failed"
        assert jobs[1].error_code == "cron_activated"
        assert jobs[1].violation_code is None

        # Deterministic cleanup ran: the per-job home is gone and every
        # runtime binding was unbound (fail closed, no leaked state).
        assert not (Path(settings.hermes_home) / "jobs" / result.job_id).exists()
        from app.hermes.runtime import (
            _ACTIVATION_THREAD_PATTERNS,
            get_active_audit_sink,
            get_active_authorization_context,
            get_active_job_ledger,
        )

        with pytest.raises(RuntimeError):
            get_active_authorization_context()
        assert get_active_job_ledger() is None
        assert get_active_audit_sink() is None

        # No ACTUAL runtime activation occurred: the real scheduler registry
        # (unpatched function object) reports nothing running, and no thread
        # matching the runtime's activation patterns survived the job.
        assert original_running() == frozenset()
        assert not [
            t.name
            for t in threading.enumerate()
            if any(pattern in t.name.lower() for pattern in _ACTIVATION_THREAD_PATTERNS)
        ]
    finally:
        if pair:
            _cleanup(pair)


# ---------------------------------------------------------------------------
# T13 — AryaOS remains the system of record (§9.10 named evidence)
# ---------------------------------------------------------------------------


def test_t13_aryaos_remains_system_of_record(tmp_path, monkeypatch):
    """T13 (§16, named evidence): AryaOS remains the system of record for
    the Hermes job lifecycle and durable artifacts. One full approval arc
    through the REAL runtime — Job N requests story.create and pends on a
    DURABLE AryaOS ApprovalCheckpoint row; the checkpoint is decided in
    the AryaOS DB; Job N+1 (FRESH runtime identity, same run) executes
    the approved capability and persists the durable artifact (a real
    Script row on the run) — while both jobs' complete §13
    JOB_START/JOB_END lifecycles anchor to the SAME workflow-run
    identity, and no Hermes memory/session/recall artifact survives as a
    competing persistence authority."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    from app.hermes.audit import FileAuditSink

    def _job_records(home):
        return FileAuditSink(Path(home) / "audit" / "hermes_policy_audit.jsonl").read_job_records()

    def _run_anchor(pair_):
        from app.hermes.capabilities import _make_capability_engine
        from app.models.core import WorkflowRun
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def _read():
            engine = _make_capability_engine()
            try:
                async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                    run = await session.get(WorkflowRun, pair_[1])
                    return (str(run.id), str(run.project_id)) if run is not None else None
            finally:
                await engine.dispose()

        return asyncio.run(_read())

    pair = None
    try:
        pair = asyncio.run(_seed_run(f"t13-{uuid.uuid4().hex[:6]}"))
        run_id = str(pair[1])

        # ---- Job N: gated request -> durable pending checkpoint ----------
        with _Harness(
            monkeypatch, tmp_path / "n", [tool_call("story.create", {"content": "t13 proposed draft"})]
        ) as h:
            result_n = h.run(_request(pair))
            assert result_n.status == "awaiting_approval"
            assert result_n.error_code == "capability_pending_approval"
            jobs_n = _job_records(h.settings.hermes_home)
            # §13 lifecycle for Job N: both boundaries, ONE runtime identity,
            # anchored to the AryaOS workflow run, awaiting outcome verbatim.
            assert [j.event for j in jobs_n] == ["JOB_START", "JOB_END"]
            assert {j.runtime_job_id for j in jobs_n} == {result_n.job_id}
            assert all(j.workflow_run_id == run_id for j in jobs_n)
            assert jobs_n[1].outcome == "awaiting_approval"
            assert jobs_n[1].error_code == "capability_pending_approval"

        # The approval authority is a DURABLE AryaOS DB row, not any
        # Hermes-side state; deciding it is an AryaOS act.
        checkpoint_id = _pending_checkpoint_id(pair[1])
        _approve_checkpoint(checkpoint_id)

        # ---- Job N+1: FRESH runtime identity, same run, executes ---------
        with _Harness(
            monkeypatch,
            tmp_path / "n1",
            [
                tool_call("story.create", {"content": "t13 proposed draft"}),
                final_response("draft submitted"),
            ],
        ) as h2:
            result_n1 = h2.run(_request(pair))
            assert result_n1.status == "completed", (result_n1.error_code, result_n1.error_detail)
            assert result_n1.final_response == "draft submitted"
            # Fresh runtime identity per job: Job N+1 is a NEW job, not a resume.
            assert result_n1.job_id != result_n.job_id
            jobs_n1 = _job_records(h2.settings.hermes_home)
            assert [j.event for j in jobs_n1] == ["JOB_START", "JOB_END"]
            assert {j.runtime_job_id for j in jobs_n1} == {result_n1.job_id}
            assert all(j.workflow_run_id == run_id for j in jobs_n1)
            assert jobs_n1[1].outcome == "completed"
            assert jobs_n1[1].error_code is None
            # The durable artifact lives in ARYAOS persistence: a real Script
            # row on the authoritative run — not in any Hermes-side store.
            assert _script_rows(pair[1]) == 1
            # No competing Hermes persistence authority survives the job: the
            # home is exactly the §13 audit store + the empty jobs root, with
            # no memory/session/recall artifact anywhere.
            home = Path(h2.settings.hermes_home)
            tree = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
            assert tree == ["audit", "audit/hermes_policy_audit.jsonl", "jobs"], tree
            assert not [
                p
                for p in home.rglob("*")
                if any(token in p.name.lower() for token in ("memory", "session", "recall"))
            ]

        # The AryaOS run identity itself remains the anchor after the whole
        # arc: the WorkflowRun row is intact under its original project.
        assert _run_anchor(pair) == (run_id, str(pair[0]))
    finally:
        if pair:
            _cleanup(pair)


def test_t16_combined_budget_denial_and_approval_resume(tmp_path, monkeypatch):
    """T16 formal combined test, both halves fully model-driven through
    the REAL runtime (only the model is scripted):
    (a) budget: run already at the §12 USD budget; the model calls
        provider.generate -> real §4 ALLOW + real §12 USD gate denies
        BEFORE execution -> ledger violation -> job FAILED with
        generation_budget_exceeded and consistent §13 records.
    (b) approval: fresh run; the model calls story.create -> pending ->
        job awaiting_approval; external approval decides the checkpoint;
        Job N+1 (same run, FRESH job) with the model repeating the call
        -> REAL Script row created; both jobs' §13 lifecycles complete."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing")
    at_budget = None
    fresh = None
    try:
        # ---- Half (a): budget denial ------------------------------------
        at_budget = asyncio.run(_seed_run(f"t16a-{uuid.uuid4().hex[:6]}", total_cost_usd=1.0))
        script_a = [
            tool_call("provider.generate", {"prompt": "write a hook"}),
            final_response("unreachable"),
        ]
        with _Harness(monkeypatch, tmp_path / "a", script_a) as h:
            result_a = h.run(_request(at_budget))
            assert result_a.status == "failed"
            assert result_a.error_code == "generation_budget_exceeded"
            records_a, jobs_a = h.audit()
            assert ("provider.generate", "ALLOW", "allowed_typed_capability") in records_a
            assert ("provider.generate", "BLOCK", "generation_budget_exceeded") in records_a
            assert jobs_a[1].outcome == "failed"
            assert jobs_a[1].violation_code == "generation_budget_exceeded"

        # ---- Half (b): approval -> awaiting -> approve -> Job N+1 -------
        fresh = asyncio.run(_seed_run(f"t16b-{uuid.uuid4().hex[:6]}"))
        with _Harness(
            monkeypatch, tmp_path / "b", [tool_call("story.create", {"content": "a proposed draft"})]
        ) as h:
            result_n = h.run(_request(fresh))
            assert result_n.status == "awaiting_approval"
            assert result_n.error_code == "capability_pending_approval"
            checkpoint_id = _pending_checkpoint_id(fresh[1])
        _approve_checkpoint(checkpoint_id)

        with _Harness(
            monkeypatch,
            tmp_path / "b2",
            [
                tool_call("story.create", {"content": "a proposed draft"}),
                final_response("draft submitted"),
            ],
        ) as h2:
            result_n1 = h2.run(_request(fresh))
            assert result_n1.status == "completed", (result_n1.error_code, result_n1.error_detail)
            assert result_n1.final_response == "draft submitted"
            assert _script_rows(fresh[1]) == 1  # REAL artifact on the right run
            records_b2, jobs_b2 = h2.audit()
            assert jobs_b2[1].outcome == "completed"
            assert ("story.create", "BLOCK", "capability_pending_approval") not in records_b2
            executions = [r for r in records_b2 if r[0] == "story.create"]
            assert executions  # the approved call executed for real
    finally:
        if at_budget:
            _cleanup(at_budget)
        if fresh:
            _cleanup(fresh)
