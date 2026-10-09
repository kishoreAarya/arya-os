"""Phase 54B-I5 — dispatch-time manifest verification tests.

Real production paths: REAL PublishingAgent, REAL approval gate and
authorize-and-permit transaction, REAL state machine and database, REAL
manifest services (creation/binding/verification), REAL PostizAdapter
decision logic (scripted httpx transport only). No providers are
contacted; artifacts are real bytes on disk.

Proves: authorization → manifest verification → stable snapshots →
permit → upload → anchor → publish, with every failure shape failing
closed BEFORE any external call.
"""

import asyncio
import hashlib
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.agents.publishing import PublishingAgent
from app.models.enums import ApprovalAction, PublicationAttemptStatus
from app.models.publication import PublicationAttempt, PublicationManifest
from app.platforms.postiz import PostizAdapter

from tests._dispatch_manifest_fixtures import (
    _cleanup_manifest_bound_target,
    _seed_manifest_bound_target,
)


class _FakeSecrets:
    def get(self, key, required=False):
        return "test-postiz-key" if key == "postiz_api_key" else None


class _ScriptedClient:
    """httpx.AsyncClient stand-in; captures the UPLOADED BYTES hash for
    the TOCTOU proof (test 12)."""

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
            files = kwargs.get("files") or {}
            uploaded = files.get("file")
            if uploaded:
                self._transport.uploaded_sha.append(
                    hashlib.sha256(uploaded[1]).hexdigest()
                )
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
        self, *, upload_behavior=("ok", "media-M1"), publish_behavior=("ok", "post-1")
    ):
        self.upload_behavior = upload_behavior
        self.publish_behavior = publish_behavior
        self.upload_calls = 0
        self.posts_calls = 0
        self.on_upload = None
        self.on_get = None
        self.uploaded_sha: list[str] = []


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
            return await PublishingAgent(db=session).run(dict(ctx))
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


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


