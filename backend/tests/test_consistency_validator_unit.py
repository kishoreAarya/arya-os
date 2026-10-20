"""Unit tests for ConsistencyValidator.

Tests:
1. Placeholder contract verification (evaluates image_paths dict).
2. Interface incompatibility documentation (demonstrates that passing a text/str
   artifact raises AttributeError because ConsistencyValidator expects a dictionary
   with image_paths, making it incompatible with text generation stages).
"""

from __future__ import annotations

import pytest

from app.validators.base import ValidationResult
from app.validators.consistency_validator import ConsistencyValidator


def test_consistency_validator_placeholder_contract():
    """Verify current ConsistencyValidator placeholder passes with score 70.0."""
    validator = ConsistencyValidator()

    # With multiple image paths
    res_multi = validator.validate({"image_paths": ["/tmp/shot1.png", "/tmp/shot2.png"]})
    assert isinstance(res_multi, ValidationResult)
    assert res_multi.passed is True
    assert res_multi.score == 70.0
    assert res_multi.dimension_scores == {"consistency": 70.0}

    # With empty dict
    res_empty = validator.validate({})
    assert res_empty.passed is True
    assert res_empty.score == 70.0


def test_consistency_validator_incompatible_with_raw_text_artifact():
    """Verify that ConsistencyValidator requires a dict and raises AttributeError on raw text.

    This documents the architectural finding: ConsistencyValidator was designed as an
    image-path identity checker, not a storyboard text/plan validator.
    """
    validator = ConsistencyValidator()
    raw_storyboard_text = '{"shots": [{"shot_number": 1, "description": "Close up"}]}'

    with pytest.raises(AttributeError):
        # artifact is a string from text generation; ConsistencyValidator calls artifact.get(...)
        validator.validate(raw_storyboard_text)  # type: ignore[arg-type]
