"""Pareto Frontier Analysis for ARYA OS Cost x Quality Optimization.

Calculates non-dominated configurations along the Cost x Quality trade-off
frontier, identifies dominated strategies, and provides data-driven recommendations
for production deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger("arya.services.pareto_frontier")


@dataclass
class ConfigurationMetric:
    """Performance and cost metrics for a single production configuration."""

    name: str
    kling_shots: int
    image_motion_shots: int
    candidate_policy: str  # e.g. "1_candidate", "smart_candidates", "3_candidates"
    continuity_bible: bool
    total_cost_usd: float
    human_quality_score: float  # 0.0 to 10.0
    visual_quality_score: float = 0.0
    story_alignment_score: float = 0.0
    motion_realism_score: float = 0.0
    continuity_score: float = 0.0
    reliability_pct: float = 100.0  # 0.0 to 100.0
    meets_quality_floor: bool = False
    meets_budget_target: bool = False

    def __post_init__(self) -> None:
        self.total_cost_usd = round(self.total_cost_usd, 4)
        self.human_quality_score = round(self.human_quality_score, 2)
        self.visual_quality_score = round(self.visual_quality_score, 2)
        self.story_alignment_score = round(self.story_alignment_score, 2)
        self.motion_realism_score = round(self.motion_realism_score, 2)
        self.continuity_score = round(self.continuity_score, 2)
        self.reliability_pct = round(self.reliability_pct, 1)


@dataclass
class ParetoAnalysisResult:
    """Result of Pareto frontier calculation across tested configurations."""

    configurations: list[ConfigurationMetric]
    frontier_configurations: list[str]  # Non-dominated configuration names
    dominated_configurations: list[str]  # Dominated configuration names
    recommended_configuration: str  # Optimal sweet spot
    sweet_spot_rationale: str
    comparison_table_md: str = ""


def dominates(a: ConfigurationMetric, b: ConfigurationMetric) -> bool:
    """Check if configuration A Pareto-dominates configuration B.

    A dominates B if A is at least as good as B in all objectives (cost,
    quality, reliability) and strictly better in at least one objective.
    (Lower cost is better, higher quality and reliability are better).
    """
    cost_le = a.total_cost_usd <= b.total_cost_usd
    qual_ge = a.human_quality_score >= b.human_quality_score
    rel_ge = a.reliability_pct >= b.reliability_pct

    strictly_better = (
        a.total_cost_usd < b.total_cost_usd
        or a.human_quality_score > b.human_quality_score
        or a.reliability_pct > b.reliability_pct
    )

    return cost_le and qual_ge and rel_ge and strictly_better


def calculate_pareto_frontier(
    configs: list[ConfigurationMetric],
    quality_floor: float = 8.5,
    target_budget: float = 0.80,
) -> ParetoAnalysisResult:
    """Calculate the Pareto frontier, identify dominated configurations, and recommend the optimal sweet spot."""
    for c in configs:
        c.meets_quality_floor = c.human_quality_score >= quality_floor
        c.meets_budget_target = c.total_cost_usd <= target_budget

    dominated: set[str] = set()
    for i, c1 in enumerate(configs):
        for j, c2 in enumerate(configs):
            if i != j and dominates(c1, c2):
                dominated.add(c2.name)

    frontier_names = [c.name for c in configs if c.name not in dominated]
    dominated_names = [c.name for c in configs if c.name in dominated]

    # Find the recommended configuration:
    # 1. Must meet quality floor (>= 8.5) and reliability >= 95%
    # 2. Prioritize non-dominated frontier configurations
    # 3. Choose the lowest cost option meeting quality floor, or the highest quality within target budget
    qualifying_frontier = [
        c for c in configs
        if c.name in frontier_names and c.meets_quality_floor and c.reliability_pct >= 95.0
    ]

    qualifying_all = [
        c for c in configs
        if c.meets_quality_floor and c.reliability_pct >= 95.0
    ]

    candidate_pool = qualifying_frontier if qualifying_frontier else qualifying_all

    recommended = "UNKNOWN"
    rationale = ""

    if not candidate_pool:
        # Fallback: configuration with highest human quality score
        best = max(configs, key=lambda c: c.human_quality_score)
        recommended = best.name
        rationale = (
            f"No configuration met both quality floor ({quality_floor}) and reliability >= 95%. "
            f"Selected highest quality configuration {best.name} ({best.human_quality_score}/10 at ${best.total_cost_usd:.4f})."
        )
    else:
        # Check if any qualifying candidate meets target budget
        within_budget = [c for c in candidate_pool if c.meets_budget_target]
        if within_budget:
            # Pick highest quality among those within budget
            best_within = max(within_budget, key=lambda c: (c.human_quality_score, -c.total_cost_usd))
            recommended = best_within.name
            rationale = (
                f"Configuration {best_within.name} sits on the Pareto frontier, meets the strict quality floor "
                f"({best_within.human_quality_score:.2f} >= {quality_floor}), meets the target budget "
                f"(${best_within.total_cost_usd:.4f} <= ${target_budget:.2f}), and achieves 100% reliability."
            )
        else:
            # Pick lowest cost among qualifying candidates
            lowest_cost_qualifying = min(candidate_pool, key=lambda c: (c.total_cost_usd, -c.human_quality_score))
            recommended = lowest_cost_qualifying.name
            rationale = (
                f"Configuration {lowest_cost_qualifying.name} represents the minimum production cost "
                f"(${lowest_cost_qualifying.total_cost_usd:.4f}) that strictly satisfies the human quality floor "
                f"({lowest_cost_qualifying.human_quality_score:.2f} >= {quality_floor}) with {lowest_cost_qualifying.reliability_pct:.1f}% reliability."
            )

    table_md = _build_markdown_table(configs, frontier_names, recommended, quality_floor, target_budget)

    return ParetoAnalysisResult(
        configurations=configs,
        frontier_configurations=frontier_names,
        dominated_configurations=dominated_names,
        recommended_configuration=recommended,
        sweet_spot_rationale=rationale,
        comparison_table_md=table_md,
    )


def _build_markdown_table(
    configs: list[ConfigurationMetric],
    frontier_names: list[str],
    recommended: str,
    quality_floor: float,
    target_budget: float,
) -> str:
    """Format configuration metrics into an empirical comparison table."""
    lines = [
        "| Configuration | Kling / Motion | Candidates | Bible | Total Cost | Quality | Visual | Motion | Rel % | Pareto Status | Gate Status |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for c in sorted(configs, key=lambda x: x.total_cost_usd):
        frontier_badge = "**FRONTIER**" if c.name in frontier_names else "Dominated"
        if c.name == recommended:
            frontier_badge += " ★ (SWEET SPOT)"

        gate_badge = "PASS" if (c.meets_quality_floor and c.reliability_pct >= 95.0) else "FAIL (<8.5)"

        lines.append(
            f"| `{c.name}` | {c.kling_shots}K / {c.image_motion_shots}M | {c.candidate_policy} | "
            f"{'Yes' if c.continuity_bible else 'No'} | ${c.total_cost_usd:.4f} | "
            f"**{c.human_quality_score:.2f}/10** | {c.visual_quality_score:.2f} | {c.motion_realism_score:.2f} | "
            f"{c.reliability_pct:.0f}% | {frontier_badge} | {gate_badge} |"
        )

    return "\n".join(lines)
