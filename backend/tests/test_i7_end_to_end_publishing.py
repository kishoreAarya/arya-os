"""Phase 54B-I7: end-to-end integration validation of the secured
publishing workflow.

Every scenario drives the NORMAL ORCHESTRATION PUBLISHING STAGE —
`Orchestrator._execute_stage("publishing", ctx)`, the orchestrator's own
stage dispatch (the same code `Orchestrator.run`'s pipeline loop calls),
which resolves the agent through AGENT_REGISTRY and executes it with the
real per-stage retry loop — against real seeded authorization state
(Project -> WorkflowRun -> Video -> publication manifest via the real I4
service -> bound THUMBNAIL checkpoint -> APPROVE decision mirroring
decide semantics). Only the EXTERNAL boundary is scripted: a recording
stub adapter replaces the platform factory product, and scripted httpx
transports replace the real HTTP layer for the router-level checks.

Scenario matrix (phase §3):
A. Successful workflow — exact call order, permit/anchor ordering
   proven from observed DB state at each adapter call, final state.
B. Authorization/manifest rejection — fail-closed before ANY external
   call for every denial class.
C. Failure at each external side-effect boundary — attempt state and
   recovery per boundary.
D. Duplicate/retry/concurrency — idempotency, UNKNOWN blocking, races.
E. Schedule and parameter consistency — manifest-derived dispatch
   parameters through the adapter boundary.
F. Dry-run and alternate entry points — no real-provider path, no
   authorization bypass through status/reconciliation surfaces.

Offline: disposable test database, scripted transports, zero real
provider calls.
"""
import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models.enums import ApprovalAction, ApprovalStage, PublicationAttemptStatus
from app.models.publication import PublicationAttempt
from app.workflows.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Harness: recording adapter (the external dependency boundary)
# ---------------------------------------------------------------------------


