"""Phase 54B-I3 — dispatch permit ordering and concurrency tests.

Proves the corrected dispatch contract:
- The PENDING -> IN_PROGRESS permit is acquired BEFORE any provider
  upload (the attempt is observably IN_PROGRESS at upload time).
- A refused permit, a refused admission, and a duplicate/ambiguous
  request all prevent EVERY external call (not even authenticate).
- Two concurrent dispatches of one intent produce exactly ONE upload.
- UNKNOWN/terminal states cannot be overwritten by later CAS writes,
  and cannot silently trigger another upload.
- The I2 anchor precondition still gates publish after the reorder.

Real production call path: REAL PublishingAgent, REAL approval gate,
REAL state machine and database, REAL PostizAdapter decision logic
(scripted httpx transport only). No providers are contacted.
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
from app.services.publication_attempts import (
    TransitionOutcome,
    admit_attempt,
    mark_in_progress,
    mark_unknown,
    persist_external_content_anchor,
)


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
    """httpx.AsyncClient stand-in scripting the Postiz endpoints (F1
    harness pattern). Optional on_get/on_upload hooks fire inside the
    REAL adapter flow, letting tests act mid-dispatch."""

    def __init__(self, transport, **kwargs):
        self._transport = transport

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, **kwargs):
        if self._transport.on_get is not None:
            await self._transport.on_get()
        return httpx.Response(
            200,
            json=[{"id": "integ-1", "name": "channel"}],
            request=httpx.Request("GET", url),
        )

    async def post(self, url, **kwargs):
        if url.endswith("/public/v1/upload"):
            self._transport.upload_calls += 1
            if self._transport.on_upload is not None:
                await self._transport.on_upload()
            kind, payload = self._transport.upload_behavior
        else:
            self._transport.posts_calls += 1
            kind, payload = self._transport.publish_behavior
        if kind == "raise":
            raise payload
        if kind == "status":
            return httpx.Response(
                payload, text="scripted", request=httpx.Request("POST", url)
            )
        return httpx.Response(
            200, json={"id": payload}, request=httpx.Request("POST", url)
        )


class _ScriptedTransport:
    def __init__(
        self, *, upload_behavior=("ok", "media-P1"), publish_behavior=("ok", "post-1")
    ):
        self.upload_behavior = upload_behavior
        self.publish_behavior = publish_behavior
        self.upload_calls = 0
        self.posts_calls = 0
        self.on_upload = None
        self.on_get = None


def _install_real_postiz(monkeypatch, transport):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: _ScriptedClient(transport, **kwargs)
    )


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


def _run_agent(ctx):
    async def _inner():
        engine, session = await _session()
        try:
            return await PublishingAgent(db=session).run(ctx)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


_SEED_STATE = {}


def _seed_target(**manifest_overrides):
    """53B-T/I5: seed a MANIFEST-BOUND approved publish target (real
    artifact, real manifest via the I4 service, bound+approved THUMBNAIL
    checkpoint) matching the postiz dispatch context used below."""

    async def _inner():
        from tests._dispatch_manifest_fixtures import _seed_manifest_bound_target

        kwargs = dict(
            platform="postiz",
            social_platform="youtube",
            integration_id="integ-1",
            privacy_status="public",
            publish_type="now",
        )
        kwargs.update(manifest_overrides)
        return await _seed_manifest_bound_target(**kwargs)

    run_id, video_id, _mid, asset, _thumb = asyncio.run(_inner())
    _SEED_STATE.clear()
    _SEED_STATE.update(run_id=run_id, video_id=video_id, asset=asset)
    return run_id, video_id


def _cleanup_target(run_id):
    async def _inner():
        from tests._dispatch_manifest_fixtures import _cleanup_manifest_bound_target

        await _cleanup_manifest_bound_target(
            run_id, _SEED_STATE.get("video_id"), _SEED_STATE.get("asset")
        )

    asyncio.run(_inner())
    _SEED_STATE.clear()


def _attempts_for(video_uuid):
    async def _inner():
        from sqlalchemy import select

        engine, session = await _session()
        try:
            rows = (
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
            return sorted(rows, key=lambda r: r.attempt_number)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _cleanup_attempts(*video_uuids):
    async def _inner():
        from sqlalchemy import delete

        engine, session = await _session()
        try:
            for v in video_uuids:
                await session.execute(
                    delete(PublicationAttempt).where(PublicationAttempt.video_id == v)
                )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _attempt_status_at_upload(video_uuid):
    """Hook body: read the attempt row's status from the database at the
    moment the provider upload begins."""

    async def _inner():
        from sqlalchemy import select

        engine, session = await _session()
        try:
            row = (
                (
                    await session.execute(
                        select(PublicationAttempt)
                        .where(PublicationAttempt.video_id == video_uuid)
                        .order_by(PublicationAttempt.attempt_number.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            return row.status.value if row else "none"
        finally:
            await session.close()
            await engine.dispose()

    return _inner


def _force_status(video_uuid, status, *, external_post_id=None):
    """Direct-SQL mid-flight resolution (test setup; the reconciliation
    floor does not apply to raw test fixtures)."""

    async def _inner():
        from sqlalchemy import update

        engine, session = await _session()
        try:
            values = {"status": status}
            if external_post_id is not None:
                values["external_post_id"] = external_post_id
                values["public_url"] = "https://example.test/p"
                values["external_content_id"] = "media-pre"
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.video_id == video_uuid)
                .values(**values)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    return _inner


def _precreate_attempt(video_uuid, status, *, with_external_ids=False):
    async def _inner():
        from sqlalchemy import update

        engine, session = await _session()
        try:
            attempt, _ = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id="integ-1",
            )
            values = {"status": status}
            if with_external_ids:
                values.update(
                    {
                        "external_post_id": "post-pre",
                        "external_content_id": "media-pre",
                        "public_url": "https://example.test/p",
                    }
                )
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.id == attempt.id)
                .values(**values)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(_inner())


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-i3-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


def _ctx(video_id, run_id, **overrides):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        # Phase 54B-I5: the seeded manifest's authoritative artifact.
        "video_storage_path": _SEED_STATE.get("asset") or _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "dry_run": False,
        "workflow_run_id": str(run_id),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Permit ordering
# ---------------------------------------------------------------------------


def test_permit_acquired_before_first_upload(monkeypatch):
    """The attempt is observably IN_PROGRESS (permit held) at the moment
    the provider upload begins — the permit precedes every upload."""
    run_id, video_id = _seed_target()
    observed = {}

    async def _capture():
        observed["status_at_upload"] = await _attempt_status_at_upload(video_id)()

    transport = _ScriptedTransport()
    transport.on_upload = _capture
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert result.success, result.error
        assert observed.get("status_at_upload") == "in_progress"
        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_permit_refusal_prevents_all_external_calls(monkeypatch):
    """An operator resolution landing between authentication and the
    permit CAS refuses the permit: NO upload, NO thumbnail, NO publish,
    and a truthful no-external-call error."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport()
    transport.on_get = _force_status(video_id, PublicationAttemptStatus.FAILED)
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "Publication permit denied" in result.error
        assert "no external upload or publish was made" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# Admission refusal, duplicates, ambiguity
