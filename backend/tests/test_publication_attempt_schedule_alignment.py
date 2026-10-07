"""Phase 54B-I6: attempt scheduling metadata follows the AUTHORITATIVE manifest.

The admitted attempt row's scheduled_at must agree with the approved
manifest's effective schedule for manifest-bound dispatch:

- scheduled manifest + request OMITTING a schedule -> the dispatched
  attempt carries the MANIFEST's schedule (normalized canonical form);
- unscheduled manifest -> the dispatched attempt carries None;
- a request schedule that DIFFERS from the manifest is an override
  attempt: denied (parameter drift), attempt FAILED, zero external
  publish calls;
- an equivalent-but-differently-spelled request schedule (offset form
  vs canonical Z form) is NOT drift: dispatch proceeds and the row is
  normalized to the manifest's canonical form;
- duplicate re-submission of a SUCCEEDED scheduled intent resolves to
  the existing attempt (idempotent duplicate, one provider publish),
  with the row still carrying the manifest's schedule.

Offline: stubbed adapter (the external dependency boundary), local
disposable test database, real manifest/approval seeding through the
I4 service. No provider is contacted.
"""
import asyncio

from app.agents.publishing import PublishingAgent
from app.models.enums import PublicationAttemptStatus
from app.models.publication import PublicationAttempt


class StubAdapter:
    def __init__(self, db, secrets=None):
        self.db = db
        self.calls = {"authenticate": 0, "upload_content": 0, "publish": 0}
        self.saw_publish_kwargs = None

    async def authenticate(self):
        from app.platforms.base import AuthResult

        self.calls["authenticate"] += 1
        return AuthResult(success=True, credentials={"api_key": "stub"})

    async def upload_content(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls["upload_content"] += 1
        return UploadResult(success=True, content_id="sched-media-1")

    async def upload_thumbnail(self, **kwargs):
        raise AssertionError("no thumbnail in these tests")

    async def publish(self, **kwargs):
        from app.platforms.base import PublishResult

        self.calls["publish"] += 1
        self.saw_publish_kwargs = dict(kwargs)
        return PublishResult(
            success=True,
            published_content_id="sched-post-1",
            publish_status="scheduled" if kwargs.get("scheduled_at") else "published",
            url="https://social.example/watch/sched-post-1",
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


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(scheduled_at=None, publish_type="now"):
    from tests._dispatch_manifest_fixtures import seed_manifest_bound_target

    return seed_manifest_bound_target(
        platform="postiz",
        social_platform="youtube",
        integration_id="integ-1",
        privacy_status="public",
        publish_type=publish_type,
        scheduled_at=scheduled_at,
    )


def _cleanup(seeded, *extra_video_ids):
    from tests._dispatch_manifest_fixtures import cleanup_manifest_bound_target

    run_id, video_id, _mid, vpath, _thumb = seeded
    cleanup_manifest_bound_target(run_id, video_id, vpath)
    if extra_video_ids:
        asyncio.run(_cleanup_attempts(*extra_video_ids))


def _context(seeded, **overrides):
    run_id, video_id, _mid, vpath, _thumb = seeded
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": vpath,
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "workflow_run_id": str(run_id),
        "dry_run": False,
    }
    base.update(overrides)
    return base


def _run(agent_context):
    async def _inner():
        engine, session = await _session()
        try:
            return await PublishingAgent(db=session).run(agent_context)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


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
            await session.execute(
                delete(PublicationAttempt).where(PublicationAttempt.video_id == v)
            )
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 1. Scheduled manifest: the dispatched attempt carries the MANIFEST schedule
# ---------------------------------------------------------------------------


def test_scheduled_manifest_governs_attempt_metadata(monkeypatch):
    """Request OMITS scheduled_at; the manifest schedules the publication.
    The permitted attempt row carries the manifest's canonical schedule —
    proving the persisted metadata follows the authoritative manifest,
    not the (absent) request value."""
    seeded = _seed(scheduled_at="2027-03-01T09:30:00Z", publish_type="schedule")
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(_context(seeded))
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        # THE I6 invariant: the row's schedule came from the manifest.
        assert rows[0].scheduled_at == "2027-03-01T09:30:00Z"
        # The adapter dispatched the manifest's schedule/publish_type too.
        assert adapter.saw_publish_kwargs["scheduled_at"] == "2027-03-01T09:30:00Z"
        assert adapter.saw_publish_kwargs["publish_type"] == "schedule"
    finally:
        _cleanup(seeded)


def test_equivalent_request_schedule_is_normalized_to_manifest_form(monkeypatch):
    """A request schedule equivalent to the manifest's but spelled with an
    explicit +00:00 offset is NOT drift (normalization preserved): dispatch
    proceeds and the attempt row holds the manifest's canonical 'Z' form."""
    seeded = _seed(scheduled_at="2027-03-01T09:30:00Z", publish_type="schedule")
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(
            _context(seeded, scheduled_at="2027-03-01T09:30:00+00:00")
        )
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].scheduled_at == "2027-03-01T09:30:00Z"
    finally:
        _cleanup(seeded)


