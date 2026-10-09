"""Publication-attempt operator reconciliation surface.

Proves the operator slice against the REAL service, REAL router (via the
real FastAPI app + ASGI transport, Bearer-authenticated), REAL Postgres,
and the REAL PostizAdapter decision logic (only the httpx transport in
the postiz module is scripted, using real httpx exceptions/responses):

- explicit transition matrix + illegal transitions (typed refusals)
- UNKNOWN -> SUCCEEDED requires the external post id AND fail-closed
  in-resolve provider verification (check_processing must say "ready")
- UNKNOWN -> FAILED requires an explicit operator attestation; the
  original error text is preserved (no silent history overwrite)
- PENDING/IN_PROGRESS -> FAILED requires force + attestation + the
  active-execution staleness floor (never under a live execution)
- CAS/concurrency: exactly one resolution wins; from-status mismatch
  refuses; immutable PublicationAttemptResolved SystemLog audit events
- authentication (401) on all three endpoints
- credential non-persistence across responses, attempt columns, audit
- Postiz evidence lookup: ready / processing / not-found-no-match
  (failed) / not-found-fallback-match (ready) / server-error (unknown)
- end-to-end: UNKNOWN -> resolve(FAILED) -> retry admitted as n+1, and
  UNKNOWN -> resolve(SUCCEEDED) -> duplicate guard engages with no
  second provider publish
- H2: evidence-based IN_PROGRESS -> SUCCEEDED (external post id +
  fail-closed in-resolve provider verification + active-execution
  floor; PENDING -> SUCCEEDED stays illegal)
- H1 races: an operator resolution can never be resurrected by a late
  agent transition (CAS on both sides), and a refused publication
  permit blocks the irreversible external publish call end-to-end
"""
import asyncio
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _synthetic_auth(synthetic_api_key: str):
    """Phase 48B: every test in this module authenticates with the shared
    synthetic credential (the cached Settings object is patched, so the
    app's Bearer validation and the _http helper below both see it). The
    live ARYA_API_KEY is never read or transmitted."""
    return synthetic_api_key

from app.agents.publishing import PublishingAgent
from app.core.config import get_settings
from app.main import app
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt  # registers the table
from app.models.system import SystemLog
from app.platforms.postiz import PostizAdapter
from app.services import publication_attempt_reconciliation as recon
from app.services.publication_attempts import (
    admit_attempt,
    mark_failed,
    mark_in_progress,
    mark_succeeded,
    mark_unknown,
)

SECRET_MARKER = "SECRET-DO-NOT-PERSIST"


class _FakeSecrets:
    def get(self, key, required=False):
        return f"test-{SECRET_MARKER}" if key == "postiz_api_key" else None


class _ScriptedPostizClient:
    """httpx.AsyncClient stand-in installed ONLY into the postiz module's
    `httpx` reference (the app's own httpx usage is unaffected)."""

    def __init__(self, script, **kwargs):
        self._script = script

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, **kwargs):
        return self._script.get(url, **kwargs)

    async def post(self, url, **kwargs):
        return self._script.post(url, **kwargs)


class _PostizHttpxShim:
    """Exposes real httpx exception/Response classes but a scripted
    AsyncClient factory, so the REAL PostizAdapter logic runs."""

    def __init__(self, script):
        self.AsyncClient = lambda **kwargs: _ScriptedPostizClient(script, **kwargs)
        for name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException"):
            setattr(self, name, getattr(httpx, name))


class _PostizScript:
    """Scripts GET /posts/{id} (check_processing), POST /upload, POST /posts."""

    def __init__(self, *, check="ready", upload=("ok", "media-1"), publish=("ok", "post-1")):
        self.check = check
        self.upload = upload
        self.publish = publish
        self.posts_calls = 0

    def get(self, url, **kwargs):
        if "/public/v1/posts" not in url:
            # integrations lookup (authenticate)
            return httpx.Response(200, json=[{"id": "integ-1"}], request=httpx.Request("GET", url))
        is_fallback_list = url.endswith("/public/v1/posts") or "startDate" in kwargs.get("params", {})
        if is_fallback_list:
            if self.check == "notfound_match":
                return httpx.Response(
                    200,
                    json={"posts": [{"id": "media-1", "state": "published"}]},
                    request=httpx.Request("GET", url),
                )
            if self.check == "notfound_draft_match":
                # F-02a fixture: matched DRAFT post in the 30-day list —
                # non-public evidence (processing since d719df4).
                return httpx.Response(
                    200,
                    json={"posts": [{"id": "media-1", "state": "draft"}]},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(200, json={"posts": []}, request=httpx.Request("GET", url))
        # specific-post status lookup
        if self.check == "ready":
            return httpx.Response(200, json={"id": "x", "status": "published"}, request=httpx.Request("GET", url))
        if self.check == "processing":
            return httpx.Response(200, json={"status": "processing"}, request=httpx.Request("GET", url))
        if self.check == "server_error":
            return httpx.Response(500, text="boom", request=httpx.Request("GET", url))
        # notfound_nomatch / notfound_match specific lookup -> 404
        return httpx.Response(404, request=httpx.Request("GET", url))

    async def aget(self, url, **kwargs):
        return self.get(url, **kwargs)

    def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            kind, payload = self.upload
        else:
            self.posts_calls += 1
            kind, payload = self.publish
        if kind == "raise":
            raise payload
        if kind == "status":
            return httpx.Response(payload, text="scripted", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"id": payload}, request=httpx.Request("POST", url))


def _install_real_postiz(monkeypatch, script):
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr("app.platforms.postiz.httpx", _PostizHttpxShim(script))


