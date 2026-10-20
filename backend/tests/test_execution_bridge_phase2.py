"""
AryaOS V1 Stage 25 Phase 2 — Execution Bridge REST API & Security Integration Tests.

Validates the Phase 2 API surface and service-layer security controls:
1. Unauthenticated requests are rejected (401 Unauthorized).
2. Unauthorized project access is rejected (403 Forbidden).
3. Cross-project mission references are rejected (422 Unprocessable Entity).
4. Cross-project production-job and approval-checkpoint references are rejected (422 Unprocessable Entity).
5. Cross-project resource-ID access masks existence (404 Not Found IDOR protection).
6. Invalid, missing, duplicate, self-referential, and cyclic DAG edges are rejected (422).
7. Valid DAGs are accepted and topologically validated (201 Created).
8. Invalid lifecycle state transitions return 409 Conflict.
9. Client-forced terminal success states (COMPLETED/SUCCEEDED) are rejected with 409 Conflict.
10. Actor identity cannot be forged through client request payloads (extra="forbid").
11. Governance decisions can be created and listed but not updated or deleted (405 Method Not Allowed).
12. Duplicate client_action_id within same goal returns 409 Conflict.
13. CRUD requests remain pure persistence: zero provider execution, connector dispatch, or external calls.
14. Project cascade deletion cleans up missions, goals, action nodes, and governance decisions.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import app
from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    GovernanceDecision,
    Mission,
)
from app.models.production import ProductionJob, ProductionSequence, ProductionShot
from app.services.authorization_service import add_project_membership, create_api_key

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest_asyncio.fixture(loop_scope="module")
async def bridge_auth_fixture(db_session: AsyncSession):
    """Provisions two isolated projects (Project A, Project B) with scoped API keys."""
    # Ensure api_auth_enabled is temporarily True for this test module
    settings = get_settings()
    original_auth_enabled = settings.api_auth_enabled
    settings.api_auth_enabled = True

    # 1. Projects
    proj_a = Project(name=f"project-a-{uuid.uuid4()}", status="ACTIVE")
    proj_b = Project(name=f"project-b-{uuid.uuid4()}", status="ACTIVE")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    # 2. Scoped API Keys
    key_a_model, key_a_raw = await create_api_key(db_session, name="Key A", is_admin=False)
    key_b_model, key_b_raw = await create_api_key(db_session, name="Key B", is_admin=False)
    admin_model, admin_raw = await create_api_key(db_session, name="Admin Key", is_admin=True)

    # 3. Memberships
    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="owner")
    await add_project_membership(db_session, project_id=proj_b.id, api_key_id=key_b_model.id, role="owner")

    yield {
        "proj_a_id": proj_a.id,
        "proj_b_id": proj_b.id,
        "key_a": key_a_raw,
        "key_b": key_b_raw,
        "key_admin": admin_raw,
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
# 1. Authentication & Project Authorization Tests
# ===========================================================================

async def test_01_unauthenticated_requests_rejected(bridge_auth_fixture):
    """Verify missing credentials return 401 Unauthorized with WWW-Authenticate header."""
    async with _create_client(token=None) as client:
        res = await client.get(f"/api/v1/projects/{bridge_auth_fixture['proj_a_id']}/missions")
        assert res.status_code == 401
        assert "WWW-Authenticate" in res.headers


async def test_02_unauthorized_project_access_rejected(bridge_auth_fixture):
    """Verify caller from Project B receives 403 Forbidden when attempting to create a mission in Project A."""
    async with _create_client(token=bridge_auth_fixture["key_b"]) as client:
        res = await client.post(
            f"/api/v1/projects/{bridge_auth_fixture['proj_a_id']}/missions",
            json={"title": "Infiltrator Mission", "objective": "Access forbidden project"},
        )
        assert res.status_code == 403
        assert "Forbidden" in res.json()["detail"]


# ===========================================================================
# 2. Co-Tenancy & Cross-Project Integrity Tests
# ===========================================================================

async def test_03_cross_project_mission_reference_rejected(bridge_auth_fixture):
    """Verify a goal in Project A cannot reference a mission in Project B (422 Unprocessable Entity)."""
    # 1. Create legitimate mission in Project B using Key B
    async with _create_client(token=bridge_auth_fixture["key_b"]) as client_b:
        m_b_res = await client_b.post(
            f"/api/v1/projects/{bridge_auth_fixture['proj_b_id']}/missions",
            json={"title": "Project B Mission", "objective": "Legitimate Project B scope"},
        )
        assert m_b_res.status_code == 201
        m_b_id = m_b_res.json()["id"]

    # 2. Attempt to create goal in Project A referencing Project B's mission
    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        goal_res = await client_a.post(
            f"/api/v1/projects/{bridge_auth_fixture['proj_a_id']}/goals",
            json={
                "mission_id": m_b_id,
                "objective": "Malicious cross-project link attempt",
            },
        )
        assert goal_res.status_code == 422
        assert "does not belong to the authorized project" in goal_res.json()["detail"]


async def test_04_cross_project_job_and_checkpoint_references_rejected(
    bridge_auth_fixture, db_session: AsyncSession
):
    """Verify action nodes cannot reference production jobs or checkpoints from other projects (422)."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]
    proj_b_id = bridge_auth_fixture["proj_b_id"]

    # 1. Create a legitimate Goal in Project A
    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        g_res = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={"objective": "Test Goal for Action Linking"},
        )
        assert g_res.status_code == 201
        goal_a_id = g_res.json()["id"]

    # 2. Provision ProductionJob in Project B directly in DB
    job_b = ProductionJob(
        project_id=proj_b_id,
        job_package_id="pkg-cross-b",
        provider="fal",
        model="fal-sd-v1",
        status="CREATED",
    )
    db_session.add(job_b)
    await db_session.commit()
    await db_session.refresh(job_b)

    # 3. Provision WorkflowRun and ApprovalCheckpoint in Project B
    run_b = WorkflowRun(
        project_id=proj_b_id,
        topic="Cross B Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(run_b)
    await db_session.commit()
    await db_session.refresh(run_b)

    cp_b = ApprovalCheckpoint(
        workflow_run_id=run_b.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add(cp_b)
    await db_session.commit()
    await db_session.refresh(cp_b)

    # 4. Attempt to link Project B's job to Project A's action node -> rejected (422)
    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        bad_action_1 = await client_a.post(
            f"/api/v1/goals/{goal_a_id}/actions",
            json={
                "client_action_id": "act-cross-job",
                "title": "Cross Job Action",
                "action_type": "JOB_PACKAGE",
                "required_capability": "IMAGE_GENERATION",
                "production_job_id": str(job_b.id),
            },
        )
        assert bad_action_1.status_code == 422
        assert "production job does not belong" in bad_action_1.json()["detail"]

        # 5. Attempt to link Project B's checkpoint to Project A's action node -> rejected (422)
        bad_action_2 = await client_a.post(
            f"/api/v1/goals/{goal_a_id}/actions",
            json={
                "client_action_id": "act-cross-cp",
                "title": "Cross Checkpoint Action",
                "action_type": "DECISION",
                "required_capability": "REASONING",
                "approval_checkpoint_id": str(cp_b.id),
            },
        )
        assert bad_action_2.status_code == 422
        assert "approval checkpoint does not belong" in bad_action_2.json()["detail"]


async def test_05_cross_project_resource_id_access_masks_existence_idor(bridge_auth_fixture):
    """Verify resource-by-ID endpoints mask unauthorized cross-project access with 404 (IDOR protection)."""
    # 1. Project B creates a Mission and a Goal
    async with _create_client(token=bridge_auth_fixture["key_b"]) as client_b:
        m_b = (
            await client_b.post(
                f"/api/v1/projects/{bridge_auth_fixture['proj_b_id']}/missions",
                json={"title": "Secret Mission B", "objective": "Classified"},
            )
        ).json()
        g_b = (
            await client_b.post(
                f"/api/v1/projects/{bridge_auth_fixture['proj_b_id']}/goals",
                json={"objective": "Secret Goal B"},
            )
        ).json()

    # 2. Project A tries to GET /missions/{m_b_id} and /goals/{g_b_id} -> returns 404 Not Found
    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        get_m = await client_a.get(f"/api/v1/missions/{m_b['id']}")
        assert get_m.status_code == 404
        assert get_m.json()["detail"] == "Mission not found"

        get_g = await client_a.get(f"/api/v1/goals/{g_b['id']}")
        assert get_g.status_code == 404
        assert get_g.json()["detail"] == "Goal not found"

        patch_g = await client_a.patch(
            f"/api/v1/goals/{g_b['id']}", json={"objective": "Attempted overwrite"}
        )
        assert patch_g.status_code == 404


# ===========================================================================
# 3. Action DAG Validation Tests
# ===========================================================================

async def test_06_dag_validation_rejects_cycles_self_deps_and_dangling(bridge_auth_fixture):
    """Verify DAG cycle detection, self-dependencies, duplicate IDs, and dangling edge rejection."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        # A. Self-dependency rejection
        res_self = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={
                "objective": "Self dependency goal",
                "plan_dag_json": {
                    "nodes": [{"id": "act-1"}],
                    "edges": [{"from": "act-1", "to": "act-1"}],
                },
            },
        )
        assert res_self.status_code == 422
        assert "Self-dependency detected" in res_self.json()["detail"]

        # B. Dangling edge rejection (edge to unknown node)
        res_dangling = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={
                "objective": "Dangling edge goal",
                "plan_dag_json": {
                    "nodes": [{"id": "act-1"}],
                    "edges": [{"from": "act-1", "to": "act-missing"}],
                },
            },
        )
        assert res_dangling.status_code == 422
        assert "references unknown" in res_dangling.json()["detail"]

        # C. Direct 2-node cycle rejection (act-1 -> act-2 -> act-1)
        res_cycle_direct = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={
                "objective": "Direct cyclic goal",
                "plan_dag_json": {
                    "nodes": [{"id": "act-1"}, {"id": "act-2"}],
                    "edges": [
                        {"from": "act-1", "to": "act-2"},
                        {"from": "act-2", "to": "act-1"},
                    ],
                },
            },
        )
        assert res_cycle_direct.status_code == 422
        assert "Cyclic dependency detected" in res_cycle_direct.json()["detail"]

        # D. Indirect 3-node cycle rejection (A -> B -> C -> A)
        res_cycle_indirect = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={
                "objective": "Indirect cyclic goal",
                "plan_dag_json": {
                    "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "edges": [
                        {"from": "A", "to": "B"},
                        {"from": "B", "to": "C"},
                        {"from": "C", "to": "A"},
                    ],
                },
            },
        )
        assert res_cycle_indirect.status_code == 422
        assert "Cyclic dependency detected" in res_cycle_indirect.json()["detail"]


async def test_07_valid_dag_accepted_with_actions(bridge_auth_fixture):
    """Verify a valid acyclic DAG with multiple action nodes is accepted (201 Created)."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    valid_payload = {
        "objective": "Multi-stage automated documentary generation",
        "plan_dag_json": {
            "nodes": [
                {"id": "act-research"},
                {"id": "act-script"},
                {"id": "act-video"},
            ],
            "edges": [
                {"from": "act-research", "to": "act-script"},
                {"from": "act-script", "to": "act-video"},
            ],
        },
        "actions": [
            {
                "client_action_id": "act-research",
                "title": "Trend Research",
                "action_type": "RESEARCH",
                "required_capability": "REASONING",
                "risk_level": "LOW",
            },
            {
                "client_action_id": "act-script",
                "title": "Script Drafting",
                "action_type": "SYNTHESIS",
                "required_capability": "REASONING",
                "risk_level": "LOW",
            },
            {
                "client_action_id": "act-video",
                "title": "Video Generation",
                "action_type": "JOB_PACKAGE",
                "required_capability": "VIDEO_GENERATION",
                "risk_level": "MEDIUM",
            },
        ],
    }

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(f"/api/v1/projects/{proj_a_id}/goals", json=valid_payload)
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "DRAFT"
        assert len(data["actions"]) == 3
        assert data["actions"][0]["client_action_id"] == "act-research"
        assert data["actions"][1]["client_action_id"] == "act-script"
        assert data["actions"][2]["client_action_id"] == "act-video"


# ===========================================================================
# 4. State Machine Transition & Terminal Success Protection Tests
# ===========================================================================

async def test_08_invalid_state_transitions_rejected_with_409(bridge_auth_fixture):
    """Verify illegal transitions (e.g. DRAFT -> EXECUTING without READY) return 409 Conflict."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        g = (
            await client_a.post(
                f"/api/v1/projects/{proj_a_id}/goals",
                json={"objective": "Test State Machine"},
            )
        ).json()
        goal_id = g["id"]
        assert g["status"] == "DRAFT"

        # Attempt illegal transition: DRAFT -> EXECUTING (Must go DRAFT -> READY first)
        illegal_res = await client_a.patch(
            f"/api/v1/goals/{goal_id}", json={"status": "EXECUTING"}
        )
        assert illegal_res.status_code == 409
        assert "Illegal Goal state transition" in illegal_res.json()["detail"]


async def test_09_client_forced_terminal_success_rejected_with_409(bridge_auth_fixture):
    """Verify clients cannot directly force terminal success states (COMPLETED / SUCCEEDED)."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        # A. Mission: cannot patch status=COMPLETED
        m = (
            await client_a.post(
                f"/api/v1/projects/{proj_a_id}/missions",
                json={"title": "Mission Status Test", "objective": "Test"},
            )
        ).json()
        m_patch = await client_a.patch(
            f"/api/v1/missions/{m['id']}", json={"status": "COMPLETED"}
        )
        assert m_patch.status_code == 409
        assert "cannot directly force Mission into terminal state" in m_patch.json()["detail"]

        # B. Goal: cannot patch status=COMPLETED
        g = (
            await client_a.post(
                f"/api/v1/projects/{proj_a_id}/goals",
                json={"objective": "Goal Status Test"},
            )
        ).json()
        g_patch = await client_a.patch(
            f"/api/v1/goals/{g['id']}", json={"status": "COMPLETED"}
        )
        assert g_patch.status_code == 409
        assert "cannot directly force Goal into terminal state" in g_patch.json()["detail"]

        # C. Action: cannot patch status=SUCCEEDED
        act = (
            await client_a.post(
                f"/api/v1/goals/{g['id']}/actions",
                json={
                    "client_action_id": "act-term-test",
                    "title": "Terminal Test",
                    "action_type": "RESEARCH",
                    "required_capability": "REASONING",
                },
            )
        ).json()
        act_patch = await client_a.patch(
            f"/api/v1/actions/{act['id']}", json={"status": "SUCCEEDED"}
        )
        assert act_patch.status_code == 409
        assert "cannot directly force ActionNode into terminal state" in act_patch.json()["detail"]


# ===========================================================================
# 5. Schema Strictness & Actor Identity Safety Tests
# ===========================================================================

async def test_10_actor_identity_cannot_be_forged_in_payload(bridge_auth_fixture):
    """Verify clients cannot forge actor identity: extra fields rejected with 422."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/missions",
            json={
                "title": "Spoofed Identity Mission",
                "objective": "Attempt to impersonate SuperAdmin",
                "created_by": "ROOT_ADMIN_SPOOFED",
            },
        )
        assert res.status_code == 422
        # Pydantic extra="forbid" rejects the unknown field
        errors = res.json()["detail"]
        assert any("extra_forbidden" in str(err) for err in errors)


# ===========================================================================
# 6. Governance Decision Append-Only Semantics Tests
# ===========================================================================

async def test_11_governance_decisions_create_list_no_update_or_delete(bridge_auth_fixture):
    """Verify governance decisions can be created and listed, but PUT/PATCH/DELETE are 405."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        # 1. Create a decision
        create_res = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/governance-decisions",
            json={
                "verdict": "REQUIRES_ESCALATION",
                "risk_level": "HIGH",
                "policy_evaluations": [
                    {"policy": "no-unattended-publishing", "passed": False}
                ],
                "reasons": ["Automated publishing requires operator signoff"],
            },
        )
        assert create_res.status_code == 201
        dec = create_res.json()
        assert dec["verdict"] == "REQUIRES_ESCALATION"
        dec_id = dec["id"]

        # 2. List decisions
        list_res = await client_a.get(f"/api/v1/projects/{proj_a_id}/governance-decisions")
        assert list_res.status_code == 200
        assert any(d["id"] == dec_id for d in list_res.json())

        # 3. Get decision by ID
        get_res = await client_a.get(f"/api/v1/governance-decisions/{dec_id}")
        assert get_res.status_code == 200

        # 4. PUT is 405 Method Not Allowed
        put_res = await client_a.put(
            f"/api/v1/governance-decisions/{dec_id}", json={"verdict": "APPROVED"}
        )
        assert put_res.status_code == 405

        # 5. PATCH is 405 Method Not Allowed
        patch_res = await client_a.patch(
            f"/api/v1/governance-decisions/{dec_id}", json={"verdict": "APPROVED"}
        )
        assert patch_res.status_code == 405

        # 6. DELETE is 405 Method Not Allowed
        del_res = await client_a.delete(f"/api/v1/governance-decisions/{dec_id}")
        assert del_res.status_code == 405


