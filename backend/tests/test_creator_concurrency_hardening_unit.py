"""
Security regression unit tests for:
creator-unbounded-background-task-exhaustion (CWE-400)

Verifies:
1. Concurrency is strictly bounded (max_concurrent).
2. Capacity rejection returns HTTP 429 with Retry-After header.
3. Concurrent admission race cannot exceed configured concurrency limit.
4. Concurrency slot is released on success.
5. Concurrency slot is released on exception.
6. Concurrency slot is released on cancellation.
7. _ACTIVE_JOBS memory is bounded with LRU terminal eviction (active jobs never evicted).
8. Existing creator generation and polling behaviors are fully preserved.
"""

import asyncio
from unittest.mock import AsyncMock, patch
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routers.creator import (
    _ACTIVE_JOBS,
    _RUNNING_JOB_IDS,
    _prune_active_jobs_cache,
    _release_creator_concurrency_slot,
)
from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.main import app
from app.models.core import Project, WorkflowRun
from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def clean_creator_concurrency_state():
    """Ensure clean concurrency state and restore settings before and after each test."""
    settings = get_settings()
    orig_max = settings.creator_max_concurrent_jobs
    orig_retention = settings.creator_active_jobs_retention_limit
    orig_key = settings.arya_api_key

    if not settings.arya_api_key:
        settings.arya_api_key = "test-arya-api-key"

    _RUNNING_JOB_IDS.clear()
    _ACTIVE_JOBS.clear()

    yield

    _RUNNING_JOB_IDS.clear()
    _ACTIVE_JOBS.clear()
    settings.creator_max_concurrent_jobs = orig_max
    settings.creator_active_jobs_retention_limit = orig_retention
    settings.arya_api_key = orig_key


async def test_creator_concurrency_is_bounded(client: AsyncClient):
    """Test 1: System never allows more than configured number of creator jobs executing simultaneously."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 3

    current_running = 0
    max_observed_concurrent = 0
    release_event = asyncio.Event()

    async def mock_background(job_id, run_id, payload):
        nonlocal current_running, max_observed_concurrent
        current_running += 1
        if current_running > max_observed_concurrent:
            max_observed_concurrent = current_running
        await release_event.wait()
        current_running -= 1

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=mock_background):
        tasks = []
        for i in range(10):
            payload = {
                "generation_type": "image",
                "prompt": f"Test bounded concurrency prompt {i}",
            }
            tasks.append(client.post("/creator/generate", json=payload))

        responses = await asyncio.gather(*tasks)

        # Allow scheduled background tasks to start
        await asyncio.sleep(0.05)

        # Concurrency must never exceed configured maximum of 3
        assert max_observed_concurrent <= 3
        accepted = [r for r in responses if r.status_code == 202]
        rejected = [r for r in responses if r.status_code == 429]
        assert len(accepted) == 3
        assert len(rejected) == 7

        release_event.set()
        await asyncio.sleep(0.05)


async def test_creator_capacity_rejection_http_429(client: AsyncClient):
    """Test 2: When capacity is full, immediate HTTP 429 is returned with Retry-After header and no background task created."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 2

    hold_event = asyncio.Event()
    launched_tasks = 0

    async def mock_background(job_id, run_id, payload):
        nonlocal launched_tasks
        launched_tasks += 1
        await hold_event.wait()

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=mock_background):
        # Fill capacity (2 slots)
        r1 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Job 1"})
        r2 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Job 2"})
        assert r1.status_code == 202
        assert r2.status_code == 202

        # 3rd request must be rejected with 429
        r3 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Job 3"})
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers
        assert r3.headers["Retry-After"] == "30"
        assert "capacity" in r3.json()["detail"].lower()

        await asyncio.sleep(0.05)
        # Verify exactly 2 background tasks were launched, 0 for the rejected request
        assert launched_tasks == 2

        hold_event.set()
        await asyncio.sleep(0.05)


async def test_creator_concurrent_admission_race(client: AsyncClient):
    """Test 3: High-concurrency race condition test around capacity boundary."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 5

    hold_event = asyncio.Event()
    max_running = 0
    running_now = 0

    async def mock_background(job_id, run_id, payload):
        nonlocal max_running, running_now
        running_now += 1
        if running_now > max_running:
            max_running = running_now
        await hold_event.wait()
        running_now -= 1

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=mock_background):
        # Fire 30 requests concurrently
        tasks = [
            client.post("/creator/generate", json={"generation_type": "image", "prompt": f"Race job {i}"})
            for i in range(30)
        ]
        responses = await asyncio.gather(*tasks)

        await asyncio.sleep(0.05)

        accepted = [r for r in responses if r.status_code == 202]
        rejected = [r for r in responses if r.status_code == 429]

        assert len(accepted) == 5, f"Expected 5 accepted, got {len(accepted)}"
        assert len(rejected) == 25, f"Expected 25 rejected, got {len(rejected)}"
        assert max_running <= 5
        assert len(_RUNNING_JOB_IDS) <= 5

        hold_event.set()
        await asyncio.sleep(0.05)


async def test_creator_slot_release_on_success(client: AsyncClient):
    """Test 4: Completed job releases its slot, allowing subsequent requests to succeed."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 1

    async def fast_success_background(job_id, run_id, payload):
        _ACTIVE_JOBS[job_id]["status"] = "completed"

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=fast_success_background):
        # 1st request
        r1 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "First job"})
        assert r1.status_code == 202
        job_1_id = r1.json()["job_id"]

        # Wait for task completion and slot release
        await asyncio.sleep(0.05)
        assert len(_RUNNING_JOB_IDS) == 0
        assert _ACTIVE_JOBS[job_1_id]["status"] == "completed"

        # 2nd request must succeed immediately without 429
        r2 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Second job"})
        assert r2.status_code == 202

        await asyncio.sleep(0.05)
        assert len(_RUNNING_JOB_IDS) == 0