def _manifest_row(manifest_id):
    async def _inner():
        engine, session = await _session()
        try:
            return await session.get(PublicationManifest, manifest_id)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _mutate_manifest_row(
    manifest_id, *, canonical_bytes=None, digest=None, video_id=None
):
    async def _inner():
        from sqlalchemy import update

        engine, session = await _session()
        try:
            values = {}
            if canonical_bytes is not None:
                values["canonical_bytes"] = canonical_bytes
            if digest is not None:
                values["manifest_digest"] = digest
            if video_id is not None:
                values["video_id"] = video_id
            await session.execute(
                update(PublicationManifest)
                .where(PublicationManifest.id == manifest_id)
                .values(**values)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(_inner())


def _select_decisions(checkpoint_id):
    from app.models.approval import ApprovalDecision
    from sqlalchemy import select

    return select(ApprovalDecision).where(
        ApprovalDecision.checkpoint_id == checkpoint_id
    )


def _update_checkpoint(checkpoint_id, action, decided_at):
    from app.models.approval import ApprovalCheckpoint
    from sqlalchemy import update

    return (
        update(ApprovalCheckpoint)
        .where(ApprovalCheckpoint.id == checkpoint_id)
        .values(action=action, decided_at=decided_at)
    )


def _authorizing_checkpoint(run_id):
    async def _inner():
        from app.models.approval import ApprovalCheckpoint
        from app.models.enums import ApprovalStage
        from sqlalchemy import select

        engine, session = await _session()
        try:
            return (
                (
                    await session.execute(
                        select(ApprovalCheckpoint)
                        .where(
                            ApprovalCheckpoint.workflow_run_id == run_id,
                            ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
                        )
                        .order_by(ApprovalCheckpoint.created_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _snapshots_on_disk() -> list[str]:
    return [str(p) for p in Path(tempfile.gettempdir()).glob("arya-i5-snapshot-*")]


def _ctx(run_id, video_id, asset, **overrides):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": asset,
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "privacy_status": "public",
        "publish_type": "now",
        "dry_run": False,
        "workflow_run_id": str(run_id),
    }
    base.update(overrides)
    return base


def _seed(**kwargs):
    return asyncio.run(_seed_manifest_bound_target(**kwargs))


def _cleanup(run_id, video_id, *assets):
    asyncio.run(_cleanup_manifest_bound_target(run_id, video_id, *assets))


# ---------------------------------------------------------------------------
# 1. Valid bound manifest + current approval permits dispatch
# ---------------------------------------------------------------------------


def test_valid_manifest_permits_dispatch(monkeypatch):
    video_bytes = b"i5-valid-video-bytes"
    run_id, video_id, manifest_id, asset, _ = _seed(video_bytes=video_bytes)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert result.success, result.error
        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        # The attempt row carries the approved manifest identity.
        assert rows[0].manifest_id == manifest_id
        # The EXACT verified bytes were uploaded (TOCTOU proof).
        assert transport.uploaded_sha == [hashlib.sha256(video_bytes).hexdigest()]
        # Snapshot cleanup: nothing left behind.
        assert _snapshots_on_disk() == []
    finally:
        _cleanup(run_id, video_id, asset)


# ---------------------------------------------------------------------------
# 2-3. Missing/foreign/corrupt manifest denials
# ---------------------------------------------------------------------------


def test_legacy_unbound_approval_denies_real_publish(monkeypatch):
    """The 53B-era seeding (approved but UNBOUND checkpoint) must no
    longer authorize real publication (I5 fail-closed integration)."""
    from tests._publish_gate_fixtures import seed_approved_publish_target

    async def _seed_legacy():
        engine, session = await _session()
        try:
            return await seed_approved_publish_target(session)
        finally:
            await session.close()
            await engine.dispose()

    run_id, video_id = asyncio.run(_seed_legacy())
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = str(Path(tempfile.mkstemp(prefix="i5-legacy-", suffix=".mp4")[1]))
    Path(asset).write_bytes(b"legacy")
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: no_content_bound_manifest" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        # The refusal is durably recorded as a FAILED attempt.
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
    finally:
        asyncio.run(_cleanup_attempts_only(video_id))
        from tests._publish_gate_fixtures import cleanup_publish_target

        async def _clean():
            engine, session = await _session()
            try:
                await cleanup_publish_target(session, run_id)
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_clean())
        Path(asset).unlink(missing_ok=True)


async def _cleanup_attempts_only(video_uuid):
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


def test_corrupted_manifest_bytes_deny_dispatch(monkeypatch):
    run_id, video_id, manifest_id, asset, _ = _seed()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        row = _manifest_row(manifest_id)
        tampered = row.canonical_bytes.replace(
            '"privacy_status":"public"', '"privacy_status":"private"'
        )
        if tampered == row.canonical_bytes:
            tampered = row.canonical_bytes[:-1]  # malformed truncation fallback
        _mutate_manifest_row(manifest_id, canonical_bytes=tampered)
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: manifest_integrity_failure" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)


def test_foreign_manifest_target_denies_dispatch(monkeypatch):
    run_a, vid_a, _mid_a, asset_a, _ = _seed(video_bytes=b"target-a")
    run_b, vid_b, mid_b, asset_b, _ = _seed(video_bytes=b"target-b")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        # Re-point run A's checkpoint binding at run B's manifest.
        checkpoint = _authorizing_checkpoint(run_a)

        async def _rebind():
            from app.models.approval import ApprovalCheckpoint
            from sqlalchemy import update

            engine, session = await _session()
            try:
                await session.execute(
                    update(ApprovalCheckpoint)
                    .where(ApprovalCheckpoint.id == checkpoint.id)
                    .values(publication_manifest_id=mid_b)
                )
                await session.commit()
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_rebind())
        result = _run_agent(_ctx(run_a, vid_a, asset_a))
        assert not result.success
        assert "publication_blocked: manifest_target_mismatch" in result.error
        assert transport.upload_calls == 0
    finally:
        _cleanup(run_a, vid_a, asset_a)
        _cleanup(run_b, vid_b, asset_b)


# ---------------------------------------------------------------------------
# 4-7. Artifact mutation / missing / size failures
# ---------------------------------------------------------------------------


def test_video_mutation_after_manifest_denies_dispatch(monkeypatch):
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"original-i5")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        Path(asset).write_bytes(b"tampered-different-content")
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: artifact_bytes_changed" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert _snapshots_on_disk() == []
    finally:
        _cleanup(run_id, video_id, asset)


def test_thumbnail_mutation_after_manifest_denies_dispatch(monkeypatch):
    thumb = str(Path(tempfile.mkstemp(prefix="i5-thumb-", suffix=".jpg")[1]))
    Path(thumb).write_bytes(b"thumb-original")
    run_id, video_id, _manifest_id, asset, _ = _seed(
        video_bytes=b"v-ok", thumbnail_path=thumb
    )
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        Path(thumb).write_bytes(b"thumb-tampered")
        result = _run_agent(_ctx(run_id, video_id, asset, thumbnail_storage_path=thumb))
        assert not result.success
        assert "publication_blocked: artifact_bytes_changed" in result.error
        assert transport.upload_calls == 0
        assert _snapshots_on_disk() == []
    finally:
        _cleanup(run_id, video_id, asset, thumb)


def test_missing_artifact_denies_dispatch(monkeypatch):
    run_id, video_id, _manifest_id, asset, _ = _seed()
    Path(asset).unlink()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: artifact_resolution_failed" in result.error
        assert transport.upload_calls == 0
    finally:
        _cleanup(run_id, video_id)


def test_caller_path_override_denied(monkeypatch):
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"path-authority")
    other = str(Path(tempfile.mkstemp(prefix="i5-other-", suffix=".mp4")[1]))
    Path(other).write_bytes(b"different-file")
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(run_id, video_id, other))
        assert not result.success
        assert "publication_blocked: manifest_path_mismatch" in result.error
        assert transport.upload_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)
        Path(other).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 8-9. Parameter and destination drift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override,code",
    [
        ({"privacy_status": "private"}, "parameter_drift:privacy_status"),
        ({"publish_type": "draft"}, "parameter_drift:publish_type"),
        ({"platform": "youtube"}, "parameter_drift:platform"),
        ({"social_platform": "tiktok"}, "parameter_drift:social_platform"),
        ({"integration_id": "integ-9"}, "parameter_drift:integration_id"),
        (
            {"scheduled_at": "2030-01-01T12:00:00Z"},
            "parameter_drift:scheduled_at",
        ),
    ],
)
def test_destination_parameter_drift_denies_dispatch(monkeypatch, override, code):
    run_id, video_id, _manifest_id, asset, _ = _seed()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(run_id, video_id, asset, **override))
        assert not result.success
        assert f"publication_blocked: {code}" in result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)


