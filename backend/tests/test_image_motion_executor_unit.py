"""Unit tests for ShotExecutor image_motion execution and FFmpeg camera motion."""

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.storyboard import Shot
from app.workflows.models import StageResult
from app.workflows.shot_executor import ShotExecutionResult, ShotExecutor
from app.workflows.video_assembler import VideoAssembler


@pytest.mark.asyncio
async def test_shot_executor_image_motion_bypasses_ai_video_and_renders_motion():
    """Verify that a shot with generation_mode='image_motion' skips the AI video stage,

    renders camera motion via FFmpeg, and incurs zero video cost.
    """
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)

    # Create dummy temp image file
    tmp_dir = Path(tempfile.gettempdir())
    dummy_img = tmp_dir / f"test_img_{uuid.uuid4().hex}.png"
    # Create minimal 1080x1920 png via ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "ffmpeg is required for this test"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=darkblue:s=1080x1920:d=1", "-vframes", "1", str(dummy_img)],
        check=True,
        capture_output=True,
    )

    shot = Shot(
        shot_number=1,
        description="Confidential document on desk under warm lamp",
        duration_seconds=3,
        camera_movement="slow_push_in",
        generation_class="C",
        generation_mode="image_motion",
    )

    executed_stages = []

    async def mock_execute_stage(stage_key, context, db, max_retries):
        executed_stages.append(stage_key)
        if stage_key == "prompt":
            return StageResult(
                stage="prompt",
                success=True,
                output={"positive_prompt": "document on desk", "negative_prompt": "blurry"},
                cost_usd=0.0001,
            )
        elif stage_key == "image":
            return StageResult(
                stage="image",
                success=True,
                output={"image_path": str(dummy_img)},
                cost_usd=0.04,
            )
        elif stage_key == "voice":
            return StageResult(
                stage="voice",
                success=True,
                output={"voice_path": "/tmp/dummy_voice.wav"},
                cost_usd=0.005,
            )
        elif stage_key == "video":
            pytest.fail("execute_stage should NEVER be called for 'video' when generation_mode is image_motion")

    with patch("app.workflows.shot_executor.execute_stage", side_effect=mock_execute_stage):
        res = await executor._execute_single_shot(
            shot=shot,
            base_context={"aspect_ratio": "9:16"},
        )

        assert res.success is True
        # AI video stage was NOT in the stages passed to execute_stage
        assert executed_stages == ["prompt", "image", "voice"]
        # A valid motion video was rendered
        assert res.video_path is not None
        assert Path(res.video_path).exists()
        assert res.video_path.endswith(".mp4")

        # Total cost is only prompt + image + voice (no AI video generation fee)
        assert pytest.approx(res.cost_usd, abs=0.001) == 0.0451

        # Check video stage result is present in stage_results with $0.00 cost
        vid_stages = [sr for sr in res.stage_results if sr.stage == "video"]
        assert len(vid_stages) == 1
        assert vid_stages[0].cost_usd == 0.0
        assert vid_stages[0].output.get("generation_mode") == "image_motion"

    # Cleanup
    if dummy_img.exists():
        dummy_img.unlink()
    if res.video_path and Path(res.video_path).exists():
        Path(res.video_path).unlink()


@pytest.mark.asyncio
async def test_shot_executor_standard_video_mode_executes_all_stages():
    """Verify that a shot with generation_mode='video' (Class A or legacy) runs all 4 stages."""
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)

    shot = Shot(
        shot_number=1,
        description="Hero fighting villain",
        duration_seconds=4,
        generation_class="A",
        generation_mode="video",
    )

    executed_stages = []

    async def mock_execute_stage(stage_key, context, db, max_retries):
        executed_stages.append(stage_key)
        return StageResult(
            stage=stage_key,
            success=True,
            output={f"{stage_key}_path": f"/tmp/dummy_{stage_key}"},
            cost_usd=0.05,
        )

    with patch("app.workflows.shot_executor.execute_stage", side_effect=mock_execute_stage):
        res = await executor._execute_single_shot(
            shot=shot,
            base_context={"aspect_ratio": "16:9"},
        )

        assert res.success is True
        assert executed_stages == ["prompt", "image", "video", "voice"]
        assert pytest.approx(res.cost_usd, abs=0.001) == 0.20


@pytest.mark.asyncio
async def test_render_image_motion_clip_ffprobe_duration_and_resolution():
    """Verify _render_image_motion_clip produces an exact MP4 matching duration and resolution."""
    db_mock = AsyncMock()
    executor = ShotExecutor(db_mock)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg and ffprobe

    # Generate 16:9 input image (1920x1080)
    tmp_img = Path(tempfile.gettempdir()) / f"probe_test_{uuid.uuid4().hex}.png"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1080:d=1", "-vframes", "1", str(tmp_img)],
        check=True,
        capture_output=True,
    )

    target_duration = 2.5
    video_path = await executor._render_image_motion_clip(
        image_path=str(tmp_img),
        camera_movement="slow_push_in",
        duration_seconds=target_duration,
        aspect_ratio="16:9",
    )

    assert video_path is not None
    assert Path(video_path).exists()

    # Probe duration and dimensions
    probe_cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    import json
    info = json.loads(proc.stdout)

    stream = info["streams"][0]
    assert stream["width"] == 1920
    assert stream["height"] == 1080

    format_dur = float(info["format"]["duration"])
    assert pytest.approx(format_dur, abs=0.1) == target_duration

    # Cleanup
    if tmp_img.exists():
        tmp_img.unlink()
    if Path(video_path).exists():
        Path(video_path).unlink()
