"""
Unit tests for Workflow Run schemas and service logic.

No database connection is used anywhere in this file — the repository
is mocked out entirely. These test business rules and validation in
isolation; see test_workflow_runs_integration.py for the full
API-through-real-Postgres path.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.core import WorkflowRun
from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus
from app.schemas.workflow_run import (
    INITIAL_STAGE,
    WorkflowRunCreateRequest,
    WorkflowRunUpdateRequest,
)
from app.services.pipeline_state import InvalidStageTransitionError
from app.services.workflow_service import (
    ProjectNotFoundError,
    create_workflow_run,
    update_workflow_run,
)

# --- Schema validation --------------------------------------------------


def test_create_request_accepts_lowercase_mode():
    req = WorkflowRunCreateRequest(project_id=uuid.uuid4(), mode="assisted")
    assert req.mode == WorkflowMode.ASSISTED


def test_create_request_accepts_uppercase_mode():
    """The task's own example payload uses {"mode": "ASSISTED"} —
    WorkflowMode's stored values are lowercase, so this must
    case-normalize rather than reject a payload shaped exactly like
    the spec's example."""
    req = WorkflowRunCreateRequest(project_id=uuid.uuid4(), mode="ASSISTED")
    assert req.mode == WorkflowMode.ASSISTED


def test_create_request_defaults_mode_to_assisted():
    req = WorkflowRunCreateRequest(project_id=uuid.uuid4())
    assert req.mode == WorkflowMode.ASSISTED


def test_create_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        WorkflowRunCreateRequest(
            project_id=uuid.uuid4(), status="pending"  # not a create-time field
        )


def test_update_request_allows_only_whitelisted_fields():
    req = WorkflowRunUpdateRequest(
        status="completed",
        current_stage="script_generated",  # a real PipelineStage member
        failure_reason=None,
        total_cost_usd="1.2500",
    )
    assert req.status == WorkflowStatus.COMPLETED
    assert req.current_stage == PipelineStage.SCRIPT_GENERATED


def test_update_request_accepts_uppercase_current_stage():
    req = WorkflowRunUpdateRequest(current_stage="SCRIPT_GENERATED")
    assert req.current_stage == PipelineStage.SCRIPT_GENERATED


def test_update_request_rejects_invalid_current_stage():
    """Fixes audit Issue 2 at the schema layer: a stage name that
    isn't a real PipelineStage member (e.g. the n8n-style free-text
    names this endpoint used to silently accept, like "research" or
    "script_generation") is rejected with a 422-equivalent
    ValidationError before it ever reaches the service."""
    with pytest.raises(ValidationError):
        WorkflowRunUpdateRequest(current_stage="research")

    with pytest.raises(ValidationError):
        WorkflowRunUpdateRequest(current_stage="script_generation")  # not "_generated"


@pytest.mark.parametrize(
    "bad_field",
    ["project_id", "topic", "mode", "id", "created_at", "arbitrary_field"],
)
def test_update_request_rejects_non_whitelisted_fields(bad_field):
    """This is the actual enforcement of 'do not allow arbitrary
    updates' — extra='forbid' on the schema, verified per disallowed
    field name."""
    with pytest.raises(ValidationError):
        WorkflowRunUpdateRequest(**{bad_field: "anything"})


def test_update_request_rejects_negative_cost():
    with pytest.raises(ValidationError):
        WorkflowRunUpdateRequest(total_cost_usd=-5)


# --- Service layer (repository mocked) -----------------------------------


@pytest.mark.asyncio
async def test_create_workflow_run_sets_pending_and_created_stage():
    """Fixes audit Issue 1: a newly-created run starts at the
    canonical PipelineStage.CREATED value ("created"), not the old
    invalid literal "research" — INITIAL_STAGE is now derived directly
    from PipelineStage, not an independent string."""
    fake_repo = AsyncMock()
    fake_repo.project_exists.return_value = True
    fake_repo.add.side_effect = lambda run: run  # echo back what was built

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        run = await create_workflow_run(db=AsyncMock(), project_id=uuid.uuid4(), topic="cats")

    assert run.status == WorkflowStatus.PENDING
    assert run.current_stage == INITIAL_STAGE
    assert run.current_stage == PipelineStage.CREATED.value
    assert run.current_stage == "created"


