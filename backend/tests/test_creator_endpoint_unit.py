"""
Unit tests for Creator Mode router (/creator/capabilities, /creator/generate, /creator/jobs, /creator/history).
"""

import uuid
import pytest
from httpx import AsyncClient

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
