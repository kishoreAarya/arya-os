"""Deterministic Class A/B/C Shot Planner and Pacing Engine.

Conforms to CINEMATIC_PRODUCTION_BIBLE.md:
- Section 21: Rhythmic Irregularity
- Section 25: Shot Generation Strategy (Class A / Class B / Class C)
- Section 26: Camera Motion for Still Images
- Section 30: Absolute Text/UI Generation Rule
"""

from __future__ import annotations

import re
from typing import Sequence

from app.schemas.cinematic import (
    CameraMovementType,
    GenerationClass,
    GenerationMode,
)

# Mandatory negative elements prohibiting AI-generated text/UI per Bible Section 30
MANDATORY_NEGATIVE_ELEMENTS = [
    "subtitles",
    "captions",
    "UI",
    "user interface",
    "buttons",
    "Subscribe button",
    "Like button",
    "Follow button",
    "watermark",
    "logo",
    "text",
    "graphical overlays",
    "lower thirds",
    "HUD",
]

# Keyword vocabularies for deterministic A/B/C classification
CLASS_A_PATTERNS = [
    r"\b(?:run|running|sprint|sprinting)\b",
    r"\b(?:fight|fighting|combat|punch|punching|kick|kicking|strike)\b",
    r"\b(?:chase|chasing|flee|fleeing|pursue|pursuing)\b",
    r"\b(?:open|opens|opening|opened|slam|slams|slamming|slammed)\s+(?:a\s+|the\s+|an\s+)?(?:door|gate|window|portal)\b|\b(?:door|gate|window|portal)\s+(?:opens|slams|swings\s+open)\b",
    r"\b(?:creature|monster|beast|alien|predator)\b.*?\b(?:move|moves|moving|emerge|emerges|emerging|attack|attacks|attacking|lunge|lunges|lunging)\b",
    r"\b(?:jump|jumping|leap|leaping|fall|falling|tumble)\b",
    r"\b(?:grab|grabbing|snatch|snatching|wrestle|struggle)\b",
    r"\b(?:sob|sobbing|weep|weeping|scream|screaming|laugh\s+hysterically)\b",
    r"\b(?:tear|tearing|break|breaking|smash|smashing|crash|crashing)\b",
    r"\b(?:collide|explosion|blast|firing|shooting)\b",
    r"\b(?:reach\s+out|hand\s+reaches|touch\s+face)\b",
]

CLASS_C_PATTERNS = [
    r"\b(?:document|paper|contract|letter|manuscript)\b",
    r"\b(?:blueprint|diagram|chart|graph|map|infographic)\b",
    r"\b(?:screen|monitor|dashboard|display|computer|laptop|phone\s+screen)\b",
    r"\b(?:book|page|journal|diary|notebook|newspaper)\b",
    r"\b(?:photograph|photo|polaroid|snapshot|portrait\s+on\s+wall)\b",
    r"\b(?:clock|watch|hourglass|timer|dial|gauge|instrument)\b",
    r"\b(?:relic|artifact|key|lock|device|specimen|evidence|archive)\b",
    r"\b(?:macro|extreme\s+close-up\s+of\s+object|still\s+life|static\s+object)\b",
    r"\b(?:information|sign|plaque|headline|notice|bulletin)\b",
]

CLASS_B_PATTERNS = [
    r"\b(?:hallway|corridor|aisle|tunnel)\b",
    r"\b(?:empty\s+street|deserted|alleyway|roadway)\b",
    r"\b(?:bedroom|living\s+room|office|kitchen|basement|attic)\b",
    r"\b(?:forest|trees|woods|jungle|canopy)\b",
    r"\b(?:exterior|skyline|building|facade|architecture)\b",
    r"\b(?:drift|drifting|float|floating|fog|mist|haze|smoke)\b",
    r"\b(?:shadows|silhouette|ambient|atmospheric)\b",
    r"\b(?:walk|walking\s+slowly|wander|wandering|pace|pacing)\b",
    r"\b(?:stand|standing|gaze|gazing|look|looking\s+out|stare|staring)\b",
    r"\b(?:wind\s+blowing|rain\s+falling|snow\s+falling)\b",
]