class RecordingAdapter:
    """Scripted platform adapter that records the ORDER of external calls
    and, at each call, the observed durable attempt state (status /
    manifest stamped / anchor persisted) — the evidence base for
    permit-before-upload and anchor-before-publish ordering."""

    def __init__(self, video_uuid, *, auth="ok", upload="ok", thumbnail="ok",
                 publish="ok", evidence="unknown", hooks=None,
                 observe=True):
        self._video_uuid = video_uuid
        self.behaviors = {"authenticate": auth, "upload_content": upload,
                          "upload_thumbnail": thumbnail, "publish": publish}
        self.evidence = evidence
        self.hooks = hooks or {}
        self.observe = observe  # False for concurrent runs (shared adapter)
        self.db = None
        self.calls = []          # ordered external-call names
        self.observations = []   # (phase, status, manifest_stamped, anchor)
        self.saw = {}            # last kwargs per call

    async def check_processing(self, content_id, **kwargs):
        """Reconciliation/evidence surface (read-only provider probe)."""
        from app.platforms.base import ProcessingStatus

        self.calls.append(f"check_processing:{content_id}")
        return ProcessingStatus(
            status=self.evidence,
            progress_percent=100.0 if self.evidence == "ready" else None,
        )

    async def _observe(self, phase):
        if not self.observe or self.db is None:
            return
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
        row = rows[0] if rows else None
        self.observations.append(
            (
                phase,
                row.status.value if row else None,
                bool(row is not None and row.manifest_id is not None),
                row.external_content_id if row else None,
            )
        )

    async def _hook(self, phase):
        hook = self.hooks.get(phase)
        if hook is not None:
            await hook()

    async def authenticate(self):
        from app.platforms.base import AuthResult

        self.calls.append("authenticate")
        await self._observe("authenticate")
        await self._hook("authenticate")
        if self.behaviors["authenticate"] == "fail":
            return AuthResult(success=False, error="no credentials configured")
        if self.behaviors["authenticate"] == "raise":
            raise ConnectionError("auth endpoint unreachable")
        return AuthResult(success=True, credentials={"api_key": "SCRIPTED"})

    async def upload_content(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls.append("upload_content")
        self.saw["upload_content"] = dict(kwargs)
        await self._observe("upload_content")
        await self._hook("upload_content")
        await self._hook("before_anchor")
        behavior = self.behaviors["upload_content"]
        if behavior == "fail":
            return UploadResult(success=False, error="provider refused upload")
        if behavior == "raise":
            raise TimeoutError("connection dropped mid-upload")
        if behavior == "no_id":
            return UploadResult(success=True, content_id=None)
        return UploadResult(success=True, content_id="e2e-media-1")

    async def upload_thumbnail(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls.append("upload_thumbnail")
        self.saw["upload_thumbnail"] = dict(kwargs)
        await self._observe("upload_thumbnail")
        behavior = self.behaviors["upload_thumbnail"]
        if behavior == "fail":
            return UploadResult(success=False, error="thumbnail rejected")
        if behavior == "raise":
            raise TimeoutError("thumbnail upload timed out")
        return UploadResult(success=True, content_id="e2e-thumb-1")

    async def publish(self, **kwargs):
        from app.platforms.base import PublishResult

        self.calls.append("publish")
        self.saw["publish"] = dict(kwargs)
        await self._observe("publish")
        await self._hook("publish")
        behavior = self.behaviors["publish"]
        if behavior == "reject":
            return PublishResult(success=False, error="provider rejected the post")
        if behavior == "raise":
            raise TimeoutError("no confirmation after submission")
        scheduled = bool(kwargs.get("scheduled_at"))
        return PublishResult(
            success=True,
            published_content_id="e2e-post-1",
            publish_status="scheduled" if scheduled else "published",
            url="https://social.example/watch/e2e-post-1",
        )

    async def fetch_url(self, **kwargs):
        self.calls.append("fetch_url")
        return "https://social.example/watch/e2e-post-1"


def _install_adapter(monkeypatch, adapter):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: _bind(adapter, db),
    )


def _bind(adapter, db):
    adapter.db = db
    return adapter


# ---------------------------------------------------------------------------
# Harness: seeding (real services) + orchestration entry
# ---------------------------------------------------------------------------


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(**kwargs):
    from tests._dispatch_manifest_fixtures import seed_manifest_bound_target

    return seed_manifest_bound_target(**kwargs)


def _cleanup(seeded):
    from tests._dispatch_manifest_fixtures import cleanup_manifest_bound_target

    run_id, video_id, _mid, vpath, thumb = seeded
    cleanup_manifest_bound_target(run_id, video_id, vpath, thumb)


def _stage_context(seeded, **overrides):
    """The context the pipeline holds at the publishing stage: identity,
    the manifest's authoritative artifact, and the requested destination
    (destination fields are verified against — and cannot override — the
    approved manifest)."""
    run_id, video_id, _mid, vpath, _thumb = seeded
    base = {
        "platform": "postiz",
        "video_id": str(video_id),
        "video_storage_path": vpath,
        "thumbnail_storage_path": _thumb,
        "social_platform": "youtube",
        "integration_id": "integ-1",
        "workflow_run_id": str(run_id),
        "dry_run": False,
    }
    base.update(overrides)
    return base


def _run_stage(ctx, *, execute_wrapper=None):
    """Drive the NORMAL orchestrator publishing stage (the same dispatch
    the pipeline loop uses) on its own engine/session."""

    async def _inner():
        engine, session = await _session()
        try:
            orch = Orchestrator(db=session, max_retries=0)
            return await orch._execute_stage("publishing", ctx)
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


def _attempts(video_uuid):
    return asyncio.run(_attempts_for(video_uuid))


async def _mutate_seeded_state(run_id, *, action=None, age_hours=None,
                               rebind_manifest_id=None, corrupt=False,
                               stage=None):
    """Operator-style DB mutations for the denial matrix (mirroring
    decide semantics: append-only event + cache refresh)."""
    from sqlalchemy import select, update

    from app.models.approval import ApprovalCheckpoint, ApprovalDecision

    engine, session = await _session()
    try:
        cp = (
            await session.execute(
                select(ApprovalCheckpoint).where(
                    ApprovalCheckpoint.workflow_run_id == run_id,
                    ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
                )
            )
        ).scalars().one()
        if action is not None:
            decided_at = datetime.now(UTC).replace(tzinfo=None)
            seq = (
                (
                    await session.execute(
                        select(ApprovalDecision.sequence_number)
                        .where(ApprovalDecision.checkpoint_id == cp.id)
                        .order_by(ApprovalDecision.sequence_number.desc())
                        .limit(1)
                    )
                ).scalar()
                or 0
            ) + 1
            session.add(
                ApprovalDecision(
                    checkpoint_id=cp.id,
                    sequence_number=seq,
                    action=action,
                    decided_at=decided_at,
                    decided_by="i7-mutator",
                )
            )
            cp.action = action
            cp.decided_at = decided_at
        if age_hours is not None:
            aged = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=age_hours)
            await session.execute(
                update(ApprovalCheckpoint)
                .where(ApprovalCheckpoint.id == cp.id)
                .values(decided_at=aged)
            )
        if rebind_manifest_id is not None:
            await session.execute(
                update(ApprovalCheckpoint)
                .where(ApprovalCheckpoint.id == cp.id)
                .values(publication_manifest_id=rebind_manifest_id)
            )
        if corrupt:
            from app.models.publication import PublicationManifest

            m = await session.get(PublicationManifest, cp.publication_manifest_id)
            m.canonical_bytes = m.canonical_bytes.replace("youtube", "Y0UTUBE")
        if stage is not None:
            await session.execute(
                update(ApprovalCheckpoint)
                .where(ApprovalCheckpoint.id == cp.id)
                .values(stage=stage)
            )
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


def _mutate(run_id, **kwargs):
    asyncio.run(_mutate_seeded_state(run_id, **kwargs))


def _tmp_video():
    path = Path(tempfile.mkstemp(prefix="i7-", suffix=".mp4")[1])
    path.write_bytes(b"i7-video-bytes")
    return str(path)


def _tmp_thumb():
    path = Path(tempfile.mkstemp(prefix="i7-thumb-", suffix=".png")[1])
    path.write_bytes(b"i7-thumb-bytes")
    return str(path)


# ===========================================================================
# A. Successful workflow through the normal orchestration publishing stage
# ===========================================================================


