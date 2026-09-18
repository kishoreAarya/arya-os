"""Unit tests for ThumbnailValidator.

Tests:
1. Hard failures (missing path, non-existent file)
2. File size exceeding YouTube 2MB limit
3. Sub-minimum resolution
4. Aspect ratio compliance (16:9)
5. Blank thumbnail detection
6. Valid YouTube thumbnail scoring and dimension breakdown
"""
import pytest
from app.validators.thumbnail_validator import ThumbnailValidator


def test_missing_thumbnail_path_fails_hard():
    validator = ThumbnailValidator()
    result = validator.validate({})
    assert result.passed is False
    assert result.score == 0.0
    assert "No thumbnail file present" in result.issues


def test_non_existent_file_fails():
    validator = ThumbnailValidator()
    result = validator.validate({"storage_path": "/thumbnails/missing.jpg"})
    assert result.passed is False
    assert result.score == 0.0
    assert any("not found at path" in issue for issue in result.issues)


def test_file_size_exceeding_2mb_flagged():
    validator = ThumbnailValidator()
    # 3MB file
    result = validator.validate({
        "storage_path": "/thumbnails/huge.jpg",
        "mock_image_data": {
            "width": 1280,
            "height": 720,
            "format": "JPEG",
            "file_size": 3 * 1024 * 1024,
            "stddev": 35.0,
        },
    })
    assert any("exceeds YouTube maximum" in issue for issue in result.issues)


def test_resolution_below_minimum_flagged():
    validator = ThumbnailValidator(min_width=640, min_height=360)
    result = validator.validate({
        "storage_path": "/thumbnails/lowres.jpg",
        "mock_image_data": {
            "width": 320,
            "height": 180,
            "format": "JPEG",
            "file_size": 50_000,
            "stddev": 30.0,
        },
    })
    assert any("below YouTube minimum" in issue for issue in result.issues)


def test_aspect_ratio_non_16_9_flagged():
    validator = ThumbnailValidator()
    # Square 1080x1080
    result = validator.validate({
        "storage_path": "/thumbnails/square.jpg",
        "mock_image_data": {
            "width": 1080,
            "height": 1080,
            "format": "JPEG",
            "file_size": 300_000,
            "stddev": 30.0,
        },
    })
    assert any("Aspect ratio" in issue for issue in result.issues)


def test_blank_thumbnail_fails():
    validator = ThumbnailValidator()
    result = validator.validate({
        "storage_path": "/thumbnails/white.jpg",
        "mock_image_data": {
            "width": 1280,
            "height": 720,
            "format": "JPEG",
            "file_size": 100_000,
            "stddev": 1.0,  # blank
        },
    })
    assert result.passed is False
    assert result.score == 10.0
    assert any("blank" in issue for issue in result.issues)


def test_valid_youtube_thumbnail_passes():
    validator = ThumbnailValidator()
    result = validator.validate({
        "storage_path": "/thumbnails/good.jpg",
        "mock_image_data": {
            "width": 1280,
            "height": 720,
            "format": "JPEG",
            "file_size": 450_000,
            "stddev": 40.0,
        },
    })
    assert result.passed is True
    assert result.score >= 80.0
    assert result.dimension_scores["resolution"] == 30.0
    assert result.dimension_scores["aspect_ratio"] == 25.0
    assert result.dimension_scores["contrast"] == 25.0
    assert result.dimension_scores["file_specs"] == 20.0
