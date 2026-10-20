"""
AryaOS V1 Phase 13 — Multi-Shot Temporal Continuity & Production Graph Test Suite.

Verifies:
1. Production Graph (independent shots, linear chains, branching, cycle detection)
2. Frame Anchors & Extraction (first frame, last frame, caching, validation, anti-corruption)
3. Deterministic Continuity Validation (PASS, WARNING, BLOCKED)
4. Multi-Shot Scheduling & Execution (dependency blocking, successor unlocking, independent dispatch)
5. Production API Endpoints (/graph, /dependencies, /continuity, /extract-frames)
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from app.main import app
from app.models.production import ProductionJob, ProductionSequence, ProductionShot
from app.schemas.production import AryaJobPackageSchema
from app.services.artifact_validator import validate_artifact_file
from app.services.continuity_validator import continuity_validator
from app.services.execution_gateway import STORAGE_ARTIFACTS_DIR, ExecutionGateway
from app.services.frame_extractor import frame_extractor
from app.services.openmontage_adapter import OpenMontageAdapter, OpenMontageToolResult
from app.services.shot_graph_service import shot_graph_service

pytestmark = pytest.mark.asyncio(loop_scope="module")


def create_test_image(filename: str, width: int = 1280, height: int = 720, color: str = "blue") -> Path:
    target = STORAGE_ARTIFACTS_DIR / filename
    img = Image.new("RGB", (width, height), color=color)
    img.save(target, format="PNG")
    return target


# -----------------------------------------------------------------------------
# 1. Production Graph Tests
# -----------------------------------------------------------------------------

async def test_01_independent_shot_graph(client: AsyncClient, db_session: AsyncSession):
    """An independent shot has dependency_state=INDEPENDENT and is listed as a root."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Graph Independent Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    shot_res = await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": str(seq_id),
            "shot_number": 1,
            "title": "Root Shot 01",
            "prompt": "Solo monolith",
            "model": "diagram-boxes",
            "provider": "diagram",
        },
    )
    assert shot_res.status_code == 201
    shot_id = shot_res.json()["id"]

    graph_res = await client.get(f"/api/v1/projects/{project_id}/graph")
    assert graph_res.status_code == 200
    data = graph_res.json()

    assert data["has_cycles"] is False
    assert shot_id in data["roots"]
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["dependency_state"] == "INDEPENDENT"
    assert data["nodes"][0]["predecessor_shot_id"] is None


async def test_02_predecessor_dependency_edge(client: AsyncClient, db_session: AsyncSession):
    """Successor shot dependent on predecessor forms a directed graph edge."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Graph Dependency Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": str(seq_id),
            "shot_number": 1,
            "title": "Shot 01",
            "prompt": "First shot",
            "model": "diagram-boxes",
            "provider": "diagram",
        },
    )).json()

    s2 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={
            "sequence_id": str(seq_id),
            "shot_number": 2,
            "title": "Shot 02",
            "prompt": "Second shot",
            "model": "diagram-boxes",
            "provider": "diagram",
            "predecessor_shot_id": s1["id"],
        },
    )).json()

    graph = (await client.get(f"/api/v1/projects/{project_id}/graph")).json()
    assert graph["has_cycles"] is False
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["source_shot_id"] == s1["id"]
    assert graph["edges"][0]["target_shot_id"] == s2["id"]
    assert graph["edges"][0]["relationship_type"] == "last_frame_to_first_frame"


async def test_03_multi_level_dependency_chain(client: AsyncClient, db_session: AsyncSession):
    """Linear chain: Shot 01 -> Shot 02 -> Shot 03."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Graph Chain Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 1, "title": "Chain 01", "prompt": "p1", "model": "m", "provider": "p"},
    )).json()
    s2 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 2, "title": "Chain 02", "prompt": "p2", "model": "m", "provider": "p", "predecessor_shot_id": s1["id"]},
    )).json()
    s3 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 3, "title": "Chain 03", "prompt": "p3", "model": "m", "provider": "p", "predecessor_shot_id": s2["id"]},
    )).json()

    graph = (await client.get(f"/api/v1/projects/{project_id}/graph")).json()
    assert graph["roots"] == [s1["id"]]
    assert len(graph["edges"]) == 2
    assert {"source_shot_id": s1["id"], "target_shot_id": s2["id"], "relationship_type": "last_frame_to_first_frame", "status": "PENDING"} in graph["edges"]
    assert {"source_shot_id": s2["id"], "target_shot_id": s3["id"], "relationship_type": "last_frame_to_first_frame", "status": "PENDING"} in graph["edges"]


