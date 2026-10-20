"""
AryaOS V1 Phase 11.5 — Lightweight Server-Side Artifact Validation Layer.

Enforces strict security, format, dimension, and binary integrity on all
production artifacts before they can be marked COMPLETED or served to clients.

Rejects:
- HTML or error pages masquerading as media
- JSON error payloads saved with media extensions
- Empty files (0 bytes) or corrupted binary data
- Path traversal attempts, symlink escapes, or unsafe filenames
- Unsupported media types or zero-dimension images
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

from app.core.logging import get_logger

logger = get_logger("arya.execution.artifact_validator")

# Permitted storage directory for artifacts
STORAGE_ARTIFACTS_DIR = (Path(__file__).resolve().parents[2] / "storage" / "artifacts").resolve()
STORAGE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Safe filename regex: strictly alphanumeric, underscores, hyphens, and periods
SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

# Format canonical and allowed extensions mapping (MED-03)
FORMAT_CANONICAL_EXTENSIONS: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "MP4": ".mp4",
    "WEBM": ".webm",
}

FORMAT_ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    "JPEG": {".jpg", ".jpeg", ".jfif"},
    "PNG": {".png"},
    "WEBP": {".webp"},
    "MP4": {".mp4", ".m4v"},
    "WEBM": {".webm"},
}

# Known Magic Byte Signatures
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_WEBP_RIFF = b"RIFF"
MAGIC_WEBP_TAG = b"WEBP"
MAGIC_MP4_FTYP = b"ftyp"

# Text signatures to aggressively reject
REJECT_TEXT_SIGNATURES = [
    b"<!DOCTYPE",
    b"<html",
    b"<?xml",
    b'{"error"',
    b'{"detail"',
    b'{"message"',
    b'{"status"',
    b"Error 404",
    b"Error 403",
    b"Error 500",
]

MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB


@dataclass
class ArtifactValidationResult:
    """Detailed result contract from artifact validation."""

    is_valid: bool
    file_path: Path | None = None
    filename: str | None = None
    file_size_bytes: int = 0
    mime_type: str = "application/octet-stream"
    format: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    sha256: str | None = None
    error: str | None = None
    extension_mismatch: bool = False
    canonical_extension: str | None = None
    canonical_filename: str | None = None
    canonical_path: Path | None = None


@dataclass
class ArtifactNormalizationResult:
    """Detailed contract for artifact normalization outcomes."""

    success: bool
    original_path: Path
    normalized_path: Path | None = None
    canonical_filename: str | None = None
    sha256: str | None = None
    format: str | None = None
    re_encoded: bool = False
    alias_created: bool = False
    error: str | None = None
    validation_result: ArtifactValidationResult | None = None


def validate_artifact_file(
    file_path: str | Path,
    expected_type: Literal["image", "video", "any"] = "image",
    allowed_dir: Path | None = None,
    strict_extension: bool = True,
) -> ArtifactValidationResult:
    """Validates an artifact file on disk for integrity, dimensions, signature, and safety.

    Args:
        file_path: Path to the target artifact file.
        expected_type: 'image', 'video', or 'any'.
        allowed_dir: Directory the artifact MUST reside in (defaults to STORAGE_ARTIFACTS_DIR).
        strict_extension: If True, rejects artifacts whose extension does not match binary format.

    Returns:
        ArtifactValidationResult with verified dimensions, format, MIME, and safety state.
    """
    target_dir = allowed_dir or STORAGE_ARTIFACTS_DIR
    raw_path = Path(file_path)

    # 1. Filename safety validation
    filename = raw_path.name
    if not SAFE_FILENAME_REGEX.match(filename) or ".." in filename or "/" in filename or "\\" in filename:
        return ArtifactValidationResult(
            is_valid=False,
            filename=filename,
            error=f"Security violation: Unsafe artifact filename '{filename}'",
        )

    # 2. Path Traversal & Directory Confinement (resolve symlinks)
    try:
        resolved_path = raw_path.resolve()
        resolved_dir = target_dir.resolve()
        if not str(resolved_path).startswith(str(resolved_dir)):
            return ArtifactValidationResult(
                is_valid=False,
                filename=filename,
                error=f"Security violation: Artifact path traversal outside storage directory",
            )
    except Exception as exc:
        return ArtifactValidationResult(
            is_valid=False,
            filename=filename,
            error=f"Path resolution error: {exc}",
        )

    # 3. File existence and type check
    if not resolved_path.is_file():
        return ArtifactValidationResult(
            is_valid=False,
            file_path=resolved_path,
            filename=filename,
            error=f"Artifact file not found: {filename}",
        )

    # 4. File size check (> 0 bytes and <= maximum limit)
    try:
        size = resolved_path.stat().st_size
    except OSError as exc:
        return ArtifactValidationResult(
            is_valid=False,
            file_path=resolved_path,
            filename=filename,
            error=f"Failed to inspect file size: {exc}",
        )

    if size == 0:
        return ArtifactValidationResult(
            is_valid=False,
            file_path=resolved_path,
            filename=filename,
            file_size_bytes=0,
            error="Artifact validation failed: File is empty (0 bytes)",
        )

    max_allowed = MAX_VIDEO_SIZE_BYTES if expected_type == "video" else MAX_IMAGE_SIZE_BYTES
    if size > max_allowed:
        return ArtifactValidationResult(
            is_valid=False,
            file_path=resolved_path,
            filename=filename,
            file_size_bytes=size,
            error=f"Artifact exceeds maximum permitted size of {max_allowed} bytes",
        )

    # 5. Header / Magic Bytes Inspection
    try:
        with open(resolved_path, "rb") as f:
            header = f.read(512)
    except Exception as exc:
        return ArtifactValidationResult(
            is_valid=False,
            file_path=resolved_path,
            filename=filename,
            file_size_bytes=size,
            error=f"Failed to read file header: {exc}",
        )

    # Reject text / HTML masquerading as binary media
    for text_sig in REJECT_TEXT_SIGNATURES:
        if text_sig in header:
            return ArtifactValidationResult(
                is_valid=False,
                file_path=resolved_path,
                filename=filename,
                file_size_bytes=size,
                error="Artifact validation failed: Text or HTML payload detected inside media file",
            )

    # 6. Deep Content Validation by Type
    if expected_type in ("image", "any"):
        is_png = header.startswith(MAGIC_PNG)
        is_jpeg = header.startswith(MAGIC_JPEG)
        is_webp = header.startswith(MAGIC_WEBP_RIFF) and MAGIC_WEBP_TAG in header[:16]

        if is_png or is_jpeg or is_webp or expected_type == "image":
            # Verify via Pillow
            try:
                with Image.open(resolved_path) as im:
                    fmt = (im.format or "").upper()
                    if fmt not in ("PNG", "JPEG", "WEBP"):
                        return ArtifactValidationResult(
                            is_valid=False,
                            file_path=resolved_path,
                            filename=filename,
                            file_size_bytes=size,
                            format=fmt,
                            error=f"Unsupported image format '{fmt}'. Allowed: PNG, JPEG, WEBP",
                        )

                    w, h = im.size
                    if w <= 0 or h <= 0:
                        return ArtifactValidationResult(
                            is_valid=False,
                            file_path=resolved_path,
                            filename=filename,
                            file_size_bytes=size,
                            format=fmt,
                            width=w,
                            height=h,
                            error=f"Invalid image dimensions: {w}x{h}",
                        )

                    # Verify image integrity
                    im.verify()

                # Determine MIME type
                mime = "image/png" if fmt == "PNG" else "image/jpeg" if fmt == "JPEG" else "image/webp"

                # Calculate SHA256 checksum
                sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()

                # Check file extension against verified format (MED-03)
                file_ext = raw_path.suffix.lower()
                allowed_exts = FORMAT_ALLOWED_EXTENSIONS.get(fmt, set())
                canonical_ext = FORMAT_CANONICAL_EXTENSIONS.get(fmt)
                is_ext_mismatch = file_ext not in allowed_exts
                canonical_name = f"{raw_path.stem}{canonical_ext}" if (canonical_ext and is_ext_mismatch) else filename
                canonical_p = resolved_path.parent / canonical_name

                if is_ext_mismatch and strict_extension:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        mime_type=mime,
                        format=fmt,
                        width=w,
                        height=h,
                        sha256=sha256,
                        extension_mismatch=True,
                        canonical_extension=canonical_ext,
                        canonical_filename=canonical_name,
                        canonical_path=canonical_p,
                        error=f"Artifact extension mismatch: binary format '{fmt}' is incompatible with file extension '{file_ext}' (canonical: '{canonical_ext}')",
                    )

                return ArtifactValidationResult(
                    is_valid=True,
                    file_path=resolved_path,
                    filename=filename,
                    file_size_bytes=size,
                    mime_type=mime,
                    format=fmt,
                    width=w,
                    height=h,
                    sha256=sha256,
                    extension_mismatch=is_ext_mismatch,
                    canonical_extension=canonical_ext,
                    canonical_filename=canonical_name,
                    canonical_path=canonical_p,
                    error=None,
                )

            except Exception as exc:
                if expected_type == "image":
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        error=f"Invalid image binary: {exc}",
                    )

    if expected_type in ("video", "any"):
        is_mp4 = MAGIC_MP4_FTYP in header[:32]
        is_webm = header.startswith(b"\x1a\x45\xdf\xa3")

        if is_mp4 or is_webm or expected_type == "video":
            import json
            import shutil
            import subprocess

            ffprobe_bin = shutil.which("ffprobe")
            if not ffprobe_bin:
                if not is_mp4 and not is_webm:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        error="Invalid video container: Missing valid MP4/WebM magic bytes",
                    )
                sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
                fmt = "MP4" if is_mp4 else "WEBM"
                file_ext = raw_path.suffix.lower()
                allowed_exts = FORMAT_ALLOWED_EXTENSIONS.get(fmt, set())
                canonical_ext = FORMAT_CANONICAL_EXTENSIONS.get(fmt)
                is_ext_mismatch = file_ext not in allowed_exts
                canonical_name = f"{raw_path.stem}{canonical_ext}" if (canonical_ext and is_ext_mismatch) else filename
                canonical_p = resolved_path.parent / canonical_name

                if is_ext_mismatch and strict_extension:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        mime_type="video/mp4" if is_mp4 else "video/webm",
                        format=fmt,
                        container="mp4" if is_mp4 else "webm",
                        sha256=sha256,
                        extension_mismatch=True,
                        canonical_extension=canonical_ext,
                        canonical_filename=canonical_name,
                        canonical_path=canonical_p,
                        error=f"Artifact extension mismatch: video format '{fmt}' is incompatible with file extension '{file_ext}' (canonical: '{canonical_ext}')",
                    )

                return ArtifactValidationResult(
                    is_valid=True,
                    file_path=resolved_path,
                    filename=filename,
                    file_size_bytes=size,
                    mime_type="video/mp4" if is_mp4 else "video/webm",
                    format=fmt,
                    container="mp4" if is_mp4 else "webm",
                    sha256=sha256,
                    extension_mismatch=is_ext_mismatch,
                    canonical_extension=canonical_ext,
                    canonical_filename=canonical_name,
                    canonical_path=canonical_p,
                    error=None,
                )

            # Deep inspection with ffprobe
            try:
                proc = subprocess.run(
                    [
                        ffprobe_bin,
                        "-v", "error",
                        "-print_format", "json",
                        "-show_format",
                        "-show_streams",
                        str(resolved_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode != 0:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        error=f"Corrupt video container: ffprobe inspection failed with code {proc.returncode}",
                    )

                probe_data = json.loads(proc.stdout)
                fmt_info = probe_data.get("format", {})
                duration = float(fmt_info.get("duration", 0.0) or 0.0)
                container = fmt_info.get("format_name", "mp4").split(",")[0]

                video_stream = None
                audio_stream = None
                for stream in probe_data.get("streams", []):
                    if stream.get("codec_type") == "video" and not video_stream:
                        video_stream = stream
                    elif stream.get("codec_type") == "audio" and not audio_stream:
                        audio_stream = stream

                if not video_stream:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        error="Invalid video container: No video stream found",
                    )

                v_width = int(video_stream.get("width", 0))
                v_height = int(video_stream.get("height", 0))
                v_codec = video_stream.get("codec_name", "")

                # Calculate FPS from r_frame_rate e.g. "25/1"
                v_fps = None
                r_fps = video_stream.get("r_frame_rate", "")
                if "/" in r_fps:
                    num, den = r_fps.split("/", 1)
                    try:
                        v_fps = round(float(num) / float(den), 2) if float(den) > 0 else None
                    except Exception:
                        pass

                a_codec = audio_stream.get("codec_name") if audio_stream else None

                if v_width <= 0 or v_height <= 0:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        width=v_width,
                        height=v_height,
                        error=f"Invalid video dimensions: {v_width}x{v_height}",
                    )

                sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
                mime = "video/mp4" if ("mp4" in container or "mov" in container or is_mp4) else "video/webm"
                fmt = "MP4" if "mp4" in mime else "WEBM"
                file_ext = raw_path.suffix.lower()
                allowed_exts = FORMAT_ALLOWED_EXTENSIONS.get(fmt, set())
                canonical_ext = FORMAT_CANONICAL_EXTENSIONS.get(fmt)
                is_ext_mismatch = file_ext not in allowed_exts
                canonical_name = f"{raw_path.stem}{canonical_ext}" if (canonical_ext and is_ext_mismatch) else filename
                canonical_p = resolved_path.parent / canonical_name

                if is_ext_mismatch and strict_extension:
                    return ArtifactValidationResult(
                        is_valid=False,
                        file_path=resolved_path,
                        filename=filename,
                        file_size_bytes=size,
                        mime_type=mime,
                        format=fmt,
                        container=container,
                        width=v_width,
                        height=v_height,
                        duration=duration,
                        fps=v_fps,
                        video_codec=v_codec,
                        audio_codec=a_codec,
                        sha256=sha256,
                        extension_mismatch=True,
                        canonical_extension=canonical_ext,
                        canonical_filename=canonical_name,
                        canonical_path=canonical_p,
                        error=f"Artifact extension mismatch: video format '{fmt}' is incompatible with file extension '{file_ext}' (canonical: '{canonical_ext}')",
                    )

                return ArtifactValidationResult(
                    is_valid=True,
                    file_path=resolved_path,
                    filename=filename,
                    file_size_bytes=size,
                    mime_type=mime,
                    format=fmt,
                    container=container,
                    width=v_width,
                    height=v_height,
                    duration=duration,
                    fps=v_fps,
                    video_codec=v_codec,
                    audio_codec=a_codec,
                    sha256=sha256,
                    extension_mismatch=is_ext_mismatch,
                    canonical_extension=canonical_ext,
                    canonical_filename=canonical_name,
                    canonical_path=canonical_p,
                    error=None,
                )

            except Exception as exc:
                return ArtifactValidationResult(
                    is_valid=False,
                    file_path=resolved_path,
                    filename=filename,
                    file_size_bytes=size,
                    error=f"Video container inspection failed: {exc}",
                )

    return ArtifactValidationResult(
        is_valid=False,
        file_path=resolved_path,
        filename=filename,
        file_size_bytes=size,
        error=f"Artifact format could not be verified for expected type '{expected_type}'",
    )


def normalize_artifact_file(
    file_path: str | Path,
    expected_type: Literal["image", "video", "any"] = "any",
    allowed_dir: Path | None = None,
    target_format: str | None = None,
    alias_legacy: bool = True,
) -> ArtifactNormalizationResult:
    """Safely normalizes an artifact file to canonical naming and/or required format contract.

    Policy (Task A):
    1. Detects actual format using validated binary content (Pillow/ffprobe magic bytes).
    2. Re-encodes ONLY when explicitly required by a format contract (target_format); validates the resulting file before accepting.
    3. Never modifies artifact bytes merely to make the extension appear correct.
    4. Canonical naming creates a crash-safe link/copy to canonical extension and preserves legacy path as alias (preserving historical DB references).
    5. Preserves artifact identity, provenance, hashes, and fail-closed security.
    """
    raw_path = Path(file_path)

    # 1. First validate content with strict_extension=False to discover genuine binary format
    val = validate_artifact_file(
        raw_path,
        expected_type=expected_type,
        allowed_dir=allowed_dir,
        strict_extension=False,
    )
    if not val.is_valid:
        return ArtifactNormalizationResult(
            success=False,
            original_path=raw_path,
            error=f"Cannot normalize invalid artifact: {val.error}",
            validation_result=val,
        )

    orig_path = val.file_path or raw_path.resolve()
    detected_fmt = val.format or ""
    orig_ext = raw_path.suffix.lower()

    # 2. Re-encoding check: Re-encode ONLY when explicitly required by a format contract
    if target_format and target_format.upper() != detected_fmt.upper():
        req_fmt = target_format.upper()
        if req_fmt not in ("PNG", "JPEG", "WEBP"):
            return ArtifactNormalizationResult(
                success=False,
                original_path=orig_path,
                error=f"Unsupported target format contract '{req_fmt}'. Allowed: PNG, JPEG, WEBP",
                validation_result=val,
            )

        if val.mime_type.startswith("video/"):
            return ArtifactNormalizationResult(
                success=False,
                original_path=orig_path,
                error="Video re-encoding contract is not supported in lightweight normalization",
                validation_result=val,
            )

        target_ext = FORMAT_CANONICAL_EXTENSIONS.get(req_fmt, ".png")
        canonical_filename = f"{orig_path.stem}{target_ext}"
        canonical_path = orig_path.parent / canonical_filename
        tmp_filename = f".tmp_norm_{uuid.uuid4().hex[:8]}_{canonical_filename}"
        tmp_path = orig_path.parent / tmp_filename

        try:
            with Image.open(orig_path) as im:
                save_kwargs: dict[str, Any] = {}
                if req_fmt == "JPEG":
                    if im.mode in ("RGBA", "P"):
                        im = im.convert("RGB")
                    save_kwargs["quality"] = 95
                im.save(tmp_path, format=req_fmt, **save_kwargs)

            # Deep validation of re-encoded artifact before accepting
            re_val = validate_artifact_file(
                tmp_path,
                expected_type="image",
                allowed_dir=allowed_dir,
                strict_extension=True,
            )
            if not re_val.is_valid:
                if tmp_path.exists():
                    tmp_path.unlink()
                return ArtifactNormalizationResult(
                    success=False,
                    original_path=orig_path,
                    error=f"Re-encoded artifact failed validation: {re_val.error}",
                    validation_result=re_val,
                )

            # Atomic replace to canonical path
            os.replace(tmp_path, canonical_path)

            final_val = validate_artifact_file(
                canonical_path,
                expected_type="image",
                allowed_dir=allowed_dir,
                strict_extension=True,
            )
            return ArtifactNormalizationResult(
                success=True,
                original_path=orig_path,
                normalized_path=canonical_path,
                canonical_filename=canonical_filename,
                sha256=final_val.sha256,
                format=req_fmt,
                re_encoded=True,
                alias_created=False,
                validation_result=final_val,
            )
        except Exception as exc:
            if tmp_path.exists():
                tmp_path.unlink()
            return ArtifactNormalizationResult(
                success=False,
                original_path=orig_path,
                error=f"Re-encoding failed: {exc}",
                validation_result=val,
            )

    # 3. Canonical naming (Never modify bytes merely to fit extension!)
    canonical_ext = FORMAT_CANONICAL_EXTENSIONS.get(detected_fmt, orig_ext)
    canonical_filename = f"{orig_path.stem}{canonical_ext}"
    canonical_path = orig_path.parent / canonical_filename

    # If the file already has the canonical name, return success directly
    if orig_path.name == canonical_filename:
        final_val = validate_artifact_file(
            canonical_path,
            expected_type=expected_type,
            allowed_dir=allowed_dir,
            strict_extension=True,
        )
        return ArtifactNormalizationResult(
            success=True,
            original_path=orig_path,
            normalized_path=canonical_path,
            canonical_filename=canonical_filename,
            sha256=val.sha256,
            format=detected_fmt,
            re_encoded=False,
            alias_created=False,
            validation_result=final_val,
        )

    # Idempotent check: if canonical_path already exists, check content
    if canonical_path.exists():
        canon_sha = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        if canon_sha == val.sha256:
            # Already exists with identical content
            final_val = validate_artifact_file(
                canonical_path,
                expected_type=expected_type,
                allowed_dir=allowed_dir,
                strict_extension=True,
            )
            return ArtifactNormalizationResult(
                success=True,
                original_path=orig_path,
                normalized_path=canonical_path,
                canonical_filename=canonical_filename,
                sha256=val.sha256,
                format=detected_fmt,
                re_encoded=False,
                alias_created=alias_legacy,
                validation_result=final_val,
            )
        else:
            return ArtifactNormalizationResult(
                success=False,
                original_path=orig_path,
                error=f"Collision: canonical target file '{canonical_filename}' already exists with different content",
                validation_result=val,
            )

    # Create canonical file crash-safely
    alias_created = False
    try:
        os.link(orig_path, canonical_path)
        alias_created = True
    except OSError:
        # Fallback to atomic copy if link fails
        tmp_path = orig_path.parent / f".tmp_norm_{uuid.uuid4().hex[:8]}_{canonical_filename}"
        try:
            shutil.copy2(orig_path, tmp_path)
            os.replace(tmp_path, canonical_path)
            alias_created = True
        except Exception as copy_err:
            if tmp_path.exists():
                tmp_path.unlink()
            return ArtifactNormalizationResult(
                success=False,
                original_path=orig_path,
                error=f"Failed to create canonical file: {copy_err}",
                validation_result=val,
            )

    if not alias_legacy:
        try:
            orig_path.unlink()
            alias_created = False
        except Exception:
            pass

    final_val = validate_artifact_file(
        canonical_path,
        expected_type=expected_type,
        allowed_dir=allowed_dir,
        strict_extension=True,
    )
    return ArtifactNormalizationResult(
        success=final_val.is_valid,
        original_path=orig_path,
        normalized_path=canonical_path,
        canonical_filename=canonical_filename,
        sha256=val.sha256,
        format=detected_fmt,
        re_encoded=False,
        alias_created=alias_created,
        validation_result=final_val,
        error=final_val.error if not final_val.is_valid else None,
    )
