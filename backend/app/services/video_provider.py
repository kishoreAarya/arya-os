"""
AryaOS V1 Phase 12 — Real Video Generation Provider Abstraction.

Implements Phase 12A & 12B clean video provider architecture:
- VideoGenerationProvider (abstract base class)
- Explicit capability flags:
    * IMAGE_TO_VIDEO
    * TEXT_TO_VIDEO
    * FIRST_FRAME_TO_VIDEO
    * FIRST_LAST_FRAME_TO_VIDEO
    * REFERENCE_GUIDED_VIDEO
- KlingVideoProvider: Real Kling video generation through OpenMontage kling_video (fal.ai backend).
- CameraMotionVideoProvider: Real local camera motion video generation through OpenMontage camera_push_video (FFmpeg backend).
- VideoProviderRegistry: Central lookup, capability introspection, and provider resolution.

Architectural Boundary:
AryaOS decides WHAT, WHY, WHEN, WHICH provider/model.
OpenMontage decides HOW video is synthesized, encoded, and formatted.
Zero fake success. Truthful capability reporting.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.schemas.production import AryaJobPackageSchema
from app.services.openmontage_adapter import (
    GovernedExecutionContext,
    OpenMontageAdapter,
    OpenMontageToolResult,
    openmontage_adapter,
)

logger = get_logger("arya.execution.video_provider")

STORAGE_ARTIFACTS_DIR = (Path(__file__).resolve().parents[2] / "storage" / "artifacts").resolve()
STORAGE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


# Explicit capability constants
CAP_IMAGE_TO_VIDEO = "IMAGE_TO_VIDEO"
CAP_TEXT_TO_VIDEO = "TEXT_TO_VIDEO"
CAP_FIRST_FRAME_TO_VIDEO = "FIRST_FRAME_TO_VIDEO"
CAP_FIRST_LAST_FRAME_TO_VIDEO = "FIRST_LAST_FRAME_TO_VIDEO"
CAP_REFERENCE_GUIDED_VIDEO = "REFERENCE_GUIDED_VIDEO"


class VideoGenerationProvider(ABC):
    """Abstract base class for video generation providers in AryaOS."""

    provider_id: str
    model_id: str
    capabilities: list[str]

    @abstractmethod
    def validate_configuration(self) -> tuple[bool, str | None]:
        """Validates that credentials, runtimes, and tools exist.

        Returns:
            (is_valid, error_reason_if_invalid)
        """
        pass

    @abstractmethod
    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        """Estimates execution cost in USD."""
        pass

    @abstractmethod
    async def generate_video(
        self,
        pkg: AryaJobPackageSchema,
        output_path: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        """Executes real video generation via OpenMontage tool boundary."""
        pass

    def supports_capability(self, capability: str) -> bool:
        """Checks if this provider supports the requested capability."""
        return capability in self.capabilities


class KlingVideoProvider(VideoGenerationProvider):
    """Kling video provider via OpenMontage kling_video tool (fal.ai backend).

    Truthful capabilities: Supports TEXT_TO_VIDEO and FIRST_FRAME_TO_VIDEO.
    Does NOT support FIRST_LAST_FRAME_TO_VIDEO on fal standard endpoint.
    """

    provider_id: str = "kling"
    model_id: str = "kling-video/v3/standard"
    capabilities: list[str] = [
        CAP_TEXT_TO_VIDEO,
        CAP_IMAGE_TO_VIDEO,
        CAP_FIRST_FRAME_TO_VIDEO,
    ]

    def __init__(self, adapter: OpenMontageAdapter | None = None) -> None:
        self.adapter = adapter or openmontage_adapter

    def validate_configuration(self) -> tuple[bool, str | None]:
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
                "Set FAL_KEY in backend/.env to enable Kling video generation via fal.ai.",
            )

        if not self.adapter.is_available():
            return (
                False,
                f"CONFIGURATION REQUIRED: OpenMontage engine is unavailable at {self.adapter.openmontage_path}",
            )

        return (True, None)

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        duration = float(pkg.plan.durationSeconds or 5.0)
        return 0.10 * (duration / 5.0)

    async def generate_video(
        self,
        pkg: AryaJobPackageSchema,
        output_path: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        is_valid, error_msg = self.validate_configuration()
        if not is_valid:
            logger.error("kling_video_configuration_invalid", error=error_msg)
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=error_msg,
            )

        # Check last-frame conditioning requested
        last_frame = getattr(pkg.references, "lastFrame", None) or pkg.references.endFrameUrl
        if last_frame:
            # Rule: Represent requirement as unsupported rather than pretending it worked
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=(
                    "Unsupported generation mode: Kling provider on fal.ai does not support "
                    "last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO). Only first-frame conditioning is supported."
                ),
            )

        # Resolve first frame
        first_frame = (
            getattr(pkg.references, "firstFrame", None)
            or pkg.references.startFrameUrl
            or pkg.references.referenceImageUrl
        )

        mode = (pkg.modelRoute.mode or "").lower()
        if "image" in mode or first_frame:
            operation = "image_to_video"
        else:
            operation = "text_to_video"

        duration = str(int(pkg.plan.durationSeconds or 5.0))
        if duration not in ("5", "10"):
            duration = "5"

        inputs: dict[str, Any] = {
            "prompt": pkg.plan.prompt or "",
            "operation": operation,
            "duration": duration,
            "aspect_ratio": pkg.shotConfiguration.aspectRatio or "16:9",
            "output_path": output_path,
        }
        if first_frame:
            inputs["image_url"] = first_frame

        logger.info(
            "kling_video_executing",
            provider=self.provider_id,
            model=self.model_id,
            operation=operation,
            duration=duration,
            output_path=output_path,
        )

        if execution_context is not None and hasattr(self.adapter, "execute_governed_tool"):
            return await self.adapter.execute_governed_tool(
                tool_name="kling_video",
                inputs=inputs,
                execution_context=execution_context,
                timeout_seconds=300.0,
            )

        return await self.adapter.execute_tool(
            tool_name="kling_video",
            inputs=inputs,
            timeout_seconds=300.0,
            execution_context=execution_context,
        )


class CameraMotionVideoProvider(VideoGenerationProvider):
    """Camera motion video provider via OpenMontage camera_push_video tool (FFmpeg local backend).

    Produces genuine H.264 MP4 videos executing smooth cinematic camera pushes on an input image.
    100% real, local, deterministic, and verifies the full video pipeline.
    """

    provider_id: str = "camera_motion"
    model_id: str = "camera-push"
    capabilities: list[str] = [
        CAP_IMAGE_TO_VIDEO,
        CAP_FIRST_FRAME_TO_VIDEO,
    ]

    def __init__(self, adapter: OpenMontageAdapter | None = None) -> None:
        self.adapter = adapter or openmontage_adapter

    def validate_configuration(self) -> tuple[bool, str | None]:
        import shutil
        if not shutil.which("ffmpeg"):
            return (False, "CONFIGURATION REQUIRED: FFmpeg is not installed or not on PATH.")
        if not self.adapter.is_available():
            return (
                False,
                f"CONFIGURATION REQUIRED: OpenMontage engine is unavailable at {self.adapter.openmontage_path}",
            )
        return (True, None)

    def estimate_cost(self, pkg: AryaJobPackageSchema) -> float:
        return 0.0

    async def generate_video(
        self,
        pkg: AryaJobPackageSchema,
        output_path: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        is_valid, error_msg = self.validate_configuration()
        if not is_valid:
            logger.error("camera_motion_configuration_invalid", error=error_msg)
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=error_msg,
            )

        # Check last-frame conditioning requested
        last_frame = getattr(pkg.references, "lastFrame", None) or pkg.references.endFrameUrl
        if last_frame:
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=(
                    "Unsupported generation mode: Camera motion provider does not support "
                    "last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO). Only first-frame conditioning is supported."
                ),
            )

        first_frame = (
            getattr(pkg.references, "firstFrame", None)
            or pkg.references.startFrameUrl
            or pkg.references.referenceImageUrl
        )

        # If referenceAssets contains an image, use it as fallback
        if not first_frame and pkg.references.referenceAssets:
            first_frame = pkg.references.referenceAssets[0]

        if not first_frame:
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=(
                    "Missing source frame: Camera motion provider requires a valid first-frame source image "
                    "(IMAGE_TO_VIDEO / FIRST_FRAME_TO_VIDEO)."
                ),
            )

        # Resolve source frame to an absolute path on disk
        source_frame_path = str(first_frame).strip()
        if "/api/v1/artifacts/" in source_frame_path:
            filename = source_frame_path.split("/api/v1/artifacts/")[-1].split("?")[0]
            candidate = STORAGE_ARTIFACTS_DIR / filename
            if candidate.is_file():
                source_frame_path = str(candidate)
        elif not os.path.isabs(source_frame_path):
            candidate = STORAGE_ARTIFACTS_DIR / source_frame_path
            if candidate.is_file():
                source_frame_path = str(candidate)
            elif (Path.cwd() / source_frame_path).is_file():
                source_frame_path = str((Path.cwd() / source_frame_path).resolve())

        if not Path(source_frame_path).is_file():
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                error=f"Source frame '{first_frame}' does not exist on disk or cannot be resolved.",
            )

        duration = float(pkg.plan.durationSeconds or 5.0)
        fps = int(getattr(pkg.shotConfiguration, "fps", None) or 25)

        inputs = {
            "prompt": pkg.plan.prompt or "Cinematic camera push",
            "image_path": source_frame_path,
            "duration": duration,
            "fps": fps,
            "aspect_ratio": pkg.shotConfiguration.aspectRatio or "16:9",
            "output_path": output_path,
        }

        # Propagate action_id and goal_id to inputs and adapter for subprocess tracking
        action_id = (
            execution_context.action_node_id
            if execution_context
            else getattr(pkg, "executionPayload", {}).get("action_id")
            if hasattr(pkg, "executionPayload") and isinstance(pkg.executionPayload, dict)
            else None
        )
        goal_id = (
            execution_context.goal_id
            if execution_context
            else getattr(pkg, "executionPayload", {}).get("goal_id")
            if hasattr(pkg, "executionPayload") and isinstance(pkg.executionPayload, dict)
            else None
        )
        if action_id:
            inputs["action_id"] = str(action_id)
        if goal_id:
            inputs["goal_id"] = str(goal_id)

        logger.info(
            "camera_motion_executing",
            provider=self.provider_id,
            source_image=source_frame_path,
            duration=duration,
            fps=fps,
            output_path=output_path,
        )

        if hasattr(self.adapter, "execute_local_tool"):
            return await self.adapter.execute_local_tool(
                tool_name="camera_push_video",
                inputs=inputs,
                timeout_seconds=60.0,
                execution_context=execution_context,
            )
        return await self.adapter.execute_tool(
            tool_name="camera_push_video",
            inputs=inputs,
            timeout_seconds=60.0,
            execution_context=execution_context,
        )


class VideoProviderRegistry:
    """Registry managing available video generation providers in AryaOS."""

    def __init__(self) -> None:
        self._providers: dict[str, VideoGenerationProvider] = {}
        # Register real providers: Kling (fal.ai cloud) and CameraMotion (local FFmpeg)
        self.register(KlingVideoProvider())
        self.register(CameraMotionVideoProvider())

    def register(self, provider: VideoGenerationProvider) -> None:
        self._providers[provider.provider_id.lower()] = provider

    def get(self, provider_id: str) -> VideoGenerationProvider | None:
        return self._providers.get(provider_id.lower())

    def list_providers(self) -> list[VideoGenerationProvider]:
        return list(self._providers.values())

    def resolve_provider_for_package(self, pkg: AryaJobPackageSchema) -> VideoGenerationProvider:
        """Resolves the video provider for an AryaJobPackage."""
        requested_provider = (pkg.modelRoute.provider or "").lower()
        if requested_provider in self._providers:
            return self._providers[requested_provider]

        model = (pkg.modelRoute.model or "").lower()
        if "kling" in model or "fal" in requested_provider:
            return self._providers.get("kling") or next(iter(self._providers.values()))
        if "camera" in model or "push" in model or "motion" in model or "ffmpeg" in requested_provider:
            return self._providers.get("camera_motion") or next(iter(self._providers.values()))

        # Check if first-frame is supplied and model requested is camera motion
        first_frame = (
            getattr(pkg.references, "firstFrame", None)
            or pkg.references.startFrameUrl
            or pkg.references.referenceImageUrl
        )
        if first_frame and "camera_motion" in self._providers:
            # If user explicitly asks for camera push or motion
            prompt = (pkg.plan.prompt or "").lower()
            if "push" in prompt or "camera" in prompt or "motion" in prompt:
                return self._providers["camera_motion"]

        # Default to kling
        return self._providers.get("kling") or next(iter(self._providers.values()))


# Global shared video provider registry
video_provider_registry = VideoProviderRegistry()
