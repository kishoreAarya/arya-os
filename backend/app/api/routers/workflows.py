"""
Arya OS — Workflow API Router.

Thin FastAPI router for end-to-end workflow execution.

Delegates all business logic to the Runner. Contains no orchestration,
no retry logic, no provider knowledge, and no platform knowledge.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.models.enums import WorkflowMode
from app.workflows.models import WorkflowInput, WorkflowResult
from app.workflows.runner import Runner

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "/youtube",
    response_model=WorkflowResult,
    status_code=status.HTTP_200_OK,
    summary="Execute a complete YouTube content workflow",
    description=(
        "Runs the full pipeline sequentially: TrendAgent → ScriptAgent → "
        "PromptAgent → StoryboardAgent → ImageAgent → VideoAgent → "
        "VoiceAgent → ThumbnailAgent → Storage → PublishingAgent → "
        "AnalyticsAgent → LearningFeedbackAgent. Each stage receives "
        "the previous stage's output. If any stage fails, execution "
        "stops and structured error information is returned."
    ),
)
async def create_youtube_workflow(
    workflow_input: WorkflowInput,
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID,
    mode: WorkflowMode = WorkflowMode.AUTONOMOUS,
) -> WorkflowResult:
    """Execute a complete YouTube content workflow.

    Validates the request, obtains a database session via the existing
    dependency injection, instantiates the Runner, and delegates
    execution. Returns the full WorkflowResult upon completion or failure.

    Args:
        workflow_input: Validated workflow parameters.
        db: Request-scoped async database session.
        project_id: The Project to associate this run with.
        mode: Execution mode — manual, assisted, or autonomous.

    Returns:
        WorkflowResult with final status, outputs, timing, and cost.

    Raises:
        HTTPException: If workflow execution fails with an unhandled error.
    """
    runner = Runner(db=db)

    try:
        result = await runner.start(
            workflow_input=workflow_input,
            project_id=project_id,
            mode=mode,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {exc}",
        ) from exc

    return result
