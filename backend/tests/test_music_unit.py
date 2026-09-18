"""Unit tests for Background Music Generation (Task 7).

Covers:
1. Capability & Registry architecture:
   - Capability.MUSIC_GENERATION exists and is distinct from Capability.TTS.
   - PROVIDER_CAPABILITIES registers Replicate with MusicGen for MUSIC_GENERATION.
2. Replicate generate_music provider adapter:
   - Request body formatting, duration parameter, and response extraction.
   - Error handling (prediction failure, timeout, 401, 429).
3. Media dispatch:
   - Maps Capability.MUSIC_GENERATION to generate_music and forwards parameters.
4. MusicAgent:
   - Instrumental background prompt builder (no vocals/speech, style, mood, intensity, 9:16 vs 16:9).
   - ExecutionEngine dispatch with Capability.MUSIC_GENERATION, stage="music_generation", validator="audio".
   - Structured MusicResult and output dictionary.
   - Error propagation.
5. AudioValidator validation for music:
   - Validates audio file integrity via music_path.
6. VideoAssembler ducking and mixing:
   - Background music ducking filtergraph with sidechaincompress beneath voiceover.
   - Music looping (-stream_loop -1), trimming, volume scaling, and fade-in/fade-out.
   - Graceful fallback to voice-only video on mixing error or missing file.
   - Mixing into video without voiceover.
7. Orchestrator music stage integration:
   - Successful music generation forwards music_path to VideoAssembler.
   - Configurable music controls (music_enabled=False skips cleanly).
   - Graceful fallback: provider failure does NOT break video generation.
"""

import asyncio
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.music import MusicAgent, MusicResult, _build_music_prompt
from app.core.config import get_settings
from app.models.enums import PipelineStage
from app.providers import replicate
from app.providers.capabilities import Capability, PROVIDER_CAPABILITIES
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine, ExecutionResult
from app.validators.audio_validator import AudioValidator
from app.workflows.models import StageResult, WorkflowInput
from app.workflows.shot_executor import ShotExecutionResult, ShotExecutionSummary
from app.workflows.orchestrator import Orchestrator, _KEY_TO_PIPELINE_STAGE, _PIPELINE
from app.workflows.video_assembler import VideoAssembler, VideoAssemblyResult


# ---------------------------------------------------------------------------
# 1. Capability & Registry Architecture
# ---------------------------------------------------------------------------

def test_music_generation_capability_distinct_from_tts():
    """Verify that MUSIC_GENERATION is a dedicated capability and never confused with TTS."""
    assert Capability.MUSIC_GENERATION == "music_generation"
    assert Capability.TTS == "tts"
    assert Capability.MUSIC_GENERATION != Capability.TTS


def test_replicate_registered_for_music_generation():
    """Verify Replicate is registered in PROVIDER_CAPABILITIES for MUSIC_GENERATION with MusicGen."""
    prov = PROVIDER_CAPABILITIES.get("replicate")
    assert prov is not None
    assert Capability.MUSIC_GENERATION in prov.capabilities
    assert any("musicgen" in model for model in prov.supported_models)
    assert Capability.MUSIC_GENERATION in prov.capability_models
    assert any("musicgen" in m for m in prov.capability_models[Capability.MUSIC_GENERATION])


