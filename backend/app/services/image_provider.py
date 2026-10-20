"""
AryaOS V1 Phase 11 — Real Image Generation Provider Abstraction.

Implements Phase 11A clean provider abstraction:
ImageGenerationProvider
- provider_id: str
- model_id: str
- capabilities: list[str]
- validate_configuration() -> tuple[bool, str | None]
- estimate_cost(job_package) -> float
- generate_image(job_package, output_path) -> OpenMontageToolResult

Architectural Boundary:
AryaOS decides WHAT, WHY, WHEN, WHICH provider/model.
OpenMontage decides HOW generation is executed.
The provider implementation executes through the existing OpenMontage adapter boundary.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any

from app.core.logging import get_logger
from app.schemas.production import AryaJobPackageSchema
from app.services.openmontage_adapter import (
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    openmontage_adapter,
)

logger = get_logger("arya.execution.image_provider")


class ImageGenerationProvider(ABC):
    """Abstract base class for real image generation providers in AryaOS."""

    provider_id: str
    model_id: str
    capabilities: list[str]

    @abstractmethod
    def validate_configuration(self) -> tuple[bool, str | None]:
        """Validates that credentials and tools are present in the environment.

        Returns:
            (is_valid, error_reason_if_invalid)
        """
        pass

    @abstractmethod
    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        """Estimates execution cost in USD."""
        pass

    @abstractmethod
    async def generate_image(
        self,
        pkg: AryaJobPackageSchema,
        output_path: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        """Executes real image generation via OpenMontage tool boundary."""
        pass


class FluxImageProvider(ImageGenerationProvider):
    """FLUX image generation provider via OpenMontage flux_image tool (fal.ai backend)."""

    provider_id: str = "fal"
    model_id: str = "flux-pro/v1.1"
    capabilities: list[str] = [
        "text_to_image",
        "photorealistic",
        "cinematic",
        "16:9",
        "9:16",
        "1:1",
        "21:9",
    ]

    def __init__(self, adapter: OpenMontageAdapter | None = None) -> None:
        self.adapter = adapter or openmontage_adapter

    def validate_configuration(self) -> tuple[bool, str | None]:
        # 1. Verify API Key presence
        fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
        if not fal_key:
            try:
                from app.core.config import get_settings
                s = get_settings()
                fal_key = s.fal_key or s.fal_api_key
                if fal_key:
                    os.environ["FAL_KEY"] = fal_key
            except Exception:
                pass

        if not fal_key:
            return (
                False,
                "CONFIGURATION REQUIRED: FAL_KEY or FAL_API_KEY is missing from environment. "
                "Set FAL_KEY in backend/.env to enable fal.ai / FLUX generation.",
            )

        # 2. Verify OpenMontage availability
        if not self.adapter.is_available():
            return (
                False,
                f"CONFIGURATION REQUIRED: OpenMontage engine is unavailable at {self.adapter.openmontage_path}",
            )

        return (True, None)

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        model = (pkg.modelRoute.model or "").lower()
        if "pro" in model or "1.1" in model:
            return 0.05
        return 0.03

    def _resolve_dimensions(self, aspect_ratio: str | None) -> tuple[int, int]:
        aspect = (aspect_ratio or "16:9").strip()
        if aspect == "1:1":
            return (1024, 1024)
        if aspect == "9:16":
            return (768, 1344)
        if aspect == "21:9":
            return (1536, 640)
        if aspect == "4:3":
            return (1152, 864)
        # Default 16:9
        return (1344, 768)

    def _normalize_model_name(self, raw_model: str | None) -> str:
        """Normalizes model name to OpenMontage flux_image allowed enum:

        ['flux-pro/v1.1', 'flux/dev', 'flux-pro'].
        """
        raw = (raw_model or "").lower().replace("fal-ai/", "").replace("fal/", "").strip()
        if "1.1" in raw or "flux-pro/v1.1" in raw:
            return "flux-pro/v1.1"
        if "dev" in raw:
            return "flux/dev"
        if "pro" in raw:
            return "flux-pro"
        return "flux-pro/v1.1"

    async def generate_image(
        self,
        pkg: AryaJobPackageSchema,
        output_path: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        is_valid, error_msg = self.validate_configuration()
        if not is_valid:
            logger.error("flux_image_configuration_invalid", error=error_msg)
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=error_msg,
            )

        width, height = self._resolve_dimensions(pkg.shotConfiguration.aspectRatio)
        model = self._normalize_model_name(pkg.modelRoute.model)
        prompt = pkg.plan.prompt or ""

        inputs = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "model": model,
            "output_path": output_path,
        }

        logger.info(
            "flux_image_executing",
            provider=self.provider_id,
            model=model,
            dimensions=f"{width}x{height}",
            output_path=output_path,
        )

        if execution_context is not None and hasattr(self.adapter, "execute_governed_tool"):
            return await self.adapter.execute_governed_tool(
                tool_name="flux_image",
                inputs=inputs,
                execution_context=execution_context,
                timeout_seconds=180.0,
            )

        return await self.adapter.execute_tool(
            tool_name="flux_image",
            inputs=inputs,
            timeout_seconds=180.0,
            execution_context=execution_context,
        )


class ImageProviderRegistry:
    """Registry managing available image generation providers in AryaOS."""

    def __init__(self) -> None:
        self._providers: dict[str, ImageGenerationProvider] = {}
        # Register default FLUX provider
        self.register(FluxImageProvider())

    def register(self, provider: ImageGenerationProvider) -> None:
        self._providers[provider.provider_id.lower()] = provider

    def get(self, provider_id: str) -> ImageGenerationProvider | None:
        return self._providers.get(provider_id.lower())

    def list_providers(self) -> list[ImageGenerationProvider]:
        return list(self._providers.values())

    def resolve_provider_for_package(self, pkg: AryaJobPackageSchema) -> ImageGenerationProvider:
        """Resolves the most suitable image provider for an AryaJobPackage."""
        requested_provider = (pkg.modelRoute.provider or "").lower()
        if requested_provider in self._providers:
            return self._providers[requested_provider]

        # Check if model references fal or flux
        model = (pkg.modelRoute.model or "").lower()
        if "fal" in model or "flux" in model or "fal" in self._providers:
            return self._providers["fal"]

        # Default fallback to first registered provider
        first = next(iter(self._providers.values()))
        return first


# Global shared image provider registry
image_provider_registry = ImageProviderRegistry()