# ---------------------------------------------------------------------------
# DB helpers (fresh disposable engines, same pattern as the attempt suites)
# ---------------------------------------------------------------------------


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


async def _attempts_for(video_uuid):
    from sqlalchemy import select

    engine, session = await _session()
    try:
        rows = (
            (
                await session.execute(
                    select(PublicationAttempt)
                    .where(PublicationAttempt.video_id == video_uuid)
                    .order_by(PublicationAttempt.attempt_number)
                )
            )
            .scalars()
            .all()
        )
        return rows
    finally:
        await session.close()
        await engine.dispose()


async def _audit_for(attempt_id):
    from sqlalchemy import select

    engine, session = await _session()
    try:
        rows = (
            (
                await session.execute(
                    select(SystemLog).where(
                        SystemLog.event_type == "PublicationAttemptResolved",
                        SystemLog.message.contains(str(attempt_id)),
                    )
                )
            )
            .scalars()
            .all()
        )
        return rows
    finally:
        await session.close()
        await engine.dispose()


async def _cleanup(video_uuid, attempt_ids=()):
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        await session.execute(delete(PublicationAttempt).where(PublicationAttempt.video_id == video_uuid))
        for aid in attempt_ids:
            await session.execute(
                delete(SystemLog).where(
                    SystemLog.event_type == "PublicationAttemptResolved",
                    SystemLog.message.contains(str(aid)),
                )
            )
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


async def _make_attempt(status, *, anchor=False, video_uuid=None):
    """Admit an attempt for a fresh video (or the GIVEN video — Phase
    54B-I8: the manifest-bound seeded target's video) and drive it to
    `status` via the REAL transition helpers (admission algorithm
    untouched)."""
    if video_uuid is None:
        video_uuid = uuid.uuid4()
    engine, session = await _session()
    try:
        attempt, _ = await admit_attempt(
            session,
            video_id=video_uuid,
            platform="postiz",
            social_platform="youtube",
            integration_id="integ-1",
        )
        if anchor:
            attempt.external_content_id = "media-1"
            await session.commit()
        if status == PublicationAttemptStatus.IN_PROGRESS:
            await mark_in_progress(session, attempt)
        elif status == PublicationAttemptStatus.UNKNOWN:
            if anchor:
                attempt.external_content_id = "media-1"
                await session.commit()
            await mark_unknown(session, attempt, "publish exception: ReadTimeout")
        elif status == PublicationAttemptStatus.FAILED:
            await mark_failed(session, attempt, "publish rejected: scripted")
        elif status == PublicationAttemptStatus.SUCCEEDED:
            # Real execution shape under the H1 CAS: the permit first,
            # then the confirmed-success transition.
            await mark_in_progress(session, attempt)
            await mark_succeeded(session, attempt, external_post_id="post-1")
        return attempt.id, video_uuid
    finally:
        await session.close()
        await engine.dispose()


async def _age_attempt(attempt_id, hours=1):
    from sqlalchemy import update

    engine, session = await _session()
    try:
        await session.execute(
            update(PublicationAttempt)
            .where(PublicationAttempt.id == attempt_id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=hours))
        )
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


def _svc_resolve(attempt_id, **kwargs):
    async def _inner():
        engine, session = await _session()
        try:
            return await recon.resolve_attempt(session, attempt_id, **kwargs)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _ctx(video_id):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        # Phase 54B-I8: the seeded manifest's authoritative artifact.
        "video_storage_path": _SEED_STATE.get("asset") or _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "workflow_run_id": (
            str(_SEED_STATE["run_id"]) if _SEED_STATE.get("run_id") else None
        ),
        "dry_run": False,
    }
    return base


# ---------------------------------------------------------------------------
# Phase 54B-I8: manifest-bound approved publish-target seeding (the
# minimum authorization state the 53B/I5 dispatch contract accepts).
# ---------------------------------------------------------------------------

_SEED_STATE = {}


def _seed_target():
    from tests._dispatch_manifest_fixtures import seed_manifest_bound_target

    run_id, video_id, _mid, vpath, _thumb = seed_manifest_bound_target(
        platform="postiz",
        social_platform="youtube",
        integration_id="integ-1",
        privacy_status="public",
        publish_type="now",
    )
    _SEED_STATE.clear()
    _SEED_STATE.update(run_id=run_id, video_id=video_id, asset=vpath)
    return run_id, video_id


def _cleanup_target():
    from tests._dispatch_manifest_fixtures import cleanup_manifest_bound_target

    if _SEED_STATE.get("run_id") is not None:
        cleanup_manifest_bound_target(
            _SEED_STATE["run_id"], _SEED_STATE["video_id"], _SEED_STATE["asset"]
        )
    _SEED_STATE.clear()


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-recon-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


def _run_agent(ctx):
    async def _inner():
        engine, session = await _session()
        try:
            return await PublishingAgent(db=session).run(ctx)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# HTTP helpers (real app, ASGI transport, Bearer auth)
# ---------------------------------------------------------------------------


def _http(method, path, payload=None, auth=True):
    async def _inner():
        from httpx import ASGITransport
        from app.database.session import engine

        settings = get_settings()
        # Phase 48B: the module autouse _synthetic_auth fixture has pinned
        # this to the shared synthetic credential — never the live key.
        key = settings.arya_api_key
        headers = {"Authorization": f"Bearer {key}"} if auth else {}
        try:
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                    headers=headers,
                ) as ac:
                    r = await ac.request(method, path, json=payload)
                    try:
                        body = r.json()
                    except Exception:  # non-JSON error bodies tolerated
                        body = {"raw": r.text}
                    return r.status_code, body
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# 1. Transition matrix + illegal transitions (service level, typed errors)
# ---------------------------------------------------------------------------


