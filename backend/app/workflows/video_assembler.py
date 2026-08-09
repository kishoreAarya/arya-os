"""VideoAssembler — assembles multiple generated shot videos into one
final publishable video using FFmpeg.

P0 FIX: Now merges per-shot voice audio with each video clip before
concatenation, so the final output has voiceover narration.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

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
    FFmpeg. Each shot's video is merged with its voice audio before
    concatenation.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def assemble(self, summary: ShotExecutionSummary) -> VideoAssemblyResult:
        """Concatenate shot videos into one final video with voiceover."""
        if summary is None:
            logger.warning("video_assembler_empty_summary")
            return VideoAssemblyResult(
                success=False,
                error="ShotExecutionSummary is None",
            )

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_clips_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # P0 FIX: Build pairs of (video_path, voice_path) per shot
            shot_media: list[tuple[str, str | None]] = []

            for r in summary.results:
                if not r.video_path:
                    continue
                shot_media.append((r.video_path, r.voice_path))

            logger.info(
                "video_assembler_input",
                clip_count=len(shot_media),
                shots_with_voice=sum(1 for _, v in shot_media if v),
            )

            if not shot_media:
                logger.warning("video_assembler_no_clips")
                return VideoAssemblyResult(
                    success=False,
                    error="No valid video clips found in ShotExecutionSummary",
                )

            # Download all videos and voices to local temp
            local_shots: list[tuple[str, str | None]] = []
            for video_url, voice_url in shot_media:
                local_video = await self._resolve_local_path(video_url, tmp_dir, ".mp4")
                if not local_video:
                    continue
                local_voice = None
                if voice_url:
                    local_voice = await self._resolve_local_path(voice_url, tmp_dir, ".wav")
                local_shots.append((local_video, local_voice))

            if not local_shots:
                return VideoAssemblyResult(
                    success=False,
                    error="No video clips could be downloaded",
                )

            # Merge voice with each video clip
            merged_clips: list[str] = []
            for i, (video_path, voice_path) in enumerate(local_shots):
                if voice_path:
                    merged = await self._merge_audio_video(video_path, voice_path, tmp_dir, i)
                    if merged:
                        merged_clips.append(merged)
                    else:
                        merged_clips.append(video_path)
                else:
                    merged_clips.append(video_path)

            clip_count = len(merged_clips)

            if clip_count == 1:
                source_path = merged_clips[0]
                duration = await self._probe_duration(source_path)
                if duration is None:
                    duration = summary.total_duration

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

            return await self._concatenate(merged_clips, summary)

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

    async def _merge_audio_video(
        self,
        video_path: str,
        audio_path: str,
        tmp_dir: Path,
        index: int,
    ) -> str | None:
        """Merge a video clip with its voice audio using FFmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.error("ffmpeg_not_found_for_audio_merge")
            return None

        output_path = tmp_dir / f"merged_shot_{index}_{uuid.uuid4().hex}.mp4"

        try:
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
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
                    "ffmpeg_audio_merge_failed",
                    returncode=proc.returncode,
                    stderr=proc.stderr[:1000],
                    video=video_path,
                    audio=audio_path,
                )
                return None

            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("ffmpeg_audio_merge_empty_output")
                return None

            logger.info(
                "ffmpeg_audio_merge_succeeded",
                output=str(output_path),
                video=video_path,
                audio=audio_path,
            )
            return str(output_path)

        except Exception as exc:
            logger.exception("audio_merge_unexpected_error", error=str(exc))
            return None

    async def _concatenate(
        self,
        video_paths: list[str],
        summary: ShotExecutionSummary,
    ) -> VideoAssemblyResult:
        """Run FFmpeg concat with re-encoding to fix audio gaps."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.error("ffmpeg_not_found")
            return VideoAssemblyResult(
                success=False,
                error="FFmpeg not found in PATH",
            )

        # FIX: Remove duplicate clips
        unique_paths = list(dict.fromkeys(video_paths))
        if len(unique_paths) != len(video_paths):
            logger.warning(
                "duplicate_clips_removed",
                original_count=len(video_paths),
                unique_count=len(unique_paths),
            )
            video_paths = unique_paths

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

            # FIX: Re-encode instead of -c copy to fix audio stream boundaries
            cmd = [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-af", "aresample=async=1:first_pts=0",
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
        media_path: str,
        tmp_dir: Path,
        suffix: str = ".mp4",
    ) -> str | None:
        """Return a local filesystem path."""
        if not media_path:
            return None

        if not media_path.startswith(("http://", "https://")):
            return media_path if os.path.exists(media_path) else None

        try:
            local_path = tmp_dir / f"{uuid.uuid4().hex}{suffix}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(media_path)
                response.raise_for_status()

            local_path.write_bytes(response.content)

            logger.info(
                "media_downloaded",
                remote_url=media_path,
                local_path=str(local_path),
                size_bytes=local_path.stat().st_size,
            )

            return str(local_path)

        except Exception as exc:
            logger.warning(
                "media_download_failed",
                url=media_path,
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
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
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