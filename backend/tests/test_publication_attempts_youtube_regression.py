"""Publication attempt core — real-YouTube-adapter failure-contract regression.

F5 regression: proves the truthful adapter/agent failure contract against
the REAL YouTubeAdapter decision logic (only the external Google client
is scripted — real googleapiclient HttpError objects, real transport
exception types, real MediaFileUpload against real temp files) wired
through the REAL PublishingAgent and the real database:

- dry-run upload / thumbnail / publish: validation only, ZERO Google API
  calls (no insert / update / thumbnails.set invocations)
- successful real upload + publish -> SUCCEEDED with external ids
- confirmed 4xx (videos.update)                -> FAILED (retry admits n+1)
- pre-dispatch transport failure (connect refused) -> FAILED (retry admits n+1)
- timeout after dispatch                        -> UNKNOWN (retry blocked)
- HTTP 5xx after submission                     -> UNKNOWN (retry blocked)
- an ambiguous publish failure can never produce a retryable FAILED attempt
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

import httplib2
from googleapiclient.errors import HttpError

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt  # noqa: F401 — registers the table
from app.platforms.youtube import YouTubeAdapter

SECRET_MARKER = "SECRET-DO-NOT-PERSIST"


class _FakeSecrets:
    def get(self, key, required=False):
        return f"test-{SECRET_MARKER}" if key.startswith("youtube_") else None


def _http_error(code: int) -> HttpError:
    return HttpError(
        resp=httplib2.Response({"status": str(code), "reason": "scripted"}),
        content=b'{"error":{"message":"scripted"}}',
    )


class _InsertRequest:
    """videos().insert(...) request with scripted next_chunk()."""

    def __init__(self, behavior):
        self._behavior = behavior

    def next_chunk(self):
        kind, payload = self._behavior
        if kind == "raise":
            raise payload
        if kind == "http_status":
            raise _http_error(payload)
        return (None, {"id": payload or "yt-video-1"})


class _UpdateRequest:
    """videos().update(...) request with scripted execute()."""

    def __init__(self, behavior):
        self._behavior = behavior

    def execute(self):
        kind, payload = self._behavior
        if kind == "raise":
            raise payload
        if kind == "http_status":
            raise _http_error(payload)
        return {"id": "ok"}


class _SetRequest:
    """thumbnails().set(...) request with scripted execute()."""

    def __init__(self, behavior):
        self._behavior = behavior

    def execute(self):
        kind, payload = self._behavior
        if kind == "raise":
            raise payload
        if kind == "http_status":
            raise _http_error(payload)
        return {}


class _Videos:
    def __init__(self, script, counters):
        self._script = script
        self._counters = counters

    def insert(self, *, part, body, media_body):
        self._counters["insert_calls"] += 1
        return _InsertRequest(self._script.upload_behavior)

    def update(self, *, part, body):
        self._counters["update_calls"] += 1
        return _UpdateRequest(self._script.publish_behavior)


class _Thumbnails:
    def __init__(self, script, counters):
        self._script = script
        self._counters = counters

    def set(self, *, videoId, media_body):
        self._counters["thumbnail_calls"] += 1
        return _SetRequest(self._script.thumbnail_behavior)


class _ScriptedGoogleClient:
    def __init__(self, script, counters):
        self._videos = _Videos(script, counters)
        self._thumbnails = _Thumbnails(script, counters)

    def videos(self):
        return self._videos

    def thumbnails(self):
        return self._thumbnails


class _Script:
    """Behaviors are (kind, payload): ("ok", id) | ("http_status", code) |
    ("raise", exception)."""

    def __init__(
        self,
        *,
        upload=("ok", "yt-video-1"),
        publish=("ok", None),
        thumbnail=("ok", None),
    ):
        self.upload_behavior = upload
        self.publish_behavior = publish
        self.thumbnail_behavior = thumbnail
        self.counters = {"insert_calls": 0, "update_calls": 0, "thumbnail_calls": 0}


def _install_real_youtube(monkeypatch, script):
    """The REAL YouTubeAdapter class with only the external Google client
    transport scripted (credential/client builders replaced; authenticate()
    itself runs its real logic)."""
    client = _ScriptedGoogleClient(script, script.counters)

    def _fake_build_api_client(self, credentials=None):
        return client

    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: YouTubeAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(YouTubeAdapter, "_build_credentials", lambda self: {"api_key": SECRET_MARKER})
    monkeypatch.setattr(YouTubeAdapter, "_build_api_client", _fake_build_api_client)


# ---------------------------------------------------------------------------
# DB / agent helpers (same pattern as the other publication-attempt suites)
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


async def _cleanup(video_uuid):
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        await session.execute(delete(PublicationAttempt).where(PublicationAttempt.video_id == video_uuid))
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


def _run_agent(ctx):
    async def _inner():
        engine, session = await _session()
        try:
            return await PublishingAgent(db=session).run(ctx)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _ctx(video_id, **overrides):
    base = {
        "platform": "youtube",
        "video_id": str(video_id),
        "video_storage_path": _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": None,
        "dry_run": False,
    }
    base.update(overrides)
    return base


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-f5-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


def _tmp_thumbnail():
    path = Path(tempfile.mkstemp(prefix="pub-f5-", suffix=".jpg")[1])
    path.write_bytes(b"fake-jpeg")
    return str(path)


# ---------------------------------------------------------------------------
# Dry-run: validation only, ZERO Google API calls
# ---------------------------------------------------------------------------


def test_dry_run_upload_thumbnail_publish_zero_external_calls(monkeypatch):
    script = _Script()
    _install_real_youtube(monkeypatch, script)
    video_path = _tmp_video()
    thumb_path = _tmp_thumbnail()

    async def _adapter():
        engine, session = await _session()
        try:
            adapter = YouTubeAdapter(db=session, secrets=_FakeSecrets())
            up = await adapter.upload_content(
                file_path=video_path, title="t", is_dry_run=True
            )
            th = await adapter.upload_thumbnail(
                video_content_id="dry", thumbnail_path=thumb_path, is_dry_run=True
            )
            pub = await adapter.publish(
                content_id="dry", is_dry_run=True, privacy_status="public"
            )
            return up, th, pub, adapter
        finally:
            await session.close()
            await engine.dispose()

    up, th, pub, adapter = asyncio.run(_adapter())
    assert up.success and up.content_id.startswith("dry_run_upload_")
    assert th.success and th.content_id.startswith("dry_run_upload_")
    assert pub.success and pub.published_content_id.startswith("dry_run_post_")
    # ZERO external Google API calls, and no client was even built.
    assert script.counters == {"insert_calls": 0, "update_calls": 0, "thumbnail_calls": 0}
    assert adapter._youtube_client is None


def test_agent_dry_run_flow_makes_zero_external_calls(monkeypatch):
    script = _Script()
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid, dry_run=True)
    try:
        result = _run_agent(ctx)
        assert result.success, result.error
        assert result.output["published_video_id"].startswith("dry_run_post_")
        assert script.counters == {
            "insert_calls": 0,
            "update_calls": 0,
            "thumbnail_calls": 0,
        }
        assert asyncio.run(_attempts_for(video_uuid)) == []  # dry-run records no attempt
    finally:
        asyncio.run(_cleanup(video_uuid))


# ---------------------------------------------------------------------------
# Real execution: success
# ---------------------------------------------------------------------------


def test_real_upload_and_publish_succeed(monkeypatch):
    script = _Script()
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        result = _run_agent(ctx)
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].external_content_id == "yt-video-1"
        assert rows[0].external_post_id == "yt-video-1"  # youtube: publish returns the upload id
        assert script.counters == {"insert_calls": 1, "update_calls": 1, "thumbnail_calls": 0}
    finally:
        asyncio.run(_cleanup(video_uuid))


# ---------------------------------------------------------------------------
# Confirmed / pre-dispatch failures -> FAILED, retryable
# ---------------------------------------------------------------------------


def test_confirmed_4xx_is_failed_and_retry_admits_new_attempt(monkeypatch):
    script = _Script(publish=("http_status", 409))
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" not in first.error
        assert "HTTP 409" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]

        script.publish_behavior = ("ok", None)
        second = _run_agent(ctx)
        assert second.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        assert script.counters["update_calls"] == 2  # the one legitimate retry
    finally:
        asyncio.run(_cleanup(video_uuid))


def test_pre_dispatch_transport_failure_is_failed_and_retryable(monkeypatch):
    script = _Script(publish=("raise", ConnectionRefusedError("connection refused")))
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" not in first.error
        assert "request not sent" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]

        script.publish_behavior = ("ok", None)
        second = _run_agent(ctx)
        assert second.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
    finally:
        asyncio.run(_cleanup(video_uuid))


# ---------------------------------------------------------------------------
# Ambiguous post-submission outcomes -> UNKNOWN, retry blocked
# ---------------------------------------------------------------------------


def test_timeout_after_dispatch_is_unknown_and_never_retryable_failed(monkeypatch):
    """The core F5 invariant: an ambiguous publish failure (timeout after
    submission) lands UNKNOWN; a re-submission of the same intent NEVER
    invokes the provider publish again — it can never produce a retryable
    FAILED attempt."""
    script = _Script(publish=("raise", TimeoutError("read timed out after submission")))
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert rows[0].external_content_id == "yt-video-1"  # anchor persisted
        assert script.counters["update_calls"] == 1

        second = _run_agent(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert script.counters["update_calls"] == 1  # no second publication attempt
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN
    finally:
        asyncio.run(_cleanup(video_uuid))


def test_5xx_after_submission_is_unknown_and_blocks_retry(monkeypatch):
    script = _Script(publish=("http_status", 503))
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        first = _run_agent(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]

        second = _run_agent(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert script.counters["update_calls"] == 1
    finally:
        asyncio.run(_cleanup(video_uuid))


def test_upload_timeout_is_unknown(monkeypatch):
    script = _Script(upload=("raise", TimeoutError("timed out mid resumable upload")))
    _install_real_youtube(monkeypatch, script)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid)
    try:
        result = _run_agent(ctx)
        assert not result.success and "UNKNOWN" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert script.counters["update_calls"] == 0  # never reached publish
    finally:
        asyncio.run(_cleanup(video_uuid))