def test_illegal_transitions_refused(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    made = []
    try:
        # SUCCEEDED is terminal
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.SUCCEEDED))
        made.append((aid, vu))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid, from_status=PublicationAttemptStatus.SUCCEEDED, to_status=PublicationAttemptStatus.FAILED, attestation="a", force=True)

        # FAILED is not resolvable (admission already handles retry)
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.FAILED))
        made.append((aid, vu))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid, from_status=PublicationAttemptStatus.FAILED, to_status=PublicationAttemptStatus.FAILED, attestation="a", force=True)

        # PENDING -> SUCCEEDED is illegal
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.PENDING))
        made.append((aid, vu))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid, from_status=PublicationAttemptStatus.PENDING, to_status=PublicationAttemptStatus.SUCCEEDED, external_post_id="p1")

        # UNKNOWN -> SUCCEEDED without the external post id
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
        made.append((aid, vu))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid, from_status=PublicationAttemptStatus.UNKNOWN, to_status=PublicationAttemptStatus.SUCCEEDED)

        # UNKNOWN -> FAILED without an attestation
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid, from_status=PublicationAttemptStatus.UNKNOWN, to_status=PublicationAttemptStatus.FAILED)

        # PENDING -> FAILED without force / without attestation
        aid2, vu2 = asyncio.run(_make_attempt(PublicationAttemptStatus.PENDING))
        made.append((aid2, vu2))
        asyncio.run(_age_attempt(aid2, hours=1))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid2, from_status=PublicationAttemptStatus.PENDING, to_status=PublicationAttemptStatus.FAILED, attestation="a")
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(aid2, from_status=PublicationAttemptStatus.PENDING, to_status=PublicationAttemptStatus.FAILED, force=True)
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_active_execution_floor_blocks_fresh_pending_and_in_progress(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    made = []
    try:
        for status in (PublicationAttemptStatus.PENDING, PublicationAttemptStatus.IN_PROGRESS):
            aid, vu = asyncio.run(_make_attempt(status))
            made.append((aid, vu))
            with pytest.raises(recon.ActiveExecutionError):
                _svc_resolve(
                    aid,
                    from_status=status,
                    to_status=PublicationAttemptStatus.FAILED,
                    attestation="operator verified crash",
                    force=True,
                )
            # After the floor passes (row untouched for 1h) the same
            # resolution succeeds.
            asyncio.run(_age_attempt(aid, hours=1))
            attempt, _audit = _svc_resolve(
                aid,
                from_status=status,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="operator verified crash",
                force=True,
            )
            assert attempt.status == PublicationAttemptStatus.FAILED
            events = asyncio.run(_audit_for(aid))
            assert len(events) == 1
            assert json.loads(events[0].message)["to_status"] == "failed"
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_unknown_to_failed_requires_attestation_and_preserves_error(monkeypatch):
    # F-02a: non-public fixture evidence — this test exercises the
    # attestation contract, not evidence gating.
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified in provider console: no post exists for media-1",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
        # No silent history overwrite: the UNKNOWN reason is preserved.
        assert "ReadTimeout" in (attempt.error or "")
        assert audit["attestation"].startswith("verified in provider console")
        assert len(asyncio.run(_audit_for(aid))) == 1
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 2. UNKNOWN -> SUCCEEDED: fail-closed provider verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("check_script", ["processing", "server_error", "notfound_nomatch"])
def test_unknown_to_succeeded_fails_closed_without_ready_evidence(monkeypatch, check_script):
    _install_real_postiz(monkeypatch, _PostizScript(check=check_script))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        with pytest.raises(recon.VerificationFailedError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="post-9",
            )
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN  # unchanged
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_unknown_to_succeeded_requires_anchor(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=False))
    try:
        with pytest.raises(recon.MissingAnchorError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="post-9",
            )
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_unknown_to_succeeded_with_verified_evidence(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.SUCCEEDED,
            external_post_id="post-9",
            public_url="https://social.example/watch/post-9",
        )
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert attempt.external_post_id == "post-9"
        assert attempt.public_url == "https://social.example/watch/post-9"
        assert audit["verification"]["provider_status"] == "ready"
        events = asyncio.run(_audit_for(aid))
        assert len(events) == 1
        assert json.loads(events[0].message)["from_status"] == "unknown"
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 3. CAS / concurrency
# ---------------------------------------------------------------------------


def test_cas_refuses_on_from_status_mismatch(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.FAILED))
    try:
        with pytest.raises(recon.ConcurrentResolutionError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="stale operator view",
            )
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_concurrent_resolutions_exactly_one_wins(monkeypatch):
    # F-02a: non-public fixture evidence — this test exercises the CAS
    # arbitration, not evidence gating.
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))

    async def _one():
        engine, session = await _session()
        try:
            return await recon.resolve_attempt(
                session,
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="concurrent operator 1",
            )
        except recon.ConcurrentResolutionError:
            return "lost"
        finally:
            await session.close()
            await engine.dispose()

    async def _race():
        return await asyncio.gather(_one(), _one())

    try:
        outcomes = asyncio.run(_race())
        losers = [o for o in outcomes if o == "lost"]
        winners = [o for o in outcomes if o != "lost"]
        assert len(losers) == 1 and len(winners) == 1
        assert winners[0][0].status == PublicationAttemptStatus.FAILED
        assert len(asyncio.run(_audit_for(aid))) == 1  # exactly one audit event
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 4. Authentication / authorization (HTTP)
# ---------------------------------------------------------------------------