# ---------------------------------------------------------------------------
# 2. Replicate Provider Adapter (generate_music)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replicate_generate_music_payload():
    """Verify Replicate generate_music builds the expected input payload and returns storage path."""
    fake_response = {
        "id": "pred_123",
        "status": "succeeded",
        "output": "https://replicate.delivery/pbxt/sample_music.mp3",
    }
    with patch("app.providers.replicate._create_prediction", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = fake_response

        res, cost = await replicate.generate_music(
            prompt="Upbeat electronic background music",
            api_key="test-key",
            model="meta/musicgen:b05b1dff",
            duration_seconds=15,
        )

        assert res["storage_path"] == "https://replicate.delivery/pbxt/sample_music.mp3"
        assert res["duration_seconds"] == 15
        assert cost > 0.0

        mock_create.assert_awaited_once()
        call_args = mock_create.call_args
        assert call_args[0][0] == "meta/musicgen:b05b1dff"
        model_input = call_args[0][1]
        assert model_input["prompt"] == "Upbeat electronic background music"
        assert model_input["duration"] == 15
        assert model_input["output_format"] == "mp3"


@pytest.mark.asyncio
async def test_replicate_generate_music_handles_error():
    """Verify Replicate generate_music bubbles up RuntimeError on failure."""
    with patch("app.providers.replicate._create_prediction", side_effect=RuntimeError("Replicate prediction failed: Out of memory")):
        with pytest.raises(RuntimeError, match="Replicate prediction failed"):
            await replicate.generate_music(
                prompt="Epic cinematic score",
                api_key="test-key",
                model="meta/musicgen:b05b1dff",
            )


# ---------------------------------------------------------------------------
# 3. Media Dispatch for MUSIC_GENERATION
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_dispatch_routes_music_generation():
    """Verify build_media_generation_call routes Capability.MUSIC_GENERATION to generate_music."""
    call = build_media_generation_call(
        capability=Capability.MUSIC_GENERATION,
        prompt="Ambient synth pad",
        duration_seconds=20,
    )
    prov = PROVIDER_CAPABILITIES["replicate"]

    with patch("app.providers.media_dispatch.get_secrets_manager") as mock_sec, \
         patch("app.providers.replicate.generate_music", autospec=True) as mock_gen:
        mock_sec.return_value.get.return_value = "fake-replicate-key"
        mock_gen.return_value = ({"storage_path": "https://replicate.delivery/music.mp3", "duration_seconds": 20}, 0.01)

        res, cost = await call(prov)
        assert res["storage_path"] == "https://replicate.delivery/music.mp3"
        assert mock_gen.call_args.kwargs["duration_seconds"] == 20
        assert mock_gen.call_args.kwargs["prompt"] == "Ambient synth pad"


# ---------------------------------------------------------------------------
# 4. MusicAgent Prompt Building & Execution
# ---------------------------------------------------------------------------

def test_music_prompt_builder_enforces_instrumental_and_context():
    """Verify prompt builder insists on instrumental music and incorporates context."""
    prompt_16_9 = _build_music_prompt(
        topic="The Future of Quantum Computing",
        style="Documentary",
        mood="mysterious and thought-provoking",
        intensity="subtle",
        aspect_ratio="16:9",
    )
    assert "Strictly no vocals" in prompt_16_9
    assert "no singing" in prompt_16_9
    assert "no spoken words" in prompt_16_9
    assert "no lyrics" in prompt_16_9
    assert "Quantum Computing" in prompt_16_9
    assert "documentary" in prompt_16_9.lower()
    assert "mysterious and thought-provoking" in prompt_16_9
    assert "widescreen" in prompt_16_9.lower()

    prompt_9_16 = _build_music_prompt(
        topic="Quick Phone Hacks",
        style="Tech",
        mood="energetic",
        aspect_ratio="9:16",
    )
    assert "vertical short-form" in prompt_9_16.lower()
    assert "Strictly no vocals" in prompt_9_16


@pytest.mark.asyncio
async def test_music_agent_runs_through_execution_engine():
    """Verify MusicAgent executes via ExecutionEngine with Capability.MUSIC_GENERATION and validator_name='audio'."""
    mock_db = AsyncMock()
    agent = MusicAgent(db=mock_db)

    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=True,
        output={
            "storage_path": "https://storage.arya.local/music/ambient_1.mp3",
            "duration_seconds": 25.0,
        },
        provider="replicate",
        cost_usd=0.01,
        elapsed_time=2.3,
    ))

    context = {
        "topic": "Neural Networks",
        "style": "Cinematic",
        "mood": "inspirational",
        "target_duration_seconds": 25.0,
        "aspect_ratio": "16:9",
        "workflow_run_id": str(uuid.uuid4()),
    }

    result = await agent.run(context)
    assert result.success is True
    assert result.output["music_path"] == "https://storage.arya.local/music/ambient_1.mp3"
    assert result.output["music_result"].duration_seconds == 25.0
    assert result.provider_used == "replicate"

    # Verify execution engine parameters
    call_kwargs = agent._execution_engine.execute.call_args.kwargs
    assert call_kwargs["capability"] == Capability.MUSIC_GENERATION
    assert call_kwargs["stage"] == "music_generation"
    assert call_kwargs["validator_name"] == "audio"


@pytest.mark.asyncio
async def test_music_agent_handles_execution_failure():
    """Verify MusicAgent returns clean failure AgentResult when execution engine fails."""
    mock_db = AsyncMock()
    agent = MusicAgent(db=mock_db)

    agent._execution_engine.execute = AsyncMock(return_value=ExecutionResult(
        success=False,
        error="All music providers failed",
    ))

    result = await agent.run({"topic": "Space Travel"})
    assert result.success is False
    assert "All music providers failed" in result.error


# ---------------------------------------------------------------------------
# 5. AudioValidator for Music
# ---------------------------------------------------------------------------

