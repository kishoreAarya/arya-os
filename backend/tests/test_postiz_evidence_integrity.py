"""Postiz evidence-integrity regression (post-H1/H2 audit slice).

Proves, against the REAL PostizAdapter decision logic (only the httpx
transport in the postiz module is scripted, using real httpx
exceptions/responses) and — for the UNKNOWN requirement — the REAL
PublishingAgent and the real database:

- check_processing() never interprets a MISSING provider status as
  "ready" (direct lookup AND the 404/list fallback branch fail closed
  to "unknown")
- the 404/list-fallback branch maps "draft" exactly like the direct
  lookup branch: "processing" (a draft post has not been published)
- a 2xx publication response with NO parseable external post id never
  fabricates an id: the adapter raises the existing ambiguity type and
  the agent records the attempt as UNKNOWN
- UNKNOWN remains blocking: the provider /posts endpoint is never
  called a second time for the same intent
- normal success with a valid id, 404-no-match, and the existing
  4xx/5xx/transport failure contract are unchanged
- the operator -> SUCCEEDED verification path fails closed on
  missing-status evidence (reconciliation service untouched)
"""
import asyncio
import tempfile
import uuid as uuid_mod
from pathlib import Path

import httpx
import pytest

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt  # noqa: F401 — registers the table on Base.metadata
from app.platforms.postiz import PostizAdapter


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
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
        self.AsyncClient = lambda **kwargs: _ScriptedClient(script, **kwargs)
        for name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException"):
            setattr(self, name, getattr(httpx, name))


class _PostizScript:
    """Scripts the Postiz endpoints.

    - specific: response for GET /posts/{id} — a dict body (HTTP 200) or
      an int status code (e.g. 404 to trigger the list fallback).
    - fallback: posts list returned by the 30-day listing after a 404
      (None -> empty list).
    - publish: ("json", body) -> HTTP 200 with that JSON body;
      ("status", code) -> HTTP <code> text; ("raise", exc) -> raised.
    """

    def __init__(self, *, specific=None, fallback=None, publish=None):
        self.specific = specific if specific is not None else {"id": "x", "status": "published"}
        self.fallback = fallback
        self.publish = publish or ("json", {"id": "post-1"})
        self.posts_calls = 0

    def get(self, url, **kwargs):
        if "/public/v1/posts" not in url:
            # integrations lookup (authenticate)
            return httpx.Response(
                200, json=[{"id": "integ-1"}], request=httpx.Request("GET", url)
            )
        is_fallback_list = url.endswith("/public/v1/posts") or "startDate" in kwargs.get("params", {})
        if is_fallback_list:
            body = {"posts": self.fallback} if self.fallback is not None else {"posts": []}
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))
        # specific-post status lookup
        if isinstance(self.specific, int):
            return httpx.Response(self.specific, request=httpx.Request("GET", url))
        return httpx.Response(200, json=self.specific, request=httpx.Request("GET", url))

    def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            return httpx.Response(
                200, json={"id": "media-1"}, request=httpx.Request("POST", url)
            )
        self.posts_calls += 1
        kind, payload = self.publish
        if kind == "raise":
            raise payload
        if kind == "status":
            return httpx.Response(payload, text="scripted", request=httpx.Request("POST", url))
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


def _install_real_postiz(monkeypatch, script):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr("app.platforms.postiz.httpx", _PostizHttpxShim(script))


# ---------------------------------------------------------------------------
# DB helpers (same pattern as the attempt suites)
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
                    select(PublicationAttempt).where(PublicationAttempt.video_id == video_uuid)
                )
            )
            .scalars()
            .all()
        )
        return sorted(rows, key=lambda r: r.attempt_number)
    finally:
        await session.close()
        await engine.dispose()


async def _cleanup_attempts(*video_uuids):
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        for v in video_uuids:
            await session.execute(delete(PublicationAttempt).where(PublicationAttempt.video_id == v))
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


def _run(agent_context):
    async def _inner():
        engine, session = await _session()
        try:
            return await PublishingAgent(db=session).run(agent_context)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="postiz-evidence-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


def _ctx(video_id):
    return {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "dry_run": False,
    }


def _check_processing(script):
    async def _inner():
        adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.check_processing(content_id="media-1")

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# 1. Missing provider status is never "ready" (fail-closed evidence)
# ---------------------------------------------------------------------------


def test_direct_lookup_missing_status_is_not_ready(monkeypatch):
    script = _PostizScript(specific={"id": "media-1"})  # 200 with NO status field
    _install_real_postiz(monkeypatch, script)
    processing = _check_processing(script)
    assert processing.status != "ready"
    assert processing.status == "unknown"
    assert processing.error


def test_fallback_match_without_state_is_not_ready(monkeypatch):
    script = _PostizScript(
        specific=404,
        fallback=[{"id": "media-1"}],  # matched post with NO state/status
    )
    _install_real_postiz(monkeypatch, script)
    processing = _check_processing(script)
    assert processing.status != "ready"
    assert processing.status == "unknown"
    assert processing.error


# ---------------------------------------------------------------------------
# 2. Draft mapping is consistent across both lookup branches
# ---------------------------------------------------------------------------


def test_direct_lookup_draft_is_processing(monkeypatch):
    script = _PostizScript(specific={"id": "media-1", "status": "draft"})
    _install_real_postiz(monkeypatch, script)
    processing = _check_processing(script)
    assert processing.status == "processing"


