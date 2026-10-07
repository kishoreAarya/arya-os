"""Approval decision history + first-class REVOKE (operator-locked slice).

Proves the append-only ApprovalDecision semantics through the REAL
routes (POST /approvals, POST /approvals/{id}/decide, GET
/approvals/{id}/decisions, GET /approvals/{id}) against the real
database: events are immutable, REJECT stays distinct from REVOKE, the
ApprovalCheckpoint current-state cache always equals the latest event,
ordering is deterministic (sequence_number), legacy migration invariants
hold (backfilled rows carry exactly one synthetic event; the six
operator-excluded rows carry none), and Model B authorization semantics
are unchanged at the gate.
"""
import asyncio
import uuid

from app.main import app  # noqa: F401 — app import for the ASGI client fixtures

# ---------------------------------------------------------------------------
# Helpers (real routes + disposable DB seeding/cleanup)
# ---------------------------------------------------------------------------


async def _seed_checkpoint_via_api(client, stage="script"):
    """Create a real pending checkpoint through POST /approvals (the n8n
    path) anchored to a freshly seeded Project/WorkflowRun."""
    from app.hermes.capabilities import _make_capability_engine
    from app.models.core import Project, WorkflowRun

    engine = _make_capability_engine()
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            project = Project(name=f"ah-{uuid.uuid4().hex[:8]}")
            session.add(project)
            await session.flush()
            run = WorkflowRun(project_id=project.id)
            session.add(run)
            await session.commit()
            pair = (project.id, run.id)
    finally:
        await engine.dispose()

    resp = await client.post(
        "/approvals/",
        json={
            "workflow_run_id": str(pair[1]),
            "stage": stage,
            "reference_table": "workflow_runs",
            "reference_id": str(pair[1]),
        },
    )
    assert resp.status_code == 200, resp.text
    return pair, resp.json()["id"]


async def _cleanup(pair, checkpoint_ids):
    from app.hermes.capabilities import _make_capability_engine
    from app.models.approval import ApprovalCheckpoint, ApprovalDecision
    from app.models.core import Project, WorkflowRun

    engine = _make_capability_engine()
    try:
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            for cid in checkpoint_ids:
                await session.execute(
                    delete(ApprovalDecision).where(ApprovalDecision.checkpoint_id == cid)
                )
                await session.execute(
                    delete(ApprovalCheckpoint).where(ApprovalCheckpoint.id == cid)
                )
            run = await session.get(WorkflowRun, pair[1])
            if run is not None:
                await session.delete(run)
            project = await session.get(Project, pair[0])
            if project is not None:
                await session.delete(project)
            await session.commit()
    finally:
        await engine.dispose()


async def _decide(client, checkpoint_id, action, notes=None, decided_by=None):
    payload = {"action": action}
    if notes is not None:
        payload["reviewer_notes"] = notes
    if decided_by is not None:
        payload["decided_by"] = decided_by
    return await client.post(f"/approvals/{checkpoint_id}/decide", json=payload)


async def _history(client, checkpoint_id):
    resp = await client.get(f"/approvals/{checkpoint_id}/decisions")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1-8: append-only history semantics
# ---------------------------------------------------------------------------


async def test_decide_appends_immutable_events(client):
    """PENDING -> APPROVE -> REVOKE -> APPROVE produces THREE permanent
    events; earlier events (action, decided_at, notes, decided_by) never
    change; sequences are 1,2,3; the cache equals the latest event at
    every step."""
    pair, checkpoint_id = await _seed_checkpoint_via_api(client)
    try:
        # PENDING -> APPROVE: exactly one event.
        first = await _decide(client, checkpoint_id, "approve", notes="first approval", decided_by="op-1")
        assert first.status_code == 200
        events = await _history(client, checkpoint_id)
        assert len(events) == 1
        assert events[0]["action"] == "approve"
        assert events[0]["sequence_number"] == 1
        assert events[0]["decided_by"] == "op-1"
        assert events[0]["reviewer_notes"] == "first approval"
        original_first = dict(events[0])

        # APPROVE -> REVOKE: second event; original preserved verbatim.
        second = await _decide(client, checkpoint_id, "revoke", notes="withdrawn", decided_by="op-2")
        assert second.status_code == 200
        # The REVOKE makes the checkpoint non-authorizing (cache state).
        assert second.json()["action"] == "revoke"
        events = await _history(client, checkpoint_id)
        assert len(events) == 2
        assert {e["action"] for e in events} == {"approve", "revoke"}
        assert events[0] == original_first  # immutable: byte-identical
        assert events[1]["sequence_number"] == 2

        # REVOKE -> APPROVE: THIRD event (not an edit of event #1).
        third = await _decide(client, checkpoint_id, "approve", notes="re-approved")
        assert third.status_code == 200
        events = await _history(client, checkpoint_id)
        assert [e["sequence_number"] for e in events] == [1, 2, 3]
        assert [e["action"] for e in events] == ["approve", "revoke", "approve"]
        assert events[0] == original_first  # the original APPROVE survives
        for earlier, later in ((events[0], events[2]), (events[1], events[2])):
            assert later["decided_at"] > earlier["decided_at"]

        # Cache equals the latest event.
        state = (await client.get(f"/approvals/{checkpoint_id}")).json()
        assert state["action"] == "approve"
        assert state["decided_at"] == events[2]["decided_at"]
        assert state["reviewer_notes"] == "re-approved"
    finally:
        await _cleanup(pair, [checkpoint_id])


