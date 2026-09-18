"""Unit tests for Visual Model Profiles & Visual Standard V2 Integration (Task 24)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import get_settings
from app.services.visual_profiles import (
    BUZZWORD_BAN_LIST,
    CandidateAllocationPolicy,
    ProviderAvailabilityStatus,
    VisualModelProfile,
    VisualProfileType,
    build_cinematic_prompt_v2,
    check_provider_status,
    classify_provider_error,
    execute_visual_dry_run,
    get_task23_standard_horror_scene_shots,
    list_visual_profiles,
    resolve_visual_profile,
    sanitize_prompt_v2,
)
from app.services.smart_allocator import SmartShotAllocator


def test_resolve_visual_profile_defaults():
    """Verify default resolution to current_legacy and case/hyphen normalization."""
    # Default without argument
    prof = resolve_visual_profile()
    assert prof.name == "current_legacy"
    assert prof.image_steps == 4
    assert prof.cost_per_image == 0.003

    # Named resolution
    lean = resolve_visual_profile("visual_v2_lean")
    assert lean.name == "visual_v2_lean"
    assert lean.cost_per_image == 0.025
    assert lean.image_steps == 28

    flagship = resolve_visual_profile("Visual-V2-Flagship")
    assert flagship.name == "visual_v2_flagship"
    assert flagship.cost_per_image == 0.040
    assert flagship.target_quality_rating == 9.5

    # Enum resolution
    enum_prof = resolve_visual_profile(VisualProfileType.VISUAL_V2_FLAGSHIP)
    assert enum_prof.name == "visual_v2_flagship"

    # Instance pass-through
    assert resolve_visual_profile(flagship) is flagship

    # Safe fallback on unknown
    fallback = resolve_visual_profile("non_existent_profile_xyz")
    assert fallback.name == "current_legacy"


def test_visual_model_profile_candidate_counts():
    """Verify candidate count calculation across profiles according to policies."""
    legacy = resolve_visual_profile("current_legacy")
    assert legacy.get_candidate_count("A", is_key_beat=True, keyframe_score=0.9) == 1
    assert legacy.get_candidate_count("B", is_key_beat=False, keyframe_score=0.3) == 1

    lean = resolve_visual_profile("visual_v2_lean")
    assert lean.get_candidate_count("A", is_key_beat=True, keyframe_score=0.8) == 3
    assert lean.get_candidate_count("B", is_key_beat=False, keyframe_score=0.4) == 1
    assert lean.get_candidate_count("C", is_key_beat=False, keyframe_score=0.2) == 1

    flagship = resolve_visual_profile("visual_v2_flagship")
    assert flagship.get_candidate_count("A", is_key_beat=True, keyframe_score=0.8) == 3
    assert flagship.get_candidate_count("B", is_key_beat=False, keyframe_score=0.5) == 2
    assert flagship.get_candidate_count("C", is_key_beat=False, keyframe_score=0.2) == 1


def test_provider_availability_status_classification():
    """Verify explicit distinction between CREDIT_EXHAUSTED and CREDENTIAL_ERROR."""
    # Credit exhaustion patterns
    assert classify_provider_error("Replicate returned 402: Payment Required") == ProviderAvailabilityStatus.CREDIT_EXHAUSTED
    assert classify_provider_error("Insufficient credits in account") == ProviderAvailabilityStatus.CREDIT_EXHAUSTED
    assert classify_provider_error("You have reached your spending limit") == ProviderAvailabilityStatus.CREDIT_EXHAUSTED
    assert classify_provider_error("Billing account suspended due to unpaid balance") == ProviderAvailabilityStatus.CREDIT_EXHAUSTED

    # Credential error patterns
    assert classify_provider_error("Replicate rejected the API key (401)") == ProviderAvailabilityStatus.CREDENTIAL_ERROR
    assert classify_provider_error("HTTP 403 Forbidden") == ProviderAvailabilityStatus.CREDENTIAL_ERROR
    assert classify_provider_error("SecretNotConfigured: REPLICATE_API_KEY") == ProviderAvailabilityStatus.CREDENTIAL_ERROR

    # Rate limiting & Timeout
    assert classify_provider_error("429 Too Many Requests") == ProviderAvailabilityStatus.RATE_LIMITED
    assert classify_provider_error("Replicate timed out after 300s") == ProviderAvailabilityStatus.TIMEOUT

    # General unavailable
    assert classify_provider_error("Connection reset by peer") == ProviderAvailabilityStatus.UNAVAILABLE

    # Ensure CREDIT_EXHAUSTED != CREDENTIAL_ERROR
    assert ProviderAvailabilityStatus.CREDIT_EXHAUSTED != ProviderAvailabilityStatus.CREDENTIAL_ERROR


def test_check_provider_status():
    """Verify check_provider_status reports CREDIT_EXHAUSTED when flagged."""
    status, detail = check_provider_status("replicate", override_credits_exhausted=True)
    assert status == ProviderAvailabilityStatus.CREDIT_EXHAUSTED
    assert "0 active credits" in detail

    with patch.object(get_settings(), "replicate_api_key", ""):
        status, detail = check_provider_status("replicate", override_credits_exhausted=False)
        assert status == ProviderAvailabilityStatus.CREDENTIAL_ERROR


def test_prompt_policy_v2_sanitization():
    """Verify Prompt Policy V2 strips banned AI buzzwords while keeping optics."""
    raw_prompt = (
        "masterpiece, best quality, 8k uhd, photorealistic image of Father Thomas "
        "descending into the crypt, 35mm anamorphic prime, f/2.0, trending on artstation, "
        "hyperrealistic, octane render, beautiful lighting"
    )
    sanitized = sanitize_prompt_v2(raw_prompt)

    assert "masterpiece" not in sanitized.lower()
    assert "8k" not in sanitized.lower()
    assert "photorealistic" not in sanitized.lower()
    assert "artstation" not in sanitized.lower()
    assert "octane render" not in sanitized.lower()
    assert "hyperrealistic" not in sanitized.lower()

    # Preserved physical optics & subject
    assert "Father Thomas" in sanitized
    assert "35mm anamorphic prime" in sanitized
    assert "f/2.0" in sanitized


def test_build_cinematic_prompt_v2():
    """Verify build_cinematic_prompt_v2 adds optics, Kelvin lighting, and depth."""
    prompt = build_cinematic_prompt_v2(
        base_prompt="Father Thomas in the subterranean crypt",
        focal_length="35mm anamorphic prime, f/1.8",
        lighting="2400K amber candlelight against 5600K slate moonlight fill",
        depth_staging="three-plane depth staging with foreground stone archway",
        tactile_textures="coarse wool cassock, damp porous limestone",
        emotional_intent="caught mid-breath, tension in shoulders",
    )
    assert "35mm anamorphic prime" in prompt
    assert "2400K amber candlelight" in prompt
    assert "three-plane depth staging" in prompt
    assert "coarse wool cassock" in prompt
    assert "caught mid-breath" in prompt
    assert "subtle 35mm film grain" in prompt


def test_smart_allocator_with_visual_profiles():
    """Verify SmartShotAllocator uses profile rates and candidate policies."""
    shots = [
        {"shot_number": 1, "description": "Priest descending stairs", "narrative_beat": "HOOK", "generation_class": "B"},
        {"shot_number": 2, "description": "Empty hallway stone wall", "narrative_beat": "ATMOSPHERE", "generation_class": "C"},
        {"shot_number": 3, "description": "Monster attacks and lunges at camera", "narrative_beat": "ACTION", "generation_class": "A"},
    ]

    # Legacy profile: 1 candidate each, $0.003 image rate
    legacy_alloc = SmartShotAllocator(visual_profile="current_legacy")
    legacy_plan = legacy_alloc.allocate(shots)
    assert legacy_plan.total_candidates_generated == 3
    assert legacy_alloc.image_candidate_cost == 0.003
    assert legacy_plan.kling_shot_count == 1
    assert legacy_plan.allocated_cost_usd == pytest.approx(0.25 + 3 * 0.003, rel=1e-3)

    # Flagship profile: smart candidate allocation, $0.040 image rate
    flagship_alloc = SmartShotAllocator(visual_profile="visual_v2_flagship")
    flagship_plan = flagship_alloc.allocate(shots)
    assert flagship_alloc.image_candidate_cost == 0.040
    # Shot 1 (HOOK) -> 3, Shot 2 (C) -> 1 or 2, Shot 3 (ACTION/Kling) -> 3
    assert flagship_plan.total_candidates_generated >= 7
    assert flagship_plan.kling_shot_count == 1
    assert flagship_plan.allocated_cost_usd <= 0.80


def test_quality_floor_override_logging():
    """Verify Quality Floor (>= 8.5) strictly overrides budget limit for kinetic beats."""
    shots = [
        {"shot_number": 1, "description": "Priest runs and flees in terror", "action": "runs and flees", "narrative_beat": "ACTION"},
        {"shot_number": 2, "description": "Monster attacks and lunges at camera", "action": "attacks and lunges violently", "narrative_beat": "ACTION"},
    ]
    # Restrict max_kling_shots to 1, but both shots have high kinetic motion
    alloc = SmartShotAllocator(max_kling_shots=1, quality_floor=8.5)
    plan = alloc.allocate(shots)

    # Shot 2 must be promoted to Kling due to quality floor override
    assert plan.kling_shot_count == 2
    assert len(plan.overrun_reasons) >= 1
    assert "quality floor" in plan.overrun_reasons[0].lower()


def test_execute_visual_dry_run():
    """Verify deterministic dry-run execution produces full plan with $0.00 observed cost."""
    shots = get_task23_standard_horror_scene_shots()
    result = execute_visual_dry_run(
        shots_data=shots,
        profile_name="visual_v2_flagship",
        provider_override_status=ProviderAvailabilityStatus.CREDIT_EXHAUSTED,
    )

    assert result.total_observed_cost_usd == 0.0
    assert result.total_expected_cost_usd > 0.0
    assert result.total_expected_cost_usd <= 0.80
    assert result.kling_shot_count == 1
    assert result.image_motion_shot_count == 2
    assert result.provider_status == ProviderAvailabilityStatus.CREDIT_EXHAUSTED

    # Verify shot contents
    assert len(result.shots) == 3
    for s in result.shots:
        assert s.observed_cost == 0.0
        assert s.expected_total_cost > 0.0
        assert "subtle 35mm film grain" in s.positive_prompt_v2
        assert "subtitles" in s.negative_prompt_enforced


@pytest.mark.asyncio
async def test_image_agent_dry_run():
    """Verify ImageAgent respects visual_dry_run setting without calling paid providers."""
    from app.agents.image import ImageAgent

    mock_session = AsyncMock()
    agent = ImageAgent(mock_session)

    context = {
        "shot_number": 1,
        "shot_description": "Father Thomas descends stone stairs with lantern",
        "visual_dry_run": True,
        "visual_profile": "visual_v2_flagship",
        "num_keyframe_candidates": 3,
    }

    result = await agent.run(context)
    assert result.success is True
    assert result.cost_usd == 0.0
    assert "dry_run" in result.provider_used
    assert result.output["source_image_path"].startswith("dry_run://")
    assert len(result.output["candidate_urls"]) == 3
    assert result.output["keyframe_selection"] is not None


@pytest.mark.asyncio
async def test_video_agent_dry_run():
    """Verify VideoAgent respects visual_dry_run setting without calling paid providers."""
    from app.agents.video import VideoAgent

    mock_session = AsyncMock()
    agent = VideoAgent(mock_session)

    context = {
        "shot_number": 3,
        "source_image_path": "dry_run://shot_3_keyframe.png",
        "shot_description": "Shadow entity lunges toward camera",
        "visual_dry_run": True,
        "target_duration_seconds": 4.0,
    }

    result = await agent.run(context)
    assert result.success is True
    assert result.cost_usd == 0.0
    assert "dry_run" in result.provider_used
    assert result.output["source_video_path"].startswith("dry_run://")
