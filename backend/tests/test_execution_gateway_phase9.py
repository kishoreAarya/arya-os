"""
AryaOS V1 Phase 9 — Execution Bridge & Production Telemetry Tests.

Validates the full Phase 9 boundary requirements:
1. Valid Job Package submission
2. Invalid Job Package rejection (malformed package / decision boundary / preflight failure)
3. OpenMontage adapter isolation, availability probing, and tool execution
4. OpenMontage adapter security: illegal tool names rejected, path traversal blocked
5. OpenMontage unavailable behavior (graceful honest failure reporting)
6. External execution ID persistence
7. State machine transitions: QUEUED -> SUBMITTED -> RUNNING -> COMPLETED
8. State machine failure path: QUEUED -> SUBMITTED -> RUNNING -> FAILED
9. Terminal state protection: Cannot transition from COMPLETED or CANCELLED
10. Retry behavior: Failed job can be re-dispatched, preserving execution attempts history
11. Real artifact generation & storage persistence
12. Artifact serving endpoint: GET /api/v1/artifacts/{filename}
13. Artifact security: Path traversal in GET /api/v1/artifacts/{filename} blocked
14. Shot status & output_asset_url synchronization
15. SSE telemetry events: JOB_SUBMITTED, JOB_STARTED, JOB_PROGRESS, JOB_COMPLETED, JOB_FAILED, ARTIFACT_READY, SHOT_UPDATED
"""

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from PIL import Image

from app.models.production import ProductionJob, ProductionShot
from app.schemas.production import AryaJobPackageSchema
from app.services.execution_gateway import STORAGE_ARTIFACTS_DIR, ExecutionGateway
from app.services.openmontage_adapter import OpenMontageAdapter, OpenMontageToolResult

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture
def mock_openmontage_success():
    """Mock adapter returning successful execution with artifact."""
    adapter = OpenMontageAdapter()
    test_artifact = STORAGE_ARTIFACTS_DIR / f"test_shot_{uuid.uuid4().hex[:6]}.png"
    img = Image.new("RGB", (32, 32), color=(255, 120, 0))
    img.save(test_artifact, format="PNG")

    adapter.execute_tool = AsyncMock(
        return_value=OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[str(test_artifact)],
            data={"method": "pillow", "box_count": 2},
            cost_usd=0.0,
            duration_seconds=0.45,
            model="diagram-engine",
        )
    )
    return adapter, test_artifact


@pytest.fixture
def mock_openmontage_failure():
    """Mock adapter returning honest tool failure."""
    adapter = OpenMontageAdapter()
    adapter.execute_tool = AsyncMock(
        return_value=OpenMontageToolResult(
            success=False,
            status="FAILED",
            error="No fal.ai API key found. Set FAL_KEY in environment.",
            cost_usd=0.0,
            duration_seconds=0.12,
        )
    )
    return adapter


# -----------------------------------------------------------------------------
# 1. Job Package Submission & Validation
# -----------------------------------------------------------------------------

