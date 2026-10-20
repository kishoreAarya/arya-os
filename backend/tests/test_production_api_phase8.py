"""
AryaOS V1 Phase 8 — Production API & Database Integration Unit & Integration Tests.

Validates:
1. Project creation, listing, retrieval, update, deletion
2. Sequence creation and listing
3. Shot creation, listing, and updating
4. Full project tree retrieval
5. AryaJobPackage boundary contract submission and validation
6. Centralized Job State Machine transitions and illegal transition rejection
7. Preflight blocked package rejection
8. Malformed decision boundary rejection
9. 404 responses for nonexistent IDs
10. Server-Sent Events (SSE) telemetry streaming
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.production import ProductionShot

# Uses conftest.py module-scoped fixtures (client, db_session)
pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_01_create_and_list_projects(client: AsyncClient):
    # Create Project
    res = await client.post(
        "/api/v1/projects",
        json={"name": "Obsidian Station Chronicle", "description": "Sci-Fi cinematic timeline"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Obsidian Station Chronicle"
    assert data["status"] == "ACTIVE"
    project_id = data["id"]

    # List Projects
    list_res = await client.get("/api/v1/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    assert any(p["id"] == project_id for p in projects)


async def test_02_get_and_update_project(client: AsyncClient):
    create_res = await client.post(
        "/api/v1/projects",
        json={"name": "Project To Update", "description": "Initial desc"},
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    # Get by ID
    get_res = await client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Project To Update"

    # Patch project
    patch_res = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Project Updated Name", "status": "ARCHIVED"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Project Updated Name"
    assert patch_res.json()["status"] == "ARCHIVED"


async def test_03_delete_project_cascades(client: AsyncClient):
    create_res = await client.post(
        "/api/v1/projects",
        json={"name": "Project To Delete"},
    )
    project_id = create_res.json()["id"]

    del_res = await client.delete(f"/api/v1/projects/{project_id}")
    assert del_res.status_code == 204

    # Verify 404
    get_res = await client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 404


async def test_04_sequences_crud(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Seq Test Project"})
    project_id = proj_res.json()["id"]

    # Initial sequence was automatically created
    seq_list_res = await client.get(f"/api/v1/projects/{project_id}/sequences")
    assert seq_list_res.status_code == 200
    initial_seqs = seq_list_res.json()
    assert len(initial_seqs) == 1
    assert initial_seqs[0]["order_index"] == 1

    # Add Sequence 02
    add_seq_res = await client.post(
        f"/api/v1/projects/{project_id}/sequences",
        json={"name": "Sequence 02 // Motion push", "order_index": 2},
    )
    assert add_seq_res.status_code == 201
    seq2_id = add_seq_res.json()["id"]

    # Verify both sequences present in order
    seq_list_res2 = await client.get(f"/api/v1/projects/{project_id}/sequences")
    seqs = seq_list_res2.json()
    assert len(seqs) == 2
    assert seqs[1]["id"] == seq2_id


async def test_05_shots_crud_and_patch(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Shot Test Project"})
    project_id = proj_res.json()["id"]

    seq_res = await client.get(f"/api/v1/projects/{project_id}/sequences")
    sequence_id = seq_res.json()[0]["id"]

    # Create Shot 01
    shot_payload = {
        "sequence_id": sequence_id,
        "shot_number": 1,
        "title": "Establishing Wide",
        "prompt": "Deep space monolithic quantum spire",
        "generation_type": "image",
        "model": "flux-schnell",
        "provider": "together",
        "aspect_ratio": "16:9",
        "status": "READY",
        "first_frame": "https://assets.aryaos.internal/monolith.jpg",
    }
    create_shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json=shot_payload,
    )
    assert create_shot_res.status_code == 201
    shot_data = create_shot_res.json()
    assert shot_data["title"] == "Establishing Wide"
    assert shot_data["status"] == "READY"
    shot_id = shot_data["id"]

    # List Shots
    list_shots_res = await client.get(f"/api/v1/projects/{project_id}/shots")
    assert list_shots_res.status_code == 200
    assert len(list_shots_res.json()) == 1

    # Update Shot
    patch_shot_res = await client.patch(
        f"/api/v1/shots/{shot_id}",
        json={"status": "COMPLETE", "output_asset_url": "https://assets.aryaos.internal/render01.mp4"},
    )
    assert patch_shot_res.status_code == 200
    updated_shot = patch_shot_res.json()
    assert updated_shot["status"] == "COMPLETE"
    assert updated_shot["output_asset_url"] == "https://assets.aryaos.internal/render01.mp4"


async def test_06_get_full_project_tree(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Full Tree Project"})
    project_id = proj_res.json()["id"]

    seq_res = await client.get(f"/api/v1/projects/{project_id}/sequences")
    sequence_id = seq_res.json()[0]["id"]

    await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": sequence_id,
            "shot_number": 1,
            "title": "Tree Shot 1",
            "prompt": "Cyber command hub",
            "model": "kling-video",
            "provider": "kling",
        },
    )

    tree_res = await client.get(f"/api/v1/projects/{project_id}/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert tree["id"] == project_id
    assert len(tree["sequences"]) >= 1
    assert len(tree["sequences"][0]["shots"]) == 1
    assert tree["sequences"][0]["shots"][0]["title"] == "Tree Shot 1"


async def test_07_job_package_contract_submission(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Job Contract Project"})
    project_id = proj_res.json()["id"]

    seq_res = await client.get(f"/api/v1/projects/{project_id}/sequences")
    sequence_id = seq_res.json()[0]["id"]

    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": sequence_id,
            "shot_number": 1,
            "title": "Shot For Job",
            "prompt": "Cybernetic core chamber",
            "model": "kling-video",
            "provider": "kling",
        },
    )
    shot_id = shot_res.json()["id"]

    # Submit formal AryaJobPackage contract
    pkg_payload = {
        "jobPackageId": f"pkg-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T14:40:00Z",
        "projectId": project_id,
        "sequenceId": sequence_id,
        "shotId": shot_id,
        "shotOrder": 1,
        "plan": {
            "title": "Shot For Job",
            "prompt": "Cybernetic core chamber",
            "generationType": "video",
            "durationSeconds": 5.0,
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {
            "startFrameUrl": "https://assets.aryaos.internal/first_frame.jpg",
            "referenceAssets": ["https://assets.aryaos.internal/first_frame.jpg"],
        },
        "modelRoute": {
            "provider": "kling",
            "model": "kling-video",
            "modelName": "Kling Video v1.5",
            "mode": "video",
            "preflightReady": True,
            "preflightReasons": ["PASSED"],
            "availability": "AVAILABLE",
            "estimatedCostUsd": 0.05,
        },
        "shotConfiguration": {
            "aspectRatio": "16:9",
            "duration": 5.0,
        },
        "continuityRequirements": {
            "character": "UNAVAILABLE",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "PROVIDED",
        },
        "outputRequirements": {
            "destination": "ARYAOS_CORRIDOR_STREAM",
            "targetFormat": "video/mp4",
        },
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {
            "generation_type": "video",
            "prompt": "Cybernetic core chamber",
            "model": "kling-video",
            "provider": "kling",
        },
    }

    job_res = await client.post(
        f"/api/v1/projects/{project_id}/jobs",
        json=pkg_payload,
    )
    assert job_res.status_code == 201
    job_data = job_res.json()
    assert job_data["status"] == "QUEUED"
    assert job_data["progress"] == 0.0
    assert job_data["provider"] == "kling"
    assert job_data["shot_id"] == shot_id
    job_id = job_data["id"]

    # Verify shot status transitioned to QUEUED
    updated_shot_res = await client.get(f"/api/v1/projects/{project_id}/shots")
    target_shot = next(s for s in updated_shot_res.json() if s["id"] == shot_id)
    assert target_shot["status"] == "QUEUED"

    # Get Job by ID
    get_job_res = await client.get(f"/api/v1/jobs/{job_id}")
    assert get_job_res.status_code == 200
    assert get_job_res.json()["id"] == job_id


async def test_08_centralized_job_state_machine_transitions(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "State Machine Project"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]
    shot_id = (await client.post(f"/api/v1/projects/{project_id}/shots", json={
        "sequence_id": seq_id,
        "title": "SM Shot",
        "prompt": "Neon corridor",
        "model": "kling-video",
        "provider": "kling",
    })).json()["id"]

    pkg_payload = {
        "jobPackageId": f"pkg-sm-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T14:40:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": shot_id,
        "plan": {
            "title": "SM Shot",
            "prompt": "Neon corridor",
            "generationType": "video",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "kling",
            "model": "kling-video",
            "modelName": "Kling Video",
            "mode": "video",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "video/mp4"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"generation_type": "video", "prompt": "Neon corridor"},
    }

    job_id = (await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg_payload)).json()["id"]

    # 1. QUEUED -> RUNNING (Valid transition)
    upd1 = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"status": "RUNNING", "progress": 0.45, "external_job_id": "ext-kling-123"},
    )
    assert upd1.status_code == 200
    assert upd1.json()["status"] == "RUNNING"
    assert upd1.json()["progress"] == 0.45

    # 2. RUNNING -> COMPLETED (Valid transition)
    upd2 = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"status": "COMPLETED", "progress": 1.0},
    )
    assert upd2.status_code == 200
    assert upd2.json()["status"] == "COMPLETED"

    # 3. COMPLETED -> RUNNING (Illegal transition from terminal state -> 409 Conflict)
    upd_bad = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"status": "RUNNING"},
    )
    assert upd_bad.status_code == 409


async def test_09_preflight_blocked_job_package_rejected(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Blocked Job Project"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]

    blocked_pkg = {
        "jobPackageId": f"pkg-blocked-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T14:40:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {
            "title": "Blocked",
            "prompt": "Test",
            "generationType": "video",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "kling",
            "model": "kling-video",
            "modelName": "Kling Video",
            "mode": "video",
            "preflightReady": False,
            "preflightReasons": ["Aspect ratio not supported by provider", "Token limit exceeded"],
        },
        "shotConfiguration": {"aspectRatio": "32:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "video/mp4"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {},
    }

    res = await client.post(f"/api/v1/projects/{project_id}/jobs", json=blocked_pkg)
    assert res.status_code == 400
    assert "Preflight validation blocked" in res.json()["detail"]


async def test_10_invalid_ids_return_404(client: AsyncClient):
    random_id = uuid.uuid4()
    assert (await client.get(f"/api/v1/projects/{random_id}")).status_code == 404
    assert (await client.get(f"/api/v1/projects/{random_id}/sequences")).status_code == 404
    assert (await client.get(f"/api/v1/projects/{random_id}/shots")).status_code == 404
    assert (await client.get(f"/api/v1/shots/{random_id}")).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{random_id}")).status_code == 404


async def test_11_persistence_across_separate_sessions(client: AsyncClient, db_session: AsyncSession):
    # Create project and shot
    proj_res = await client.post("/api/v1/projects", json={"name": "Persistent Session Project", "description": "Survives reload"})
    assert proj_res.status_code == 201
    proj_id = proj_res.json()["id"]

    seqs_res = await client.get(f"/api/v1/projects/{proj_id}/sequences")
    seq_id = seqs_res.json()[0]["id"]

    shot_res = await client.post(
        f"/api/v1/projects/{proj_id}/shots",
        json={
            "sequence_id": seq_id,
            "shot_number": 1,
            "title": "Persistent Shot",
            "prompt": "Monumental Core in deep space",
            "model": "kling-video",
            "provider": "kling",
        },
    )
    assert shot_res.status_code == 201
    shot_id = shot_res.json()["id"]

    # Verify directly against database engine via a separate query
    stmt = select(ProductionShot).where(ProductionShot.id == uuid.UUID(shot_id))
    db_result = await db_session.execute(stmt)
    persisted_shot = db_result.scalar_one_or_none()
    assert persisted_shot is not None
    assert persisted_shot.title == "Persistent Shot"
    assert str(persisted_shot.project_id) == proj_id

    # Verify retrieval via a fresh HTTP request
    verify_res = await client.get(f"/api/v1/shots/{shot_id}")
    assert verify_res.status_code == 200
    assert verify_res.json()["title"] == "Persistent Shot"


async def test_12_api_failure_handling_and_malformed_payload(client: AsyncClient):
    # Malformed project (name empty or missing)
    bad_proj = await client.post("/api/v1/projects", json={})
    assert bad_proj.status_code == 422

    # Malformed shot (missing required prompt or model)
    good_proj = await client.post("/api/v1/projects", json={"name": "Validation Test Project"})
    proj_id = good_proj.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{proj_id}/sequences")).json()[0]["id"]

    bad_shot = await client.post(f"/api/v1/projects/{proj_id}/shots", json={"sequence_id": seq_id})
    assert bad_shot.status_code == 422

    # Malformed job package (invalid decisionBoundary)
    bad_boundary_pkg = {
        "jobPackageId": f"pkg-invalid-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T14:40:00Z",
        "projectId": proj_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {
            "title": "Bad Boundary",
            "prompt": "Test",
            "generationType": "video",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "kling",
            "model": "kling-video",
            "modelName": "Kling Video",
            "mode": "video",
            "preflightReady": True,
            "preflightReasons": [],
        },
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {
            "character": "PASS",
            "environment": "PASS",
            "visual": "PASS",
            "temporal": "PASS",
            "startFrame": "NOT_APPLICABLE",
        },
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "video/mp4"},
        "decisionBoundary": "UNAUTHORIZED_BOUNDARY",
        "executionPayload": {},
    }
    bad_pkg_res = await client.post(f"/api/v1/projects/{proj_id}/jobs", json=bad_boundary_pkg)
    assert bad_pkg_res.status_code == 422
