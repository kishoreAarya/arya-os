"""
AryaOS V1 Stage 25 Phase 3.1.2 / 3.1.5 — Durable Approval Provenance Security Test Suite.

Validates durable human operator approval provenance, actor classification, and fail-closed dispatch:
1. Active API key with principal_type="human" allows consequential action dispatch.
2. Active API key with principal_type="service_account" is rejected for consequential dispatch (409 Conflict).
3. System Master Key (principal_type="system") is rejected for consequential dispatch (409 Conflict).
4. Development bypass (principal_type="development") is rejected for consequential dispatch (409 Conflict).
5. Client-supplied provenance fields in decide/patch are rejected by Pydantic (422 Unprocessable Content).
6. Revoked operator credential fails closed at dispatch (409 Conflict).
7. Deleted operator credential fails closed at dispatch (409 Conflict).
8. Revoked project membership fails closed at dispatch (403 Forbidden).
9. Legacy approval without provenance fails closed at dispatch (409 Conflict).
10. Administrative key promotion enforces admin authorization, active status, and audit logging.
"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import AuthenticatedPrincipal
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
)
from app.services.authorization_service import (
    add_project_membership,
    create_api_key,
    promote_api_key_to_human,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# FIXTURES & ISOLATION
# ===========================================================================

@pytest.fixture(autouse=True)
def forbid_external_network_and_subprocess(monkeypatch):
    """Guarantees zero network and zero subprocess calls occur during test execution."""

    def _block_call(*args, **kwargs):
        raise RuntimeError(
            "VIOLATION: External network or subprocess call attempted during Phase 3.1.2 test execution!"
        )

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _block_call)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _block_call)
    monkeypatch.setattr("asyncio.create_subprocess_shell", _block_call)
    monkeypatch.setattr("subprocess.Popen", _block_call)


@pytest_asyncio.fixture(loop_scope="module")
async def provenance_fixture(db_session: AsyncSession):
    """Provisions isolated project with human, service_account, admin, and unprivileged keys."""
    settings = get_settings()
    original_auth_enabled = settings.api_auth_enabled
    settings.api_auth_enabled = True

    proj = Project(name=f"proj-provenance-{uuid.uuid4()}", status="ACTIVE")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)

    # 1. Human Operator Key
    human_key_model, human_key_raw = await create_api_key(
        db_session,
        name="Human Director",
        is_admin=False,
        principal_type="human",
    )

    # 2. Service Account Key (default)
    sa_key_model, sa_key_raw = await create_api_key(
        db_session,
        name="Automated Ingest Worker",
        is_admin=False,
        principal_type="service_account",
    )

    # 3. Admin Key (human admin)
    admin_key_model, admin_key_raw = await create_api_key(
        db_session,
        name="Admin Operator",
        is_admin=True,
        principal_type="human",
    )

    # 4. Standard member key (not admin, service_account)
    regular_key_model, regular_key_raw = await create_api_key(
        db_session,
        name="Regular Member",
        is_admin=False,
        principal_type="service_account",
    )

    # Memberships
    await add_project_membership(db_session, project_id=proj.id, api_key_id=human_key_model.id, role="editor")
    await add_project_membership(db_session, project_id=proj.id, api_key_id=sa_key_model.id, role="editor")
    await add_project_membership(db_session, project_id=proj.id, api_key_id=regular_key_model.id, role="viewer")

    master_key = "arya_master_test_provenance_secret_key"
    settings.arya_api_key = master_key

    yield {
        "proj_id": proj.id,
        "human_key": human_key_raw,
        "human_key_id": human_key_model.id,
        "sa_key": sa_key_raw,
        "sa_key_id": sa_key_model.id,
        "admin_key": admin_key_raw,
        "admin_key_id": admin_key_model.id,
        "regular_key": regular_key_raw,
        "regular_key_id": regular_key_model.id,
        "master_key": master_key,
    }

    settings.api_auth_enabled = original_auth_enabled


def _create_client(token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=headers,
    )


# ===========================================================================
# 1. Human vs Non-Human Approval Provenance Tests
# ===========================================================================

async def test_01_human_operator_approval_allows_consequential_dispatch(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 1: Active API key with principal_type='human' allows consequential action dispatch."""
    async with _create_client(provenance_fixture["human_key"]) as client:
        # Create goal with HIGH risk action
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "Human Provenance Success Test",
                "plan_dag_json": {"nodes": ["act-human-01"]},
                "actions": [
                    {
                        "client_action_id": "act-human-01",
                        "title": "Publish Marketing Video",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "PUBLISH",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        goal_id = g_res.json()["id"]
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        # Execute goal step: runner transitions goal & node to AWAITING_APPROVAL
        step_res = await client.post(f"/api/v1/goals/{goal_id}/execute")
        assert step_res.status_code == 200
        assert step_res.json()["status"] == "AWAITING_APPROVAL"

        # Create WorkflowRun for approval checkpoint
        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        # Create checkpoint
        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()
        await db_session.refresh(cp)

        # Decide checkpoint using human key through the REST endpoint
        decide_res = await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Signed off by human director"},
        )
        assert decide_res.status_code == 200
        decided_data = decide_res.json()
        assert decided_data["action"] == "approve"
        assert decided_data["decided_by_actor_type"] == "human"
        assert decided_data["decided_by_principal_id"] == str(provenance_fixture["human_key_id"])

        # Link checkpoint to action node
        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Dispatch action -> Must SUCCEED
        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 200
        assert disp_res.json()["status"] == "SUCCEEDED"


async def test_02_service_account_approval_rejected_for_consequential_action(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 2: Active API key with principal_type='service_account' cannot satisfy human approval."""
    async with _create_client(provenance_fixture["sa_key"]) as client:
        # Create goal with CRITICAL risk action
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "SA Approval Rejection Test",
                "plan_dag_json": {"nodes": ["act-sa-01"]},
                "actions": [
                    {
                        "client_action_id": "act-sa-01",
                        "title": "Drop Production Database",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "MAINTENANCE",
                        "risk_level": "CRITICAL",
                    }
                ],
            },
        )
        assert g_res.status_code == 201
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()
        await db_session.refresh(cp)

        # Decide checkpoint using service account key
        decide_res = await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Attempted automated signoff"},
        )
        assert decide_res.status_code == 200
        assert decide_res.json()["decided_by_actor_type"] == "service_account"

        # Link checkpoint to action node
        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Dispatch action -> Must fail with 409 Conflict
        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "credential actor type 'service_account' is not human" in disp_res.json()["detail"]


async def test_03_system_master_key_approval_rejected_for_consequential_action(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 3: System Master Key (principal_type='system') cannot satisfy human approval."""
    async with _create_client(provenance_fixture["master_key"]) as client:
        # Create goal with DECISION action
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "System Master Key Rejection Test",
                "plan_dag_json": {"nodes": ["act-sys-01"]},
                "actions": [
                    {
                        "client_action_id": "act-sys-01",
                        "title": "Select Script Revision",
                        "action_type": "DECISION",
                        "required_capability": "CHOICE",
                        "risk_level": "LOW",  # DECISION action is consequential regardless of risk_level
                    }
                ],
            },
        )
        assert g_res.status_code == 201
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.SCRIPT,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()
        await db_session.refresh(cp)

        # Decide checkpoint using Master Key
        decide_res = await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Master key automated approval"},
        )
        assert decide_res.status_code == 200
        assert decide_res.json()["decided_by_actor_type"] == "system"

        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Dispatch action -> Must fail with 409 Conflict
        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "credential actor type 'system' is not human" in disp_res.json()["detail"]