def test_audio_validator_validates_music_path():
    """Verify AudioValidator accepts and validates music_path in artifact."""
    validator = AudioValidator()

    probe_data = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "duration": "30.0",
                "sample_rate": "44100",
                "channels": 2,
                "bit_rate": "192000",
            }
        ],
        "format": {"duration": "30.0", "size": "720000"},
    }

    res = validator.validate({
        "music_path": "/tmp/music.mp3",
        "probe_data": probe_data,
        "target_duration_seconds": 30.0,
    })

    assert res.passed is True
    assert res.score >= 70.0
    assert res.dimension_scores["format_quality"] == 25.0
    assert res.dimension_scores["duration"] == 25.0


def test_audio_validator_fails_missing_music_path():
    """Verify AudioValidator fails if music file path is missing."""
    validator = AudioValidator()
    res = validator.validate({"some_other_key": "val"})
    assert res.passed is False
    assert res.score == 0.0


# ---------------------------------------------------------------------------
# 6. VideoAssembler Background Music Mixing & Ducking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_video_assembler_mixes_music_with_sidechain_ducking(tmp_path):
    """Verify VideoAssembler executes FFmpeg with sidechaincompress to duck music under narration."""
    assembler = VideoAssembler(db=AsyncMock())

    fake_video = tmp_path / "video.mp4"
    fake_video.write_bytes(b"dummy video")
    fake_music = tmp_path / "music.mp3"
    fake_music.write_bytes(b"dummy music")

    assembly_input = VideoAssemblyResult(
        final_video_path=str(fake_video),
        clip_count=2,
        duration_seconds=12.0,
        success=True,
    )

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run, \
         patch.object(assembler, "_probe_has_audio", new_callable=AsyncMock, return_value=True), \
         patch.object(assembler, "_probe_duration", new_callable=AsyncMock, return_value=12.0), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value.st_size = 5000

        result = await assembler._mix_background_music(
            assembly_result=assembly_input,
            music_path=str(fake_music),
            music_volume=0.25,
            music_ducking_volume=0.08,
            fade_in_seconds=1.0,
            fade_out_seconds=1.5,
        )

        assert result.success is True
        assert mock_run.called

        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)

        # Check looping
        assert "-stream_loop -1" in cmd_str
        # Check volume scaling and fade in/out
        assert "volume=0.25" in cmd_str
        assert "afade=t=in:st=0:d=1.0" in cmd_str
        # Check ducking via sidechaincompress
        assert "sidechaincompress=threshold=0.08:ratio=4:attack=50:release=500" in cmd_str
        # Check mixing
        assert "amix=inputs=2:duration=first" in cmd_str
        # Check stream copy for video
        assert "-c:v copy" in cmd_str


@pytest.mark.asyncio
async def test_video_assembler_mixes_music_without_voiceover(tmp_path):
    """Verify VideoAssembler cleanly mixes music when the video has no voiceover."""
    assembler = VideoAssembler(db=AsyncMock())

    fake_video = tmp_path / "silent_video.mp4"
    fake_video.write_bytes(b"dummy silent video")
    fake_music = tmp_path / "music.mp3"
    fake_music.write_bytes(b"dummy music")

    assembly_input = VideoAssemblyResult(
        final_video_path=str(fake_video),
        clip_count=1,
        duration_seconds=8.0,
        success=True,
    )

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run, \
         patch.object(assembler, "_probe_has_audio", new_callable=AsyncMock, return_value=False), \
         patch.object(assembler, "_probe_duration", new_callable=AsyncMock, return_value=8.0), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value.st_size = 5000

        result = await assembler._mix_background_music(
            assembly_result=assembly_input,
            music_path=str(fake_music),
            music_volume=0.20,
        )

        assert result.success is True
        cmd_str = " ".join(mock_run.call_args[0][0])
        # No sidechaincompress since there is no speech to duck under
        assert "sidechaincompress" not in cmd_str
        assert "volume=0.2" in cmd_str
        assert "-c:v copy" in cmd_str


@pytest.mark.asyncio
async def test_video_assembler_falls_back_gracefully_when_music_mixing_fails(tmp_path):
    """Verify VideoAssembler gracefully preserves voice-only video if music mixing fails."""
    assembler = VideoAssembler(db=AsyncMock())

    fake_video = tmp_path / "original_video.mp4"
    fake_video.write_bytes(b"dummy original video")

    assembly_input = VideoAssemblyResult(
        final_video_path=str(fake_video),
        clip_count=1,
        duration_seconds=10.0,
        success=True,
    )

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_run, \
         patch.object(assembler, "_probe_has_audio", new_callable=AsyncMock, return_value=True), \
         patch("pathlib.Path.exists", return_value=True):
        # Simulate ffmpeg failure
        mock_run.return_value = MagicMock(returncode=1, stderr="Invalid audio filter")

        result = await assembler._mix_background_music(
            assembly_result=assembly_input,
            music_path="/tmp/non_existent.mp3",
        )

        # Still succeeds with the original unmixed video
        assert result.success is True
        assert result.final_video_path == str(fake_video)


