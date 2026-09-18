"""Unit tests for deterministic Class A/B/C shot classifier, pacing, and guardrails."""

import pytest

from app.core.shot_classifier import (
    MANDATORY_NEGATIVE_ELEMENTS,
    calculate_irregular_pacing,
    calculate_shot_cost,
    classify_shot,
    get_enforced_negative_prompt,
    sanitize_generation_prompt,
)
from app.schemas.cinematic import GenerationClass, GenerationMode


def test_classify_shot_class_a_critical_motion():
    """Verify that physical actions, running, fighting, door opening, and creature movement are classified as Class A video."""
    # Running / chasing
    cls_a, mode_a, cost_r, qual_r = classify_shot(action="The detective sprints through the alley chasing a shadow")
    assert cls_a == GenerationClass.A
    assert mode_a == GenerationMode.VIDEO
    assert "video" in cost_r.lower()
    assert "kinetic" in qual_r.lower() or "motion" in qual_r.lower()

    # Fighting / combat
    cls_b, mode_b, _, _ = classify_shot(action="Two operatives fight fiercely on the rain-soaked catwalk")
    assert cls_b == GenerationClass.A
    assert mode_b == GenerationMode.VIDEO

    # Door opening
    cls_c, mode_c, _, _ = classify_shot(action="The rusty iron door opens slowly with a loud screech")
    assert cls_c == GenerationClass.A
    assert mode_c == GenerationMode.VIDEO

    # Creature movement
    cls_d, mode_d, _, _ = classify_shot(
        subject="Alien predator",
        action="Creature lunges forward out of the darkness",
    )
    assert cls_d == GenerationClass.A
    assert mode_d == GenerationMode.VIDEO


def test_classify_shot_class_c_information_context():
    """Verify that documents, diagrams, screens, and static artifacts are classified as Class C image_motion with zero video cost."""
    # Document / contract
    cls_a, mode_a, cost_r, qual_r = classify_shot(
        subject="Confidential government document on the desk",
        action="Camera frames the classified red stamp on the paper",
    )
    assert cls_a == GenerationClass.C
    assert mode_a == GenerationMode.IMAGE_MOTION
    assert "$0.00" in cost_r
    assert "typography" in qual_r.lower() or "micro-details" in qual_r.lower()

    # Blueprint / diagram
    cls_b, mode_b, _, _ = classify_shot(action="Architectural blueprint of the vault laid out under a warm lamp")
    assert cls_b == GenerationClass.C
    assert mode_b == GenerationMode.IMAGE_MOTION

    # Screen / monitor
    cls_c, mode_c, _, _ = classify_shot(
        subject="Computer monitor displaying encrypted logs",
        action="Green terminal text glows in the dark room",
    )
    assert cls_c == GenerationClass.C
    assert mode_c == GenerationMode.IMAGE_MOTION

    # Photograph / relic
    cls_d, mode_d, _, _ = classify_shot(
        subject="Faded polaroid photograph of the expedition crew",
        action="Dust covers the glass frame",
    )
    assert cls_d == GenerationClass.C
    assert mode_d == GenerationMode.IMAGE_MOTION


def test_classify_shot_class_b_atmospheric_motion():
    """Verify that hallways, empty streets, weather drift, and mood environments are classified as Class B image_motion."""
    cls_a, mode_a, cost_r, qual_r = classify_shot(
        environment="Deserted city street at dawn with light mist",
        action="Fog drifts past neon signs",
    )
    assert cls_a == GenerationClass.B
    assert mode_a == GenerationMode.IMAGE_MOTION
    assert "atmospheric" in cost_r.lower()

    cls_b, mode_b, _, _ = classify_shot(
        environment="Old Victorian bedroom",
        action="Curtains billow gently in the cold night breeze",
    )
    assert cls_b == GenerationClass.B
    assert mode_b == GenerationMode.IMAGE_MOTION


def test_classify_shot_explicit_override():
    """Verify that explicit force_class or force_mode is respected."""
    cls_f, mode_f, cost_r, qual_r = classify_shot(
        action="Reading a book",
        force_class=GenerationClass.A,
        force_mode=GenerationMode.VIDEO,
    )
    assert cls_f == GenerationClass.A
    assert mode_f == GenerationMode.VIDEO
    assert "Class A" in qual_r


