"""
AryaOS V1 — Slice 12: Production Authorization, Project Isolation & Workflow Ownership Hardening.

Comprehensive integration test suite verifying:
1. Strict Bearer token authentication & WWW-Authenticate headers on all protected endpoints.
2. Inactive & unknown token rejection (401 Unauthorized).
3. Unrestricted access for System Master Key and DB-backed Admin keys (is_admin=True).
4. Project isolation on Workflow Run creation (403 Forbidden on non-member projects).
5. IDOR protection on Workflow Runs (404 Not Found on cross-project GET, PATCH, execute, recover, resume).
6. List filtering on Workflow Runs (non-admin callers only receive runs from authorized projects).
7. IDOR protection on Approval Checkpoints (404 Not Found on cross-project GET, decide, pending, create).
8. List filtering on Approval Checkpoints (non-admin callers only receive checkpoints for authorized runs).
9. Project isolation on end-to-end workflow endpoints (/workflows/youtube).
10. Multi-project membership authorization.
11. Zero-membership key safety (empty lists, 404/403 on resources).
12. API key SHA-256 hashing and helper integrity.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.approval import ApprovalAction, ApprovalCheckpoint
from app.models.content import Script, Storyboard
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalStage, PipelineStage, WorkflowMode, WorkflowStatus
from app.models.media import Thumbnail, Video
from app.models.system import SystemLog
from app.services.authorization_service import (
    add_project_membership,
    create_api_key,
    generate_api_key,
    get_authorized_project_ids,
    hash_api_key,
    verify_checkpoint_access,
    verify_project_access,
    verify_workflow_access,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ===========================================================================
# FIXTURES & SETUP
# ===========================================================================


@pytest_asyncio.fixture(loop_scope="module")
async def isolation_fixture(db_session: AsyncSession):
    """Sets up two distinct projects (Project A and Project B) and three principals:
    - Key A: member of Project A only
    - Key B: member of Project B only
    - Key Admin: database key with is_admin=True
    - Key Multi: member of both Project A and Project B
    - Key None: active key with NO project memberships
    - Key Inactive: inactive key
    """
    # 1. Projects
    proj_a = Project(name=f"Project-A-{uuid.uuid4()}")
    proj_b = Project(name=f"Project-B-{uuid.uuid4()}")
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()
    await db_session.refresh(proj_a)
    await db_session.refresh(proj_b)

    # 2. API Keys
    key_a_model, key_a_raw = await create_api_key(db_session, name="Key A", is_admin=False)
    key_b_model, key_b_raw = await create_api_key(db_session, name="Key B", is_admin=False)
    admin_model, admin_raw = await create_api_key(db_session, name="Key Admin", is_admin=True)
    multi_model, multi_raw = await create_api_key(db_session, name="Key Multi", is_admin=False)
    none_model, none_raw = await create_api_key(db_session, name="Key None", is_admin=False)
    inactive_model, inactive_raw = await create_api_key(db_session, name="Key Inactive", is_admin=False)

    inactive_model.is_active = False
    await db_session.commit()

    # 3. Memberships
    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=key_a_model.id, role="owner")
    await add_project_membership(db_session, project_id=proj_b.id, api_key_id=key_b_model.id, role="owner")
    await add_project_membership(db_session, project_id=proj_a.id, api_key_id=multi_model.id, role="member")
    await add_project_membership(db_session, project_id=proj_b.id, api_key_id=multi_model.id, role="member")

    # 4. Workflow Runs and Checkpoints
    run_a = WorkflowRun(
        project_id=proj_a.id,
        topic="Project A Topic",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.PENDING,
        current_stage=PipelineStage.CREATED.value,
    )
    run_b = WorkflowRun(
        project_id=proj_b.id,
        topic="Project B Topic",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.PENDING,
        current_stage=PipelineStage.CREATED.value,
    )
    db_session.add_all([run_a, run_b])
    await db_session.commit()
    await db_session.refresh(run_a)
    await db_session.refresh(run_b)

    cp_a = ApprovalCheckpoint(
        workflow_run_id=run_a.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    cp_b = ApprovalCheckpoint(
        workflow_run_id=run_b.id,
        stage=ApprovalStage.SCRIPT,
        reference_table="scripts",
        reference_id=uuid.uuid4(),
    )
    db_session.add_all([cp_a, cp_b])
    await db_session.commit()
    await db_session.refresh(cp_a)
    await db_session.refresh(cp_b)

    data = {
        "proj_a": proj_a,
        "proj_b": proj_b,
        "key_a": key_a_raw,
        "key_b": key_b_raw,
        "key_admin": admin_raw,
        "key_multi": multi_raw,
        "key_none": none_raw,
        "key_inactive": inactive_raw,
        "run_a": run_a,
        "run_b": run_b,
        "cp_a": cp_a,
        "cp_b": cp_b,
    }

    yield data

    # Teardown
    try:
        await db_session.execute(delete(ApprovalCheckpoint).where(ApprovalCheckpoint.workflow_run_id.in_([run_a.id, run_b.id])))
        await db_session.execute(delete(SystemLog).where(SystemLog.workflow_run_id.in_([run_a.id, run_b.id])))
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.project_id.in_([proj_a.id, proj_b.id])))
        await db_session.execute(delete(ProjectMembership).where(ProjectMembership.project_id.in_([proj_a.id, proj_b.id])))
        await db_session.execute(delete(Project).where(Project.id.in_([proj_a.id, proj_b.id])))
        await db_session.execute(
            delete(ApiKey).where(
                ApiKey.id.in_([
                    key_a_model.id,
                    key_b_model.id,
                    admin_model.id,
                    multi_model.id,
                    none_model.id,
                    inactive_model.id,
                ])
            )
        )
        await db_session.commit()
    except Exception:
        await db_session.rollback()


def _make_client(token: str | None = None) -> httpx.AsyncClient:
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers)


# ===========================================================================
# 1. AUTHENTICATION & HEADER ENFORCEMENT
# ===========================================================================


async def test_unauthenticated_requests_receive_401_with_headers():
    """Missing Authorization header receives 401 with WWW-Authenticate: Bearer."""
    async with _make_client(None) as client:
        endpoints = [
            ("GET", "/workflow-runs/"),
            ("POST", "/workflow-runs/"),
            ("GET", f"/workflow-runs/{uuid.uuid4()}"),
            ("PATCH", f"/workflow-runs/{uuid.uuid4()}"),
            ("POST", f"/workflow-runs/{uuid.uuid4()}/execute"),
            ("POST", f"/workflow-runs/{uuid.uuid4()}/recover"),
            ("POST", f"/workflow-runs/{uuid.uuid4()}/resume"),
            ("GET", "/approvals/"),
            ("POST", "/approvals/"),
            ("GET", f"/approvals/{uuid.uuid4()}"),
            ("POST", f"/approvals/{uuid.uuid4()}/decide"),
            ("GET", f"/approvals/pending/{uuid.uuid4()}"),
            ("POST", f"/workflows/youtube?project_id={uuid.uuid4()}"),
        ]

        for method, path in endpoints:
            if method == "GET":
                resp = await client.get(path)
            elif method == "PATCH":
                resp = await client.patch(path, json={})
            else:
                resp = await client.post(path, json={})

            assert resp.status_code == 401, f"{method} {path} expected 401, got {resp.status_code}"
            assert resp.headers.get("WWW-Authenticate") == "Bearer"


async def test_malformed_auth_headers_receive_401():
    """Non-Bearer schemes or empty tokens receive 401."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    ) as client:
        resp = await client.get("/workflow-runs/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer  "},
    ) as client:
        resp = await client.get("/workflow-runs/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"


async def test_inactive_and_unknown_api_keys_receive_401(isolation_fixture):
    """Inactive keys and unrecognized tokens receive 401."""
    # Inactive key
    async with _make_client(isolation_fixture["key_inactive"]) as client:
        resp = await client.get("/workflow-runs/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    # Completely unknown token
    async with _make_client("arya_completely_unknown_token_value_xyz") as client:
        resp = await client.get("/workflow-runs/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"


# ===========================================================================
# 2. SYSTEM MASTER KEY & ADMIN PRIVILEGES
# ===========================================================================


async def test_system_master_key_unrestricted_access(client: httpx.AsyncClient, isolation_fixture):
    """Configured ARYA_API_KEY has full unrestricted access across all projects."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]
    cp_a = isolation_fixture["cp_a"]
    cp_b = isolation_fixture["cp_b"]

    # Can read run A and run B
    resp_a = await client.get(f"/workflow-runs/{run_a.id}")
    assert resp_a.status_code == 200
    assert resp_a.json()["id"] == str(run_a.id)

    resp_b = await client.get(f"/workflow-runs/{run_b.id}")
    assert resp_b.status_code == 200
    assert resp_b.json()["id"] == str(run_b.id)

    # Can read checkpoint A and checkpoint B
    resp_cp_a = await client.get(f"/approvals/{cp_a.id}")
    assert resp_cp_a.status_code == 200

    resp_cp_b = await client.get(f"/approvals/{cp_b.id}")
    assert resp_cp_b.status_code == 200

    # Lists contain both runs
    list_runs = await client.get("/workflow-runs/")
    assert list_runs.status_code == 200
    returned_run_ids = {r["id"] for r in list_runs.json()}
    assert str(run_a.id) in returned_run_ids
    assert str(run_b.id) in returned_run_ids


async def test_database_admin_key_unrestricted_access(isolation_fixture):
    """Database-backed key with is_admin=True has unrestricted access across all projects."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]
    cp_a = isolation_fixture["cp_a"]
    cp_b = isolation_fixture["cp_b"]

    async with _make_client(isolation_fixture["key_admin"]) as client:
        # Access runs in different projects
        resp_a = await client.get(f"/workflow-runs/{run_a.id}")
        assert resp_a.status_code == 200
        assert resp_a.json()["id"] == str(run_a.id)

        resp_b = await client.get(f"/workflow-runs/{run_b.id}")
        assert resp_b.status_code == 200
        assert resp_b.json()["id"] == str(run_b.id)

        # Access checkpoints in different projects
        resp_cp_a = await client.get(f"/approvals/{cp_a.id}")
        assert resp_cp_a.status_code == 200

        resp_cp_b = await client.get(f"/approvals/{cp_b.id}")
        assert resp_cp_b.status_code == 200


# ===========================================================================
# 3. PROJECT ISOLATION & WORKFLOW RUN CREATION
# ===========================================================================


async def test_workflow_run_creation_project_isolation(isolation_fixture, db_session: AsyncSession):
    """A scoped key can only create runs for projects it belongs to."""
    proj_a = isolation_fixture["proj_a"]
    proj_b = isolation_fixture["proj_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        # 1. Allowed: Key A creates run for Project A
        resp_ok = await client_a.post(
            "/workflow-runs/",
            json={"project_id": str(proj_a.id), "topic": "New Run A", "mode": "assisted"},
        )
        assert resp_ok.status_code == 201
        created_id = uuid.UUID(resp_ok.json()["workflow_run_id"])

        # Clean up created run
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == created_id))
        await db_session.commit()

        # 2. Forbidden: Key A attempts to create run for Project B
        resp_forbidden = await client_a.post(
            "/workflow-runs/",
            json={"project_id": str(proj_b.id), "topic": "Unauthorized Run B", "mode": "assisted"},
        )
        assert resp_forbidden.status_code == 403
        assert "not authorized" in resp_forbidden.json()["detail"].lower()

        # 3. Unprocessable: Non-existent project
        non_existent_id = uuid.uuid4()
        resp_not_found = await client_a.post(
            "/workflow-runs/",
            json={"project_id": str(non_existent_id), "topic": "Missing Project", "mode": "assisted"},
        )
        assert resp_not_found.status_code == 422


# ===========================================================================
# 4. IDOR PROTECTION ON WORKFLOW RUN MUTATIONS & ACCESS
# ===========================================================================


async def test_workflow_run_idor_protection_returns_404(isolation_fixture):
    """Accessing, updating, executing, recovering, or resuming another project's run
    MUST return 404 Not Found to prevent information disclosure (never 403)."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        # Key A querying run B receives 404
        resp_get = await client_a.get(f"/workflow-runs/{run_b.id}")
        assert resp_get.status_code == 404
        assert "not found" in resp_get.json()["detail"].lower()

        # Key A updating run B receives 404
        resp_patch = await client_a.patch(
            f"/workflow-runs/{run_b.id}",
            json={"failure_reason": "Malicious override"},
        )
        assert resp_patch.status_code == 404

        # Key A executing run B receives 404
        resp_exec = await client_a.post(f"/workflow-runs/{run_b.id}/execute")
        assert resp_exec.status_code == 404

        # Key A recovering run B receives 404
        resp_rec = await client_a.post(f"/workflow-runs/{run_b.id}/recover")
        assert resp_rec.status_code == 404

        # Key A resuming run B receives 404
        resp_res = await client_a.post(f"/workflow-runs/{run_b.id}/resume")
        assert resp_res.status_code == 404

        # In contrast, Key A accessing run A succeeds with 200
        resp_legit = await client_a.get(f"/workflow-runs/{run_a.id}")
        assert resp_legit.status_code == 200
        assert resp_legit.json()["id"] == str(run_a.id)


# ===========================================================================
# 5. LIST FILTERING ON WORKFLOW RUNS
# ===========================================================================


async def test_workflow_runs_list_filtering(isolation_fixture):
    """Listing workflow runs is strictly partitioned by project membership."""
    proj_a = isolation_fixture["proj_a"]
    proj_b = isolation_fixture["proj_b"]
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        # Unfiltered list for Key A contains run A, but NOT run B
        resp = await client_a.get("/workflow-runs/")
        assert resp.status_code == 200
        run_ids = {r["id"] for r in resp.json()}
        assert str(run_a.id) in run_ids
        assert str(run_b.id) not in run_ids

        # Explicitly filtering by Project A works
        resp_a = await client_a.get(f"/workflow-runs/?project_id={proj_a.id}")
        assert resp_a.status_code == 200
        assert str(run_a.id) in {r["id"] for r in resp_a.json()}

        # Requesting runs for Project B returns an empty list
        resp_b = await client_a.get(f"/workflow-runs/?project_id={proj_b.id}")
        assert resp_b.status_code == 200
        assert resp_b.json() == []

    async with _make_client(isolation_fixture["key_b"]) as client_b:
        resp = await client_b.get("/workflow-runs/")
        assert resp.status_code == 200
        run_ids = {r["id"] for r in resp.json()}
        assert str(run_b.id) in run_ids
        assert str(run_a.id) not in run_ids


# ===========================================================================
# 6. IDOR PROTECTION & LIST FILTERING ON APPROVALS
# ===========================================================================


async def test_approvals_idor_protection_returns_404(isolation_fixture):
    """Accessing, deciding, or querying checkpoints for another project's run returns 404."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]
    cp_a = isolation_fixture["cp_a"]
    cp_b = isolation_fixture["cp_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        # 1. GET /approvals/{cp_b.id} -> 404
        resp_get = await client_a.get(f"/approvals/{cp_b.id}")
        assert resp_get.status_code == 404

        # 2. POST /approvals/{cp_b.id}/decide -> 404
        resp_decide = await client_a.post(
            f"/approvals/{cp_b.id}/decide",
            json={"action": "approve", "reviewer_notes": "Should fail"},
        )
        assert resp_decide.status_code == 404

        # 3. GET /approvals/pending/{run_b.id} -> 404
        resp_pending = await client_a.get(f"/approvals/pending/{run_b.id}")
        assert resp_pending.status_code == 404

        # 4. POST /approvals/ referencing run_b -> 404
        resp_create = await client_a.post(
            "/approvals/",
            json={
                "workflow_run_id": str(run_b.id),
                "stage": "script",
                "reference_table": "scripts",
                "reference_id": str(uuid.uuid4()),
            },
        )
        assert resp_create.status_code == 404

        # Legit access to Project A checkpoint works
        resp_legit = await client_a.get(f"/approvals/{cp_a.id}")
        assert resp_legit.status_code == 200
        assert resp_legit.json()["id"] == str(cp_a.id)

        resp_pending_a = await client_a.get(f"/approvals/pending/{run_a.id}")
        assert resp_pending_a.status_code == 200
        assert str(cp_a.id) in {c["id"] for c in resp_pending_a.json()}


async def test_approvals_list_filtering(isolation_fixture):
    """Listing checkpoints only returns checkpoints for authorized projects."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]
    cp_a = isolation_fixture["cp_a"]
    cp_b = isolation_fixture["cp_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        resp = await client_a.get("/approvals/")
        assert resp.status_code == 200
        cp_ids = {c["id"] for c in resp.json()}
        assert str(cp_a.id) in cp_ids
        assert str(cp_b.id) not in cp_ids

        # Filtering by run_b returns empty list
        resp_filtered = await client_a.get(f"/approvals/?workflow_run_id={run_b.id}")
        assert resp_filtered.status_code == 200
        assert resp_filtered.json() == []

    async with _make_client(isolation_fixture["key_b"]) as client_b:
        resp = await client_b.get("/approvals/")
        assert resp.status_code == 200
        cp_ids = {c["id"] for c in resp.json()}
        assert str(cp_b.id) in cp_ids
        assert str(cp_a.id) not in cp_ids


# ===========================================================================
# 7. MULTI-PROJECT MEMBERSHIP & ZERO-MEMBERSHIP KEYS
# ===========================================================================


async def test_multi_project_membership(isolation_fixture):
    """A key associated with multiple projects can access resources in all authorized projects."""
    run_a = isolation_fixture["run_a"]
    run_b = isolation_fixture["run_b"]
    cp_a = isolation_fixture["cp_a"]
    cp_b = isolation_fixture["cp_b"]

    async with _make_client(isolation_fixture["key_multi"]) as client_multi:
        # Can access run A and run B
        resp_a = await client_multi.get(f"/workflow-runs/{run_a.id}")
        assert resp_a.status_code == 200

        resp_b = await client_multi.get(f"/workflow-runs/{run_b.id}")
        assert resp_b.status_code == 200

        # Can access checkpoint A and checkpoint B
        resp_cp_a = await client_multi.get(f"/approvals/{cp_a.id}")
        assert resp_cp_a.status_code == 200

        resp_cp_b = await client_multi.get(f"/approvals/{cp_b.id}")
        assert resp_cp_b.status_code == 200

        # Listing runs returns both
        resp_runs = await client_multi.get("/workflow-runs/")
        assert resp_runs.status_code == 200
        ids = {r["id"] for r in resp_runs.json()}
        assert str(run_a.id) in ids
        assert str(run_b.id) in ids


async def test_key_without_project_membership(isolation_fixture):
    """An active key without any project memberships returns empty lists and 404/403 on resources."""
    proj_a = isolation_fixture["proj_a"]
    run_a = isolation_fixture["run_a"]
    cp_a = isolation_fixture["cp_a"]

    async with _make_client(isolation_fixture["key_none"]) as client_none:
        # Lists are empty
        resp_runs = await client_none.get("/workflow-runs/")
        assert resp_runs.status_code == 200
        assert resp_runs.json() == []

        resp_cps = await client_none.get("/approvals/")
        assert resp_cps.status_code == 200
        assert resp_cps.json() == []

        # Accessing resources returns 404
        assert (await client_none.get(f"/workflow-runs/{run_a.id}")).status_code == 404
        assert (await client_none.get(f"/approvals/{cp_a.id}")).status_code == 404

        # Creating run returns 403
        resp_create = await client_none.post(
            "/workflow-runs/",
            json={"project_id": str(proj_a.id), "topic": "Topic", "mode": "assisted"},
        )
        assert resp_create.status_code == 403


# ===========================================================================
# 8. WORKFLOWS YOUTUBE ENDPOINT AUTHORIZATION
# ===========================================================================


async def test_workflows_youtube_project_authorization(isolation_fixture):
    """POST /workflows/youtube enforces project authorization."""
    proj_b = isolation_fixture["proj_b"]

    async with _make_client(isolation_fixture["key_a"]) as client_a:
        # Key A attempting to run workflow in Project B -> 403 Forbidden
        resp_forbidden = await client_a.post(
            f"/workflows/youtube?project_id={proj_b.id}",
            json={"topic": "Unauthorized Video", "platform": "youtube", "preset": "documentary_short"},
        )
        assert resp_forbidden.status_code == 403

        # Non-existent project -> 404
        missing_id = uuid.uuid4()
        resp_missing = await client_a.post(
            f"/workflows/youtube?project_id={missing_id}",
            json={"topic": "Missing Video", "platform": "youtube", "preset": "documentary_short"},
        )
        assert resp_missing.status_code == 404


# ===========================================================================
# 9. SERVICE UNIT TESTS & INTEGRITY
# ===========================================================================


async def test_hash_api_key_deterministic_and_secure():
    """Verify SHA-256 hash output format and determinism."""
    raw = "arya_test_secret_key_12345"
    h1 = hash_api_key(raw)
    h2 = hash_api_key(f"  {raw}  ")
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


async def test_generate_api_key_format():
    """Verify generated API key prefix and randomness."""
    key = generate_api_key()
    assert key.startswith("arya_")
    assert len(key) >= 40
