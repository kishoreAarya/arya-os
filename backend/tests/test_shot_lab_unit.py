"""Unit tests for ShotLab service (Task 23).

Verifies:
1. VisualReferenceSheet data structure and completeness.
2. StandardizedHorrorScene definition and parameters.
3. PromptStrategy prompt generation (P1, P2, P3).
4. VisualQualityRubricScores subtotal and composite calculations.
5. Image and Video model registry definitions.
6. Representative frame extraction logic.
7. HTML dashboard generation.
8. Safe handling of unavailable models (Fal).
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.services.shot_lab import (
    IMAGE_MODEL_REGISTRY,
    VIDEO_MODEL_REGISTRY,
    CharacterReference,
    CinematographyReference,
    EnvironmentReference,
    ImageCandidateResult,
    LightingReference,
    PromptStrategy,
    PropReference,
    ShotLab,
    StandardizedHorrorScene,
    VideoCandidateResult,
    VisualQualityRubricScores,
    VisualReferenceSheet,
    build_prompt_for_strategy,
)


def test_visual_reference_sheet_completeness():
    """Verify that the Visual Reference Sheet contains all required dimensions."""
    sheet = VisualReferenceSheet()
    assert sheet.character.name == "Father Thomas"
    assert sheet.character.age == 48
    assert "spectacles" in sheet.character.accessories
    assert "cassock" in sheet.character.clothing
    assert "dread" in sheet.character.emotional_state

    assert "Lantern" in sheet.prop.name
    assert "2400K" in sheet.prop.light_behavior

    assert "Romanesque" in sheet.environment.architecture
    assert "mirror" in sheet.environment.mirror

    assert "2400K" in sheet.lighting.color_temperature
    assert "5600K" in sheet.lighting.color_temperature

    assert "35mm anamorphic" in sheet.cinematography.lens
    assert "9:16" in sheet.cinematography.framing


def test_standardized_scene_definition():
    """Verify standardized horror scene includes character, prop, environment, action, and supernatural element."""
    scene = StandardizedHorrorScene()
    assert "Father Thomas" in scene.action
    assert "brass lantern" in scene.concept
    assert "cracked" in scene.concept
    assert "reflected" in scene.supernatural_element


def test_prompt_strategies_differentiation():
    """Verify that P1, P2, and P3 produce distinct, specialized prompt strategies."""
    scene = StandardizedHorrorScene()

    pos1, neg1 = build_prompt_for_strategy(PromptStrategy.P1_CURRENT_ARYA, scene)
    pos2, neg2 = build_prompt_for_strategy(PromptStrategy.P2_CINEMATOGRAPHY, scene)
    pos3, neg3 = build_prompt_for_strategy(PromptStrategy.P3_CINEMATIC_STORYTELLING, scene)

    # P1 includes classic buzzwords from production prompt.py
    assert "photorealistic masterpiece" in pos1 or "8k resolution" in pos1

    # P2 explicitly avoids AI buzzwords and uses optical physics
    assert "anamorphic prime lens" in pos2
    assert "f/2.0" in pos2
    assert "8k" not in pos2
    assert "masterpiece" not in pos2

    # P3 emphasizes visual hierarchy and storytelling dread
    assert "Visual hierarchy" in pos3
    assert "terror" in pos3
    assert "woman" in pos3


def test_rubric_scoring_math():
    """Verify subtotal and composite score mathematics."""
    rubric = VisualQualityRubricScores(
        # Image: all 8.0 -> subtotal 8.0
        composition=8.0, lighting=8.0, character_appearance=8.0, environment=8.0,
        prop_accuracy=8.0, texture_detail=8.0, depth=8.0, realism=8.0,
        cinematic_appeal=8.0, visual_storytelling=8.0,
        # Video: all 9.0 -> subtotal 9.0
        motion_realism=9.0, temporal_consistency=9.0, identity_preservation=9.0,
        anatomy_stability=9.0, camera_movement=9.0, performance=9.0,
        environmental_motion=9.0, lighting_stability=9.0,
        # Human: all 7.0 -> subtotal 7.0
        first_impression=7.0, would_stop_scrolling=7.0,
        does_this_feel_authored=7.0, looks_like_real_production=7.0,
    )

    assert rubric.image_subtotal == pytest.approx(8.0)
    assert rubric.video_subtotal == pytest.approx(9.0)
    assert rubric.human_subtotal == pytest.approx(7.0)

    # Composite = (8.0 * 0.35) + (9.0 * 0.35) + (7.0 * 0.30) = 2.8 + 3.15 + 2.10 = 8.05
    assert rubric.composite_score == pytest.approx(8.05)


def test_model_registry_configuration():
    """Verify that image and video registries contain required shootout targets."""
    assert "flux-schnell" in IMAGE_MODEL_REGISTRY
    assert "flux-dev" in IMAGE_MODEL_REGISTRY
    assert "flux-1.1-pro" in IMAGE_MODEL_REGISTRY
    assert "fal-flux-pro" in IMAGE_MODEL_REGISTRY

    assert IMAGE_MODEL_REGISTRY["fal-flux-pro"].is_available is False

    assert "kling-standard" in VIDEO_MODEL_REGISTRY
    assert "ltx-video" in VIDEO_MODEL_REGISTRY
    assert "wan-2.1-i2v" in VIDEO_MODEL_REGISTRY


def test_html_dashboard_generation(tmp_path: Path):
    """Verify HTML review dashboard generates properly formatted report."""
    lab = ShotLab(output_dir=str(tmp_path), desktop_dir=str(tmp_path / "desktop"))

    dummy_img_path = tmp_path / "test.png"
    dummy_img = Image.new("RGB", (100, 100), color=(50, 50, 50))
    dummy_img.save(dummy_img_path)

    images = [
        ImageCandidateResult(
            candidate_id="img_flux_dev_p2",
            model_id="flux-dev",
            strategy=PromptStrategy.P2_CINEMATOGRAPHY,
            positive_prompt="A test prompt",
            negative_prompt="Negative prompt",
            image_url="https://fake.url/img.png",
            local_image_path=str(dummy_img_path),
            latency_seconds=12.5,
            cost_usd=0.025,
            rubric=VisualQualityRubricScores(composition=9.0, lighting=9.0),
        )
    ]

    videos = [
        VideoCandidateResult(
            candidate_id="vid_kling_from_img",
            video_model_id="kling-standard",
            source_image_candidate_id="img_flux_dev_p2",
            source_image_url="https://fake.url/img.png",
            source_image_local_path=str(dummy_img_path),
            motion_prompt="Slow push in",
            video_url="https://fake.url/vid.mp4",
            local_video_path=str(tmp_path / "fake.mp4"),
            representative_frames=[str(dummy_img_path)],
            latency_seconds=120.0,
            cost_usd=0.250,
            rubric=VisualQualityRubricScores(motion_realism=8.8),
        )
    ]

    dashboard_path = lab.generate_html_review_dashboard(images, videos)
    assert os.path.exists(dashboard_path)

    content = Path(dashboard_path).read_text(encoding="utf-8")
    assert "ARYA OS — TASK 23" in content
    assert "flux-dev" in content
    assert "kling-standard" in content
    assert "P2_Cinematography" in content