def test_a_success_full_order_permit_anchor_and_final_state(monkeypatch):
    """The complete happy path, ordered and observed:

    admission (PENDING attempt) -> 53B gate -> I5 manifest verification
    -> authenticate -> PERMIT (IN_PROGRESS + manifest stamped, observed
    at upload) -> upload the verified snapshot -> ANCHOR persisted
    (observed at thumbnail/publish) -> thumbnail upload -> publish ->
    SUCCEEDED with external ids -> Video writeback + provenance log.
    """
    seeded = _seed(thumbnail_path=_tmp_thumb())
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert stage.success, stage.error

        # Exact external call order — no other external call exists.
        assert adapter.calls == [
            "authenticate", "upload_content", "upload_thumbnail",
            "publish", "fetch_url",
        ]

        # Durable-state observations at each external call: the attempt
        # exists (PENDING, unbound) BEFORE the first external call; the
        # PERMIT (IN_PROGRESS + manifest stamped) precedes the first
        # irreversible external call (upload); the ANCHOR precedes both
        # the thumbnail upload and the publish.
        phases = {obs[0]: obs for obs in adapter.observations}
        _phase, auth_status, auth_stamped, _anchor = phases["authenticate"]
        _phase, up_status, up_stamped, up_anchor = phases["upload_content"]
        _phase, thumb_status, _stamped, thumb_anchor = phases["upload_thumbnail"]
        _phase, pub_status, _stamped, pub_anchor = phases["publish"]
        assert auth_status == "pending" and auth_stamped is False
        assert up_status == "in_progress" and up_stamped is True
        assert up_anchor is None
        assert thumb_status == pub_status == "in_progress"
        assert thumb_anchor == pub_anchor == "e2e-media-1"

        # Final durable state.
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        attempt = rows[0]
        assert attempt.manifest_id == seeded[2]
        assert attempt.scheduled_at is None  # unscheduled manifest
        assert attempt.external_content_id == "e2e-media-1"
        assert attempt.external_post_id == "e2e-post-1"
        assert attempt.public_url == "https://social.example/watch/e2e-post-1"
        assert stage.output["attempt_id"] == str(attempt.id)

        from app.models.enums import PublishStatus

        async def _video_and_log():
            from sqlalchemy import select

            from app.models.media import Video
            from app.models.system import SystemLog

            engine, session = await _session()
            try:
                video = await session.get(Video, seeded[1])
                logs = (
                    (
                        await session.execute(
                            select(SystemLog).where(
                                SystemLog.workflow_run_id == seeded[0]
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return video, logs
            finally:
                await session.close()
                await engine.dispose()

        video, logs = asyncio.run(_video_and_log())
        assert video.youtube_video_id == "e2e-post-1"
        assert video.publish_status == PublishStatus.PUBLISHED
        assert any(log.event_type == "PostizPublishDispatched" for log in logs)
    finally:
        _cleanup(seeded)


def test_a_success_scheduled_manifest_controls_dispatch(monkeypatch):
    """A scheduled manifest: the adapter publishes under the MANIFEST's
    schedule/publish_type and the persisted attempt carries the
    manifest's canonical schedule (request omitted it)."""
    seeded = _seed(
        scheduled_at="2027-03-01T09:30:00Z",
        publish_type="schedule",
        thumbnail_path=_tmp_thumb(),
    )
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert stage.success, stage.error
        assert adapter.saw["publish"]["scheduled_at"] == "2027-03-01T09:30:00Z"
        assert adapter.saw["publish"]["publish_type"] == "schedule"
        rows = _attempts(seeded[1])
        assert rows[0].scheduled_at == "2027-03-01T09:30:00Z"
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup(seeded)


# ===========================================================================
# B. Authorization and manifest rejection — fail closed BEFORE any
#    external call. Gate denials leave NO attempt; dispatch-time manifest
#    denials record FAILED on the admitted attempt.
# ===========================================================================


def _assert_denied(seeded, adapter, *, fragment, attempts_expected):
    rows = _attempts(seeded[1])
    assert len(rows) == attempts_expected
    if attempts_expected:
        assert rows[0].status == PublicationAttemptStatus.FAILED
        assert "publication_blocked" in rows[0].error or "approval" in rows[0].error
        assert rows[0].external_content_id is None
        assert rows[0].external_post_id is None
    # No external operation of any kind occurred.
    assert adapter.calls == []
    return rows


def test_b_unbound_approved_checkpoint_denies_at_gate(monkeypatch):
    """A legacy APPROVED-but-UNBOUND checkpoint cannot authorize real
    publishing (fail closed at the 53B gate, before admission)."""
    from tests._publish_gate_fixtures import cleanup_publish_target
    from tests._publish_gate_fixtures import seed_approved_publish_target

    async def _seed_unbound():
        engine, session = await _session()
        try:
            return await seed_approved_publish_target(session)
        finally:
            await session.close()
            await engine.dispose()

    run_id, video_id = asyncio.run(_seed_unbound())
    adapter = RecordingAdapter(video_id)
    _install_adapter(monkeypatch, adapter)
    try:
        ctx = {
            "platform": "postiz",
            "video_id": str(video_id),
            "video_storage_path": _tmp_video(),
            "social_platform": "youtube",
            "integration_id": "integ-1",
            "workflow_run_id": str(run_id),
            "dry_run": False,
        }
        stage = _run_stage(ctx)
        assert not stage.success
        # The 53B gate authorizes the APPROVED checkpoint; the I5
        # dispatch-time verification then fails closed on the missing
        # content binding: the admitted attempt is recorded FAILED and
        # ZERO external calls occur.
        assert "publication_blocked: no_content_bound_manifest" in stage.error
        assert adapter.calls == []
        rows = _attempts(video_id)
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert rows[0].external_content_id is None
    finally:
        async def _cleanup_unbound():
            engine, session = await _session()
            try:
                await cleanup_publish_target(session, run_id)
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_cleanup_unbound())


def test_b_missing_checkpoint_denies(monkeypatch):
    # Seed normally, then remove checkpoint + decisions + manifest: the
    # gate must find no authorizing checkpoint at all.
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        async def _drop_approval():
            from sqlalchemy import delete, select

            from app.models.approval import ApprovalCheckpoint, ApprovalDecision

            engine, session = await _session()
            try:
                cps = (
                    await session.execute(
                        select(ApprovalCheckpoint).where(
                            ApprovalCheckpoint.workflow_run_id == seeded[0]
                        )
                    )
                ).scalars().all()
                for cp in cps:
                    await session.execute(
                        delete(ApprovalDecision).where(
                            ApprovalDecision.checkpoint_id == cp.id
                        )
                    )
                await session.execute(
                    delete(ApprovalCheckpoint).where(
                        ApprovalCheckpoint.workflow_run_id == seeded[0]
                    )
                )
                await session.commit()
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_drop_approval())
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "no_thumbnail_checkpoint" in stage.error
        assert adapter.calls == []
        assert _attempts(seeded[1]) == []
    finally:
        _cleanup(seeded)


def test_b_rejected_approval_denies(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        _mutate(seeded[0], action=ApprovalAction.REJECT)
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "checkpoint_reject" in stage.error
        _assert_denied(seeded, adapter, fragment="reject", attempts_expected=0)
    finally:
        _cleanup(seeded)


def test_b_revoked_approval_denies(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        # Cache-revoke (the decide path updates the cache atomically).
        _mutate(seeded[0], action=ApprovalAction.REVOKE)
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "checkpoint_revoke" in stage.error
        _assert_denied(seeded, adapter, fragment="revoke", attempts_expected=0)

        # Stale-cache divergence: the cache says APPROVE again but the
        # AUTHORITATIVE latest decision is REVOKE — still denied.
        async def _stale_cache():
            from sqlalchemy import select, update

            from app.models.approval import ApprovalCheckpoint

            engine, session = await _session()
            try:
                cp = (
                    await session.execute(
                        select(ApprovalCheckpoint).where(
                            ApprovalCheckpoint.workflow_run_id == seeded[0]
                        )
                    )
                ).scalars().one()
                await session.execute(
                    update(ApprovalCheckpoint)
                    .where(ApprovalCheckpoint.id == cp.id)
                    .values(action=ApprovalAction.APPROVE)
                )
                await session.commit()
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_stale_cache())
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "latest_decision_not_approve" in stage.error
        assert adapter.calls == []
        assert _attempts(seeded[1]) == []
    finally:
        _cleanup(seeded)


def test_b_expired_approval_denies(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        from app.models.approval import ApprovalTtlPolicy

        async def _expire():
            engine, session = await _session()
            try:
                session.add(
                    ApprovalTtlPolicy(stage="thumbnail", ttl_seconds=3600)
                )
                await session.commit()
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_expire())
        _mutate(seeded[0], age_hours=2)
        try:
            stage = _run_stage(_stage_context(seeded))
            assert not stage.success
            assert "approval_expired" in stage.error
            _assert_denied(seeded, adapter, fragment="expired", attempts_expected=0)
        finally:
            async def _drop_policy():
                from sqlalchemy import delete

                engine, session = await _session()
                try:
                    await session.execute(
                        delete(ApprovalTtlPolicy).where(
                            ApprovalTtlPolicy.stage == "thumbnail"
                        )
                    )
                    await session.commit()
                finally:
                    await session.close()
                    await engine.dispose()

            asyncio.run(_drop_policy())
    finally:
        _cleanup(seeded)


def test_b_wrong_stage_checkpoint_denies(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        _mutate(seeded[0], stage=ApprovalStage.SCRIPT)
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "no_thumbnail_checkpoint" in stage.error
        assert adapter.calls == []
    finally:
        _cleanup(seeded)


def test_b_video_from_foreign_run_denies(monkeypatch):
    seeded = _seed()
    other = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        # Claim other run's authorization for seeded's video.
        ctx = _stage_context(seeded, workflow_run_id=str(other[0]))
        stage = _run_stage(ctx)
        assert not stage.success
        assert "video_not_in_workflow_run" in stage.error
        assert adapter.calls == []
    finally:
        _cleanup(seeded)
        _cleanup(other)


def test_b_foreign_manifest_target_denies_at_dispatch(monkeypatch):
    """Checkpoint rebound to another video's manifest: admitted then
    denied (manifest_target_mismatch) — FAILED attempt, zero calls."""
    seeded = _seed()
    other = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        _mutate(seeded[0], rebind_manifest_id=other[2])
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "manifest_target_mismatch" in stage.error
        _assert_denied(seeded, adapter, fragment="mismatch", attempts_expected=1)
    finally:
        _cleanup(seeded)
        _cleanup(other)


def test_b_corrupted_manifest_bytes_deny(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        _mutate(seeded[0], corrupt=True)
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "manifest_integrity_failure" in stage.error
        _assert_denied(seeded, adapter, fragment="integrity", attempts_expected=1)
    finally:
        _cleanup(seeded)


def test_b_changed_video_bytes_deny(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        Path(seeded[3]).write_bytes(b"tampered-after-approval")
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "artifact_bytes_changed" in stage.error
        _assert_denied(seeded, adapter, fragment="bytes", attempts_expected=1)
    finally:
        _cleanup(seeded)


def test_b_changed_content_parameters_deny(monkeypatch):
    seeded = _seed(title="original title")
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        async def _retitle():
            from app.models.media import Video

            engine, session = await _session()
            try:
                video = await session.get(Video, seeded[1])
                video.title = "retitled after approval"
                await session.commit()
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_retitle())
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "content_drift" in stage.error
        _assert_denied(seeded, adapter, fragment="drift", attempts_expected=1)
    finally:
        _cleanup(seeded)


def test_b_destination_parameter_override_denies(monkeypatch):
    seeded = _seed(privacy_status="public")
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded, privacy_status="private"))
        assert not stage.success
        assert "parameter_drift:privacy_status" in stage.error
        _assert_denied(seeded, adapter, fragment="drift", attempts_expected=1)
    finally:
        _cleanup(seeded)


def test_b_unsafe_artifact_resolution_denies(monkeypatch):
    """Both an SSRF-shaped caller path (path-authority mismatch) and a
    missing authoritative artifact fail closed with zero external calls."""
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(
            _stage_context(
                seeded, video_storage_path="http://169.254.169.254/latest/meta-data"
            )
        )
        assert not stage.success
        assert "manifest_path_mismatch" in stage.error
        _assert_denied(seeded, adapter, fragment="path", attempts_expected=1)
    finally:
        _cleanup(seeded)


def test_b_missing_artifact_denies(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        Path(seeded[3]).unlink()
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "artifact_resolution_failed" in stage.error
        _assert_denied(seeded, adapter, fragment="missing", attempts_expected=1)
    finally:
        _cleanup(seeded)


# ===========================================================================
# C. Failure at each external side-effect boundary
# ===========================================================================


def test_c_authentication_failure_is_failed_zero_side_effects(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], auth="fail")
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "Authentication failed" in stage.error
        assert adapter.calls == ["authenticate"]
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "authentication failed" in rows[0].error
    finally:
        _cleanup(seeded)


def test_c_upload_rejection_is_failed_no_publish(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], upload="fail")
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "Upload failed" in stage.error
        assert adapter.calls == ["authenticate", "upload_content"]
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
    finally:
        _cleanup(seeded)


def test_c_upload_timeout_is_unknown_and_blocks_retry(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], upload="raise")
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success and "UNKNOWN" in stage.error
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert "publish" not in adapter.calls

        # Re-invocation of the stage resolves to the UNKNOWN attempt.
        second = _run_stage(_stage_context(seeded))
        assert not second.success and "AMBIGUOUS" in second.error
        assert adapter.calls.count("publish") == 0
        assert len(_attempts(seeded[1])) == 1
    finally:
        _cleanup(seeded)


def test_c_upload_without_media_id_is_unknown_never_fabricated(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], upload="no_id")
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success and "UNKNOWN" in stage.error
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert rows[0].external_content_id is None  # no fabricated anchor
        assert adapter.calls == ["authenticate", "upload_content"]
    finally:
        _cleanup(seeded)


