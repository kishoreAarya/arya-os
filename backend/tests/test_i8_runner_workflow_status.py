"""Phase 54B-I8 Workstream C: Runner-level workflow status transitions.

Drives the REAL Runner (real WorkflowRun creation service, real
Orchestrator stage loop, real context merging, real per-stage retry
loop, real final-state persistence) with a REDUCED pipeline selected
through the orchestrator's own pipeline mechanism (`_PIPELINE`):
trend -> script -> publishing -> analytics.

- trend: a scripted stub agent (registry seam) that assembles the REAL
  authorization chain mid-workflow through the REAL services using the
  Runner's own session (Video row from a real artifact, publication
  manifest via the real I4 service, bound+approved THUMBNAIL checkpoint)
  and emits the identity fields into the running context — the same
  role the storage/metadata stages play in the full pipeline.
- script/analytics: scripted stubs (registry seam) with configurable
  failure/raise behavior for the status-transition scenarios.
- publishing: the REAL AGENT_REGISTRY entry (PublishingAgent) — the
  full 53B gate + I5 manifest verification + permit + anchor + publish
  chain, with only the platform adapter scripted.

No real AI/media providers are invoked; no real publishing provider is
contacted. Workflow cancellation does not exist in the current contract
(no API, no service, no state) — nothing to test without inventing new
behavior.
"""
import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.agents.base import AgentResult
from app.models.enums import PublicationAttemptStatus, WorkflowStatus
from app.models.publication import PublicationAttempt
from app.workflows.models import WorkflowInput
from app.workflows.runner import Runner

_PIPELINE_UNDER_TEST = ["trend", "script", "publishing", "analytics"]


# ---------------------------------------------------------------------------
# Scripted stub agents (registry seam)
# ---------------------------------------------------------------------------


class TrendStub:
    """Assembles the real manifest-bound authorization chain for the run
    being executed (using the Runner's own session) and emits the
    publishing identity fields into the context."""

    def __init__(self, db, *, authorize=True):
        self._db = db
        self.authorize = authorize

    async def run(self, context: dict) -> AgentResult:
        from app.models.media import Video
        from app.services.publication_manifest_service import (
            create_and_bind_manifest,
        )

        # A FRESH artifact per workflow run (unique bytes -> unique
        # manifest digest; each run is a distinct publication intent).
        artifact = Path(tempfile.mkstemp(prefix="i8-runner-", suffix=".mp4")[1])
        artifact.write_bytes(f"i8-runner-video-{uuid.uuid4().hex}".encode())
        _ARTIFACTS.setdefault("videos", []).append(str(artifact))
        video = Video(
            workflow_run_id=uuid.UUID(context["workflow_run_id"]),
            storage_path=str(artifact),
            title="i8 runner title",
            description="i8 runner description",
            tags="alpha,beta",
        )
        self._db.add(video)
        await self._db.flush()

        if self.authorize:
            await create_and_bind_manifest(
                self._db,
                workflow_run_id=uuid.UUID(context["workflow_run_id"]),
                video_id=video.id,
                platform="postiz",
                social_platform="youtube",
                integration_id="integ-1",
                privacy_status="public",
                publish_type="now",
                scheduled_at=None,
            )
            # Approve the bound checkpoint (mirroring decide semantics).
            from app.models.approval import ApprovalCheckpoint, ApprovalDecision
            from app.models.enums import ApprovalAction, ApprovalStage

            from sqlalchemy import select

            cp = (
                (
                    await self._db.execute(
                        select(ApprovalCheckpoint).where(
                            ApprovalCheckpoint.workflow_run_id
                            == uuid.UUID(context["workflow_run_id"]),
                            ApprovalCheckpoint.stage == ApprovalStage.THUMBNAIL,
                        )
                    )
                )
                .scalars()
                .one()
            )
            decided_at = datetime.now(UTC).replace(tzinfo=None)
            self._db.add(
                ApprovalDecision(
                    checkpoint_id=cp.id,
                    sequence_number=1,
                    action=ApprovalAction.APPROVE,
                    decided_at=decided_at,
                    decided_by="i8-runner",
                )
            )
            cp.action = ApprovalAction.APPROVE
            cp.decided_at = decided_at
            await self._db.commit()

        return AgentResult(
            success=True,
            output={
                "video_id": str(video.id),
                "video_storage_path": str(artifact),
                "platform": "postiz",
                "social_platform": "youtube",
                "integration_id": "integ-1",
            },
        )