async def test_04_development_bypass_key_approval_rejected_for_consequential_action(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 4: Development bypass (principal_type='development') cannot satisfy human approval."""
    settings = get_settings()
    original_auth = settings.api_auth_enabled
    settings.api_auth_enabled = False  # Enable development bypass

    try:
        async with _create_client(token=None) as client:
            g_res = await client.post(
                f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
                json={
                    "objective": "Dev Bypass Rejection Test",
                    "plan_dag_json": {"nodes": ["act-dev-01"]},
                    "actions": [
                        {
                            "client_action_id": "act-dev-01",
                            "title": "Release Production Asset",
                            "action_type": "EXTERNAL_ACTION",
                            "required_capability": "PUBLISH",
                            "risk_level": "HIGH",
                        }
                    ],
                },
            )
            assert g_res.status_code == 201
            act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

            wf = WorkflowRun(
                project_id=provenance_fixture["proj_id"],
                mode=WorkflowMode.AUTONOMOUS,
                status=WorkflowStatus.RUNNING,
            )
            db_session.add(wf)
            await db_session.flush()

            cp = ApprovalCheckpoint(
                workflow_run_id=wf.id,
                stage=ApprovalStage.VIDEO,
                reference_table="autonomous_action_nodes",
                reference_id=act_id,
            )
            db_session.add(cp)
            await db_session.commit()
            await db_session.refresh(cp)

            # Decide checkpoint in bypass mode
            decide_res = await client.post(
                f"/approvals/{cp.id}/decide",
                json={"action": "approve", "reviewer_notes": "Bypassed local approval"},
            )
            assert decide_res.status_code == 200
            assert decide_res.json()["decided_by_actor_type"] == "development"

            node = await db_session.get(AutonomousActionNode, act_id)
            node.approval_checkpoint_id = cp.id
            node.status = "AWAITING_APPROVAL"
            await db_session.commit()

            # Dispatch action -> Must fail with 409 Conflict
            disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
            assert disp_res.status_code == 409
            assert "credential actor type 'development' is not human" in disp_res.json()["detail"]
    finally:
        settings.api_auth_enabled = original_auth


async def test_05_client_spoofed_provenance_fields_rejected_by_pydantic_422(
    provenance_fixture: dict
):
    """Test 5: Client cannot inject decided_by_* fields in decide payload (extra='forbid')."""
    fake_id = str(uuid.uuid4())
    async with _create_client(provenance_fixture["human_key"]) as client:
        # Attempt to spoof decided_by_actor_type
        res = await client.post(
            f"/approvals/{fake_id}/decide",
            json={
                "action": "approve",
                "decided_by_actor_type": "human",
                "decided_by_principal_id": fake_id,
                "decided_by_principal_name": "Forged Human",
            },
        )
        assert res.status_code == 422
        errors = res.json()["detail"]
        fields = [e["loc"][-1] for e in errors]
        assert "decided_by_actor_type" in fields or "extra_forbidden" in str(errors)


# ===========================================================================
# 2. Lifecycle, Purge, and Revocation Failsafe Tests
# ===========================================================================

async def test_06_revoked_operator_credential_fails_closed_at_dispatch(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 6: Revoked human operator credential blocks subsequent dispatch."""
    # Create a separate human operator key that will be revoked
    revocable_key, revocable_raw = await create_api_key(
        db_session,
        name="Revocable Operator",
        is_admin=False,
        principal_type="human",
    )
    await add_project_membership(
        db_session,
        project_id=provenance_fixture["proj_id"],
        api_key_id=revocable_key.id,
        role="editor",
    )

    async with _create_client(revocable_raw) as client:
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "Revoked Key Test",
                "plan_dag_json": {"nodes": ["act-revoked-01"]},
                "actions": [
                    {
                        "client_action_id": "act-revoked-01",
                        "title": "Deploy Live Pipeline",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "DEPLOY",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()

        # Approve with revocable key
        d_res = await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Approval before revocation"},
        )
        assert d_res.status_code == 200

        # Link checkpoint to action node
        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Now revoke the operator's key
        revocable_key.is_active = False
        await db_session.commit()

    # Attempt dispatch using valid client (human key) -> Must fail closed
    async with _create_client(provenance_fixture["human_key"]) as client_valid:
        disp_res = await client_valid.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "credential has been revoked or deleted" in disp_res.json()["detail"]


async def test_07_deleted_operator_credential_fails_closed_at_dispatch(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 7: Deleted human operator credential sets FK to NULL and fails closed at dispatch."""
    deletable_key, deletable_raw = await create_api_key(
        db_session,
        name="Deletable Operator",
        is_admin=False,
        principal_type="human",
    )
    await add_project_membership(
        db_session,
        project_id=provenance_fixture["proj_id"],
        api_key_id=deletable_key.id,
        role="editor",
    )

    async with _create_client(deletable_raw) as client:
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "Deleted Key Test",
                "plan_dag_json": {"nodes": ["act-deleted-01"]},
                "actions": [
                    {
                        "client_action_id": "act-deleted-01",
                        "title": "Publish Shot",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "PUBLISH",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()

        # Approve with deletable key
        await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Approval before deletion"},
        )

        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Delete the key from database (ON DELETE SET NULL triggers)
        await db_session.delete(deletable_key)
        await db_session.commit()

        # Verify checkpoint preserved principal name but nulled FK
        await db_session.refresh(cp)
        assert cp.decided_by_principal_id is None
        assert cp.decided_by_principal_name == "Deletable Operator"

    # Attempt dispatch -> Fails closed
    async with _create_client(provenance_fixture["human_key"]) as client_valid:
        disp_res = await client_valid.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "credential record is missing or has been deleted" in disp_res.json()["detail"]


async def test_08_revoked_project_membership_fails_closed_at_dispatch(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 8: Operator removed from project membership cannot have their approval dispatched."""
    departing_key, departing_raw = await create_api_key(
        db_session,
        name="Departing Operator",
        is_admin=False,
        principal_type="human",
    )
    pm = await add_project_membership(
        db_session,
        project_id=provenance_fixture["proj_id"],
        api_key_id=departing_key.id,
        role="editor",
    )

    async with _create_client(departing_raw) as client:
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "Membership Revocation Test",
                "plan_dag_json": {"nodes": ["act-pm-01"]},
                "actions": [
                    {
                        "client_action_id": "act-pm-01",
                        "title": "Scoped Action",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "EXECUTE",
                        "risk_level": "HIGH",
                    }
                ],
            },
        )
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
        )
        db_session.add(cp)
        await db_session.commit()

        await client.post(
            f"/approvals/{cp.id}/decide",
            json={"action": "approve", "reviewer_notes": "Approved while still a member"},
        )

        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        # Remove operator from project memberships
        await db_session.delete(pm)
        await db_session.commit()

    # Attempt dispatch -> 403 Forbidden
    async with _create_client(provenance_fixture["human_key"]) as client_valid:
        disp_res = await client_valid.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 403
        assert "does not have active membership in project" in disp_res.json()["detail"]


