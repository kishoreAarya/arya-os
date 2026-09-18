"""Unit tests for Task 22 Cost x Quality Frontier Optimization.

Covers:
- Configuration tunables (visual_budget_usd, max_kling_shots, candidate_policy, quality_floor)
- SmartShotAllocator scoring (motion importance & keyframe importance)
- Allocation algorithms (smart candidates vs fixed candidates, budget overruns, quality floor promotion)
- Itemized cost breakdown (accepted vs rejected candidates, video, audio)
- Pareto frontier analysis (dominance calculation, non-dominated frontier, sweet-spot recommendation)
- CinematicDirectorAgent and ShotExecutor integration
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.core.config import get_settings
from app.schemas.cinematic import (
    CinematicPlan,
    CinematicShotPlan,
    GenerationClass,
    GenerationMode,
    NarrativeBeatType,
)
from app.services.pareto_frontier import (
    ConfigurationMetric,
    ParetoAnalysisResult,
    calculate_pareto_frontier,
    dominates,
)
from app.services.smart_allocator import (
    AllocationDecision,
    SmartShotAllocator,
    VisualBudgetPlan,
    VisualCostBreakdown,
)
from app.workflows.shot_executor import ShotExecutionResult, ShotExecutionSummary


def test_task22_settings_defaults():
    """Verify Task 22 tunables have safe, non-breaking production defaults."""
    settings = get_settings()
    assert getattr(settings, "visual_keyframe_candidates", None) == 1
    assert getattr(settings, "max_kling_shots", None) == 1
    assert getattr(settings, "visual_budget_usd", None) == 0.80
    assert getattr(settings, "quality_floor", None) == 8.5
    assert getattr(settings, "candidate_policy", None) == "fixed"
    assert getattr(settings, "allocation_strategy", None) == "hybrid"


def test_smart_allocator_scoring():
    """Verify motion importance and keyframe importance scoring logic."""
    allocator = SmartShotAllocator()

    # High kinetic action shot with character
    kinetic_shot = CinematicShotPlan(
        shot_number=1,
        generation_class=GenerationClass.A,
        narrative_beat=NarrativeBeatType.ACTION,
        subject="Father Thomas running with iron lantern",
        action="Father Thomas sprints down the corridor and strikes the heavy iron gate",
    )
    motion_score = allocator.score_motion_importance(kinetic_shot)
    keyframe_score = allocator.score_keyframe_importance(kinetic_shot)

    assert motion_score >= 0.70, f"Expected high motion score, got {motion_score}"
    assert keyframe_score >= 0.65, f"Expected high keyframe score for character hook, got {keyframe_score}"

    # Atmospheric, static Class C shot
    static_shot = CinematicShotPlan(
        shot_number=2,
        generation_class=GenerationClass.C,
        narrative_beat=NarrativeBeatType.ESTABLISH,
        subject="Stone archway in crypt",
        action="Dust motes float in the silence of the empty stone crypt hallway",
    )
    static_motion_score = allocator.score_motion_importance(static_shot)
    static_keyframe_score = allocator.score_keyframe_importance(static_shot)

    assert static_motion_score <= 0.40, f"Expected low motion score, got {static_motion_score}"
    assert static_keyframe_score <= 0.50, f"Expected moderate/low keyframe score, got {static_keyframe_score}"


def test_smart_allocator_fixed_vs_smart_candidates():
    """Verify candidate count allocation under fixed vs smart candidate policies."""
    shots = [
        CinematicShotPlan(
            shot_number=1,
            narrative_beat=NarrativeBeatType.HOOK,
            subject="Father Thomas",
            action="Father Thomas stares into the dark abyss",
            generation_class=GenerationClass.A,
        ),
        CinematicShotPlan(
            shot_number=2,
            narrative_beat=NarrativeBeatType.ESTABLISH,
            subject="Crypt walls",
            action="Moonlight glints across damp stone masonry",
            generation_class=GenerationClass.C,
        ),
    ]

    # 1. Fixed policy (default = 1 candidate)
    fixed_allocator = SmartShotAllocator(candidate_policy="fixed", default_candidate_count=1)
    plan_fixed = fixed_allocator.allocate(shots)
    assert plan_fixed.decisions[0].num_candidates == 1
    assert plan_fixed.decisions[1].num_candidates == 1
    assert plan_fixed.total_candidates_generated == 2

    # 2. Smart policy (high importance gets 3, ambient gets 1)
    smart_allocator = SmartShotAllocator(candidate_policy="smart")
    plan_smart = smart_allocator.allocate(shots)
    assert plan_smart.decisions[0].num_candidates == 3  # Hook / Character gets 3
    assert plan_smart.decisions[1].num_candidates == 1  # Ambient stone wall gets 1
    assert plan_smart.total_candidates_generated == 4


def test_smart_allocator_quality_floor_promotion():
    """Verify quality floor protection promotes critical kinetic beats even if max_kling is reached."""
    allocator = SmartShotAllocator(max_kling_shots=1, visual_budget_usd=0.80, quality_floor=8.5)

    shots = [
        CinematicShotPlan(
            shot_number=1,
            narrative_beat=NarrativeBeatType.ACTION,
            generation_class=GenerationClass.A,
            subject="Father Thomas",
            action="Father Thomas strikes the beast with silver blade as it lunges",  # Score >= 0.75
        ),
        CinematicShotPlan(
            shot_number=2,
            narrative_beat=NarrativeBeatType.ACTION,
            generation_class=GenerationClass.A,
            subject="Father Thomas",
            action="The beast screams, tackles him, and attacks violently",  # Score >= 0.75
        ),
        CinematicShotPlan(
            shot_number=3,
            narrative_beat=NarrativeBeatType.ESTABLISH,
            generation_class=GenerationClass.C,
            subject="Crypt floor",
            action="Silence settles over the empty stone floor",
        ),
    ]

    budget_plan = allocator.allocate(shots)

    # Both kinetic shots should be promoted to Kling to prevent quality floor breach
    assert budget_plan.kling_shot_count == 2
    assert budget_plan.image_motion_shot_count == 1
    assert len(budget_plan.overrun_reasons) >= 1
    assert "quality floor" in budget_plan.overrun_reasons[0].lower()


def test_visual_cost_breakdown_itemization():
    """Verify exact itemized accounting separating accepted vs rejected candidates and media costs."""
    shots = [
        {"generation_mode": "video", "num_candidates": 3},  # 1 accepted ($0.03), 2 rejected ($0.06), Kling ($0.25)
        {"generation_mode": "image_motion", "num_candidates": 3},  # 1 accepted ($0.03), 2 rejected ($0.06), Motion ($0.00)
        {"generation_mode": "image_motion", "num_candidates": 1},  # 1 accepted ($0.03), 0 rejected ($0.00), Motion ($0.00)
        {"generation_mode": "image_motion", "num_candidates": 1},  # 1 accepted ($0.03), 0 rejected ($0.00), Motion ($0.00)
    ]

    breakdown = SmartShotAllocator.calculate_cost_breakdown(
        shots=shots,
        narration_cost=0.0822,
        music_cost=0.0100,
        prompt_cost=0.0016,
    )

    assert breakdown.narration_cost == 0.0822
    assert breakdown.music_cost == 0.0100
    assert breakdown.prompt_cost == 0.0016
    assert breakdown.accepted_keyframe_cost == 0.12  # 4 shots * $0.03
    assert breakdown.rejected_keyframe_cost == 0.12  # 4 rejected candidates * $0.03
    assert breakdown.kling_video_cost == 0.25  # 1 Kling shot * $0.25
    assert breakdown.image_motion_cost == 0.00

    # Total = 0.0822 + 0.0100 + 0.0016 + 0.12 + 0.12 + 0.25 = 0.5838
    assert pytest.approx(breakdown.total_production_cost, abs=0.0001) == 0.5838


def test_pareto_dominance_calculation():
    """Verify Pareto dominance logic."""
    # A dominates B if A is cheaper and higher quality
    config_a = ConfigurationMetric(
        name="A_SMART",
        kling_shots=1,
        image_motion_shots=3,
        candidate_policy="smart",
        continuity_bible=True,
        total_cost_usd=0.5838,
        human_quality_score=8.70,
        reliability_pct=100.0,
    )

    # B is more expensive and lower quality than A -> A strictly dominates B
    config_b = ConfigurationMetric(
        name="B_INFERIOR",
        kling_shots=1,
        image_motion_shots=3,
        candidate_policy="fixed_3",
        continuity_bible=False,
        total_cost_usd=0.7038,
        human_quality_score=8.10,
        reliability_pct=100.0,
    )

    assert dominates(config_a, config_b) is True
    assert dominates(config_b, config_a) is False


def test_pareto_frontier_and_sweet_spot_selection():
    """Verify Pareto frontier identification and optimal sweet-spot selection."""
    configs = [
        # Baseline (cheap, but fails quality floor)
        ConfigurationMetric(
            name="V1_BASELINE",
            kling_shots=1,
            image_motion_shots=3,
            candidate_policy="1_candidate",
            continuity_bible=False,
            total_cost_usd=0.4334,
            human_quality_score=6.20,
            visual_quality_score=5.8,
            motion_realism_score=6.5,
            reliability_pct=100.0,
        ),
        # Lean Smart (very cheap, meets quality floor, on frontier)
        ConfigurationMetric(
            name="K1_LEAN_SMART",
            kling_shots=1,
            image_motion_shots=3,
            candidate_policy="smart_candidates",
            continuity_bible=True,
            total_cost_usd=0.5838,
            human_quality_score=8.60,
            visual_quality_score=8.6,
            motion_realism_score=8.3,
            reliability_pct=100.0,
        ),
        # Standard Smart (meets budget $0.80 target, high quality, sweet spot)
        ConfigurationMetric(
            name="K2_OPTIMAL_HYBRID",
            kling_shots=2,
            image_motion_shots=2,
            candidate_policy="smart_candidates",
            continuity_bible=True,
            total_cost_usd=0.8338,
            human_quality_score=8.95,
            visual_quality_score=9.0,
            motion_realism_score=8.8,
            reliability_pct=100.0,
        ),
        # Unoptimized Standard (dominated by K2: same quality, higher cost)
        ConfigurationMetric(
            name="V2_STANDARD_FIXED3",
            kling_shots=2,
            image_motion_shots=2,
            candidate_policy="3_candidates",
            continuity_bible=True,
            total_cost_usd=0.9538,
            human_quality_score=8.85,
            visual_quality_score=8.9,
            motion_realism_score=8.8,
            reliability_pct=100.0,
        ),
        # Premium (top quality, highest cost, on frontier)
        ConfigurationMetric(
            name="V3_PREMIUM",
            kling_shots=3,
            image_motion_shots=1,
            candidate_policy="3_candidates",
            continuity_bible=True,
            total_cost_usd=1.2038,
            human_quality_score=9.35,
            visual_quality_score=9.4,
            motion_realism_score=9.2,
            reliability_pct=100.0,
        ),
    ]

    result: ParetoAnalysisResult = calculate_pareto_frontier(
        configs=configs,
        quality_floor=8.5,
        target_budget=0.85,
    )

    # V2_STANDARD_FIXED3 is dominated by K2_OPTIMAL_HYBRID (K2 is cheaper and higher quality)
    assert "V2_STANDARD_FIXED3" in result.dominated_configurations
    assert "K1_LEAN_SMART" in result.frontier_configurations
    assert "K2_OPTIMAL_HYBRID" in result.frontier_configurations
    assert "V3_PREMIUM" in result.frontier_configurations

    # V1 fails quality floor (<8.5)
    v1_metric = next(c for c in result.configurations if c.name == "V1_BASELINE")
    assert v1_metric.meets_quality_floor is False

    # Sweet spot should be selected from qualifying frontier configs
    assert result.recommended_configuration in ("K1_LEAN_SMART", "K2_OPTIMAL_HYBRID")
    assert len(result.comparison_table_md) > 0


def test_shot_executor_summary_breakdown():
    """Verify ShotExecutionSummary stores itemized cost_breakdown."""
    res1 = ShotExecutionResult(
        shot_number=1,
        generation_mode="video",
        generation_class="A",
        candidate_urls=["https://img1.jpg", "https://img2.jpg"],
        num_candidates=2,
        cost_usd=0.31,
        success=True,
    )
    res2 = ShotExecutionResult(
        shot_number=2,
        generation_mode="image_motion",
        generation_class="B",
        candidate_urls=["https://img3.jpg"],
        num_candidates=1,
        cost_usd=0.03,
        success=True,
    )

    summary = ShotExecutionSummary(
        results=[res1, res2],
        video_clips=["clip1.mp4", "clip2.mp4"],
        total_cost=0.34,
        total_duration=8.0,
        cost_breakdown={"accepted_keyframe_cost": 0.06, "total_production_cost": 0.43},
    )

    assert summary.total_cost == 0.34
    assert summary.cost_breakdown is not None
    assert summary.cost_breakdown["accepted_keyframe_cost"] == 0.06
