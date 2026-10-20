"""
AryaOS V1 — Slice 13 Integration Test Suite.
Production Readiness, Authorization Completion & Distributed-Safety Hardening.

Verifies:
1. Lineage Object-Level Authorization & IDOR Prevention (404 on foreign project).
2. Publishing Object-Level Authorization & IDOR Prevention (404 on foreign workflow_run_id and video_id).
3. Analytics Object-Level Authorization & Scoped Listing (snapshots query filtering by project membership).
4. Agents Object-Level Authorization (404 on foreign workflow_run_id).
5. Research Object-Level Authorization (404 on foreign workflow_run_id for reddit and trends).
6. Feature Flags Admin Mutation Protection (403 for non-admin on PUT, read allowed on GET).
7. Creator Studio Multi-Tenancy & Project Isolation (project assignment, history filtering, job IDOR 404).
8. Distributed Concurrency & Row-Locking Lease Safety (concurrent claim rejection, stale worker fencing).
9. API Key & Membership Service Hardening (non-admin forbidden from creating admin keys or assigning memberships).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.analytics import Analytics
from app.models.core import Project, WorkflowRun
from app.models.enums import WorkflowMode, WorkflowStatus
from app.models.media import Video
from app.services.authorization_service import (
    add_project_membership,
    create_api_key,
    get_authorized_project_ids,
)
from app.services.workflow_execution_service import (
    WorkflowExecutionConflictError,
    claim_execution_lease,
    finalize_workflow_execution,
    recover_workflow_run,
    update_heartbeat,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def isolation_setup(db_session: AsyncSession):
    """Setup two distinct isolated projects and two dedicated scoped API keys."""
    # 1. Project A & Principal A
    proj_a = Project(name=f"Project-A-{uuid.uuid4().hex[:8]}")
    db_session.add(proj_a)
    await db_session.commit()
    await db_session.refresh(proj_a)

    key_record_a, raw_key_a = await create_api_key(
        db_session, name="Key-A-Member", is_admin=False
    )
    await add_project_membership(db_session, proj_a.id, key_record_a.id, role="owner")

    # 2. Project B & Principal B
    proj_b = Project(name=f"Project-B-{uuid.uuid4().hex[:8]}")
    db_session.add(proj_b)
    await db_session.commit()
    await db_session.refresh(proj_b)

    key_record_b, raw_key_b = await create_api_key(
        db_session, name="Key-B-Member", is_admin=False
    )
    await add_project_membership(db_session, proj_b.id, key_record_b.id, role="owner")

    # 3. Dedicated HTTP clients
    transport = ASGITransport(app=app)
    client_a = AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    client_b = AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_key_b}"},
    )

    yield {
        "proj_a_id": proj_a.id,
        "key_a": raw_key_a,
        "client_a": client_a,
        "proj_b_id": proj_b.id,
        "key_b": raw_key_b,
        "client_b": client_b,
    }

    await client_a.aclose()
    await client_b.aclose()


# ============================================================================
# 1. LINEAGE OBJECT-LEVEL AUTHORIZATION & IDOR
# ============================================================================

async def test_lineage_cross_project_idor_blocked(
    db_session: AsyncSession,
    isolation_setup: dict,
    client: AsyncClient,
):
    """GET /lineage/{workflow_run_id} returns 404 when queried by non-member of project."""
    proj_a_id = isolation_setup["proj_a_id"]
    client_a = isolation_setup["client_a"]
    client_b = isolation_setup["client_b"]

    run_a = WorkflowRun(
        project_id=proj_a_id,
        topic="Project A Lineage Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
    )
    db_session.add(run_a)
    await db_session.commit()
    await db_session.refresh(run_a)

    # Key A (project member) -> 200
    res_a = await client_a.get(f"/lineage/{run_a.id}")
    assert res_a.status_code == 200
    data = res_a.json()
    assert data["workflow_run_id"] == str(run_a.id)

    # Key B (foreign project) -> 404 (IDOR protection masks existence)
    res_b = await client_b.get(f"/lineage/{run_a.id}")
    assert res_b.status_code == 404

    # Admin Key -> 200
    res_admin = await client.get(f"/lineage/{run_a.id}")
    assert res_admin.status_code == 200


# ============================================================================
# 2. PUBLISHING OBJECT-LEVEL AUTHORIZATION & IDOR
# ============================================================================

async def test_publishing_cross_project_idor_blocked(
    db_session: AsyncSession,
    isolation_setup: dict,
    client: AsyncClient,
):
    """POST /publishing/publish validates workflow_run_id and video_id ownership."""
    proj_a_id = isolation_setup["proj_a_id"]
    client_a = isolation_setup["client_a"]
    client_b = isolation_setup["client_b"]

    run_a = WorkflowRun(
        project_id=proj_a_id,
        topic="Project A Publishing Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
    )
    db_session.add(run_a)
    await db_session.commit()
    await db_session.refresh(run_a)

    vid_a = Video(
        workflow_run_id=run_a.id,
        storage_path="videos/test_proj_a.mp4",
        duration_seconds=5.0,
        aspect_ratio="16:9",
    )
    db_session.add(vid_a)
    await db_session.commit()
    await db_session.refresh(vid_a)

    # 1. Foreign caller attempting publish with workflow_run_id -> 404
    payload_run = {
        "asset_storage_path": "videos/test_proj_a.mp4",
        "title": "Publish Test",
        "platform": "postiz",
        "social_platform": "youtube",
        "dry_run": True,
        "workflow_run_id": str(run_a.id),
    }
    res_b_run = await client_b.post("/publishing/publish", json=payload_run)
    assert res_b_run.status_code == 404

    # 2. Foreign caller attempting publish with video_id -> 404
    payload_vid = {
        "asset_storage_path": "videos/test_proj_a.mp4",
        "title": "Publish Test",
        "platform": "postiz",
        "social_platform": "youtube",
        "dry_run": True,
        "video_id": str(vid_a.id),
    }
    res_b_vid = await client_b.post("/publishing/publish", json=payload_vid)
    assert res_b_vid.status_code == 404

    # 3. Authorized caller with dry_run -> 200
    res_a = await client_a.post("/publishing/publish", json=payload_run)
    assert res_a.status_code == 200
    assert res_a.json()["is_dry_run"] is True


# ============================================================================
# 3. ANALYTICS OBJECT-LEVEL AUTHORIZATION & MULTI-PROJECT ISOLATION
# ============================================================================

async def test_analytics_multi_project_filtering_and_idor(
    db_session: AsyncSession,
    isolation_setup: dict,
    client: AsyncClient,
):
    """GET /analytics/snapshots and GET /analytics/latest enforce project isolation."""
    proj_a_id = isolation_setup["proj_a_id"]
    proj_b_id = isolation_setup["proj_b_id"]
    client_a = isolation_setup["client_a"]
    client_b = isolation_setup["client_b"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create run and snapshot in Project A
    run_a = WorkflowRun(
        project_id=proj_a_id,
        topic="Project A Analytics Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
    )
    db_session.add(run_a)
    await db_session.commit()
    await db_session.refresh(run_a)

    snap_a = Analytics(
        workflow_run_id=run_a.id,
        platform="youtube",
        source="fixture",
        snapshot_at=now,
        views=1500,
        likes=120,
        comments=15,
        shares=5,
        subscribers_gained=8,
    )
    db_session.add(snap_a)

    # Create run and snapshot in Project B
    run_b = WorkflowRun(
        project_id=proj_b_id,
        topic="Project B Analytics Topic",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
    )
    db_session.add(run_b)
    await db_session.commit()
    await db_session.refresh(run_b)

    snap_b = Analytics(
        workflow_run_id=run_b.id,
        platform="youtube",
        source="fixture",
        snapshot_at=now,
        views=800,
        likes=50,
        comments=4,
        shares=1,
        subscribers_gained=2,
    )
    db_session.add(snap_b)
    await db_session.commit()

    # 1. IDOR lookup: Key B looks up run_a snapshot explicitly -> 404
    res_idor = await client_b.get(f"/analytics/snapshots?workflow_run_id={run_a.id}")
    assert res_idor.status_code == 404

    res_latest_idor = await client_b.get(f"/analytics/latest?workflow_run_id={run_a.id}")
    assert res_latest_idor.status_code == 404

    # 2. Scoped listing: Key B lists all snapshots -> sees snap_b, NOT snap_a
    res_list_b = await client_b.get("/analytics/snapshots")
    assert res_list_b.status_code == 200
    b_snaps = res_list_b.json()
    b_run_ids = [s["workflow_run_id"] for s in b_snaps]
    assert str(run_b.id) in b_run_ids
    assert str(run_a.id) not in b_run_ids

    # 3. Scoped listing: Key A lists all snapshots -> sees snap_a, NOT snap_b
    res_list_a = await client_a.get("/analytics/snapshots")
    assert res_list_a.status_code == 200
    a_snaps = res_list_a.json()
    a_run_ids = [s["workflow_run_id"] for s in a_snaps]
    assert str(run_a.id) in a_run_ids
    assert str(run_b.id) not in a_run_ids


# ============================================================================
# 4. AGENTS OBJECT-LEVEL AUTHORIZATION & IDOR
# ============================================================================

async def test_agents_endpoint_cross_project_idor_blocked(
    db_session: AsyncSession,
    isolation_setup: dict,
):
    """POST /agents/{agent_name}/run verifies caller ownership of workflow_run_id."""
    proj_a_id = isolation_setup["proj_a_id"]
    client_b = isolation_setup["client_b"]

    run_a = WorkflowRun(
        project_id=proj_a_id,
        topic="Project A Agent Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
    )
    db_session.add(run_a)
    await db_session.commit()
    await db_session.refresh(run_a)

    # Key B attempts to trigger agent bound to Project A's workflow_run -> 404
    payload = {
        "context": {"topic": "Test Agent"},
        "workflow_run_id": str(run_a.id),
    }
    res = await client_b.post("/agents/script/run", json=payload)
    assert res.status_code == 404


# ============================================================================
# 5. RESEARCH OBJECT-LEVEL AUTHORIZATION & IDOR
# ============================================================================

async def test_research_endpoints_cross_project_idor_blocked(
    db_session: AsyncSession,
    isolation_setup: dict,
):
    """GET and POST /research endpoints reject binding provenance to foreign workflow runs."""
    proj_a_id = isolation_setup["proj_a_id"]
    client_b = isolation_setup["client_b"]

    run_a = WorkflowRun(
        project_id=proj_a_id,
        topic="Project A Research Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
    )
    db_session.add(run_a)
    await db_session.commit()
    await db_session.refresh(run_a)

    # 1. GET /research/reddit with foreign workflow_run_id -> 404
    res_get_reddit = await client_b.get(f"/research/reddit?topic=AI&workflow_run_id={run_a.id}")
    assert res_get_reddit.status_code == 404

    # 2. POST /research/reddit with foreign workflow_run_id -> 404
    res_post_reddit = await client_b.post(
        "/research/reddit",
        json={"topic": "AI", "workflow_run_id": str(run_a.id)},
    )
    assert res_post_reddit.status_code == 404

    # 3. GET /research/trends with foreign workflow_run_id -> 404
    res_trends = await client_b.get(f"/research/trends?topic=AI&workflow_run_id={run_a.id}")
    assert res_trends.status_code == 404


# ============================================================================
# 6. FEATURE FLAGS ADMIN MUTATION ENFORCEMENT
# ============================================================================

async def test_feature_flags_admin_mutation_enforcement(
    isolation_setup: dict,
    client: AsyncClient,
):
    """Non-admin callers can read feature flags but cannot mutate (PUT -> 403)."""
    client_a = isolation_setup["client_a"]

    # 1. Non-admin read -> 200 OK
    res_read = await client_a.get("/feature-flags/")
    assert res_read.status_code == 200

    # 2. Non-admin write -> 403 Forbidden
    res_write_denied = await client_a.put(
        "/feature-flags/autonomous_publishing",
        json={"enabled": True, "description": "Attempted non-admin mutation"},
    )
    assert res_write_denied.status_code == 403
    assert "Admin access required" in res_write_denied.json()["detail"]

    # 3. Admin write -> 200 OK
    res_write_admin = await client.put(
        "/feature-flags/autonomous_publishing",
        json={"enabled": False, "description": "Admin configuration"},
    )
    assert res_write_admin.status_code == 200
    assert res_write_admin.json()["enabled"] is False


# ============================================================================
# 7. CREATOR STUDIO MULTI-TENANCY & PROJECT ISOLATION
# ============================================================================

async def test_creator_studio_project_isolation(
    db_session: AsyncSession,
    isolation_setup: dict,
):
    """Creator Studio generations are bound to caller's project and protected from IDOR."""
    proj_a_id = isolation_setup["proj_a_id"]
    proj_b_id = isolation_setup["proj_b_id"]
    client_a = isolation_setup["client_a"]
    client_b = isolation_setup["client_b"]

    # 1. Key A generates without specifying project_id -> auto-assigned to Project A
    res_gen_a = await client_a.post(
        "/creator/generate",
        json={"generation_type": "image", "prompt": "Cyberpunk Neon City"},
    )
    assert res_gen_a.status_code == 202
    job_a = res_gen_a.json()
    job_a_id = job_a["job_id"]

    run_a = await db_session.get(WorkflowRun, uuid.UUID(job_a_id))
    assert run_a is not None
    assert run_a.project_id == proj_a_id

    # 2. Key A attempts to generate explicitly specifying Project B -> 403 Forbidden
    res_denied = await client_a.post(
        "/creator/generate",
        json={
            "generation_type": "image",
            "prompt": "Forbidden Generation",
            "project_id": str(proj_b_id),
        },
    )
    assert res_denied.status_code == 403

    # 3. Key B attempts to poll Key A's job -> 404 (both in-memory cache and DB)
    res_poll_b = await client_b.get(f"/creator/jobs/{job_a_id}")
    assert res_poll_b.status_code == 404

    # 4. Key A polls own job -> 200 OK
    res_poll_a = await client_a.get(f"/creator/jobs/{job_a_id}")
    assert res_poll_a.status_code == 200

    # 5. History isolation: Key B history does not contain Key A's job
    res_hist_b = await client_b.get("/creator/history")
    assert res_hist_b.status_code == 200
    hist_b_ids = [item["job_id"] for item in res_hist_b.json()]
    assert job_a_id not in hist_b_ids

    # Key A history contains own job
    res_hist_a = await client_a.get("/creator/history")
    assert res_hist_a.status_code == 200
    hist_a_ids = [item["job_id"] for item in res_hist_a.json()]
    assert job_a_id in hist_a_ids


