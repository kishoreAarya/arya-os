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

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt  # noqa: F401 — registers the table on Base.metadata
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
        "video_storage_path": None,  # filled per-test
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "dry_run": False,
    }
    base.update(overrides)
    return base


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
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ReadTimeout("read timed out waiting for Postiz response"))
    )
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_publish_5xx_after_submission_is_unknown_and_blocks_retry(monkeypatch):
    """A 5xx on POST /posts is a server-side failure after our submission
    reached Postiz (e.g. gateway timeout after the backend committed) —
    not a confirmed rejection: UNKNOWN, retry blocked."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(publish_behavior=("status", 504))
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 1
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_upload_read_timeout_after_submission_is_unknown(monkeypatch):
    """A transport exception during POST /upload: the provider may hold
    the media — UNKNOWN (the agent must never re-dispatch after a
    possibly-accepted upload)."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(
        upload_behavior=("raise", httpx.ReadTimeout("read timed out during upload"))
    )
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_upload_5xx_after_submission_is_unknown(monkeypatch):
    """A 5xx on POST /upload: the provider may still hold the media —
    UNKNOWN, retry blocked."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(upload_behavior=("status", 502))
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        result = _run(ctx)
        assert not result.success and "UNKNOWN" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.posts_calls == 0
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# Confirmed / pre-external failures -> FAILED, retryable
# ---------------------------------------------------------------------------


def test_confirmed_4xx_rejection_is_failed_and_retry_admits_new_attempt(monkeypatch):
    """HTTP 4xx on POST /posts is a confirmed provider rejection: FAILED,
    and a retry legitimately admits attempt_number+1 (the provider told us
    no post was created)."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(publish_behavior=("status", 400))
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_pre_dispatch_connect_error_is_failed_and_retryable(monkeypatch):
    """ConnectError means the request was never sent — no external side
    effect is possible: FAILED (retryable), not UNKNOWN."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ConnectError("connection refused"))
    )
    _install_real_postiz(monkeypatch, transport)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f09_permit_denied_error_names_the_uploaded_media_id(monkeypatch):
    """F-09 (Option 1, observability only): when an operator resolution
    lands between the upload and the anchor write, the permit is
    correctly denied (H1: zero publications) — and the denied execution
    now NAMES the uploaded provider media id so the otherwise-untracked
    orphan can be found and cleaned up manually."""
    from datetime import datetime, timedelta, timezone

    import app.services.publication_attempts as attempt_service
    import app.services.publication_attempt_reconciliation as recon
    from app.models.enums import PublicationAttemptStatus as Status

    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(
        upload_behavior=("ok", "media-ORPHAN"),
        publish_behavior=("ok", "post-never"),
    )
    _install_real_postiz(monkeypatch, transport)

    real_mark_external_content = attempt_service.mark_external_content

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
                from_status=Status.PENDING,
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
        return await real_mark_external_content(db, attempt, content_id)

    monkeypatch.setattr(
        attempt_service, "mark_external_content", _resolve_then_anchor
    )
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        result = _run(ctx)
        assert not result.success
        assert "permit" in result.error.lower()
        # H1 held: no publication was dispatched.
        assert transport.posts_calls == 0
        assert transport.upload_calls == 1
        # F-09 observability: the orphaning media id is named in the error.
        assert "media-ORPHAN" in result.error
        assert "no external publish was made" in result.error
        # The row itself is FAILED with no anchor (the untracked-orphan
        # case) — only the surfaced id makes the artifact findable.
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [Status.FAILED]
        assert rows[0].external_content_id is None
    finally:
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
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport()  # upload ok media-1; publish ok post-1
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="succeeded", external_post_id="post-operator"),
        evidence="ready",
    )
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f11a_failed_refusal_remains_fail_loud(monkeypatch):
    """Test 6: refusal under a FAILED resolution (non-public evidence,
    force) stays fail-loud byte-for-byte — that is the genuine duplicate-
    risk manual-review signal."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport()
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="failed"),
        evidence="processing",
    )
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f11a_unknown_refusal_unchanged(monkeypatch):
    """Test 7: a publish EXCEPTION after a concurrent SUCCEEDED resolution
    keeps the existing refused-transition behavior: failure naming the
    resolution, no UNKNOWN landing, row stays SUCCEEDED."""
    video_uuid = uuid.uuid4()
    transport = _ScriptedTransport(
        publish_behavior=("raise", httpx.ReadTimeout("dropped after submit"))
    )
    _install_midflight_postiz(
        monkeypatch,
        transport,
        _operator_resolution_hook(video_uuid, to_status="succeeded", external_post_id="post-operator"),
        evidence="ready",
    )
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        first = _run(ctx)
        assert not first.success
        assert "attempt already resolved" in first.error
        assert transport.posts_calls == 1
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_post_id == "post-operator"
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))
