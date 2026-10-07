"""Publication attempt core — real-Postiz-adapter failure-contract regression.

F1 regression: proves the truthful adapter/agent failure contract against
the REAL PostizAdapter decision logic (only the httpx transport is
scripted, using real httpx exception classes and real httpx.Response
objects) wired through the REAL PublishingAgent and the real database:

- confirmed provider rejection (HTTP 4xx on /posts)        -> FAILED (retry admits n+1)
- pre-dispatch unreachability (ConnectError)                -> FAILED (retry admits n+1)
- ambiguous post-submission outcomes                        -> UNKNOWN (retry blocked):
    - transport exception mid-exchange (ReadTimeout) on /posts or /upload
    - server-side failure (HTTP 5xx) on /posts or /upload

The duplicate-publication invariant: after an ambiguous outcome the
provider /posts endpoint is NEVER called a second time automatically.
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt
from app.platforms.postiz import PostizAdapter


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
    """httpx.AsyncClient stand-in: scripts the three Postiz endpoints.

    Behaviors are (kind, payload) tuples:
      ("ok", provider_id)  -> HTTP 200 JSON {"id": provider_id}
      ("status", code)     -> HTTP <code> with a text body
      ("raise", exception) -> the real httpx exception object is raised
    """

    def __init__(self, transport, **kwargs):
        self._transport = transport

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, **kwargs):
        return httpx.Response(
            200,
            json=[{"id": "integ-1", "name": "channel"}],
            request=httpx.Request("GET", url),
        )

    async def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            self._transport.upload_calls += 1
            kind, payload = self._transport.upload_behavior
        else:
            self._transport.posts_calls += 1
            kind, payload = self._transport.publish_behavior
        if kind == "raise":
            raise payload
        if kind == "status":
            return httpx.Response(payload, text="scripted", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"id": payload}, request=httpx.Request("POST", url))


class _ScriptedTransport:
    def __init__(self, *, upload_behavior=("ok", "media-1"), publish_behavior=("ok", "post-1")):
        self.upload_behavior = upload_behavior
        self.publish_behavior = publish_behavior
        self.upload_calls = 0
        self.posts_calls = 0


def _install_real_postiz(monkeypatch, transport):
    """The REAL PostizAdapter class (real decision logic) with only the
    httpx transport scripted."""
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: _ScriptedClient(transport, **kwargs)
    )


def _context(video_id, **overrides):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        # Phase 54B-I6: the seeded manifest's authoritative artifact —
        # dispatch verifies against (and uploads) the manifest-bound
        # snapshot, not an arbitrary caller path.
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
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Phase 54B-I6: manifest-bound approved publish-target seeding (the
# minimum authorization state the Phase 54B-I5 dispatch contract accepts
# for real publishing: real artifact, real manifest through the I4
# service, bound + approved THUMBNAIL checkpoint).
# ---------------------------------------------------------------------------

_SEED_STATE = {}


def _seed_target(**manifest_overrides):
    kwargs = dict(
        platform="postiz",
        social_platform="youtube",
        integration_id="integ-1",
        privacy_status="public",
        publish_type="now",
    )
    kwargs.update(manifest_overrides)

    async def _inner():
        from tests._dispatch_manifest_fixtures import _seed_manifest_bound_target

        return await _seed_manifest_bound_target(**kwargs)

    run_id, video_id, _mid, vpath, _thumb = asyncio.run(_inner())
    _SEED_STATE.clear()
    _SEED_STATE.update(run_id=run_id, video_id=video_id, asset=vpath)
    return run_id, video_id


def _cleanup_target():
    async def _inner():
        from tests._dispatch_manifest_fixtures import _cleanup_manifest_bound_target

        await _cleanup_manifest_bound_target(
            _SEED_STATE.get("run_id"), _SEED_STATE.get("video_id"),
            _SEED_STATE.get("asset"),
        )

    if _SEED_STATE.get("run_id") is not None:
        asyncio.run(_inner())
    _SEED_STATE.clear()


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
            agent = PublishingAgent(db=session)
            return await agent.run(agent_context)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-f1-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


# ---------------------------------------------------------------------------
# Ambiguous external submission -> UNKNOWN, retry blocked, no second post
# ---------------------------------------------------------------------------


def test_publish_read_timeout_after_submission_is_unknown_and_blocks_retry(monkeypatch):
    """F1 core regression with the REAL adapter: a transport exception
    after POST /posts was dispatched (read timeout mid-exchange) must land
    UNKNOWN — and a re-submission of the same intent must NEVER invoke the
    provider /posts endpoint again (no duplicate publication)."""
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ReadTimeout("read timed out waiting for Postiz response"))
    )
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        # The upload anchor was persisted before the ambiguous publish.
        assert rows[0].external_content_id == "media-1"
        assert "ReadTimeout" in rows[0].error
        assert transport.posts_calls == 1

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        # The duplicate-publication invariant: exactly ONE /posts call ever.
        assert transport.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_publish_5xx_after_submission_is_unknown_and_blocks_retry(monkeypatch):
    """A 5xx on POST /posts is a server-side failure after our submission
    reached Postiz (e.g. gateway timeout after the backend committed) —
    not a confirmed rejection: UNKNOWN, retry blocked."""
    transport = _ScriptedTransport(publish_behavior=("status", 504))
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_upload_read_timeout_after_submission_is_unknown(monkeypatch):
    """A transport exception during POST /upload: the provider may hold
    the media — UNKNOWN (the agent must never re-dispatch after a
    possibly-accepted upload)."""
    transport = _ScriptedTransport(
        upload_behavior=("raise", httpx.ReadTimeout("read timed out during upload"))
    )
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        result = _run(ctx)
        assert not result.success and "UNKNOWN" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert transport.posts_calls == 0

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 0
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_upload_5xx_after_submission_is_unknown(monkeypatch):
    """A 5xx on POST /upload: the provider may still hold the media —
    UNKNOWN, retry blocked."""
    transport = _ScriptedTransport(upload_behavior=("status", 502))
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        result = _run(ctx)
        assert not result.success and "UNKNOWN" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 0
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# Confirmed / pre-external failures -> FAILED, retryable
# ---------------------------------------------------------------------------


def test_confirmed_4xx_rejection_is_failed_and_retry_admits_new_attempt(monkeypatch):
    """HTTP 4xx on POST /posts is a confirmed provider rejection: FAILED,
    and a retry legitimately admits attempt_number+1 (the provider told us
    no post was created)."""
    transport = _ScriptedTransport(publish_behavior=("status", 400))
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" not in first.error
        assert "HTTP 400" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]

        transport.publish_behavior = ("ok", "post-9")
        second = _run(ctx)
        assert second.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        assert transport.posts_calls == 2  # the one legitimate retry
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_pre_dispatch_connect_error_is_failed_and_retryable(monkeypatch):
    """ConnectError means the request was never sent — no external side
    effect is possible: FAILED (retryable), not UNKNOWN."""
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ConnectError("connection refused"))
    )
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" not in first.error
        assert "request not sent" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]

        transport.publish_behavior = ("ok", "post-7")
        second = _run(ctx)
        assert second.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f09_permit_denied_error_names_the_uploaded_media_id(monkeypatch):
    """F-09 (Option 1, observability only): when an operator resolution
    lands between the upload and the anchor write, the anchor
    persistence is correctly refused (H1/I2: zero publications) — and
    the denied execution now NAMES the uploaded provider media id so the
    otherwise-untracked orphan can be found and cleaned up manually.
    Phase 54B-I6: the anchor write is the I2
    persist_external_content_anchor precondition (publish is unreachable
    unless it PERSISTS), and the attempt is IN_PROGRESS at upload time
    (the I3/I5 permit precedes every upload)."""
    from datetime import datetime, timedelta, timezone

    import app.services.publication_attempts as attempt_service
    import app.services.publication_attempt_reconciliation as recon
    from app.models.enums import PublicationAttemptStatus as Status

    transport = _ScriptedTransport(
        upload_behavior=("ok", "media-ORPHAN"),
        publish_behavior=("ok", "post-never"),
    )
    _install_real_postiz(monkeypatch, transport)
    _, video_uuid = _seed_target()

    real_persist_anchor = attempt_service.persist_external_content_anchor

    async def _force_fail_aged(attempt_id):
        from sqlalchemy import update

        engine, session = await _session()
        try:
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.id == attempt_id)
                .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await session.commit()
            await recon.resolve_attempt(
                session,
                attempt_id,
                from_status=Status.IN_PROGRESS,
                to_status=Status.FAILED,
                attestation="operator verified: execution stalled",
                force=True,
            )
        finally:
            await session.close()
            await engine.dispose()

    async def _resolve_then_anchor(db, attempt, content_id):
        # The operator lands mid-flight, right after the upload returned
        # media-ORPHAN and before the anchor write can commit.
        await _force_fail_aged(attempt.id)
        return await real_persist_anchor(db, attempt, content_id)

    monkeypatch.setattr(
        attempt_service, "persist_external_content_anchor", _resolve_then_anchor
    )
    ctx = _context(video_uuid)
    try:
        result = _run(ctx)
        assert not result.success
        assert "Publication aborted" in result.error
        # H1 held: no publication was dispatched.
        assert transport.posts_calls == 0
        assert transport.upload_calls == 1
        # F-09 observability: the orphaning media id is named in the error.
        assert "media-ORPHAN" in result.error
        assert "external publish was made" in result.error
        # The row itself is FAILED with no anchor (the untracked-orphan
        # case) — only the surfaced id makes the artifact findable.
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [Status.FAILED]
        assert rows[0].external_content_id is None
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# F-11a: agreement-aware success refusal — when the agent's mark_succeeded
# CAS is refused under an already-SUCCEEDED row (concurrent evidence-based
# operator resolution), the outcome is AGREEMENT: success with the attempt
# row's ids and the agent-observed id surfaced as a warning. Refusals under
# any other status remain fail-loud exactly as ratified.
# ---------------------------------------------------------------------------


class _MidFlightOperatorClient(_ScriptedClient):
    """Scripts the Postiz transport AND interposes an operator resolution
    on the FIRST /posts dispatch (F-11 harness). Evidence lookups answer
    per the configured provider state."""

    def __init__(self, transport, on_publish_dispatch=None, evidence="ready", **kwargs):
        super().__init__(transport, **kwargs)
        self._on_publish_dispatch = on_publish_dispatch
        self._evidence = evidence

    async def get(self, url, **kwargs):
        is_specific_post = (
            "/public/v1/posts" in url
            and not url.endswith("/public/v1/posts")
            and "startDate" not in kwargs.get("params", {})
        )
        if is_specific_post:
            if self._evidence == "ready":
                return httpx.Response(
                    200, json={"id": "x", "status": "published"},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200, json={"status": "processing"}, request=httpx.Request("GET", url)
            )
        return await super().get(url, **kwargs)

    async def post(self, url, **kwargs):
        if not url.endswith("/public/v1/upload") and self._on_publish_dispatch:
            hook = self._on_publish_dispatch
            self._on_publish_dispatch = None  # first dispatch only
            await hook()
        return await super().post(url, **kwargs)


def _operator_resolution_hook(video_uuid, *, to_status, external_post_id=None):
    """Aged mid-flight operator resolution (IN_PROGRESS -> SUCCEEDED on
    ready evidence, or -> FAILED with force on non-public evidence)."""

    async def hook():
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select, update

        from app.services import publication_attempt_reconciliation as recon

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
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.id == row.id)
                .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await session.commit()
            if to_status == "succeeded":
                await recon.resolve_attempt(
                    session,
                    row.id,
                    from_status=PublicationAttemptStatus.IN_PROGRESS,
                    to_status=PublicationAttemptStatus.SUCCEEDED,
                    external_post_id=external_post_id,
                    public_url=f"https://social.example/watch/{external_post_id}",
                )
            else:
                await recon.resolve_attempt(
                    session,
                    row.id,
                    from_status=PublicationAttemptStatus.IN_PROGRESS,
                    to_status=PublicationAttemptStatus.FAILED,
                    attestation="operator verified: execution stalled",
                    force=True,
                )
        finally:
            await session.close()
            await engine.dispose()

    return hook


def _install_midflight_postiz(monkeypatch, transport, on_publish_dispatch, evidence):
    class _Shim:
        ConnectError = httpx.ConnectError
        ConnectTimeout = httpx.ConnectTimeout
        ReadTimeout = httpx.ReadTimeout
        TimeoutException = httpx.TimeoutException

        @staticmethod
        def AsyncClient(**kwargs):
            return _MidFlightOperatorClient(
                transport, on_publish_dispatch, evidence, **kwargs
            )

    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr("app.platforms.postiz.httpx", _Shim)


def test_f11a_concurrent_succeeded_resolution_is_agreement_not_failure(monkeypatch):
    """Tests 1-5: an evidence-based SUCCEEDED resolution landing under the
    in-flight publish is AGREEMENT: the agent returns success with the
    attempt ROW's ids, surfaces the agent-observed id as a warning, makes
    exactly one dispatch, and the duplicate retry stays zero-dispatch."""
    transport = _ScriptedTransport()  # upload ok media-1; publish ok post-1
    _, video_uuid = _seed_target()
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="succeeded", external_post_id="post-operator"),
        evidence="ready",
    )
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        # 1. Agreement, not failure.
        assert first.success, first.error
        # 2. The authoritative ids come from the attempt ROW.
        assert first.output["published_video_id"] == "post-operator"
        assert first.output["public_url"] == "https://social.example/watch/post-operator"
        assert first.output["attempt_status"] == "succeeded"
        # 3. The agent-observed id is surfaced in the warning.
        warnings = first.output.get("writeback_warnings") or []
        assert any("post-1" in w for w in warnings)
        # 4. Exactly one dispatch.
        assert transport.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_post_id == "post-operator"
        # 5. Duplicate retry: successful, zero additional dispatch.
        second = _run(ctx)
        assert second.success and second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "post-operator"
        assert transport.posts_calls == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f11a_failed_refusal_remains_fail_loud(monkeypatch):
    """Test 6: refusal under a FAILED resolution (non-public evidence,
    force) stays fail-loud byte-for-byte — that is the genuine duplicate-
    risk manual-review signal."""
    transport = _ScriptedTransport()
    _, video_uuid = _seed_target()
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="failed"),
        evidence="processing",
    )
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success
        assert "manual review required" in first.error
        assert "post-1" in first.error
        assert transport.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert rows[0].external_post_id is None
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f11a_unknown_refusal_unchanged(monkeypatch):
    """Test 7: a publish EXCEPTION after a concurrent SUCCEEDED resolution
    keeps the existing refused-transition behavior: failure naming the
    resolution, no UNKNOWN landing, row stays SUCCEEDED."""
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ReadTimeout("dropped after submit"))
    )
    _, video_uuid = _seed_target()
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="succeeded", external_post_id="post-operator"),
        evidence="ready",
    )
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success
        assert "attempt already resolved" in first.error
        assert transport.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_post_id == "post-operator"
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# F-13a: bounded, sanitized provider error text — control characters
# stripped, provider-derived component capped at 1000 characters with a
# deterministic truncation marker; diagnostic prefixes/status codes intact.
# ---------------------------------------------------------------------------


def test_f13a_postiz_helper_sanitize_and_truncate():
    from app.platforms.postiz import _PROVIDER_TEXT_LIMIT, _provider_text

    # Small clean text passes through unchanged (idempotent no-op).
    assert _provider_text("boom") == "boom"
    assert _provider_text(None) == ""
    # Control characters (C0, DEL, C1) are stripped.
    dirty = "a\x00b\x1bc\x7fd\x9fe\nf\rg"
    assert _provider_text(dirty) == "abcdefg"
    # Oversized text is capped with a deterministic marker.
    big = "A" * (_PROVIDER_TEXT_LIMIT + 4321)
    out = _provider_text(big)
    assert out == "A" * _PROVIDER_TEXT_LIMIT + "… [truncated 4321 chars]"
    assert len(out) <= _PROVIDER_TEXT_LIMIT + len("… [truncated 4321 chars]")


def test_f13a_postiz_oversized_4xx_body_is_capped_and_clean(monkeypatch):
    """End-to-end through the REAL adapter + agent: a malicious/oversized
    provider 4xx body is sanitized before persistence — bounded, control-
    character-free, marker present, diagnostic prefix intact."""
    from app.platforms.postiz import _PROVIDER_TEXT_LIMIT

    markup = "<script>alert(1)</script>"
    body = "B" * (_PROVIDER_TEXT_LIMIT + 5000) + "\x00\x1b" + markup
    dropped = 5000 + len(markup)  # control chars stripped; markup counted
    _, video_uuid = _seed_target()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)

    import httpx as _httpx

    class _BigBodyClient(_ScriptedClient):
        async def post(self, url, **kwargs):
            if url.endswith("/public/v1/upload"):
                return await super().post(url, **kwargs)
            self._transport.posts_calls += 1
            return _httpx.Response(400, text=body, request=_httpx.Request("POST", url))

    _orig = _httpx.AsyncClient
    _httpx.AsyncClient = lambda **kw: _BigBodyClient(transport, **kw)
    try:
        ctx = _context(video_uuid)
        result = _run(ctx)
        assert not result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        err = rows[0].error
        # Diagnostic prefix and status preserved.
        assert "Postiz post creation failed with HTTP 400" in (result.error or "")
        assert "publish rejected: Postiz post creation failed with HTTP 400" in err
        # Control characters gone; markup beyond the cap gone.
        assert "\x00" not in err and "\x1b" not in err
        assert "<script>" not in err
        # Bounded provider component with a deterministic marker.
        marker = f"… [truncated {dropped} chars]"
        assert marker in err
        assert len(err) <= len("publish rejected: Postiz post creation failed with HTTP 400: ") + _PROVIDER_TEXT_LIMIT + len(marker)
    finally:
        _httpx.AsyncClient = _orig
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f13a_postiz_evidence_path_inherits_sanitized_text(monkeypatch):
    """The evidence/verification path (check_processing >=400 ->
    ProcessingStatus.error -> VerificationFailedError detail) inherits the
    sanitized provider text."""
    from app.services import publication_attempt_reconciliation as recon
    from app.services.publication_attempts import admit_attempt, mark_unknown
    from app.models.enums import PublicationAttemptStatus as S
    from app.platforms.postiz import _PROVIDER_TEXT_LIMIT

    import httpx as _httpx

    body = "E" * (_PROVIDER_TEXT_LIMIT + 1234)
    video_uuid = uuid.uuid4()

    class _EvilGetClient(_ScriptedClient):
        async def get(self, url, **kwargs):
            if "/public/v1/posts" in url and not url.endswith("/public/v1/posts") and "startDate" not in kwargs.get("params", {}):
                return _httpx.Response(503, text=body, request=_httpx.Request("GET", url))
            return await super().get(url, **kwargs)

    _install_real_postiz(monkeypatch, _ScriptedTransport())
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    import app.platforms.postiz as _postiz_mod

    class _Shim:
        ConnectError = _httpx.ConnectError
        ConnectTimeout = _httpx.ConnectTimeout
        ReadTimeout = _httpx.ReadTimeout
        TimeoutException = _httpx.TimeoutException
        AsyncClient = staticmethod(lambda **kw: _EvilGetClient(_ScriptedTransport(), **kw))

    monkeypatch.setattr(_postiz_mod, "httpx", _Shim)

    async def _make():
        engine, session = await _session()
        try:
            a, _ = await admit_attempt(session, video_id=video_uuid, platform="postiz",
                                       social_platform="youtube", integration_id="i1")
            a.external_content_id = "media-1"
            await session.commit()
            assert await mark_unknown(session, a, "publish exception: ReadTimeout") is True
            return a.id
        finally:
            await session.close()
            await engine.dispose()

    aid = asyncio.run(_make())

    async def _check():
        engine, session = await _session()
        try:
            ev = await recon.fetch_evidence(session, aid)
            try:
                await recon.resolve_attempt(session, aid, from_status=S.UNKNOWN,
                                            to_status=S.SUCCEEDED, external_post_id="p")
                return ev["provider_error"], None
            except recon.VerificationFailedError as exc:
                return ev["provider_error"], str(exc)
        finally:
            await session.close()
            await engine.dispose()

    provider_error, detail = asyncio.run(_check())
    try:
        assert "… [truncated 1234 chars]" in provider_error
        assert len(provider_error) <= _PROVIDER_TEXT_LIMIT + len("… [truncated 1234 chars]") + len("HTTP 503: ")
        assert detail is not None and "… [truncated 1234 chars]" in detail
        assert "E" * 1200 not in detail  # the unbounded body never leaks
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# F-14a: the three-leg duplicate-dispatch scenario — without the explicit
# deferred-commitment acknowledgement the UNKNOWN resolution is REFUSED,
# so the retry stays blocked at admission and NO second scheduled post is
# dispatched; with the acknowledgement the operator-gated escape proceeds.
# ---------------------------------------------------------------------------


class _ScheduledProviderClient(_ScriptedClient):
    """Simulates the provider-side truth: a SCHEDULED post exists (created
    on the first dispatch, which then timed out client-side), findable in
    the 30-day list only by its POST id — never by the media anchor."""

    def __init__(self, transport, provider_posts, **kwargs):
        super().__init__(transport, **kwargs)
        self._provider_posts = provider_posts
        self._first_dispatch = True

    async def get(self, url, **kwargs):
        is_fallback = url.endswith("/public/v1/posts") or "startDate" in kwargs.get("params", {})
        if is_fallback:
            return httpx.Response(
                200, json={"posts": list(self._provider_posts)},
                request=httpx.Request("GET", url),
            )
        if "/public/v1/posts" in url:
            return httpx.Response(404, request=httpx.Request("GET", url))  # media anchor ≠ post id
        return await super().get(url, **kwargs)

    async def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            return await super().post(url, **kwargs)
        self._transport.posts_calls += 1
        if self._first_dispatch:
            self._first_dispatch = False
            self._provider_posts.append({"id": "post-sched-1", "state": "scheduled"})
            raise httpx.ReadTimeout("dropped after the scheduled post was accepted")
        self._provider_posts.append({"id": "post-sched-2", "state": "scheduled"})
        return httpx.Response(200, json={"id": "post-sched-2"}, request=httpx.Request("POST", url))


def _install_scheduled_provider(monkeypatch, provider_posts):
    class _Shim:
        ConnectError = httpx.ConnectError
        ConnectTimeout = httpx.ConnectTimeout
        ReadTimeout = httpx.ReadTimeout
        TimeoutException = httpx.TimeoutException

        @staticmethod
        def AsyncClient(**kwargs):
            return _ScheduledProviderClient(_ScriptedTransport(), provider_posts, **kwargs)

    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr("app.platforms.postiz.httpx", _Shim)


def test_f14a_three_leg_scenario_second_dispatch_blocked_without_ack(monkeypatch):
    """Legs 1-3 of the F-14 audit: scheduled dispatch -> ambiguous outcome
    -> UNKNOWN; the honest-but-unqualified attestation is REFUSED; the
    retry therefore stays blocked at admission — exactly ONE scheduled
    post exists at the provider."""
    from app.services import publication_attempt_reconciliation as recon

    provider_posts = []
    _install_scheduled_provider(monkeypatch, provider_posts)
    _, video_uuid = _seed_target(
        scheduled_at="2030-06-01T10:00:00Z", publish_type="schedule"
    )
    ctx = _context(
        video_uuid, scheduled_at="2030-06-01T10:00:00Z"
    )
    try:
        # Leg 1: scheduled dispatch -> client timeout -> UNKNOWN.
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
        assert len(provider_posts) == 1  # the scheduled post exists server-side

        # Leg 2: honest-but-unqualified attestation -> REFUSED (F-14a).
        with pytest.raises(recon.IllegalTransitionError) as excinfo:
            asyncio.run(_resolve_via_http(rows[0].id))
        assert "including scheduled posts" in str(excinfo.value)

        # Leg 3: the retry is BLOCKED at admission (UNKNOWN is durable) —
        # no second scheduled post is ever dispatched.
        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert len(provider_posts) == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


async def _resolve_rows():
    pass


def _resolve_via_http(attempt_id):
    from app.services import publication_attempt_reconciliation as recon
    from app.models.enums import PublicationAttemptStatus as Status

    async def _inner():
        engine, session = await _session()
        try:
            return await recon.resolve_attempt(
                session,
                attempt_id,
                from_status=Status.UNKNOWN,
                to_status=Status.FAILED,
                attestation="verified in provider console: no public post exists today",
            )
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def test_f14a_operator_gated_escape_with_ack_proceeds(monkeypatch):
    """With the explicit acknowledgement the operator-gated escape hatch
    works exactly as ratified: resolution succeeds and the retry admits
    n+1 (documented operator responsibility: cancel the scheduled post
    at the provider first)."""
    from app.services import publication_attempt_reconciliation as recon
    from app.models.enums import PublicationAttemptStatus as Status

    provider_posts = []
    _install_scheduled_provider(monkeypatch, provider_posts)
    _, video_uuid = _seed_target(
        scheduled_at="2030-06-01T10:00:00Z", publish_type="schedule"
    )
    ctx = _context(
        video_uuid, scheduled_at="2030-06-01T10:00:00Z"
    )

    async def _resolve_with_ack(attempt_id):
        engine, session = await _session()
        try:
            return await recon.resolve_attempt(
                session,
                attempt_id,
                from_status=Status.UNKNOWN,
                to_status=Status.FAILED,
                attestation=(
                    "scheduled provider-side publication cancelled with the provider — "
                    "including scheduled posts"
                ),
            )
        finally:
            await session.close()
            await engine.dispose()

    def _resolve_with_ack_sync(attempt_id):
        return asyncio.run(_resolve_with_ack(attempt_id))

    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))

        resolved, _ = _resolve_with_ack_sync(rows[0].id)
        assert resolved.status == Status.FAILED

        # Retry admitted as n+1; the provider now holds the second
        # scheduled post (operator-gated escape, documented).
        _run(ctx)
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert len(provider_posts) == 2
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# F-15a: truthful upload anchors — an id-less 2xx upload response raises
# the ambiguity error (agent records UNKNOWN, retry blocked) instead of
# fabricating an anchor from the local file name; parseable id/path
# responses are unaffected; symmetry with the F-06 publish-side contract.
# ---------------------------------------------------------------------------


class _UploadResponseClient(_ScriptedClient):
    """Scripts the upload endpoint's 200 JSON body; everything else normal."""

    def __init__(self, transport, upload_body, **kwargs):
        super().__init__(transport, **kwargs)
        self._upload_body = upload_body

    async def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            self._transport.upload_calls += 1
            return httpx.Response(
                200, json=self._upload_body, request=httpx.Request("POST", url)
            )
        return await super().post(url, **kwargs)


