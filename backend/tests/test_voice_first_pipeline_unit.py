"""Unit tests for the Voice-First canonical pipeline and director timing integration.

Covers Section 16 requirements:
- Script -> Voice -> Director works
- existing non-cinematic workflow remains functional
- Director receives narration timing and aligns shot boundaries
- preserves irregular pacing and A/B/C classification
- ShotExecutor skips TTS when master voice is present
"""

import uuid
from unittest.mock import AsyncMock, patch
import pytest

from app.agents.voice import VoiceAgent
from app.agents.cinematic_director import CinematicDirectorAgent
from app.core.audio_timing import build_fallback_timing
from app.schemas.cinematic import GenerationClass, GenerationMode, NarrationTiming
from app.workflows.orchestrator import _CINEMATIC_PIPELINE, _PIPELINE, Orchestrator
from app.workflows.shot_executor import ShotExecutor
from app.agents.storyboard import Shot


@pytest.mark.asyncio
async def test_voice_agent_produces_narration_timing():
    """VoiceAgent.run outputs typed narration_timing, voice_duration_seconds, and master_voice_path."""
    db_mock = AsyncMock()
    agent = VoiceAgent(db_mock)

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = AsyncMock(
            success=True,
            output={"storage_path": "/tmp/voice.mp3", "duration_seconds": 18.5, "alignment": None},
            provider="replicate",
            cost_usd=0.005,
            elapsed_time=2.1,
        )

        res = await agent.run({"script_content": "A chilling whisper echoed in the silent hall."})

        assert res.success is True
        assert res.output["voice_path"] == "/tmp/voice.mp3"
        assert res.output["master_voice_path"] == "/tmp/voice.mp3"
        assert res.output["voice_duration_seconds"] == 18.5
        assert "narration_timing" in res.output
        timing = res.output["narration_timing"]
        assert timing["total_duration_seconds"] == 18.5
        assert len(timing["segments"]) >= 1


@pytest.mark.asyncio
async def test_cinematic_director_consumes_narration_timing_and_aligns_shots():
    """CinematicDirectorAgent consumes narration_timing and aligns shot durations to phrase boundaries."""
    db_mock = AsyncMock()
    director = CinematicDirectorAgent(db_mock)

    timing = build_fallback_timing(
        text="Dark waters stirred. A colossal shape surfaced! The crew froze in terror.",
        total_duration_seconds=18.0,
    )

    context = {
        "script_content": "Dark waters stirred. A colossal shape surfaced! The crew froze in terror.",
        "target_duration": 18.0,
        "narration_timing": timing.model_dump(),
        "aspect_ratio": "9:16",
    }

    res = await director.run(context)
    assert res.success is True
    plan = res.output["cinematic_plan"]
    assert len(plan.shots) >= 2
    # Planned duration equals voice duration
    assert plan.planned_duration == pytest.approx(18.0, abs=0.05)
    # Master audio plan created
    assert "master_audio_plan" in res.output
    # Classification preserved
    classes = [s.generation_class for s in plan.shots]
    assert all(c in [GenerationClass.A, GenerationClass.B, GenerationClass.C] for c in classes)


def test_orchestrator_pipeline_selection():
    """Cinematic workflow selects _CINEMATIC_PIPELINE (Voice-first); standard workflow selects _PIPELINE."""
    db_mock = AsyncMock()
    orch = Orchestrator(db_mock)

    cinematic_ctx = {"use_cinematic_director": True}
    pipe_cinematic = orch._get_pipeline(cinematic_ctx)
    assert pipe_cinematic == _CINEMATIC_PIPELINE
    assert pipe_cinematic.index("voice") < pipe_cinematic.index("storyboard")

    standard_ctx = {"use_cinematic_director": False}
    pipe_standard = orch._get_pipeline(standard_ctx)
    assert pipe_standard == _PIPELINE
    assert "storyboard" in pipe_standard


@pytest.mark.asyncio
async def test_shot_executor_skips_voice_when_master_voice_present():
    """When master_voice_path or narration_timing is in context, ShotExecutor does not call TTS stage."""
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)

    shot = Shot(
        shot_number=1,
        description="A dark cave with glowing runes.",
        shot_type="wide",
        duration_seconds=4,
        camera_movement="slow_push_in",
        generation_mode="image_motion",
        generation_class="C",
    )

    context = {
        "shots": [shot],
        "master_voice_path": "/tmp/master_voice.mp3",
        "narration_timing": {"total_duration_seconds": 20.0},
    }

    stages_executed = []

    async def mock_execute_stage(stage_key, context, db, max_retries):
        stages_executed.append(stage_key)
        return AsyncMock(
            stage=stage_key,
            success=True,
            output={"image_path": "/tmp/img.png", "video_path": "/tmp/vid.mp4"} if stage_key == "image" else {},
            cost_usd=0.01,
            error=None,
        )

    with patch("app.workflows.shot_executor.execute_stage", side_effect=mock_execute_stage), \
         patch.object(executor, "_render_image_motion_clip", new_callable=AsyncMock) as mock_render:
        mock_render.return_value = "/tmp/motion.mp4"
        summary = await executor.execute(context)

        assert summary is not None
        # Must execute prompt and image, but SKIP voice!
        assert "prompt" in stages_executed
        assert "image" in stages_executed
        assert "voice" not in stages_executed