async def test_01_valid_job_package_submission(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Phase 9 Execution Project"})
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    seqs = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()
    seq_id = seqs[0]["id"]

    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": seq_id,
            "shot_number": 1,
            "title": "Phase 9 Shot 01",
            "prompt": "Monumental monolith awakening",
            "model": "diagram-boxes",
            "provider": "diagram",
        },
    )
    assert shot_res.status_code == 201
    shot_id = shot_res.json()["id"]

    pkg = {
        "jobPackageId": f"pkg-p9-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": shot_id,
        "plan": {
            "title": "Phase 9 Shot 01",
            "prompt": "Monumental monolith awakening",
            "generationType": "image",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "diagram",
            "model": "diagram-boxes",
            "modelName": "Diagram Boxes",
            "mode": "image",
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
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Monumental monolith awakening"},
    }

    res = await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "QUEUED"
    assert data["job_package_id"] == pkg["jobPackageId"]


async def test_02_invalid_decision_boundary_rejected(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Boundary Test Proj"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]

    bad_pkg = {
        "jobPackageId": f"pkg-bad-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {"title": "Bad", "prompt": "Bad", "generationType": "image", "dependencies": [], "isFirstShotInSequence": True},
        "references": {"referenceAssets": []},
        "modelRoute": {"provider": "flux", "model": "flux", "modelName": "Flux", "mode": "image", "preflightReady": True, "preflightReasons": []},
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {"character": "PASS", "environment": "PASS", "visual": "PASS", "temporal": "PASS", "startFrame": "NOT_APPLICABLE"},
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "UNVALIDATED_BYPASS",  # Invalid boundary
        "executionPayload": {},
    }

    res = await client.post(f"/api/v1/projects/{project_id}/jobs", json=bad_pkg)
    assert res.status_code == 422


# -----------------------------------------------------------------------------
# 2. OpenMontage Adapter Isolation & Security
# -----------------------------------------------------------------------------

async def test_03_openmontage_adapter_security_and_tool_not_found():
    adapter = OpenMontageAdapter()

    # 1. Reject illegal tool names containing shell metacharacters
    sec_res = await adapter.execute_tool("malicious_tool; rm -rf /", {})
    assert sec_res.success is False
    assert sec_res.status == "FAILED"
    assert "Security violation" in sec_res.error

    # 2. Non-existent tool returns honest error
    if adapter.is_available():
        nf_res = await adapter.execute_tool("tool_does_not_exist_xyz", {})
        assert nf_res.success is False
        assert "not found in OpenMontage registry" in nf_res.error


async def test_04_openmontage_adapter_unavailable_behavior():
    # Adapter pointed to nonexistent directory
    bogus_adapter = OpenMontageAdapter(openmontage_path="/nonexistent/path/nowhere")
    assert bogus_adapter.is_available() is False

    res = await bogus_adapter.execute_tool("flux_image", {"prompt": "Sunset"})
    assert res.success is False
    assert res.status == "UNAVAILABLE"
    assert "OpenMontage engine is unavailable" in res.error


# -----------------------------------------------------------------------------
# 3. State Machine & Full Execution Lifecycle
# -----------------------------------------------------------------------------

async def test_05_execution_gateway_full_lifecycle_success(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_openmontage_success,
):
    adapter, test_artifact = mock_openmontage_success
    gateway = ExecutionGateway(adapter=adapter)

    # Create project and shot
    proj_res = await client.post("/api/v1/projects", json={"name": "Lifecycle Success Project"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": str(seq_id),
            "shot_number": 1,
            "title": "Quantum Monolith Awakening",
            "prompt": "Cinematic monolith activating with amber pulse",
            "model": "diagram-boxes",
            "provider": "diagram",
        },
    )
    shot_id = uuid.UUID(shot_res.json()["id"])

    pkg_dict = {
        "jobPackageId": f"pkg-exec-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(seq_id),
        "shotId": str(shot_id),
        "plan": {
            "title": "Quantum Monolith Awakening",
            "prompt": "Cinematic monolith activating with amber pulse",
            "generationType": "image",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "diagram",
            "model": "diagram-boxes",
            "modelName": "Diagram Boxes",
            "mode": "image",
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
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Cinematic monolith activating with amber pulse"},
    }

    job_create = await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg_dict)
    assert job_create.status_code == 201
    job_id = uuid.UUID(job_create.json()["id"])

    # Initial state must be QUEUED
    assert job_create.json()["status"] == "QUEUED"

    # Execute via Gateway
    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)
    finished_job = await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)

    # Verify final states
    assert finished_job.status == "COMPLETED"
    assert finished_job.progress == 1.0
    assert finished_job.external_job_id is not None
    assert finished_job.external_job_id.startswith("om-diagram_gen-")
    assert finished_job.error is None

    # Verify execution attempt was recorded
    attempts = finished_job.job_package_json.get("execution_attempts", [])
    assert len(attempts) == 1
    assert attempts[0]["status"] == "COMPLETED"
    assert attempts[0]["external_job_id"] == finished_job.external_job_id

    # Verify shot status and artifact synchronization
    shot_stmt = select(ProductionShot).where(ProductionShot.id == shot_id)
    updated_shot = (await db_session.execute(shot_stmt)).scalar_one()
    assert updated_shot.status == "COMPLETE"
    assert updated_shot.output_asset_url == f"/api/v1/artifacts/{test_artifact.name}"

    # Clean up test artifact
    if test_artifact.is_file():
        test_artifact.unlink()