def _install_upload_body(monkeypatch, upload_body):
    transport = _ScriptedTransport()

    class _Shim:
        ConnectError = httpx.ConnectError
        ConnectTimeout = httpx.ConnectTimeout
        ReadTimeout = httpx.ReadTimeout
        TimeoutException = httpx.TimeoutException

        @staticmethod
        def AsyncClient(**kwargs):
            return _UploadResponseClient(transport, upload_body, **kwargs)

    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr("app.platforms.postiz.httpx", _Shim)
    return transport


def test_f15a_idless_upload_200_is_unknown_with_no_fabricated_anchor(monkeypatch):
    """Requirements: id-less 2xx upload -> ambiguity/UNKNOWN; NO fabricated
    anchor; NO publish dispatch; retry remains blocked (UNKNOWN is durable)."""
    transport = _install_upload_body(monkeypatch, {"unrelated": True})
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        first = _run(ctx)
        assert not first.success
        assert "UNKNOWN" in first.error
        assert "no parseable media id" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        # No fabricated anchor: the row carries no external_content_id.
        assert rows[0].external_content_id is None
        # No publish was dispatched.
        assert transport.posts_calls == 0
        assert transport.upload_calls == 1

        # Retry remains blocked at admission (UNKNOWN is durable).
        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 0
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f15a_path_only_upload_response_still_works(monkeypatch):
    """A 200 response carrying only `path` (no `id`) remains a valid,
    non-fabricated anchor — unchanged behavior."""
    transport = _install_upload_body(monkeypatch, {"path": "uploads/media-9.mp4"})
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        result = _run(ctx)
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].external_content_id == "uploads/media-9.mp4"
        assert transport.posts_calls == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f15a_id_upload_response_still_works(monkeypatch):
    """A 200 response carrying `id` is unchanged (the default scripted
    behavior exercises exactly this)."""
    _install_upload_body(monkeypatch, {"id": "media-77"})
    _, video_uuid = _seed_target()
    ctx = _context(video_uuid)
    try:
        result = _run(ctx)
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].external_content_id == "media-77"
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f15a_f06_symmetry_idless_2xx_raises_on_both_paths(monkeypatch):
    """F-06 symmetry: an id-less 2xx raises the SAME ambiguity contract on
    both the upload path and the publish path — never a fabricated
    identifier on either."""
    import pytest as _pytest

    from app.platforms.postiz import PostizAdapter

    # Upload path: id-less 200 -> ambiguity RuntimeError (F-15a).
    _install_upload_body(monkeypatch, {"unrelated": True})

    async def _upload():
        adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.upload_content(
            file_path=_tmp_video(), credentials={"api_key": "k"}, is_dry_run=False
        )

    with _pytest.raises(RuntimeError) as upload_exc:
        asyncio.run(_upload())
    assert "no parseable media id" in str(upload_exc.value)

    class _PublishClient(_ScriptedClient):
        async def post(self, url, **kwargs):
            if url.endswith("/public/v1/upload"):
                return await super().post(url, **kwargs)
            return httpx.Response(200, json={"unrelated": True}, request=httpx.Request("POST", url))

    import app.platforms.postiz as _pm

    class _PublishShim:
        ConnectError = httpx.ConnectError
        ConnectTimeout = httpx.ConnectTimeout
        ReadTimeout = httpx.ReadTimeout
        TimeoutException = httpx.TimeoutException
        AsyncClient = staticmethod(lambda **kw: _PublishClient(_ScriptedTransport(), **kw))

    original_httpx = _pm.httpx
    _pm.httpx = _PublishShim
    try:

        async def _publish():
            adapter = PostizAdapter(db=None, secrets=_FakeSecrets())
            return await adapter.publish(
                content_id="media-1",
                credentials={"api_key": "k"},
                integration_id="integ-1",
                publish_type="now",
            )

        with _pytest.raises(RuntimeError) as publish_exc:
            asyncio.run(_publish())
        assert "no parseable post id" in str(publish_exc.value)
    finally:
        _pm.httpx = original_httpx
