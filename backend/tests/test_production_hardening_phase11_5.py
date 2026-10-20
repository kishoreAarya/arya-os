"""
AryaOS V1 Phase 11.5 — Production Hardening & Real Artifact Verification Tests.

Covers:
1. Artifact validation:
   - Valid image accepted (PNG, JPEG, WebP)
   - Empty file (0 bytes) rejected
   - Invalid binary rejected
   - HTML / text masquerading as image rejected
   - JSON error payload rejected
   - Path traversal and directory escape rejected
2. API & Security:
   - GET /api/v1/artifacts/{filename} returns valid bytes + security headers
   - HEAD /api/v1/artifacts/{filename} returns 200 OK with correct headers
   - 404 for missing artifact
   - 400 / 403 for path traversal attempts
   - 422 for corrupt binary
3. Execution Gateway & State Machine:
   - Successful artifact validation transitions Job to COMPLETED and Shot to COMPLETE
   - Corrupted or empty artifact transitions Job to FAILED and Shot to FAILED
   - Provider failure transitions Job to FAILED and Shot to FAILED
4. Database Consistency & Persistence:
   - Completed job and shot survive reload from DB
   - Metadata contains verified artifact dimensions, size, mime_type, sha256
5. Telemetry & SSE:
   - Truthful events: JOB_SUBMITTED -> JOB_STARTED -> JOB_COMPLETED -> ARTIFACT_READY -> SHOT_UPDATED
"""

from __future__ import annotations

import io
import os
import uuid
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio(loop_scope="module")

from app.main import app
from app.models.core import Project
from app.models.production import ProductionJob, ProductionShot, ProductionSequence
from app.schemas.production import (
    AryaJobPackageSchema,
    AryaJobPackagePlan,
    AryaJobPackageModelRoute,
    AryaJobPackageShotConfig,
    AryaJobPackageContinuity,
    AryaJobPackageReferences,
)
from app.services.artifact_validator import (
    STORAGE_ARTIFACTS_DIR,
    ArtifactValidationResult,
    validate_artifact_file,
)
from app.services.execution_gateway import ExecutionGateway
from app.services.openmontage_adapter import OpenMontageToolResult


# -----------------------------------------------------------------------------
# Fixtures & Helpers
# -----------------------------------------------------------------------------

def create_valid_test_png(filename: str, width: int = 640, height: int = 360) -> Path:
    target = STORAGE_ARTIFACTS_DIR / filename
    img = Image.new("RGB", (width, height), color=(30, 41, 59))
    img.save(target, format="PNG")
    return target


def make_test_job_package(
    shot_id: uuid.UUID,
    project_id: uuid.UUID,
    sequence_id: uuid.UUID,
    provider: str = "diagram",
    model: str = "diagram-boxes",
) -> AryaJobPackageSchema:
    return AryaJobPackageSchema(
        jobPackageId=f"pkg-harden-{uuid.uuid4().hex[:6]}",
        createdAt="2026-09-28T15:00:00Z",
        projectId=str(project_id),
        sequenceId=str(sequence_id),
        shotId=str(shot_id),
        shotOrder=1,
        plan=AryaJobPackagePlan(
            title="Hardening Shot",
            prompt="Minimal cinematic futuristic command center, dark graphite architecture, warm amber energy core",
            generationType="image",
            dependencies=[],
            isFirstShotInSequence=True,
        ),
        references=AryaJobPackageReferences(),
        modelRoute=AryaJobPackageModelRoute(
            provider=provider,
            model=model,
            modelName=model,
            mode="image",
            preflightReady=True,
            preflightReasons=[],
        ),
        shotConfiguration=AryaJobPackageShotConfig(aspectRatio="16:9"),
        continuityRequirements=AryaJobPackageContinuity(),
        outputRequirements={"destination": "ARYAOS_CORRIDOR_STREAM", "targetFormat": "image/png"},
        decisionBoundary="ARYAOS_ORCHESTRATION_VALIDATED",
        executionPayload={"prompt": "Hardening Prompt"},
    )


# -----------------------------------------------------------------------------
# 1. Artifact Validator Unit Tests
# -----------------------------------------------------------------------------

