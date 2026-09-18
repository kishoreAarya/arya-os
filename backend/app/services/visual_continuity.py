"""Visual Continuity Bible and Shot-to-Shot Continuity Engine.

Provides strongly-typed schemas and methods for maintaining visual coherence:
- Character continuity (face, build, wardrobe, anchor details)
- Environment continuity (architecture, surfaces, palette, lighting anchors)
- Prop continuity (materials, distinguishing markers)
- Cinematography continuity (lens, lighting, grading, texture)
- Shot continuity risk analysis (evaluates adjacent shot transitions)
- Compact prompt injection (extracts minimal relevant anchors per shot)
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContinuityRisk(str, Enum):
    """Risk rating for visual disconnect between consecutive shots."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CharacterContinuity(BaseModel):
    """Persistent visual definition for a recurring character."""

    character_id: str = Field(description="Unique identifier, e.g. char_elena")
    name: str = Field(description="Character name")
    visual_description: str = Field(
        description="Core physical traits: face structure, age, build, ethnicity, distinctive hair/eyes"
    )
    wardrobe: str = Field(
        description="Consistent clothing, color scheme, fabric textures, wear/damage"
    )
    anchor_details: list[str] = Field(
        default_factory=list,
        description="Distinguishing anchor markers (e.g. silver signet ring on left thumb, faint scar on cheek)",
    )

    model_config = ConfigDict(extra="ignore")


class EnvironmentContinuity(BaseModel):
    """Persistent visual definition for a primary location."""

    environment_id: str = Field(description="Unique identifier, e.g. env_basement")
    name: str = Field(description="Setting name")
    architecture_style: str = Field(
        description="Architectural style, wall materials, architectural era"
    )
    key_surfaces: str = Field(
        description="Key surfaces and textures (e.g. peeling damp wallpaper, cracked concrete floor)"
    )
    color_palette: list[str] = Field(
        default_factory=list,
        description="Hex codes or color names defining the spatial palette",
    )
    lighting_anchors: list[str] = Field(
        default_factory=list,
        description="Motivated practical light sources (e.g. single 40W tungsten bulb overhead, flashlight beam)",
    )
    atmosphere: str = Field(
        default="Dust motes suspended in air, damp humid chill",
        description="Particulate, atmospheric texture, weather",
    )

    model_config = ConfigDict(extra="ignore")


class PropContinuity(BaseModel):
    """Persistent visual definition for a narrative key prop."""

    prop_id: str = Field(description="Unique identifier, e.g. prop_antique_mirror")
    name: str = Field(description="Prop name")
    description: str = Field(description="Visual description and physical dimensions")
    materials: str = Field(description="Materials, patina, distressing, reflective properties")
    visual_markers: list[str] = Field(
        default_factory=list,
        description="Specific distinguishing marks (e.g. hairline crack from top-left corner, tarnished brass filigree)",
    )

    model_config = ConfigDict(extra="ignore")


class CinematographyContinuity(BaseModel):
    """Overarching cinematic camera, optics, and lighting rules."""

    aspect_ratio: str = Field(default="9:16", description="'9:16' or '16:9'")
    primary_lens_character: str = Field(
        default="35mm anamorphic prime, sharp center with subtle optical barrel falloff",
        description="Lens family and optical characteristics",
    )
    lighting_philosophy: str = Field(
        default="Motivated single-source practical key with deep shadow roll-off and low fill",
        description="Lighting contrast, key-to-fill ratio, shadow depth",
    )
    color_grading_rules: str = Field(
        default="Muted desaturated tones, sickly emerald/cyan shadow tint, warm sodium/tungsten practical accents",
        description="Color palette, LUT character, shadow/highlight split",
    )
    texture_grain: str = Field(
        default="Subtle organic 35mm film grain, tactile physical textures",
        description="Film stock emulation, micro-contrast, organic texture",
    )

    model_config = ConfigDict(extra="ignore")


class VisualRules(BaseModel):
    """Negative and positive visual constraints."""

    prohibited_elements: list[str] = Field(
        default_factory=lambda: [
            "text", "subtitles", "captions", "watermarks", "UI elements",
            "glossy stock-photo plastic skin", "oversaturated neon", "cartoonish CGI",
            "floating disembodied limbs", "extra fingers",
        ],
        description="Elements strictly excluded from generation",
    )
    required_elements: list[str] = Field(
        default_factory=lambda: [
            "grounded physical weight", "motivated practical lighting",
            "authentic physical surface textures", "cinematic depth layering",
        ],
        description="Elements required across all visuals",
    )

    model_config = ConfigDict(extra="ignore")


