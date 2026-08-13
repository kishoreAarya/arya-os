"""VideoAssembler — assembles shot videos into final video using voice-first workflow.

Voice-first approach:
- Full voice track is generated first (continuous audio)
- Video clips are generated to match voice segment durations
- Assembly: concatenate video clips, overlay full voice track
- Subtitles burned from voice segment text + timing
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
    """Assembles shot-level video outputs into a single deliverable.
    Voice-first: video clips sync to pre-generated voice track.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def assemble(
        self,
        summary: ShotExecutionSummary,
        voice_path: str | None = None,
    ) -> VideoAssemblyResult:
        """Concatenate shot videos and overlay full voice track."""
        if summary is None:
            logger.warning("video_assembler_empty_summary")
            return VideoAssemblyResult(
                success=False,
                error="ShotExecutionSummary is None",
            )

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_clips_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Collect video clips (no per-shot voice merge in voice-first)
            video_clips: list[str] = []
            for r in summary.results:
                if r.video_path:
                    video_clips.append(r.video_path)

            logger.info(
                "video_assembler_input",
                clip_count=len(video_clips),
            )

            if not video_clips:
                logger.warning("video_assembler_no_clips")
                return VideoAssemblyResult(
                    success=False,
                    error="No valid video clips found",
                )

            # Download all videos to local temp
            local_videos: list[str] = []
            for video_url in video_clips:
                local_video = await self._resolve_local_path(video_url, tmp_dir, ".mp4")
                if local_video:
                    local_videos.append(local_video)

            if not local_videos:
                return VideoAssemblyResult(
                    success=False,
                    error="No video clips could be downloaded",
                )

            # Collect subtitle data from shots
            subtitle_segments: list[dict] = []
            current_time = 0.0
            for r in summary.results:
                if r.video_path and r.voice_text:
                    duration = r.duration_seconds or 4.0
                    subtitle_segments.append({
                        "start": current_time,
                        "end": current_time + duration,
                        "text": r.voice_text,
                    })
                    current_time += duration

            # Concatenate video clips
            if len(local_videos) == 1:
                concat_path = local_videos[0]
            else:
                concat_result = await self._concatenate_videos(local_videos, tmp_dir)
                if not concat_result:
                    return VideoAssemblyResult(
                        success=False,
                        error="Video concatenation failed",
                    )
                concat_path = concat_result

            # Overlay full voice track if provided
            if voice_path:
                final_path = await self._overlay_voice(concat_path, voice_path, tmp_dir)
                if not final_path:
                    final_path = concat_path
            else:
                final_path = concat_path

            # Apply fade in/out
            faded_path = await self._apply_fade_to_path(final_path)
            if faded_path:
                final_path = faded_path

            # Burn subtitles
            if subtitle_segments:
                subtitled_path = await self._burn_subtitles(final_path, subtitle_segments)
                if subtitled_path:
                    final_path = subtitled_path

            # Move to stable path (must be OUTSIDE tmp_dir before cleanup)
            stable_path = Path(tempfile.gettempdir()) / f"arya_final_{uuid.uuid4().hex}.mp4"
            shutil.copy2(final_path, stable_path)

            duration = await self._probe_duration(str(stable_path))

            logger.info(
                "video_assemble_complete",
                final_path=str(stable_path),
                clip_count=len(local_videos),
                duration_seconds=duration,
                has_voice=bool(voice_path),
                has_subtitles=bool(subtitle_segments),
            )

            return VideoAssemblyResult(
                final_video_path=str(stable_path),
                clip_count=len(local_videos),
                duration_seconds=duration or 0.0,
                success=True,
            )

        finally:
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
            except Exception as exc:
                logger.warning(
                    "assembler_cleanup_failed",
                    path=str(tmp_dir),
                    error=str(exc),
                )

    async def _concatenate_videos(
        self,
        video_paths: list[str],
        tmp_dir: Path,
    ) -> str | None:
        """Concatenate multiple video clips using FFmpeg concat demuxer."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None

        list_path = tmp_dir / "concat_list.txt"
        output_path = tmp_dir / "concatenated.mp4"

        try:
            with list_path.open("w", encoding="utf-8") as f:
                for path in video_paths:
                    normalized = os.path.abspath(path).replace("\\", "/")
                    escaped = normalized.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

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

            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return str(output_path)
            else:
                logger.error("concat_failed", stderr=proc.stderr[:500])
                return None

        except Exception as exc:
            logger.exception("concat_error", error=str(exc))
            return None

    async def _overlay_voice(
        self,
        video_path: str,
        voice_path: str,
        tmp_dir: Path,
    ) -> str | None:
        """Overlay full voice track onto concatenated video."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return video_path

        # Download voice if remote
        local_voice = await self._resolve_local_path(voice_path, tmp_dir, ".wav")
        if not local_voice:
            return video_path

        output_path = tmp_dir / "with_voice.mp4"

        try:
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-i", local_voice,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
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

            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return str(output_path)
            else:
                logger.error("voice_overlay_failed", stderr=proc.stderr[:500])
                return video_path

        except Exception as exc:
            logger.exception("voice_overlay_error", error=str(exc))
            return video_path

    async def _apply_fade_to_path(self, video_path: str) -> str | None:
        """Apply fade in/out to a video file."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_fade_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fade_output = tmp_dir / "faded.mp4"

        try:
            duration = await self._probe_duration(video_path)
            fade_out_start = max(0, (duration or 0) - 1.5)

            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-vf", f"fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out_start}:d=1.0",
                "-c:a", "copy",
                str(fade_output),
            ]

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode == 0 and fade_output.exists() and fade_output.stat().st_size > 0:
                # Move to stable path before tmp_dir cleanup
                stable_path = Path(tempfile.gettempdir()) / f"arya_faded_{uuid.uuid4().hex}.mp4"
                shutil.move(str(fade_output), str(stable_path))
                return str(stable_path)
            return None

        except Exception:
            return None
        finally:
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
            except Exception:
                pass

    def _generate_srt(self, segments: list[dict], output_path: Path) -> None:
        """Generate SRT subtitle file from segments."""
        def fmt_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")

    async def _burn_subtitles(
        self,
        video_path: str,
        segments: list[dict],
    ) -> str | None:
        """Burn SRT subtitles into video using FFmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not segments:
            return None

        tmp_dir = Path(tempfile.gettempdir()) / f"arya_subs_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            srt_path = tmp_dir / "subtitles.srt"
            self._generate_srt(segments, srt_path)

            output_path = tmp_dir / "subtitled.mp4"

            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-vf", f"subtitles={srt_path}:force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Alignment=2'",
                "-c:a", "copy",
                str(output_path),
            ]

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                # Move to stable path before tmp_dir cleanup
                stable_path = Path(tempfile.gettempdir()) / f"arya_subtitled_{uuid.uuid4().hex}.mp4"
                shutil.move(str(output_path), str(stable_path))
                return str(stable_path)
            return None

        except Exception:
            return None
        finally:
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
            except Exception:
                pass

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