async def test_creator_slot_release_on_exception(client: AsyncClient):
    """Test 5: Failed background job (exception) releases its slot cleanly."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 1

    async def failing_background(job_id, run_id, payload):
        raise RuntimeError("Simulated unhandled pipeline failure")

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=failing_background):
        r1 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Failing job"})
        assert r1.status_code == 202

        await asyncio.sleep(0.05)

        # Slot must be released despite failure
        assert len(_RUNNING_JOB_IDS) == 0

        # Subsequent request must succeed
        async def fast_success(job_id, run_id, payload):
            _ACTIVE_JOBS[job_id]["status"] = "completed"

        with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=fast_success):
            r2 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Next job"})
            assert r2.status_code == 202
            await asyncio.sleep(0.05)
            assert len(_RUNNING_JOB_IDS) == 0


async def test_creator_slot_release_on_cancellation(client: AsyncClient):
    """Test 6: Cancelled job releases its slot and updates state to failed."""
    settings = get_settings()
    settings.creator_max_concurrent_jobs = 1

    job_task = None
    started_event = asyncio.Event()

    async def cancellable_background(job_id, run_id, payload):
        started_event.set()
        await asyncio.sleep(10.0)

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=cancellable_background):
        r1 = await client.post("/creator/generate", json={"generation_type": "image", "prompt": "Cancellable job"})
        assert r1.status_code == 202
        job_id = r1.json()["job_id"]

        # Wait until background task starts
        await started_event.wait()
        assert len(_RUNNING_JOB_IDS) == 1

        # Find and cancel the task
        for t in asyncio.all_tasks():
            if "_execute_creator_job_background" in str(t):
                t.cancel()

        # Allow cancellation to process
        await asyncio.sleep(0.05)

        # Slot must be released and job marked as failed
        assert len(_RUNNING_JOB_IDS) == 0
        assert _ACTIVE_JOBS[job_id]["status"] == "failed"
        assert "cancelled" in _ACTIVE_JOBS[job_id]["failure_reason"].lower()


async def test_creator_active_jobs_bounded_retention(client: AsyncClient):
    """Test 7: _ACTIVE_JOBS memory bound - terminal jobs evicted FIFO, active jobs never evicted."""
    settings = get_settings()
    retention_limit = 5

    # Seed 2 active jobs
    _ACTIVE_JOBS["active-1"] = {"job_id": "active-1", "status": "in_progress"}
    _ACTIVE_JOBS["active-2"] = {"job_id": "active-2", "status": "pending"}

    # Seed 6 terminal jobs
    for i in range(1, 7):
        _ACTIVE_JOBS[f"term-{i}"] = {
            "job_id": f"term-{i}",
            "status": "completed" if i % 2 == 0 else "failed",
        }

    assert len(_ACTIVE_JOBS) == 8

    # Prune cache to retention limit 5
    _prune_active_jobs_cache(retention_limit=retention_limit)

    # Dictionary size must now be <= retention_limit
    assert len(_ACTIVE_JOBS) == 5

    # Invariant: Active jobs must NEVER be evicted
    assert "active-1" in _ACTIVE_JOBS
    assert "active-2" in _ACTIVE_JOBS

    # Oldest terminal jobs (term-1, term-2, term-3) should have been evicted
    assert "term-1" not in _ACTIVE_JOBS
    assert "term-2" not in _ACTIVE_JOBS
    assert "term-3" not in _ACTIVE_JOBS

    # Recent terminal jobs (term-4, term-5, term-6) must be retained
    assert "term-4" in _ACTIVE_JOBS
    assert "term-5" in _ACTIVE_JOBS
    assert "term-6" in _ACTIVE_JOBS


async def test_creator_existing_behavior_preserved(client: AsyncClient):
    """Test 8: Preserves all schemas, polling responses, and validation."""
    # 1. Validation test (422 for empty prompt)
    r_empty = await client.post("/creator/generate", json={"generation_type": "image", "prompt": ""})
    assert r_empty.status_code == 422

    # 2. Validation test (422 for image_to_video missing start frame)
    r_no_frame = await client.post(
        "/creator/generate",
        json={"generation_type": "image_to_video", "prompt": "Animate this"},
    )
    assert r_no_frame.status_code == 422

    # 3. Successful generation response schema
    async def mock_bg(job_id, run_id, payload):
        _ACTIVE_JOBS[job_id]["status"] = "completed"

    with patch("app.api.routers.creator._do_execute_creator_job_background", side_effect=mock_bg):
        r_gen = await client.post(
            "/creator/generate",
            json={
                "generation_type": "image",
                "prompt": "Preserve API compatibility prompt",
                "aspect_ratio": "16:9",
            },
        )
        assert r_gen.status_code == 202
        data = r_gen.json()
        assert "job_id" in data
        assert "workflow_run_id" in data
        assert data["status"] in ("pending", "completed")
        assert data["prompt"] == "Preserve API compatibility prompt"

        # Polling endpoint check
        r_poll = await client.get(f"/creator/jobs/{data['job_id']}")
        assert r_poll.status_code == 200
        poll_data = r_poll.json()
        assert poll_data["job_id"] == data["job_id"]