class VisualContinuityBible(BaseModel):
    """Full visual continuity bible for a cinematic production."""

    title: str = Field(default="", description="Production or story title")
    genre: str = Field(default="Horror", description="Subgenre or narrative theme")
    characters: list[CharacterContinuity] = Field(default_factory=list)
    environments: list[EnvironmentContinuity] = Field(default_factory=list)
    props: list[PropContinuity] = Field(default_factory=list)
    cinematography: CinematographyContinuity = Field(default_factory=CinematographyContinuity)
    rules: VisualRules = Field(default_factory=VisualRules)

    model_config = ConfigDict(extra="ignore")


class ContinuityCheckResult(BaseModel):
    """Result of evaluating continuity risk between consecutive shots."""

    risk_level: ContinuityRisk
    score: float = Field(ge=0.0, le=10.0, description="Continuity coherence score (10.0 = flawless)")
    mismatches: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


def build_shot_continuity_context(
    bible: VisualContinuityBible | None,
    shot_plan: Any,
) -> str:
    """Build a compact, focused continuity injection for a single shot.

    Avoids prompt bloat by injecting only the anchors relevant to this shot's
    subject, environment, and cinematography.
    """
    if not bible:
        return ""

    parts: list[str] = []

    # 1. Cinematography tone (always 1 concise line)
    cin = bible.cinematography
    parts.append(
        f"Visual Tone: {cin.lighting_philosophy}. {cin.primary_lens_character}. {cin.color_grading_rules}."
    )

    # 2. Extract shot text for keyword matching
    shot_subject = str(getattr(shot_plan, "subject", "") or "")
    shot_env = str(getattr(shot_plan, "environment", "") or "")
    shot_desc = str(getattr(shot_plan, "description", "") or "")
    shot_action = str(getattr(shot_plan, "action", "") or "")
    shot_narr = str(getattr(shot_plan, "narration_segment", "") or "")
    shot_prompt = str(getattr(shot_plan, "generation_prompt", "") or "")
    combined_text = f"{shot_subject} {shot_env} {shot_desc} {shot_action} {shot_narr} {shot_prompt}".lower()

    # 3. Match relevant character anchors
    matched_chars = []
    for ch in bible.characters:
        ch_name_words = ch.name.lower().split()
        if any(w in combined_text for w in ch_name_words if len(w) > 2) or ch.character_id.lower() in combined_text:
            anchors_str = f" [Anchors: {', '.join(ch.anchor_details[:2])}]" if ch.anchor_details else ""
            matched_chars.append(f"{ch.name}: {ch.visual_description}. Wearing: {ch.wardrobe}.{anchors_str}")

    if matched_chars:
        parts.append("Character Continuity: " + " | ".join(matched_chars))
    elif bible.characters and any(term in combined_text for term in ("person", "man", "woman", "figure", "face", "protagonist")):
        # Inject primary character as default subject reference
        prim = bible.characters[0]
        anchors_str = f" [Anchors: {', '.join(prim.anchor_details[:2])}]" if prim.anchor_details else ""
        parts.append(f"Character Continuity: {prim.name}: {prim.visual_description}. Wearing: {prim.wardrobe}.{anchors_str}")

    # 4. Match relevant environment anchors
    matched_envs = []
    for env in bible.environments:
        env_words = env.name.lower().split()
        if any(w in combined_text for w in env_words if len(w) > 2) or env.environment_id.lower() in combined_text:
            lights = f" Lighting: {', '.join(env.lighting_anchors[:2])}." if env.lighting_anchors else ""
            matched_envs.append(f"{env.name} ({env.architecture_style}, {env.key_surfaces}.{lights})")

    if matched_envs:
        parts.append("Environment Anchors: " + " | ".join(matched_envs))
    elif bible.environments:
        prim_env = bible.environments[0]
        lights = f" Lighting: {', '.join(prim_env.lighting_anchors[:2])}." if prim_env.lighting_anchors else ""
        parts.append(f"Environment Anchors: {prim_env.name} ({prim_env.architecture_style}, {prim_env.key_surfaces}.{lights})")

    # 5. Match relevant prop anchors
    matched_props = []
    for prop in bible.props:
        p_words = prop.name.lower().split()
        if any(w in combined_text for w in p_words if len(w) > 2):
            markers = f" ({', '.join(prop.visual_markers[:2])})" if prop.visual_markers else ""
            matched_props.append(f"{prop.name}{markers}: {prop.materials}")

    if matched_props:
        parts.append("Prop Anchors: " + " | ".join(matched_props))

    return "\n".join(parts).strip()