# ============================================================================
# 8. DISTRIBUTED CONCURRENCY & LEASE FENCING
# ============================================================================

async def test_concurrent_double_execution_prevention(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """Concurrent attempts to claim execution lease on active run are rejected with row-locking."""
    run = WorkflowRun(
        project_id=test_project,
        topic="Concurrent Claim Race Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.PENDING,
        current_stage="created",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    # Worker 1 claims lease
    worker_1 = "worker-instance-1"
    run_1 = await claim_execution_lease(db_session, run.id, worker_id=worker_1)
    assert run_1.status == WorkflowStatus.RUNNING
    assert run_1.worker_id == worker_1

    # Worker 2 attempts concurrent claim on active lease -> raises WorkflowExecutionConflictError
    worker_2 = "worker-instance-2"
    with pytest.raises(WorkflowExecutionConflictError) as exc_info:
        await claim_execution_lease(db_session, run.id, worker_id=worker_2)
    assert "actively executing" in str(exc_info.value)


async def test_stale_worker_lease_fencing_and_recovery(
    db_session: AsyncSession,
    test_project: uuid.UUID,
):
    """When a stale run is recovered, the previous worker's heartbeat and completion fail."""
    from datetime import timedelta

    run = WorkflowRun(
        project_id=test_project,
        topic="Lease Fencing Test",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        current_stage="created",
        worker_id="worker-stale-1",
        last_heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=600),
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    # 1. Recovery worker reclaims the stale lease
    recovery_worker = "worker-recovery-2"
    recovered_run, next_stage = await recover_workflow_run(
        db=db_session,
        run_id=run.id,
        worker_id=recovery_worker,
        timeout_seconds=300,
    )
    assert recovered_run.worker_id == recovery_worker
    assert recovered_run.status == WorkflowStatus.RUNNING

    # 2. Stale worker wakes up and attempts heartbeat -> rejected with WorkflowExecutionConflictError
    with pytest.raises(WorkflowExecutionConflictError) as hb_exc:
        await update_heartbeat(db_session, run.id, worker_id="worker-stale-1")
    assert "cannot update heartbeat for lease owned by" in str(hb_exc.value)

    # 3. Stale worker attempts to finalize/complete run -> rejected with WorkflowExecutionConflictError
    with pytest.raises(WorkflowExecutionConflictError) as finalize_exc:
        await finalize_workflow_execution(
            db=db_session,
            run_id=run.id,
            worker_id="worker-stale-1",
            status=WorkflowStatus.COMPLETED,
        )
    assert "cannot finalize workflow run" in str(finalize_exc.value)

    # Verify run remains owned by recovery worker
    refreshed = await db_session.get(WorkflowRun, run.id)
    assert refreshed.worker_id == recovery_worker
    assert refreshed.status == WorkflowStatus.RUNNING


# ============================================================================
# 9. SERVICE-LEVEL API KEY & MEMBERSHIP ADMINISTRATION HARDENING
# ============================================================================

async def test_service_level_api_key_and_membership_hardening(
    db_session: AsyncSession,
    isolation_setup: dict,
):
    """Non-admin principals cannot create admin API keys or add members to foreign projects."""
    from app.core.security import AuthenticatedPrincipal
    from fastapi import HTTPException

    key_a = isolation_setup["key_a"]
    proj_b_id = isolation_setup["proj_b_id"]

    principal_a = AuthenticatedPrincipal(
        name="Key-A-Member",
        is_admin=False,
        api_key_id=uuid.uuid4(),
    )

    # 1. Non-admin principal cannot create API key
    with pytest.raises(HTTPException) as exc_key:
        await create_api_key(
            db_session,
            name="Rogue-Key",
            is_admin=True,
            creator_principal=principal_a,
        )
    assert exc_key.value.status_code == 403

    # 2. Non-admin principal cannot assign membership to foreign Project B
    with pytest.raises(HTTPException) as exc_mem:
        await add_project_membership(
            db_session,
            project_id=proj_b_id,
            api_key_id=uuid.uuid4(),
            role="member",
            creator_principal=principal_a,
        )
    assert exc_mem.value.status_code == 403
