"""Unit tests for Orchestrator pipeline integration with MetadataAgent."""
from unittest.mock import AsyncMock, patch
import uuid

import pytest
from app.models.enums import PipelineStage
from app.workflows.models import StageResult
from app.workflows.orchestrator import _KEY_TO_PIPELINE_STAGE, _PIPELINE, Orchestrator
from app.workflows.stage_executor import _merge_context


def test_pipeline_order_includes_metadata_before_publishing():
    """Verify that metadata stage exists and is situated immediately before publishing."""
    assert "metadata" in _PIPELINE
    assert "publishing" in _PIPELINE

    metadata_idx = _PIPELINE.index("metadata")
    publishing_idx = _PIPELINE.index("publishing")

    assert metadata_idx == publishing_idx - 1
    assert _KEY_TO_PIPELINE_STAGE["metadata"] == PipelineStage.APPROVED


def test_context_merge_propagates_metadata_to_publishing():
    """Verify that when metadata stage completes, its title, description, and
    tags merge into the orchestrator context and are available for publishing."""
    initial_context = {
        "workflow_run_id": str(uuid.uuid4()),
        "topic": "The Science of Sleep",
        "video_storage_path": "/videos/render1.mp4",
        "video_id": str(uuid.uuid4()),
    }

    metadata_output = {
        "title": "Why You Sleep: The Surprising Science of Brain Cleaning",
        "description": "Discover how the glymphatic system clears toxins while you sleep. Subscribe for more health science!",
        "tags": "sleep science, biology, brain health, neuroscience",
        "hashtags": ["#Sleep", "#Health", "#Science"],
        "category": "Science & Technology",
    }

    merged = _merge_context(initial_context, metadata_output)

    # PublishingAgent required / optional fields must now be present
    assert merged["title"] == "Why You Sleep: The Surprising Science of Brain Cleaning"
    assert "glymphatic system" in merged["description"]
    assert merged["tags"] == "sleep science, biology, brain health, neuroscience"
    assert merged["video_storage_path"] == "/videos/render1.mp4"
    assert merged["video_id"] == initial_context["video_id"]


@pytest.mark.asyncio
async def test_orchestrator_routes_to_cinematic_director_when_requested():
    """Verify that when use_cinematic_director=True, storyboard stage executes cinematic_director."""
    db_mock = AsyncMock()
    orch = Orchestrator(db_mock)

    context = {
        "workflow_run_id": str(uuid.uuid4()),
        "script_content": "A thrilling cinematic tale.",
        "use_cinematic_director": True,
    }

    with patch("app.workflows.orchestrator.execute_stage", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = StageResult(
            stage="cinematic_director",
            success=True,
            output={"shots": []},
        )
        res = await orch._execute_stage("storyboard", context)

        mock_exec.assert_awaited_once_with("cinematic_director", context, db_mock, orch._max_retries)
        assert res.stage == "cinematic_director"
        assert res.success is True


@pytest.mark.asyncio
async def test_orchestrator_routes_to_legacy_storyboard_by_default():
    """Verify that by default (use_cinematic_director=False), storyboard stage executes standard storyboard."""
    db_mock = AsyncMock()
    orch = Orchestrator(db_mock)

    context = {
        "workflow_run_id": str(uuid.uuid4()),
        "script_content": "Standard script content.",
    }

    with patch("app.workflows.orchestrator.execute_stage", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = StageResult(
            stage="storyboard",
            success=True,
            output={"shots": []},
        )
        res = await orch._execute_stage("storyboard", context)

        mock_exec.assert_awaited_once_with("storyboard", context, db_mock, orch._max_retries)
        assert res.stage == "storyboard"
        assert res.success is True

