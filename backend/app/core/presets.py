"""
Arya OS — Creator Presets.

Defines standardized, production-grade creator presets for video generation.
Presets provide opinionated defaults for style, duration, aspect ratio,
audio, and music settings for different video formats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CreatorPreset:
    """Standardized preset configuration for creator workflows."""

    name: str
    description: str
    format: str  # "short" or "landscape"
    aspect_ratio: str  # "9:16" or "16:9"
    duration: int  # Target duration in seconds
    style: str  # Visual and narrative style prompt
    platform: str = "youtube"
    language: str = "en"
    music_enabled: bool = True
    music_volume: float = 0.20
    music_ducking_volume: float = 0.06
    music_style: str = "ambient cinematic instrumental"
    music_mood: str = "mysterious, awe-inspiring, deep contemplation"
    music_provider: Optional[str] = None
    music_model: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_model: Optional[str] = None
    video_provider: Optional[str] = None
    video_model: Optional[str] = None
    captions_enabled: bool = False


CREATOR_PRESETS: dict[str, CreatorPreset] = {
    "documentary_short": CreatorPreset(
        name="documentary_short",
        description="High-engagement 9:16 documentary Short with cinematic macro/aerial visuals and subtle ambient music",
        format="short",
        aspect_ratio="9:16",
        duration=20,
        style="cinematic documentary, photorealistic, 8k uhd, atmospheric lighting, National Geographic style",
        platform="youtube",
        language="en",
        music_enabled=True,
        music_volume=0.20,
        music_ducking_volume=0.06,
        music_style="ambient cinematic instrumental",
        music_mood="mysterious, awe-inspiring, deep contemplation",
    ),
    "cosmic_explainer": CreatorPreset(
        name="cosmic_explainer",
        description="Fast-paced 9:16 astronomy/space explainer Short with deep space visuals and synth ambiance",
        format="short",
        aspect_ratio="9:16",
        duration=20,
        style="cinematic astrophotography, NASA Hubble/James Webb style, hyper-detailed, volumetric cosmic dust, 8k uhd",
        platform="youtube",
        language="en",
        music_enabled=True,
        music_volume=0.22,
        music_ducking_volume=0.06,
        music_style="deep space ambient synth instrumental",
        music_mood="cosmic, profound, majestic",
    ),
    "deep_sea_wonders": CreatorPreset(
        name="deep_sea_wonders",
        description="9:16 oceanic wonder Short focusing on abyss creatures and bioluminescence",
        format="short",
        aspect_ratio="9:16",
        duration=20,
        style="cinematic deep ocean documentary, BBC Blue Planet style, bioluminescent glow, abyssal darkness, 8k uhd",
        platform="youtube",
        language="en",
        music_enabled=True,
        music_volume=0.20,
        music_ducking_volume=0.05,
        music_style="underwater ambient drone instrumental",
        music_mood="mysterious, otherworldly, tranquil",
    ),
    "landscape_documentary": CreatorPreset(
        name="landscape_documentary",
        description="Standard 16:9 widescreen documentary with cinematic pacing and orchestral accompaniment",
        format="landscape",
        aspect_ratio="16:9",
        duration=30,
        style="cinematic nature documentary, 16:9 wide aspect, 35mm film grain, 8k uhd, shallow depth of field",
        platform="youtube",
        language="en",
        music_enabled=True,
        music_volume=0.25,
        music_ducking_volume=0.08,
        music_style="cinematic orchestral instrumental",
        music_mood="epic, emotional, wondrous",
    ),
    "cinematic_story": CreatorPreset(
        name="cinematic_story",
        description="Cinematic narrative short conforming to Cinematic Production Bible with Class A/B/C planning and irregular pacing",
        format="short",
        aspect_ratio="9:16",
        duration=20,
        style="grounded cinematic realism, 35mm film texture, motivated directional lighting, human operator presence",
        platform="youtube",
        language="en",
        music_enabled=True,
        music_volume=0.18,
        music_ducking_volume=0.05,
        music_style="minimal ambient score with subtle tension",
        music_mood="grounded, suspenseful, authentic",
        voice_provider="elevenlabs",
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        voice_model="eleven_turbo_v2_5",
        video_provider="kling",
        captions_enabled=True,
    ),
}

DEFAULT_PRESET_NAME = "documentary_short"


def list_presets() -> dict[str, CreatorPreset]:
    """Return all available creator presets."""
    return dict(CREATOR_PRESETS)


def get_preset(preset_name: str | None) -> CreatorPreset:
    """Retrieve a CreatorPreset by name.

    Args:
        preset_name: Key in CREATOR_PRESETS (e.g. "documentary_short").

    Returns:
        The matched CreatorPreset.

    Raises:
        ValueError: If the preset name is not recognized.
    """
    if not preset_name or not str(preset_name).strip():
        raise ValueError(f"Preset name cannot be empty. Available presets: {sorted(CREATOR_PRESETS.keys())}")
    clean = str(preset_name).strip().lower()
    if clean not in CREATOR_PRESETS:
        raise ValueError(
            f"Unknown preset '{clean}'. Available presets: {sorted(CREATOR_PRESETS.keys())}"
        )
    return CREATOR_PRESETS[clean]
