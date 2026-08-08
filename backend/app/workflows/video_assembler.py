"""VideoAssembler — assembles multiple generated shot videos into one
final publishable video using FFmpeg.
"""

from __future__ import annotations

import httpx
import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.workflows.shot_executor import ShotExecutionSummary

logger = get_logger("arya.workflows.video_assembler")


@dataclass
class VideoAssemblyResult:
    final_video_path: str = ""
    clip_count: int = 0
    duration_seconds: float = 0.0
    success: bool = False
    error: str | None = None


class VideoAssembler:
    """Assembles shot-level video outputs into a single deliverable via
    FFmpeg concat demuxer.  Falls back to the sole clip when only one
    video is present.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def assemble(self, summary: ShotExecutionSummary) -> VideoAssemblyResult:
        """Concatenate shot videos into one final video.

        Args:
            summary: The aggregated output of ShotExecutor.

        Returns:
            VideoAssemblyResult with the assembled clip metadata.
        """
        if summary is None:
            logger.warning("video_assembler_empty_summary")
            return VideoAssemblyResult(
                success=False,
                error="ShotExecutionSummary is None",
            )

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_clips_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            video_paths: list[str] = []

            for r in summary.results:
                if not r.video_path:
                    continue

                local_path = await self._resolve_local_path(
                    r.video_path,
                    tmp_dir,
                )

                if local_path:
                    video_paths.append(local_path)

            logger.info(
                "video_assembler_input",
                clip_count=len(video_paths),
            )

            clip_count = len(video_paths)

            if clip_count == 0:
                logger.warning("video_assembler_no_clips")
                return VideoAssemblyResult(
                    success=False,
                    error="No valid video clips found in ShotExecutionSummary",
                )

            if clip_count == 1:
                source_path = video_paths[0]
                duration = await self._probe_duration(source_path)
                if duration is None:
                    duration = summary.total_duration

                # Copy single clip to a stable location so tmp_dir cleanup
                # doesn't delete the only video we have.
                stable_name = f"arya_assembled_{uuid.uuid4().hex}.mp4"
                stable_path = Path(tempfile.gettempdir()) / stable_name
                shutil.copy2(source_path, stable_path)

                logger.info(
                    "video_assembler_single_clip",
                    source=str(source_path),
                    final=str(stable_path),
                    duration_seconds=duration,
                )

                return VideoAssemblyResult(
                    final_video_path=str(stable_path),
                    clip_count=1,
                    duration_seconds=duration,
                    success=True,
                )

            return await self._concatenate(video_paths, summary)

        finally:
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
            except Exception as exc:
                logger.warning(
                    "download_cleanup_failed",
                    path=str(tmp_dir),
                    error=str(exc),
                )
                
    async def _concatenate(
        self,
        video_paths: list[str],
        summary: ShotExecutionSummary,
    ) -> VideoAssemblyResult:
        """Run FFmpeg concat demuxer and return the output path."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.error("ffmpeg_not_found")
            return VideoAssemblyResult(
                success=False,
                error="FFmpeg not found in PATH",
            )

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_concat_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        list_path = tmp_dir / "concat_list.txt"
        output_path = tmp_dir / "output.mp4"

        try:
            with list_path.open("w", encoding="utf-8") as f:
                for path in video_paths:
                    normalized = os.path.abspath(path).replace("\\", "/")
                    escaped = normalized.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            logger.info(
                "ffmpeg_concat_started",
                clip_count=len(video_paths),
                list_path=str(list_path),
                output_path=str(output_path),
            )

            cmd = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ]

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode != 0:
                logger.error(
                    "ffmpeg_concat_failed",
                    returncode=proc.returncode,
                    stderr=proc.stderr[:2000],
                )
                return VideoAssemblyResult(
                    success=False,
                    error=f"FFmpeg concat failed (rc={proc.returncode}): {proc.stderr[:500]}",
                )

            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("ffmpeg_concat_empty_output")
                return VideoAssemblyResult(
                    success=False,
                    error="FFmpeg produced an empty output file",
                )

            stable_name = f"arya_assembled_{uuid.uuid4().hex}.mp4"
            stable_path = Path(tempfile.gettempdir()) / stable_name
            shutil.move(str(output_path), str(stable_path))

            duration = await self._probe_duration(str(stable_path))
            if duration is None:
                duration = summary.total_duration

            logger.info(
                "ffmpeg_concat_succeeded",
                final_path=str(stable_path),
                clip_count=len(video_paths),
                duration_seconds=duration,
                size_bytes=stable_path.stat().st_size,
            )

            return VideoAssemblyResult(
                final_video_path=str(stable_path),
                clip_count=len(video_paths),
                duration_seconds=duration,
                success=True,
            )

        except Exception as exc:
            logger.exception("video_assembler_unexpected_error", error=str(exc))
            return VideoAssemblyResult(
                success=False,
                error=f"Video assembly failed: {exc}",
            )
        finally:
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
            except Exception as exc:
                logger.warning("concat_cleanup_failed", path=str(tmp_dir), error=str(exc))


    async def _resolve_local_path(
        self,
        video_path: str,
        tmp_dir: Path,
    ) -> str | None:
        """Return a local filesystem path.

        Downloads remote URLs into tmp_dir.
        Leaves existing local files untouched.
        """

        if not video_path:
            return None

        # Already a local file.
        if not video_path.startswith(("http://", "https://")):
            return video_path if os.path.exists(video_path) else None

        try:
            local_path = tmp_dir / f"{uuid.uuid4().hex}.mp4"

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(video_path)
                response.raise_for_status()

            local_path.write_bytes(response.content)

            logger.info(
                "video_clip_downloaded",
                remote_url=video_path,
                local_path=str(local_path),
            )

            return str(local_path)

        except Exception as exc:
            logger.warning(
                "clip_download_failed",
                url=video_path,
                error=str(exc),
            )
            return None            

    async def _probe_duration(self, path: str) -> float | None:
        """Best-effort duration probe via ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None

        try:
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ]
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if proc.returncode == 0:
                return float(proc.stdout.strip())
        except Exception:
            pass
        return None