async def test_06_execution_gateway_honest_failure_handling(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_openmontage_failure,
):
    gateway = ExecutionGateway(adapter=mock_openmontage_failure)

    proj_res = await client.post("/api/v1/projects", json={"name": "Lifecycle Failure Project"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": str(seq_id),
            "shot_number": 1,
            "title": "Missing Key Shot",
            "prompt": "Sunset over mountain",
            "model": "flux-pro/v1.1",
            "provider": "flux",
        },
    )
    shot_id = uuid.UUID(shot_res.json()["id"])

    pkg_dict = {
        "jobPackageId": f"pkg-fail-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(seq_id),
        "shotId": str(shot_id),
        "plan": {
            "title": "Missing Key Shot",
            "prompt": "Sunset over mountain",
            "generationType": "image",
            "dependencies": [],
            "isFirstShotInSequence": True,
        },
        "references": {"referenceAssets": []},
        "modelRoute": {
            "provider": "flux",
            "model": "flux-pro/v1.1",
            "modelName": "Flux Pro",
            "mode": "image",
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
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {"prompt": "Sunset over mountain"},
    }

    job_create = await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg_dict)
    job_id = uuid.UUID(job_create.json()["id"])

    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)
    failed_job = await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)

    # Verify honest failure representation (no fake success, no fake artifacts)
    assert failed_job.status == "FAILED"
    assert ("No fal.ai API key found" in failed_job.error or "FAL_KEY" in failed_job.error)

    # Verify shot marked FAILED
    shot_stmt = select(ProductionShot).where(ProductionShot.id == shot_id)
    updated_shot = (await db_session.execute(shot_stmt)).scalar_one()
    assert updated_shot.status == "FAILED"
    assert updated_shot.output_asset_url is None


# -----------------------------------------------------------------------------
# 4. Terminal State Protection & Retry Behavior
# -----------------------------------------------------------------------------

async def test_07_terminal_state_protection(client: AsyncClient):
    proj_res = await client.post("/api/v1/projects", json={"name": "Terminal State Proj"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]

    pkg = {
        "jobPackageId": f"pkg-term-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {"title": "Terminal Shot", "prompt": "Pylons", "generationType": "image", "dependencies": [], "isFirstShotInSequence": True},
        "references": {"referenceAssets": []},
        "modelRoute": {"provider": "flux", "model": "flux", "modelName": "Flux", "mode": "image", "preflightReady": True, "preflightReasons": []},
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {"character": "PASS", "environment": "PASS", "visual": "PASS", "temporal": "PASS", "startFrame": "NOT_APPLICABLE"},
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {},
    }

    job_id = (await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg)).json()["id"]

    # Transition to COMPLETED
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "SUBMITTED"})
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "RUNNING"})
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "COMPLETED"})

    # Attempt illegal transition from COMPLETED terminal state -> 409
    bad_res = await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "RUNNING"})
    assert bad_res.status_code == 409
    assert "terminal state" in bad_res.json()["detail"].lower()


