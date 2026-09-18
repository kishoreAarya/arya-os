"""Aspect ratio configurations and validation for Arya OS video pipeline."""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class AspectRatio(str, Enum):
    """Canonical aspect ratio values supported across the video pipeline."""

    PORTRAIT_9_16 = "9:16"
    LANDSCAPE_16_9 = "16:9"


class AspectRatioConfig(NamedTuple):
    """Specifications for a supported video aspect ratio."""

    aspect_ratio: str
    width: int
    height: int
    fal_image_size: str
    thumbnail_width: int
    thumbnail_height: int
    description: str

    @property
    def is_vertical(self) -> bool:
        return self.aspect_ratio == "9:16"

    @property
    def ratio(self) -> AspectRatio:
        return AspectRatio(self.aspect_ratio)


ASPECT_RATIO_CONFIGS: dict[str, AspectRatioConfig] = {
    "16:9": AspectRatioConfig(
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        fal_image_size="landscape_16_9",
        thumbnail_width=1280,
        thumbnail_height=720,
        description="Horizontal 16:9 landscape video (standard YouTube)",
    ),
    "9:16": AspectRatioConfig(
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fal_image_size="portrait_16_9",
        thumbnail_width=1080,
        thumbnail_height=1920,
        description="Vertical 9:16 portrait video (YouTube Shorts, TikTok, Reels)",
    ),
}

DEFAULT_ASPECT_RATIO = "16:9"
SUPPORTED_ASPECT_RATIOS = frozenset(ASPECT_RATIO_CONFIGS.keys())


def validate_aspect_ratio(aspect_ratio: str | None) -> str:
    """Validate and return canonical aspect ratio string.

    Defaults to "16:9" if omitted or empty.
    Raises ValueError for unsupported values.
    """
    if aspect_ratio is None:
        return DEFAULT_ASPECT_RATIO
    clean = str(aspect_ratio).strip()
    if not clean:
        return DEFAULT_ASPECT_RATIO
    if clean not in SUPPORTED_ASPECT_RATIOS:
        raise ValueError(
            f"Unsupported aspect_ratio '{clean}'. Supported values are: {sorted(SUPPORTED_ASPECT_RATIOS)}"
        )
    return clean


def get_aspect_ratio_config(aspect_ratio: str | None = None) -> AspectRatioConfig:
    """Retrieve the AspectRatioConfig for the given or default aspect ratio."""
    canonical = validate_aspect_ratio(aspect_ratio)
    return ASPECT_RATIO_CONFIGS[canonical]
