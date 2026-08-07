"""
Provider Capability Registry.

Beginner note: this is a plain data table, same philosophy as
agents/registry.py — a dict, not a plugin-loader. It answers one
question: "which providers CAN do X, and in what priority order should
I try them?" It does NOT call anything (that's providers/router.py's
job) and does NOT hold API clients (that's each provider adapter's
job, added under app/providers/<name>.py as they're wired in Sprint 3+).

To add a provider: add one ProviderCapability entry below. Nothing
else needs to change — the router, the fallback chain, and any future
/providers health endpoint all read from this one table.
"""
from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    TEXT_GENERATION = "text_generation"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    TTS = "tts"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    GPU_EXECUTION = "gpu_execution"


@dataclass(frozen=True)
class ProviderCapability:
    name: str                              # matches Provider.name in the DB
    capabilities: tuple[Capability, ...]
    cost_tier: int                         # 1 = cheapest, 5 = most expensive (relative, not $)
    avg_latency_seconds: float             # rough expectation, used for timeout defaults
    max_context_tokens: int | None = None  # None where not applicable (image/video/gpu providers)
    supported_models: tuple[str, ...] = field(default_factory=tuple)
    capability_models: dict[Capability, tuple[str, ...]] = field(default_factory=dict)
    secret_name: str | None = None         # field name on Settings, resolved via SecretsManager


    def get_model(self, capability: Capability) -> str | None:
        if capability in self.capability_models and self.capability_models[capability]:
            return self.capability_models[capability][0]

        if self.supported_models:
            return self.supported_models[0]

        return None

# --- Registry -----------------------------------------------------------
# Ordering within a capability list (see `providers_for`) determines the
# default fallback priority: first entry = primary, then secondary, etc.
PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "openrouter": ProviderCapability(
        name="openrouter",
        capabilities=(Capability.TEXT_GENERATION,),
        cost_tier=2,
        avg_latency_seconds=8,
        max_context_tokens=128_000,
        supported_models=("deepseek/deepseek-chat", "moonshotai/kimi-k2"),
        secret_name="openrouter_api_key",
    ),
    "gemini": ProviderCapability(
        name="gemini",
        capabilities=(Capability.TEXT_GENERATION, Capability.VISION, Capability.EMBEDDINGS),
        cost_tier=1,
        avg_latency_seconds=6,
        max_context_tokens=1_000_000,
        supported_models=("gemini-3.1-flash-lite", "gemini-3-flash-preview","gemini-3.1-pro-preview","gemini-3.5-flash","gemini-3.5-flash","gemini-3.6-flash"),
        secret_name="gemini_api_key",
    ),
    "anthropic": ProviderCapability(
        name="anthropic",
        capabilities=(Capability.TEXT_GENERATION, Capability.VISION),
        cost_tier=3,
        avg_latency_seconds=7,
        max_context_tokens=200_000,
        supported_models=("claude-sonnet-4-6",),
        secret_name="anthropic_api_key",
    ),
    "openai": ProviderCapability(
        name="openai",
        capabilities=(Capability.TEXT_GENERATION, Capability.VISION, Capability.TTS, Capability.EMBEDDINGS),
        cost_tier=3,
        avg_latency_seconds=6,
        max_context_tokens=128_000,
        secret_name="openai_api_key",
    ),
   "fal": ProviderCapability(
        name="fal",
        capabilities=(Capability.IMAGE_GENERATION, Capability.VIDEO_GENERATION),
        cost_tier=2,
        avg_latency_seconds=45,
        supported_models=("flux-dev", "ltx-video"),
        capability_models={
            Capability.IMAGE_GENERATION: ("flux-dev",),
            Capability.VIDEO_GENERATION: ("ltx-video",),
        },
        secret_name="fal_api_key",
    ),
    "comfyui": ProviderCapability(
        name="comfyui",
        capabilities=(Capability.IMAGE_GENERATION, Capability.VIDEO_GENERATION),
        cost_tier=1,  # self-hosted on RunPod — compute cost only, no per-call fee
        avg_latency_seconds=60,
        secret_name=None,  # self-hosted, reached over the RunPod tunnel URL, not a key
    ),
    "runpod": ProviderCapability(
        name="runpod",
        capabilities=(Capability.GPU_EXECUTION,),
        cost_tier=2,
        avg_latency_seconds=0,  # not a generation call itself; GPU rental
        secret_name="runpod_api_key",
    ),
    "replicate": ProviderCapability(
        name="replicate",
        capabilities=(
            Capability.TTS,
        ),
        cost_tier=3,
        avg_latency_seconds=40,
        supported_models=(
            "jaaari/kokoro-82m:f559560eb822dc509045f3921a1921234918b91739db4bf3daab2169b71c7a13",
        ),
        secret_name="replicate_api_key",
    ),
}


def providers_for(capability: Capability) -> list[ProviderCapability]:
    """Every provider that can do X, cheapest-first (used as the
    default fallback order unless a caller passes its own priority)."""
    matches = [p for p in PROVIDER_CAPABILITIES.values() if capability in p.capabilities]
    return sorted(matches, key=lambda p: p.cost_tier)


def get_capability(provider_name: str) -> ProviderCapability | None:
    return PROVIDER_CAPABILITIES.get(provider_name)