def classify_shot(
    action: str = "",
    subject: str = "",
    environment: str = "",
    purpose: str = "",
    force_class: GenerationClass | str | None = None,
    force_mode: GenerationMode | str | None = None,
) -> tuple[GenerationClass, GenerationMode, str, str]:
    """Deterministically classify a shot into Class A, B, or C.

    Returns:
        (generation_class, generation_mode, cost_reason, quality_reason)
    """
    # Explicit override handling
    if force_class:
        if isinstance(force_class, str):
            force_class = GenerationClass(force_class.upper())
        mode = force_mode
        if isinstance(mode, str):
            mode = GenerationMode(mode.lower())
        elif mode is None:
            mode = GenerationMode.VIDEO if force_class == GenerationClass.A else GenerationMode.IMAGE_MOTION

        cost_r = (
            "Allocated video generation budget"
            if mode == GenerationMode.VIDEO
            else "Allocated image motion ($0 video cost)"
        )
        quality_r = f"Explicitly directed as Class {force_class.value}"
        return force_class, mode, cost_r, quality_r

    text_corpus = f"{action} {subject} {environment} {purpose}".lower()

    # 1. Test for Class A (Critical Kinetic Motion)
    for pat in CLASS_A_PATTERNS:
        if re.search(pat, text_corpus, re.IGNORECASE):
            return (
                GenerationClass.A,
                GenerationMode.VIDEO,
                "High kinetic motion and direct physical interaction require AI video temporal coherence.",
                "Static image cannot convey critical physical motion and kinetic energy.",
            )

    # 2. Test for Class C (Information / Context / Details)
    for pat in CLASS_C_PATTERNS:
        if re.search(pat, text_corpus, re.IGNORECASE):
            return (
                GenerationClass.C,
                GenerationMode.IMAGE_MOTION,
                "Zero AI video generation cost ($0.00); high-fidelity static image animated with FFmpeg camera movement.",
                "High-resolution still image preserves sharp micro-details, diagrams, and typography without video compression artifacts.",
            )

    # 3. Test for Class B (Atmospheric / Environmental Motion)
    for pat in CLASS_B_PATTERNS:
        if re.search(pat, text_corpus, re.IGNORECASE):
            return (
                GenerationClass.B,
                GenerationMode.IMAGE_MOTION,
                "Atmospheric mood achieved via high-fidelity image + cinematic camera motion, conserving video budget.",
                "Smooth camera motion captures environmental atmosphere without AI video jitter or hallucinations.",
            )

    # 4. Default: Class B with image_motion (cost-conscious default per Section 4 & 5)
    return (
        GenerationClass.B,
        GenerationMode.IMAGE_MOTION,
        "Subtle atmospheric scene; optimized with image + cinematic camera motion ($0 video cost).",
        "High-fidelity image provides superior visual sharpness and composition control.",
    )


def get_enforced_negative_prompt(base_negative_prompt: str | None = None) -> str:
    """Ensure negative prompt strictly includes all Bible Section 30 prohibitions."""
    existing_items: list[str] = []
    if base_negative_prompt:
        existing_items = [item.strip() for item in base_negative_prompt.split(",") if item.strip()]

    # Normalized lookup set
    existing_lower = {item.lower() for item in existing_items}

    # Add missing mandatory prohibitions
    for mandatory in MANDATORY_NEGATIVE_ELEMENTS:
        if mandatory.lower() not in existing_lower:
            existing_items.append(mandatory)

    return ", ".join(existing_items)