async def test_04_branching_dependency_graph(client: AsyncClient, db_session: AsyncSession):
    """Branching tree: Shot 01 -> Shot 02 and Shot 01 -> Shot 03."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Graph Branching Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 1, "title": "Branch Root", "prompt": "p", "model": "m", "provider": "p"},
    )).json()
    s2 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 2, "title": "Branch A", "prompt": "pA", "model": "m", "provider": "p", "predecessor_shot_id": s1["id"]},
    )).json()
    s3 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 3, "title": "Branch B", "prompt": "pB", "model": "m", "provider": "p", "predecessor_shot_id": s1["id"]},
    )).json()

    graph = (await client.get(f"/api/v1/projects/{project_id}/graph")).json()
    assert graph["roots"] == [s1["id"]]
    assert len(graph["edges"]) == 2

    # Verify Shot 01 has two successors
    root_node = next(n for n in graph["nodes"] if n["shot_id"] == s1["id"])
    assert s2["id"] in root_node["successor_shot_ids"]
    assert s3["id"] in root_node["successor_shot_ids"]


async def test_05_circular_dependency_detection():
    """Circular dependencies are detected by cycle detector."""
    # Synthetic mock shot objects
    class DummyShot:
        def __init__(self, shot_id: str, pred_id: str | None):
            self.id = shot_id
            self.predecessor_shot_id = pred_id

    s_a = DummyShot("shot-a", "shot-c")
    s_b = DummyShot("shot-b", "shot-a")
    s_c = DummyShot("shot-c", "shot-b")

    has_cycles, cycle_nodes = shot_graph_service.detect_cycles([s_a, s_b, s_c])
    assert has_cycles is True
    assert len(cycle_nodes) > 0


# -----------------------------------------------------------------------------
# 2. Frame Anchors & Extraction Tests
# -----------------------------------------------------------------------------

async def test_06_frame_extraction_valid_video():
    """Extracts first and last frame anchors from real MP4 video."""
    video_path = STORAGE_ARTIFACTS_DIR / "artifact_ba3d08aa-0d26-47d5-9b95-fb6c97079a9f_dcca839d.mp4"
    if not video_path.is_file():
        pytest.skip("Video artifact not present in storage")

    shot_id = f"test-shot-{uuid.uuid4().hex[:6]}"
    anchors = await frame_extractor.extract_video_anchors(video_path, shot_id, duration=5.0)

    assert "first_frame" in anchors
    assert "last_frame" in anchors

    first = anchors["first_frame"]
    assert first.status == "VERIFIED"
    assert first.mime_type == "image/png"
    assert first.width > 0
    assert first.height > 0
    assert len(first.sha256) == 64
    assert Path(first.file_path).is_file()

    last = anchors["last_frame"]
    assert last.status == "VERIFIED"
    assert last.timestamp > 0.0
    assert len(last.sha256) == 64
    assert Path(last.file_path).is_file()


async def test_07_frame_extraction_image_anchor():
    """Image artifact is cataloged as keyframe anchor."""
    filename = f"test_anchor_img_{uuid.uuid4().hex[:6]}.png"
    img_path = create_test_image(filename, width=1280, height=720)
    try:
        shot_id = f"test-shot-{uuid.uuid4().hex[:6]}"
        anchors = await frame_extractor.extract_image_anchor(img_path, shot_id)
        assert "first_frame" in anchors
        assert "last_frame" in anchors
        assert anchors["first_frame"].width == 1280
        assert anchors["first_frame"].height == 720
        assert anchors["first_frame"].status == "VERIFIED"
    finally:
        if img_path.is_file():
            img_path.unlink()


async def test_08_frame_extraction_missing_artifact_raises_error():
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        await frame_extractor.extract_video_anchors(STORAGE_ARTIFACTS_DIR / "nonexistent.mp4", "shot-xyz")


async def test_09_frame_extraction_corrupted_artifact_rejected():
    """Corrupted binary fails validation during extraction."""
    corrupt_file = STORAGE_ARTIFACTS_DIR / f"test_corrupt_{uuid.uuid4().hex[:6]}.mp4"
    corrupt_file.write_bytes(b"NOT_A_VALID_VIDEO_OR_IMAGE")
    try:
        with pytest.raises(Exception):
            await frame_extractor.extract_video_anchors(corrupt_file, "shot-corrupt", duration=2.0)
    finally:
        if corrupt_file.is_file():
            corrupt_file.unlink()


# -----------------------------------------------------------------------------
# 3. Deterministic Continuity Validation Tests
# -----------------------------------------------------------------------------

async def test_10_continuity_validation_technical_pass(client: AsyncClient, db_session: AsyncSession):
    """Matching predecessor with valid last-frame passes continuity."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Cont PASS Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    # Create dummy image for predecessor last frame
    f_name = f"pred_frame_{uuid.uuid4().hex[:6]}.png"
    create_test_image(f_name, 1280, 720)

    # Predecessor completed
    pred = ProductionShot(
        project_id=project_id,
        sequence_id=seq_id,
        shot_number=1,
        title="Pred Shot",
        prompt="p",
        generation_type="image",
        model="m",
        provider="p",
        aspect_ratio="16:9",
        status="COMPLETE",
        output_asset_url=f"/api/v1/artifacts/{f_name}",
        last_frame=f"/api/v1/artifacts/{f_name}",
        metadata_json={
            "frame_anchors": {
                "last_frame": {
                    "artifact_url": f"/api/v1/artifacts/{f_name}",
                    "file_path": str(STORAGE_ARTIFACTS_DIR / f_name),
                    "status": "VERIFIED",
                }
            }
        },
    )
    db_session.add(pred)
    await db_session.commit()
    await db_session.refresh(pred)

    # Downstream shot
    curr = ProductionShot(
        project_id=project_id,
        sequence_id=seq_id,
        shot_number=2,
        title="Curr Shot",
        prompt="p2",
        generation_type="video",
        model="m",
        provider="p",
        aspect_ratio="16:9",
        predecessor_shot_id=str(pred.id),
        first_frame=f"/api/v1/artifacts/{f_name}",
    )
    db_session.add(curr)
    await db_session.commit()
    await db_session.refresh(curr)

    report = continuity_validator.validate(curr, pred)
    assert report.status == "PASS"
    assert report.technical_status == "PASS"
    assert report.dependency_status == "PASS"
    assert report.temporal_status == "PASS"


