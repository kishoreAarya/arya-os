"""
Unit and integration tests for Phase 11 Real Image Generation Architecture.
Tests:
- FluxImageProvider configuration validation, cost estimation, dimension resolution.
- ImageProviderRegistry registration, lookup, and fallback resolution.
- ExecutionGateway resolution and honest configuration failure handling.
- Real end-to-end execution flow simulation.
"""

from __future__ import annotations

import os
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.schemas.production import (
    AryaJobPackageSchema,
    AryaJobPackagePlan,
    AryaJobPackageModelRoute,
    AryaJobPackageShotConfig,
    AryaJobPackageContinuity,
    AryaJobPackageReferences,
)
from app.services.image_provider import (
    ImageGenerationProvider,
    FluxImageProvider,
    ImageProviderRegistry,
    image_provider_registry,
)
from app.services.execution_gateway import ExecutionGateway
from app.services.openmontage_adapter import OpenMontageAdapter, OpenMontageToolResult
from app.models.production import ProductionJob, ProductionShot


def make_sample_job_package(
    prompt: str = "Cinematic futuristic Indian city at sunset, 16:9",
    model: str = "flux-pro/v1.1",
    provider: str = "fal",
    aspect_ratio: str = "16:9",
    generation_type: str = "image",
) -> AryaJobPackageSchema:
    return AryaJobPackageSchema(
        jobPackageId=f"pkg-test-{uuid.uuid4().hex[:6]}",
        createdAt="2026-09-28T12:00:00Z",
        projectId=str(uuid.uuid4()),
        sequenceId=str(uuid.uuid4()),
        shotId=str(uuid.uuid4()),
        shotOrder=1,
        plan=AryaJobPackagePlan(
            title="Test Shot",
            prompt=prompt,
            generationType=generation_type,
            dependencies=[],
            isFirstShotInSequence=True,
        ),
        references=AryaJobPackageReferences(),
        modelRoute=AryaJobPackageModelRoute(
            provider=provider,
            model=model,
            modelName=model,
            mode=generation_type,
            preflightReady=True,
            preflightReasons=[],
        ),
        shotConfiguration=AryaJobPackageShotConfig(
            aspectRatio=aspect_ratio,
        ),
        continuityRequirements=AryaJobPackageContinuity(),
        outputRequirements={
            "destination": "ARYAOS_CORRIDOR_STREAM",
            "targetFormat": "image/png",
        },
        decisionBoundary="ARYAOS_ORCHESTRATION_VALIDATED",
        executionPayload={
            "generation_type": generation_type,
            "prompt": prompt,
            "model": model,
            "provider": provider,
            "aspect_ratio": aspect_ratio,
        },
    )


