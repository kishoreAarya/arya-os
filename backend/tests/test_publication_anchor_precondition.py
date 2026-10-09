"""Phase 54B-I2 — external-content anchor precondition tests.

Proves the invariant: adapter.publish() (and the thumbnail upload) are
UNREACHABLE unless persistence of the external-content anchor is
POSITIVELY CONFIRMED (row matched AND committed). Every failure shape —
CAS refusal, raised exception, ambiguous commit, upload success without
a media id — aborts publication with truthful attempt state and safe
operator evidence, and never auto-retries.

Real production call path: the REAL PublishingAgent, the REAL approval
gate, the REAL state machine and database, and the REAL PostizAdapter
decision logic (only the httpx transport is scripted, reusing the F1
regression harness pattern). No providers are contacted.
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
from app.platforms.base import AuthResult, PublishResult, UploadResult
from app.platforms.postiz import PostizAdapter
from app.services.publication_attempts import (
    TransitionOutcome,
    admit_attempt,
    persist_external_content_anchor,
)


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
    """httpx.AsyncClient stand-in scripting the Postiz endpoints; real
    httpx Response/exception objects (F1 harness pattern)."""

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
        self, *, upload_behavior=("ok", "media-A1"), publish_behavior=("ok", "post-1")
    ):
        self.upload_behavior = upload_behavior
        self.publish_behavior = publish_behavior
        self.upload_calls = 0
        self.posts_calls = 0
        self.on_upload = None


def _install_real_postiz(monkeypatch, transport):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: PostizAdapter(db=db, secrets=_FakeSecrets()),
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: _ScriptedClient(transport, **kwargs)
    )


class _NoIdAdapter:
    """Stub adapter for the upload-success-without-media-id window: the
    only adapter behavior under test is UploadResult(success=True,
    content_id=None) on a REAL publish path."""

    def __init__(self):
        self.upload_calls = 0
        self.publish_calls = 0

    async def authenticate(self):
        return AuthResult(success=True, credentials={"api_key": "stub"})

    async def upload_content(self, **kwargs):
        self.upload_calls += 1
        return UploadResult(
            success=True, content_id=None, storage_path=kwargs.get("file_path")
        )

    async def upload_thumbnail(self, **kwargs):
        return UploadResult(success=True, content_id="thumb")

    async def publish(self, **kwargs):
        self.publish_calls += 1
        return PublishResult(
            success=True, published_content_id="post-leak", publish_status="published"
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


def _revoke_approval(run_id):
    """Flip the seeded APPROVE to REVOKE-latest (cache + history) via
    direct SQL — test setup only, the gate reads the latest decision."""

    async def _inner():
        from app.models.approval import ApprovalCheckpoint, ApprovalDecision
        from app.models.enums import ApprovalAction
        from sqlalchemy import select, update

        engine, session = await _session()
        try:
            checkpoint = (
                (
                    await session.execute(
                        select(ApprovalCheckpoint).where(
                            ApprovalCheckpoint.workflow_run_id == run_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            await session.execute(
                update(ApprovalDecision)
                .where(ApprovalDecision.checkpoint_id == checkpoint.id)
                .values(action=ApprovalAction.REVOKE)
            )
            await session.execute(
                update(ApprovalCheckpoint)
                .where(ApprovalCheckpoint.id == checkpoint.id)
                .values(action=ApprovalAction.REVOKE)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="pub-i2-", suffix=".mp4")[1])
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


def _resolve_attempt_failed_async(video_uuid):
    """Simulate an operator force-FAILED resolution landing mid-flight
    (direct SQL — the reconciliation floor does not apply to raw test
    setup). Returns an awaitable for the scripted transport hook."""

    async def _inner():
        from sqlalchemy import update

        engine, session = await _session()
        try:
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.video_id == video_uuid)
                .values(status=PublicationAttemptStatus.FAILED)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    return _inner


# ---------------------------------------------------------------------------
# Precondition holds: every failure shape aborts BEFORE publish
# ---------------------------------------------------------------------------


def test_anchor_persisted_publication_completes(monkeypatch):
    """Happy path: positively confirmed anchor persistence is the only
    route through to adapter.publish()."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert result.success, result.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_content_id == "media-A1"
        assert rows[0].external_post_id == "post-1"
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_anchor_cas_refusal_prevents_publish(monkeypatch):
    """An operator resolution landing between the upload and the anchor
    CAS refuses the anchor write; the resolution stands and NO publish
    (or thumbnail upload) is dispatched. The orphaned media id is
    surfaced for manual cleanup."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport(upload_behavior=("ok", "media-ORPH2"))
    transport.on_upload = _resolve_attempt_failed_async(video_id)
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "Publication aborted" in result.error
        assert "the attempt is now failed" in result.error
        assert "external-content anchor could not be persisted" in result.error
        assert "no thumbnail upload or external publish was made" in result.error
        # Safe reconciliation evidence: the orphan id is named.
        assert "media-ORPH2" in result.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        # The operator resolution stands; the agent wrote nothing.
        assert rows[0].external_content_id is None
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_anchor_exception_prevents_publish(monkeypatch):
    """persist_external_content_anchor raising (DB execute failure)
    aborts publication; the attempt lands UNKNOWN (the upload DID
    happen); no automatic retry occurs."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport(upload_behavior=("ok", "media-EXC3"))
    _install_real_postiz(monkeypatch, transport)

    async def _raising_anchor(db, attempt, content_id):
        raise RuntimeError("simulated database execute failure")

    monkeypatch.setattr(
        "app.services.publication_attempts.persist_external_content_anchor",
        _raising_anchor,
    )
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "Publication aborted" in result.error
        assert "media-EXC3" in result.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        # Second submission of the same intent: admission is blocked by
        # UNKNOWN — the provider upload is NEVER repeated automatically.
        second = _run_agent(_ctx(video_id, run_id))
        assert not second.success and "AMBIGUOUS" in second.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 0
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_anchor_uncertain_commit_prevents_publish(monkeypatch):
    """An ambiguous commit outcome (UNCERTAIN) aborts publication, best-
    effort records UNKNOWN, and names the orphaned media id."""
    run_id, video_id = _seed_target()
    transport = _ScriptedTransport(upload_behavior=("ok", "media-AMB4"))
    _install_real_postiz(monkeypatch, transport)

    async def _uncertain_anchor(db, attempt, content_id):
        return TransitionOutcome.UNCERTAIN

    monkeypatch.setattr(
        "app.services.publication_attempts.persist_external_content_anchor",
        _uncertain_anchor,
    )
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "Publication aborted" in result.error
        assert "UNCERTAIN database outcome" in result.error
        assert "may or may not be recorded" in result.error
        assert "media-AMB4" in result.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_upload_success_without_media_id_prevents_publish(monkeypatch):
    """Upload success with NO provider media id makes an anchor
    impossible: publish is unreachable and the attempt lands UNKNOWN
    (the provider may hold media of unknown identity)."""
    run_id, video_id = _seed_target()
    stub = _NoIdAdapter()
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: stub,
    )
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert "no provider media id" in result.error
        assert "aborted before any thumbnail upload or publish call" in result.error
        assert stub.upload_calls == 1
        assert stub.publish_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert rows[0].external_content_id is None
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


