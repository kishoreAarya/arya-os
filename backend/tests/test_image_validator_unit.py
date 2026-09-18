"""Unit tests for ImageValidator.

Tests:
1. Hard failures (missing path, non-existent file, corrupted image file)
2. Blank / uniform solid color detection (low pixel entropy)
3. Sub-minimum resolution handling
4. Aspect ratio compliance checking
5. Vision model judge callable injection
6. Real Pillow image file creation and verification
"""
import os
import tempfile
from unittest.mock import patch

from PIL import Image
import pytest

from app.validators.image_validator import ImageValidator


def test_missing_image_path_fails_hard():
    validator = ImageValidator()
    result = validator.validate({})
    assert result.passed is False
    assert result.score == 0.0
    assert "No image file present to validate" in result.issues


def test_non_existent_file_fails():
    validator = ImageValidator()
    result = validator.validate({"storage_path": "/path/to/non_existent.png"})
    assert result.passed is False
    assert result.score == 0.0
    assert any("not found at path" in issue for issue in result.issues)


def test_corrupted_image_fails():
    validator = ImageValidator()
    result = validator.validate({
        "storage_path": "/images/corrupt.png",
        "mock_image_data": {"is_corrupt": True},
    })
    assert result.passed is False
    assert result.score == 0.0
    assert any("Corrupted image file" in issue for issue in result.issues)


def test_blank_solid_image_fails():
    validator = ImageValidator(min_stddev_variance=3.0)
    # stddev 0.5 is virtually a solid color (blank failure)
    result = validator.validate({
        "storage_path": "/images/black.png",
        "mock_image_data": {
            "width": 1024,
            "height": 1024,
            "format": "PNG",
            "mode": "RGB",
            "stddev": 0.5,
        },
    })
    assert result.passed is False
    assert result.score == 15.0
    assert any("blank or uniform solid color" in issue for issue in result.issues)


def test_valid_image_passes_with_dimensions():
    validator = ImageValidator()
    result = validator.validate({
        "storage_path": "/images/hero.png",
        "mock_image_data": {
            "width": 1024,
            "height": 1024,
            "format": "PNG",
            "mode": "RGB",
            "stddev": 42.0,
        },
    })
    assert result.passed is True
    assert result.score >= 80.0
    assert result.dimension_scores["file_integrity"] == 25.0
    assert result.dimension_scores["resolution"] == 30.0
    assert result.dimension_scores["visual_entropy"] == 20.0
    assert result.dimension_scores["content_compliance"] == 22.0


def test_sub_minimum_resolution_flags_issue():
    validator = ImageValidator(min_width=512, min_height=512)
    result = validator.validate({
        "storage_path": "/images/tiny.png",
        "mock_image_data": {
            "width": 200,
            "height": 200,
            "format": "PNG",
            "mode": "RGB",
            "stddev": 30.0,
        },
    })
    assert any("below minimum" in issue for issue in result.issues)


def test_aspect_ratio_mismatch_flags_issue():
    validator = ImageValidator()
    # 1024x1024 is 1:1, but user requested 16:9
    result = validator.validate({
        "storage_path": "/images/square.png",
        "aspect_ratio": "16:9",
        "mock_image_data": {
            "width": 1024,
            "height": 1024,
            "format": "PNG",
            "mode": "RGB",
            "stddev": 35.0,
        },
    })
    assert any("Aspect ratio" in issue for issue in result.issues)


def test_vision_judge_callable_integration():
    def mock_vision_judge(path, artifact):
        return {"score": 25.0, "issues": []}

    validator = ImageValidator(vision_judge_callable=mock_vision_judge)
    result = validator.validate({
        "storage_path": "/images/scene.png",
        "mock_image_data": {
            "width": 1920,
            "height": 1080,
            "format": "PNG",
            "mode": "RGB",
            "stddev": 40.0,
        },
    })
    assert result.passed is True
    assert result.dimension_scores["content_compliance"] == 25.0


def test_real_pillow_file_inspection():
    validator = ImageValidator()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        temp_path = tf.name

    try:
        # Create a real 512x512 gradient image using Pillow
        img = Image.new("RGB", (512, 512))
        for x in range(512):
            for y in range(512):
                img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
        img.save(temp_path, format="PNG")

        result = validator.validate({"storage_path": temp_path})
        assert result.passed is True
        assert result.score >= 75.0
        assert result.dimension_scores["file_integrity"] == 25.0
        assert result.dimension_scores["visual_entropy"] == 20.0
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