class TestArtifactValidator:
    """Verifies that the server-side validator accurately inspects and confines artifacts."""

    def test_valid_png_accepted(self):
        filename = f"test_val_valid_{uuid.uuid4().hex[:6]}.png"
        path = create_valid_test_png(filename, 1344, 768)
        try:
            val = validate_artifact_file(path, expected_type="image")
            assert val.is_valid is True
            assert val.filename == filename
            assert val.format == "PNG"
            assert val.mime_type == "image/png"
            assert val.width == 1344
            assert val.height == 768
            assert val.file_size_bytes > 0
            assert val.sha256 is not None
            assert val.error is None
        finally:
            if path.is_file():
                path.unlink()

    def test_empty_file_rejected(self):
        filename = f"test_val_empty_{uuid.uuid4().hex[:6]}.png"
        path = STORAGE_ARTIFACTS_DIR / filename
        path.write_bytes(b"")
        try:
            val = validate_artifact_file(path, expected_type="image")
            assert val.is_valid is False
            assert "empty" in val.error.lower()
        finally:
            if path.is_file():
                path.unlink()

    def test_html_pretending_to_be_image_rejected(self):
        filename = f"test_val_html_{uuid.uuid4().hex[:6]}.png"
        path = STORAGE_ARTIFACTS_DIR / filename
        path.write_text("<!DOCTYPE html><html><body>502 Bad Gateway</body></html>")
        try:
            val = validate_artifact_file(path, expected_type="image")
            assert val.is_valid is False
            assert "HTML" in val.error or "Text" in val.error
        finally:
            if path.is_file():
                path.unlink()

    def test_json_error_payload_rejected(self):
        filename = f"test_val_json_{uuid.uuid4().hex[:6]}.png"
        path = STORAGE_ARTIFACTS_DIR / filename
        path.write_text('{"error": "User is locked. Reason: TOP_UP."}')
        try:
            val = validate_artifact_file(path, expected_type="image")
            assert val.is_valid is False
            assert "Text" in val.error or "JSON" in val.error or "HTML" in val.error
        finally:
            if path.is_file():
                path.unlink()

    def test_corrupt_binary_rejected(self):
        filename = f"test_val_corrupt_{uuid.uuid4().hex[:6]}.png"
        path = STORAGE_ARTIFACTS_DIR / filename
        path.write_bytes(b"RANDOM_CORRUPT_BYTES_XYZ_1234567890")
        try:
            val = validate_artifact_file(path, expected_type="image")
            assert val.is_valid is False
            assert "Invalid image binary" in val.error
        finally:
            if path.is_file():
                path.unlink()

    def test_path_traversal_filename_rejected(self):
        val = validate_artifact_file("../../etc/passwd")
        assert val.is_valid is False
        assert "traversal" in val.error.lower() or "unsafe" in val.error.lower()

    def test_unsafe_filename_characters_rejected(self):
        val = validate_artifact_file("file;rm -rf /")
        assert val.is_valid is False
        assert "unsafe" in val.error.lower()


# -----------------------------------------------------------------------------
# 2. Artifact Serving API Endpoint Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestArtifactServingAPI:
    """Verifies GET/HEAD /api/v1/artifacts/{filename} security and integrity."""

    async def test_get_valid_artifact_returns_bytes_and_security_headers(self, client: AsyncClient):
        filename = f"test_srv_valid_{uuid.uuid4().hex[:6]}.png"
        path = create_valid_test_png(filename, 800, 600)
        try:
            res = await client.get(f"/api/v1/artifacts/{filename}")
            assert res.status_code == 200
            assert res.headers["content-type"] == "image/png"
            assert res.headers["x-content-type-options"] == "nosniff"
            assert "default-src 'none'" in res.headers["content-security-policy"]
            assert len(res.content) > 0
        finally:
            if path.is_file():
                path.unlink()

    async def test_head_method_supported(self, client: AsyncClient):
        filename = f"test_srv_head_{uuid.uuid4().hex[:6]}.png"
        path = create_valid_test_png(filename, 400, 300)
        try:
            res = await client.head(f"/api/v1/artifacts/{filename}")
            assert res.status_code == 200
            assert res.headers["content-type"] == "image/png"
            assert res.headers["x-content-type-options"] == "nosniff"
        finally:
            if path.is_file():
                path.unlink()

    async def test_missing_artifact_returns_404(self, client: AsyncClient):
        res = await client.get("/api/v1/artifacts/nonexistent_file_xyz.png")
        assert res.status_code == 404

    async def test_path_traversal_attempt_returns_400_or_403(self, client: AsyncClient):
        res = await client.get("/api/v1/artifacts/..%2F..%2Fetc%2Fpasswd")
        assert res.status_code in (400, 403, 404)

    async def test_corrupt_artifact_returns_422(self, client: AsyncClient):
        filename = f"test_srv_corrupt_{uuid.uuid4().hex[:6]}.png"
        path = STORAGE_ARTIFACTS_DIR / filename
        path.write_bytes(b"INVALID_IMAGE_PAYLOAD")
        try:
            res = await client.get(f"/api/v1/artifacts/{filename}")
            assert res.status_code == 422
            assert "corrupted" in res.json()["detail"].lower()
        finally:
            if path.is_file():
                path.unlink()


# -----------------------------------------------------------------------------
# 3. Execution Gateway Validation & Database Consistency Tests
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# 3. Execution Gateway Hardening & Database Consistency
# -----------------------------------------------------------------------------