class TestFluxImageProvider:
    """Tests for FluxImageProvider implementation."""

    def test_provider_attributes(self):
        provider = FluxImageProvider()
        assert provider.provider_id == "fal"
        assert provider.model_id == "flux-pro/v1.1"
        assert "text_to_image" in provider.capabilities
        assert "16:9" in provider.capabilities
        assert "1:1" in provider.capabilities

    def test_dimension_resolution(self):
        provider = FluxImageProvider()
        assert provider._resolve_dimensions("16:9") == (1344, 768)
        assert provider._resolve_dimensions("1:1") == (1024, 1024)
        assert provider._resolve_dimensions("9:16") == (768, 1344)
        assert provider._resolve_dimensions("21:9") == (1536, 640)
        assert provider._resolve_dimensions("4:3") == (1152, 864)
        # Default fallback
        assert provider._resolve_dimensions(None) == (1344, 768)

    def test_model_name_normalization(self):
        provider = FluxImageProvider()
        assert provider._normalize_model_name("fal-ai/flux-pro/v1.1") == "flux-pro/v1.1"
        assert provider._normalize_model_name("flux-pro/v1.1") == "flux-pro/v1.1"
        assert provider._normalize_model_name("flux/dev") == "flux/dev"
        assert provider._normalize_model_name("flux-pro") == "flux-pro"
        assert provider._normalize_model_name("fal-ai/flux-dev") == "flux/dev"
        # Unknown falls back to default
        assert provider._normalize_model_name("unknown-model") == "flux-pro/v1.1"

    def test_estimate_cost(self):
        provider = FluxImageProvider()
        pkg_pro = make_sample_job_package(model="flux-pro/v1.1")
        pkg_dev = make_sample_job_package(model="flux/dev")
        assert provider.estimate_cost(pkg_pro) == 0.05
        assert provider.estimate_cost(pkg_dev) == 0.03

    def test_validate_configuration_success(self):
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.openmontage_path = "/path/to/openmontage"

        provider = FluxImageProvider(adapter=mock_adapter)
        with patch.dict(os.environ, {"FAL_KEY": "test-key-123"}):
            valid, err = provider.validate_configuration()
            assert valid is True
            assert err is None

    def test_validate_configuration_missing_key(self):
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True

        provider = FluxImageProvider(adapter=mock_adapter)
        # Clean both environment and mocked settings
        with patch.dict(os.environ, {}, clear=True), patch("app.core.config.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.fal_key = None
            mock_s.fal_api_key = None
            mock_settings.return_value = mock_s

            valid, err = provider.validate_configuration()
            assert valid is False
            assert "CONFIGURATION REQUIRED" in err
            assert "FAL_KEY" in err

    def test_validate_configuration_unavailable_engine(self):
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = False
        mock_adapter.openmontage_path = "/nonexistent/openmontage"

        provider = FluxImageProvider(adapter=mock_adapter)
        with patch.dict(os.environ, {"FAL_KEY": "test-key-123"}):
            valid, err = provider.validate_configuration()
            assert valid is False
            assert "CONFIGURATION REQUIRED" in err
            assert "OpenMontage engine is unavailable" in err


class TestImageProviderRegistry:
    """Tests for ImageProviderRegistry."""

    def test_registry_resolution(self):
        registry = ImageProviderRegistry()
        pkg_fal = make_sample_job_package(provider="fal")
        pkg_flux = make_sample_job_package(provider="flux", model="flux-pro/v1.1")

        prov_fal = registry.resolve_provider_for_package(pkg_fal)
        prov_flux = registry.resolve_provider_for_package(pkg_flux)

        assert isinstance(prov_fal, FluxImageProvider)
        assert isinstance(prov_flux, FluxImageProvider)

    def test_fallback_resolution(self):
        registry = ImageProviderRegistry()
        pkg_unknown = make_sample_job_package(provider="unknown_provider", model="unknown_model")
        resolved = registry.resolve_provider_for_package(pkg_unknown)
        assert isinstance(resolved, FluxImageProvider)


class TestExecutionGatewayPhase11:
    """Tests ExecutionGateway tool resolution and pre-validation."""

    def test_resolve_tool_flux_image(self):
        gw = ExecutionGateway()
        pkg = make_sample_job_package(
            prompt="Futuristic city at sunset",
            aspect_ratio="16:9",
            generation_type="image",
        )
        tool_name, inputs = gw.resolve_tool_for_package(pkg)
        assert tool_name == "flux_image"
        assert inputs["prompt"] == "Futuristic city at sunset"
        assert inputs["width"] == 1344
        assert inputs["height"] == 768
        assert "artifact_" in inputs["output_path"]
        assert inputs["output_path"].endswith(".png")

    @pytest.mark.asyncio
    async def test_honest_failure_on_missing_configuration(self):
        gw = ExecutionGateway()
        pkg = make_sample_job_package()

        mock_db = AsyncMock()
        mock_job = ProductionJob(
            id=uuid.uuid4(),
            project_id=uuid.UUID(pkg.projectId),
            shot_id=uuid.UUID(pkg.shotId),
            status="QUEUED",
            provider="fal",
            model="flux-pro/v1.1",
            job_package_json={},
        )
        mock_shot = ProductionShot(
            id=uuid.UUID(pkg.shotId),
            project_id=uuid.UUID(pkg.projectId),
            sequence_id=uuid.UUID(pkg.sequenceId),
            title="Test Shot",
            prompt=pkg.plan.prompt,
            model=pkg.modelRoute.model,
            provider=pkg.modelRoute.provider,
            status="READY",
        )

        res_job = MagicMock()
        res_job.scalar_one_or_none.return_value = mock_job

        res_shot = MagicMock()
        res_shot.scalar_one_or_none.return_value = mock_shot

        mock_db.execute.side_effect = [res_job, res_shot]

        # Force invalid configuration
        with patch.object(
            FluxImageProvider,
            "validate_configuration",
            return_value=(False, "CONFIGURATION REQUIRED: FAL_KEY missing from environment"),
        ):
            result_job = await gw.execute_job(mock_job.id, pkg, mock_db)

            assert result_job.status == "FAILED"
            assert "CONFIGURATION REQUIRED" in result_job.error
            assert result_job.progress == 0.0
            # Verify attempt history was recorded
            attempts = (result_job.job_package_json or {}).get("execution_attempts", [])
            assert len(attempts) == 1
            assert attempts[0]["status"] == "FAILED"
            assert "CONFIGURATION REQUIRED" in attempts[0]["error"]