def test_endpoints_require_bearer_auth():
    for method, path in (
        ("get", "/publishing/attempts"),
        ("get", "/publishing/attempts/00000000-0000-0000-0000-000000000000/evidence"),
        ("post", "/publishing/attempts/00000000-0000-0000-0000-000000000000/resolve"),
    ):
        status_code, _ = _http(method, path, auth=False)
        assert status_code == 401, (method, path, status_code)


# ---------------------------------------------------------------------------
# 5. HTTP surface: listing, evidence, resolve
# ---------------------------------------------------------------------------


def test_list_attempts_filters_by_status(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        status_code, body = _http("get", "/publishing/attempts?status=unknown&limit=200")
        assert status_code == 200
        mine = [a for a in body if a["id"] == str(aid)]
        assert len(mine) == 1 and mine[0]["status"] == "unknown"
        status_code, _ = _http("get", "/publishing/attempts?status=not-a-status")
        assert status_code == 422
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_evidence_endpoint_real_postiz_ready_processing_unknown_404(monkeypatch):
    made = []
    try:
        # ready
        _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
        made.append((aid, vu))
        status_code, body = _http("get", f"/publishing/attempts/{aid}/evidence")
        assert status_code == 200 and body["provider_status"] == "ready"
        assert body["attempt_status"] == "unknown"

        # processing
        _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
        status_code, body = _http("get", f"/publishing/attempts/{aid}/evidence")
        assert status_code == 200 and body["provider_status"] == "processing"

        # server error -> provider "unknown" with error text
        _install_real_postiz(monkeypatch, _PostizScript(check="server_error"))
        status_code, body = _http("get", f"/publishing/attempts/{aid}/evidence")
        assert status_code == 200 and body["provider_status"] == "unknown"
        assert "500" in (body["provider_error"] or "")

        # 404 with no fallback match -> provider "failed" (post not found)
        _install_real_postiz(monkeypatch, _PostizScript(check="notfound_nomatch"))
        status_code, body = _http("get", f"/publishing/attempts/{aid}/evidence")
        assert status_code == 200 and body["provider_status"] == "failed"

        # 404 with fallback match -> "ready"
        _install_real_postiz(monkeypatch, _PostizScript(check="notfound_match"))
        status_code, body = _http("get", f"/publishing/attempts/{aid}/evidence")
        assert status_code == 200 and body["provider_status"] == "ready"

        # missing anchor -> 409; unknown id -> 404
        aid2, vu2 = asyncio.run(_make_attempt(PublicationAttemptStatus.PENDING))
        made.append((aid2, vu2))
        status_code, _ = _http("get", f"/publishing/attempts/{aid2}/evidence")
        assert status_code == 409
        status_code, _ = _http("get", f"/publishing/attempts/{uuid.uuid4()}/evidence")
        assert status_code == 404
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_resolve_endpoint_http_paths(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        # illegal transition -> 422 (missing attestation)
        status_code, body = _http(
            "post",
            f"/publishing/attempts/{aid}/resolve",
            {"from_status": "unknown", "to_status": "failed"},
        )
        assert status_code == 422

        # verification fail-closed -> 409 (provider says processing)
        _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
        status_code, body = _http(
            "post",
            f"/publishing/attempts/{aid}/resolve",
            {"from_status": "unknown", "to_status": "succeeded", "external_post_id": "post-9"},
        )
        assert status_code == 409

        # attested UNKNOWN -> FAILED -> 200
        status_code, body = _http(
            "post",
            f"/publishing/attempts/{aid}/resolve",
            {"from_status": "unknown", "to_status": "failed", "attestation": "verified no post"},
        )
        assert status_code == 200 and body["status"] == "failed"

        # now FAILED -> not resolvable
        status_code, _ = _http(
            "post",
            f"/publishing/attempts/{aid}/resolve",
            {"from_status": "failed", "to_status": "failed", "attestation": "x", "force": True},
        )
        assert status_code == 422
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 6. Credential non-persistence
# ---------------------------------------------------------------------------


def test_credentials_never_persist_or_leak(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        _, evidence_body = _http("get", f"/publishing/attempts/{aid}/evidence")
        _, resolve_body = _http(
            "post",
            f"/publishing/attempts/{aid}/resolve",
            {"from_status": "unknown", "to_status": "succeeded", "external_post_id": "post-9"},
        )
        rows = asyncio.run(_attempts_for(vu))
        events = asyncio.run(_audit_for(aid))
        for blob in (
            json.dumps(evidence_body),
            json.dumps(resolve_body),
            json.dumps([e.message for e in events]),
        ):
            assert SECRET_MARKER not in blob
        for attempt in rows:
            for column in (
                "platform", "social_platform", "integration_id", "intent_key",
                "external_content_id", "external_post_id", "public_url", "error",
            ):
                assert SECRET_MARKER not in str(getattr(attempt, column) or "")
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 7. End-to-end: UNKNOWN -> resolve -> duplicate guard / retry as n+1
# ---------------------------------------------------------------------------


def test_e2e_unknown_resolved_failed_then_retry_admitted_as_n_plus_1(monkeypatch):
    # F-02a: non-public fixture evidence — this e2e exercises the
    # resolve(FAILED) -> retry-as-n+1 flow, not evidence gating.
    script = _PostizScript(
        check="processing", publish=("raise", httpx.ReadTimeout("dropped after submit"))
    )
    _install_real_postiz(monkeypatch, script)
    _, video_uuid = _seed_target()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" in first.error
        assert script.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        attempt_id = rows[0].id

        # Operator resolves UNKNOWN -> FAILED with attestation.
        status_code, body = _http(
            "post",
            f"/publishing/attempts/{attempt_id}/resolve",
            {"from_status": "unknown", "to_status": "failed", "attestation": "provider console shows no post"},
        )
        assert status_code == 200 and body["status"] == "failed"

        # The retry is admitted as attempt n+1 and succeeds.
        script.publish = ("ok", "post-42")
        second = _run_agent(ctx)
        assert second.success, second.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        assert script.posts_calls == 2  # exactly one legitimate retry
    finally:
        _cleanup_target()
        asyncio.run(_cleanup(video_uuid))


def test_e2e_unknown_resolved_succeeded_duplicate_guard_engages(monkeypatch):
    script = _PostizScript(check="ready", publish=("raise", httpx.ReadTimeout("dropped after submit")))
    _install_real_postiz(monkeypatch, script)
    _, video_uuid = _seed_target()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        attempt_id = rows[0].id
        posts_after_first = script.posts_calls

        # Evidence confirms the provider DID accept the post.
        status_code, evidence = _http("get", f"/publishing/attempts/{attempt_id}/evidence")
        assert status_code == 200 and evidence["provider_status"] == "ready"

        # Operator resolves UNKNOWN -> SUCCEEDED with the external post id.
        status_code, body = _http(
            "post",
            f"/publishing/attempts/{attempt_id}/resolve",
            {
                "from_status": "unknown",
                "to_status": "succeeded",
                "external_post_id": "post-77",
                "public_url": "https://social.example/watch/post-77",
            },
        )
        assert status_code == 200 and body["status"] == "succeeded"

        # Re-submission of the identical intent is an idempotent duplicate:
        # NO second provider publish, NO new attempt row.
        second = _run_agent(ctx)
        assert second.success and second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "post-77"
        assert script.posts_calls == posts_after_first
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup(video_uuid))


# ---------------------------------------------------------------------------
# 8. H2: evidence-based IN_PROGRESS -> SUCCEEDED
# ---------------------------------------------------------------------------


def test_in_progress_to_succeeded_refusals(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    made = []
    try:
        # PENDING -> SUCCEEDED remains illegal (no irreversible external
        # call was ever made from PENDING).
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.PENDING))
        made.append((aid, vu))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.PENDING,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="p1",
            )

        # IN_PROGRESS -> SUCCEEDED requires the external post id.
        aid, vu = asyncio.run(
            _make_attempt(PublicationAttemptStatus.IN_PROGRESS, anchor=True)
        )
        made.append((aid, vu))
        asyncio.run(_age_attempt(aid, hours=1))
        with pytest.raises(recon.IllegalTransitionError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
            )

        # Fresh row: the active-execution floor still applies.
        aid, vu = asyncio.run(
            _make_attempt(PublicationAttemptStatus.IN_PROGRESS, anchor=True)
        )
        made.append((aid, vu))
        with pytest.raises(recon.ActiveExecutionError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="p1",
            )

        # Missing anchor: nothing to verify against.
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.IN_PROGRESS))
        made.append((aid, vu))
        asyncio.run(_age_attempt(aid, hours=1))
        with pytest.raises(recon.MissingAnchorError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="p1",
            )
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


