"""Smart Shot Allocator for ARYA OS.

Implements cost-aware, quality-first visual budget allocation per Task 22:
- Dynamic scoring of motion importance and keyframe importance
- Smart candidate allocation (spending candidates on critical hooks/reveals, saving on ambient)
- Kling video vs deterministic FFmpeg image-motion allocation
- Quality floor enforcement with budget overrun tracking
- Itemized accepted vs rejected candidate cost accounting
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("arya.services.smart_allocator")

HIGH_MOTION_VERBS = {
    "attacks", "charges", "chases", "collapses", "crawls", "dodges",
    "explodes", "falls", "flees", "lunges", "runs", "rushes",
    "screams", "shatters", "slams", "sprints", "strikes", "swings",
    "tackles", "wrestles",
}

MEDIUM_MOTION_VERBS = {
    "approaches", "blinks", "creeps", "drifts", "emerges", "gestures",
    "glances", "kneels", "lifts", "nods", "opens", "peers",
    "raises", "reaches", "rises", "rotates", "shifts", "steps",
    "stumbles", "turns", "whispers",
}

STATIC_ATMOSPHERIC_TERMS = {
    "archway", "brick", "candle", "ceiling", "corridor", "crypt",
    "door", "doorway", "empty", "hallway", "lantern", "moonlight",
    "portrait", "relic", "room", "shadows", "silence", "stares",
    "stone", "wall", "window",
}


@dataclass
class AllocationDecision:
    """Per-shot allocation decision made by SmartShotAllocator."""

    shot_number: int
    generation_class: str  # "A", "B", "C"
    generation_mode: str  # "video", "image_motion"
    num_candidates: int  # 1 to 4
    motion_importance_score: float  # 0.0 to 1.0
    keyframe_importance_score: float  # 0.0 to 1.0
    estimated_cost: float  # USD
    reason: str
    budget_overrun_reason: str | None = None


@dataclass
class VisualBudgetPlan:
    """Summary of visual budget allocation across all shots."""

    target_budget_usd: float
    allocated_cost_usd: float
    kling_shot_count: int
    image_motion_shot_count: int
    total_candidates_generated: int
    decisions: list[AllocationDecision] = field(default_factory=list)
    budget_exceeded: bool = False
    overrun_reasons: list[str] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return self.allocated_cost_usd


@dataclass
class VisualCostBreakdown:
    """Exact itemized cost accounting for an ARYA OS production run."""

    narration_cost: float = 0.0
    music_cost: float = 0.0
    prompt_cost: float = 0.0
    accepted_keyframe_cost: float = 0.0
    rejected_keyframe_cost: float = 0.0
    kling_video_cost: float = 0.0
    image_motion_cost: float = 0.0
    total_production_cost: float = 0.0

    @property
    def keyframe_total_cost(self) -> float:
        return round(self.accepted_keyframe_cost + self.rejected_keyframe_cost, 4)

    @property
    def visual_total_cost(self) -> float:
        return round(
            self.accepted_keyframe_cost
            + self.rejected_keyframe_cost
            + self.kling_video_cost
            + self.image_motion_cost,
            4,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "narration_cost": round(self.narration_cost, 4),
            "music_cost": round(self.music_cost, 4),
            "prompt_cost": round(self.prompt_cost, 4),
            "accepted_keyframe_cost": round(self.accepted_keyframe_cost, 4),
            "rejected_keyframe_cost": round(self.rejected_keyframe_cost, 4),
            "keyframe_total_cost": self.keyframe_total_cost,
            "kling_video_cost": round(self.kling_video_cost, 4),
            "image_motion_cost": round(self.image_motion_cost, 4),
            "visual_total_cost": self.visual_total_cost,
            "total_production_cost": round(self.total_production_cost, 4),
        }


class SmartShotAllocator:
    """Allocates video generation mode and keyframe candidate budget per shot."""

    IMAGE_CANDIDATE_COST: float = 0.03
    KLING_SHOT_COST: float = 0.25
    IMAGE_MOTION_COST: float = 0.00

    def __init__(
        self,
        visual_budget_usd: float | None = None,
        max_kling_shots: int | None = None,
        quality_floor: float | None = None,
        candidate_policy: str | None = None,
        allocation_strategy: str | None = None,
        default_candidate_count: int | None = None,
        visual_profile: Any | None = None,
    ) -> None:
        settings = get_settings()
        from app.services.visual_profiles import resolve_visual_profile

        self.profile = resolve_visual_profile(
            visual_profile
            if visual_profile is not None
            else getattr(settings, "visual_profile", "current_legacy")
        )
        self.visual_budget_usd = (
            visual_budget_usd
            if visual_budget_usd is not None
            else getattr(settings, "visual_budget_usd", 0.80)
        )
        self.max_kling_shots = (
            max_kling_shots
            if max_kling_shots is not None
            else getattr(settings, "max_kling_shots", 1)
        )
        self.quality_floor = (
            quality_floor
            if quality_floor is not None
            else getattr(settings, "quality_floor", 8.5)
        )
        if candidate_policy is not None:
            self.candidate_policy = candidate_policy
        elif visual_profile is not None or self.profile.name != "current_legacy":
            self.candidate_policy = self.profile.candidate_policy
        else:
            self.candidate_policy = getattr(settings, "candidate_policy", "fixed")
        self.allocation_strategy = (
            allocation_strategy
            if allocation_strategy is not None
            else getattr(settings, "allocation_strategy", "hybrid")
        )
        self.default_candidate_count = (
            default_candidate_count
            if default_candidate_count is not None
            else getattr(settings, "visual_keyframe_candidates", 1)
        )
        self.image_candidate_cost = self.profile.cost_per_image
        self.kling_shot_cost = self.profile.cost_per_video

    def score_motion_importance(self, shot: Any) -> float:
        """Score the motion importance of a shot (0.0 to 1.0).

        Higher score indicates shot requires generative AI video (Kling)
        to deliver realistic physical kinetic movement.
        """
        score = 0.30

        gen_class = (
            getattr(shot, "generation_class", None)
            or (shot.get("generation_class") if isinstance(shot, dict) else None)
            or ""
        )
        if isinstance(gen_class, Enum):
            gen_class = gen_class.value
        gen_class = str(gen_class).upper()

        if gen_class == "A":
            score += 0.30
        elif gen_class == "B":
            score += 0.10
        elif gen_class == "C":
            score -= 0.15

        narrative_beat = (
            getattr(shot, "narrative_beat", None)
            or (shot.get("narrative_beat") if isinstance(shot, dict) else None)
            or ""
        )
        if isinstance(narrative_beat, Enum):
            narrative_beat = narrative_beat.value
        narrative_beat = str(narrative_beat).upper()

        beat_bonuses = {
            "ACTION": 0.35,
            "HOOK": 0.20,
            "ESCALATION": 0.15,
            "REVEAL": 0.20,
            "REACTION": 0.05,
            "ESTABLISH": -0.10,
            "CONSEQUENCE": -0.10,
            "ENDING": 0.05,
        }
        score += beat_bonuses.get(narrative_beat, 0.0)

        action_text = (
            getattr(shot, "action", None)
            or getattr(shot, "description", None)
            or (shot.get("action") if isinstance(shot, dict) else "")
            or (shot.get("description") if isinstance(shot, dict) else "")
            or ""
        ).lower()

        tokens = set(re.findall(r"\b[a-z]+\b", action_text))
        if tokens & HIGH_MOTION_VERBS:
            score += 0.25
        elif tokens & MEDIUM_MOTION_VERBS:
            score += 0.10

        if tokens & STATIC_ATMOSPHERIC_TERMS and not (tokens & HIGH_MOTION_VERBS):
            score -= 0.10

        return max(0.0, min(1.0, round(score, 3)))

    def score_keyframe_importance(self, shot: Any) -> float:
        """Score the keyframe visual importance of a shot (0.0 to 1.0).

        Higher score indicates shot requires multiple candidate generation
        and selection to avoid deformities and maximize cinematic aesthetic.
        """
        score = 0.35

        narrative_beat = (
            getattr(shot, "narrative_beat", None)
            or (shot.get("narrative_beat") if isinstance(shot, dict) else None)
            or ""
        )
        if isinstance(narrative_beat, Enum):
            narrative_beat = narrative_beat.value
        narrative_beat = str(narrative_beat).upper()

        beat_bonuses = {
            "HOOK": 0.35,  # First visual anchor must look phenomenal
            "REVEAL": 0.30,  # Climax / creature reveal is critical
            "CHARACTER": 0.25,  # Character close-up sensitive to AI artifacts
            "ACTION": 0.15,
            "ESCALATION": 0.10,
            "ESTABLISH": 0.05,
            "ENDING": 0.15,
        }
        score += beat_bonuses.get(narrative_beat, 0.0)

        shot_num = getattr(shot, "shot_number", None) or (
            shot.get("shot_number") if isinstance(shot, dict) else 1
        )
        if shot_num == 1:
            score += 0.15  # Shot 1 is the hook

        subject_text = (
            getattr(shot, "subject", None)
            or getattr(shot, "description", None)
            or (shot.get("subject") if isinstance(shot, dict) else "")
            or ""
        ).lower()

        char_tokens = {"face", "eyes", "father", "priest", "thomas", "man", "woman", "person", "creature", "beast", "entity", "demon"}
        tokens = set(re.findall(r"\b[a-z]+\b", subject_text))
        if tokens & char_tokens:
            score += 0.20

        return max(0.0, min(1.0, round(score, 3)))

    def allocate(
        self,
        shots: list[Any],
        budget_usd: float | None = None,
        max_kling: int | None = None,
        candidate_policy: str | None = None,
        quality_floor: float | None = None,
    ) -> VisualBudgetPlan:
        """Execute cost-aware, quality-first visual budget allocation."""
        budget = budget_usd if budget_usd is not None else self.visual_budget_usd
        kling_limit = max_kling if max_kling is not None else self.max_kling_shots
        policy = candidate_policy if candidate_policy is not None else self.candidate_policy
        q_floor = quality_floor if quality_floor is not None else self.quality_floor

        scored_shots: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            m_score = self.score_motion_importance(shot)
            k_score = self.score_keyframe_importance(shot)
            shot_num = getattr(shot, "shot_number", idx + 1)
            scored_shots.append({
                "index": idx,
                "shot_obj": shot,
                "shot_number": shot_num,
                "motion_score": m_score,
                "keyframe_score": k_score,
            })

        # Sort by motion score descending to prioritize generative video
        scored_by_motion = sorted(
            scored_shots, key=lambda s: s["motion_score"], reverse=True
        )

        kling_indices: set[int] = set()
        overrun_reasons: list[str] = []

        # 1. Allocate top kinetic shots up to kling_limit
        for s in scored_by_motion:
            if len(kling_indices) < kling_limit and s["motion_score"] >= 0.40:
                kling_indices.add(s["index"])

        # 2. Quality Floor Protection: If any remaining shot has high motion (>= 0.75)
        # where image-motion would fail the quality floor (>= 8.5), promote it!
        for s in scored_by_motion:
            if s["index"] not in kling_indices and s["motion_score"] >= 0.75:
                kling_indices.add(s["index"])
                reason = (
                    f"Shot {s['shot_number']} promoted to Kling (motion_score={s['motion_score']:.2f}) "
                    f"to prevent quality floor breach (<{q_floor:.1f})"
                )
                overrun_reasons.append(reason)
                logger.info("quality_floor_promotion", reason=reason)

        decisions: list[AllocationDecision] = []
        total_candidates = 0
        total_allocated_cost = 0.0

        for s in scored_shots:
            idx = s["index"]
            shot = s["shot_obj"]
            shot_num = s["shot_number"]
            m_score = s["motion_score"]
            k_score = s["keyframe_score"]

            is_kling = idx in kling_indices
            gen_mode = "video" if is_kling else "image_motion"
            gen_class = "A" if is_kling else ("B" if k_score >= 0.40 else "C")

            # Determine candidate count
            if policy in ("lean", "smart_lean"):
                num_cand = self.profile.get_candidate_count(gen_class, is_key_beat=(k_score >= 0.65 or is_kling), keyframe_score=k_score)
            elif policy in ("flagship", "smart_flagship"):
                num_cand = self.profile.get_candidate_count(gen_class, is_key_beat=(k_score >= 0.65 or is_kling), keyframe_score=k_score)
            elif policy == "smart":
                if k_score >= 0.65 or is_kling:
                    num_cand = 3  # High importance / Hook / Action / Climax
                elif k_score >= 0.45:
                    num_cand = 2  # Medium importance
                else:
                    num_cand = 1  # Ambient / Background / Architecture
            else:
                num_cand = max(1, min(4, self.default_candidate_count))

            total_candidates += num_cand

            # Cost calculation using profile rate or class defaults
            img_rate = getattr(self, "image_candidate_cost", self.IMAGE_CANDIDATE_COST)
            vid_rate = getattr(self, "kling_shot_cost", self.KLING_SHOT_COST)
            keyframe_cost = num_cand * img_rate
            video_cost = vid_rate if is_kling else self.IMAGE_MOTION_COST
            shot_est_cost = round(keyframe_cost + video_cost, 4)
            total_allocated_cost += shot_est_cost

            # Reason string
            if is_kling:
                reason = (
                    f"Generative video (Kling) allocated for kinetic motion "
                    f"(motion_score={m_score:.2f}, keyframe_score={k_score:.2f}, cand={num_cand})"
                )
            else:
                reason = (
                    f"FFmpeg image-motion allocated for atmosphere/pacing "
                    f"(motion_score={m_score:.2f}, keyframe_score={k_score:.2f}, cand={num_cand})"
                )

            overrun_reason = None
            if is_kling and len(kling_indices) > kling_limit:
                overrun_reason = f"Quality floor protection for kinetic beat {shot_num}"

            decision = AllocationDecision(
                shot_number=shot_num,
                generation_class=gen_class,
                generation_mode=gen_mode,
                num_candidates=num_cand,
                motion_importance_score=m_score,
                keyframe_importance_score=k_score,
                estimated_cost=shot_est_cost,
                reason=reason,
                budget_overrun_reason=overrun_reason,
            )
            decisions.append(decision)

            # Update mutable shot object if applicable
            self._apply_decision_to_shot(shot, decision)

        total_allocated_cost = round(total_allocated_cost, 4)
        budget_exceeded = total_allocated_cost > budget

        plan = VisualBudgetPlan(
            target_budget_usd=budget,
            allocated_cost_usd=total_allocated_cost,
            kling_shot_count=len(kling_indices),
            image_motion_shot_count=len(shots) - len(kling_indices),
            total_candidates_generated=total_candidates,
            decisions=decisions,
            budget_exceeded=budget_exceeded,
            overrun_reasons=overrun_reasons,
        )

        logger.info(
            "visual_budget_allocated",
            target_budget=budget,
            allocated_cost=total_allocated_cost,
            kling_shots=plan.kling_shot_count,
            image_motion_shots=plan.image_motion_shot_count,
            total_candidates=total_candidates,
            budget_exceeded=budget_exceeded,
        )
        return plan

    def _apply_decision_to_shot(self, shot: Any, decision: AllocationDecision) -> None:
        """Propagate allocation decisions onto the Shot or CinematicShotPlan instance."""
        if hasattr(shot, "generation_class"):
            from app.schemas.cinematic import GenerationClass
            try:
                shot.generation_class = GenerationClass(decision.generation_class)
            except Exception:
                shot.generation_class = decision.generation_class

        if hasattr(shot, "generation_mode"):
            from app.schemas.cinematic import GenerationMode
            try:
                shot.generation_mode = GenerationMode(decision.generation_mode)
            except Exception:
                shot.generation_mode = decision.generation_mode

        if hasattr(shot, "num_candidates"):
            shot.num_candidates = decision.num_candidates
        if hasattr(shot, "estimated_cost"):
            shot.estimated_cost = decision.estimated_cost
        if hasattr(shot, "cost_reason"):
            shot.cost_reason = decision.reason
        if hasattr(shot, "budget_overrun_reason") and decision.budget_overrun_reason:
            shot.budget_overrun_reason = decision.budget_overrun_reason
        elif isinstance(shot, dict):
            shot["generation_class"] = decision.generation_class
            shot["generation_mode"] = decision.generation_mode
            shot["num_candidates"] = decision.num_candidates
            shot["estimated_cost"] = decision.estimated_cost
            shot["cost_reason"] = decision.reason
            if decision.budget_overrun_reason:
                shot["budget_overrun_reason"] = decision.budget_overrun_reason

    @classmethod
    def calculate_cost_breakdown(
        cls,
        shots: list[Any],
        narration_cost: float = 0.0,
        music_cost: float = 0.0,
        prompt_cost: float = 0.0,
        kling_rate: float | None = None,
        image_candidate_rate: float | None = None,
        visual_profile: Any | None = None,
    ) -> VisualCostBreakdown:
        """Compute exact itemized costs separating accepted vs rejected candidates."""
        effective_kling_rate = 0.25 if kling_rate is None else kling_rate
        effective_image_rate = 0.03 if image_candidate_rate is None else image_candidate_rate

        if visual_profile is not None:
            from app.services.visual_profiles import resolve_visual_profile
            prof = resolve_visual_profile(visual_profile)
            if image_candidate_rate is None:
                effective_image_rate = prof.cost_per_image
            if kling_rate is None:
                effective_kling_rate = prof.cost_per_video

        kling_count = 0
        accepted_cand_count = 0
        rejected_cand_count = 0

        for shot in shots:
            mode = getattr(shot, "generation_mode", None) or (
                shot.get("generation_mode") if isinstance(shot, dict) else ""
            )
            if hasattr(mode, "value"):
                mode = mode.value
            mode = str(mode).lower()

            if mode in ("video", "kling"):
                kling_count += 1

            num_cand = getattr(shot, "num_candidates", None) or (
                shot.get("num_candidates") if isinstance(shot, dict) else 1
            )
            try:
                num_cand = max(1, int(num_cand))
            except (ValueError, TypeError):
                num_cand = 1

            accepted_cand_count += 1
            rejected_cand_count += max(0, num_cand - 1)

        acc_keyframe_cost = round(accepted_cand_count * effective_image_rate, 4)
        rej_keyframe_cost = round(rejected_cand_count * effective_image_rate, 4)
        kling_cost = round(kling_count * effective_kling_rate, 4)
        image_motion_cost = 0.0

        total = round(
            narration_cost
            + music_cost
            + prompt_cost
            + acc_keyframe_cost
            + rej_keyframe_cost
            + kling_cost
            + image_motion_cost,
            4,
        )

        return VisualCostBreakdown(
            narration_cost=round(narration_cost, 4),
            music_cost=round(music_cost, 4),
            prompt_cost=round(prompt_cost, 4),
            accepted_keyframe_cost=acc_keyframe_cost,
            rejected_keyframe_cost=rej_keyframe_cost,
            kling_video_cost=kling_cost,
            image_motion_cost=image_motion_cost,
            total_production_cost=total,
        )