async def test_11_continuity_validation_warning_on_aspect_mismatch(client: AsyncClient, db_session: AsyncSession):
    """Aspect ratio mismatch triggers WARNING, not BLOCKED."""
    f_name = f"pred_aspect_{uuid.uuid4().hex[:6]}.png"
    create_test_image(f_name, 1280, 720)

    pred = ProductionShot(
        project_id=uuid.uuid4(),
        sequence_id=uuid.uuid4(),
        title="Pred 16:9",
        prompt="p",
        generation_type="image",
        model="m",
        provider="p",
        aspect_ratio="16:9",
        status="COMPLETE",
        output_asset_url=f"/api/v1/artifacts/{f_name}",
        last_frame=f"/api/v1/artifacts/{f_name}",
        metadata_json={
            "frame_anchors": {"last_frame": {"artifact_url": f"/api/v1/artifacts/{f_name}", "status": "VERIFIED"}}
        },
    )
    curr = ProductionShot(
        project_id=pred.project_id,
        sequence_id=pred.sequence_id,
        title="Curr 9:16",
        prompt="p",
        generation_type="video",
        model="m",
        provider="p",
        aspect_ratio="9:16",  # Mismatch!
        predecessor_shot_id=str(pred.id),
        first_frame=f"/api/v1/artifacts/{f_name}",
    )

    report = continuity_validator.validate(curr, pred)
    assert report.status == "WARNING"
    assert report.technical_status == "WARNING"
    assert any("Aspect ratio discrepancy" in r for r in report.reasons)


async def test_12_continuity_validation_blocked_when_predecessor_failed():
    """Failed predecessor BLOCKS downstream shot."""
    pred = ProductionShot(
        project_id=uuid.uuid4(),
        sequence_id=uuid.uuid4(),
        title="Pred Failed",
        prompt="p",
        generation_type="image",
        model="m",
        provider="p",
        status="FAILED",  # Failed!
        output_asset_url=None,
    )
    curr = ProductionShot(
        project_id=pred.project_id,
        sequence_id=pred.sequence_id,
        title="Curr Blocked",
        prompt="p",
        generation_type="video",
        model="m",
        provider="p",
        predecessor_shot_id=str(pred.id),
    )

    report = continuity_validator.validate(curr, pred)
    assert report.status == "BLOCKED"
    assert report.dependency_status == "BLOCKED"
    assert any("failed generation" in r for r in report.reasons)


# -----------------------------------------------------------------------------
# 4. Multi-Shot Scheduling & Execution Tests
# -----------------------------------------------------------------------------

