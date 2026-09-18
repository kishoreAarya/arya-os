"""Unit tests for Creator Presets and preset integration in WorkflowInput."""

import pytest
from pydantic import ValidationError

from app.core.presets import (
    CREATOR_PRESETS,
    CreatorPreset,
    get_preset,
    list_presets,
)
from app.workflows.models import WorkflowInput


def test_list_presets_returns_registry():
    presets = list_presets()
    assert isinstance(presets, dict)
    assert "documentary_short" in presets
    assert "cosmic_explainer" in presets
    assert "deep_sea_wonders" in presets
    assert "landscape_documentary" in presets


def test_get_preset_success():
    preset = get_preset("documentary_short")
    assert isinstance(preset, CreatorPreset)
    assert preset.aspect_ratio == "9:16"
    assert preset.duration == 20
    assert preset.music_enabled is True
    assert preset.music_volume == 0.20
    assert preset.music_ducking_volume == 0.06


def test_get_preset_case_insensitive():
    preset = get_preset("DOCUMENTARY_SHORT")
    assert preset.name == "documentary_short"


def test_get_preset_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown preset"):
        get_preset("non_existent_preset_xyz")


def test_get_preset_empty_raises_value_error():
    with pytest.raises(ValueError, match="cannot be empty"):
        get_preset("")


def test_workflow_input_with_preset_applies_defaults():
    inp = WorkflowInput(
        topic="Immortal Jellyfish",
        preset="documentary_short",
    )
    assert inp.topic == "Immortal Jellyfish"
    assert inp.preset == "documentary_short"
    assert inp.duration == 20
    assert inp.aspect_ratio == "9:16"
    assert "cinematic documentary" in inp.style
    assert inp.music_enabled is True
    assert inp.music_volume == 0.20
    assert inp.music_ducking_volume == 0.06
    assert inp.music_style == "ambient cinematic instrumental"


def test_workflow_input_preset_with_overrides():
    inp = WorkflowInput(
        topic="Immortal Jellyfish",
        preset="documentary_short",
        duration=25,
        aspect_ratio="16:9",
        music_volume=0.35,
    )
    assert inp.duration == 25
    assert inp.aspect_ratio == "16:9"
    assert inp.music_volume == 0.35
    # Non-overridden fields still come from preset
    assert inp.music_ducking_volume == 0.06
    assert "cinematic documentary" in inp.style


def test_workflow_input_without_preset_requires_style_and_duration():
    with pytest.raises(ValidationError) as exc_info:
        WorkflowInput(topic="Just Topic")
    errors = str(exc_info.value)
    assert "style" in errors or "duration" in errors


def test_workflow_input_without_preset_succeeds_when_fields_provided():
    inp = WorkflowInput(
        topic="Explicit Parameters",
        language="en",
        style="educational",
        duration=15,
        platform="youtube",
        aspect_ratio="9:16",
    )
    assert inp.preset is None
    assert inp.style == "educational"
    assert inp.duration == 15
    assert inp.aspect_ratio == "9:16"
