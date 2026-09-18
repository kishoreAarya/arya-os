"""Unit tests for VideoValidator.

Tests:
1. Hard failures (missing path, non-existent file, corrupted container)
2. Missing video stream
3. Zero / negative duration
4. Resolution compliance and sub-minimum resolution handling
5. Frame rate parsing and bounds checking
6. Audio / video sync drift detection
7. Custom probe function injection
"""
from unittest.mock import MagicMock, patch

import pytest
from app.validators.video_validator import VideoValidator, _parse_fps


def test_parse_fps_helper():
    assert _parse_fps("30/1") == 30.0
    assert _parse_fps("24000/1001") == 23.98
    assert _parse_fps(60.0) == 60.0
    assert _parse_fps(None) is None
    assert _parse_fps("invalid") is None


def test_missing_video_path_fails_hard():
    validator = VideoValidator()
    result = validator.validate({})
    assert result.passed is False
    assert result.score == 0.0
    assert "Missing video file path" in result.issues


def test_non_existent_file_fails():
    validator = VideoValidator()
    result = validator.validate({"storage_path": "/non/existent/path/clip.mp4"})
    assert result.passed is False
    assert result.score == 0.0
    assert any("not found at path" in issue for issue in result.issues)


def test_corrupted_file_fails():
    validator = VideoValidator()
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "Invalid data found when processing input"

    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_run):
        result = validator.validate({"storage_path": "/videos/corrupted.mp4"})

    assert result.passed is False
    assert result.score == 0.0
    assert any("Corrupted video file" in issue for issue in result.issues)


def test_missing_video_stream_fails():
    validator = VideoValidator()
    audio_only_probe = {
        "streams": [{"codec_type": "audio", "codec_name": "aac", "duration": "5.0"}],
        "format": {"duration": "5.0"},
    }
    result = validator.validate({
        "storage_path": "/videos/no_video.mp4",
        "probe_data": audio_only_probe,
    })
    assert result.passed is False
    assert result.score == 0.0
    assert "No valid video stream found in media file" in result.issues


def test_zero_duration_fails():
    validator = VideoValidator()
    probe_data = {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "0.0"}],
        "format": {"duration": "0.0"},
    }
    result = validator.validate({
        "storage_path": "/videos/zero_len.mp4",
        "probe_data": probe_data,
    })
    assert result.passed is False
    assert result.score == 0.0
    assert "Zero or negative video duration" in result.issues


def test_valid_video_passes_with_dimensions():
    validator = VideoValidator()
    valid_probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "duration": "10.0",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "duration": "10.0",
            }
        ],
        "format": {"duration": "10.0"},
    }
    result = validator.validate({
        "storage_path": "/videos/valid.mp4",
        "probe_data": valid_probe,
    })
    assert result.passed is True
    assert result.score >= 80.0
    assert result.dimension_scores["stream_integrity"] == 25.0
    assert result.dimension_scores["resolution"] == 25.0
    assert result.dimension_scores["frame_rate"] == 15.0
    assert result.dimension_scores["duration"] == 20.0
    assert result.dimension_scores["audio_sync"] == 15.0


def test_av_sync_drift_detected():
    validator = VideoValidator(max_av_sync_drift_seconds=1.0)
    # Video is 10.0s, Audio is 6.0s (drift 4.0s)
    drift_probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "30/1",
                "duration": "10.0",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "duration": "6.0",
            }
        ],
        "format": {"duration": "10.0"},
    }
    result = validator.validate({
        "storage_path": "/videos/drift.mp4",
        "probe_data": drift_probe,
    })
    assert result.passed is False
    assert any("A/V duration drift" in issue for issue in result.issues)


def test_sub_minimum_resolution_flags_issue():
    validator = VideoValidator(min_width=480, min_height=480)
    low_res_probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 320,
                "height": 240,
                "r_frame_rate": "24/1",
                "duration": "5.0",
            }
        ],
        "format": {"duration": "5.0"},
    }
    result = validator.validate({
        "storage_path": "/videos/lowres.mp4",
        "probe_data": low_res_probe,
    })
    assert any("below minimum" in issue for issue in result.issues)
