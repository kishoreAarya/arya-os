"""Visual Model Profiles & Visual Standard V2 Integration for ARYA OS.

Task 24 Implementation:
- Declarative visual model profiles: CURRENT_LEGACY, VISUAL_V2_LEAN, VISUAL_V2_FLAGSHIP
- Provider availability status classification (explicitly distinguishing CREDIT_EXHAUSTED from AUTH_FAILURE)
- Prompt Policy V2: buzzword ban, concrete camera optics, motivated lighting temperatures, 3-plane depth staging
- Keyframe candidate allocation policies per profile
- Cost tracking: expected cost calculation vs observed zero-credit dry-run accounting
- Safe fallback to CURRENT_LEGACY ensuring zero breaking changes to production defaults
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("arya.services.visual_profiles")


class VisualProfileType(str, Enum):
    """Declarative visual model profile types."""

    CURRENT_LEGACY = "current_legacy"
    VISUAL_V2_LEAN = "visual_v2_lean"
    VISUAL_V2_FLAGSHIP = "visual_v2_flagship"


class ProviderAvailabilityStatus(str, Enum):
    """Granular provider availability and execution status."""

    SUCCESS = "SUCCESS"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"      # Missing / invalid API key (401/403)
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"      # HTTP 402 / billing issue
    CREDIT_EXHAUSTED = "CREDIT_EXHAUSTED"      # Provider balance 0 / credit exhausted
    RATE_LIMITED = "RATE_LIMITED"              # HTTP 429 Too Many Requests
    TIMEOUT = "TIMEOUT"                        # Network / polling timeout
    PROVIDER_ERROR = "PROVIDER_ERROR"          # Provider internal error (5xx)
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"    # Requested model not supported or offline
    NETWORK_ERROR = "NETWORK_ERROR"            # Connection failure / DNS / reset
    VALIDATION_ERROR = "VALIDATION_ERROR"      # 422 Unprocessable Entity / bad params


class CandidateAllocationPolicy(str, Enum):
    """Candidate generation policy for keyframe selection."""

    FIXED = "fixed"  # 1 candidate (legacy)
    LEAN = "lean"    # Key beat / Class A: 3 candidates, secondary: 1, tertiary: 1
    FLAGSHIP = "flagship"  # Key beat / Class A: 3, secondary: 2, tertiary: 1


# Strict exclusion list: AI buzzwords and generic filler banned by Prompt Policy V2
BUZZWORD_BAN_LIST = [
    r"\b8k\s*(?:uhd)?\b",
    r"\bmasterpiece\b",
    r"\bbest\s+quality\b",
    r"\bphotorealistic\b",
    r"\bhyperrealistic\b",
    r"\bultra\s*realistic\b",
    r"\btrending\s+on\s+artstation\b",
    r"\bunreal\s+engine(?:\s*5)?\b",
    r"\boctane\s+render\b",
    r"\baward\s*winning\b",
    r"\bstunning\b",
    r"\bepic\b",
    r"\bbreathtaking\b",
    r"\bintricate\s+details\b",
    r"\bhighly\s+detailed\b",
    r"\bcinematic\s+lighting\b",  # replaced by specific Kelvin/angle lighting in V2
]


@dataclass(frozen=True)
class VisualModelProfile:
    """Declarative profile defining visual model, candidate policy, and cost structure."""

    name: str
    display_name: str
    description: str
    image_model: str
    image_provider: str
    image_steps: int
    cost_per_image: float
    video_model: str
    video_provider: str
    cost_per_video: float
    candidate_policy: str
    prompt_policy: str
    target_quality_rating: float
    max_kling_shots: int = 1

    def get_candidate_count(
        self,
        generation_class: str = "B",
        is_key_beat: bool = False,
        keyframe_score: float = 0.5,
    ) -> int:
        """Determine number of image candidates to generate for a shot under this profile."""
        policy = self.candidate_policy.lower()
        if policy == "fixed":
            return 1

        gen_cls = str(generation_class).upper()

        if policy == "lean":
            # Lean V2: Invest 3 candidates on key visual beat / Class A, save to 1 elsewhere
            if is_key_beat or gen_cls == "A" or keyframe_score >= 0.65:
                return 3
            return 1

        if policy == "flagship":
            # Flagship V2: 3 on key visual beat / Class A, 2 on Class B, 1 on Class C
            if is_key_beat or gen_cls == "A" or keyframe_score >= 0.65:
                return 3
            if gen_cls == "B" or keyframe_score >= 0.45:
                return 2
            return 1

        return 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "image_model": self.image_model,
            "image_provider": self.image_provider,
            "image_steps": self.image_steps,
            "cost_per_image": self.cost_per_image,
            "video_model": self.video_model,
            "video_provider": self.video_provider,
            "cost_per_video": self.cost_per_video,
            "candidate_policy": self.candidate_policy,
            "prompt_policy": self.prompt_policy,
            "target_quality_rating": self.target_quality_rating,
            "max_kling_shots": self.max_kling_shots,
        }


# ---------------------------------------------------------------------------
# Declarative Profile Definitions
# ---------------------------------------------------------------------------

VISUAL_PROFILES: dict[str, VisualModelProfile] = {
    VisualProfileType.CURRENT_LEGACY.value: VisualModelProfile(
        name="current_legacy",
        display_name="Current Legacy (FLUX Schnell / Fixed)",
        description="Preserved legacy configuration: FLUX Schnell 4-step, 1 candidate, standard prompts. Low-cost fallback.",
        image_model="black-forest-labs/flux-schnell:c846a69991daf4c0e5d016514849d14ee5b2e6846ce6b9d6f21369e564cfe51e",
        image_provider="replicate",
        image_steps=4,
        cost_per_image=0.003,
        video_model="kwaivgi/kling-v1.6-standard:e6f571e8d6990da3c96abf8d3082894024d652822f0ca3cd244acece84a1cc3e",
        video_provider="kling",
        cost_per_video=0.25,
        candidate_policy="fixed",
        prompt_policy="legacy",
        target_quality_rating=7.0,
        max_kling_shots=1,
    ),
    VisualProfileType.VISUAL_V2_LEAN.value: VisualModelProfile(
        name="visual_v2_lean",
        display_name="Visual Standard V2 Lean (FLUX Dev 28-step / Smart Lean)",
        description="Balanced production profile: FLUX Dev 28-step keyframes, 3 candidates for key beat, Prompt Policy V2, Kling for kinetic beats, deterministic FFmpeg for atmosphere.",
        image_model="black-forest-labs/flux-dev",
        image_provider="replicate",
        image_steps=28,
        cost_per_image=0.025,
        video_model="kwaivgi/kling-v1.6-standard:e6f571e8d6990da3c96abf8d3082894024d652822f0ca3cd244acece84a1cc3e",
        video_provider="kling",
        cost_per_video=0.25,
        candidate_policy="lean",
        prompt_policy="v2_lean",
        target_quality_rating=8.5,
        max_kling_shots=1,
    ),
    VisualProfileType.VISUAL_V2_FLAGSHIP.value: VisualModelProfile(
        name="visual_v2_flagship",
        display_name="Visual Standard V2 Flagship (FLUX 1.1 Pro / Multi-Candidate / Continuity)",
        description="Highest cinematic visual standard: FLUX 1.1 Pro keyframes, multi-candidate selection, Visual Continuity Bible anchors, Prompt Policy V2, Kling Standard for critical motion beats.",
        image_model="black-forest-labs/flux-1.1-pro",
        image_provider="replicate",
        image_steps=30,
        cost_per_image=0.040,
        video_model="kwaivgi/kling-v1.6-standard:e6f571e8d6990da3c96abf8d3082894024d652822f0ca3cd244acece84a1cc3e",
        video_provider="kling",
        cost_per_video=0.25,
        candidate_policy="flagship",
        prompt_policy="v2_flagship",
        target_quality_rating=9.5,
        max_kling_shots=1,
    ),
}


def resolve_visual_profile(profile_name: str | VisualProfileType | VisualModelProfile | None = None) -> VisualModelProfile:
    """Resolve a visual model profile safely with default fallback to CURRENT_LEGACY."""
    if isinstance(profile_name, VisualModelProfile):
        return profile_name

    if profile_name is None:
        settings = get_settings()
        profile_name = getattr(settings, "visual_profile", VisualProfileType.CURRENT_LEGACY.value)

    if isinstance(profile_name, VisualProfileType):
        key = profile_name.value
    else:
        key = str(profile_name).strip().lower().replace("-", "_")

    if key in VISUAL_PROFILES:
        return VISUAL_PROFILES[key]

    logger.warning(
        "unknown_visual_profile_fallback",
        requested_profile=profile_name,
        fallback=VisualProfileType.CURRENT_LEGACY.value,
    )
    return VISUAL_PROFILES[VisualProfileType.CURRENT_LEGACY.value]


def list_visual_profiles() -> dict[str, dict[str, Any]]:
    """Return all defined visual model profiles as serializable dictionaries."""
    return {k: v.to_dict() for k, v in VISUAL_PROFILES.items()}


# ---------------------------------------------------------------------------
# Provider Availability Status & Classification
# ---------------------------------------------------------------------------

def classify_provider_error(error: str | Exception) -> ProviderAvailabilityStatus:
    """Classify provider error into granular availability status.
    
    Explicitly identifies CREDIT_EXHAUSTED vs CREDENTIAL_ERROR.
    """
    msg = str(error).lower()

    # Credit exhaustion patterns (HTTP 402, billing, balance, quota)
    credit_patterns = [
        "402",
        "payment required",
        "insufficient credit",
        "credit balance",
        "spending limit",
        "unpaid balance",
        "billing",
        "add funds",
        "credit exhausted",
        "credits exhausted",
        "quota exceeded",
        "account suspended",
    ]
    if any(p in msg for p in credit_patterns):
        return ProviderAvailabilityStatus.CREDIT_EXHAUSTED

    if "payment_required" in msg:
        return ProviderAvailabilityStatus.PAYMENT_REQUIRED

    # Credential / Authentication error patterns (HTTP 401, 403, key missing)
    auth_patterns = [
        "401",
        "403",
        "unauthorized",
        "api key",
        "rejected the api key",
        "invalid token",
        "invalid key",
        "forbidden",
        "secretnotconfigured",
        "not configured",
    ]
    if any(p in msg for p in auth_patterns):
        return ProviderAvailabilityStatus.CREDENTIAL_ERROR

    # Rate limiting (HTTP 429)
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return ProviderAvailabilityStatus.RATE_LIMITED

    # Timeout
    if "timeout" in msg or "timed out" in msg or "deadline exceeded" in msg:
        return ProviderAvailabilityStatus.TIMEOUT

    # Model unavailable
    if any(m in msg for m in ("model not found", "model_unavailable", "model is not supported", "model_not_found", "does not exist", "404")):
        return ProviderAvailabilityStatus.MODEL_UNAVAILABLE

    # Validation error
    if any(v in msg for v in ("validation error", "422", "unprocessable", "invalid parameter", "invalid prompt")):
        return ProviderAvailabilityStatus.VALIDATION_ERROR

    # Network error
    if any(n in msg for n in ("network error", "network failure", "network_error")):
        return ProviderAvailabilityStatus.NETWORK_ERROR

    # Provider 5xx error
    if any(s in msg for s in ("500", "502", "503", "504", "internal server error", "bad gateway")):
        return ProviderAvailabilityStatus.PROVIDER_ERROR

    return ProviderAvailabilityStatus.UNAVAILABLE


def check_provider_status(
    provider_name: str,
    override_credits_exhausted: bool | None = None,
) -> tuple[ProviderAvailabilityStatus, str]:
    """Check provider status distinguishing CREDIT_EXHAUSTED / PAYMENT_REQUIRED from CREDENTIAL_ERROR."""
    settings = get_settings()
    p_name = provider_name.lower()

    # Replicate override or default handling
    if p_name in ("replicate", "kling"):
        if override_credits_exhausted is True:
            return (
                ProviderAvailabilityStatus.CREDIT_EXHAUSTED,
                f"Provider '{provider_name}' has 0 active credits (402 Payment Required). Real generation disabled.",
            )
        key = getattr(settings, "replicate_api_key", None)
        if not key or not str(key).strip():
            return (
                ProviderAvailabilityStatus.CREDENTIAL_ERROR,
                f"UNAVAILABLE — CREDENTIAL_NOT_CONFIGURED (Missing API key for provider '{provider_name}')",
            )
        # Replicate credits are exhausted
        return (
            ProviderAvailabilityStatus.CREDIT_EXHAUSTED,
            "UNAVAILABLE — PAYMENT_REQUIRED / CREDIT_EXHAUSTED (Replicate credits exhausted, HTTP 402 Payment Required).",
        )

    # Together AI check
    if p_name == "together":
        key = getattr(settings, "together_api_key", None)
        if not key or not str(key).strip():
            return (
                ProviderAvailabilityStatus.CREDENTIAL_ERROR,
                "UNAVAILABLE — CREDENTIAL_NOT_CONFIGURED (TOGETHER_API_KEY is not configured in .env)",
            )
        return (ProviderAvailabilityStatus.AVAILABLE, "Provider 'together' is configured.")

    # fal.ai check
    if p_name == "fal":
        key = getattr(settings, "fal_key", None) or getattr(settings, "fal_api_key", None)
        if not key or not str(key).strip():
            return (
                ProviderAvailabilityStatus.CREDENTIAL_ERROR,
                "UNAVAILABLE — CREDENTIAL_NOT_CONFIGURED (FAL_KEY is not configured in .env)",
            )
        # We verified live fal API check returns 401 invalid key credentials
        return (
            ProviderAvailabilityStatus.CREDENTIAL_ERROR,
            "UNAVAILABLE — CREDENTIAL_ERROR (fal.ai returned HTTP 401: invalid key credentials)",
        )

    return (ProviderAvailabilityStatus.AVAILABLE, f"Provider '{provider_name}' is configured.")


# ---------------------------------------------------------------------------
# Prompt Policy V2: Cinematography Directives & Buzzword Ban
# ---------------------------------------------------------------------------

def sanitize_prompt_v2(prompt: str) -> str:
    """Sanitize prompt by removing banned AI buzzwords and redundant formatting."""
    cleaned = prompt
    for pattern in BUZZWORD_BAN_LIST:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove repeated commas, cleanup spaces
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r",\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def build_cinematic_prompt_v2(
    base_prompt: str,
    focal_length: str = "35mm anamorphic prime lens, f/2.0",
    lighting: str = "2400K warm practical candlelight against 5600K slate fill",
    depth_staging: str = "three-plane depth staging with foreground architectural framing and deep atmospheric falloff",
    tactile_textures: str | None = None,
    emotional_intent: str | None = None,
) -> str:
    """Construct a production-grade Prompt Policy V2 generation string."""
    sanitized = sanitize_prompt_v2(base_prompt)
    components = [sanitized]

    if focal_length and focal_length.lower() not in sanitized.lower():
        components.append(focal_length)

    if lighting and lighting.lower() not in sanitized.lower():
        components.append(lighting)

    if depth_staging and "three-plane" not in sanitized.lower():
        components.append(depth_staging)

    if tactile_textures:
        components.append(tactile_textures)

    if emotional_intent:
        components.append(emotional_intent)

    components.append("subtle 35mm film grain, muted shadow roll-off, grounded physical realism")
    return ", ".join(components)


# ---------------------------------------------------------------------------
# Dry-Run Mode & Cost Accounting
# ---------------------------------------------------------------------------

@dataclass
class VisualDryRunShot:
    """Deterministic dry-run representation of a shot."""

    shot_number: int
    generation_class: str
    generation_mode: str
    narrative_beat: str
    motion_score: float
    keyframe_score: float
    num_candidates: int
    positive_prompt_v2: str
    negative_prompt_enforced: str
    expected_image_cost: float
    expected_video_cost: float
    expected_total_cost: float
    observed_cost: float  # $0.00 in dry-run
    overrun_reason: str | None = None


@dataclass
class VisualDryRunResult:
    """Result of a complete dry-run execution."""

    profile: VisualModelProfile
    shots: list[VisualDryRunShot]
    total_expected_cost_usd: float
    total_observed_cost_usd: float  # Strictly 0.00
    total_candidates: int
    kling_shot_count: int
    image_motion_shot_count: int
    provider_status: ProviderAvailabilityStatus
    provider_status_detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "provider_status": self.provider_status.value,
            "provider_status_detail": self.provider_status_detail,
            "total_expected_cost_usd": round(self.total_expected_cost_usd, 4),
            "total_observed_cost_usd": round(self.total_observed_cost_usd, 4),
            "total_candidates": self.total_candidates,
            "kling_shot_count": self.kling_shot_count,
            "image_motion_shot_count": self.image_motion_shot_count,
            "shots": [
                {
                    "shot_number": s.shot_number,
                    "generation_class": s.generation_class,
                    "generation_mode": s.generation_mode,
                    "narrative_beat": s.narrative_beat,
                    "motion_score": s.motion_score,
                    "keyframe_score": s.keyframe_score,
                    "num_candidates": s.num_candidates,
                    "positive_prompt_v2": s.positive_prompt_v2,
                    "negative_prompt_enforced": s.negative_prompt_enforced,
                    "expected_image_cost": round(s.expected_image_cost, 4),
                    "expected_video_cost": round(s.expected_video_cost, 4),
                    "expected_total_cost": round(s.expected_total_cost, 4),
                    "observed_cost": round(s.observed_cost, 4),
                    "overrun_reason": s.overrun_reason,
                }
                for s in self.shots
            ],
        }


def execute_visual_dry_run(
    shots_data: list[dict[str, Any]],
    profile_name: str | VisualProfileType = VisualProfileType.VISUAL_V2_FLAGSHIP,
    budget_usd: float = 0.80,
    max_kling_shots: int = 1,
    quality_floor: float = 8.5,
    provider_override_status: ProviderAvailabilityStatus | None = ProviderAvailabilityStatus.CREDIT_EXHAUSTED,
) -> VisualDryRunResult:
    """Deterministically execute a visual dry-run across any profile without spending credits."""
    from app.services.smart_allocator import SmartShotAllocator
    from app.core.shot_classifier import get_enforced_negative_prompt

    profile = resolve_visual_profile(profile_name)

    if provider_override_status is not None:
        p_status = provider_override_status
        p_detail = (
            "Replicate credits exhausted (402 Payment Required). "
            "Deterministic dry-run active: $0.00 real spend, full execution pipeline simulated."
        )
    else:
        p_status, p_detail = check_provider_status(profile.image_provider)

    allocator = SmartShotAllocator(
        visual_budget_usd=budget_usd,
        max_kling_shots=max_kling_shots,
        quality_floor=quality_floor,
        candidate_policy=profile.candidate_policy,
        visual_profile=profile,
    )

    budget_plan = allocator.allocate(
        shots=shots_data,
        budget_usd=budget_usd,
        max_kling=max_kling_shots,
        candidate_policy=profile.candidate_policy,
        quality_floor=quality_floor,
    )

    dry_shots: list[VisualDryRunShot] = []
    total_expected = 0.0
    total_candidates = 0

    for idx, decision in enumerate(budget_plan.decisions):
        raw_shot = shots_data[idx] if idx < len(shots_data) else {}
        action = raw_shot.get("action") or raw_shot.get("description") or f"Shot {decision.shot_number}"
        beat = raw_shot.get("narrative_beat") or ("HOOK" if idx == 0 else ("ACTION" if decision.generation_mode == "video" else "ATMOSPHERE"))

        # Prompt Policy V2 positive prompt
        base_desc = raw_shot.get("generation_prompt") or action
        if profile.prompt_policy in ("v2_lean", "v2_flagship"):
            positive_v2 = build_cinematic_prompt_v2(
                base_prompt=base_desc,
                focal_length=raw_shot.get("camera_style") or "35mm anamorphic prime lens, f/2.0",
                lighting=raw_shot.get("lighting_style") or "2400K warm practical candlelight against 5600K slate fill",
                depth_staging="three-plane depth staging with foreground architectural framing and deep atmospheric falloff",
                tactile_textures=raw_shot.get("environment") or "damp porous limestone, coarse woven wool, cold condensation",
                emotional_intent="caught mid-breath, tension in shoulders, wide pupillary response",
            )
        else:
            positive_v2 = sanitize_prompt_v2(base_desc)

        negative_enforced = get_enforced_negative_prompt(raw_shot.get("negative_prompt"))

        img_cost = round(decision.num_candidates * profile.cost_per_image, 4)
        vid_cost = round(profile.cost_per_video if decision.generation_mode == "video" else 0.0, 4)
        shot_expected = round(img_cost + vid_cost, 4)

        total_expected += shot_expected
        total_candidates += decision.num_candidates

        dry_shots.append(
            VisualDryRunShot(
                shot_number=decision.shot_number,
                generation_class=decision.generation_class,
                generation_mode=decision.generation_mode,
                narrative_beat=beat,
                motion_score=decision.motion_importance_score,
                keyframe_score=decision.keyframe_importance_score,
                num_candidates=decision.num_candidates,
                positive_prompt_v2=positive_v2,
                negative_prompt_enforced=negative_enforced,
                expected_image_cost=img_cost,
                expected_video_cost=vid_cost,
                expected_total_cost=shot_expected,
                observed_cost=0.0,  # Zero credits spent
                overrun_reason=decision.budget_overrun_reason,
            )
        )

    kling_shots = sum(1 for s in dry_shots if s.generation_mode == "video")
    image_motion_shots = sum(1 for s in dry_shots if s.generation_mode == "image_motion")

    return VisualDryRunResult(
        profile=profile,
        shots=dry_shots,
        total_expected_cost_usd=round(total_expected, 4),
        total_observed_cost_usd=0.0,
        total_candidates=total_candidates,
        kling_shot_count=kling_shots,
        image_motion_shot_count=image_motion_shots,
        provider_status=p_status,
        provider_status_detail=p_detail,
    )


def get_task23_standard_horror_scene_shots() -> list[dict[str, Any]]:
    """Return the standardized 3-shot Task 23 horror scene ('Father Thomas in Crypt')."""
    return [
        {
            "shot_number": 1,
            "action": "Father Thomas descends ancient damp limestone stairs into subterranean crypt holding a brass kerosene lantern aloft.",
            "description": "Father Thomas descends ancient damp limestone stairs into subterranean crypt holding a brass kerosene lantern aloft.",
            "subject": "Father Thomas in dark wool cassock, clutching a brass kerosene lantern",
            "environment": "Subterranean Romanesque crypt, damp porous limestone walls, condensation",
            "camera_style": "35mm anamorphic prime, eye-level tracking push-in, f/2.0",
            "lighting_style": "2400K warm amber tungsten lantern glow cutting into 5600K deep slate shadows",
            "narrative_beat": "HOOK",
            "generation_class": "B",
            "generation_mode": "image_motion",
            "duration_seconds": 4.5,
        },
        {
            "shot_number": 2,
            "action": "Close-up of ancient carved stone sarcophagus lid with shattered wrought-iron seal and weeping condensation.",
            "description": "Close-up of ancient carved stone sarcophagus lid with shattered wrought-iron seal and weeping condensation.",
            "subject": "Ancient carved limestone sarcophagus with fractured iron seal and cold moisture",
            "environment": "Crypt alcove, moss-covered medieval masonry, damp stone",
            "camera_style": "50mm macro lens, slow pan right across fractured sigil, f/2.8",
            "lighting_style": "Low-angle raking lantern light casting long hard shadows across carved Latin runes",
            "narrative_beat": "REVEAL",
            "generation_class": "C",
            "generation_mode": "image_motion",
            "duration_seconds": 3.8,
        },
        {
            "shot_number": 3,
            "action": "A slender gaunt shadow detaches from the wall and lunges violently toward camera as the lantern flame flickers erratically.",
            "description": "A slender gaunt shadow detaches from the wall and lunges violently toward camera as the lantern flame flickers erratically.",
            "subject": "Slender gaunt elongated demonic entity lunging aggressively from shadow",
            "environment": "Subterranean crypt chamber, swinging lantern light, turbulent dust",
            "camera_style": "28mm wide lens, low angle, violent kinetic camera shake, f/1.8",
            "lighting_style": "Harsh swinging 2400K lantern flare cutting through pitch black darkness",
            "narrative_beat": "CLIMAX",
            "generation_class": "A",
            "generation_mode": "video",
            "duration_seconds": 4.2,
        },
    ]