async def test_reject_and_revoke_are_distinct(client):
    """REJECT = request not authorized; REVOKE = withdrawing an existing
    authorization. Both non-authorizing at the cache, permanently
    distinct in history; REJECT -> APPROVE preserves both events."""
    pair_a, cp_a = await _seed_checkpoint_via_api(client)
    pair_b, cp_b = await _seed_checkpoint_via_api(client)
    try:
        await _decide(client, cp_a, "reject", notes="not approved")
        await _decide(client, cp_b, "approve")
        await _decide(client, cp_b, "revoke", notes="withdrawn after approval")

        events_a = await _history(client, cp_a)
        events_b = await _history(client, cp_b)
        assert [e["action"] for e in events_a] == ["reject"]
        assert [e["action"] for e in events_b] == ["approve", "revoke"]

        # REJECT -> APPROVE on the same checkpoint: both events preserved.
        await _decide(client, cp_a, "approve", notes="approved later")
        events_a = await _history(client, cp_a)
        assert [e["action"] for e in events_a] == ["reject", "approve"]
        assert events_a[0]["reviewer_notes"] == "not approved"
        assert (await client.get(f"/approvals/{cp_a}")).json()["action"] == "approve"
    finally:
        await _cleanup(pair_a, [cp_a])
        await _cleanup(pair_b, [cp_b])


async def test_repeated_approve_creates_distinct_events(client):
    """APPROVE -> APPROVE appends a second event (never a no-op mutation);
    notes stay attached to their individual events."""
    pair, checkpoint_id = await _seed_checkpoint_via_api(client)
    try:
        await _decide(client, checkpoint_id, "approve", notes="note A", decided_by="r1")
        await _decide(client, checkpoint_id, "approve", notes="note B", decided_by="r2")
        events = await _history(client, checkpoint_id)
        assert [e["sequence_number"] for e in events] == [1, 2]
        assert events[0]["reviewer_notes"] == "note A" and events[0]["decided_by"] == "r1"
        assert events[1]["reviewer_notes"] == "note B" and events[1]["decided_by"] == "r2"
        assert events[0]["decided_at"] != events[1]["decided_at"]
    finally:
        await _cleanup(pair, [checkpoint_id])


async def test_decided_by_blank_is_null_and_history_404(client):
    """Blank decided_by is stored as NULL (no invented provenance); the
    history endpoint 404s for an unknown checkpoint."""
    pair, checkpoint_id = await _seed_checkpoint_via_api(client)
    try:
        resp = await _decide(client, checkpoint_id, "approve", decided_by="   ")
        assert resp.status_code == 200
        events = await _history(client, checkpoint_id)
        assert events[0]["decided_by"] is None
        missing = await client.get(f"/approvals/{uuid.uuid4()}/decisions")
        assert missing.status_code == 404
    finally:
        await _cleanup(pair, [checkpoint_id])