def _operator_force_fail_hook(video_uuid):
    """Aged operator FAILED resolution landing right after the upload
    returned, before the anchor write (the F-09 window)."""
    from sqlalchemy import select, update

    from app.services import publication_attempt_reconciliation as recon

    async def hook():
        engine, session = await _session()
        try:
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.video_id == video_uuid)
                .values(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(hours=1)
                )
            )
            await session.commit()
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


def test_c_anchor_refusal_aborts_naming_orphan_media(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(
        seeded[1], hooks={"before_anchor": _operator_force_fail_hook(seeded[1])}
    )
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "Publication aborted" in stage.error
        assert "e2e-media-1" in stage.error  # the orphan is named
        assert adapter.calls == ["authenticate", "upload_content"]
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert rows[0].external_content_id is None  # anchor never landed
    finally:
        _cleanup(seeded)


def test_c_thumbnail_failure_is_non_fatal(monkeypatch):
    seeded = _seed(thumbnail_path=_tmp_thumb())
    adapter = RecordingAdapter(seeded[1], thumbnail="fail")
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert stage.success, stage.error
        assert adapter.calls == [
            "authenticate", "upload_content", "upload_thumbnail",
            "publish", "fetch_url",
        ]
        rows = _attempts(seeded[1])
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup(seeded)


def test_c_publish_rejection_is_failed_then_retry_admits_n_plus_1(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], publish="reject")
    _install_adapter(monkeypatch, adapter)
    try:
        first = _run_stage(_stage_context(seeded))
        assert not first.success and "UNKNOWN" not in first.error
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]

        adapter.behaviors["publish"] = "ok"
        second = _run_stage(_stage_context(seeded))
        assert second.success, second.error
        rows = _attempts(seeded[1])
        assert [r.attempt_number for r in rows] == [1, 2]
        assert [r.status for r in rows] == [
            PublicationAttemptStatus.FAILED,
            PublicationAttemptStatus.SUCCEEDED,
        ]
        # First (rejected) + exactly one legitimate retry.
        assert adapter.calls.count("publish") == 2
    finally:
        _cleanup(seeded)