def test_content_drift_via_video_row_denies_dispatch(monkeypatch):
    """Editing the persisted Video row's title after approval is content
    drift — fresh approval required."""
    run_id, video_id, _manifest_id, asset, _ = _seed(title="approved title")

    async def _edit_video():
        from sqlalchemy import update

        engine, session = await _session()
        try:
            from app.models.media import Video

            await session.execute(
                update(Video).where(Video.id == video_id).values(title="edited title")
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        asyncio.run(_edit_video())
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: content_drift:title" in result.error
        assert transport.upload_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)


def test_shorts_transform_drift_denies_dispatch(monkeypatch):
    """Changing the aspect ratio on the Video row after approval changes
    the effective #Shorts transform — drift, fresh approval required."""
    run_id, video_id, _manifest_id, asset, _ = _seed(
        aspect_ratio="16:9", description="plain"
    )

    async def _edit_video():
        from app.models.media import Video
        from sqlalchemy import update

        engine, session = await _session()
        try:
            await session.execute(
                update(Video).where(Video.id == video_id).values(aspect_ratio="9:16")
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        asyncio.run(_edit_video())
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "publication_blocked: content_drift:" in result.error
        assert transport.upload_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)


# ---------------------------------------------------------------------------
# 10-11. Revocation and concurrent denial at permit time
# ---------------------------------------------------------------------------


def test_revoke_between_gate_and_permit_denies_dispatch(monkeypatch):
    """A REVOKE landing AFTER the early gate has authorized but BEFORE
    the authorize-and-permit transaction blocks every external call
    (the window the 53B gate could not close). The revoke fires during
    the read-only authenticate call — between gate and permit."""
    run_id, video_id, _manifest_id, asset, _ = _seed()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    checkpoint = _authorizing_checkpoint(run_id)

    async def _revoke_mid_flight():
        await _append_decision_async(checkpoint, ApprovalAction.REVOKE)

    transport.on_get = _revoke_mid_flight
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert "Publication permit denied" in result.error
        assert (
            "checkpoint_revoke" in result.error
            or "latest_decision_not_approve" in result.error
        )
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
    finally:
        _cleanup(run_id, video_id, asset)


async def _append_decision_async(checkpoint, action):
    from datetime import UTC, datetime

    from app.models.approval import ApprovalDecision

    engine, session = await _session()
    try:
        existing = list(
            (await session.execute(_select_decisions(checkpoint.id))).scalars().all()
        )
        decided_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            ApprovalDecision(
                checkpoint_id=checkpoint.id,
                sequence_number=len(existing) + 1,
                action=action,
                decided_at=decided_at,
            )
        )
        await session.execute(_update_checkpoint(checkpoint.id, action, decided_at))
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 12. TOCTOU: the uploaded bytes are the verified snapshot bytes
# ---------------------------------------------------------------------------


def test_uploaded_bytes_are_verified_snapshot_not_mutable_source(monkeypatch):
    """Mutating the SOURCE artifact DURING dispatch (after verification,
    before/regardless of the adapter's read) cannot change what is
    uploaded: the adapter reads the private snapshot, never the source."""
    video_bytes = b"i5-toctou-original-content"
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=video_bytes)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:

        async def _mutate_during_upload():
            Path(asset).write_bytes(b"MUTATED-DURING-DISPATCH")

        transport.on_upload = _mutate_during_upload
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert result.success, result.error
        # The provider received the EXACT verified bytes — not the
        # mid-flight mutation of the mutable source.
        assert transport.uploaded_sha == [hashlib.sha256(video_bytes).hexdigest()]
        assert _snapshots_on_disk() == []
        # The mutated source file itself is NOT deleted (user-owned).
        assert Path(asset).exists()
    finally:
        _cleanup(run_id, video_id, asset)