@pytest.mark.asyncio
async def test_create_workflow_run_raises_when_project_missing():
    fake_repo = AsyncMock()
    fake_repo.project_exists.return_value = False

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        with pytest.raises(ProjectNotFoundError):
            await create_workflow_run(db=AsyncMock(), project_id=uuid.uuid4())

    fake_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_workflow_run_returns_none_when_missing():
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = None

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        result = await update_workflow_run(
            db=AsyncMock(),
            run_id=uuid.uuid4(),
            payload=WorkflowRunUpdateRequest(status="running"),
        )

    assert result is None
    fake_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_update_workflow_run_only_applies_fields_that_were_set():
    """A non-stage-only PATCH (no current_stage in the payload) must
    not touch pipeline_state.advance_stage() at all."""
    existing = WorkflowRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        topic="original topic",
        status=WorkflowStatus.PENDING,
        current_stage=PipelineStage.CREATED.value,
    )
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = existing
    fake_repo.save.side_effect = lambda run: run

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        result = await update_workflow_run(
            db=AsyncMock(),
            run_id=existing.id,
            payload=WorkflowRunUpdateRequest(status="running"),
        )

    assert result.status == WorkflowStatus.RUNNING
    assert result.topic == "original topic"  # untouched — was never in the payload
    assert result.current_stage == PipelineStage.CREATED.value  # untouched


@pytest.mark.asyncio
async def test_update_workflow_run_advances_stage_via_state_machine():
    """Fixes audit Issue 2: PATCHing current_stage now goes through
    pipeline_state.advance_stage() — a legal transition
    (CREATED -> TREND_SELECTED) succeeds and is reflected on the
    returned run."""
    existing = WorkflowRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.CREATED.value,
    )
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = existing

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        result = await update_workflow_run(
            db=AsyncMock(),
            run_id=existing.id,
            payload=WorkflowRunUpdateRequest(current_stage="trend_selected"),
        )

    assert result.current_stage == PipelineStage.TREND_SELECTED.value


@pytest.mark.asyncio
async def test_update_workflow_run_rejects_illegal_stage_transition():
    """CREATED -> PUBLISHED skips every stage in between and must be
    rejected, exactly like calling pipeline_state.advance_stage()
    directly would reject it — same validation, same error type,
    because it IS the same function now."""
    existing = WorkflowRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.CREATED.value,
    )
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = existing

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        with pytest.raises(InvalidStageTransitionError):
            await update_workflow_run(
                db=AsyncMock(),
                run_id=existing.id,
                payload=WorkflowRunUpdateRequest(current_stage="published"),
            )


@pytest.mark.asyncio
async def test_update_workflow_run_auto_stamps_completed_at():
    existing = WorkflowRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.VIDEO_GENERATED.value,
    )
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = existing
    fake_repo.save.side_effect = lambda run: run

    before = datetime.now(timezone.utc)

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        result = await update_workflow_run(
            db=AsyncMock(),
            run_id=existing.id,
            payload=WorkflowRunUpdateRequest(status="completed"),
        )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.completed_at is not None
    # WorkflowRun.completed_at is a naive TIMESTAMP WITHOUT TIME ZONE
    # column (see _to_naive_utc's docstring in workflow_service.py) —
    # the service strips tzinfo before storing, so compare naive-to-naive.
    assert result.completed_at >= before.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_update_workflow_run_respects_explicit_completed_at():
    """If the caller sets completed_at explicitly, the auto-stamp
    convenience must not clobber it."""
    explicit_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing = WorkflowRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=WorkflowStatus.RUNNING,
        current_stage=PipelineStage.VIDEO_GENERATED.value,
    )
    fake_repo = AsyncMock()
    fake_repo.get_by_id.return_value = existing
    fake_repo.save.side_effect = lambda run: run

    with patch("app.services.workflow_service.WorkflowRunRepository", return_value=fake_repo):
        result = await update_workflow_run(
            db=AsyncMock(),
            run_id=existing.id,
            payload=WorkflowRunUpdateRequest(status="completed", completed_at=explicit_time),
        )

    # Stored value is naive UTC (tzinfo stripped) — see _to_naive_utc.
    assert result.completed_at == explicit_time.replace(tzinfo=None)
