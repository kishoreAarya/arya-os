"""Comprehensive integration unit tests for Task 16.

Covers:
1. voice -> timing -> captions
2. director -> sound design -> SFX
3. assembly -> captions -> validation
4. audio mix hierarchy (voice priority, SFX placement, music ducking, silence, limiter)
5. non-cinematic legacy pipeline preservation
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.captions import build_caption_timeline
from app.core.sound_design import SoundDesignManager
from app.core.sound_resolver import SoundAssetResolver
from app.schemas.cinematic import (
    AmbientSoundIntent,
    CaptionStyle,
    CaptionTimeline,
    FoleyEvent,
    MasterAudioPlan,
    NarrationSegment,
    NarrationTiming,
    SilenceInterval,
    WordTiming,
)
from app.validators.caption_validator import CaptionValidator
from app.validators.video_validator import VideoValidator
from app.workflows.shot_executor import ShotExecutionResult, ShotExecutionSummary
from app.workflows.video_assembler import VideoAssembler, VideoAssemblyResult


def test_voice_to_timing_to_captions_pipeline():
    # 1. Voice timing generated
    words = [
        WordTiming(word="The", start_seconds=0.0, end_seconds=0.2),
        WordTiming(word="door", start_seconds=0.2, end_seconds=0.6),
        WordTiming(word="creaked", start_seconds=0.6, end_seconds=1.2),
        WordTiming(word="open.", start_seconds=1.2, end_seconds=1.8),
        WordTiming(word="Silence", start_seconds=2.4, end_seconds=3.0),
        WordTiming(word="followed.", start_seconds=3.0, end_seconds=3.8),
    ]
    narration_timing = NarrationTiming(
        text="The door creaked open. Silence followed.",
        total_duration_seconds=4.0,
        has_real_timestamps=True,
        words=words,
    )

    # 2. Build captions
    timeline = build_caption_timeline(narration_timing, video_duration=4.5)
    assert isinstance(timeline, CaptionTimeline)
    assert len(timeline.segments) >= 2

    # 3. Validate captions
    validator = CaptionValidator(captions_required=True)
    res = validator.validate({
        "captions": [s.model_dump() for s in timeline.segments],
        "video_duration_seconds": 4.5,
        "voice_duration_seconds": 4.0,
        "captions_required": True,
    })
    assert res.passed is True
    assert res.score == 100.0


def test_director_to_sound_design_to_sfx_resolver():
    tmp_dir = Path(tempfile.mkdtemp())
    resolver = SoundAssetResolver(assets_dir=tmp_dir)

    # Director requested audio plan
    master_plan = MasterAudioPlan(
        ambient_layers=[AmbientSoundIntent(environment="wind", duration=6.0)],
        foley_events=[
            FoleyEvent(event="door_creak", start_time=1.5, duration=2.0),
            FoleyEvent(event="footsteps", start_time=3.5, duration=2.5),
        ],
        silence_intervals=[SilenceInterval(silence_start=3.0, silence_duration=0.5, reason="tension")],
    )

    # Resolve all sound cues
    res = resolver.resolve_master_plan(master_plan)
    assert len(res.resolved_ambient) == 1
    assert len(res.resolved_foley) == 2
    assert master_plan.ambient_layers[0].source_path is not None
    assert master_plan.foley_events[0].source_path is not None
    assert master_plan.foley_events[1].source_path is not None


def test_audio_mix_hierarchy_and_filtergraph():
    sd = SoundDesignManager()
    silence = [SilenceInterval(silence_start=2.0, silence_duration=1.0, reason="shock")]
    ambient = [(3, AmbientSoundIntent(environment="room_tone", duration=5.0, volume=0.08))]
    foley = [(4, FoleyEvent(event="heartbeat", start_time=1.2, duration=2.0, volume=0.4))]

    fg, out_map = sd.build_audio_filtergraph(
        video_duration=5.0,
        voice_input_idx=1,
        music_input_idx=2,
        music_volume=0.20,
        music_ducking_volume=0.06,
        ambient_inputs=ambient,
        foley_inputs=foley,
        silence_intervals=silence,
    )

    # 1. Voice at 0dB (uncompressed volume=1.0)
    assert "[1:a]volume=1.0[voice_track]" in fg
    # 2. Ambient bed (~ -22dB, volume=0.08)
    assert "volume=0.08" in fg
    # 3. Foley timestamped with adelay (1.2s -> 1200ms)
    assert "adelay=1200|1200" in fg
    # 4. Music silence gating
    assert "between(t,2.00,3.00)" in fg
    # 5. Sidechain ducking under voice
    assert "sidechaincompress=" in fg
    # 6. Master limiter
    assert "alimiter=limit=0.95" in fg


@pytest.mark.asyncio
async def test_assembly_burns_captions_and_passes_validation():
    # Verify that VideoAssembler calls caption burn-in and passes VideoValidator
    db_mock = MagicMock()
    assembler = VideoAssembler(db=db_mock)

    summary = ShotExecutionSummary(
        results=[
            ShotExecutionResult(
                shot_number=1,
                video_path="/fake/clip1.mp4",
                duration_seconds=3.0,
            ),
            ShotExecutionResult(
                shot_number=2,
                video_path="/fake/clip2.mp4",
                duration_seconds=3.0,
            ),
        ]
    )

    narration_timing = NarrationTiming(
        text="A single candle flickered on the altar. The door opened.",
        total_duration_seconds=6.0,
        has_real_timestamps=False,
        segments=[
            NarrationSegment(
                segment_index=0,
                text="A single candle flickered on the altar.",
                start_seconds=0.0,
                end_seconds=3.2,
                duration_seconds=3.2,
                words=[],
            ),
            NarrationSegment(
                segment_index=1,
                text="The door opened.",
                start_seconds=3.5,
                end_seconds=5.8,
                duration_seconds=2.3,
                words=[],
            ),
        ],
    )

    with patch.object(assembler, "_resolve_local_path", new=AsyncMock(side_effect=lambda u, d, e: str(Path(tempfile.gettempdir()) / "mock.mp4"))), \
         patch.object(assembler, "_normalize_video_clip", new=AsyncMock(return_value="/tmp/norm.mp4")), \
         patch.object(assembler, "_concatenate", new=AsyncMock(return_value=VideoAssemblyResult(final_video_path="/tmp/concat.mp4", clip_count=2, duration_seconds=6.0, success=True))), \
         patch.object(assembler, "_apply_fade", new=AsyncMock(side_effect=lambda r: r)), \
         patch("app.core.captions.burn_captions_to_video", new=AsyncMock(return_value="/tmp/captioned.mp4")):

        res = await assembler.assemble(
            summary=summary,
            aspect_ratio="9:16",
            narration_timing=narration_timing,
            captions_enabled=True,
            captions_required=True,
        )

        assert res.success is True
        assert res.captions_burned_in is True
        assert res.final_video_path == "/tmp/captioned.mp4"
        assert res.captions is not None
        assert len(res.captions) >= 2

        # Validate with VideoValidator
        probe_mock = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "25/1", "duration": "6.0"},
                {"codec_type": "audio", "codec_name": "aac", "duration": "6.0"},
            ],
            "format": {"duration": "6.0"},
        }
        val_res = VideoValidator(probe_fn=lambda _: probe_mock, captions_required=True).validate({
            "video_storage_path": res.final_video_path,
            "duration_seconds": 6.0,
            "aspect_ratio": "9:16",
            "captions": res.captions,
            "captions_required": True,
        })
        assert val_res.passed is True


@pytest.mark.asyncio
async def test_legacy_non_cinematic_pipeline_remains_functional():
    # Non-cinematic workflows (no captions_required, no narration_timing) must succeed as before
    db_mock = MagicMock()
    assembler = VideoAssembler(db=db_mock)

    summary = ShotExecutionSummary(
        results=[
            ShotExecutionResult(shot_number=1, video_path="/fake/clip1.mp4", duration_seconds=2.0),
        ]
    )

    dummy_norm = Path(tempfile.gettempdir()) / "dummy_norm.mp4"
    dummy_norm.write_bytes(b"dummy")

    with patch.object(assembler, "_resolve_local_path", new=AsyncMock(side_effect=lambda u, d, e: "/tmp/mock.mp4")), \
         patch.object(assembler, "_normalize_video_clip", new=AsyncMock(return_value=str(dummy_norm))), \
         patch.object(assembler, "_probe_duration", new=AsyncMock(return_value=2.0)), \
         patch.object(assembler, "_apply_fade", new=AsyncMock(side_effect=lambda r: r)):

        res = await assembler.assemble(
            summary=summary,
            aspect_ratio="16:9",
            captions_enabled=False,
            captions_required=False,
        )
        assert res.success is True
        assert res.captions_burned_in is False

        # Legacy VideoValidator passes cleanly without captions
        probe_mock = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1", "duration": "2.0"},
                {"codec_type": "audio", "codec_name": "aac", "duration": "2.0"},
            ],
            "format": {"duration": "2.0"},
        }
        val_res = VideoValidator(probe_fn=lambda _: probe_mock, captions_required=False).validate({
            "video_storage_path": res.final_video_path,
            "duration_seconds": 2.0,
            "aspect_ratio": "16:9",
            "captions_required": False,
        })
        assert val_res.passed is True