class ScriptStub:
    def __init__(self, db=None, *, fail=False, raise_times=0):
        self._db = db
        self.fail = fail
        self.raise_times = raise_times
        self.calls = 0

    async def run(self, context: dict) -> AgentResult:
        self.calls += 1
        if self.calls <= self.raise_times:
            raise RuntimeError(f"scripted stage exception #{self.calls}")
        if self.fail:
            return AgentResult(success=False, error="scripted stage failure")
        return AgentResult(success=True, output={"script_content": "s"})


class AnalyticsStub:
    def __init__(self, db=None):
        self._db = db

    async def run(self, context: dict) -> AgentResult:
        return AgentResult(success=True, output={"analytics": "ok"})


# ---------------------------------------------------------------------------
# Scripted platform adapter (the external publishing boundary)
# ---------------------------------------------------------------------------


class ScriptedPublishAdapter:
    def __init__(self):
        self.calls = []

    async def authenticate(self):
        from app.platforms.base import AuthResult

        self.calls.append("authenticate")
        return AuthResult(success=True, credentials={"api_key": "SCRIPTED"})

    async def upload_content(self, **kwargs):
        from app.platforms.base import UploadResult

        self.calls.append("upload_content")
        return UploadResult(success=True, content_id="runner-media-1")

    async def upload_thumbnail(self, **kwargs):
        raise AssertionError("no thumbnail in these tests")

    async def publish(self, **kwargs):
        from app.platforms.base import PublishResult

        self.calls.append("publish")
        if kwargs.get("is_dry_run"):
            return PublishResult(success=True, published_content_id="dry")
        if _PUBLISH_BEHAVIOR["publish"] == "raise":
            raise TimeoutError("dropped after submission")
        return PublishResult(
            success=True,
            published_content_id="runner-post-1",
            publish_status="published",
            url="https://social.example/watch/runner-post-1",
        )

    async def fetch_url(self, **kwargs):
        self.calls.append("fetch_url")
        return "https://social.example/watch/runner-post-1"


_ARTIFACTS = {}
_PUBLISH_BEHAVIOR = {"publish": "ok"}


def _install_pipeline(monkeypatch, *, trend=None, script=None):
    import app.workflows.orchestrator as orch_mod
    from app.agents.registry import AGENT_REGISTRY

    monkeypatch.setattr(orch_mod, "_PIPELINE", list(_PIPELINE_UNDER_TEST))
    trend_impl = trend or TrendStub
    script_impl = script or ScriptStub
    monkeypatch.setitem(AGENT_REGISTRY, "trend", trend_impl)
    monkeypatch.setitem(AGENT_REGISTRY, "script", script_impl)
    monkeypatch.setitem(AGENT_REGISTRY, "analytics", AnalyticsStub)
    # publishing keeps the REAL registry entry (PublishingAgent).


def _install_adapter(monkeypatch, adapter):
    monkeypatch.setattr(
        "app.agents.publishing.get_platform_adapter",
        lambda platform, db, secrets=None: adapter,
    )


async def _session():
    from app.hermes.capabilities import _make_capability_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_capability_engine()
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)()


def _make_project():
    async def _inner():
        from app.models.core import Project

        engine, session = await _session()
        try:
            project = Project(name=f"i8-runner-{uuid.uuid4().hex[:8]}")
            session.add(project)
            await session.commit()
            return project.id
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _wipe_project(project_id):
    async def _inner():
        from sqlalchemy import delete, select

        from app.models.approval import ApprovalCheckpoint, ApprovalDecision
        from app.models.core import Project, WorkflowRun
        from app.models.media import Video
        from app.models.publication import PublicationManifest
        from app.models.system import SystemLog

        engine, session = await _session()
        try:
            run_ids = [
                r
                for r in (
                    await session.execute(
                        select(WorkflowRun.id).where(
                            WorkflowRun.project_id == project_id
                        )
                    )
                )
                .scalars()
                .all()
            ]
            for run_id in run_ids:
                await session.execute(
                    delete(SystemLog).where(SystemLog.workflow_run_id == run_id)
                )
                await session.execute(
                    delete(ApprovalDecision).where(
                        ApprovalDecision.checkpoint_id.in_(
                            select(ApprovalCheckpoint.id).where(
                                ApprovalCheckpoint.workflow_run_id == run_id
                            )
                        )
                    )
                )
                await session.execute(
                    delete(PublicationAttempt).where(
                        PublicationAttempt.workflow_run_id == run_id
                    )
                )
                await session.execute(
                    delete(ApprovalCheckpoint).where(
                        ApprovalCheckpoint.workflow_run_id == run_id
                    )
                )
                await session.execute(
                    delete(PublicationManifest).where(
                        PublicationManifest.workflow_run_id == run_id
                    )
                )
                await session.execute(
                    delete(Video).where(Video.workflow_run_id == run_id)
                )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.project_id == project_id)
            )
            await session.execute(
                delete(Project).where(Project.id == project_id)
            )
            await session.commit()
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(_inner())
    for path in _ARTIFACTS.pop("videos", []):
        Path(path).unlink(missing_ok=True)
    if _ARTIFACTS.get("video"):
        Path(_ARTIFACTS["video"]).unlink(missing_ok=True)
    _ARTIFACTS.clear()


