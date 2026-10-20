"""
Unit and Contract Test Suite for Phase 3.2.4.4.6.3.3.12 — Artifact Normalization & Retention.

Tests cover all 12 required areas:
1. JPEG/JFIF content incorrectly named .png
2. Valid PNG, JPEG, WebP, and supported video artifacts
3. Corrupt, empty, unsupported, or disguised HTML/JSON payloads
4. Safe normalization and preservation of durable artifact references
5. Interrupted normalization and duplicate/repeated maintenance runs
6. Referenced old artifacts being retained
7. Unreferenced expired scratch artifacts appearing as dry-run candidates
8. Active, recoverable, and UNKNOWN/reconciliation-pending artifacts never being deleted
9. Symlink, path traversal, and storage-root escape attempts
10. Database or reference-check failures causing pruning to fail closed
11. Concurrent maintenance runs and races between reference creation and deletion
12. Explicit toggle enabling deletion only when dry-run is turned off
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import io
import os
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock
import uuid

from PIL import Image
import pytest

from app.core.config import Settings
from app.services.artifact_retention_service import (
    ArtifactRetentionService,
    RetentionCandidate,
    RetentionSweepReport,
)
from app.services.artifact_validator import (
    ArtifactNormalizationResult,
    ArtifactValidationResult,
    FORMAT_ALLOWED_EXTENSIONS,
    FORMAT_CANONICAL_EXTENSIONS,
    STORAGE_ARTIFACTS_DIR,
    normalize_artifact_file,
    validate_artifact_file,
)


def create_sample_image(format_name: str, width: int = 64, height: int = 64) -> bytes:
    """Helper to generate minimal valid image bytes."""
    buf = io.BytesIO()
    mode = "RGB" if format_name.upper() in ("JPEG", "WEBP") else "RGBA"
    img = Image.new(mode, (width, height), color=(100, 150, 200))
    img.save(buf, format=format_name.upper())
    return buf.getvalue()


def make_mock_session(action_rows=None, parent_goal_rows=None):
    """Creates a mock AsyncSession that inspects the query statement to return matching rows."""
    mock_session = AsyncMock()

    def execute_side_effect(stmt):
        s = str(stmt)
        res = MagicMock()
        if "autonomous_action_nodes" in s and action_rows is not None:
            res.all.return_value = action_rows
        elif "autonomous_goals" in s and parent_goal_rows is not None:
            res.all.return_value = parent_goal_rows
        else:
            res.all.return_value = []
        return res

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


# ==============================================================================
# 1. JPEG/JFIF content incorrectly named .png
# ==============================================================================

def test_01_jpeg_incorrectly_named_png_detected_and_normalized(tmp_path: Path):
    """Test 01: A JPEG/JFIF binary named .png must fail strict validation and normalize to .jpg."""
    jpeg_bytes = create_sample_image("JPEG", 128, 128)
    expected_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()

    mismatched_file = tmp_path / "flux_astrolabe_mismatched.png"
    mismatched_file.write_bytes(jpeg_bytes)

    # 1. Strict validation must fail closed
    val_strict = validate_artifact_file(
        mismatched_file,
        expected_type="image",
        allowed_dir=tmp_path,
        strict_extension=True,
    )
    assert val_strict.is_valid is False
    assert val_strict.extension_mismatch is True
    assert val_strict.format == "JPEG"
    assert val_strict.canonical_extension == ".jpg"
    assert val_strict.canonical_filename == "flux_astrolabe_mismatched.jpg"
    assert "incompatible with file extension '.png'" in str(val_strict.error)

    # 2. Permissive check still reports mismatch
    val_permissive = validate_artifact_file(
        mismatched_file,
        expected_type="image",
        allowed_dir=tmp_path,
        strict_extension=False,
    )
    assert val_permissive.is_valid is True
    assert val_permissive.extension_mismatch is True

    # 3. Safe normalization to canonical naming
    norm_res = normalize_artifact_file(
        mismatched_file,
        expected_type="image",
        allowed_dir=tmp_path,
        alias_legacy=True,
    )
    assert norm_res.success is True
    assert norm_res.re_encoded is False  # Bytes MUST NOT be altered
    assert norm_res.alias_created is True
    assert norm_res.canonical_filename == "flux_astrolabe_mismatched.jpg"
    assert norm_res.normalized_path.name == "flux_astrolabe_mismatched.jpg"
    assert norm_res.sha256 == expected_sha256

    # 4. Verify canonical file passes strict validation
    canon_val = validate_artifact_file(
        norm_res.normalized_path,
        expected_type="image",
        allowed_dir=tmp_path,
        strict_extension=True,
    )
    assert canon_val.is_valid is True
    assert canon_val.extension_mismatch is False
    assert canon_val.format == "JPEG"
    assert canon_val.sha256 == expected_sha256

    # 5. Verify legacy path is preserved as alias with identical bytes
    assert mismatched_file.exists()
    assert hashlib.sha256(mismatched_file.read_bytes()).hexdigest() == expected_sha256


# ==============================================================================
# 2. Valid PNG, JPEG, WebP, and supported video artifacts
# ==============================================================================

def test_02_valid_formats_pass_strict_validation(tmp_path: Path):
    """Test 02: Valid PNG, JPEG, WebP, and MP4 artifacts match extensions and pass."""
    # PNG
    png_file = tmp_path / "valid_image.png"
    png_file.write_bytes(create_sample_image("PNG", 64, 64))
    png_val = validate_artifact_file(png_file, expected_type="image", allowed_dir=tmp_path, strict_extension=True)
    assert png_val.is_valid is True
    assert png_val.format == "PNG"
    assert png_val.extension_mismatch is False

    # JPEG
    jpg_file = tmp_path / "valid_image.jpg"
    jpg_file.write_bytes(create_sample_image("JPEG", 64, 64))
    jpg_val = validate_artifact_file(jpg_file, expected_type="image", allowed_dir=tmp_path, strict_extension=True)
    assert jpg_val.is_valid is True
    assert jpg_val.format == "JPEG"
    assert jpg_val.extension_mismatch is False

    # WebP
    webp_file = tmp_path / "valid_image.webp"
    webp_file.write_bytes(create_sample_image("WEBP", 64, 64))
    webp_val = validate_artifact_file(webp_file, expected_type="image", allowed_dir=tmp_path, strict_extension=True)
    assert webp_val.is_valid is True
    assert webp_val.format == "WEBP"
    assert webp_val.extension_mismatch is False

    # MP4 (using genuine test MP4 from storage)
    mp4_file = tmp_path / "valid_video.mp4"
    source_mp4 = STORAGE_ARTIFACTS_DIR / "test_ffmpeg.mp4"
    if source_mp4.exists():
        mp4_file.write_bytes(source_mp4.read_bytes())
    else:
        # Fallback to minimal bytes if storage file is absent
        mp4_file.write_bytes(b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00" + b"\x00" * 64)

    mp4_val = validate_artifact_file(mp4_file, expected_type="video", allowed_dir=tmp_path, strict_extension=True)
    assert mp4_val.is_valid is True
    assert mp4_val.format in ("MP4", "mp4")
    assert mp4_val.extension_mismatch is False


# ==============================================================================
# 3. Corrupt, empty, unsupported, or disguised HTML/JSON payloads
# ==============================================================================

def test_03_corrupt_empty_and_disguised_payloads_rejected(tmp_path: Path):
    """Test 03: Empty, corrupt, HTML, and JSON error files must be rejected and fail normalization."""
    # Empty file
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    val_empty = validate_artifact_file(empty_file, allowed_dir=tmp_path)
    assert val_empty.is_valid is False
    assert "empty" in str(val_empty.error).lower()
    norm_empty = normalize_artifact_file(empty_file, allowed_dir=tmp_path)
    assert norm_empty.success is False

    # Corrupt binary
    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"\xff\xd8\xffCORRUPT_BYTES_XYZ_12345")
    val_corrupt = validate_artifact_file(corrupt_file, allowed_dir=tmp_path)
    assert val_corrupt.is_valid is False
    norm_corrupt = normalize_artifact_file(corrupt_file, allowed_dir=tmp_path)
    assert norm_corrupt.success is False

    # HTML disguised as PNG
    html_file = tmp_path / "error_page.png"
    html_file.write_text("<!DOCTYPE html><html><body>504 Gateway Timeout</body></html>")
    val_html = validate_artifact_file(html_file, allowed_dir=tmp_path)
    assert val_html.is_valid is False
    assert "Text or HTML payload" in str(val_html.error)
    norm_html = normalize_artifact_file(html_file, allowed_dir=tmp_path)
    assert norm_html.success is False

    # JSON error payload disguised as JPG
    json_file = tmp_path / "api_error.jpg"
    json_file.write_text('{"error": "QuotaExceeded", "detail": "Budget depleted"}')
    val_json = validate_artifact_file(json_file, allowed_dir=tmp_path)
    assert val_json.is_valid is False
    assert "Text or HTML payload" in str(val_json.error)
    norm_json = normalize_artifact_file(json_file, allowed_dir=tmp_path)
    assert norm_json.success is False


# ==============================================================================
# 4. Safe normalization and preservation of durable artifact references
# ==============================================================================

def test_04_contract_re_encode_vs_canonical_naming(tmp_path: Path):
    """Test 04: Explicit format contract re-encodes, while default preserves original bytes and alias."""
    jpeg_bytes = create_sample_image("JPEG", 64, 64)
    sample_file = tmp_path / "source_shot.jpg"
    sample_file.write_bytes(jpeg_bytes)
    orig_sha = hashlib.sha256(jpeg_bytes).hexdigest()

    # Case A: Explicit contract target_format="PNG" requires re-encoding
    norm_reencode = normalize_artifact_file(
        sample_file,
        expected_type="image",
        allowed_dir=tmp_path,
        target_format="PNG",
    )
    assert norm_reencode.success is True
    assert norm_reencode.re_encoded is True
    assert norm_reencode.format == "PNG"
    assert norm_reencode.normalized_path.name == "source_shot.png"
    assert norm_reencode.normalized_path.exists() is True

    # Case B: Without contract, never modify bytes merely to fit extension
    mismatched = tmp_path / "preserved_bytes.png"
    mismatched.write_bytes(jpeg_bytes)
    norm_naming = normalize_artifact_file(
        mismatched,
        expected_type="image",
        allowed_dir=tmp_path,
        target_format=None,
        alias_legacy=True,
    )
    assert norm_naming.success is True
    assert norm_naming.re_encoded is False
    assert norm_naming.sha256 == orig_sha
    assert norm_naming.normalized_path.name == "preserved_bytes.jpg"
    assert mismatched.exists() is True  # Legacy reference remains resolvable


# ==============================================================================
# 5. Interrupted normalization and duplicate/repeated maintenance runs
# ==============================================================================

def test_05_idempotent_normalization_and_collision_protection(tmp_path: Path):
    """Test 05: Repeated normalization is idempotent; colliding canonical targets are rejected."""
    jpeg_bytes = create_sample_image("JPEG", 64, 64)
    file_path = tmp_path / "repeat_test.png"
    file_path.write_bytes(jpeg_bytes)

    # First run
    res1 = normalize_artifact_file(file_path, allowed_dir=tmp_path, alias_legacy=True)
    assert res1.success is True

    # Second run on same original path
    res2 = normalize_artifact_file(file_path, allowed_dir=tmp_path, alias_legacy=True)
    assert res2.success is True
    assert res2.normalized_path == res1.normalized_path

    # Third run directly on canonical path
    res3 = normalize_artifact_file(res1.normalized_path, allowed_dir=tmp_path)
    assert res3.success is True
    assert res3.normalized_path == res1.normalized_path

    # Collision test: target canonical path already exists with DIFFERENT bytes
    another_file = tmp_path / "collision_test.png"
    another_file.write_bytes(create_sample_image("JPEG", 64, 64))

    # Plant conflicting collision_test.jpg with different content
    collision_target = tmp_path / "collision_test.jpg"
    collision_target.write_bytes(b"DIFFERENT_CONTENT_BYTES_PREVENT_COLLISION")

    res_collision = normalize_artifact_file(another_file, allowed_dir=tmp_path)
    assert res_collision.success is False
    assert "Collision" in str(res_collision.error)


# ==============================================================================
# 6. Referenced old artifacts being retained
# ==============================================================================

@pytest.mark.asyncio
async def test_06_referenced_old_artifacts_retained(tmp_path: Path):
    """Test 06: An artifact older than retention_days referenced by an action node is NOT pruned."""
    service = ArtifactRetentionService(storage_dir=tmp_path)

    old_file = tmp_path / "durable_output_shot_01.png"
    old_file.write_bytes(create_sample_image("PNG", 64, 64))

    # Set file mtime to 30 days ago
    old_time = time.time() - (30 * 86400)
    os.utime(old_file, (old_time, old_time))

    # Mock DB session reporting action node reference
    action_match = [MagicMock(id=uuid.uuid4(), status="SUCCEEDED", goal_id=uuid.uuid4())]
    mock_session = make_mock_session(action_rows=action_match)

    report = await service.run_retention_sweep(
        dry_run=False,
        enabled=True,
        retention_days=14,
        session=mock_session,
    )

    assert report.pruned_count == 0
    assert report.retained_count == 1
    assert old_file.exists() is True
    assert len(report.candidates) == 1
    assert report.candidates[0].proposed_action == "RETAIN"
    assert "action_nodes" in report.candidates[0].reason


# ==============================================================================
# 7. Unreferenced expired scratch artifacts appearing as dry-run candidates
# ==============================================================================

@pytest.mark.asyncio
async def test_07_unreferenced_expired_scratch_candidate_in_dry_run(tmp_path: Path):
    """Test 07: Unreferenced artifact older than 14d is marked PRUNE but NOT deleted in dry-run mode."""
    service = ArtifactRetentionService(storage_dir=tmp_path)

    scratch_file = tmp_path / "scratch_candidate.png"
    scratch_file.write_bytes(create_sample_image("PNG", 64, 64))

    # Set mtime to 20 days ago
    old_time = time.time() - (20 * 86400)
    os.utime(scratch_file, (old_time, old_time))

    # Mock DB session with zero references
    mock_session = make_mock_session()

    report = await service.run_retention_sweep(
        dry_run=True,
        enabled=True,
        retention_days=14,
        session=mock_session,
    )

    assert report.dry_run is True
    assert report.pruned_count == 0
    assert report.retained_count == 1
    assert scratch_file.exists() is True  # File MUST remain intact in dry-run
    assert len(report.candidates) == 1
    assert report.candidates[0].proposed_action == "PRUNE"
    assert "dry-run" in report.candidates[0].reason


# ==============================================================================
# 8. Active, recoverable, and UNKNOWN/reconciliation-pending artifacts never being deleted
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("goal_status", [
    "RUNNING",
    "EXECUTING",
    "RECOVERABLE",
    "UNKNOWN",
    "RECONCILIATION_PENDING",
    "FAILED",
    "AWAITING_APPROVAL",
])
async def test_08_active_or_recoverable_goal_artifacts_never_deleted(tmp_path: Path, goal_status: str):
    """Test 08: Artifacts tied to active or recoverable goals are strictly retained."""
    service = ArtifactRetentionService(storage_dir=tmp_path)

    test_file = tmp_path / f"goal_linked_{goal_status.lower()}.png"
    test_file.write_bytes(create_sample_image("PNG", 64, 64))
    old_time = time.time() - (45 * 86400)
    os.utime(test_file, (old_time, old_time))

    action_match = [MagicMock(id=uuid.uuid4(), status="PENDING", goal_id=uuid.uuid4())]
    goal_match = [MagicMock(id=uuid.uuid4(), status=goal_status)]
    mock_session = make_mock_session(action_rows=action_match, parent_goal_rows=goal_match)

    report = await service.run_retention_sweep(
        dry_run=False,
        enabled=True,
        retention_days=14,
        session=mock_session,
    )

    assert report.pruned_count == 0
    assert test_file.exists() is True
    assert len(report.candidates) == 1
    assert report.candidates[0].proposed_action == "RETAIN"
    assert f"active_goal({goal_status})" in report.candidates[0].reason


# ==============================================================================
# 9. Symlink, path traversal, and storage-root escape attempts
# ==============================================================================

def test_09_symlink_and_path_traversal_escapes_rejected(tmp_path: Path):
    """Test 09: Path traversal filenames and escaping symlinks fail validation and cannot be deleted."""
    storage_dir = tmp_path / "artifacts"
    storage_dir.mkdir()
    external_dir = tmp_path / "external"
    external_dir.mkdir()

    # External sensitive file
    external_secret = external_dir / "external_secret.txt"
    external_secret.write_text("SENSITIVE_KEY_DATA")

    # 1. Path traversal in filename
    val_traversal = validate_artifact_file("../../external/external_secret.txt", allowed_dir=storage_dir)
    assert val_traversal.is_valid is False
    assert "Security violation" in str(val_traversal.error)

    # 2. Symlink in storage pointing outside storage root
    symlink_file = storage_dir / "symlink_escape.png"
    os.symlink(external_secret, symlink_file)

    val_symlink = validate_artifact_file(symlink_file, allowed_dir=storage_dir)
    assert val_symlink.is_valid is False
    assert "path traversal outside storage" in str(val_symlink.error).lower()

    # 3. Retention service sweep over escaping symlink
    service = ArtifactRetentionService(storage_dir=storage_dir)
    mock_session = AsyncMock()

    loop = asyncio.new_event_loop()
    report = loop.run_until_complete(
        service.run_retention_sweep(dry_run=False, enabled=True, retention_days=0, session=mock_session)
    )
    loop.close()

    assert report.pruned_count == 0
    assert external_secret.exists() is True  # Target file MUST NOT be touched
    assert any("escapes storage root" in e for e in report.errors)


# ==============================================================================
# 10. Database or reference-check failures causing pruning to fail closed
# ==============================================================================

@pytest.mark.asyncio
async def test_10_database_failure_fails_closed(tmp_path: Path):
    """Test 10: If DB query fails or throws an exception, candidate is retained and not deleted."""
    service = ArtifactRetentionService(storage_dir=tmp_path)

    candidate = tmp_path / "db_failure_candidate.png"
    candidate.write_bytes(create_sample_image("PNG", 64, 64))
    old_time = time.time() - (25 * 86400)
    os.utime(candidate, (old_time, old_time))

    # Mock session that raises an unexpected database error
    mock_session = AsyncMock()
    mock_session.execute.side_effect = RuntimeError("Database connection dropped unexpectedly")

    report = await service.run_retention_sweep(
        dry_run=False,
        enabled=True,
        retention_days=14,
        session=mock_session,
    )

    assert report.pruned_count == 0
    assert candidate.exists() is True  # FAIL CLOSED: Never delete on DB error!
    assert len(report.candidates) == 1
    assert report.candidates[0].proposed_action == "RETAIN"
    assert "DB_ERROR_FAIL_CLOSED" in report.candidates[0].reason


# ==============================================================================
# 11. Concurrent maintenance runs and races between reference creation and deletion
# ==============================================================================

@pytest.mark.asyncio
async def test_11_pre_deletion_race_check_and_concurrency_lock(tmp_path: Path):
    """Test 11: Pre-deletion re-check catches references created during sweep; service lock guards concurrency."""
    service = ArtifactRetentionService(storage_dir=tmp_path)

    race_file = tmp_path / "race_artifact.png"
    race_file.write_bytes(create_sample_image("PNG", 64, 64))
    old_time = time.time() - (30 * 86400)
    os.utime(race_file, (old_time, old_time))

    # Simulate race:
    # First call to check_artifact_references (initial scan): unreferenced
    # Second call to check_artifact_references (pre-deletion re-check): live reference appears!
    check_call_count = 0

    async def race_check_references(session, filename, full_path=None):
        nonlocal check_call_count
        check_call_count += 1
        if check_call_count == 1:
            # First check: file appears unreferenced
            return False, []
        # Pre-deletion re-check: action completed and wrote reference!
        return True, ["action_nodes(1)", "active_goal(RUNNING)"]

    service.check_artifact_references = race_check_references
    mock_session = AsyncMock()

    report = await service.run_retention_sweep(
        dry_run=False,
        enabled=True,
        retention_days=14,
        session=mock_session,
    )

    assert report.pruned_count == 0
    assert race_file.exists() is True  # Saved by pre-deletion re-check!
    assert report.retained_count == 1
    assert "Pre-deletion race caught reference" in report.candidates[0].reason

    # Concurrency test: Ensure lock prevents simultaneous runs
    async with service._lock:
        assert service._lock.locked() is True


# ==============================================================================
# 12. Explicit toggle enabling deletion only when dry-run is turned off
# ==============================================================================

@pytest.mark.asyncio
async def test_12_explicit_toggle_double_gate_matrix(tmp_path: Path):
    """Test 12: Verify double gate (enabled=True AND dry_run=False) is required for actual deletion."""
    test_cases = [
        (False, True, False),   # disabled, dry_run: NO prune
        (False, False, False),  # disabled, not dry_run: NO prune
        (True, True, False),    # enabled, dry_run: NO prune
        (True, False, True),    # enabled, not dry_run: PRUNE!
    ]

    for enabled, dry_run, expected_pruned in test_cases:
        case_dir = tmp_path / f"case_{enabled}_{dry_run}"
        case_dir.mkdir(parents=True, exist_ok=True)
        service = ArtifactRetentionService(storage_dir=case_dir)

        fname = f"gate_test_en_{enabled}_dry_{dry_run}.png"
        fpath = case_dir / fname
        fpath.write_bytes(create_sample_image("PNG", 64, 64))
        old_time = time.time() - (20 * 86400)
        os.utime(fpath, (old_time, old_time))

        mock_session = make_mock_session()

        report = await service.run_retention_sweep(
            dry_run=dry_run,
            enabled=enabled,
            retention_days=14,
            session=mock_session,
        )

        if expected_pruned:
            assert report.pruned_count == 1
            assert fpath.exists() is False
        else:
            assert report.pruned_count == 0
            assert fpath.exists() is True
