"""Unit tests for CinematicDirectorAgent and CinematicPlan schemas."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.agents.base import AgentResult
from app.agents.cinematic_director import (
    CinematicDirectorAgent,
    _build_cinematic_director_prompt,
    _build_fallback_cinematic_plan,
    _parse_cinematic_plan_json,
)
from app.agents.storyboard import Shot, StoryboardResult
from app.schemas.cinematic import (
    CameraMovementType,
    CinematicPlan,
    CinematicShotPlan,
    GenerationClass,
    GenerationMode,
    SoundDesignPlan,
)
from app.services.execution_engine import ExecutionResult


def test_cinematic_shot_plan_schema_and_conversion():
    """Verify CinematicShotPlan validation and conversion to standard Storyboard Shot."""
    shot_plan = CinematicShotPlan(
        shot_number=1,
        shot_id="shot_1_test",
        start_time=0.0,
        duration_seconds=3.2,
        narration_segment="Three knocks shattered the silence of midnight.",
        purpose="Visceral hook introducing tension",
        generation_class=GenerationClass.A,
        generation_mode=GenerationMode.VIDEO,
        subject="Heavy oak front door in Victorian foyer",
        action="The door trembles visibly under three forceful knocks from outside",
        environment="Dimly lit entrance hall, rain streaming down side transom windows",
        composition="Low angle looking up toward brass doorknob",
        camera_angle="Low Angle",
        camera_movement="slow_push_in",
        lens="24mm anamorphic",
        lighting="Single warm wall sconce casting long shadows",
        performance_behavior="Stillness before violent vibration",
        sound_design=SoundDesignPlan(
            sound_events=["three heavy wood impacts", "rain on glass", "subtle sub-bass rumble"],
            music_type="minimal",
            music_intensity="low",
            silence_intentional=True,
            silence_reason="Tension before reaction",
        ),
        generation_prompt="Heavy oak door trembling under knocks, cinematic lighting, 24mm anamorphic lens",
        negative_prompt="subtitles, captions, UI, watermark",
        estimated_cost=0.08,
        cost_reason="Critical kinetic movement requires video",
        quality_reason="Captures vibration and physical impact",
    )

    assert shot_plan.shot_number == 1
    assert shot_plan.duration_seconds == 3.2
    assert shot_plan.generation_class == GenerationClass.A
    assert shot_plan.generation_mode == GenerationMode.VIDEO

    # Convert to standard Storyboard Shot
    sb_shot = shot_plan.to_storyboard_shot()
    assert isinstance(sb_shot, Shot)
    assert sb_shot.shot_number == 1
    assert sb_shot.voiceover == "Three knocks shattered the silence of midnight."
    assert sb_shot.generation_class == "A"
    assert sb_shot.generation_mode == "video"
    assert sb_shot.estimated_cost == 0.08
    assert sb_shot.sound_design["music_type"] == "minimal"
    assert sb_shot.camera_movement == "slow_push_in"


def test_cinematic_plan_aggregation_and_counts():
    """Verify CinematicPlan total duration and class count aggregations."""
    shots = [
        CinematicShotPlan(
            shot_number=1,
            duration_seconds=2.8,
            generation_class=GenerationClass.A,
            generation_mode=GenerationMode.VIDEO,
            purpose="Hook",
        ),
        CinematicShotPlan(
            shot_number=2,
            duration_seconds=4.5,
            generation_class=GenerationClass.B,
            generation_mode=GenerationMode.IMAGE_MOTION,
            purpose="Atmosphere",
        ),
        CinematicShotPlan(
            shot_number=3,
            duration_seconds=3.2,
            generation_class=GenerationClass.C,
            generation_mode=GenerationMode.IMAGE_MOTION,
            purpose="Document detail",
        ),
    ]

    plan = CinematicPlan(
        target_duration=10.5,
        aspect_ratio="9:16",
        emotional_arc="Intrigue to tension",
        visual_style="Grounded noir with high contrast",
        total_estimated_cost=0.08,
        shots=shots,
    )

    assert pytest.approx(plan.planned_duration, abs=0.01) == 10.5
    assert plan.class_counts == {"A": 1, "B": 1, "C": 1}


def test_build_cinematic_director_prompt_contains_bible_directives():
    """Verify prompt instructs LLM on Bible principles, irregular pacing, and UI prohibition."""
    prompt = _build_cinematic_director_prompt(
        script_content="A mystery in the lighthouse.",
        target_duration=20.0,
        aspect_ratio="16:9",
        camera_style="Observational, subtle handheld",
        lighting_style="Motivated practicals",
        target_shots=5,
    )

    assert "CINEMATIC PRODUCTION BIBLE" in prompt
    assert "SHOW -> IMPLY -> REVEAL" in prompt
    assert "RHYTHMIC IRREGULARITY" in prompt
    assert "DO NOT use uniform 4.0s shot durations" in prompt
    assert "CLASS A / B / C" in prompt
    assert "ABSOLUTE PROHIBITION ON TEXT/UI" in prompt
    assert "Target Total Duration: 20.0 seconds" in prompt
    assert "Target Aspect Ratio: 16:9" in prompt


def test_parse_cinematic_plan_json():
    """Verify JSON parsing into a structured CinematicPlan."""
    sample_json = json.dumps({
        "target_duration": 15.0,
        "aspect_ratio": "16:9",
        "emotional_arc": "Calm to terror",
        "visual_style": "Cold blue tones with warm sodium vapor highlights",
        "shots": [
            {
                "shot_number": 1,
                "duration_seconds": 3.0,
                "narration_segment": "The phone rang once.",
                "purpose": "Audio trigger",
                "generation_class": "C",
                "generation_mode": "image_motion",
                "subject": "Vintage rotary telephone on side table",
                "action": "The brass bell inside vibrates slightly",
                "environment": "Dim hallway",
                "camera_movement": "slow_push_in",
                "sound_design": {
                    "sound_events": ["sharp telephone ring"],
                    "music_type": "diegetic",
                    "music_intensity": "low",
                },
            },
            {
                "shot_number": 2,
                "duration_seconds": 5.0,
                "narration_segment": "He bolted toward the stairs.",
                "purpose": "Urgent pursuit",
                "generation_class": "A",
                "generation_mode": "video",
                "subject": "Man in dark overcoat",
                "action": "Man sprints across hardwood floor toward staircase",
                "environment": "Foyer with moonlight through skylight",
                "camera_movement": "pan_right",
            },
        ],
    })

    plan = _parse_cinematic_plan_json(sample_json, target_duration=15.0, aspect_ratio="16:9")
    assert plan is not None
    assert len(plan.shots) == 2
    assert plan.shots[0].generation_class == GenerationClass.C
    assert plan.shots[0].generation_mode == GenerationMode.IMAGE_MOTION
    assert plan.shots[1].generation_class == GenerationClass.A
    assert plan.shots[1].generation_mode == GenerationMode.VIDEO
    assert plan.shots[0].camera_movement == "slow_push_in"


def test_fallback_cinematic_plan():
    """Verify fallback plan generator handles raw text scripts deterministically."""
    script = "The night was silent.\nA shadow crossed the garden.\nThe latch clicked."
    plan = _build_fallback_cinematic_plan(script, target_duration=18.0, aspect_ratio="9:16")

    assert plan is not None
    assert len(plan.shots) == 3
    assert pytest.approx(plan.planned_duration, abs=0.01) == 18.0
    # Check that each shot has purpose and non-zero duration
    for s in plan.shots:
        assert s.duration_seconds >= 1.5
        assert s.purpose != ""
        assert s.sound_design is not None


@pytest.mark.asyncio
async def test_cinematic_director_agent_run_success():
    """Verify CinematicDirectorAgent execution with mocked ExecutionEngine."""
    db_mock = AsyncMock()
    agent = CinematicDirectorAgent(db_mock)

    llm_payload = {
        "target_duration": 20.0,
        "aspect_ratio": "16:9",
        "emotional_arc": "Suspense escalating to visceral dread",
        "visual_style": "Grounded naturalism with motivated directional lighting",
        "shots": [
            {
                "shot_number": 1,
                "duration_seconds": 3.0,
                "narration_segment": "The lock had been forced open.",
                "purpose": "Introduce breach",
                "generation_class": "C",
                "generation_mode": "image_motion",
                "subject": "Scratched brass padlock hanging from broken hasp",
                "action": "Fresh tool marks glint under flashlight beam",
                "environment": "Cellar exterior door",
                "camera_movement": "slow_push_in",
                "negative_prompt": "blurry, low quality",
            },
            {
                "shot_number": 2,
                "duration_seconds": 4.5,
                "narration_segment": "Something rushed past him in the pitch black.",
                "purpose": "Kinetic scare",
                "generation_class": "A",
                "generation_mode": "video",
                "subject": "Detective spinning around",
                "action": "Detective whirls around flashlight beam slicing through dust motes",
                "environment": "Flooded subterranean corridor",
                "camera_movement": "pan_left",
                "negative_prompt": "cartoon, oversaturated",
            },
        ],
    }

    mock_exec_result = ExecutionResult(
        provider="gemini",
        output=json.dumps(llm_payload),
        elapsed_time=1.2,
        cost_usd=0.0004,
        success=True,
    )

    with patch.object(agent._execution_engine, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_exec_result

        result = await agent.run({
            "script_content": "The lock was forced. Something moved in the dark.",
            "duration": 20.0,
            "aspect_ratio": "16:9",
            "script_id": "script_123",
            "video_provider": "fal-ai",
            "video_model": "fal-ai/wan-i2v",
        })

        assert result.success is True
        assert "cinematic_plan" in result.output
        assert "shots" in result.output
        assert "storyboard_result" in result.output

        plan: CinematicPlan = result.output["cinematic_plan"]
        assert pytest.approx(plan.planned_duration, abs=0.01) == 20.0
        assert len(plan.shots) == 2

        # Verify Class C has $0.00 video cost
        shot1 = plan.shots[0]
        assert shot1.generation_class == GenerationClass.C
        assert shot1.generation_mode == GenerationMode.IMAGE_MOTION
        assert shot1.estimated_cost == 0.0

        # Verify negative prompt strictly enforced Section 30 prohibitions
        assert "subtitles" in shot1.negative_prompt
        assert "Subscribe button" in shot1.negative_prompt
        assert "UI" in shot1.negative_prompt

        # Verify storyboard result contains valid Shot dataclasses
        sb_res: StoryboardResult = result.output["storyboard_result"]
        assert len(sb_res.shots) == 2
        assert all(isinstance(s, Shot) for s in sb_res.shots)
        assert sb_res.script_id == "script_123"


@pytest.mark.asyncio
async def test_cinematic_director_agent_missing_script():
    """Verify CinematicDirectorAgent errors when script_content is empty."""
    db_mock = AsyncMock()
    agent = CinematicDirectorAgent(db_mock)

    result = await agent.run({})
    assert result.success is False
    assert "script_content is required" in result.error