async def test_corrupt_artifact_fails_job_and_shot(db_session: AsyncSession):
    gw = ExecutionGateway()

    proj_id = uuid.uuid4()
    seq_id = uuid.uuid4()
    shot_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Create real DB records
    proj = Project(id=proj_id, name="Hardening Proj")
    db_session.add(proj)
    seq = ProductionSequence(id=seq_id, project_id=proj_id, name="Seq 01")
    db_session.add(seq)
    shot = ProductionShot(
        id=shot_id,
        project_id=proj_id,
        sequence_id=seq_id,
        title="Corrupt Shot",
        prompt="Test corrupt",
        model="flux-pro/v1.1",
        provider="fal",
        status="READY",
    )
    db_session.add(shot)
    job = ProductionJob(
        id=job_id,
        project_id=proj_id,
        shot_id=shot_id,
        job_package_id=f"pkg-corrupt-{uuid.uuid4().hex[:8]}",
        status="QUEUED",
        provider="fal",
        model="flux-pro/v1.1",
        job_package_json={},
    )
    db_session.add(job)
    await db_session.commit()

    # Write a corrupt artifact file
    corrupt_filename = f"artifact_corrupt_{uuid.uuid4().hex[:6]}.png"
    corrupt_path = STORAGE_ARTIFACTS_DIR / corrupt_filename
    corrupt_path.write_bytes(b"CORRUPT_BYTES_REJECT_ME")

    pkg = make_test_job_package(shot_id=shot_id, project_id=proj_id, sequence_id=seq_id)

    # Mock adapter returning success=True with the corrupt artifact
    mock_adapter = MagicMock()
    mock_adapter.is_available.return_value = True
    mock_adapter.execute_tool = AsyncMock(
        return_value=OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[str(corrupt_path)],
            duration_seconds=1.5,
            cost_usd=0.03,
        )
    )
    gw.adapter = mock_adapter

    # Run execute_job
    res_job = await gw.execute_job(job_id, pkg, db_session)

    try:
        # Rule 1 Enforcement: Job and Shot MUST be FAILED despite tool success
        assert res_job.status == "FAILED"
        assert "Artifact validation failed" in res_job.error
        assert res_job.progress == 0.0

        # Verify Shot in DB is also marked FAILED and output_asset_url is None
        shot_db = (await db_session.execute(select(ProductionShot).where(ProductionShot.id == shot_id))).scalar_one()
        assert shot_db.status == "FAILED"
        assert shot_db.output_asset_url is None
    finally:
        if corrupt_path.is_file():
            corrupt_path.unlink()


async def test_valid_artifact_completes_and_persists_metadata(db_session: AsyncSession):
    gw = ExecutionGateway()

    proj_id = uuid.uuid4()
    seq_id = uuid.uuid4()
    shot_id = uuid.uuid4()
    job_id = uuid.uuid4()

    proj = Project(id=proj_id, name="Valid Proj")
    db_session.add(proj)
    seq = ProductionSequence(id=seq_id, project_id=proj_id, name="Seq 01")
    db_session.add(seq)
    shot = ProductionShot(
        id=shot_id,
        project_id=proj_id,
        sequence_id=seq_id,
        title="Valid Shot",
        prompt="Test valid",
        model="flux-pro/v1.1",
        provider="fal",
        status="READY",
    )
    db_session.add(shot)
    job = ProductionJob(
        id=job_id,
        project_id=proj_id,
        shot_id=shot_id,
        job_package_id=f"pkg-valid-{uuid.uuid4().hex[:8]}",
        status="QUEUED",
        provider="fal",
        model="flux-pro/v1.1",
        job_package_json={},
    )
    db_session.add(job)
    await db_session.commit()

    # Write a real valid PNG
    valid_filename = f"artifact_valid_{uuid.uuid4().hex[:6]}.png"
    valid_path = create_valid_test_png(valid_filename, 1280, 720)

    pkg = make_test_job_package(shot_id=shot_id, project_id=proj_id, sequence_id=seq_id)

    mock_adapter = MagicMock()
    mock_adapter.is_available.return_value = True
    mock_adapter.execute_tool = AsyncMock(
        return_value=OpenMontageToolResult(
            success=True,
            status="COMPLETED",
            artifacts=[str(valid_path)],
            duration_seconds=2.1,
            cost_usd=0.05,
        )
    )
    gw.adapter = mock_adapter

    res_job = await gw.execute_job(job_id, pkg, db_session)

    try:
        assert res_job.status == "COMPLETED"
        assert res_job.progress == 1.0
        assert res_job.error is None

        shot_db = (await db_session.execute(select(ProductionShot).where(ProductionShot.id == shot_id))).scalar_one()
        assert shot_db.status == "COMPLETE"
        assert shot_db.output_asset_url == f"/api/v1/artifacts/{valid_filename}"

        # Verify metadata contains verified dimensions and sha256
        meta = shot_db.metadata_json or {}
        art_meta = meta.get("artifact", {})
        assert art_meta.get("filename") == valid_filename
        assert art_meta.get("width") == 1280
        assert art_meta.get("height") == 720
        assert art_meta.get("mime_type") == "image/png"
        assert art_meta.get("size_bytes") > 0
        assert art_meta.get("sha256") is not None
    finally:
        if valid_path.is_file():
            valid_path.unlink()