# ---------------------------------------------------------------------------
# 13-16. Ordering and terminal behavior (representative proofs)
# ---------------------------------------------------------------------------


def test_no_upload_before_permit(monkeypatch):
    """The authorize-and-permit transaction precedes the upload: an
    approval failure at permit time means zero transport calls of any
    upload kind (authentication's read-only GET excepted)."""
    run_id, video_id, _manifest_id, asset, _ = _seed()
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    checkpoint = _authorizing_checkpoint(run_id)

    async def _revoke_mid_flight():
        await _append_decision_async(checkpoint, ApprovalAction.REVOKE)

    transport.on_get = _revoke_mid_flight
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
    finally:
        _cleanup(run_id, video_id, asset)


def test_duplicate_dispatch_after_success_is_safe(monkeypatch):
    video_bytes = b"i5-dup-video"
    run_id, video_id, manifest_id, asset, _ = _seed(video_bytes=video_bytes)
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    try:
        first = _run_agent(_ctx(run_id, video_id, asset))
        assert first.success
        second = _run_agent(_ctx(run_id, video_id, asset))
        assert second.success
        assert second.output.get("duplicate") is True
        assert transport.upload_calls == 1
        assert transport.posts_calls == 1
        rows = _attempts_for(video_id)
        assert len(rows) == 1
        assert rows[0].manifest_id == manifest_id
    finally:
        _cleanup(run_id, video_id, asset)


def test_snapshot_cleanup_on_failure_preserves_source(monkeypatch):
    """Failure paths clean up private snapshots and never delete the
    user-owned source artifacts."""
    run_id, video_id, _manifest_id, asset, _ = _seed(video_bytes=b"cleanup-case")
    transport = _ScriptedTransport(publish_behavior=("status", 503))
    _install_real_postiz(monkeypatch, transport)
    try:
        result = _run_agent(_ctx(run_id, video_id, asset))
        assert not result.success
        rows = _attempts_for(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        # Private snapshots cleaned; the source artifact survives.
        assert _snapshots_on_disk() == []
        assert Path(asset).exists()
    finally:
        _cleanup(run_id, video_id, asset)


# ---------------------------------------------------------------------------
# 17. THUMBNAIL-stage / TTL semantics intact (spot checks via gate)
# ---------------------------------------------------------------------------


def test_gate_semantics_unchanged_for_manifest_bound_approvals(monkeypatch):
    """The 53B gate still denies unknown videos, run mismatches, and
    missing checkpoints BEFORE any I5 logic (reason codes intact)."""
    from app.services.publish_gate import (
        PublishApprovalDenied,
        assert_publish_authorized,
    )

    class _ExecResult:
        def __init__(self, scalar):
            self._scalar = scalar

        def scalar_one_or_none(self):
            return self._scalar

    class _GateSession:
        def __init__(self, *results):
            self._queue = list(results)

        async def execute(self, *_a, **_k):
            return _ExecResult(self._queue.pop(0))

    video = SimpleNamespace(id=uuid.uuid4(), workflow_run_id=uuid.uuid4())
    with pytest.raises(PublishApprovalDenied) as ei:
        asyncio.run(
            assert_publish_authorized(
                _GateSession(None), video.workflow_run_id, video.id
            )
        )
    assert ei.value.reason_code == "unknown_video"
    with pytest.raises(PublishApprovalDenied) as ei:
        asyncio.run(
            assert_publish_authorized(_GateSession(video), uuid.uuid4(), video.id)
        )
    assert ei.value.reason_code == "video_not_in_workflow_run"
    with pytest.raises(PublishApprovalDenied) as ei:
        asyncio.run(
            assert_publish_authorized(
                _GateSession(video, None), video.workflow_run_id, video.id
            )
        )
    assert ei.value.reason_code == "no_thumbnail_checkpoint"


# ---------------------------------------------------------------------------
# 18. Dry-run remains fully inert
# ---------------------------------------------------------------------------


def test_dry_run_unchanged_and_inert(monkeypatch):
    transport = _ScriptedTransport()
    _install_real_postiz(monkeypatch, transport)
    asset = str(Path(tempfile.mkstemp(prefix="i5-dry-", suffix=".mp4")[1]))
    Path(asset).write_bytes(b"dry-run-video")
    try:
        ctx = _ctx(
            uuid.uuid4(), uuid.uuid4(), asset, dry_run=True, workflow_run_id=None
        )
        result = _run_agent(ctx)
        assert result.success, result.error
        assert transport.upload_calls == 0
        assert transport.posts_calls == 0
        assert _snapshots_on_disk() == []
    finally:
        Path(asset).unlink(missing_ok=True)
