"""
Integration tests for POST/GET/PATCH /workflow-runs.

Runs the real FastAPI app against a real Postgres database (same
DATABASE_URL / migrations already applied as the rest of the test
suite, provisioned by test.yml in CI). No mocking here — this is the
full request -> router -> service -> pipeline_state -> repository ->
database path.
"""

import uuid

import httpx
import pytest

# Must match conftest.py's fixtures (loop_scope="module") so the app's
# module-level async engine/connection pool stays valid for every test
# in this file — see the comment in conftest.py for why.
pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_create_workflow_run_returns_expected_shape(client: httpx.AsyncClient, test_project):
    response = await client.post(
        "/workflow-runs/",
        json={
            "project_id": str(test_project),
            "topic": "cats vs dogs",
            "mode": "ASSISTED",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"workflow_run_id", "status", "current_stage"}
    assert body["status"] == "pending"
    # Fixes audit Issue 1: was the invalid literal "research"; now the
    # canonical PipelineStage.CREATED value.
    assert body["current_stage"] == "created"
    uuid.UUID(body["workflow_run_id"])  # doesn't raise


async def test_create_workflow_run_defaults_mode_when_omitted(
    client: httpx.AsyncClient, test_project
):
    response = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    assert response.status_code == 201


async def test_create_workflow_run_rejects_unknown_project(client: httpx.AsyncClient):
    response = await client.post(
        "/workflow-runs/",
        json={"project_id": str(uuid.uuid4()), "topic": "x"},
    )
    assert response.status_code == 422


async def test_create_workflow_run_rejects_malformed_project_id(
    client: httpx.AsyncClient,
):
    response = await client.post("/workflow-runs/", json={"project_id": "not-a-uuid"})
    assert response.status_code == 422


async def test_get_workflow_run_returns_full_representation(
    client: httpx.AsyncClient, test_project
):
    create_resp = await client.post(
        "/workflow-runs/", json={"project_id": str(test_project), "topic": "t"}
    )
    created = create_resp.json()

    response = await client.get(f"/workflow-runs/{created['workflow_run_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["workflow_run_id"]
    assert body["project_id"] == str(test_project)
    assert body["topic"] == "t"
    assert body["status"] == "pending"
    assert body["current_stage"] == "created"
    assert body["total_cost_usd"] is not None
    assert body["failure_reason"] is None
    assert body["completed_at"] is None


async def test_get_workflow_run_404_when_missing(client: httpx.AsyncClient):
    response = await client.get(f"/workflow-runs/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_workflow_run_422_on_malformed_id(client: httpx.AsyncClient):
    response = await client.get("/workflow-runs/not-a-uuid")
    assert response.status_code == 422


async def test_patch_updates_status_without_touching_stage(client: httpx.AsyncClient, test_project):
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(f"/workflow-runs/{run_id}", json={"status": "running"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["current_stage"] == "created"  # untouched


async def test_patch_advances_stage_through_legal_transition(
    client: httpx.AsyncClient, test_project
):
    """Fixes audit Issue 2: current_stage now moves through
    pipeline_state's own STAGE_TRANSITIONS. CREATED -> TREND_SELECTED
    is the only legal first move."""
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(
        f"/workflow-runs/{run_id}", json={"current_stage": "trend_selected"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_stage"] == "trend_selected"

    # confirm it actually persisted, not just echoed back
    refetched = (await client.get(f"/workflow-runs/{run_id}")).json()
    assert refetched["current_stage"] == "trend_selected"


async def test_patch_rejects_illegal_stage_transition(client: httpx.AsyncClient, test_project):
    """CREATED -> PUBLISHED skips every intermediate stage and must be
    rejected with 409 Conflict, not silently accepted."""
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(f"/workflow-runs/{run_id}", json={"current_stage": "published"})

    assert response.status_code == 409

    # confirm the run's stage was NOT changed by the rejected attempt
    refetched = (await client.get(f"/workflow-runs/{run_id}")).json()
    assert refetched["current_stage"] == "created"


async def test_patch_rejects_invalid_stage_name(client: httpx.AsyncClient, test_project):
    """A stage name that isn't a real PipelineStage member at all
    (e.g. the old free-text values this endpoint used to accept, like
    "research" or "script_generation") is rejected with 422, before
    ever reaching the state machine."""
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(f"/workflow-runs/{run_id}", json={"current_stage": "research"})

    assert response.status_code == 422


async def test_patch_partial_update_does_not_clobber_other_fields(
    client: httpx.AsyncClient, test_project
):
    create_resp = await client.post(
        "/workflow-runs/",
        json={"project_id": str(test_project), "topic": "keep me"},
    )
    run_id = create_resp.json()["workflow_run_id"]

    await client.patch(f"/workflow-runs/{run_id}", json={"status": "running"})

    refetched = (await client.get(f"/workflow-runs/{run_id}")).json()
    assert refetched["topic"] == "keep me"  # untouched by the PATCH
    assert refetched["status"] == "running"


async def test_patch_auto_stamps_completed_at_on_completed_status(
    client: httpx.AsyncClient, test_project
):
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(f"/workflow-runs/{run_id}", json={"status": "completed"})

    assert response.status_code == 200
    assert response.json()["completed_at"] is not None


async def test_patch_rejects_disallowed_fields(client: httpx.AsyncClient, test_project):
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(
        f"/workflow-runs/{run_id}",
        json={"project_id": str(uuid.uuid4())},  # not in the whitelist
    )

    assert response.status_code == 422


async def test_patch_rejects_arbitrary_unknown_field(client: httpx.AsyncClient, test_project):
    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = create_resp.json()["workflow_run_id"]

    response = await client.patch(f"/workflow-runs/{run_id}", json={"totally_made_up_field": "x"})

    assert response.status_code == 422


async def test_patch_404_when_missing(client: httpx.AsyncClient):
    response = await client.patch(f"/workflow-runs/{uuid.uuid4()}", json={"status": "running"})
    assert response.status_code == 404


# --- Pipeline resume compatibility (requirement 3) -----------------------


async def test_resume_stage_still_works_on_a_run_created_via_the_api(
    client: httpx.AsyncClient, test_project, db_session
):
    """The core compatibility requirement: a WorkflowRun created
    through POST /workflow-runs/ must be fully usable by
    pipeline_state.py's resume_stage()/advance_stage() — the exact
    crash it would have hit before this fix (PipelineStage("research")
    raising ValueError)."""
    from app.services.pipeline_state import advance_stage, resume_stage

    create_resp = await client.post("/workflow-runs/", json={"project_id": str(test_project)})
    run_id = uuid.UUID(create_resp.json()["workflow_run_id"])

    # Would have raised ValueError before this fix.
    stage = await resume_stage(db_session, run_id)
    assert stage.value == "created"

    # advance_stage() (the same function PATCH now delegates to) still
    # works directly too, independent of the HTTP layer.
    run = await advance_stage(db_session, run_id, stage.__class__.TREND_SELECTED)
    assert run.current_stage == "trend_selected"

    stage_after = await resume_stage(db_session, run_id)
    assert stage_after.value == "trend_selected"
