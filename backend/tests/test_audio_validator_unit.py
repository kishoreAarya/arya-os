"""Unit tests for AudioValidator.

Tests:
1. Hard failures (missing path, non-existent file, 0-byte file, corrupted audio container)
2. Missing audio stream
3. Zero / negative duration
4. Severe speech truncation detection (text vs audio duration mismatch)
5. Low sample rate detection
6. Valid speech audio scoring and dimension breakdown
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from app.validators.audio_validator import AudioValidator


def test_missing_audio_path_fails_hard():
    validator = AudioValidator()
    result = validator.validate({})
    assert result.passed is False
    assert result.score == 0.0
    assert "No audio file path provided" in result.issues[0]


def test_non_existent_file_fails():
    validator = AudioValidator()
    result = validator.validate({"storage_path": "/audio/not_found.mp3"})
    assert result.passed is False
    assert result.score == 0.0
    assert any("not found at path" in issue for issue in result.issues)


def test_empty_0_byte_file_fails():
    validator = AudioValidator()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        empty_path = tf.name

    try:
        result = validator.validate({"storage_path": empty_path})
        assert result.passed is False
        assert result.score == 0.0
        assert any("0 bytes" in issue for issue in result.issues)
    finally:
        if os.path.exists(empty_path):
            os.remove(empty_path)


def test_corrupted_audio_file_fails():
    validator = AudioValidator()
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "Invalid audio header found"

    with patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=1024), \
         patch("subprocess.run", return_value=mock_run):
        result = validator.validate({"storage_path": "/audio/corrupt.mp3"})

    assert result.passed is False
    assert result.score == 0.0
    assert any("Corrupted audio file" in issue for issue in result.issues)


def test_missing_audio_stream_fails():
    validator = AudioValidator()
    result = validator.validate({
        "storage_path": "/audio/silent.mp4",
        "probe_data": {"streams": [], "format": {"duration": "5.0"}},
    })
    assert result.passed is False
    assert result.score == 0.0
    assert "No valid audio stream found in media file" in result.issues


def test_zero_duration_fails():
    validator = AudioValidator()
    result = validator.validate({
        "storage_path": "/audio/zero.mp3",
        "probe_data": {
            "streams": [{"codec_type": "audio", "codec_name": "mp3", "duration": "0.0"}],
            "format": {"duration": "0.0"},
        },
    })
    assert result.passed is False
    assert result.score == 0.0
    assert "Zero or negative audio duration" in result.issues


def test_valid_speech_audio_passes():
    validator = AudioValidator()
    probe_data = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "8.5",
                "bit_rate": "192000",
            }
        ],
        "format": {"duration": "8.5", "bit_rate": "192000"},
    }
    result = validator.validate({
        "storage_path": "/audio/speech.mp3",
        "probe_data": probe_data,
    })
    assert result.passed is True
    assert result.score >= 80.0
    assert result.dimension_scores["file_integrity"] == 30.0
    assert result.dimension_scores["format_quality"] == 25.0
    assert result.dimension_scores["duration"] == 25.0
    assert result.dimension_scores["audio_level"] == 20.0


def test_severe_speech_truncation_flagged():
    validator = AudioValidator()
    # 50-word script narrated in 0.6s (impossible speed; TTS was cut off!)
    long_script = "word " * 50
    probe_data = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 1,
                "duration": "0.6",
            }
        ],
        "format": {"duration": "0.6"},
    }
    result = validator.validate({
        "storage_path": "/audio/cut_off.aac",
        "script_content": long_script,
        "probe_data": probe_data,
    })
    assert any("severely truncated" in issue for issue in result.issues)


def test_sub_minimum_sample_rate_flagged():
    validator = AudioValidator(min_sample_rate=16000)
    low_sr_probe = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "8000",
                "channels": 1,
                "duration": "4.0",
            }
        ],
        "format": {"duration": "4.0"},
    }
    result = validator.validate({
        "storage_path": "/audio/telephone.mp3",
        "probe_data": low_sr_probe,
    })
    assert any("Sample rate" in issue for issue in result.issues)