@pytest.mark.parametrize("check_script", ["processing", "server_error", "notfound_nomatch"])
def test_in_progress_to_succeeded_fails_closed_without_ready_evidence(monkeypatch, check_script):
    _install_real_postiz(monkeypatch, _PostizScript(check=check_script))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.IN_PROGRESS, anchor=True))
    asyncio.run(_age_attempt(aid, hours=1))
    try:
        with pytest.raises(recon.VerificationFailedError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="post-9",
            )
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.IN_PROGRESS  # unchanged
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_in_progress_to_succeeded_with_verified_evidence(monkeypatch):
    """The H2 crash window: the provider accepted the publication, the
    execution died before persisting SUCCEEDED (row stale IN_PROGRESS
    with its upload anchor); verified evidence resolves it, the audit
    records the verification, and the duplicate guard engages on
    re-submission (no second external publication)."""
    script = _PostizScript(check="ready")
    _install_real_postiz(monkeypatch, script)
    # I8: the crash-window attempt belongs to a real manifest-bound
    # target so the duplicate re-submission crosses the 53B/I5 gates.
    _, vu = _seed_target()
    aid, _ = asyncio.run(
        _make_attempt(
            PublicationAttemptStatus.IN_PROGRESS, anchor=True, video_uuid=vu
        )
    )
    asyncio.run(_age_attempt(aid, hours=1))
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.IN_PROGRESS,
            to_status=PublicationAttemptStatus.SUCCEEDED,
            external_post_id="post-8",
            public_url="https://social.example/watch/post-8",
        )
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert attempt.external_post_id == "post-8"
        assert attempt.public_url == "https://social.example/watch/post-8"
        assert audit["from_status"] == "in_progress"
        assert audit["verification"]["provider_status"] == "ready"
        events = asyncio.run(_audit_for(aid))
        assert len(events) == 1
        assert json.loads(events[0].message)["from_status"] == "in_progress"

        # Re-submission of the identical intent: idempotent duplicate.
        second = _run_agent(_ctx(vu))
        assert second.success and second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "post-8"
        assert script.posts_calls == 0  # no second external publication
    finally:
        _cleanup_target()
        asyncio.run(_cleanup(vu, (aid,)))