def test_fallback_draft_is_processing(monkeypatch):
    script = _PostizScript(
        specific=404,
        fallback=[{"id": "media-1", "state": "draft"}],
    )
    _install_real_postiz(monkeypatch, script)
    processing = _check_processing(script)
    assert processing.status == "processing"


def test_published_remains_ready_in_both_branches(monkeypatch):
    direct = _PostizScript(specific={"id": "media-1", "status": "published"})
    _install_real_postiz(monkeypatch, direct)
    assert _check_processing(direct).status == "ready"

    fallback = _PostizScript(
        specific=404,
        fallback=[{"id": "media-1", "state": "published"}],
    )
    _install_real_postiz(monkeypatch, fallback)
    assert _check_processing(fallback).status == "ready"


def test_404_no_match_remains_failed(monkeypatch):
    script = _PostizScript(specific=404, fallback=None)
    _install_real_postiz(monkeypatch, script)
    processing = _check_processing(script)
    assert processing.status == "failed"  # existing behavior unchanged


# ---------------------------------------------------------------------------
# 3. Operator verification fails closed on missing-status evidence
#    (reconciliation service itself untouched)
# ---------------------------------------------------------------------------


def test_succeeded_resolution_fails_closed_on_missing_status_evidence(monkeypatch):
    from app.services import publication_attempt_reconciliation as recon
    from app.services.publication_attempts import admit_attempt, mark_unknown

    script = _PostizScript(specific={"id": "media-1"})  # no status field
    _install_real_postiz(monkeypatch, script)
    video_uuid = uuid_mod.uuid4()

    async def _make_unknown():
        engine, session = await _session()
        try:
            attempt, _ = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id="integ-1",
            )
            attempt.external_content_id = "media-1"
            await session.commit()
            assert await mark_unknown(session, attempt, "publish exception: ReadTimeout") is True
            return attempt.id
        finally:
            await session.close()
            await engine.dispose()

    async def _resolve(aid):
        engine, session = await _session()
        try:
            return await recon.resolve_attempt(
                session,
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="post-9",
            )
        finally:
            await session.close()
            await engine.dispose()

    try:
        aid = asyncio.run(_make_unknown())
        with pytest.raises(recon.VerificationFailedError):
            asyncio.run(_resolve(aid))
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN  # unchanged
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# 4. 2xx publication response without a parseable post id -> UNKNOWN
# ---------------------------------------------------------------------------


def test_publish_success_without_parseable_id_records_unknown_and_blocks_retry(monkeypatch):
    """The provider accepts the post (HTTP 200) but returns no parseable
    id: the adapter must NOT fabricate one — it raises the existing
    ambiguity type and the REAL agent records UNKNOWN, which blocks any
    automatic re-dispatch (exactly one /posts call ever)."""
    script = _PostizScript(publish=("json", {"unrelated": True}))
    _install_real_postiz(monkeypatch, script)
    video_uuid = uuid_mod.uuid4()
    ctx = _ctx(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success
        assert "UNKNOWN" in first.error
        assert "no parseable post id" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert rows[0].external_post_id is None  # nothing fabricated
        assert rows[0].external_content_id == "media-1"  # anchor intact
        assert script.posts_calls == 1

        # UNKNOWN is durable and blocking: no automatic second dispatch.
        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert script.posts_calls == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_publish_success_with_empty_string_id_records_unknown(monkeypatch):
    script = _PostizScript(publish=("json", {"id": ""}))
    _install_real_postiz(monkeypatch, script)
    video_uuid = uuid_mod.uuid4()
    try:
        result = _run(_ctx(video_uuid))
        assert not result.success and "UNKNOWN" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
        assert rows[0].external_post_id is None
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# 5. Normal success with a valid id -> unchanged
# ---------------------------------------------------------------------------


def test_publish_success_with_valid_id_still_succeeds(monkeypatch):
    script = _PostizScript(publish=("json", {"id": "post-42"}))
    _install_real_postiz(monkeypatch, script)
    video_uuid = uuid_mod.uuid4()
    try:
        result = _run(_ctx(video_uuid))
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].external_post_id == "post-42"
        assert rows[0].public_url is not None
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# 6. Existing 4xx/5xx/transport contract unchanged (adapter level)
# ---------------------------------------------------------------------------


def test_publish_4xx_is_confirmed_rejection(monkeypatch):
    script = _PostizScript(publish=("status", 400))
    _install_real_postiz(monkeypatch, script)

    async def _inner():
        adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.publish(
            content_id="media-1",
            credentials={"api_key": "k"},
            integration_id="integ-1",
            publish_type="now",
        )

    result = asyncio.run(_inner())
    assert result.success is False
    assert "HTTP 400" in result.error


def test_publish_5xx_raises_ambiguity(monkeypatch):
    script = _PostizScript(publish=("status", 502))
    _install_real_postiz(monkeypatch, script)

    async def _inner():
        adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.publish(
            content_id="media-1",
            credentials={"api_key": "k"},
            integration_id="integ-1",
            publish_type="now",
        )

    with pytest.raises(RuntimeError):
        asyncio.run(_inner())


def test_publish_connect_error_is_pre_dispatch_failure(monkeypatch):
    script = _PostizScript(publish=("raise", httpx.ConnectError("connection refused")))
    _install_real_postiz(monkeypatch, script)

    async def _inner():
        adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.publish(
            content_id="media-1",
            credentials={"api_key": "k"},
            integration_id="integ-1",
            publish_type="now",
        )

    result = asyncio.run(_inner())
    assert result.success is False
    assert "request not sent" in result.error