def test_enforced_negative_prompt_includes_all_prohibitions():
    """Verify Bible Section 30 text/UI prohibition is strictly added to negative prompt."""
    base_negative = "low quality, deformed hands, blurry"
    enforced = get_enforced_negative_prompt(base_negative)

    assert "low quality" in enforced
    assert "deformed hands" in enforced
    assert "blurry" in enforced

    for mandatory in MANDATORY_NEGATIVE_ELEMENTS:
        assert mandatory.lower() in enforced.lower()

    # Verify deduplication if some are already present
    partially_enforced = f"{base_negative}, subtitles, UI"
    result2 = get_enforced_negative_prompt(partially_enforced)
    # Check that 'subtitles' appears exactly once in the split list
    items = [x.strip().lower() for x in result2.split(",")]
    assert items.count("subtitles") == 1
    assert items.count("ui") == 1


def test_sanitize_generation_prompt():
    """Verify that generation prompts asking for on-screen text or buttons are sanitized."""
    raw_prompt = 'Cinematic medium shot of detective with text saying "THE END" in bold font.'
    cleaned = sanitize_generation_prompt(raw_prompt)
    assert "with text saying" not in cleaned
    assert "THE END" not in cleaned

    raw_prompt2 = "Hero looking at horizon with subscribe button and text overlay"
    cleaned2 = sanitize_generation_prompt(raw_prompt2)
    assert "subscribe button" not in cleaned2
    assert "text overlay" not in cleaned2


def test_calculate_shot_cost_zero_for_image_motion():
    """Verify Class C / image_motion has strictly 0.0 video generation cost."""
    cost_c = calculate_shot_cost(GenerationClass.C, GenerationMode.IMAGE_MOTION, provider="fal", model="wan-i2v")
    assert cost_c == 0.0

    cost_b_motion = calculate_shot_cost(GenerationClass.B, GenerationMode.IMAGE_MOTION, provider="runway", model="gen3")
    assert cost_b_motion == 0.0


def test_calculate_shot_cost_for_video():
    """Verify video generation cost calculation without inventing fake pricing."""
    # Known fal wan 2.1 rate
    cost_wan = calculate_shot_cost(GenerationClass.A, GenerationMode.VIDEO, provider="fal-ai", model="fal-ai/wan-i2v")
    assert cost_wan == 0.08

    # Known runway rate
    cost_runway = calculate_shot_cost(GenerationClass.A, GenerationMode.VIDEO, provider="runway", model="gen3a_turbo")
    assert cost_runway == 0.25

    # Unknown provider does NOT invent fake price
    cost_unknown = calculate_shot_cost(GenerationClass.A, GenerationMode.VIDEO, provider=None)
    assert cost_unknown is None


def test_calculate_irregular_pacing_preserves_target_duration():
    """Verify that irregular pacing generates non-uniform, positive durations summing to target duration."""
    target_duration = 20.0
    shot_count = 5

    pacing = calculate_irregular_pacing(target_duration, shot_count)

    assert len(pacing) == shot_count
    # All durations are positive and >= 1.5s
    assert all(d >= 1.5 for d in pacing)
    # Sum must strictly equal target duration
    assert pytest.approx(sum(pacing), abs=0.01) == target_duration
    # Durations must NOT be uniform 4.0s everywhere
    assert len(set(pacing)) > 1

    # Test with different target durations and counts
    pacing_15 = calculate_irregular_pacing(15.0, 4)
    assert len(pacing_15) == 4
    assert pytest.approx(sum(pacing_15), abs=0.01) == 15.0
    assert len(set(pacing_15)) > 1

    pacing_30 = calculate_irregular_pacing(30.0, 7)
    assert len(pacing_30) == 7
    assert pytest.approx(sum(pacing_30), abs=0.01) == 30.0


def test_calculate_irregular_pacing_with_word_counts():
    """Verify that pacing adapts to speech word counts when provided."""
    target_duration = 20.0
    word_counts = [10, 22, 8, 25, 12]  # Varying sentence lengths

    pacing = calculate_irregular_pacing(target_duration, len(word_counts), word_counts=word_counts)

    assert len(pacing) == 5
    assert pytest.approx(sum(pacing), abs=0.01) == target_duration
    # Shot with 25 words should be longer than shot with 8 words
    assert pacing[3] > pacing[2]