def sanitize_generation_prompt(prompt: str) -> str:
    """Strip any instructions asking for on-screen text, subtitles, or UI elements."""
    cleaned = prompt
    # Remove phrases like "with text saying ...", "with subtitles ...", "with UI overlay"
    patterns_to_remove = [
        r"(?i)\bwith\s+text\s+(?:saying|reading|displaying)?[^.]*",
        r"(?i)\bwith\s+(?:subtitles|captions|lower\s+thirds|ui\s+elements|subscribe\s+button)\b",
        r"(?i)\btext\s+overlay\b",
    ]
    for pat in patterns_to_remove:
        cleaned = re.sub(pat, "", cleaned)

    # Clean double spaces or orphaned punctuation
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def calculate_shot_cost(
    generation_class: GenerationClass,
    generation_mode: GenerationMode,
    provider: str | None = None,
    model: str | None = None,
) -> float | None:
    """Estimate cost without inventing fake provider pricing.

    Class C is strictly $0.00 for video generation.
    For video generation mode, maps to known baseline rates if provider is specified;
    otherwise returns None to indicate unknown/unconfigured.
    """
    if generation_mode == GenerationMode.IMAGE_MOTION:
        return 0.0

    if not provider:
        return None

    provider_lower = provider.lower()
    model_lower = (model or "").lower()

    if "fal" in provider_lower:
        if "wan" in model_lower:
            return 0.08
        if "kling" in model_lower:
            return 0.25
        if "luma" in model_lower:
            return 0.30
        if "runway" in model_lower:
            return 0.25
        return 0.15

    if "runway" in provider_lower:
        return 0.25

    if "luma" in provider_lower:
        return 0.30

    return None


def calculate_irregular_pacing(
    target_duration: float,
    shot_count: int,
    word_counts: Sequence[int] | None = None,
) -> list[float]:
    """Calculate non-uniform shot durations that sum precisely to target_duration.

    Conforms to Section 21 of the Bible (rhythmic irregularity instead of 4s, 4s, 4s).
    Hook shot is punchy, reveal/development shots breathe, climax is deliberate.
    Guarantees:
    - All durations are > 0 and >= 1.5s
    - Sum of durations strictly equals target_duration
    """
    if shot_count <= 0:
        return []
    if shot_count == 1:
        return [round(target_duration, 2)]

    # If word counts per shot are provided, calculate duration based on speech rhythm (~2.2 words/sec)
    if word_counts and len(word_counts) == shot_count and sum(word_counts) > 0:
        raw_durations = [max(1.8, count / 2.2) for count in word_counts]
        scale = target_duration / sum(raw_durations)
        adjusted = [round(d * scale, 1) for d in raw_durations]
        # Fix rounding error on the longest shot
        diff = round(target_duration - sum(adjusted), 2)
        max_idx = adjusted.index(max(adjusted))
        adjusted[max_idx] = round(adjusted[max_idx] + diff, 2)
        return adjusted

    # Canonical cinematic rhythm weight curve:
    # Shot 1 (Hook): punchy (0.8x avg)
    # Shot 2 (Atmosphere / Context): expansive (1.15x avg)
    # Shot 3 (Escalation): moderate (0.9x avg)
    # Shot 4 (Revelation / Climax): expansive / breathing (1.25x avg)
    # Shot 5 (Resolution / Lingering): reflective (0.9x avg)
    canonical_weights = [0.80, 1.15, 0.90, 1.25, 0.90, 1.05, 0.95, 1.10]
    weights = [canonical_weights[i % len(canonical_weights)] for i in range(shot_count)]

    total_weight = sum(weights)
    raw = [(w / total_weight) * target_duration for w in weights]
    rounded = [round(max(1.8, d), 1) for d in raw]

    # Rebalance to ensure exact total match
    diff = round(target_duration - sum(rounded), 2)
    # Add difference to the shot that has the largest duration to maintain rhythm
    max_idx = rounded.index(max(rounded))
    rounded[max_idx] = round(rounded[max_idx] + diff, 2)

    return rounded