def check_shot_continuity_risk(
    shot_a: Any,
    shot_b: Any,
    bible: VisualContinuityBible | None = None,
) -> ContinuityCheckResult:
    """Evaluate continuity risk between two consecutive shots.

    Checks:
    - Environment abrupt jumps (e.g. sudden daylight from night interior)
    - Lighting motivation shifts
    - Subject presence / eyeline plausibility
    - Camera axis jump (e.g. extreme whip-pan reverse without motivation)
    """
    mismatches: list[str] = []
    recommendations: list[str] = []
    penalty = 0.0

    env_a = str(getattr(shot_a, "environment", "") or "").lower()
    env_b = str(getattr(shot_b, "environment", "") or "").lower()

    light_a = str(getattr(shot_a, "lighting", "") or "").lower()
    light_b = str(getattr(shot_b, "lighting", "") or "").lower()

    subj_a = str(getattr(shot_a, "subject", "") or "").lower()
    subj_b = str(getattr(shot_b, "subject", "") or "").lower()

    # 1. Day/Night mismatch
    is_night_a = any(k in env_a or k in light_a for k in ("night", "midnight", "dark", "moon", "candle", "flashlight"))
    is_day_a = any(k in env_a or k in light_a for k in ("day", "sunlight", "morning", "afternoon", "bright sun"))

    is_night_b = any(k in env_b or k in light_b for k in ("night", "midnight", "dark", "moon", "candle", "flashlight"))
    is_day_b = any(k in env_b or k in light_b for k in ("day", "sunlight", "morning", "afternoon", "bright sun"))

    if (is_night_a and is_day_b) or (is_day_a and is_night_b):
        mismatches.append("Temporal lighting shift: sudden transition between day and night lighting.")
        recommendations.append("Align time-of-day lighting cues or insert establishing transition shot.")
        penalty += 3.5

    # 2. Complete location jump without transition note
    if env_a and env_b and env_a != env_b:
        words_a = set(re.findall(r"\w{4,}", env_a))
        words_b = set(re.findall(r"\w{4,}", env_b))
        common = words_a.intersection(words_b)
        if not common:
            # Different environments
            trans_b = str(getattr(shot_b, "transition", "") or "").lower()
            if "cut" in trans_b or not trans_b:
                mismatches.append(f"Abrupt spatial leap from '{env_a[:40]}' to '{env_b[:40]}' without bridging anchor.")
                recommendations.append("Ensure consistent architectural materials or lighting palette across locations.")
                penalty += 2.0

    # 3. Incompatible lighting temperature
    has_warm_a = any(w in light_a for w in ("warm", "tungsten", "candle", "amber", "fire"))
    has_cool_a = any(w in light_a for w in ("cool", "cyan", "moonlight", "fluorescent", "blue"))

    has_warm_b = any(w in light_b for w in ("warm", "tungsten", "candle", "amber", "fire"))
    has_cool_b = any(w in light_b for w in ("cool", "cyan", "moonlight", "fluorescent", "blue"))

    if has_warm_a and not has_cool_a and has_cool_b and not has_warm_b:
        mismatches.append("Extreme color temperature shift: warm-only illumination to cool-only illumination.")
        recommendations.append("Carry practical motivated light source into the shadow roll-off.")
        penalty += 1.5

    score = max(0.0, min(10.0, 10.0 - penalty))

    if score >= 8.0:
        risk = ContinuityRisk.LOW
    elif score >= 5.5:
        risk = ContinuityRisk.MEDIUM
    else:
        risk = ContinuityRisk.HIGH

    return ContinuityCheckResult(
        risk_level=risk,
        score=round(score, 1),
        mismatches=mismatches,
        recommendations=recommendations,
    )
