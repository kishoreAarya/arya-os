"""
AryaOS V1 Phase 13 — Controlled Frame Extraction Service.

Extracts, validates, caches, and catalogs binary visual frame anchors
from completed video and image artifacts.

Architectural Rule:
- AryaOS decides WHAT anchors are required and WHEN to extract them.
- Media processing utilizes OpenMontage frame_sampler / FFmpeg without simulating or mocking frames.
- Every frame must be validated via validate_artifact_file:
  non-zero size, valid image format (PNG), correct magic bytes, SHA-256 checksum.
- Caches frames to avoid repeated extraction.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.schemas.production import FrameAnchorInfo
from app.services.artifact_validator import validate_artifact_file
from app.services.openmontage_adapter import openmontage_adapter, OpenMontageAdapter

logger = get_logger("arya.services.frame_extractor")

STORAGE_ARTIFACTS_DIR = (Path(__file__).resolve().parents[2] / "storage" / "artifacts").resolve()
STORAGE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


class FrameExtractor:
    """Manages real frame extraction and caching for video and image artifacts."""

    def __init__(self, adapter: OpenMontageAdapter | None = None) -> None:
        self.adapter = adapter or openmontage_adapter

    async def extract_video_anchors(
        self,
        video_path: Path | str,
        shot_id: str,
        duration: float | None = None,
        force_reextract: bool = False,
    ) -> dict[str, FrameAnchorInfo]:
        """Extracts first-frame and last-frame anchors from a validated video artifact.

        Returns:
            {"first_frame": FrameAnchorInfo, "last_frame": FrameAnchorInfo}
        """
        video_file = Path(video_path).resolve()
        if not video_file.is_file():
            raise FileNotFoundError(f"Video artifact not found: {video_file}")

        # Probe duration if not provided
        if duration is None or duration <= 0:
            duration = self._probe_duration(video_file)
            if duration <= 0:
                duration = 1.0  # Safe minimum fallback for single-frame videos

        first_frame_path = STORAGE_ARTIFACTS_DIR / f"frame_{shot_id}_first.png"
        last_frame_path = STORAGE_ARTIFACTS_DIR / f"frame_{shot_id}_last.png"

        # Check existing cache
        first_frame_cached = (
            not force_reextract
            and first_frame_path.is_file()
            and validate_artifact_file(first_frame_path, expected_type="image").is_valid
        )
        last_frame_cached = (
            not force_reextract
            and last_frame_path.is_file()
            and validate_artifact_file(last_frame_path, expected_type="image").is_valid
        )

        timestamps_to_extract = []
        target_paths = {}

        if not first_frame_cached:
            timestamps_to_extract.append(0.0)
            target_paths[0.0] = first_frame_path

        last_timestamp = max(0.0, round(duration - 0.04, 3))
        if not last_frame_cached:
            timestamps_to_extract.append(last_timestamp)
            target_paths[last_timestamp] = last_frame_path

        if timestamps_to_extract:
            await self._run_extraction(video_file, timestamps_to_extract, target_paths)

        # Validate extracted files
        anchors: dict[str, FrameAnchorInfo] = {}

        # 1. First Frame Anchor
        first_val = validate_artifact_file(first_frame_path, expected_type="image")
        if not first_val.is_valid:
            raise RuntimeError(f"First frame extraction failed validation: {first_val.error}")
        anchors["first_frame"] = FrameAnchorInfo(
            anchor_type="first_frame",
            file_path=str(first_frame_path),
            artifact_url=f"/api/v1/artifacts/{first_frame_path.name}",
            timestamp=0.0,
            width=first_val.width or 1280,
            height=first_val.height or 720,
            mime_type=first_val.mime_type or "image/png",
            sha256=first_val.sha256 or "",
            status="VERIFIED",
        )

        # 2. Last Frame Anchor
        last_val = validate_artifact_file(last_frame_path, expected_type="image")
        if not last_val.is_valid:
            raise RuntimeError(f"Last frame extraction failed validation: {last_val.error}")
        anchors["last_frame"] = FrameAnchorInfo(
            anchor_type="last_frame",
            file_path=str(last_frame_path),
            artifact_url=f"/api/v1/artifacts/{last_frame_path.name}",
            timestamp=last_timestamp,
            width=last_val.width or 1280,
            height=last_val.height or 720,
            mime_type=last_val.mime_type or "image/png",
            sha256=last_val.sha256 or "",
            status="VERIFIED",
        )

        logger.info(
            "frame_extraction_anchors_ready",
            shot_id=shot_id,
            first_frame_sha=anchors["first_frame"].sha256[:10],
            last_frame_sha=anchors["last_frame"].sha256[:10],
        )
        return anchors

    async def extract_image_anchor(
        self,
        image_path: Path | str,
        shot_id: str,
    ) -> dict[str, FrameAnchorInfo]:
        """Catalogs an image artifact as both first_frame and last_frame visual anchor."""
        img_file = Path(image_path).resolve()
        if not img_file.is_file():
            raise FileNotFoundError(f"Image artifact not found: {img_file}")

        val = validate_artifact_file(img_file, expected_type="image")
        if not val.is_valid:
            raise RuntimeError(f"Image artifact failed validation: {val.error}")

        anchor = FrameAnchorInfo(
            anchor_type="keyframe",
            file_path=str(img_file),
            artifact_url=f"/api/v1/artifacts/{img_file.name}",
            timestamp=0.0,
            width=val.width or 1200,
            height=val.height or 800,
            mime_type=val.mime_type or "image/png",
            sha256=val.sha256 or "",
            status="VERIFIED",
        )
        return {"first_frame": anchor, "last_frame": anchor}

    async def _run_extraction(
        self,
        video_file: Path,
        timestamps: list[float],
        target_paths: dict[float, Path],
    ) -> None:
        """Executes frame extraction via OpenMontage frame_sampler with direct FFmpeg fallback."""
        temp_dir = STORAGE_ARTIFACTS_DIR / f"_tmp_{os.getpid()}_{video_file.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Attempt extraction via OpenMontage frame_sampler tool
            tool_inputs = {
                "input_path": str(video_file),
                "strategy": "timestamps",
                "timestamps": timestamps,
                "format": "png",
                "quality": 2,
                "output_dir": str(temp_dir),
            }

            result = await self.adapter.execute_tool(
                tool_name="frame_sampler",
                inputs=tool_inputs,
                timeout_seconds=30.0,
            )

            # Check if OpenMontage produced frames
            extracted_frames = []
            if result.success and result.data and "frames" in result.data:
                extracted_frames = result.data["frames"]

            if extracted_frames:
                for idx, frame_info in enumerate(extracted_frames):
                    src = Path(frame_info["path"])
                    ts = timestamps[idx] if idx < len(timestamps) else 0.0
                    dst = target_paths.get(ts)
                    if dst and src.is_file():
                        shutil.copy2(src, dst)
            else:
                # Direct FFmpeg fallback (preserves zero fake output without depending on adapter)
                logger.info("falling_back_to_direct_ffmpeg_frame_extraction", video=str(video_file))
                ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
                for ts, dst in target_paths.items():
                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-ss",
                        str(ts),
                        "-i",
                        str(video_file),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        str(dst),
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()

        finally:
            # Clean up temp dir
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _probe_duration(self, video_file: Path) -> float:
        """Probes video duration via ffprobe."""
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        try:
            out = subprocess.check_output(
                [
                    ffprobe_bin,
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(video_file),
                ],
                text=True,
                timeout=5.0,
            )
            return float(out.strip() or "0")
        except Exception as e:
            logger.warning("duration_probe_failed", error=str(e), file=str(video_file))
            return 0.0


frame_extractor = FrameExtractor()