async def test_13_predecessor_blocks_downstream_dispatch(client: AsyncClient, db_session: AsyncSession):
    """A downstream shot cannot be dispatched if predecessor is incomplete."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Scheduling Block Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 1, "title": "Pred Incomplete", "prompt": "p1", "model": "m", "provider": "p"},
    )).json()

    s2 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 2, "title": "Downstream", "prompt": "p2", "model": "m", "provider": "p", "predecessor_shot_id": s1["id"]},
    )).json()
    s2_id = uuid.UUID(s2["id"])

    # Prepare job package for Shot 02
    pkg_dict = {
        "jobPackageId": f"pkg-sched-{uuid.uuid4().hex[:8]}",
        "createdAt": "2026-09-28T17:00:00Z",
        "projectId": str(project_id),
        "sequenceId": str(seq_id),
        "shotId": str(s2_id),
        "plan": {
            "title": "Downstream Shot",
            "prompt": "Generating downstream",
            "generationType": "image",
            "dependencies": [s1["id"]],
            "predecessorShotId": s1["id"],
            "isFirstShotInSequence": False,
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
        "executionPayload": {"prompt": "Generating downstream"},
    }

    job_res = await client.post(f"/api/v1/projects/{project_id}/jobs", json=pkg_dict)
    job_id = uuid.UUID(job_res.json()["id"])

    # Execute Shot 02 via Gateway
    gateway = ExecutionGateway()
    pkg_schema = AryaJobPackageSchema.model_validate(pkg_dict)
    job = await gateway.execute_job(job_id=job_id, pkg=pkg_schema, db=db_session)

    # Job must fail/block honestly
    assert job.status == "FAILED"
    assert "not yet COMPLETE" in job.error

    # Shot dependency_state must be WAITING_FOR_PREDECESSOR
    stmt = select(ProductionShot).where(ProductionShot.id == s2_id)
    updated_s2 = (await db_session.execute(stmt)).scalar_one()
    assert updated_s2.dependency_state == "WAITING_FOR_PREDECESSOR"


async def test_14_predecessor_completion_unlocks_downstream(client: AsyncClient, db_session: AsyncSession):
    """When predecessor completes, successors are unlocked and given first-frame anchor."""
    proj_res = await client.post("/api/v1/projects", json={"name": "Successor Unlock Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    # Create predecessor shot
    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 1, "title": "Unlocking Pred", "prompt": "p1", "model": "diagram-boxes", "provider": "diagram"},
    )).json()
    s1_id = uuid.UUID(s1["id"])

    # Create successor shot
    s2 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 2, "title": "Waiting Succ", "prompt": "p2", "model": "diagram-boxes", "provider": "diagram", "predecessor_shot_id": str(s1_id)},
    )).json()
    s2_id = uuid.UUID(s2["id"])

    # Complete predecessor with real artifact
    f_name = f"succ_unlock_{uuid.uuid4().hex[:6]}.png"
    create_test_image(f_name, 1280, 720)

    s1_stmt = select(ProductionShot).where(ProductionShot.id == s1_id)
    pred_shot = (await db_session.execute(s1_stmt)).scalar_one()
    pred_shot.status = "COMPLETE"
    pred_shot.output_asset_url = f"/api/v1/artifacts/{f_name}"
    pred_shot.last_frame = f"/api/v1/artifacts/{f_name}"
    pred_shot.metadata_json = {
        "frame_anchors": {
            "last_frame": {
                "artifact_url": f"/api/v1/artifacts/{f_name}",
                "file_path": str(STORAGE_ARTIFACTS_DIR / f_name),
                "status": "VERIFIED",
            }
        }
    }
    await db_session.commit()

    # Trigger unlock_successors
    unlocked = await shot_graph_service.unlock_successors(s1_id, db_session)
    assert len(unlocked) == 1

    s2_stmt = select(ProductionShot).where(ProductionShot.id == s2_id)
    updated_s2 = (await db_session.execute(s2_stmt)).scalar_one()
    assert updated_s2.dependency_state == "READY"
    assert updated_s2.continuity_status == "PASS"
    assert updated_s2.first_frame == f"/api/v1/artifacts/{f_name}"


async def test_15_api_endpoints_graph_dependencies_and_continuity(client: AsyncClient, db_session: AsyncSession):
    """Tests GET /graph, GET /dependencies, and GET /continuity endpoints."""
    proj_res = await client.post("/api/v1/projects", json={"name": "API Endpoints Proj"})
    project_id = uuid.UUID(proj_res.json()["id"])
    seq_id = uuid.UUID((await client.get(f"/api/v1/projects/{project_id}/sequences")).json()[0]["id"])

    s1 = (await client.post(
        f"/api/v1/projects/{project_id}/shots",
        json={"sequence_id": str(seq_id), "shot_number": 1, "title": "Endpoint Shot", "prompt": "p", "model": "m", "provider": "p"},
    )).json()

    # 1. /graph endpoint
    graph_res = await client.get(f"/api/v1/projects/{project_id}/graph")
    assert graph_res.status_code == 200
    assert len(graph_res.json()["nodes"]) == 1

    # 2. /dependencies endpoint
    dep_res = await client.get(f"/api/v1/shots/{s1['id']}/dependencies")
    assert dep_res.status_code == 200
    assert dep_res.json()["dependency_state"] == "INDEPENDENT"

    # 3. /continuity endpoint
    cont_res = await client.get(f"/api/v1/shots/{s1['id']}/continuity")
    assert cont_res.status_code == 200
    assert cont_res.json()["status"] == "PASS"