# ---------------------------------------------------------------------------
# Unchanged behavior pins
# ---------------------------------------------------------------------------


def test_approval_denial_unchanged_by_precondition(monkeypatch):
    """A revoked approval still denies before any attempt, upload, or
    publish (Phase 53B semantics intact)."""
    run_id, video_id = _seed_target()
    _revoke_approval(run_id)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(video_id, run_id))
        assert not result.success
        assert result.error.startswith("publish_approval_denied:")
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        assert _attempts_for(video_id) == []
    finally:
        _cleanup_attempts(video_id)
        _cleanup_target(run_id)


def test_dry_run_unchanged_by_precondition(monkeypatch):
    """Dry-run: no attempt row, no anchor writes, ZERO transport calls
    (the real adapter's dry-run branches validate only), and the flow
    still completes successfully end to end."""
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


# ---------------------------------------------------------------------------
# Service-level outcomes of persist_external_content_anchor itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_anchor_service_outcomes():
    """Direct verification of the three persistence outcomes on real
    rows: PERSISTED, REFUSED (resolved underneath), and UNCERTAIN
    (execute raises / commit raises — the ambiguous-commit window)."""
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

        # PERSISTED: positively confirmed success.
        outcome = await persist_external_content_anchor(session, attempt, "media-S1")
        assert outcome is TransitionOutcome.PERSISTED
        row = (
            await session.execute(
                select(PublicationAttempt).where(PublicationAttempt.id == attempt.id)
            )
        ).scalar_one()
        assert row.external_content_id == "media-S1"

        # REFUSED: the row moved underneath (operator resolution).
        await session.execute(
            update(PublicationAttempt)
            .where(PublicationAttempt.id == attempt.id)
            .values(status=PublicationAttemptStatus.FAILED)
        )
        await session.commit()
        outcome = await persist_external_content_anchor(session, attempt, "media-S2")
        assert outcome is TransitionOutcome.REFUSED
        await session.refresh(row)
        assert row.external_content_id == "media-S1"  # nothing overwritten
    finally:
        await session.close()
        await engine.dispose()
    await _cleanup_attempts_sync(video_uuid)

    # UNCERTAIN (execute raises): fail closed, nothing reported persisted.
    engine, session = await _session()
    try:
        attempt, _ = await admit_attempt(
            session,
            video_id=video_uuid,
            platform="postiz",
            social_platform="youtube",
            integration_id="integ-1",
        )

        class _ExecuteRaising:
            def __init__(self, inner):
                self._inner = inner

            async def execute(self, *a, **k):
                raise RuntimeError("simulated execute failure")

            def __getattr__(self, name):
                return getattr(self._inner, name)

        outcome = await persist_external_content_anchor(
            _ExecuteRaising(session), attempt, "media-S3"
        )
        assert outcome is TransitionOutcome.UNCERTAIN
    finally:
        await session.close()
        await engine.dispose()
    await _cleanup_attempts_sync(video_uuid)

    # UNCERTAIN (commit raises AFTER a matched execute): the ambiguous-
    # commit window — the write may or may not have landed server-side,
    # and the caller must never be told it persisted.
    engine, session = await _session()
    try:
        attempt, _ = await admit_attempt(
            session,
            video_id=video_uuid,
            platform="postiz",
            social_platform="youtube",
            integration_id="integ-1",
        )

        class _CommitRaising:
            def __init__(self, inner):
                self._inner = inner

            async def commit(self):
                raise RuntimeError("simulated ambiguous commit")

            def __getattr__(self, name):
                return getattr(self._inner, name)

        outcome = await persist_external_content_anchor(
            _CommitRaising(session), attempt, "media-S4"
        )
        assert outcome is TransitionOutcome.UNCERTAIN
    finally:
        await session.close()
        await engine.dispose()
    await _cleanup_attempts_sync(video_uuid)


async def _cleanup_attempts_sync(video_uuid):
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


def test_non_uuid_video_id_real_publish_refused(monkeypatch):
    """A real (non-dry-run) dispatch whose video id admits no attempt
    record is refused before ANY external call. In the production path
    the 53B gate refuses the non-UUID id first (invalid_identifier);
    the agent-level guard is downstream defense-in-depth for the same
    invariant: no trackable attempt -> no publish."""
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    ctx = {
        "platform": "postiz",
        "video_id": "not-a-uuid",
        "video_storage_path": _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "dry_run": False,
        "workflow_run_id": str(uuid.uuid4()),
    }
    result = _run_agent(ctx)
    assert not result.success
    assert result.error.startswith("publish_approval_denied:")
    assert transport.upload_calls == 0
    assert transport.posts_calls == 0