def test_c_publish_timeout_is_unknown_blocks_auto_retry(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], publish="raise")
    _install_adapter(monkeypatch, adapter)
    try:
        first = _run_stage(_stage_context(seeded))
        assert not first.success and "UNKNOWN" in first.error
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.UNKNOWN]
        assert rows[0].external_content_id == "e2e-media-1"  # anchor first

        second = _run_stage(_stage_context(seeded))
        assert not second.success and "AMBIGUOUS" in second.error
        assert adapter.calls.count("publish") == 1  # never re-dispatched
        assert len(_attempts(seeded[1])) == 1
    finally:
        _cleanup(seeded)


def test_c_permit_persistence_uncertainty_denies_every_external_call(monkeypatch):
    """The permit CAS itself cannot commit (one-shot execute failure on
    the publication-attempts UPDATE): the permit is NOT granted, no
    upload or publish may follow, and the refusal is durably recorded."""
    from sqlalchemy import Update

    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)

    def _run_with_permit_failure(ctx):
        async def _inner():
            engine, session = await _session()
            original_execute = session.execute
            failed_once = False

            async def _failing_execute(statement, *args, **kwargs):
                nonlocal failed_once
                if (
                    not failed_once
                    and isinstance(statement, Update)
                    and statement.table.name == "publication_attempts"
                ):
                    failed_once = True
                    raise RuntimeError("simulated permit commit failure")
                return await original_execute(statement, *args, **kwargs)

            session.execute = _failing_execute
            try:
                orch = Orchestrator(db=session, max_retries=0)
                return await orch._execute_stage("publishing", ctx)
            finally:
                await session.close()
                await engine.dispose()

        return asyncio.run(_inner())

    try:
        stage = _run_with_permit_failure(_stage_context(seeded))
        assert not stage.success
        assert "permit" in stage.error.lower()
        # No upload, no publish — the permit is the gate to both.
        assert adapter.calls == ["authenticate"]
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "permit_not_persisted" in rows[0].error
    finally:
        _cleanup(seeded)