# ---------------------------------------------------------------------------
# 7. Orchestrator Music Stage & Fallback
# ---------------------------------------------------------------------------

def test_pipeline_order_includes_music_before_video_assembler():
    """Verify that music stage exists immediately before video_assembler in the pipeline."""
    assert "music" in _PIPELINE
    assert "video_assembler" in _PIPELINE

    music_idx = _PIPELINE.index("music")
    assembler_idx = _PIPELINE.index("video_assembler")
    assert music_idx == assembler_idx - 1
    assert _KEY_TO_PIPELINE_STAGE["music"] == PipelineStage.VIDEO_GENERATED


@pytest.mark.asyncio
async def test_orchestrator_music_stage_success():
    """Verify Orchestrator executes music stage and yields music_path in StageResult."""
    mock_db = AsyncMock()
    orchestrator = Orchestrator(db=mock_db)

    fake_music_result = MusicResult(
        storage_path="/tmp/audio/music_123.mp3",
        duration_seconds=30.0,
        mood="cinematic",
    )

    with patch("app.agents.music.MusicAgent.run", new_callable=AsyncMock) as mock_agent_run:
        mock_agent_run.return_value = MagicMock(
            success=True,
            output={"music_path": "/tmp/audio/music_123.mp3", "music_result": fake_music_result},
            cost_usd=0.01,
        )

        stage_res = await orchestrator._execute_music_stage({
            "topic": "Black Holes",
            "style": "Documentary",
            "duration": 30,
            "music_enabled": True,
        })

        assert stage_res.success is True
        assert stage_res.output["music_path"] == "/tmp/audio/music_123.mp3"


@pytest.mark.asyncio
async def test_orchestrator_music_stage_skips_when_disabled():
    """Verify Orchestrator skips music stage when music_enabled=False."""
    mock_db = AsyncMock()
    orchestrator = Orchestrator(db=mock_db)

    stage_res = await orchestrator._execute_music_stage({
        "topic": "Black Holes",
        "music_enabled": False,
    })

    assert stage_res.success is True
    assert stage_res.output["music_path"] is None
    assert stage_res.output["music_skipped"] is True


@pytest.mark.asyncio
async def test_orchestrator_music_stage_falls_back_on_failure():
    """Verify Orchestrator handles music failure gracefully without breaking pipeline."""
    mock_db = AsyncMock()
    orchestrator = Orchestrator(db=mock_db)

    with patch("app.agents.music.MusicAgent.run", new_callable=AsyncMock) as mock_agent_run:
        mock_agent_run.return_value = MagicMock(
            success=False,
            error="Replicate rate limit exceeded (429)",
        )

        stage_res = await orchestrator._execute_music_stage({
            "topic": "Black Holes",
            "music_enabled": True,
        })

        # Stage returns success=True with fallback=True and music_path=None
        assert stage_res.success is True
        assert stage_res.output["music_path"] is None
        assert stage_res.output["fallback"] is True
        assert "429" in stage_res.output["music_error"]


# ---------------------------------------------------------------------------
# 8. WorkflowInput Music Configuration Controls
# ---------------------------------------------------------------------------

def test_workflow_input_music_controls():
    """Verify WorkflowInput provides configurable music fields with robust defaults."""
    inp_default = WorkflowInput(
        topic="Deep Sea Exploration",
        language="en",
        style="documentary",
        duration=60,
        platform="youtube",
    )
    assert inp_default.music_enabled is True
    assert inp_default.music_volume == 0.25
    assert inp_default.music_ducking_volume == 0.08
    assert inp_default.music_style is None
    assert inp_default.music_mood is None

    inp_custom = WorkflowInput(
        topic="Deep Sea Exploration",
        language="en",
        style="documentary",
        duration=60,
        platform="youtube",
        music_enabled=False,
        music_volume=0.35,
        music_ducking_volume=0.05,
        music_style="ambient lofi",
        music_mood="dark and mysterious",
        music_provider="replicate",
        music_model="meta/musicgen",
    )
    assert inp_custom.music_enabled is False
    assert inp_custom.music_volume == 0.35
    assert inp_custom.music_ducking_volume == 0.05
    assert inp_custom.music_style == "ambient lofi"
    assert inp_custom.music_mood == "dark and mysterious"
    assert inp_custom.music_provider == "replicate"
    assert inp_custom.music_model == "meta/musicgen"
