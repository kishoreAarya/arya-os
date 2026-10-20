"""
Unit tests for Creator Mode router (/creator/capabilities, /creator/generate, /creator/jobs, /creator/history).
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Uses conftest.py module-scoped fixtures (client, db_session)
pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_creator_capabilities_returns_manifest(client: AsyncClient):
    resp = await client.get("/creator/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "generation_types" in data
    assert "aspect_ratios" in data
    assert "resolutions" in data
    assert "durations" in data
    assert "models" in data

    # Check generation types
    gen_type_ids = [t["id"] for t in data["generation_types"]]
    assert "image" in gen_type_ids
    assert "video" in gen_type_ids
    assert "image_to_video" in gen_type_ids

    # Check models for image and video
    assert len(data["models"]["image"]) > 0
    assert len(data["models"]["video"]) > 0
    assert len(data["models"]["image_to_video"]) > 0


async def test_creator_capabilities_end_frame_is_false(client: AsyncClient):
    """Verify that end_frame is FALSE for all current models in V1 backend."""
    resp = await client.get("/creator/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    for category in ["image", "video", "image_to_video"]:
        for m in data["models"][category]:
            assert m["end_frame"] is False, f"Model {m['name']} should not claim end_frame support in V1"


async def test_creator_capabilities_start_frame_for_image_to_video(client: AsyncClient):
    """Verify start_frame is True for image_to_video models like Kling."""
    resp = await client.get("/creator/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    kling_models = [m for m in data["models"]["image_to_video"] if "kling" in m["name"].lower()]
    assert len(kling_models) > 0
    assert kling_models[0]["start_frame"] is True


async def test_creator_generate_requires_non_empty_prompt(client: AsyncClient):
    resp = await client.post(
        "/creator/generate",
        json={
            "generation_type": "image",
            "prompt": "   ",
        },
    )
    assert resp.status_code == 422


async def test_creator_image_to_video_requires_start_frame(client: AsyncClient):
    resp = await client.post(
        "/creator/generate",
        json={
            "generation_type": "image_to_video",
            "prompt": "Animate camera panning slowly",
        },
    )
    assert resp.status_code == 422
    assert "start frame" in resp.text.lower()


async def test_creator_job_not_found(client: AsyncClient):
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/creator/jobs/{fake_id}")
    assert resp.status_code == 404


async def test_creator_history_endpoint(client: AsyncClient):
    resp = await client.get("/creator/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_creator_history_pagination_limits(client: AsyncClient):
    """Verify limit parameter bounds (ge=1, le=100) and error handling."""
    # Valid limits
    r1 = await client.get("/creator/history?limit=1")
    assert r1.status_code == 200

    r100 = await client.get("/creator/history?limit=100")
    assert r100.status_code == 200

    # Invalid limits: le=100
    r101 = await client.get("/creator/history?limit=101")
    assert r101.status_code == 422

    # Invalid limits: ge=1
    r0 = await client.get("/creator/history?limit=0")
    assert r0.status_code == 422

    r_neg = await client.get("/creator/history?limit=-1")
    assert r_neg.status_code == 422

    r_huge = await client.get("/creator/history?limit=9999999")
    assert r_huge.status_code == 422


async def test_creator_history_batch_resolution(client: AsyncClient, db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that multiple history items are correctly populated without N+1 query errors."""
    import json
    from app.models.core import WorkflowRun
    from app.models.enums import WorkflowMode, WorkflowStatus
    from app.models.system import SystemLog
    from app.models.media import Asset

    run_id1 = uuid.uuid4()
    run_id2 = uuid.uuid4()

    run1 = WorkflowRun(
        id=run_id1,
        project_id=test_project,
        topic="Test Run 1 topic",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
        total_cost_usd=0.05,
    )
    run2 = WorkflowRun(
        id=run_id2,
        project_id=test_project,
        topic="Test Run 2 topic",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
        total_cost_usd=0.10,
    )
    db_session.add_all([run1, run2])

    log1 = SystemLog(
        workflow_run_id=run_id1,
        event_type="CreatorGenerationResult",
        message=json.dumps({
            "asset_url": "https://example.com/asset1.png",
            "generation_type": "image",
            "provider": "replicate",
            "model": "flux-schnell",
        }),
    )
    asset2 = Asset(
        workflow_run_id=run_id2,
        storage_path="/storage/test_video.mp4",
        asset_type="video",
        provider_name="kling",
    )
    db_session.add_all([log1, asset2])
    await db_session.commit()

    resp = await client.get("/creator/history?limit=10")
    assert resp.status_code == 200
    items = resp.json()
    item_map = {item["job_id"]: item for item in items}

    assert str(run_id1) in item_map
    assert item_map[str(run_id1)]["asset_url"] == "https://example.com/asset1.png"
    assert item_map[str(run_id1)]["prompt"] == "Test Run 1 topic"

    assert str(run_id2) in item_map
    assert item_map[str(run_id2)]["asset_url"] == "/storage/test_video.mp4"
    assert item_map[str(run_id2)]["provider"] == "kling"

    # Clean up Asset record before test_project fixture cascades deletion
    await db_session.delete(asset2)
    await db_session.commit()


async def test_creator_job_state_reconstruction_and_caching(client: AsyncClient, db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that a job not in _ACTIVE_JOBS is reconstructed from DB and cached into _ACTIVE_JOBS."""
    from app.api.routers.creator import _ACTIVE_JOBS
    from app.models.core import WorkflowRun
    from app.models.enums import WorkflowMode, WorkflowStatus

    run_id = uuid.uuid4()
    job_id = str(run_id)

    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Reconstruction test prompt",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.COMPLETED,
        current_stage="completed",
        total_cost_usd=0.02,
    )
    db_session.add(run)
    await db_session.commit()

    # Ensure not in memory cache
    _ACTIVE_JOBS.pop(job_id, None)

    # Fetch status: should reconstruct from DB
    resp = await client.get(f"/creator/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "completed"
    assert data["prompt"] == "Reconstruction test prompt"

    # Should now be cached in _ACTIVE_JOBS for fast polling
    assert job_id in _ACTIVE_JOBS
    assert _ACTIVE_JOBS[job_id]["status"] == "completed"


async def test_creator_job_interrupted_stale_recovery(client: AsyncClient, db_session: AsyncSession, test_project: uuid.UUID):
    """Verify that an interrupted in-progress job (>15m) from a crashed process is marked failed on status lookup."""
    from datetime import datetime, timezone, timedelta
    from app.api.routers.creator import _ACTIVE_JOBS, _RUNNING_JOB_IDS
    from app.models.core import WorkflowRun
    from app.models.enums import WorkflowMode, WorkflowStatus

    run_id = uuid.uuid4()
    job_id = str(run_id)

    stale_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
    run = WorkflowRun(
        id=run_id,
        project_id=test_project,
        topic="Stale job test prompt",
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
        current_stage="image_generation",
        started_at=stale_start,
    )
    db_session.add(run)
    await db_session.commit()

    # Ensure not running in current process
    _ACTIVE_JOBS.pop(job_id, None)
    _RUNNING_JOB_IDS.discard(job_id)

    resp = await client.get(f"/creator/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "interrupted" in data["failure_reason"].lower() or "timed out" in data["failure_reason"].lower()