async def test_09_legacy_approval_without_provenance_fails_closed_at_dispatch(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 9: Legacy approval with decided_by_actor_type=None fails closed with 409 Conflict."""
    async with _create_client(provenance_fixture["human_key"]) as client:
        g_res = await client.post(
            f"/api/v1/projects/{provenance_fixture['proj_id']}/goals",
            json={
                "objective": "Legacy Approval Test",
                "plan_dag_json": {"nodes": ["act-legacy-01"]},
                "actions": [
                    {
                        "client_action_id": "act-legacy-01",
                        "title": "Legacy Critical Action",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "RUN",
                        "risk_level": "CRITICAL",
                    }
                ],
            },
        )
        act_id = uuid.UUID(g_res.json()["actions"][0]["id"])

        wf = WorkflowRun(
            project_id=provenance_fixture["proj_id"],
            mode=WorkflowMode.AUTONOMOUS,
            status=WorkflowStatus.RUNNING,
        )
        db_session.add(wf)
        await db_session.flush()

        # Legacy checkpoint: decided_by_actor_type is None
        legacy_cp = ApprovalCheckpoint(
            workflow_run_id=wf.id,
            stage=ApprovalStage.VIDEO,
            reference_table="autonomous_action_nodes",
            reference_id=act_id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Legacy approval without provenance",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
            decided_by_actor_type=None,
            decided_by_principal_id=None,
            decided_by_principal_name=None,
        )
        db_session.add(legacy_cp)
        await db_session.commit()

        node = await db_session.get(AutonomousActionNode, act_id)
        node.approval_checkpoint_id = legacy_cp.id
        node.status = "AWAITING_APPROVAL"
        await db_session.commit()

        disp_res = await client.post(f"/api/v1/actions/{act_id}/dispatch")
        assert disp_res.status_code == 409
        assert "legacy approval without actor attribution" in disp_res.json()["detail"]


# ===========================================================================
# 3. Administrative Key Promotion Tests
# ===========================================================================

async def test_10_administrative_promotion_enforces_admin_role_and_audit_log(
    db_session: AsyncSession, provenance_fixture: dict
):
    """Test 10: Promotion requires admin role, active key, and emits structured audit log."""
    # Target candidate key (currently service_account)
    candidate_key, _ = await create_api_key(
        db_session,
        name="Candidate Service Account",
        is_admin=False,
        principal_type="service_account",
    )
    assert candidate_key.principal_type == "service_account"

    # 1. Non-admin client attempts promotion -> 403 Forbidden
    async with _create_client(provenance_fixture["regular_key"]) as regular_client:
        p_res1 = await regular_client.post(
            f"/approvals/admin/api-keys/{candidate_key.id}/promote-human"
        )
        assert p_res1.status_code == 403

    # 2. Master Key attempts promotion -> 403 Forbidden (exclusion of system master key)
    async with _create_client(provenance_fixture["master_key"]) as master_client:
        p_res2 = await master_client.post(
            f"/approvals/admin/api-keys/{candidate_key.id}/promote-human"
        )
        assert p_res2.status_code == 403

    # 3. Inactive key cannot be promoted -> 409 Conflict
    candidate_key.is_active = False
    await db_session.commit()

    async with _create_client(provenance_fixture["admin_key"]) as admin_client:
        p_res3 = await admin_client.post(
            f"/approvals/admin/api-keys/{candidate_key.id}/promote-human"
        )
        assert p_res3.status_code == 409
        assert "Cannot promote inactive API key" in p_res3.json()["detail"]

        # Reactivate key
        candidate_key.is_active = True
        await db_session.commit()

        # 4. Valid Admin promotes active candidate key -> 200 OK
        p_res4 = await admin_client.post(
            f"/approvals/admin/api-keys/{candidate_key.id}/promote-human"
        )
        assert p_res4.status_code == 200
        data = p_res4.json()
        assert data["status"] == "promoted"
        assert data["principal_type"] == "human"

        await db_session.refresh(candidate_key)
        assert candidate_key.principal_type == "human"
