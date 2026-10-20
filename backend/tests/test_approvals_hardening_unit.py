"""Focused unit and regression tests for approval checkpoint immutability.

Validates remediation of approval-checkpoint-state-overwrite:
- Initial decision on a pending checkpoint succeeds with HTTP 200 and persists decision.
- Subsequent decision on an already decided checkpoint is rejected with HTTP 409 Conflict.
- Checkpoint decision action and reviewer notes remain unaltered after rejected attempt.
- Overwrite prevention applies across all decision action types (approve, reject, retry, etc.).
- Nonexistent checkpoint returns HTTP 404 Not Found.
- Unauthenticated requests are rejected with HTTP 401 Unauthorized.
- Pending checkpoint queries properly reflect the decided lifecycle state.
"""
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus

TEST_SECRET = "test-approval-secret-key"


@pytest.fixture(autouse=True)
def setup_api_auth(monkeypatch):
    """Ensure ARYA_API_KEY is configured for authentication checks across all tests."""
    monkeypatch.setenv("ARYA_API_KEY", TEST_SECRET)
    with patch("app.core.secrets.SecretsManager.get", return_value=TEST_SECRET):
        yield


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def test_run_context(db_session: AsyncSession) -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID], None]:
    """Provisions a test Project and WorkflowRun row to satisfy foreign keys."""
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()

    project = Project(id=project_id, name=f"test-approval-proj-{uuid.uuid4().hex[:8]}")
    db_session.add(project)
    await db_session.commit()

    run = WorkflowRun(
        id=run_id,
        project_id=project_id,
        topic="Test Approval Workflow Run",
        mode=WorkflowMode.MANUAL,
        status=WorkflowStatus.RUNNING,
        current_stage="script",
    )
    db_session.add(run)
    await db_session.commit()

    yield project_id, run_id

    await db_session.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id == run_id))
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
    await db_session.execute(delete(Project).where(Project.id == project_id))
    await db_session.commit()


@pytest_asyncio.fixture
async def auth_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TEST_SECRET}"}
    async with AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        yield client


@pytest.mark.asyncio
async def test_first_decision_records_and_commits_successfully(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    test_run_context: tuple[uuid.UUID, uuid.UUID],
):
    """Verify that deciding a pending checkpoint succeeds with HTTP 200 and persists to DB."""
    _, run_id = test_run_context
    cp_id = uuid.uuid4()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
        action=None,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    resp = await auth_client.post(
        f"/approvals/{cp_id}/decide",
        json={"action": "reject", "reviewer_notes": "Rejected due to tone mismatch"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "reject"
    assert data["reviewer_notes"] == "Rejected due to tone mismatch"
    assert data["decided_at"] is not None

    # Refresh identity map from DB
    await db_session.refresh(checkpoint)
    assert checkpoint.action == ApprovalAction.REJECT
    assert checkpoint.reviewer_notes == "Rejected due to tone mismatch"
    assert checkpoint.decided_at is not None


@pytest.mark.asyncio
async def test_subsequent_decision_rejected_with_409_conflict(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    test_run_context: tuple[uuid.UUID, uuid.UUID],
):
    """Attack case: attempting to overwrite an already decided checkpoint is rejected with HTTP 409."""
    _, run_id = test_run_context
    cp_id = uuid.uuid4()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
        action=None,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    # Step 1: Initial decision (reject)
    resp1 = await auth_client.post(
        f"/approvals/{cp_id}/decide",
        json={"action": "reject", "reviewer_notes": "Original rejection"},
    )
    assert resp1.status_code == 200

    # Step 2: Exploit attempt (override to approve)
    resp2 = await auth_client.post(
        f"/approvals/{cp_id}/decide",
        json={"action": "approve", "reviewer_notes": "Malicious override attempt"},
    )
    assert resp2.status_code == 409
    assert "Checkpoint has already been decided: reject" in resp2.json()["detail"]

    # Verify in DB that original rejection decision remained completely intact
    await db_session.refresh(checkpoint)
    assert checkpoint.action == ApprovalAction.REJECT
    assert checkpoint.reviewer_notes == "Original rejection"


@pytest.mark.asyncio
async def test_cannot_override_any_finalized_action(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    test_run_context: tuple[uuid.UUID, uuid.UUID],
):
    """Boundary case: verify that all ApprovalAction variants are immutable once decided."""
    _, run_id = test_run_context

    for finalized_action in [
        ApprovalAction.APPROVE,
        ApprovalAction.RETRY,
        ApprovalAction.MANUAL_EDIT,
        ApprovalAction.CONTINUE,
    ]:
        cp_id = uuid.uuid4()
        checkpoint = ApprovalCheckpoint(
            id=cp_id,
            workflow_run_id=run_id,
            stage=ApprovalStage.IMAGE,
            reference_table="images",
            reference_id=uuid.uuid4(),
            action=finalized_action,
        )
        db_session.add(checkpoint)
        await db_session.commit()

        # Attempt to overwrite with reject
        resp = await auth_client.post(
            f"/approvals/{cp_id}/decide",
            json={"action": "reject", "reviewer_notes": "Attempting override"},
        )
        assert resp.status_code == 409
        assert f"Checkpoint has already been decided: {finalized_action.value}" in resp.json()["detail"]

        # Ensure database row remained untouched
        await db_session.refresh(checkpoint)
        assert checkpoint.action == finalized_action


@pytest.mark.asyncio
async def test_decide_nonexistent_checkpoint_404(auth_client: AsyncClient):
    """Verify requesting decision on a nonexistent checkpoint returns HTTP 404."""
    nonexistent_id = uuid.uuid4()
    resp = await auth_client.post(
        f"/approvals/{nonexistent_id}/decide",
        json={"action": "approve"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Checkpoint not found"


@pytest.mark.asyncio
async def test_decide_requires_authentication():
    """Verify endpoint rejects unauthenticated requests with HTTP 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as unauth_client:
        resp = await unauth_client.post(
            f"/approvals/{uuid.uuid4()}/decide",
            json={"action": "approve"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pending_checkpoints_lifecycle(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    test_run_context: tuple[uuid.UUID, uuid.UUID],
):
    """Verify pending checkpoint query returns active checkpoint and omits decided checkpoint."""
    _, run_id = test_run_context
    cp_id = uuid.uuid4()

    checkpoint = ApprovalCheckpoint(
        id=cp_id,
        workflow_run_id=run_id,
        stage=ApprovalStage.THUMBNAIL,
        reference_table="thumbnails",
        reference_id=uuid.uuid4(),
        action=None,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    # 1. Listed while pending
    resp_pending1 = await auth_client.get(f"/approvals/pending/{run_id}")
    assert resp_pending1.status_code == 200
    ids = [item["id"] for item in resp_pending1.json()]
    assert str(cp_id) in ids

    # 2. Decide checkpoint
    resp_decide = await auth_client.post(
        f"/approvals/{cp_id}/decide",
        json={"action": "approve", "reviewer_notes": "Thumbnail approved"},
    )
    assert resp_decide.status_code == 200

    # 3. No longer listed under pending
    resp_pending2 = await auth_client.get(f"/approvals/pending/{run_id}")
    assert resp_pending2.status_code == 200
    ids_after = [item["id"] for item in resp_pending2.json()]
    assert str(cp_id) not in ids_after