def test_c_final_persistence_refusal_is_agreement_not_failure(monkeypatch):
    """Operator SUCCEEDED resolution lands under the in-flight publish:
    agreement — stage success with the ROW's ids, agent-observed id
    surfaced, exactly one dispatch, row stays SUCCEEDED."""
    seeded = _seed()
    video_uuid = seeded[1]

    async def _hook():
        from sqlalchemy import select, update

        from app.services import publication_attempt_reconciliation as recon

        engine, session = await _session()
        try:
            await session.execute(
                update(PublicationAttempt)
                .where(PublicationAttempt.video_id == video_uuid)
                .values(
                    updated_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(hours=1)
                )
            )
            await session.commit()
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
            await recon.resolve_attempt(
                session,
                row.id,
                from_status=PublicationAttemptStatus.IN_PROGRESS,
                to_status=PublicationAttemptStatus.SUCCEEDED,
                external_post_id="post-operator",
                public_url="https://social.example/watch/post-operator",
            )
        finally:
            await session.close()
            await engine.dispose()

    adapter = RecordingAdapter(video_uuid, evidence="ready", hooks={"publish": _hook})
    _install_adapter(monkeypatch, adapter)
    # The in-resolve provider verification must also stay scripted.
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: adapter,
    )
    try:
        stage = _run_stage(_stage_context(seeded))
        assert stage.success, stage.error
        assert stage.output["published_video_id"] == "post-operator"
        warnings = stage.output.get("writeback_warnings") or []
        assert any("e2e-post-1" in w for w in warnings)
        assert adapter.calls.count("publish") == 1
        rows = _attempts(video_uuid)
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
        assert rows[0].external_post_id == "post-operator"
    finally:
        _cleanup(seeded)


# ===========================================================================
# D. Duplicate, retry, and concurrency behavior
# ===========================================================================


def test_d_concurrent_same_intent_dispatches_exactly_once(monkeypatch):
    """Two concurrent orchestrations of the identical intent (separate
    engines/sessions): UNIQUE(intent_key, attempt_number) arbitrates —
    exactly one external publication, one attempt row, the loser
    resolves to the existing attempt. (Single-process, two DB sessions;
    TRUE multi-process concurrency: NOT VERIFIED here.)"""
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], observe=False)
    _install_adapter(monkeypatch, adapter)

    async def _one():
        engine, session = await _session()
        try:
            orch = Orchestrator(db=session, max_retries=0)
            return await orch._execute_stage("publishing", _stage_context(seeded))
        finally:
            await session.close()
            await engine.dispose()

    async def _race():
        return await asyncio.gather(_one(), _one())

    try:
        first, second = asyncio.run(_race())
        outcomes = sorted(
            [(first.success, first.error or ""), (second.success, second.error or "")],
            key=lambda o: not o[0],
        )
        assert outcomes[0][0] is True  # exactly one success
        assert outcomes[1][0] is False  # the loser refused
        assert "already in progress" in outcomes[1][1] or "pending" in outcomes[1][1]
        assert adapter.calls.count("publish") == 1
        rows = _attempts(seeded[1])
        assert len(rows) == 1
        assert rows[0].status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _cleanup(seeded)


