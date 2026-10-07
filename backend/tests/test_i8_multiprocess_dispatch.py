"""Phase 54B-I8 Workstream D: CROSS-PROCESS publication concurrency.

Two independent OS processes (spawn context — separate interpreters,
separate event loops, separate DB engines/sessions) dispatch the SAME
publication intent simultaneously against the same disposable
PostgreSQL database, synchronized by a Manager barrier immediately
before the agent run. Proves the database-enforced guarantees operate
ACROSS PROCESSES, not merely across coroutines:

- UNIQUE(intent_key, attempt_number) arbitrates competing admissions:
  exactly one process obtains the permit and performs the single
  upload/publish sequence; the loser resolves to the existing attempt
  and refuses with ZERO external calls;
- after a SUCCEEDED terminal state, competing re-dispatches are
  idempotent duplicates (no second publication, terminal state never
  overwritten);
- after an UNKNOWN outcome, competing re-dispatches across processes
  are BLOCKED at admission (durable manual-reconciliation state).

The authorization chain (53B gate + manifest binding) is fully REAL per
process; only the platform adapter is scripted, each process recording
its external calls to its own JSON evidence file.
"""
import json
from pathlib import Path

from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt

_RESULTS_DIR = Path(__file__).parent / "_i8_mp_results"


def _spawn_pair(ctx, publish_behavior="ok"):
    """Run two independent dispatch OS processes (subprocess workers with
    a deterministic file barrier); return their evidence payloads."""
    import os
    import shutil
    import subprocess
    import sys

    shutil.rmtree(_RESULTS_DIR, ignore_errors=True)
    _RESULTS_DIR.mkdir(parents=True)
    worker_script = Path(__file__).parent / "_i8_mp_worker.py"
    barrier_dir = _RESULTS_DIR / "barrier"
    specs = []
    for i in (1, 2):
        results_path = _RESULTS_DIR / f"p{i}.json"
        spec = {
            "ctx": dict(ctx),
            "results_path": str(results_path),
            "publish_behavior": publish_behavior,
            "barrier_dir": str(barrier_dir),
            "worker_name": f"w{i}",
            "barrier_others": [f"w{j}" for j in (1, 2) if j != i],
        }
        spec_path = _RESULTS_DIR / f"spec{i}.json"
        spec_path.write_text(json.dumps(spec))
        specs.append(spec_path)

    env = dict(os.environ)
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker_script), str(spec_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for spec_path in specs
    ]
    for p in procs:
        try:
            rc = p.wait(timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            raise
        assert rc == 0, f"worker exited {rc}"
    return [json.loads((_RESULTS_DIR / f"p{i}.json").read_text()) for i in (1, 2)]


# ---------------------------------------------------------------------------
# Parent-side helpers (seeding + DB reads)
# ---------------------------------------------------------------------------


def _seed():
    from tests._dispatch_manifest_fixtures import seed_manifest_bound_target

    return seed_manifest_bound_target(
        platform="postiz",
        social_platform="youtube",
        integration_id="integ-1",
        privacy_status="public",
        publish_type="now",
    )


def _cleanup(seeded):
    from tests._dispatch_manifest_fixtures import cleanup_manifest_bound_target

    run_id, video_id, _mid, vpath, _thumb = seeded
    cleanup_manifest_bound_target(run_id, video_id, vpath, _thumb)


def _ctx(seeded):
    run_id, video_id, _mid, vpath, _thumb = seeded
    return {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": vpath,
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "workflow_run_id": str(run_id),
        "dry_run": False,
    }


def _attempts(video_uuid):
    import asyncio

    async def _inner():
        from sqlalchemy import select

        from app.hermes.capabilities import _make_capability_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _make_capability_engine()
        session = async_sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            return (
                (
                    await session.execute(
                        select(PublicationAttempt).where(
                            PublicationAttempt.video_id == video_uuid
                        )
                    )
                )
                .scalars()
                .all()
            )
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _phase(label):
    """Guards: only run under an explicit opt-in (the cross-process suite
    needs a real shared Postgres reachable from child processes)."""
    import os

    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must point at the shared disposable DB"


# ===========================================================================
# 1. Competing simultaneous dispatches across processes
# ===========================================================================


def test_mp_competing_dispatches_publish_exactly_once():
    _phase("competing")
    seeded = _seed()
    try:
        one, two = _spawn_pair(_ctx(seeded), publish_behavior="ok")

        # Exactly one process completed the publication; the loser was
        # refused at admission with zero external calls of its own.
        winners = [r for r in (one, two) if r["success"]]
        losers = [r for r in (one, two) if not r["success"]]
        assert len(winners) == 1 and len(losers) == 1
        assert winners[0]["output"].get("attempt_status") == "succeeded"
        assert "pending" in losers[0]["error"] or "in progress" in losers[0]["error"]
        assert losers[0]["calls"] == []

        # Exactly ONE upload/publish sequence ever began.
        all_calls = one["calls"] + two["calls"]
        assert all_calls.count("publish") == 1
        assert all_calls.count("upload_content") == 1

        # One attempt row, SUCCEEDED, manifest-bound.
        rows = _attempts(seeded[1])
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].manifest_id == seeded[2]
    finally:
        _cleanup(seeded)


# ===========================================================================
# 2. Terminal SUCCEEDED state: competing re-dispatches are duplicates
# ===========================================================================


def test_mp_duplicate_after_success_never_republishes():
    _phase("duplicates")
    seeded = _seed()
    try:
        first = _spawn_pair(_ctx(seeded), publish_behavior="ok")
        assert sum(r["success"] for r in first) == 1

        # Both processes re-dispatch the SAME intent after SUCCEEDED.
        one, two = _spawn_pair(_ctx(seeded), publish_behavior="ok")
        assert one["success"] and two["success"]
        assert one["output"].get("duplicate") is True
        assert two["output"].get("duplicate") is True
        # Zero new external calls in the duplicate round.
        assert one["calls"] == [] and two["calls"] == []

        rows = _attempts(seeded[1])
        assert len(rows) == 1  # terminal state not overwritten, no new row
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup(seeded)


# ===========================================================================
# 3. UNKNOWN outcome: cross-process automatic retry is blocked
# ===========================================================================


def test_mp_unknown_outcome_blocks_cross_process_retry():
    _phase("unknown")
    seeded = _seed()
    try:
        one, two = _spawn_pair(_ctx(seeded), publish_behavior="raise")
        # The winner's publish raised after submission: UNKNOWN.
        outcome = [r for r in (one, two) if "UNKNOWN" in (r["error"] or "")]
        assert len(outcome) == 1
        refused = [r for r in (one, two) if r is not outcome[0]]
        assert not refused[0]["success"]
        assert refused[0]["calls"] == []

        rows = _attempts(seeded[1])
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
        assert rows[0].external_content_id == "mp-media-1"  # anchor held

        # Competing re-dispatch across processes: BOTH refused (UNKNOWN
        # is durable manual-reconciliation state; no auto-retry), and
        # the row is never overwritten.
        again_one, again_two = _spawn_pair(_ctx(seeded), publish_behavior="ok")
        for r in (again_one, again_two):
            assert not r["success"]
            assert "AMBIGUOUS" in r["error"]
            assert r["calls"] == []

        rows = _attempts(seeded[1])
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
    finally:
        _cleanup(seeded)