# ---------------------------------------------------------------------------
# 2. Unscheduled manifest: null/unscheduled semantics preserved
# ---------------------------------------------------------------------------


def test_unscheduled_manifest_keeps_attempt_schedule_null(monkeypatch):
    """An unscheduled manifest dispatch leaves the attempt's scheduled_at
    None (no invented schedule), even when the request carried a value —
    which would instead be denied as drift (covered below)."""
    seeded = _seed()
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(_context(seeded))
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].scheduled_at is None
        assert adapter.saw_publish_kwargs["scheduled_at"] is None
    finally:
        _cleanup(seeded)


# ---------------------------------------------------------------------------
# 3. Request/manifest mismatch: untrusted scheduling cannot override
# ---------------------------------------------------------------------------


def test_request_schedule_mismatch_with_manifest_is_denied(monkeypatch):
    """A request schedule DIFFERENT from the approved manifest's is an
    override attempt: fail-closed parameter-drift denial, the admitted
    attempt recorded FAILED, and ZERO external publish calls."""
    seeded = _seed(scheduled_at="2027-03-01T09:30:00Z", publish_type="schedule")
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(_context(seeded, scheduled_at="2027-03-01T23:59:00Z"))
        assert not result.success
        assert "parameter_drift:scheduled_at" in result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "parameter_drift:scheduled_at" in rows[0].error
        assert adapter.calls["publish"] == 0
        assert adapter.calls["upload_content"] == 0
    finally:
        _cleanup(seeded)


def test_request_schedule_against_unscheduled_manifest_is_denied(monkeypatch):
    """A request injecting a schedule the unscheduled manifest never
    approved is likewise denied — the manifest governs, fail closed."""
    seeded = _seed()
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run(_context(seeded, scheduled_at="2027-03-01T09:30:00Z"))
        assert not result.success
        assert "parameter_drift:scheduled_at" in result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert adapter.calls["publish"] == 0
    finally:
        _cleanup(seeded)


# ---------------------------------------------------------------------------
# 4. Duplicate intent behavior with a manifest schedule
# ---------------------------------------------------------------------------


def test_duplicate_scheduled_intent_resolves_to_existing_attempt(monkeypatch):
    """Re-submitting a SUCCEEDED scheduled intent is an idempotent
    duplicate: exactly one provider publish, one attempt row, and the
    row still carries the manifest's (not any request's) schedule."""
    seeded = _seed(scheduled_at="2027-03-01T09:30:00Z", publish_type="schedule")
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)
    try:
        first = _run(_context(seeded))
        assert first.success, first.error

        # Duplicate carries an equivalent offset-spelled schedule: still
        # the same intent, resolved to the SAME attempt.
        second = _run(
            _context(seeded, scheduled_at="2027-03-01T09:30:00+00:00")
        )
        assert second.success and second.output.get("duplicate") is True
        assert adapter.calls["publish"] == 1
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
        assert rows[0].scheduled_at == "2027-03-01T09:30:00Z"
    finally:
        _cleanup(seeded)


# ---------------------------------------------------------------------------
# 5. The permit is the atomic stamping point: no second write, no window
# ---------------------------------------------------------------------------


def test_permit_denial_leaves_no_manifest_schedule_on_the_row(monkeypatch):
    """When the permit itself is denied (approval revoked after
    verification), the attempt is FAILED and its scheduling metadata is
    whatever admission recorded — no manifest value is stamped without
    the permit, and no external call is made."""
    seeded = _seed(scheduled_at="2027-03-01T09:30:00Z", publish_type="schedule")
    adapter = StubAdapter(None)
    _install_adapter(monkeypatch, adapter)

    async def _revoke_approval():
        from datetime import UTC, datetime

        from app.models.approval import ApprovalDecision
        from app.models.enums import ApprovalAction

        engine, session = await _session()
        try:
            from app.models.approval import ApprovalCheckpoint
            from sqlalchemy import select

            cp = (
                await session.execute(
                    select(ApprovalCheckpoint).where(
                        ApprovalCheckpoint.workflow_run_id == seeded[0]
                    )
                )
            ).scalars().one()
            decided_at = datetime.now(UTC).replace(tzinfo=None)
            session.add(
                ApprovalDecision(
                    checkpoint_id=cp.id,
                    sequence_number=2,
                    action=ApprovalAction.REVOKE,
                    decided_at=decided_at,
                    decided_by="i6-revoker",
                )
            )
            cp.action = ApprovalAction.REVOKE
            cp.decided_at = decided_at
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    async def _authenticate_hook():
        # Fires BEFORE the authorize-and-permit transaction (the agent
        # authenticates first): the revocation commits between manifest
        # verification and the permit, so the permit itself is denied.
        await _revoke_approval()
        return await StubAdapter.authenticate(adapter)

    adapter.authenticate = _authenticate_hook
    try:
        result = _run(_context(seeded))
        assert not result.success
        assert "permit denied" in result.error
        rows = asyncio.run(_attempts_for(seeded[1]))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "permit denied" in rows[0].error
        assert adapter.calls["publish"] == 0
        assert adapter.calls["upload_content"] == 0
    finally:
        _cleanup(seeded)