# ---------------------------------------------------------------------------
# 9. H1 races: an operator resolution can never be resurrected by a
#    late agent transition
# ---------------------------------------------------------------------------


def _late_agent_transition(attempt_id, kind, **kwargs):
    """The crashed execution waking up AFTER the operator resolution and
    firing its next bookkeeping transition through the REAL helper."""

    async def _inner():
        from sqlalchemy import select

        from app.services.publication_attempts import (
            mark_failed,
            mark_in_progress,
            mark_succeeded,
            mark_unknown,
        )

        engine, session = await _session()
        try:
            obj = (
                (
                    await session.execute(
                        select(PublicationAttempt).where(PublicationAttempt.id == attempt_id)
                    )
                )
                .scalars()
                .one()
            )
            if kind == "succeeded":
                return await mark_succeeded(session, obj, **kwargs)
            if kind == "unknown":
                return await mark_unknown(session, obj, kwargs["reason"])
            if kind == "failed":
                return await mark_failed(session, obj, kwargs["error"])
            return await mark_in_progress(session, obj)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def test_race_operator_failed_resolution_survives_late_agent_success(monkeypatch):
    """Operator force-fails a stale IN_PROGRESS attempt; the crashed
    execution then wakes up after its publish call and fires
    mark_succeeded — the CAS refuses: the FAILED resolution stands, no
    external ids are written, exactly one audit event exists."""
    # F-02a: non-public fixture evidence — this test exercises the H1
    # race guarantee, not evidence gating.
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.IN_PROGRESS, anchor=True))
    asyncio.run(_age_attempt(aid, hours=1))
    try:
        attempt, _audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.IN_PROGRESS,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="operator verified crash: no post exists",
            force=True,
        )
        assert attempt.status == PublicationAttemptStatus.FAILED

        applied = _late_agent_transition(
            aid,
            "succeeded",
            external_post_id="post-late",
            public_url="https://social.example/watch/post-late",
        )
        assert applied is False

        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.FAILED  # not resurrected
        assert rows[0].external_post_id is None
        assert rows[0].public_url is None
        assert len(asyncio.run(_audit_for(aid))) == 1
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_race_operator_succeeded_resolution_survives_late_agent_unknown(monkeypatch):
    """Operator resolves UNKNOWN -> SUCCEEDED on verified evidence; the
    execution's delayed publish-exception handler then fires
    mark_unknown — the CAS refuses: SUCCEEDED stands with the
    operator-recorded external ids intact."""
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        attempt, _ = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.SUCCEEDED,
            external_post_id="post-9",
        )
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED

        applied = _late_agent_transition(
            aid, "unknown", reason="late publish exception: ReadTimeout"
        )
        assert applied is False

        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED  # not resurrected
        assert rows[0].external_post_id == "post-9"  # operator data intact
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_race_operator_force_fail_blocks_irreversible_publish_permit(monkeypatch):
    """End-to-end through the REAL agent: a stalled execution (attempt
    admitted, then untouched for an hour) is force-failed by the
    operator mid-flight; when the execution resumes, its publication
    permit (PENDING -> IN_PROGRESS CAS) is REFUSED and the irreversible
    external publish call is never made."""
    script = _PostizScript(check="ready", publish=("ok", "post-late"))
    _install_real_postiz(monkeypatch, script)
    _, video_uuid = _seed_target()

    real_resolve = recon.resolve_attempt

    async def _operator_force_fails_mid_flight(path, **kwargs):
        """I8: hooks the manifest-snapshot artifact resolution (the first
        post-admission step) — the operator force-fails the stalled
        PENDING row before the permit CAS can run."""
        from sqlalchemy import select, update

        from app.utils.asset_manager import ensure_local_asset as _real

        engine, session = await _session()
        try:
            row = (
                (
                    await session.execute(
                        select(PublicationAttempt).where(
                            PublicationAttempt.video_id == video_uuid
                        )
                    )
                )
                .scalars()
                .one()
            )
            # The stalled execution's row is an hour old.
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.id == row.id)
                .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await session.commit()
            await real_resolve(
                session,
                row.id,
                from_status=PublicationAttemptStatus.PENDING,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="operator verified: execution stalled before publish",
                force=True,
            )
        finally:
            await session.close()
            await engine.dispose()
        return await _real(path, **kwargs) if path is not None else None

    monkeypatch.setattr(
        "app.services.publication_manifest_service.ensure_local_asset",
        _operator_force_fails_mid_flight,
    )
    try:
        result = _run_agent(_ctx(video_uuid))
        assert not result.success
        assert "permit" in result.error.lower()
        assert "failed" in result.error  # the refreshed (operator-resolved) status
        assert script.posts_calls == 0  # the irreversible publish NEVER happened
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.FAILED
        assert rows[0].external_post_id is None
    finally:
        _cleanup_target()
        asyncio.run(_cleanup(video_uuid))


# ---------------------------------------------------------------------------
# 10. F-02a: evidence-gated FAILED resolutions (one-sided)
# ---------------------------------------------------------------------------


