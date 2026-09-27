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
"""
import asyncio
import tempfile
import uuid
from pathlib import Path

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
        self.saw_pending_attempt_at_upload = None

    async def authenticate(self):
        from app.platforms.base import AuthResult

        self.calls["authenticate"] += 1
        return AuthResult(success=True, credentials={"api_key": "SECRET-DO-NOT-PERSIST"})

    async def upload_content(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls["upload_content"] += 1
        # Prove the durable attempt exists BEFORE this external call.
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
        self.saw_pending_attempt_at_upload = [r.status for r in rows]
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


def _context(video_id, **overrides):
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": None,  # filled per-test
        "title": "t",
        "description": "d",
        "social_platform": "youtube",
        "integration_id": None,
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
    call (observed from inside the stub's upload), IN_PROGRESS is
    persisted before publish, and a confirmed publication lands SUCCEEDED
    with external ids persisted on the attempt — independent of any Video
    writeback (no Video row exists here at all)."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        result = _run(ctx)
        assert result.success, result.error
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        attempt = rows[0]
        # Before the first external call the attempt already existed.
        assert PublicationAttemptStatus.PENDING in adapter.saw_pending_attempt_at_upload
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert attempt.external_content_id == "provider-content-1"
        assert attempt.external_post_id == "provider-post-123"
        assert attempt.attempt_number == 1
        assert result.output["attempt_status"] == "succeeded"
        assert result.output["attempt_id"] == str(attempt.id)
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_confirmed_provider_rejection_is_failed(monkeypatch):
    """Adapter-confirmed publish rejection -> FAILED with the error."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    adapter.publish_behavior = "reject"
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        result = _run(ctx)
        assert not result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "rejected" in rows[0].error
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_failure_before_external_call_is_failed(monkeypatch):
    """Local validation failure (unresolvable asset) -> FAILED; no
    external publish call was made."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path="/nonexistent/no-such-file.mp4")
    try:
        result = _run(ctx)
        assert not result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert adapter.calls["publish"] == 0
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_ambiguity_after_possible_acceptance_is_unknown_and_blocks_retry(monkeypatch):
    """A timeout AFTER the provider may have accepted -> durable UNKNOWN
    (never FAILED without evidence); a second submission of the same
    intent resolves to the UNKNOWN attempt and NEVER invokes the provider
    again automatically."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    adapter.publish_behavior = "timeout-after-accept"
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
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
        asyncio.run(_cleanup_attempts(video_uuid))


def test_failed_attempt_can_be_retried_as_new_attempt_number(monkeypatch):
    """Only FAILED admits a new attempt (deterministic attempt_number+1)
    within the same intent; the retry then succeeds."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    adapter.publish_behavior = "reject"
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        assert not _run(ctx).success
        adapter.publish_behavior = "success"
        result = _run(ctx)
        assert result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED, PublicationAttemptStatus.SUCCEEDED]
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_duplicate_succeeded_intent_never_publishes_twice(monkeypatch):
    """A second submission of an already-SUCCEEDED intent returns the
    existing outcome (idempotent duplicate success) with exactly ONE
    provider publish call."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        first = _run(ctx)
        assert first.success
        second = _run(ctx)
        assert second.success
        assert second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "provider-post-123"
        assert adapter.calls["publish"] == 1
        assert len(asyncio.run(_attempts_for(video_uuid))) == 1
    finally:
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
    pre-completed publication."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(
        video_uuid,
        video_storage_path=_tmp_video(),
        scheduled_at="2026-10-01T12:00:00Z",
    )
    try:
        result = _run(ctx)
        assert result.success
        rows = asyncio.run(_attempts_for(video_uuid))
        assert len(rows) == 1
        assert rows[0].scheduled_at == "2026-10-01T12:00:00Z"
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_credentials_never_persist(monkeypatch):
    """The adapter credential material never appears in ANY persisted
    attempt column."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video())
    try:
        assert _run(ctx).success
        for attempt in asyncio.run(_attempts_for(video_uuid)):
            for column in (
                "platform", "social_platform", "integration_id", "intent_key",
                "scheduled_at", "external_content_id", "external_post_id",
                "public_url", "error",
            ):
                value = getattr(attempt, column)
                assert value is None or "SECRET-DO-NOT-PERSIST" not in str(value), column
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))


def test_dry_run_records_no_attempt(monkeypatch):
    """Dry-run validation performs no external publication and creates no
    attempt (nothing external can happen)."""
    video_uuid = uuid.uuid4()
    adapter = StubAdapter(None)
    adapter._video_uuid = video_uuid
    _install_adapter(monkeypatch, adapter)
    ctx = _context(video_uuid, video_storage_path=_tmp_video(), dry_run=True)
    try:
        result = _run(ctx)
        assert result.success
        assert asyncio.run(_attempts_for(video_uuid)) == []
    finally:
        asyncio.run(_cleanup_attempts(video_uuid))