def _run_workflow(project_id, *, max_retries=0):
    async def _inner():
        engine, session = await _session()
        try:
            runner = Runner(db=session, max_retries=max_retries)
            result = await runner.start(
                workflow_input=WorkflowInput(
                    topic="i8 runner topic",
                    style="documentary",
                    duration=30,
                    platform="postiz",
                ),
                project_id=project_id,
            )
            return result
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _run_state(project_id):
    async def _inner():
        from sqlalchemy import select

        from app.models.core import WorkflowRun

        engine, session = await _session()
        try:
            runs = (
                (
                    await session.execute(
                        select(WorkflowRun).where(
                            WorkflowRun.project_id == project_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return sorted(runs, key=lambda r: r.created_at)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _attempts(project_id):
    async def _inner():
        from sqlalchemy import select

        from app.models.core import WorkflowRun

        engine, session = await _session()
        try:
            run_ids = (
                (
                    await session.execute(
                        select(WorkflowRun.id).where(
                            WorkflowRun.project_id == project_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            rows = []
            for run_id in run_ids:
                rows.extend(
                    (
                        await session.execute(
                            select(PublicationAttempt).where(
                                PublicationAttempt.workflow_run_id == run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            return sorted(rows, key=lambda r: r.created_at)
        finally:
            await session.close()
            await engine.dispose()

    return asyncio.run(_inner())


def _artifact():
    path = Path(tempfile.mkstemp(prefix="i8-runner-", suffix=".mp4")[1])
    path.write_bytes(b"i8-runner-video-bytes")
    return str(path)


# ===========================================================================
# 1. Successful completion
# ===========================================================================


def test_runner_success_completes_and_persists(monkeypatch):
    project_id = _make_project()
    adapter = ScriptedPublishAdapter()
    _install_pipeline(monkeypatch)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id)
        assert result.success, result.error
        assert result.status == WorkflowStatus.COMPLETED.value
        assert result.completed_stages == _PIPELINE_UNDER_TEST
        assert result.failed_stage is None

        # Persisted final WorkflowRun state.
        (run,) = _run_state(project_id)
        assert run.status == WorkflowStatus.COMPLETED
        assert run.total_cost_usd is not None

        # The real publishing chain ran under the real Runner.
        assert adapter.calls == [
            "authenticate", "upload_content", "publish", "fetch_url",
        ]
        (attempt,) = _attempts(project_id)
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
        assert attempt.external_post_id == "runner-post-1"
        assert attempt.manifest_id is not None  # permit stamped the binding
        assert attempt.scheduled_at is None
    finally:
        _wipe_project(project_id)


# ===========================================================================
# 2. A stage returning a controlled failure -> run FAILED, no false success
# ===========================================================================


def test_runner_stage_failure_fails_run_before_publishing(monkeypatch):
    project_id = _make_project()
    adapter = ScriptedPublishAdapter()
    _install_pipeline(
        monkeypatch, script=lambda db=None: ScriptStub(db, fail=True)
    )
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id)
        assert not result.success
        assert result.status == WorkflowStatus.FAILED.value
        assert result.failed_stage == "script"
        assert result.completed_stages == ["trend"]

        (run,) = _run_state(project_id)
        assert run.status == WorkflowStatus.FAILED

        # No publishing machinery engaged: zero adapter calls, no attempt.
        assert adapter.calls == []
        assert _attempts(project_id) == []
    finally:
        _wipe_project(project_id)


# ===========================================================================
# 3. A stage raising an exception -> retried, then run FAILED
# ===========================================================================


def test_runner_stage_exception_fails_run_after_retries(monkeypatch):
    project_id = _make_project()
    adapter = ScriptedPublishAdapter()
    raising = ScriptStub(raise_times=99)
    _install_pipeline(monkeypatch, script=lambda db=None: raising)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id, max_retries=2)
        assert not result.success
        assert result.status == WorkflowStatus.FAILED.value
        assert result.failed_stage == "script"
        assert result.completed_stages == ["trend"]
        # The per-stage retry loop ran the full budget.
        assert raising.calls == 3  # 1 + 2 retries
        assert adapter.calls == []
        assert _attempts(project_id) == []
    finally:
        _wipe_project(project_id)


# ===========================================================================
# 4. Retryable failure recovers -> run COMPLETED, retry observed
# ===========================================================================


def test_runner_retryable_stage_failure_recovers(monkeypatch):
    project_id = _make_project()
    adapter = ScriptedPublishAdapter()
    flaky = ScriptStub(raise_times=1)
    _install_pipeline(monkeypatch, script=lambda db=None: flaky)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id, max_retries=2)
        assert result.success, result.error
        assert result.status == WorkflowStatus.COMPLETED.value
        assert "script" in result.completed_stages
        assert flaky.calls == 2  # one failure, one successful retry

        (run,) = _run_state(project_id)
        assert run.status == WorkflowStatus.COMPLETED
        (attempt,) = _attempts(project_id)
        assert attempt.status == PublicationAttemptStatus.SUCCEEDED
    finally:
        _wipe_project(project_id)


# ===========================================================================
# 5. Publishing authorization refusal -> run FAILED at the publishing stage
# ===========================================================================


def test_runner_publishing_authorization_refusal_fails_run(monkeypatch):
    project_id = _make_project()
    adapter = ScriptedPublishAdapter()
    # The trend stub assembles the Video but NO manifest/approval.
    _install_pipeline(
        monkeypatch, trend=lambda db: TrendStub(db, authorize=False)
    )
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id)
        assert not result.success
        assert result.status == WorkflowStatus.FAILED.value
        assert result.failed_stage == "publishing"
        assert result.completed_stages == ["trend", "script"]

        (run,) = _run_state(project_id)
        assert run.status == WorkflowStatus.FAILED
        # Fail closed BEFORE any external call and before admission.
        assert adapter.calls == []
        assert _attempts(project_id) == []
    finally:
        _wipe_project(project_id)


# ===========================================================================
# 6. Publishing UNKNOWN -> run FAILED, manual-reconciliation state persists
# ===========================================================================


def test_runner_publishing_unknown_persists_manual_state(monkeypatch):
    project_id = _make_project()
    _PUBLISH_BEHAVIOR["publish"] = "raise"
    adapter = ScriptedPublishAdapter()
    _install_pipeline(monkeypatch)
    _install_adapter(monkeypatch, adapter)
    try:
        result = _run_workflow(project_id)
        assert not result.success
        assert result.failed_stage == "publishing"
        assert "UNKNOWN" in (result.error or "")

        (attempt,) = _attempts(project_id)
        assert attempt.status == PublicationAttemptStatus.UNKNOWN
        assert attempt.external_content_id == "runner-media-1"  # anchor held

        # A second, INDEPENDENT Runner execution (fresh content — each
        # workflow run is a distinct intent) completes normally and
        # NEVER touches run 1's UNKNOWN attempt: the manual-
        # reconciliation state is durable across workflow executions.
        _PUBLISH_BEHAVIOR["publish"] = "ok"
        second = _run_workflow(project_id)
        assert second.success, second.error
        assert second.status == WorkflowStatus.COMPLETED.value

        (run_one, run_two) = _run_state(project_id)
        assert run_one.status == WorkflowStatus.FAILED
        assert run_two.status == WorkflowStatus.COMPLETED

        attempts = _attempts(project_id)
        assert [a.status for a in attempts] == [
            PublicationAttemptStatus.UNKNOWN,  # run 1: untouched
            PublicationAttemptStatus.SUCCEEDED,  # run 2: independent
        ]
        assert attempts[0].error and "publish exception" in attempts[0].error
    finally:
        _PUBLISH_BEHAVIOR["publish"] = "ok"
        _wipe_project(project_id)
