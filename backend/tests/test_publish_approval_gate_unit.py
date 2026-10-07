"""Phase 53B — server-side publish approval gate (finding 53A-01).

Offline unit tests: mocked sessions/fixtures only. No database, no
Postiz, no external providers, no real publishing — denial paths assert
the publisher is never dispatched.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.publishing import PublishingAgent
from app.main import app
from app.models.enums import ApprovalAction, PublicationAttemptStatus
from app.services.publish_gate import (
    AUTHORIZING_STAGE,
    PublishApprovalDenied,
    assert_publish_authorized,
)
from fastapi.testclient import TestClient

RUN = uuid.uuid4()
VIDEO = uuid.uuid4()
OTHER_RUN = uuid.uuid4()


class _ExecResult:
    def __init__(self, scalar):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """Queued execute() results in call order."""

    def __init__(self, *results):
        self._queue = list(results)
        self.calls = 0

    async def execute(self, *_a, **_k):
        self.calls += 1
        if not self._queue:
            raise AssertionError("gate issued more queries than expected")
        return _ExecResult(self._queue.pop(0))


def _video(run_id=RUN):
    return SimpleNamespace(id=VIDEO, workflow_run_id=run_id)


def _checkpoint(action=ApprovalAction.APPROVE, decided=True, digest=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        workflow_run_id=RUN,
        stage=AUTHORIZING_STAGE,
        action=action,
        decided_at=datetime.now(UTC).replace(tzinfo=None) if decided else None,
        parameter_digest=digest,
    )


def _decision(action=ApprovalAction.APPROVE):
    return SimpleNamespace(action=action, sequence_number=1)


# ---------------------------------------------------------------------------
# Gate unit tests (mocked session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_checkpoint_blocks():
    db = _FakeSession(_video(), None)
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "no_thumbnail_checkpoint"


@pytest.mark.asyncio
async def test_pending_checkpoint_blocks():
    db = _FakeSession(_video(), _checkpoint(action=None))
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "checkpoint_pending"


@pytest.mark.asyncio
async def test_rejected_checkpoint_blocks():
    db = _FakeSession(_video(), _checkpoint(action=ApprovalAction.REJECT))
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "checkpoint_reject"


@pytest.mark.asyncio
async def test_revoked_latest_decision_blocks_despite_approve_cache():
    """REVOKE withdraws authorization: cache APPROVE + latest REVOKE denies."""
    db = _FakeSession(_video(), _checkpoint(), _decision(ApprovalAction.REVOKE))
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "latest_decision_not_approve"


@pytest.mark.asyncio
async def test_missing_decision_history_blocks():
    """Cache says APPROVE but authoritative history is absent: fail closed."""
    db = _FakeSession(_video(), _checkpoint(), None)
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "latest_decision_not_approve"


@pytest.mark.asyncio
async def test_approved_authorizes():
    """Cache APPROVE + latest APPROVE + no TTL policy row (perpetual)."""
    db = _FakeSession(_video(), _checkpoint(), _decision(), None)
    await assert_publish_authorized(db, RUN, VIDEO)  # no exception


@pytest.mark.asyncio
async def test_approved_with_digest_null_passes_model_a_rows():
    """Documents the binding gap: parameter_digest is not enforced (it
    covers Hermes capability parameters, not publish content)."""
    db = _FakeSession(_video(), _checkpoint(digest=None), _decision(), None)
    await assert_publish_authorized(db, RUN, VIDEO)


@pytest.mark.asyncio
async def test_expired_ttl_blocks():
    checkpoint = _checkpoint()
    checkpoint.decided_at = (datetime.now(UTC) - timedelta(hours=2)).replace(
        tzinfo=None
    )
    policy = SimpleNamespace(stage=None, ttl_seconds=3600)
    db = _FakeSession(_video(), checkpoint, _decision(), policy)
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "approval_expired"


@pytest.mark.asyncio
async def test_fresh_ttl_passes():
    checkpoint = _checkpoint()  # decided now
    policy = SimpleNamespace(stage=None, ttl_seconds=3600)
    db = _FakeSession(_video(), checkpoint, _decision(), policy)
    await assert_publish_authorized(db, RUN, VIDEO)


@pytest.mark.asyncio
async def test_wrong_run_blocks():
    """An approval on another run never authorizes this video."""
    db = _FakeSession(_video(run_id=OTHER_RUN))
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "video_not_in_workflow_run"


@pytest.mark.asyncio
async def test_unknown_video_blocks():
    db = _FakeSession(None)
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, RUN, VIDEO)
    assert ei.value.reason_code == "unknown_video"


@pytest.mark.asyncio
async def test_malformed_identifiers_fail_closed():
    db = _FakeSession()
    with pytest.raises(PublishApprovalDenied) as ei:
        await assert_publish_authorized(db, "not-a-uuid", VIDEO)
    assert ei.value.reason_code == "invalid_identifier"
    assert db.calls == 0  # rejected before any query


# ---------------------------------------------------------------------------
# Agent boundary tests (direct invocation cannot bypass the gate)
# ---------------------------------------------------------------------------


def _base_context(**over):
    ctx = {
        "platform": "youtube",
        "video_id": str(VIDEO),
        "video_storage_path": "/app/data/storage/x.mp4",
        "workflow_run_id": str(RUN),
    }
    ctx.update(over)
    return ctx


class _Stop(Exception):
    pass


@pytest.mark.asyncio
async def test_denied_agent_never_dispatches(monkeypatch):
    factory = MagicMock(side_effect=_Stop)
    monkeypatch.setattr("app.agents.publishing.get_platform_adapter", factory)

    async def _deny(db, run_id, video_id):
        raise PublishApprovalDenied("checkpoint_pending")

    monkeypatch.setattr("app.services.publish_gate.assert_publish_authorized", _deny)
    agent = PublishingAgent(db=MagicMock())
    result = await agent.run(_base_context())
    assert result.success is False
    assert "publish_approval_denied: checkpoint_pending" in result.error
    assert factory.call_count == 0  # never dispatched


@pytest.mark.asyncio
async def test_agent_missing_workflow_run_id_fails_closed(monkeypatch):
    factory = MagicMock(side_effect=_Stop)
    monkeypatch.setattr("app.agents.publishing.get_platform_adapter", factory)
    gate = AsyncMock()
    monkeypatch.setattr("app.services.publish_gate.assert_publish_authorized", gate)
    agent = PublishingAgent(db=MagicMock())
    result = await agent.run(_base_context(workflow_run_id=None))
    assert result.success is False
    assert "missing_workflow_run_id" in result.error
    assert factory.call_count == 0
    assert gate.call_count == 0


@pytest.mark.asyncio
async def test_authorized_agent_proceeds_to_dispatch(monkeypatch):
    """Gate pass reaches the dispatch path (adapter factory called), then
    stops at a controlled duplicate-PENDING early exit (no external call)."""
    factory = MagicMock(return_value=SimpleNamespace(publish=AsyncMock()))
    monkeypatch.setattr("app.agents.publishing.get_platform_adapter", factory)

    async def _allow(db, run_id, video_id):
        return None

    monkeypatch.setattr("app.services.publish_gate.assert_publish_authorized", _allow)

    attempt = SimpleNamespace(
        status=PublicationAttemptStatus.PENDING,
        attempt_number=1,
        external_post_id=None,
        public_url=None,
        id=uuid.uuid4(),
    )

    async def _admit(*_a, **_k):
        return attempt, False  # duplicate PENDING -> clean early exit

    monkeypatch.setattr("app.services.publication_attempts.admit_attempt", _admit)
    agent = PublishingAgent(db=MagicMock())
    result = await agent.run(_base_context())
    assert factory.call_count == 1  # gate passed; dispatch path entered
    assert result.success is False  # duplicate-pending early exit
    assert "pending" in result.error


@pytest.mark.asyncio
async def test_dry_run_bypasses_gate_without_external_calls(monkeypatch):
    called = {"gate": 0, "factory": 0}

    async def _must_not_run(db, run_id, video_id):
        called["gate"] += 1
        raise AssertionError("gate must not run for dry-run")

    monkeypatch.setattr(
        "app.services.publish_gate.assert_publish_authorized", _must_not_run
    )

    def _factory(*_a, **_k):
        called["factory"] += 1
        raise _Stop  # stop right after entering the dispatch/validation path

    monkeypatch.setattr("app.agents.publishing.get_platform_adapter", _factory)
    agent = PublishingAgent(db=MagicMock())
    with pytest.raises(_Stop):
        await agent.run(_base_context(dry_run=True, workflow_run_id=None))
    assert called["gate"] == 0
    assert called["factory"] == 1


# ---------------------------------------------------------------------------
# Route edge tests (fail closed before agent construction; auth preserved)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(synthetic_api_key):
    def _fake_db():
        # The edge checks must reject BEFORE any meaningful DB use; if a
        # request gets this far with rejected inputs, using the session
        # explodes loudly.
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=AssertionError("route must reject before touching the DB")
        )
        return session

    app.dependency_overrides[
        __import__("app.api.routers.publishing", fromlist=["get_db"]).get_db
    ] = _fake_db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_route_requires_identifiers_for_real_publish(client, monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("agent must not be constructed for a rejected request")

    monkeypatch.setattr("app.api.routers.publishing.PublishingAgent", _boom)
    resp = client.post(
        "/publishing/publish",
        json={
            "asset_storage_path": "storage/x.mp4",
            "platform": "youtube",
            "publish_type": "now",
        },
        headers={"Authorization": "Bearer synthetic-test-bearer-key"},
    )
    assert resp.status_code == 422
    assert "workflow_run_id and video_id are required" in resp.text


def test_route_dry_run_may_omit_identifiers(client, monkeypatch):
    """Dry-run passes the edge check (validation-only; synthetic identity)."""

    def _boom(*_a, **_k):
        raise AssertionError("agent must not be constructed in this test")

    monkeypatch.setattr("app.api.routers.publishing.PublishingAgent", _boom)
    resp = client.post(
        "/publishing/publish",
        json={
            "asset_storage_path": "storage/x.mp4",
            "platform": "youtube",
            "dry_run": True,
        },
        headers={"Authorization": "Bearer synthetic-test-bearer-key"},
    )
    assert resp.status_code == 500  # reached the stubbed agent -> passed edge
    assert resp.status_code != 422


def test_route_authentication_preserved(client):
    resp = client.post(
        "/publishing/publish",
        json={"asset_storage_path": "storage/x.mp4", "dry_run": True},
    )
    assert resp.status_code == 401