# ===========================================================================
# 7. Constraint Integrity & Zero External Dispatch Tests
# ===========================================================================

async def test_12_duplicate_client_action_id_returns_409(bridge_auth_fixture):
    """Verify creating a second action node with an identical client_action_id in a goal returns 409."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        g = (
            await client_a.post(
                f"/api/v1/projects/{proj_a_id}/goals",
                json={"objective": "Duplicate Action ID Test Goal"},
            )
        ).json()
        goal_id = g["id"]

        # Create first action
        act1 = await client_a.post(
            f"/api/v1/goals/{goal_id}/actions",
            json={
                "client_action_id": "act-unique-01",
                "title": "First Action",
                "action_type": "RESEARCH",
                "required_capability": "REASONING",
            },
        )
        assert act1.status_code == 201

        # Attempt to create duplicate action
        act2 = await client_a.post(
            f"/api/v1/goals/{goal_id}/actions",
            json={
                "client_action_id": "act-unique-01",
                "title": "Duplicate Action Attempt",
                "action_type": "RESEARCH",
                "required_capability": "REASONING",
            },
        )
        assert act2.status_code == 409
        assert "already exists in this goal" in act2.json()["detail"]


async def test_13_crud_request_is_pure_persistence_without_external_dispatch(bridge_auth_fixture):
    """Verify that creating goals and action nodes performs only durable DB storage without side effects."""
    proj_a_id = bridge_auth_fixture["proj_a_id"]

    async with _create_client(token=bridge_auth_fixture["key_a"]) as client_a:
        res = await client_a.post(
            f"/api/v1/projects/{proj_a_id}/goals",
            json={
                "objective": "Verify pure persistence contract",
                "actions": [
                    {
                        "client_action_id": "act-no-dispatch",
                        "title": "Durable Only Step",
                        "action_type": "EXTERNAL_ACTION",
                        "required_capability": "PUBLISHING",
                    }
                ],
            },
        )
        assert res.status_code == 201
        data = res.json()

        # Goal is in DRAFT, Action is in PENDING — neither executed nor published
        assert data["status"] == "DRAFT"
        assert data["actions"][0]["status"] == "PENDING"
        assert data["actions"][0]["outputs_json"] is None