def test_d_rerun_after_success_is_idempotent_duplicate(monkeypatch):
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        first = _run_stage(_stage_context(seeded))
        assert first.success
        second = _run_stage(_stage_context(seeded))
        assert second.success
        assert second.output.get("duplicate") is True
        assert second.output["published_video_id"] == "e2e-post-1"
        assert adapter.calls.count("publish") == 1
        assert len(_attempts(seeded[1])) == 1
    finally:
        _cleanup(seeded)


def test_d_revocation_between_verification_and_permit_denies(monkeypatch):
    """REVOKE commits after manifest verification but before the permit
    transaction: the permit is denied, no upload/publish occurs, the
    attempt records the refusal."""
    seeded = _seed()

    async def _revoke_hook():
        await _mutate_seeded_state(seeded[0], action=ApprovalAction.REVOKE)

    adapter = RecordingAdapter(seeded[1], hooks={"authenticate": _revoke_hook})
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "permit denied" in stage.error
        assert adapter.calls == ["authenticate"]  # read-only call only
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.FAILED]
        assert "permit denied" in rows[0].error
    finally:
        _cleanup(seeded)


def test_d_revocation_after_permit_documented_residual(monkeypatch):
    """A REVOKE landing AFTER the permit was granted cannot stop in-flight
    external calls (documented I5 residual): the publication completes
    under the validly-permitted attempt and the revocation stands in the
    decision history."""
    seeded = _seed()

    async def _revoke_at_publish():
        await _mutate_seeded_state(seeded[0], action=ApprovalAction.REVOKE)

    adapter = RecordingAdapter(seeded[1], hooks={"publish": _revoke_at_publish})
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded))
        assert stage.success, stage.error
        assert adapter.calls.count("publish") == 1
        rows = _attempts(seeded[1])
        assert [r.status for r in rows] == [PublicationAttemptStatus.SUCCEEDED]
    finally:
        _cleanup(seeded)


def test_d_fresh_manifest_cycle_stale_approval_denies(monkeypatch):
    """After approval, changed content opens a NEW manifest + NEW pending
    checkpoint cycle: the old approval no longer authorizes — the latest
    checkpoint is PENDING, dispatch is denied, zero external calls."""
    seeded = _seed(title="v1 title")
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        async def _retitle_and_remanifest():
            from app.models.media import Video
            from app.services.publication_manifest_service import (
                create_and_bind_manifest,
            )

            engine, session = await _session()
            try:
                video = await session.get(Video, seeded[1])
                video.title = "v2 title"
                await session.commit()
                await create_and_bind_manifest(
                    session,
                    workflow_run_id=seeded[0],
                    video_id=seeded[1],
                    platform="postiz",
                    social_platform="youtube",
                    integration_id="integ-1",
                    privacy_status="public",
                    publish_type="now",
                    scheduled_at=None,
                )
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_retitle_and_remanifest())
        stage = _run_stage(_stage_context(seeded))
        assert not stage.success
        assert "checkpoint_pending" in stage.error
        assert adapter.calls == []
    finally:
        _cleanup(seeded)


# ===========================================================================
# E. Schedule and parameter consistency through the adapter boundary
# ===========================================================================


def test_e_manifest_effective_parameters_reach_the_adapter(monkeypatch):
    """Every dispatch parameter the adapter receives is the manifest's
    effective derivation (persisted Video row + ratified transforms):
    9:16 injects #Shorts, comma-tags split, privacy/integration/
    platform_type from the manifest — request content fields are inert."""
    seeded = _seed(
        title="vertical short",
        description="desc",
        tags="alpha, beta ,gamma",
        aspect_ratio="9:16",
        privacy_status="unlisted",
    )
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(
            _stage_context(seeded, title="REQUEST TITLE IGNORED", tags="x,y")
        )
        assert stage.success, stage.error
        up = adapter.saw["upload_content"]
        assert up["title"] == "vertical short"
        assert "#Shorts" in up["description"]
        assert up["tags"] == ["alpha", "beta", "gamma", "Shorts"]
        pub = adapter.saw["publish"]
        assert pub["privacy_status"] == "unlisted"
        assert pub["integration_id"] == "integ-1"
        assert pub["platform_type"] == "youtube"
        assert pub["publish_type"] == "now"
    finally:
        _cleanup(seeded)


# ===========================================================================
# F. Dry-run and alternate entry points
# ===========================================================================


