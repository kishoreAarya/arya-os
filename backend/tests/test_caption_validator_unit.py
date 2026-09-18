"""Unit tests for CaptionValidator and its integration with VideoValidator."""

import pytest

from app.schemas.cinematic import CaptionSegment, CaptionTimeline
from app.validators import VALIDATOR_REGISTRY
from app.validators.caption_validator import CaptionValidator
from app.validators.video_validator import VideoValidator


def test_caption_validator_registered():
    assert "caption" in VALIDATOR_REGISTRY
    assert isinstance(VALIDATOR_REGISTRY["caption"], CaptionValidator)


def test_caption_validator_valid_segments_pass():
    val = CaptionValidator(captions_required=True)
    segments = [
        CaptionSegment(
            segment_index=0,
            text="The ancient house stood silent.",
            start_seconds=0.0,
            end_seconds=2.5,
            duration_seconds=2.5,
        ),
        CaptionSegment(
            segment_index=1,
            text="Then the floorboards creaked.",
            start_seconds=2.8,
            end_seconds=5.0,
            duration_seconds=2.2,
        ),
    ]
    artifact = {
        "captions": [s.model_dump() for s in segments],
        "video_duration_seconds": 5.5,
        "captions_required": True,
    }
    result = val.validate(artifact)
    assert result.passed is True
    assert result.score == 100.0
    assert "captions present" in result.notes
    assert len(result.issues) == 0


def test_caption_validator_distinguishes_absent_optional_vs_mandatory():
    # 1. Optional (legacy workflow): passes cleanly
    val_opt = CaptionValidator(captions_required=False)
    res_opt = val_opt.validate({"captions": [], "captions_required": False})
    assert res_opt.passed is True
    assert "captions absent" in res_opt.notes

    # 2. Mandatory (cinematic workflow): fails hard
    val_mand = CaptionValidator(captions_required=True)
    res_mand = val_mand.validate({"captions": [], "captions_required": True})
    assert res_mand.passed is False
    assert res_mand.score == 0.0
    assert "captions absent" in res_mand.notes
    assert any("mandatory" in i.lower() for i in res_mand.issues)


def test_caption_validator_detects_invalid_timestamps():
    val = CaptionValidator(captions_required=True)
    # Negative start, impossible duration (end < start), beyond video duration
    bad_segments = [
        {
            "segment_index": 0,
            "text": "Negative start timestamp.",
            "start_seconds": -1.0,
            "end_seconds": 2.0,
            "duration_seconds": 3.0,
        },
        {
            "segment_index": 1,
            "text": "Impossible duration.",
            "start_seconds": 3.0,
            "end_seconds": 2.5,
            "duration_seconds": -0.5,
        },
        {
            "segment_index": 2,
            "text": "Extends beyond video.",
            "start_seconds": 4.0,
            "end_seconds": 10.0,
            "duration_seconds": 6.0,
        },
    ]
    artifact = {
        "captions": bad_segments,
        "video_duration_seconds": 5.0,
        "captions_required": True,
    }
    result = val.validate(artifact)
    assert result.passed is False
    assert "captions invalid" in result.notes
    assert any("negative start" in i.lower() for i in result.issues)
    assert any("impossible duration" in i.lower() for i in result.issues)
    assert any("extends beyond video duration" in i.lower() for i in result.issues)


def test_caption_validator_detects_empty_text_and_excessive_length():
    val = CaptionValidator(captions_required=True)
    bad_segments = [
        CaptionSegment(
            segment_index=0,
            text="   ",
            start_seconds=0.0,
            end_seconds=2.0,
            duration_seconds=2.0,
        ),
        CaptionSegment(
            segment_index=1,
            text="This is an absurdly long subtitle line that definitely exceeds the forty-eight character readability limit for mobile vertical shorts.",
            start_seconds=2.5,
            end_seconds=4.5,
            duration_seconds=2.0,
        ),
        CaptionSegment(
            segment_index=2,
            text="Line one.\nLine two.\nLine three is too many lines.",
            start_seconds=4.8,
            end_seconds=6.5,
            duration_seconds=1.7,
        ),
    ]
    artifact = {
        "captions": [s.model_dump() for s in bad_segments],
        "video_duration_seconds": 7.0,
        "captions_required": True,
    }
    result = val.validate(artifact)
    assert result.passed is False
    assert any("empty text" in i.lower() for i in result.issues)
    assert any("exceeds 48 chars" in i.lower() for i in result.issues)
    assert any("exceeds maximum 2 lines" in i.lower() for i in result.issues)


def test_video_validator_integration_with_captions():
    # VideoValidator with captions_required=True requires valid captions
    probe_mock = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "25/1", "duration": "5.0"},
            {"codec_type": "audio", "codec_name": "aac", "duration": "5.0"},
        ],
        "format": {"duration": "5.0"},
    }

    # 1. Missing captions with captions_required=True -> fails
    val_mandatory = VideoValidator(probe_fn=lambda _: probe_mock, captions_required=True)
    res_fail = val_mandatory.validate({
        "video_storage_path": "/fake/video.mp4",
        "duration_seconds": 5.0,
        "aspect_ratio": "9:16",
        "captions": [],
        "captions_required": True,
    })
    assert res_fail.passed is False
    assert any("captions are mandatory" in i.lower() for i in res_fail.issues)

    # 2. Missing captions with captions_required=False -> passes (legacy compatibility)
    val_legacy = VideoValidator(probe_fn=lambda _: probe_mock, captions_required=False)
    res_pass = val_legacy.validate({
        "video_storage_path": "/fake/video.mp4",
        "duration_seconds": 5.0,
        "aspect_ratio": "9:16",
        "captions_required": False,
    })
    assert res_pass.passed is True

    # 3. Valid captions with captions_required=True -> passes
    valid_caps = [
        CaptionSegment(
            segment_index=0,
            text="The dark hallway stretched out.",
            start_seconds=0.5,
            end_seconds=4.0,
            duration_seconds=3.5,
        ).model_dump()
    ]
    res_cinematic_pass = val_mandatory.validate({
        "video_storage_path": "/fake/video.mp4",
        "duration_seconds": 5.0,
        "aspect_ratio": "9:16",
        "captions": valid_caps,
        "captions_required": True,
    })
    assert res_cinematic_pass.passed is True
    assert res_cinematic_pass.dimension_scores.get("captions") == 100.0