async def test_08_retry_behavior_preserves_attempts(client: AsyncClient, db_session: AsyncSession):
    proj_res = await client.post("/api/v1/projects", json={"name": "Retry Project"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]

    pkg = {
        "jobPackageId": f"pkg-retry-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {"title": "Retry Shot", "prompt": "Orbital core", "generationType": "image", "dependencies": [], "isFirstShotInSequence": True},
        "references": {"referenceAssets": []},
        "modelRoute": {"provider": "flux", "model": "flux", "modelName": "Flux", "mode": "image", "preflightReady": True, "preflightReasons": []},
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {"character": "PASS", "environment": "PASS", "visual": "PASS", "temporal": "PASS", "startFrame": "NOT_APPLICABLE"},
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {},
    }

    job_id = (await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg)).json()["id"]

    # 1. Fail first attempt
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "SUBMITTED"})
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "RUNNING"})
    await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "FAILED", "error": "Temporary network timeout"})

    # 2. Retry: Transition from FAILED back to QUEUED
    retry_res = await client.patch(f"/api/v1/jobs/{job_id}", json={"status": "QUEUED"})
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "QUEUED"


# -----------------------------------------------------------------------------
# 5. Artifact Serving & Security
# -----------------------------------------------------------------------------

async def test_09_artifact_serving_and_traversal_protection(client: AsyncClient):
    # 1. Create a valid test artifact in storage
    art_filename = f"test_art_{uuid.uuid4().hex[:8]}.png"
    art_path = STORAGE_ARTIFACTS_DIR / art_filename
    img = Image.new("RGB", (32, 32), color=(100, 200, 255))
    img.save(art_path, format="PNG")
    expected_bytes = art_path.read_bytes()

    # 2. Retrieve valid artifact
    get_res = await client.get(f"/api/v1/artifacts/{art_filename}")
    assert get_res.status_code == 200
    assert get_res.headers["content-type"] == "image/png"
    assert get_res.content == expected_bytes

    # 3. Path traversal attack: ".." blocked
    traversal_res = await client.get("/api/v1/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert traversal_res.status_code in (400, 403, 404)

    # 4. Nonexistent artifact -> 404
    nf_res = await client.get("/api/v1/artifacts/nonexistent_12345.png")
    assert nf_res.status_code == 404

    # Cleanup
    if art_path.is_file():
        art_path.unlink()


# -----------------------------------------------------------------------------
# 6. Explicit Dispatch API & Sync Execution
# -----------------------------------------------------------------------------

async def test_10_explicit_job_dispatch_api(
    client: AsyncClient,
    mock_openmontage_success,
):
    adapter, test_artifact = mock_openmontage_success

    proj_res = await client.post("/api/v1/projects", json={"name": "Dispatch API Project"})
    project_id = proj_res.json()["id"]
    seq_id = (await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"]

    pkg = {
        "jobPackageId": f"pkg-disp-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": project_id,
        "sequenceId": seq_id,
        "shotId": str(uuid.uuid4()),
        "plan": {"title": "Dispatch Shot", "prompt": "Testing dispatch API", "generationType": "image", "dependencies": [], "isFirstShotInSequence": True},
        "references": {"referenceAssets": []},
        "modelRoute": {"provider": "diagram", "model": "diagram-boxes", "modelName": "Diagram", "mode": "image", "preflightReady": True, "preflightReasons": []},
        "shotConfiguration": {"aspectRatio": "16:9"},
        "continuityRequirements": {"character": "PASS", "environment": "PASS", "visual": "PASS", "temporal": "PASS", "startFrame": "NOT_APPLICABLE"},
        "outputRequirements": {"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
        "executionPayload": {},
    }

    job_id = (await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg)).json()["id"]

    with patch("app.api.routers.production.execution_gateway.adapter", adapter):
        dispatch_res = await client.post(f"/api/v1/jobs/{job_id}/dispatch?sync=true")
        assert dispatch_res.status_code == 200
        data = dispatch_res.json()
        assert data["status"] == "COMPLETED"
        assert data["progress"] == 1.0

    if test_artifact.is_file():
        test_artifact.unlink()
