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
import pytest
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


class _ListRequest:
    """videos().list(...) request with scripted execute(). The scripted
    payload is the full videos.list response dict (or an Exception
    instance to raise)."""

    def __init__(self, script):
        self._script = script

    def execute(self):
        if isinstance(self._script.list_response, Exception):
            raise self._script.list_response
        return self._script.list_response


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

    def list(self, *, part, id):
        # Recorded on the SCRIPT, not the counters dict (existing tests
        # assert counters by exact dict equality): proves the F-08
        # request shape.
        self._script.list_calls += 1
        self._script.last_list_part = part
        self._script.last_list_id = id
        return _ListRequest(self._script)


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
    ("raise", exception). list_response is the scripted videos.list
    response dict (or an Exception to raise)."""

    def __init__(
        self,
        *,
        upload=("ok", "yt-video-1"),
        publish=("ok", None),
        thumbnail=("ok", None),
        list_response=None,
    ):
        self.upload_behavior = upload
        self.publish_behavior = publish
        self.thumbnail_behavior = thumbnail
        if list_response is None:
            list_response = {
                "items": [
                    {
                        "processingDetails": {"processingStatus": "succeeded"},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }
        self.list_response = list_response
        # F-08 request-shape recording (kept OFF the counters dict).
        self.list_calls = 0
        self.last_list_part = None
        self.last_list_id = None
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


# ---------------------------------------------------------------------------
# F-08: publication-evidence semantics — processing completion is NOT proof
# of public publication (check_processing fails closed without public
# visibility evidence).
# ---------------------------------------------------------------------------


def _evidence_items(processing_status=None, privacy=None):
    item = {}
    if processing_status is not None:
        item["processingDetails"] = {"processingStatus": processing_status}
    if privacy is not None:
        item["status"] = {"privacyStatus": privacy}
    return {"items": [item]}


def _yt_check(content_id="yt-ev-1"):
    async def _inner():
        adapter = YouTubeAdapter(db=None, secrets=_FakeSecrets())
        return await adapter.check_processing(content_id=content_id)

    return asyncio.run(_inner())


def test_f08_ready_requires_succeeded_processing_and_public_privacy(monkeypatch):
    script = _Script(list_response=_evidence_items("succeeded", "public"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "ready"
    assert processing.error is None


def test_f08_succeeded_private_is_not_ready(monkeypatch):
    script = _Script(list_response=_evidence_items("succeeded", "private"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "unknown"
    assert "private" in processing.error
    assert "not publicly published" in processing.error


def test_f08_succeeded_unlisted_is_not_ready(monkeypatch):
    script = _Script(list_response=_evidence_items("succeeded", "unlisted"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "unknown"
    assert "unlisted" in processing.error


def test_f08_succeeded_missing_or_unrecognized_privacy_fails_closed(monkeypatch):
    # No status part at all.
    script = _Script(list_response=_evidence_items("succeeded", None))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "unknown"
    assert "privacyStatus unavailable" in processing.error

    # Unrecognized privacy value.
    script = _Script(list_response=_evidence_items("succeeded", "weird"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "unknown"
    assert "weird" in processing.error


def test_f08_processing_failed_terminated_and_unknown_mappings_unchanged(monkeypatch):
    # processing -> "processing" (with progress), regardless of privacy.
    script = _Script(
        list_response={
            "items": [
                {
                    "processingDetails": {
                        "processingStatus": "processing",
                        "processingProgress": {"partsProcessed": 2, "partsTotal": 8},
                    },
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
    )
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "processing"
    assert processing.progress_percent == 25.0

    for yt_status in ("failed", "terminated"):
        script = _Script(list_response=_evidence_items(yt_status, "public"))
        _install_real_youtube(monkeypatch, script)
        assert _yt_check().status == "failed"

    # Unrecognized processingStatus stays fail-closed "unknown".
    script = _Script(list_response=_evidence_items("garbage", "public"))
    _install_real_youtube(monkeypatch, script)
    assert _yt_check().status == "unknown"


def test_f08_empty_items_and_exception_behavior_unchanged(monkeypatch):
    script = _Script(list_response={"items": []})
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "failed"
    assert "not found" in processing.error

    script = _Script(list_response=RuntimeError("transport died mid-lookup"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check()
    assert processing.status == "failed"
    assert "transport died" in processing.error


def test_f08_request_shape_includes_the_status_part(monkeypatch):
    script = _Script(list_response=_evidence_items("succeeded", "public"))
    _install_real_youtube(monkeypatch, script)
    processing = _yt_check(content_id="yt-shape-9")
    assert processing.status == "ready"
    assert script.list_calls == 1
    assert script.last_list_part == "processingDetails,status"
    assert script.last_list_id == "yt-shape-9"
    # The publish/insert paths are untouched by an evidence lookup.
    assert script.counters == {"insert_calls": 0, "update_calls": 0, "thumbnail_calls": 0}


def _make_yt_attempt(status, *, anchor="yt-ev-1"):
    """Admit a YouTube attempt for a fresh video and drive it to `status`
    via the REAL transition helpers, with the upload anchor persisted."""

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
                platform="youtube",
                social_platform="youtube",
                integration_id=None,
            )
            attempt.external_content_id = anchor
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


def _age_yt_attempt(attempt_id, hours=1):
    from datetime import datetime, timedelta, timezone

    async def _inner():
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

    asyncio.run(_inner())


def _svc_resolve(attempt_id, **kwargs):
    async def _inner():
        from app.services import publication_attempt_reconciliation as recon

        engine, session = await _session()
        try:
            return await recon.resolve_attempt(session, attempt_id, **kwargs)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _install_recon_youtube(monkeypatch):
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: YouTubeAdapter(db=db, secrets=_FakeSecrets()),
    )


def test_f08_unknown_to_succeeded_resolution_fails_closed_on_private_video(monkeypatch):
    """Operator reconciliation: UNKNOWN -> SUCCEEDED against a
    processed-but-PRIVATE YouTube video must refuse (fail closed); the
    attempt is unchanged."""
    from app.services import publication_attempt_reconciliation as recon

    script = _Script(list_response=_evidence_items("succeeded", "private"))
    _install_real_youtube(monkeypatch, script)
    _install_recon_youtube(monkeypatch)
    aid, vu = _make_yt_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        with pytest.raises(recon.VerificationFailedError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="yt-post-9",
            )
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.UNKNOWN  # unchanged
    finally:
        asyncio.run(_cleanup(vu))


def test_f08_in_progress_to_succeeded_resolution_fails_closed_on_private_video(monkeypatch):
    """H2: IN_PROGRESS -> SUCCEEDED against a processed-but-private
    video must refuse (fail closed); the attempt is unchanged."""
    from app.services import publication_attempt_reconciliation as recon

    script = _Script(list_response=_evidence_items("succeeded", "private"))
    _install_real_youtube(monkeypatch, script)
    _install_recon_youtube(monkeypatch)
    aid, vu = _make_yt_attempt(PublicationAttemptStatus.IN_PROGRESS)
    _age_yt_attempt(aid, hours=1)
    try:
        with pytest.raises(recon.VerificationFailedError):
            _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="yt-post-9",
            )
        rows = asyncio.run(_attempts_for(vu))
        assert rows[0].status == PublicationAttemptStatus.IN_PROGRESS  # unchanged
    finally:
        asyncio.run(_cleanup(vu))


def test_f08_resolution_succeeds_on_verified_public_video(monkeypatch):
    """Positive control: with processing succeeded AND public visibility,
    the same reconciliation path resolves (the gate does not
    over-block)."""
    script = _Script(list_response=_evidence_items("succeeded", "public"))
    _install_real_youtube(monkeypatch, script)
    _install_recon_youtube(monkeypatch)
    aid, vu = _make_yt_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.SUCCEEDED,
            external_post_id="yt-post-9",
        )
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert audit["verification"]["provider_status"] == "ready"
    finally:
        asyncio.run(_cleanup(vu))


# ---------------------------------------------------------------------------
# F-02a: evidence-gated FAILED resolutions — anchored YouTube matrix
# (one-sided: refuse only on verified-public "ready"; all other outcomes
# leave the operator attestation authoritative)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "processing_status,privacy,refused",
    [
        ("succeeded", "public", True),    # 1. verified publicly live -> REFUSED
        ("succeeded", "private", False),  # 2. private -> attestation authoritative
        ("succeeded", "unlisted", False), # 3. unlisted -> allowed
        ("processing", "public", False),  # 4. still processing -> allowed
        ("failed", None, False),          # 5. failed/not-found -> allowed
    ],
)
def test_f02a_youtube_anchored_failed_matrix(monkeypatch, processing_status, privacy, refused):
    from app.services import publication_attempt_reconciliation as recon

    script = _Script(list_response=_evidence_items(processing_status, privacy))
    _install_real_youtube(monkeypatch, script)
    _install_recon_youtube(monkeypatch)
    aid, vu = _make_yt_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        if refused:
            with pytest.raises(recon.VerificationFailedError) as excinfo:
                _svc_resolve(
                    aid,
                    from_status=PublicationAttemptStatus.UNKNOWN,
                    to_status=PublicationAttemptStatus.FAILED,
                    attestation="operator believes no post exists",
                )
            assert "publicly live" in str(excinfo.value)
            rows = asyncio.run(_attempts_for(vu))
            assert rows[0].status == PublicationAttemptStatus.UNKNOWN  # unchanged
        else:
            attempt, audit = _svc_resolve(
                aid,
                from_status=PublicationAttemptStatus.UNKNOWN,
                to_status=PublicationAttemptStatus.FAILED,
                attestation="verified no public post",
            )
            assert attempt.status == PublicationAttemptStatus.FAILED
            assert audit["verification"]["gate"] == "failed_resolution_evidence"
    finally:
        asyncio.run(_cleanup(vu))


def test_f02a_youtube_evidence_api_error_allows_failed(monkeypatch):
    """6. Evidence lookup raising (API/transport error) never blocks the
    manual FAILED resolution."""
    from app.services import publication_attempt_reconciliation as recon

    script = _Script(list_response=RuntimeError("youtube api broke during lookup"))
    _install_real_youtube(monkeypatch, script)
    _install_recon_youtube(monkeypatch)
    aid, vu = _make_yt_attempt(PublicationAttemptStatus.UNKNOWN)
    try:
        attempt, audit = _svc_resolve(
            aid,
            from_status=PublicationAttemptStatus.UNKNOWN,
            to_status=PublicationAttemptStatus.FAILED,
            attestation="verified no public post",
        )
        assert attempt.status == PublicationAttemptStatus.FAILED
        assert audit["verification"]["gate"] == "failed_resolution_evidence"
    finally:
        asyncio.run(_cleanup(vu))