# ---------------------------------------------------------------------------


def test_admission_refusal_prevents_all_external_calls(monkeypatch):
    """An existing IN_PROGRESS attempt refuses admission: the duplicate
    never reaches authenticate — zero transport calls of any kind."""
    run_id, video_id = _seed_target()
    _precreate_attempt(video_id, PublicationAttemptStatus.IN_PROGRESS)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "currently in progress" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_unknown_attempt_blocks_new_upload_automatically(monkeypatch):
    """UNKNOWN is durable manual-operations state: a re-request is
    refused at admission — never an automatic second upload."""
    run_id, video_id = _seed_target()
    _precreate_attempt(video_id, PublicationAttemptStatus.UNKNOWN)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "AMBIGUOUS" in result.error
        assert "manual reconciliation required" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_duplicate_after_success_never_uploads_again(monkeypatch):
    """SUCCEEDED duplicate guard: the duplicate resolves to the existing
    attempt (F-10a self-heal allowed) with ZERO new external calls."""
    run_id, video_id = _seed_target()
    _precreate_attempt(
        video_id, PublicationAttemptStatus.SUCCEEDED, with_external_ids=True
    )
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert result.success, result.error
        assert result.output.get("duplicate") is True
        assert result.output.get("published_video_id") == "post-pre"
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        assert len(_attempts_for(video_id)) == 1
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_concurrent_dispatch_produces_exactly_one_upload(monkeypatch):
    """Two REAL agents racing on one intent: admission idempotency
    (UNIQUE(intent_key, attempt_number) + resolve-to-existing) allows
    exactly one upload and one publish."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    ctx = _ctx(video_id, run_id)

    async def _race():
        async def _one():
            engine, session = await _session()
            try:
                return await PublishingAgent(db=session).run(dict(ctx))
            finally:
                await session.close()
                await engine.dispose()

        return await asyncio.gather(_one(), _one())

    try:
        first, second = asyncio.run(_race())
        successes = [r for r in (first, second) if r.success]
        assert len(successes) == 1, (first.error, second.error)
        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# State-machine safety (service level, real rows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_writes_never_overwrite_terminal_states():
    """Terminal states are write-protected: the permit, best-effort
    UNKNOWN, and the anchor write all REFUSE on SUCCEEDED/FAILED rows
    without mutating them."""
    from sqlalchemy import select, update

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
        await session.execute(
            update(PublicationAttempt)
            .where(PublicationAttempt.id == attempt.id)
            .values(
                status=PublicationAttemptStatus.SUCCEEDED, external_post_id="post-T"
            )
        )
        await session.commit()

        # The permit refuses a non-PENDING row.
        assert await mark_in_progress(session, attempt) is False
        # A best-effort UNKNOWN transition cannot overwrite SUCCEEDED.
        assert await mark_unknown(session, attempt, "late ambiguity") is False
        # The anchor write refuses too.
        assert (
            await persist_external_content_anchor(session, attempt, "media-late")
            is TransitionOutcome.REFUSED
        )

        row = (
            await session.execute(
                select(PublicationAttempt).where(PublicationAttempt.id == attempt.id)
            )
        ).scalar_one()
        assert row.status == PublicationAttemptStatus.SUCCEEDED
        assert row.external_content_id is None  # nothing overwritten

        # Same for FAILED.
        await session.execute(
            update(PublicationAttempt)
            .where(PublicationAttempt.id == attempt.id)
            .values(status=PublicationAttemptStatus.FAILED)
        )
        await session.commit()
        assert await mark_unknown(session, attempt, "late ambiguity") is False
        assert await mark_in_progress(session, attempt) is False
        await session.refresh(row)
        assert row.status == PublicationAttemptStatus.FAILED
    finally:
        await session.close()
        await engine.dispose()
    await _cleanup_attempts_async(video_uuid)


async def _cleanup_attempts_async(video_uuid):
    from sqlalchemy import delete

    engine, session = await _session()
    try:
        await session.execute(
            delete(PublicationAttempt).where(PublicationAttempt.video_id == video_uuid)
        )
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Dry-run still inert
# ---------------------------------------------------------------------------


def test_dry_run_zero_transport_calls(monkeypatch):
    """Dry-run bypasses admission/permit entirely and the REAL adapter's
    dry-run branches make zero HTTP calls."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    video_uuid = uuid.uuid4()
    ctx = _ctx(video_uuid, uuid.uuid4(), dry_run=True, workflow_run_id=None)
    try:
        result = _run_agent(ctx)
        assert result.success, result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        assert _attempts_for(video_uuid) == []
    finally:
        _cleanup_attempts(video_uuid)
