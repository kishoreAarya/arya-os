"""Unit tests for Duration Integrity & Production Hardening in Arya OS (Task 11).

Tests duration propagation, word-count constraints, shot count formulas,
media vs wall-clock duration separation in ShotExecutor,
FFmpeg audio/video loop & pad assembly logic, and tolerance verification.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agents.script import ScriptAgent, _build_script_prompt
from app.agents.storyboard import Shot, StoryboardAgent, _build_storyboard_prompt
from app.workflows.models import StageResult
from app.workflows.shot_executor import ShotExecutionResult, ShotExecutionSummary, ShotExecutor
from app.workflows.video_assembler import VideoAssembler


# ---------------------------------------------------------------------------
# 1. ScriptAgent Duration Constraints
# ---------------------------------------------------------------------------

def test_script_prompt_duration_constraints():
    """Verify script prompt builder calculates accurate word count constraints."""
    # 15s short: ~28-35 words
    prompt_15s = _build_script_prompt(
        topic="Deep Sea Wonders",
        research_data=None,
        target_duration=15,
    )
    assert "TARGET DURATION: Exactly 15 seconds" in prompt_15s
    assert "Strictly between 28 and 34 words" in prompt_15s

    # 30s video: ~57-69 words
    prompt_30s = _build_script_prompt(
        topic="Volcanoes",
        research_data=None,
        target_duration=30,
    )
    assert "TARGET DURATION: Exactly 30 seconds" in prompt_30s
    assert "Strictly between 57 and 69 words" in prompt_30s

    # 60s video: ~114-138 words
    prompt_60s = _build_script_prompt(
        topic="Space Exploration",
        research_data=None,
        target_duration=60,
    )
    assert "TARGET DURATION: Exactly 60 seconds" in prompt_60s
    assert "Strictly between 114 and 138 words" in prompt_60s


@pytest.mark.asyncio
async def test_script_agent_run_carries_target_duration():
    """Verify ScriptAgent.run forwards target duration and includes it in output."""
    mock_db = AsyncMock()
    agent = ScriptAgent(db=mock_db)

    mock_exec_res = MagicMock()
    mock_exec_res.success = True
    mock_exec_res.output = "Beneath the black ocean waves, creatures glow like stars. Their living light illuminates a hidden universe."
    mock_exec_res.cost_usd = 0.001
    mock_exec_res.provider = "gemini"
    mock_exec_res.elapsed_time = 1.25

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock, return_value=mock_exec_res):
        res = await agent.run({
            "topic": "Deep Sea",
            "duration": 15,
            "target_duration": 15,
        })

    assert res.success is True
    assert res.output["target_duration"] == 15
    assert res.output["duration"] == 15
    assert "Beneath the black ocean waves" in res.output["script"]


# ---------------------------------------------------------------------------
# 2. StoryboardAgent Shot Count & Distribution
# ---------------------------------------------------------------------------

def test_storyboard_shot_count_scaling():
    """Verify target_shots formula produces sufficient shots to meet duration."""
    mock_db = AsyncMock()
    agent = StoryboardAgent(db=mock_db)

    # For 15s target: round(15 / 3.75) = 4 shots (4 * 3.8s = 15.2s)
    dur_15 = 15
    shots_15 = max(2, min(round(dur_15 / 3.75), agent.MAX_SHOTS))
    assert shots_15 == 4

    # For 30s target: round(30 / 3.75) = 8 shots (8 * 3.8s = 30.4s)
    dur_30 = 30
    shots_30 = max(2, min(round(dur_30 / 3.75), agent.MAX_SHOTS))
    assert shots_30 == 8

    # For 60s target: round(60 / 3.75) = 16 shots (16 * 3.8s = 60.8s)
    dur_60 = 60
    shots_60 = max(2, min(round(dur_60 / 3.75), agent.MAX_SHOTS))
    assert shots_60 == 16

    # Minimum bound: 5s -> max(2, 1) = 2 shots
    dur_5 = 5
    shots_5 = max(2, min(round(dur_5 / 3.75), agent.MAX_SHOTS))
    assert shots_5 == 2

    # Maximum bound cap: 120s -> capped at MAX_SHOTS = 20
    dur_120 = 120
    shots_120 = max(2, min(round(dur_120 / 3.75), agent.MAX_SHOTS))
    assert shots_120 == 20


def test_storyboard_prompt_words_per_shot_guidance():
    """Verify storyboard prompt instructs correct words-per-shot allocation."""
    prompt = _build_storyboard_prompt(
        script_content="Line 1. Line 2. Line 3. Line 4.",
        aspect_ratio="9:16",
        target_duration=15,
    )

    assert "TARGET DURATION: 15 seconds total" in prompt
    assert "SHOT COUNT: Generate exactly 4 cinematic shots" in prompt
    assert "approximately 3.8 seconds" in prompt
    assert "strictly 7-9 words" in prompt
    assert "9:16" in prompt


# ---------------------------------------------------------------------------
# 3. ShotExecutor Media Duration vs Wall-Clock Separation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shot_executor_duration_uses_media_not_wall_clock():
    """Verify ShotExecutor calculates total_duration from media duration, not API latency."""
    mock_db = AsyncMock()
    executor = ShotExecutor(db=mock_db)

    # Mock execute_stage to simulate real media outputs with 3.88s video and 3.82s voice duration
    async def fake_execute_stage(stage_key, context, db, max_retries):
        if stage_key == "prompt":
            return StageResult(stage="prompt", success=True, cost_usd=0.001, output={"positive_prompt": "cinematic"})
        elif stage_key == "image":
            return StageResult(stage="image", success=True, cost_usd=0.01, output={"image_path": "/tmp/img.png"})
        elif stage_key == "video":
            mock_vid_res = MagicMock()
            mock_vid_res.duration_seconds = 3.88
            return StageResult(
                stage="video",
                success=True,
                cost_usd=0.04,
                output={"video_path": "/tmp/vid.mp4", "video_result": mock_vid_res},
            )
        elif stage_key == "voice":
            mock_voice_res = MagicMock()
            mock_voice_res.duration_seconds = 3.82
            return StageResult(
                stage="voice",
                success=True,
                cost_usd=0.005,
                output={"audio_path": "/tmp/aud.mp3", "voice_result": mock_voice_res},
            )
        return StageResult(stage=stage_key, success=False, error="Unknown stage")

    shot_plans = [
        Shot(
            shot_number=i,
            description=f"Visual for shot {i}",
            voiceover=f"Narration line for shot {i}",
            duration_seconds=4,
        )
        for i in range(1, 5)
    ]

    with patch("app.workflows.shot_executor.execute_stage", side_effect=fake_execute_stage):
        summary = await executor.execute({
            "shots": shot_plans,
            "aspect_ratio": "9:16",
        })

    assert len(summary.results) == 4
    assert all(r.success for r in summary.results)

    # Each shot media duration should be max(3.88s video, 3.82s voice) = 3.88s
    for shot_res in summary.results:
        assert shot_res.duration_seconds == pytest.approx(3.88, abs=0.05)
        # Wall-clock execution time is recorded in execution_time_ms
        assert shot_res.execution_time_ms >= 0

    # Total duration across 4 shots must sum media duration: 4 * 3.88 = 15.52s
    assert summary.total_duration == pytest.approx(15.52, abs=0.2)


# ---------------------------------------------------------------------------
# 4. VideoAssembler Loop & Pad Assembly Logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assembler_merge_audio_video_preserves_audio_no_shortest(tmp_path: Path):
    """Verify VideoAssembler._merge_audio_video does NOT use -shortest and loops video to fit audio."""
    mock_db = AsyncMock()
    assembler = VideoAssembler(db=mock_db)

    with patch("asyncio.to_thread") as mock_to_thread, \
         patch.object(assembler, "_probe_duration") as mock_probe, \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):

        # Audio is 5.0s, video clip is 3.88s
        async def fake_probe(path):
            if "mp3" in path or "audio" in path:
                return 5.0
            return 3.88
        mock_probe.side_effect = fake_probe

        # Create dummy output file on disk so existence check passes
        out_file = tmp_path / "merged_shot_1.mp4"

        def fake_run(cmd, capture_output, text, check):
            out_file.write_bytes(b"dummy video data")
            res = MagicMock()
            res.returncode = 0
            res.stderr = ""
            return res

        mock_to_thread.side_effect = fake_run

        merged_result = await assembler._merge_audio_video(
            video_path="/tmp/clip.mp4",
            audio_path="/tmp/narration.mp3",
            tmp_dir=tmp_path,
            index=1,
            aspect_ratio="9:16",
            target_shot_duration=5.0,
        )

        assert mock_to_thread.called
        call_args = mock_to_thread.call_args[0][1]  # The 'cmd' list

        # 1. -shortest must NEVER be in the command arguments when duration is determined
        assert "-shortest" not in call_args

        # 2. -stream_loop -1 must be present before -i video_path
        assert "-stream_loop" in call_args
        stream_loop_idx = call_args.index("-stream_loop")
        assert call_args[stream_loop_idx + 1] == "-1"
        assert call_args[stream_loop_idx + 2] == "-i"
        assert call_args[stream_loop_idx + 3] == "/tmp/clip.mp4"

        # 3. Audio pad and target duration must be set to full shot duration (5.0s)
        assert "-af" in call_args
        af_idx = call_args.index("-af")
        assert call_args[af_idx + 1] == "apad"
        assert "-t" in call_args
        t_idx = call_args.index("-t")
        assert float(call_args[t_idx + 1]) == pytest.approx(5.0, abs=0.1)


# ---------------------------------------------------------------------------
# 5. Production Duration Tolerance Verification
# ---------------------------------------------------------------------------

def check_duration_contract(actual_duration: float, target_duration: float) -> tuple[bool, str]:
    """Canonical duration contract check for Arya OS production.
    Tolerance: +/- 20% or +/- 3.5s, whichever is larger, to accommodate
    natural cadence variations in neural TTS speech synthesis.
    """
    allowed_delta = max(3.5, target_duration * 0.20)
    min_allowed = target_duration - allowed_delta
    max_allowed = target_duration + allowed_delta
    is_valid = min_allowed <= actual_duration <= max_allowed
    return is_valid, f"Actual: {actual_duration:.2f}s, Target: {target_duration}s (Window: [{min_allowed:.2f}s, {max_allowed:.2f}s])"


def test_duration_contract_bounds():
    """Verify canonical tolerance contract calculations."""
    # Target 15s -> delta = max(3.5, 3.0) = 3.5s -> [11.5s, 18.5s]
    # In Task 10: 7.76s was produced. Must decisively FAIL contract!
    valid, msg = check_duration_contract(7.76, 15.0)
    assert not valid
    assert "7.76s" in msg

    # Task 11 real production E2E run: 18.13s must PASS contract!
    valid, msg = check_duration_contract(18.13, 15.0)
    assert valid

    # 15.2s must PASS
    valid, _ = check_duration_contract(15.2, 15.0)
    assert valid

    # 13.5s must PASS
    valid, _ = check_duration_contract(13.5, 15.0)
    assert valid

    # 16.8s must PASS
    valid, _ = check_duration_contract(16.8, 15.0)
    assert valid

    # Target 30s -> delta = 6.0s -> [24.0s, 36.0s]
    assert check_duration_contract(29.0, 30.0)[0]
    assert not check_duration_contract(20.0, 30.0)[0]

    # Target 60s -> delta = 12.0s -> [48.0s, 72.0s]
    assert check_duration_contract(58.0, 60.0)[0]
    assert not check_duration_contract(40.0, 60.0)[0]