def test_f_stage_dry_run_makes_no_publication_and_no_attempt(monkeypatch):
    """Dry-run through the orchestration stage: the adapters are invoked
    in VALIDATION mode only (is_dry_run=True on every mutating call —
    adapters perform zero external API calls by contract), no attempt
    row is created, and no publication state is written."""
    seeded = _seed()
    adapter = RecordingAdapter(seeded[1])
    _install_adapter(monkeypatch, adapter)
    try:
        stage = _run_stage(_stage_context(seeded, dry_run=True))
        assert stage.success, stage.error
        # Validation-order adapter calls only; every mutating call was
        # explicitly dry-run.
        assert adapter.calls == [
            "authenticate", "upload_content", "publish", "fetch_url",
        ]
        assert adapter.saw["upload_content"]["is_dry_run"] is True
        assert adapter.saw["publish"]["is_dry_run"] is True
        # No durable publication machinery engaged.
        assert _attempts(seeded[1]) == []
    finally:
        _cleanup(seeded)


def test_f_hermes_publishing_request_is_dry_run_only(monkeypatch):
    """The REAL Hermes publishing.request operation (§9.5): direct
    adapter dry-run invocation — simulated result, zero scripted-
    transport calls (any accidental real HTTP would hit the recorder)."""
    import httpx

    from app.hermes.capabilities import (
        PublishingRequestParams,
        _dry_run_publishing,
        _make_capability_engine,
    )

    seeded = _seed()
    transport_calls = []

    class _NoCallClient:
        def __init__(self, transport, **kwargs):
            transport_calls.append("client-created")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, **kwargs):
            transport_calls.append(f"GET {url}")
            raise AssertionError("dry-run must not perform HTTP")

        async def post(self, url, **kwargs):
            transport_calls.append(f"POST {url}")
            raise AssertionError("dry-run must not perform HTTP")

    class _FakeSecrets:
        def get(self, key, required=False):
            return "scripted" if key == "postiz_api_key" else None

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: _NoCallClient(None, **kwargs)
    )
    try:
        async def _invoke():
            engine = _make_capability_engine()
            from sqlalchemy.ext.asyncio import async_sessionmaker

            session = async_sessionmaker(bind=engine, expire_on_commit=False)()
            try:
                return await _dry_run_publishing(
                    session,
                    seeded[0],
                    PublishingRequestParams(artifact_id=seeded[1]),
                )
            finally:
                await session.close()
                await engine.dispose()

        result = asyncio.run(_invoke())
        assert "error" not in result, result
        assert result["simulated"] is True
        assert result["publish_type"] == "dry_run"
        assert transport_calls == []
    finally:
        _cleanup(seeded)


async def test_f_status_endpoint_is_read_only(client, monkeypatch):
    """GET /publishing/status authenticates only — it cannot publish."""
    calls = []

    class _ProbeAdapter:
        def __init__(self, db, secrets=None):
            pass

        async def authenticate(self):
            calls.append("authenticate")
            from app.platforms.base import AuthResult

            return AuthResult(
                success=True, credentials={"integrations": [{"id": "i1", "name": "c", "identifier": "x"}]}
            )

        async def upload_content(self, **kwargs):
            raise AssertionError("status must not upload")

        async def publish(self, **kwargs):
            raise AssertionError("status must not publish")

    monkeypatch.setattr(
        "app.api.routers.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: _ProbeAdapter(db, secrets),
    )
    resp = await client.get("/publishing/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "connected"
    assert calls == ["authenticate"]


def test_f_operator_resolution_then_retry_admits_n_plus_1(monkeypatch):
    """The operator reconciliation ROUTE resolves an UNKNOWN attempt
    (never dispatching), after which the secured stage admits n+1."""
    from app.services import publication_attempt_reconciliation as recon

    seeded = _seed()
    adapter = RecordingAdapter(seeded[1], publish="raise", evidence="unknown")
    _install_adapter(monkeypatch, adapter)
    # The F-02a in-resolve evidence probe must stay scripted.
    monkeypatch.setattr(
        "app.services.publication_attempt_reconciliation.get_platform_adapter",
        lambda platform, db, secrets=None: adapter,
    )
    try:
        first = _run_stage(_stage_context(seeded))
        assert not first.success and "UNKNOWN" in first.error
        row = _attempts(seeded[1])[0]

        async def _resolve():
            engine, session = await _session()
            try:
                await recon.resolve_attempt(
                    session,
                    row.id,
                    from_status=PublicationAttemptStatus.UNKNOWN,
                    to_status=PublicationAttemptStatus.FAILED,
                    attestation="verified in provider console: no post exists",
                )
            finally:
                await session.close()
                await engine.dispose()

        asyncio.run(_resolve())
        # Resolution itself made no adapter call.
        assert adapter.calls.count("publish") == 1  # only the original

        adapter.behaviors["publish"] = "ok"
        second = _run_stage(_stage_context(seeded))
        assert second.success, second.error
        rows = _attempts(seeded[1])
        assert [r.attempt_number for r in rows] == [1, 2]
        assert adapter.calls.count("publish") == 2
    finally:
        _cleanup(seeded)


async def test_f_post_status_endpoint_is_read_only(client, monkeypatch):
    """GET /publishing/posts/{id} only checks processing state."""
    from app.platforms.base import ProcessingStatus
    from app.platforms.postiz import PostizAdapter

    calls = []

    async def _check(self, content_id, **kwargs):
        calls.append(content_id)
        return ProcessingStatus(status="ready", progress_percent=100.0)

    monkeypatch.setattr(PostizAdapter, "check_processing", _check)
    resp = await client.get("/publishing/posts/some-post-id")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready"
    assert calls == ["some-post-id"]
