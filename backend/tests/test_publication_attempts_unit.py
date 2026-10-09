"""Publication attempt core (operator-authorized slice).

Proves the durable, DB-idempotent attempt lifecycle around the REAL
operator publishing path (PublishingAgent) with a stubbed platform
adapter (the external dependency boundary — the only stub): attempt row
exists before external calls, SUCCEEDED/FAILED/UNKNOWN semantics,
duplicate-intent dedupe, DB-level concurrent admission arbitration,
external-ID persistence independent of the Video writeback, scheduled
execution-time attempts, and credential non-persistence. The Hermes
publishing capability remains dry-run and untouched (frozen boundary —
covered by the Hermes suites).

Phase 54B-I6: every real-dispatch test seeds a MANIFEST-BOUND approved
publish target (real artifact, real manifest through the I4 service,
bound + APPROVED THUMBNAIL checkpoint) and dispatches under the I5
contract — the 53B approval gate, dispatch-time manifest verification,
the permit transaction, and the verified-snapshot upload path are all
exercised for real. The original behavioral assertions (upload/publish
failure classification, anchor persistence, idempotency, ambiguous
outcomes, CAS transition discipline) are preserved; the failure-window
tests now reach their windows through the manifest-bound path (request
paths and unverified artifacts are inert/denied by design since I5).
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

import pytest

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt

# ---------------------------------------------------------------------------
# Stub adapter (the external dependency boundary)
# ---------------------------------------------------------------------------


class StubAdapter:
    def __init__(self, db, secrets=None):
        self.db = db
        self.calls = {"authenticate": 0, "upload_content": 0, "publish": 0}
        self.publish_behavior = "success"
        self.saw_statuses_at_authenticate = None
        self.saw_statuses_at_upload = None

    async def authenticate(self):
        from app.platforms.base import AuthResult

        self.calls["authenticate"] += 1
        # Prove the durable attempt exists (PENDING) BEFORE the first
        # external call of any kind.
        from sqlalchemy import select

        rows = (
            (
                await self.db.execute(
                    select(PublicationAttempt).where(
                        PublicationAttempt.video_id == self._video_uuid
                    )
                )
            )
            .scalars()
            .all()
        )
        self.saw_statuses_at_authenticate = [r.status for r in rows]
        return AuthResult(success=True, credentials={"api_key": "SECRET-DO-NOT-PERSIST"})

    async def upload_content(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls["upload_content"] += 1
        # Prove the PERMIT (PENDING -> IN_PROGRESS, I3/I5) was persisted
        # before the first irreversible external call.
        from sqlalchemy import select

        rows = (
            (
                await self.db.execute(
                    select(PublicationAttempt).where(
                        PublicationAttempt.video_id == self._video_uuid
                    )
                )
            )
            .scalars()
            .all()
        )
        self.saw_statuses_at_upload = [r.status for r in rows]
        return UploadResult(success=True, content_id="provider-content-1")

    async def upload_thumbnail(self, **kwargs):
        raise AssertionError("no thumbnail in these tests")

    async def publish(self, **kwargs):
        from app.platforms.base import PublishResult

        self.calls["publish"] += 1
        if self.publish_behavior == "reject":
            return PublishResult(success=False, error="provider rejected the post")
        if self.publish_behavior == "timeout-after-accept":
            # The provider accepted (remote side effect done), then the
            # connection died before confirmation reached us.
            self.calls["remote_accepted"] = True
            raise TimeoutError("connection dropped after submission")
        if self.publish_behavior == "raise":
            raise ConnectionError("network unreachable during submission")
        return PublishResult(
            success=True,
            published_content_id="provider-post-123",
            publish_status="published",
            url="https://social.example/watch/provider-post-123",
        )

    async def fetch_url(self, **kwargs):
        return kwargs.get("published_content_id")


def _install_adapter(monkeypatch, adapter):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: _ready(adapter, db),
    )


def _ready(adapter, db):
    adapter.db = db
    return adapter


# ---------------------------------------------------------------------------
# Phase 54B-I6: manifest-bound approved publish-target seeding
# ---------------------------------------------------------------------------

_SEED_STATE = {}


def _seed_target(**manifest_overrides):
    """Seed a MANIFEST-BOUND approved publish target (real artifact, real
    manifest through the I4 service, bound + approved THUMBNAIL
    checkpoint) matching the unit-suite dispatch context. Returns
    (run_id, video_id); the manifest's authoritative artifact path is
    remembered for _context()."""
    kwargs = dict(
        platform="postiz",
        social_platform="youtube",
        integration_id=None,
        privacy_status="public",
        publish_type="now",
    )
    kwargs.update(manifest_overrides)

    async def _inner():
        from tests._dispatch_manifest_fixtures import _seed_manifest_bound_target

        return await _seed_manifest_bound_target(**kwargs)

    run_id, video_id, _mid, vpath, thumb = asyncio.run(_inner())
    _SEED_STATE.clear()
    _SEED_STATE.update(run_id=run_id, video_id=video_id, asset=vpath, thumb=thumb)
    return run_id, video_id


def _cleanup_target():
    """Remove the seeded manifest-bound publish-target chain."""

    async def _inner():
        from tests._dispatch_manifest_fixtures import _cleanup_manifest_bound_target

        await _cleanup_manifest_bound_target(
            _SEED_STATE.get("run_id"), _SEED_STATE.get("video_id"),
            _SEED_STATE.get("asset"), _SEED_STATE.get("thumb"),
        )

    if _SEED_STATE.get("run_id") is not None:
        asyncio.run(_inner())
    _SEED_STATE.clear()


def _context(video_id, **overrides):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        # I6: the seeded manifest's authoritative artifact — dispatch
        # verifies against (and uploads) the manifest-bound snapshot,
        # not an arbitrary caller path.
        "video_storage_path": _SEED_STATE.get("asset") or _tmp_video(),
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": None,
        "workflow_run_id": (
            str(_SEED_STATE["run_id"]) if _SEED_STATE.get("run_id") else None
        ),
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
    path = Path(tempfile.mkstemp(prefix="pub-attempt-", suffix=".mp4")[1])
    path.write_bytes(b"fake-video")
    return str(path)


# ---------------------------------------------------------------------------
# Lifecycle semantics
# ---------------------------------------------------------------------------


def test_attempt_exists_before_external_call_and_succeeds(monkeypatch):
    """The durable attempt row exists (PENDING) BEFORE the first external
    call of any kind (observed from inside the stub's authenticate), the
    PERMIT (IN_PROGRESS) is persisted before the first irreversible
    external call (upload), and a confirmed publication lands SUCCEEDED
    with external ids persisted on the attempt — independent of any Video
    writeback."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        result = _run(_context(video_uuid))
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        attempt = rows[0]
        # Before the first external call the attempt already existed...
        assert adapter.saw_statuses_at_authenticate == [
            PublicationAttemptStatus.PENDING
        ]
        # ...and the permit (I3/I5) preceded the first upload.
        assert adapter.saw_statuses_at_upload == [
            PublicationAttemptStatus.IN_PROGRESS
        ]
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert attempt.external_content_id == "provider-content-1"
        assert attempt.external_post_id == "provider-post-123"
        assert attempt.attempt_number == 1
        assert result.output["attempt_status"] == "succeeded"
        assert result.output["attempt_id"] == str(attempt.id)
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_confirmed_provider_rejection_is_failed(monkeypatch):
    """Adapter-confirmed publish rejection -> FAILED with the error."""
    adapter = StubAdapter(None)
    adapter.publish_behavior = "reject"
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        result = _run(_context(video_uuid))
        assert not result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "rejected" in rows[0].error
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_failure_before_external_call_is_failed(monkeypatch):
    """Pre-dispatch artifact failure (the authoritative manifest artifact
    became unresolvable) -> FAILED; no external call was made. I6 mapping:
    the local-resolution window now lives inside dispatch-time snapshot
    verification, which precedes every external call."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        # The manifest's authoritative artifact disappears after seeding:
        # verification must fail closed BEFORE any external call.
        Path(_SEED_STATE["asset"]).unlink()
        result = _run(_context(video_uuid))
        assert not result.success
        assert "artifact_resolution_failed" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "artifact_resolution_failed" in rows[0].error
        assert adapter.calls["publish"] == 0
        assert adapter.calls["upload_content"] == 0
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_ambiguity_after_possible_acceptance_is_unknown_and_blocks_retry(monkeypatch):
    """A timeout AFTER the provider may have accepted -> durable UNKNOWN
    (never FAILED without evidence); a second submission of the same
    intent resolves to the UNKNOWN attempt and NEVER invokes the provider
    again automatically."""
    adapter = StubAdapter(None)
    adapter.publish_behavior = "timeout-after-accept"
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        ctx = _context(video_uuid)
        first = _run(ctx)
        assert not first.success and "UNKNOWN" in first.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        # The upload anchor was persisted before the ambiguous publish.
        assert rows[0].external_content_id == "provider-content-1"
        publish_calls_after_first = adapter.calls["publish"]

        second = _run(ctx)
        assert not second.success and "AMBIGUOUS" in second.error
        assert adapter.calls["publish"] == publish_calls_after_first  # no auto-retry
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1  # same attempt owns the intent
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_failed_attempt_can_be_retried_as_new_attempt_number(monkeypatch):
    """Only FAILED admits a new attempt (deterministic attempt_number+1)
    within the same intent; the retry then succeeds."""
    adapter = StubAdapter(None)
    adapter.publish_behavior = "reject"
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        ctx = _context(video_uuid)
        assert not _run(ctx).success
        adapter.publish_behavior = "success"
        result = _run(ctx)
        assert result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED, PublicationAttemptStatus.SUCCEEDED]
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_duplicate_succeeded_intent_never_publishes_twice(monkeypatch):
    """A second submission of an already-SUCCEEDED intent returns the
    existing outcome (idempotent duplicate success) with exactly ONE
    provider publish call."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        ctx = _context(video_uuid)
        first = _run(ctx)
        assert first.success
        second = _run(ctx)
        assert second.success
        assert second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "provider-post-123"
        assert adapter.calls["publish"] == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_concurrent_duplicate_admission_is_arbitrated_by_the_database():
    """Two concurrent admissions of the same intent: exactly one row is
    created (UNIQUE(intent_key, attempt_number) arbitrates); the loser
    resolves to the winner's attempt."""
    from app.services.publication_attempts import admit_attempt

    video_uuid = uuid.uuid4()

    async def _one():
        engine, session = await _session()
        try:
            return await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
        finally:
            await session.close()
            await engine.dispose()

    async def _race():
        return await asyncio.gather(_one(), _one())

    outcomes = asyncio.run(_race())
    try:
        created = [c for _, c in outcomes]
        assert created.count(True) == 1 and created.count(False) == 1
        assert outcomes[0][0].id == outcomes[1][0].id  # both resolve to the same attempt
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_scheduled_publication_attempts_at_execution_time(monkeypatch):
    """A scheduled publication records/starts its attempt when EXECUTION
    begins (the agent run), carrying the schedule reference — not as a
    pre-completed publication. Phase 54B-I6: the persisted schedule is
    the AUTHORITATIVE MANIFEST's canonical value."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target(scheduled_at="2026-10-01T12:00:00Z", publish_type="schedule")
    adapter._video_uuid = video_uuid
    try:
        ctx = _context(
            video_uuid,
            scheduled_at="2026-10-01T12:00:00Z",
        )
        result = _run(ctx)
        assert result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].scheduled_at == "2026-10-01T12:00:00Z"
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_credentials_never_persist(monkeypatch):
    """The adapter credential material never appears in ANY persisted
    attempt column."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        assert _run(_context(video_uuid)).success
        for attempt in asyncio.run(_attempts_for(video_uuid)):
            for column in (
                "platform", "social_platform", "integration_id", "intent_key",
                "scheduled_at", "external_content_id", "external_post_id",
                "public_url", "error",
            ):
                value = getattr(attempt, column)
                assert value is None or "SECRET-DO-NOT-PERSIST" not in str(value), column
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_dry_run_records_no_attempt(monkeypatch):
    """Dry-run validation performs no external publication and creates no
    attempt (nothing external can happen)."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    try:
        ctx = _context(video_uuid, video_storage_path=_tmp_video(), dry_run=True)
        ctx.pop("workflow_run_id")  # dry-run bypasses the gate by design
        result = _run(ctx)
        assert result.success
        assert asyncio.run(_attempts_for(video_uuid)) == []
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# H1: execution transitions are CAS — refused once the attempt moved
# ---------------------------------------------------------------------------


def _operator_move(attempt_id, status):
    """Simulate an operator resolution landing via a direct conditional
    update (the same mechanism the reconciliation service uses)."""

    async def _inner():
        from datetime import datetime, timezone

        from sqlalchemy import update

        engine, session = await _session()
        try:
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.id == attempt_id)
                .values(status=status, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(_inner())


def _late_transition(attempt_id, call):
    """The crashed execution's next bookkeeping transition, fired through
    the REAL helper against the CURRENT row."""

    async def _inner():
        from sqlalchemy import select

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
            return await call(session, obj)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def test_execution_transitions_apply_while_attempt_is_owned():
    """Normal flow: every transition helper returns True and lands while
    the attempt still holds its expected source status."""
    from app.services.publication_attempts import (
        admit_attempt,
        mark_external_content,
        mark_failed,
        mark_in_progress,
        mark_succeeded,
        mark_unknown,
    )

    video_uuid, video_uuid2, video_uuid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def _success_path():
        engine, session = await _session()
        try:
            attempt, _ = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
            assert await mark_external_content(session, attempt, "anchor-1") is True
            assert await mark_in_progress(session, attempt) is True
            assert await mark_succeeded(session, attempt, external_post_id="post-1") is True
        finally:
            await session.close()
            await engine.dispose()

    async def _failure_paths():
        engine, session = await _session()
        try:
            # Upload-exception shape: UNKNOWN straight from PENDING.
            a1, _ = await admit_attempt(
                session,
                video_id=video_uuid2,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
            assert await mark_unknown(session, a1, "upload exception: ReadTimeout") is True
            # Publish-rejection shape: FAILED from IN_PROGRESS.
            a2, _ = await admit_attempt(
                session,
                video_id=video_uuid3,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
            assert await mark_in_progress(session, a2) is True
            assert await mark_failed(session, a2, "publish rejected: scripted") is True
        finally:
            await session.close()
            await engine.dispose()

    try:
        asyncio.run(_success_path())
        rows = asyncio.run(_attempts_for(video_uuid))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].external_content_id == "anchor-1"
        assert rows[0].external_post_id == "post-1"
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))
    try:
        asyncio.run(_failure_paths())
    finally:
        asyncio.run(_cleanup_attempts(video_uuid2, video_uuid3))


def test_operator_resolution_rejects_every_late_execution_transition():
    """The H1 core: once the row leaves the execution-owned statuses
    (operator resolution), every transition helper refuses (returns
    False) and writes NOTHING — the resolution cannot be resurrected."""
    from app.services.publication_attempts import (
        admit_attempt,
        mark_external_content,
        mark_failed,
        mark_in_progress,
        mark_succeeded,
        mark_unknown,
    )

    made = []

    async def _admit(video_uuid, to_in_progress=False):
        engine, session = await _session()
        try:
            attempt, _ = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
            if to_in_progress:
                assert await mark_in_progress(session, attempt) is True
            return attempt.id
        finally:
            await session.close()
            await engine.dispose()

    try:
        # Operator force-failed a stalled PENDING attempt mid-execution.
        v1 = uuid.uuid4()
        made.append(v1)
        aid = asyncio.run(_admit(v1))
        _operator_move(aid, PublicationAttemptStatus.FAILED)
        assert _late_transition(aid, lambda s, o: mark_in_progress(s, o)) is False
        assert _late_transition(aid, lambda s, o: mark_external_content(s, o, "anchor-x")) is False
        assert _late_transition(aid, lambda s, o: mark_failed(s, o, "late failure")) is False
        assert _late_transition(aid, lambda s, o: mark_unknown(s, o, "late ambiguity")) is False
        rows = asyncio.run(_attempts_for(v1))
        assert rows[0].status == PublicationAttemptStatus.FAILED
        assert rows[0].external_content_id is None
        assert rows[0].error is None  # nothing the late execution wrote

        # Operator resolved a crashed IN_PROGRESS attempt to SUCCEEDED.
        v2 = uuid.uuid4()
        made.append(v2)
        aid2 = asyncio.run(_admit(v2, to_in_progress=True))
        _operator_move(aid2, PublicationAttemptStatus.SUCCEEDED)
        assert (
            _late_transition(aid2, lambda s, o: mark_succeeded(s, o, external_post_id="late-post"))
            is False
        )
        assert _late_transition(aid2, lambda s, o: mark_unknown(s, o, "late ambiguity")) is False
        rows2 = asyncio.run(_attempts_for(v2))
        assert rows2[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows2[0].external_post_id is None
        assert rows2[0].error is None
    finally:
        asyncio.run(_cleanup_attempts(*made))


# ---------------------------------------------------------------------------
# F-07: exception-window hardening — pre-permit local failures land FAILED
# (never a stranded PENDING row, never a provider publish); post-success
# bookkeeping failures never falsify an externally-successful publication.
# I6: the local-asset windows are exercised through the manifest-bound
# snapshot-verification path (the only asset resolution a real dispatch
# performs since I5).
# ---------------------------------------------------------------------------


def test_ssrf_rejected_asset_url_is_failed_not_pending(monkeypatch):
    """The identified window, under the I5 contract: a caller-supplied
    SSRF URL can never be resolved or fetched — it is denied as a path
    override against the authoritative manifest BEFORE any external call
    (the manifest's verified snapshot is the only upload source). The
    denial lands FAILED (not a stranded PENDING row) with zero provider
    calls, and the existing FAILED -> n+1 admission admits the retry."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        result = _run(
            _context(
                video_uuid,
                video_storage_path="http://169.254.169.254/latest/meta-data",
            )
        )
        assert not result.success
        assert "manifest_path_mismatch" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "manifest_path_mismatch" in rows[0].error  # classified, not stranded
        assert adapter.calls["publish"] == 0
        assert adapter.calls["upload_content"] == 0

        # The existing admission contract: FAILED admits attempt n+1.
        second = _run(_context(video_uuid))
        assert second.success, second.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        assert adapter.calls["publish"] == 1  # exactly the one legitimate retry
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_local_asset_oserror_is_failed_not_pending(monkeypatch):
    """Representative pre-dispatch local failure: OSError while resolving
    the AUTHORITATIVE artifact during snapshot verification -> FAILED, no
    provider publish call."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid

    async def _oserror(path, **kwargs):
        raise OSError("disk I/O error while resolving asset")

    monkeypatch.setattr(
        "app.services.publication_manifest_service.ensure_local_asset", _oserror
    )
    try:
        result = _run(_context(video_uuid))
        assert not result.success
        assert "artifact_resolution_failed" in result.error
        assert "OSError" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "artifact_resolution_failed" in rows[0].error
        assert adapter.calls["publish"] == 0
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_unexpected_asset_error_is_not_silently_classified_failed(monkeypatch):
    """Review-required: a genuine programming defect (KeyError) escaping
    artifact resolution must NOT be silently converted into the FAILED
    asset-resolution classification — it propagates for observability.
    No provider publish occurs; the attempt is left unclassified (the
    defect must be investigated, not papered over)."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid

    async def _defect(path, **kwargs):
        raise KeyError("programming defect in resolution path")

    monkeypatch.setattr(
        "app.services.publication_manifest_service.ensure_local_asset", _defect
    )
    try:
        with pytest.raises(KeyError):
            _run(_context(video_uuid))
        rows = asyncio.run(_attempts_for(video_uuid))
        # NOT classified as an asset-resolution FAILED: the defect stays loud.
        assert [r.status for r in rows] == [PublicationAttemptStatus.PENDING]
        assert rows[0].error is None
        assert adapter.calls["publish"] == 0
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_thumbnail_resolution_failure_is_failed_not_pending(monkeypatch):
    """Pre-dispatch local failure in the THUMBNAIL resolution window: no
    post can exist -> FAILED, no adapter.publish call. I6 mapping: since
    I5 both artifacts are snapshotted and verified BEFORE any external
    call (TOCTOU closure), so the failure now precedes the upload too —
    the fail-closed classification is unchanged."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    # Seed WITH a real thumbnail artifact (the default seed has none).
    thumb_file = Path(tempfile.mkstemp(prefix="pub-attempt-thumb-", suffix=".png")[1])
    thumb_file.write_bytes(b"thumb-bytes")
    _, video_uuid = _seed_target(thumbnail_path=str(thumb_file))
    adapter._video_uuid = video_uuid

    # The manifest's authoritative thumbnail artifact disappears after
    # seeding: thumbnail verification fails (after the video snapshot
    # succeeded — its private snapshot is cleaned up by the denial).
    Path(_SEED_STATE["thumb"]).unlink()
    try:
        result = _run(
            _context(video_uuid, thumbnail_storage_path=_SEED_STATE["thumb"])
        )
        assert not result.success
        assert "artifact_resolution_failed" in result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert adapter.calls["upload_content"] == 0  # verification precedes upload (I5)
        assert adapter.calls["publish"] == 0  # ...and no publish was dispatched
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_video_writeback_failure_never_falsifies_succeeded_publication(monkeypatch):
    """Provider publication succeeds, SUCCEEDED is durably committed, then
    the Video-row writeback fails: the result stays successful with the
    problem surfaced, the attempt stays SUCCEEDED, no second publish
    occurs, and the duplicate guard blocks any re-submission."""
    from sqlalchemy import Update

    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid

    def _run_with_failing_video_update(agent_context):
        async def _inner():
            engine, session = await _session()
            original_execute = session.execute

            async def _failing_execute(statement, *args, **kwargs):
                if isinstance(statement, Update) and statement.table.name == "videos":
                    raise RuntimeError("simulated writeback persistence failure")
                return await original_execute(statement, *args, **kwargs)

            session.execute = _failing_execute
            try:
                return await PublishingAgent(db=session).run(agent_context)
            finally:
                await session.close()
                await engine.dispose()

        return asyncio.run(_inner())

    try:
        result = _run_with_failing_video_update(_context(video_uuid))
        # The external publication is authoritative: never a false failure.
        assert result.success, result.error
        warnings = result.output.get("writeback_warnings")
        assert warnings and any("video writeback failed" in w for w in warnings)
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_post_id == "provider-post-123"
        assert adapter.calls["publish"] == 1

        # Duplicate guard: the re-submission resolves to the SUCCEEDED
        # attempt — no second provider publication.
        second = _run(_context(video_uuid))
        assert second.success and second.output.get("duplicate") is True
        assert adapter.calls["publish"] == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_public_url_fetch_failure_is_surfaced_not_fatal(monkeypatch):
    """A post-success public-URL fetch failure is surfaced as a recovery
    warning; the publication remains successful and SUCCEEDED."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid

    async def _fetch_url_raises(**kwargs):
        raise RuntimeError("url lookup unavailable")

    adapter.fetch_url = _fetch_url_raises
    try:
        result = _run(_context(video_uuid))
        assert result.success, result.error
        warnings = result.output.get("writeback_warnings")
        assert warnings and any("public url fetch failed" in w for w in warnings)
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert adapter.calls["publish"] == 1
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


def test_normal_success_output_unchanged_without_warnings(monkeypatch):
    """Normal successful publication: response shape unchanged — no
    writeback_warnings key, no error, existing output fields intact."""
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    _, video_uuid = _seed_target()
    adapter._video_uuid = video_uuid
    try:
        result = _run(_context(video_uuid))
        assert result.success
        assert "writeback_warnings" not in result.output
        assert result.error is None
        assert result.output["published_video_id"] == "provider-post-123"
        assert result.output["attempt_status"] == "succeeded"
        assert result.output["public_url"] == "provider-post-123"
    finally:
        _cleanup_target()
        asyncio.run(_cleanup_attempts(video_uuid))


# ---------------------------------------------------------------------------
# F-10a: duplicate-path Video writeback self-heal (ratified: idempotent,
# staleness-guarded, no-op for synthetic identities, never a provider call)
# ---------------------------------------------------------------------------


def _make_video_row(**manifest_overrides):
    """I6: seed the REAL manifest-bound approved chain (Project -> Run ->
    Video -> manifest -> bound approved THUMBNAIL checkpoint). Returns
    (run_id, video_id)."""
    return _seed_target(**manifest_overrides)


async def _read_video_row(video_uuid):
    from sqlalchemy import select

    from app.models.media import Video as VideoRow

    engine, session = await _session()
    try:
        v = (
            (await session.execute(select(VideoRow).where(VideoRow.id == video_uuid)))
            .scalars()
            .one()
        )
        return v.youtube_video_id, v.publish_status
    finally:
        await session.close()
        await engine.dispose()


def _run_with_video_update_failure(agent_context):
    """Run the agent with ONLY the videos-table UPDATE failing (the F-10
    loss scenario: publication SUCCEEDED, writeback lost)."""

    async def _inner():
        from sqlalchemy import Update

        engine, session = await _session()
        original_execute = session.execute

        async def _failing_execute(statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "videos":
                raise RuntimeError("simulated writeback persistence failure")
            return await original_execute(statement, *args, **kwargs)

        session.execute = _failing_execute
        try:
            return await PublishingAgent(db=session).run(agent_context)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def test_f10a_duplicate_path_heals_stale_video_row(monkeypatch):
    """The F-10 scenario end-to-end: publication SUCCEEDED, Video
    writeback lost (F-07 surfaces it), and the idempotent-duplicate
    retry now HEALS the stale row from the attempt's authoritative
    external ids — with zero provider re-publication."""
    from app.models.enums import PublishStatus

    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    made = None
    try:
        made = _make_video_row()
        _, real_video_id = made

        # Attempt 1: SUCCEEDED, writeback lost.
        first = _run_with_video_update_failure(_context(real_video_id))
        assert first.success
        assert first.output.get("writeback_warnings")
        assert asyncio.run(_read_video_row(real_video_id)) == (None, PublishStatus.DRAFT)

        # Attempt 2 (identical intent, real Video id): duplicate + HEAL.
        second = _run(_context(real_video_id))
        assert second.success and second.output.get("duplicate") is True
        assert asyncio.run(_read_video_row(real_video_id)) == (
            "provider-post-123",
            PublishStatus.PUBLISHED,
        )
        assert adapter.calls["publish"] == 1  # no second provider publication
    finally:
        if made:
            _cleanup_target()
            asyncio.run(_cleanup_attempts(video_uuid))
            asyncio.run(_cleanup_attempts(real_video_id))


def test_f10a_heal_uses_scheduled_status_for_scheduled_attempts(monkeypatch):
    """A SUCCEEDED scheduled-dispatch attempt heals the Video row to
    SCHEDULED (the attempt's persisted scheduled_at — the manifest's
    authoritative schedule since I6 — is the signal)."""
    from app.models.enums import PublishStatus

    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    made = None
    try:
        made = _make_video_row(scheduled_at="2030-01-01T00:00:00Z", publish_type="schedule")
        _, real_video_id = made

        first = _run_with_video_update_failure(
            _context(real_video_id, scheduled_at="2030-01-01T00:00:00Z")
        )
        assert first.success
        assert asyncio.run(_read_video_row(real_video_id)) == (None, PublishStatus.DRAFT)

        second = _run(
            _context(real_video_id, scheduled_at="2030-01-01T00:00:00Z")
        )
        assert second.success and second.output.get("duplicate") is True
        assert asyncio.run(_read_video_row(real_video_id)) == (
            "provider-post-123",
            PublishStatus.SCHEDULED,
        )
    finally:
        if made:
            _cleanup_target()
            asyncio.run(_cleanup_attempts(real_video_id))
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f10a_heal_is_noop_when_row_already_current(monkeypatch):
    """When the original writeback landed, the duplicate path leaves the
    row untouched (staleness guard: no regression of a current value)."""
    from app.models.enums import PublishStatus

    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    made = None
    try:
        made = _make_video_row()
        _, real_video_id = made

        first = _run(_context(real_video_id))
        assert first.success
        assert asyncio.run(_read_video_row(real_video_id)) == (
            "provider-post-123",
            PublishStatus.PUBLISHED,
        )

        second = _run(_context(real_video_id))
        assert second.success and second.output.get("duplicate") is True
        assert asyncio.run(_read_video_row(real_video_id)) == (
            "provider-post-123",
            PublishStatus.PUBLISHED,
        )
        assert adapter.calls["publish"] == 1
    finally:
        if made:
            _cleanup_target()
            asyncio.run(_cleanup_attempts(real_video_id))
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f10a_synthetic_identity_is_refused_pre_admission(monkeypatch):
    """I6 conversion of the synthetic-identity no-op scenario: under the
    I5 contract a synthetic identity (a UUID with NO Video row) can no
    longer be published or duplicated at all — the 53B gate refuses
    unknown_video BEFORE any attempt is admitted, so no external call
    and no heal surface exist. (The manifest FK pins every published
    Video row, making the post-success row-absent heal race structurally
    unreachable; the heal's staleness guard remains covered above.)"""
    video_uuid = uuid.uuid4()  # a UUID with NO Video row (synthetic shape)
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(
            # A syntactically valid run id so the gate reaches the video
            # lookup (which is what must refuse the synthetic identity).
            _context(video_uuid, workflow_run_id=str(uuid.uuid4()))
        )
        assert not result.success
        assert "publish_approval_denied: unknown_video" in result.error
        assert adapter.calls["publish"] == 0
        assert adapter.calls["upload_content"] == 0
        assert asyncio.run(_attempts_for(video_uuid)) == []
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f10a_heal_failure_is_nonfatal_on_duplicate(monkeypatch):
    """If the heal UPDATE itself fails on the duplicate path, the
    response stays truthful (duplicate success) and the failure is
    surfaced as a warning — never a false publication failure."""
    from app.models.enums import PublishStatus

    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    made = None
    try:
        made = _make_video_row()
        _, real_video_id = made

        first = _run_with_video_update_failure(_context(real_video_id))
        assert first.success

        second = _run_with_video_update_failure(_context(real_video_id))
        assert second.success and second.output.get("duplicate") is True
        # Row remains stale; the heal failure did not falsify anything.
        assert asyncio.run(_read_video_row(real_video_id)) == (None, PublishStatus.DRAFT)
        assert adapter.calls["publish"] == 1
    finally:
        if made:
            _cleanup_target()
            asyncio.run(_cleanup_attempts(real_video_id))
        asyncio.run(_cleanup_attempts(video_uuid))


def test_f12a_admission_stamp_comes_from_the_application_clock():
    """F-12a: the admission row's updated_at is stamped EXPLICITLY with
    the APPLICATION clock — the same authority the active-execution
    floor compares against — instead of the database server_default.
    Discriminator: the in-memory instance carries the stamp immediately
    after commit (a server_default would leave it None until a refresh),
    and the stamp lies strictly between app-clock samples taken around
    the admission."""
    from datetime import datetime, timedelta, timezone

    from app.services.publication_attempts import admit_attempt

    video_uuid = uuid.uuid4()

    async def _inner():
        engine, session = await _session()
        try:
            t0 = datetime.now(timezone.utc)
            attempt, created = await admit_attempt(
                session,
                video_id=video_uuid,
                platform="postiz",
                social_platform="youtube",
                integration_id=None,
            )
            t1 = datetime.now(timezone.utc)
            return attempt, created, t0, t1
        finally:
            await session.close()
            await engine.dispose()

    attempt, created, t0, t1 = asyncio.run(_inner())
    try:
        assert created is True
        # App-clock provenance: populated immediately on the instance
        # (server_default would leave this None until a refresh).
        assert attempt.updated_at is not None
        assert attempt.updated_at.tzinfo is not None
        # The stamp was taken between the two app-clock samples.
        assert t0 - timedelta(seconds=1) <= attempt.updated_at <= t1 + timedelta(seconds=1)
        # And it is what was PERSISTED (fresh read-back).
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].updated_at is not None
        assert abs((rows[0].updated_at - attempt.updated_at).total_seconds()) < 1
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))