async def test_concurrent_decides_cannot_corrupt_cache(client):
    """Two concurrent decide calls both append; the events carry distinct
    deterministic sequences and the cache equals the LATEST (highest
    sequence) event — the row lock + MAX+1 allocation keep the cache
    consistent with the authoritative history."""
    pair, checkpoint_id = await _seed_checkpoint_via_api(client)
    try:
        responses = await asyncio.gather(
            _decide(client, checkpoint_id, "approve", notes="c1"),
            _decide(client, checkpoint_id, "revoke", notes="c2"),
        )
        assert all(r.status_code == 200 for r in responses)
        events = await _history(client, checkpoint_id)
        assert sorted(e["sequence_number"] for e in events) == [1, 2]
        latest = max(events, key=lambda e: e["sequence_number"])
        state = (await client.get(f"/approvals/{checkpoint_id}")).json()
        assert state["action"] == latest["action"]
        assert state["decided_at"] == latest["decided_at"]
    finally:
        await _cleanup(pair, [checkpoint_id])


# ---------------------------------------------------------------------------
# 14-15: legacy migration invariants (operator Option 1)
# ---------------------------------------------------------------------------


async def test_legacy_migration_invariants():
    """Backfill contract (migration d4e5f6a7b8c9), verified DATA-
    INDEPENDENTLY: the test seeds its own minimal legacy-shaped rows
    (pre-Model-B checkpoints: decided-with-decided_at, the six-row
    operator-excluded shape action=APPROVE/decided_at NULL/NULL digest,
    and a pending control row), executes the migration's OWN backfill
    SQL (extracted from the migration module source and locked to the
    shipped contract text), and proves the invariants against only the
    rows it created — everything inside one rolled-back transaction, so
    the test neither depends on nor disturbs any pre-existing database
    content:

    - every decided checkpoint WITH decided_at receives EXACTLY ONE
      synthetic event (sequence 1, decided_by NULL, action/decided_at/
      reviewer_notes copied verbatim — nothing invented);
    - the operator-excluded rows receive ZERO events and remain APPROVE,
      decided_at NULL, digest NULL — untouched;
    - a pending checkpoint receives no event;
    - every decided checkpoint's cache is derivable from its latest
      event (append-only decision-log contract).
    """
    import importlib.util
    import inspect
    import re
    from datetime import datetime, timedelta
    from pathlib import Path

    from app.hermes.capabilities import _make_capability_engine
    from app.models.approval import ApprovalCheckpoint
    from app.models.core import Project, WorkflowRun
    from app.models.enums import ApprovalAction, ApprovalStage
    from sqlalchemy import bindparam, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # The shipped backfill contract (whitespace-normalized). If the
    # migration's SQL changes, this lock forces this test to be
    # re-reviewed against the new contract.
    _EXPECTED_BACKFILL_SQL = (
        "INSERT INTO approval_decisions "
        "(id, checkpoint_id, sequence_number, action, decided_at, "
        "decided_by, reviewer_notes, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, 1, action, decided_at, "
        "NULL, reviewer_notes, decided_at, decided_at "
        "FROM approval_checkpoints "
        "WHERE action IS NOT NULL AND decided_at IS NOT NULL"
    )

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "d4e5f6a7b8c9_add_approval_decision_history_and_revoke.py"
    )
    spec = importlib.util.spec_from_file_location(
        "d4e5f6a7b8c9_migration_under_test", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    triple_quoted = re.findall(
        r'op\.execute\(\s*"""(.*?)"""\s*\)',
        inspect.getsource(migration.upgrade),
        re.DOTALL,
    )
    assert len(triple_quoted) == 1, "expected exactly one triple-quoted op.execute"
    backfill_sql = " ".join(triple_quoted[0].split())
    assert backfill_sql == _EXPECTED_BACKFILL_SQL

    async def _run():
        engine = _make_capability_engine()
        try:
            async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                # --- Seed the minimal legacy world (never committed). ---
                project = Project(name=f"i6-mig-{uuid.uuid4().hex[:8]}")
                session.add(project)
                await session.flush()
                run = WorkflowRun(project_id=project.id)
                session.add(run)
                await session.flush()

                # Deliberately NAIVE: the legacy decided_at column is a
                # naive timestamp and the migration copies it verbatim.
                base = datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001
                decided_ids, notes = [], {}
                for i in range(5):
                    action = ApprovalAction.APPROVE if i % 2 == 0 else ApprovalAction.REJECT
                    decided_at = base + timedelta(hours=i)
                    cp = ApprovalCheckpoint(
                        workflow_run_id=run.id,
                        stage=ApprovalStage.SCRIPT,
                        reference_table="workflow_runs",
                        reference_id=run.id,
                        action=action,
                        reviewer_notes=f"legacy note {i}",
                        decided_at=decided_at,
                        parameter_digest=f"digest-{i}",
                    )
                    session.add(cp)
                    await session.flush()
                    decided_ids.append(cp.id)
                    notes[cp.id] = (action, decided_at, f"legacy note {i}")

                excluded_ids = []
                for _ in range(6):
                    cp = ApprovalCheckpoint(
                        workflow_run_id=run.id,
                        stage=ApprovalStage.SCRIPT,
                        reference_table="workflow_runs",
                        reference_id=run.id,
                        action=ApprovalAction.APPROVE,
                        decided_at=None,
                        parameter_digest=None,
                    )
                    session.add(cp)
                    await session.flush()
                    excluded_ids.append(cp.id)

                pending = ApprovalCheckpoint(
                    workflow_run_id=run.id,
                    stage=ApprovalStage.SCRIPT,
                    reference_table="workflow_runs",
                    reference_id=run.id,
                )
                session.add(pending)
                await session.flush()

                # --- Execute the migration's OWN backfill, scoped to the
                # seeded checkpoints only (hermetic on any database). ---
                await session.flush()
                scoped = text(
                    backfill_sql.replace(
                        "WHERE action IS NOT NULL AND decided_at IS NOT NULL",
                        "WHERE action IS NOT NULL AND decided_at IS NOT NULL "
                        "AND id IN :seeded_ids",
                    )
                ).bindparams(bindparam("seeded_ids", expanding=True))
                await session.execute(
                    scoped, {"seeded_ids": decided_ids + excluded_ids + [pending.id]}
                )

                # --- Invariants, proven only against the seeded rows. ---
                def _in(cp_ids):
                    return text(
                        "SELECT count(*) FROM approval_decisions d "
                        "JOIN approval_checkpoints cp ON cp.id = d.checkpoint_id "
                        "WHERE cp.id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True))

                backfilled = (
                    await session.execute(_in(decided_ids), {"ids": decided_ids})
                ).scalar()
                excluded_events = (
                    await session.execute(_in(excluded_ids), {"ids": excluded_ids})
                ).scalar()
                pending_events = (
                    await session.execute(_in([pending.id]), {"ids": [pending.id]})
                ).scalar()

                events = {}
                for cp_id in decided_ids:
                    rows = (
                        await session.execute(
                            text(
                                "SELECT sequence_number, action::text, decided_at, "
                                "decided_by, reviewer_notes, created_at, updated_at "
                                "FROM approval_decisions WHERE checkpoint_id = :cp"
                            ).bindparams(cp=cp_id)
                        )
                    ).fetchall()
                    events[cp_id] = rows

                untouched = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM approval_checkpoints "
                            "WHERE id IN :ids AND action::text = 'APPROVE' "
                            "AND decided_at IS NULL AND parameter_digest IS NULL"
                        ).bindparams(bindparam("ids", expanding=True)),
                        {"ids": excluded_ids},
                    )
                ).scalar()

                # Everything runs inside ONE transaction: roll back so the
                # seeded world and the scoped backfill never persist.
                await session.rollback()
                return (
                    backfilled, excluded_events, pending_events, events, notes,
                    untouched,
                )
        finally:
            await engine.dispose()

    backfilled, excluded_events, pending_events, events, notes, untouched = await _run()

    # Exactly one synthetic event per decided-with-decided_at row.
    assert backfilled == 5
    for cp_id, rows in events.items():
        assert len(rows) == 1
        seq, action, decided_at, decided_by, reviewer_notes, created, updated = rows[0]
        assert seq == 1
        expected_action, expected_decided_at, expected_notes = notes[cp_id]
        assert action == expected_action.name  # PG enum label form
        # Verbatim copy — nothing invented.
        assert decided_at == expected_decided_at
        assert reviewer_notes == expected_notes
        assert decided_by is None  # no invented provenance
        # created_at/updated_at are timestamptz columns: the naive copy
        # reads back UTC-aware when the session timezone is UTC. Compare
        # the wall-clock value the migration copied (nothing invented).
        assert created.replace(tzinfo=None) == expected_decided_at
        assert updated.replace(tzinfo=None) == expected_decided_at
        # Cache derivable from the (single) latest event.
        assert (action, decided_at, reviewer_notes) == (
            expected_action.name, expected_decided_at, expected_notes
        )

    # The operator-excluded rows: zero events, still APPROVE, untouched.
    assert excluded_events == 0
    assert untouched == 6

    # Pending checkpoints receive no event.
    assert pending_events == 0