def test_f02a_postiz_anchored_ready_refuses_failed_resolution(monkeypatch):
    """Matrix 7 + 11a: anchored Postiz attempt whose provider evidence is
    'ready' (post state published) — the FAILED resolution is REFUSED
    (the attestation is contradicted); nothing is written, no audit
    event exists, the attempt is unchanged. Both UNKNOWN and aged
    IN_PROGRESS sources."""
    made = []
    try:
        for status, age in (
            (PublicationAttemptStatus.UNKNOWN, False),
            (PublicationAttemptStatus.IN_PROGRESS, True),
        ):
            _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
            aid, vu = asyncio.run(_make_attempt(status, anchor=True))
            made.append((aid, vu))
            if age:
                asyncio.run(_age_attempt(aid, hours=1))
            with pytest.raises(recon.VerificationFailedError) as excinfo:
                _svc_resolve(
                    aid,
                    from_status=status,
                    to_status=PublicationAttemptStatus.FAILED,
                    attestation="operator believes no post exists",
                    force=age,
                )
            assert "publicly live" in str(excinfo.value)
            rows = asyncio.run(_attempts_for(vu))
            assert rows[0].status == status  # unchanged
            assert rows[0].external_post_id is None
            assert len(asyncio.run(_audit_for(aid))) == 0  # nothing written
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_postiz_non_public_evidence_allows_failed(monkeypatch):
    """Matrix 8: anchored Postiz attempt with non-public evidence —
    processing (direct), and draft via the 404/list fallback (mapped to
    processing since d719df4) — the attestation stays authoritative."""
    made = []
    try:
        # Direct lookup: processing.
        _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
        made.append((aid, vu))
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified no public post",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
        assert audit["verification"] == {
            "gate": "failed_resolution_evidence",
            "provider_status": "processing",
        }

        # Fallback branch: matched DRAFT post -> processing (not ready).
        _install_real_postiz(monkeypatch, _PostizScript(check="notfound_draft_match"))
        aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
        made.append((aid, vu))
        attempt, _ = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified draft was never published",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_postiz_unavailable_or_notfound_evidence_allows_failed(monkeypatch):
    """Matrix 9: anchored Postiz attempt where evidence is unavailable
    (server error -> adapter 'unknown') or not-found-no-match (adapter
    'failed', e.g. media-id addressing) — the attestation stays
    authoritative; provider availability is never a prerequisite."""
    made = []
    try:
        for check_script in ("server_error", "notfound_nomatch"):
            _install_real_postiz(monkeypatch, _PostizScript(check=check_script))
            aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
            made.append((aid, vu))
            attempt, audit = _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="verified no public post",
            )
            assert attempt.status == PublicationAttemptStatus.FAILED
            assert audit["verification"]["gate"] == "failed_resolution_evidence"
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_evidence_adapter_failure_allows_failed(monkeypatch):
    """Matrix 6/9 (hard-failure variant): the evidence lookup itself
    raising (adapter construction/transport failure) never blocks the
    manual FAILED resolution."""

    def _broken_get_platform_adapter(platform, db, secrets=None):
        raise RuntimeError("provider adapter unavailable")

    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        _broken_get_platform_adapter,
    )
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.UNKNOWN, anchor=True))
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified no public post",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
        assert audit["verification"] == {
            "gate": "failed_resolution_evidence",
            "provider_status": None,
        }
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_unanchored_attempt_makes_no_provider_call(monkeypatch):
    """Matrix 10 + 11b: unanchored attempts keep today's behavior with
    ZERO provider calls (publish was never dispatchable — the
    attestation is mechanically sound)."""

    def _forbidden_adapter(platform, db, secrets=None):
        raise AssertionError("evidence gate must not call the provider for unanchored attempts")

    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        _forbidden_adapter,
    )
    made = []
    try:
        for status, age in (
            (PublicationAttemptStatus.UNKNOWN, False),
            (PublicationAttemptStatus.PENDING, True),
            (PublicationAttemptStatus.IN_PROGRESS, True),
        ):
            aid, vu = asyncio.run(_make_attempt(status, anchor=False))
            made.append((aid, vu))
            if age:
                asyncio.run(_age_attempt(aid, hours=1))
            attempt, audit = _svc_resolve(
                aid,
                from_status=status,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="no post could exist (never dispatched)",
                force=age,
            )
            assert attempt.status == PublicationAttemptStatus.FAILED
            assert audit["verification"] == {}  # gate did not run
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_aged_in_progress_non_public_evidence_allows_failed(monkeypatch):
    """Matrix 12: anchored, aged IN_PROGRESS force-fail with non-public
    evidence — the full existing guard chain (floor/force/attestation)
    plus the gate's fall-through."""
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = asyncio.run(_make_attempt(PublicationAttemptStatus.IN_PROGRESS, anchor=True))
    try:
        # Fresh row: the floor still refuses.
        with pytest.raises(recon.ActiveExecutionError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="verified no public post",
                force=True,
            )
        # Aged past the floor: non-public evidence falls through and the
        # existing guard chain (force+attestation) admits the resolution.
        asyncio.run(_age_attempt(aid, hours=1))
        attempt, _ = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.IN_PROGRESS,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified no public post",
            force=True,
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_f02a_characterization_mechanical_guarantee_vs_external_risk(monkeypatch):
    """F-02 characterization (design §9), deterministic (aging via
    updated_at, no sleeps): the complete mechanical sequence and its
    guarantee boundary — the state machine refuses every late mutation
    and admits attempt B; whether B's dispatch duplicates an external
    publication is OUTSIDE the state machine (the ratified F-02
    residual)."""
    script = _PostizScript(
        check="processing", publish=("raise", httpx.ReadTimeout("dropped after submit"))
    )
    _install_real_postiz(monkeypatch, script)
    _, video_uuid = _seed_target()
    ctx = _ctx(video_uuid)
    try:
        # A: admission -> anchor -> permit -> dispatch outcome unresolved.
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        attempt_id = rows[0].id

        # Immediate force-fail of a FRESH in-flight execution is refused
        # by the floor (separate in-flight family, same evidence script).
        inflight_vu = uuid.uuid4()

        async def _make_in_progress():
            from app.services.publication_attempts import admit_attempt, mark_in_progress

            engine, session = await _session()
            try:
                a, _ = await admit_attempt(
                    session,
                    video_id=inflight_vu,
                    platform="postiz",
                    social_platform="youtube",
                    integration_id="integ-1",
                )
                a.external_content_id = "media-1"
                await session.commit()
                assert await mark_in_progress(session, a) is True
                return a.id
            finally:
                await session.close()
                await engine.dispose()

        inflight_id = asyncio.run(_make_in_progress())
        with pytest.raises(recon.ActiveExecutionError):
            _svc_resolve(
                inflight_id,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="too early",
                force=True,
            )

        # UNKNOWN -> FAILED with non-public evidence + attestation.
        attempt, _audit = _svc_resolve(
            attempt_id,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="operator attests: no public post was created",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED

        # Late agent terminal attempts: every mutation refused.
        assert _late_agent_transition(attempt_id, "succeeded", external_post_id="post-late", public_url="u") is False
        assert _late_agent_transition(attempt_id, "unknown", reason="late") is False
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert len(asyncio.run(_audit_for(attempt_id))) == 1

        # B: admitted as n+1 — the mechanical guarantee ends here; the
        # duplicate question is about the external world.
        script.publish = ("ok", "post-B")
        second = _run_agent(ctx)
        assert second.success, second.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        assert script.posts_calls == 2  # A dispatched once; B dispatched once (structurally permitted)
    finally:
        _cleanup_target()
        asyncio.run(_cleanup(video_uuid, (attempt_id,)))
        asyncio.run(_cleanup(inflight_vu, (inflight_id,)))


# ---------------------------------------------------------------------------
# 11. F-14a: deferred-commitment-aware FAILED resolution — scheduled
# attempts require the explicit "including scheduled posts" acknowledgement
# ---------------------------------------------------------------------------


def _make_scheduled_attempt(status, *, anchor=True, scheduled_at="2030-06-01T10:00:00Z"):
    """Admit a SCHEDULED attempt for a fresh video and drive it to `status`
    via the REAL transition helpers (F-14a harness)."""

    async def _inner():
        from app.services.publication_attempts import (
            admit_attempt,
            mark_in_progress,
            mark_unknown,
        )

        video_uuid = uuid.uuid4()
        engine, session = await _session()
        try:
            attempt, _ = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id="integ-1",
                scheduled_at=scheduled_at,
            )
            if anchor:
                attempt.external_content_id = "media-1"
                await session.commit()
            if status == PublicationAttemptStatus.IN_PROGRESS:
                assert await mark_in_progress(session, attempt) is True
            elif status == PublicationAttemptStatus.UNKNOWN:
                assert await mark_unknown(session, attempt, "publish exception: ReadTimeout") is True
            return attempt.id, video_uuid
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def test_f14a_scheduled_unknown_to_failed_without_ack_is_refused(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = _make_scheduled_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        with pytest.raises(recon.IllegalTransitionError) as excinfo:
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="verified in provider console: no public post exists today",
            )
        assert "including scheduled posts" in str(excinfo.value)
        assert "SCHEDULED" in str(excinfo.value)
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN  # unchanged
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_f14a_scheduled_unknown_to_failed_with_ack_is_allowed(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = _make_scheduled_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation=(
                "verified no public post exists today and none will: the scheduled "
                "provider-side publication was cancelled with the provider — "
                "INCLUDING SCHEDULED POSTS"
            ),
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
        assert audit["verification"]["gate"] == "failed_resolution_evidence"
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_f14a_unscheduled_unknown_to_failed_is_unchanged(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    aid, vu = _make_scheduled_attempt(
        PublicationAttemptStatus.UNKNOWN, scheduled_at=None
    )
    try:
        attempt, _ = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified no public post exists",  # no ack phrase needed
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
    finally:
        asyncio.run(_cleanup(vu, (aid,)))


def test_f14a_scheduled_in_progress_force_fail_is_protected_consistently(monkeypatch):
    _install_real_postiz(monkeypatch, _PostizScript(check="processing"))
    made = []
    try:
        # Without the acknowledgement: refused (fresh or aged).
        aid, vu = _make_scheduled_attempt(PublicationAttemptStatus.IN_PROGRESS)
        made.append((aid, vu))
        asyncio.run(_age_attempt(aid, hours=1))
        with pytest.raises(recon.IllegalTransitionError) as excinfo:
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="operator verified crash: no post exists",
                force=True,
            )
        assert "including scheduled posts" in str(excinfo.value)

        # With the acknowledgement: the existing force/floor/attestation
        # chain admits the resolution.
        attempt, _ = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.IN_PROGRESS,
            to_status=PublicationAttemptStatus.FAILED,
            attestation=(
                "operator verified: the scheduled provider-side publication was "
                "cancelled with the provider — including scheduled posts"
            ),
            force=True,
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
    finally:
        for aid, vu in made:
            asyncio.run(_cleanup(vu, (aid,)))


def test_f14a_ready_evidence_still_refuses_failed_with_ack(monkeypatch):
    """Requirement 5: with the acknowledgement present, evidence proving
    the publication is publicly live still refuses FAILED exactly as
    before (F-02a semantics preserved for scheduled attempts too)."""
    _install_real_postiz(monkeypatch, _PostizScript(check="ready"))
    aid, vu = _make_scheduled_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        with pytest.raises(recon.VerificationFailedError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="including scheduled posts — but evidence says live",
            )
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
    finally:
        asyncio.run(_cleanup(vu, (aid,)))
