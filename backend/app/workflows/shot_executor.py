"""ShotExecutor — executes every storyboard shot through the generation pipeline.

Integrates with the existing Orchestrator architecture by reusing the
same stage-execution mechanism (agent-registry lookup, retry logic,
timing, cost tracking, and StageResult wrapping).  Does not publish,
write to the database, or run analytics.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult
from app.agents.storyboard import Shot
from app.core.logging import get_logger
from app.workflows.models import StageResult
from app.workflows.stage_executor import execute_stage, _merge_context

logger = get_logger("arya.workflows.shot_executor")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ShotExecutionResult:
    shot_number: int
    stage_results: list[StageResult] = field(default_factory=list)
    positive_prompt: str = ""
    negative_prompt: str = ""
    image_path: str | None = None
    video_path: str | None = None
    voice_path: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0  # Media duration of the shot in seconds
    execution_time_ms: float = 0.0  # Wall-clock execution time in milliseconds
    success: bool = False
    error: str | None = None
    generation_mode: str | None = None
    generation_class: str | None = None
    candidate_urls: list[str] = field(default_factory=list)
    num_candidates: int = 1
    keyframe_selection: dict | None = None


@dataclass
class ShotExecutionSummary:
    results: list[ShotExecutionResult] = field(default_factory=list)

    video_clips: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    voice_paths: list[str] = field(default_factory=list)
    music_path: str | None = None

    total_cost: float = 0.0
    total_duration: float = 0.0
    cost_breakdown: dict | None = None


# ---------------------------------------------------------------------------
# ShotExecutor
# ---------------------------------------------------------------------------

class ShotExecutor:
    """Executes a list of storyboard shots through Prompt → Image → Video → Voice.

    Each shot runs sequentially. One shot failing does not abort the
    remaining shots. The class delegates stage execution to the shared
    ``execute_stage`` helper so that Orchestrator and ShotExecutor
    follow the same execution path.
    """

    def __init__(self, db: AsyncSession, max_retries: int = 3) -> None:
        self._db = db
        self._max_retries = max_retries

    async def execute(self, context: dict[str, Any]) -> ShotExecutionSummary:
        """Run every shot in *context["shots"]* through the pipeline.

        Args:
            context: Execution context containing at least ``shots``.
                Each entry is a :class:`Shot` dataclass.

        Returns:
            Summary with per-shot results and rolled-up totals.
        """
        shots: list[Shot] = context.get("shots", [])

        # Initialize accumulators BEFORE any early-return check
        video_clips: list[str] = []
        image_paths: list[str] = []
        voice_paths: list[str] = []

        logger.info(
            "shot_executor_summary",
            shot_count=len(shots),
        )

        if not shots:
            logger.warning("shot_executor_no_shots")
            logger.info(
                "shot_summary_debug",
                video_clips=video_clips,
                image_paths=image_paths,
                voice_paths=voice_paths,
            )
            return ShotExecutionSummary(
                video_clips=video_clips,
                image_paths=image_paths,
                voice_paths=voice_paths,
            )

        results: list[ShotExecutionResult] = []
        total_cost = 0.0
        total_duration = 0.0

        for shot in shots:
            shot_result = await self._execute_single_shot(shot, context)
            results.append(shot_result)
            if shot_result.video_path:
                video_clips.append(shot_result.video_path)
            if shot_result.image_path:
                image_paths.append(shot_result.image_path)
            if shot_result.voice_path:
                voice_paths.append(shot_result.voice_path)
            total_cost += shot_result.cost_usd
            total_duration += shot_result.duration_seconds

        cost_breakdown: dict[str, float] | None = None
        try:
            from app.services.smart_allocator import SmartShotAllocator
            cost_breakdown = SmartShotAllocator.calculate_cost_breakdown(
                shots=shots,
                narration_cost=float(context.get("master_voice_cost", 0.0) or context.get("voice_cost", 0.0)),
                music_cost=float(context.get("master_music_cost", 0.0) or context.get("music_cost", 0.0)),
                prompt_cost=float(context.get("prompt_cost", 0.0)),
                visual_profile=context.get("visual_profile"),
            ).to_dict()
        except Exception:
            pass

        return ShotExecutionSummary(
            results=results,
            video_clips=video_clips,
            image_paths=image_paths,
            voice_paths=voice_paths,
            total_cost=total_cost,
            total_duration=total_duration,
            cost_breakdown=cost_breakdown,
        )

    async def _execute_single_shot(
        self,
        shot: Shot,
        base_context: dict[str, Any],
    ) -> ShotExecutionResult:
        """Execute one shot through Prompt → Image → Video → Voice."""
        shot_start = time.perf_counter()
        
        # P0 FIX: Extract all fields from both dict and dataclass shots
        if isinstance(shot, dict):
            shot_number = shot.get("shot_number", 0)
            shot_description = shot.get("description", "")
            shot_voiceover = shot.get("voiceover")
            shot_dialogue = shot.get("dialogue")
            shot_camera_angle = shot.get("camera_angle")
            shot_camera_movement = shot.get("camera_movement")
            shot_lighting = shot.get("lighting")
            shot_environment = shot.get("environment")
            shot_continuity_notes = shot.get("continuity_notes")
            shot_duration_seconds = shot.get("duration_seconds")
            shot_transition = shot.get("transition")
            shot_image_prompt_hint = shot.get("image_prompt_hint")
            shot_negative_prompt_hint = shot.get("negative_prompt_hint")
            shot_generation_class = shot.get("generation_class")
            shot_generation_mode = shot.get("generation_mode")
        else:
            shot_number = shot.shot_number
            shot_description = shot.description
            shot_voiceover = getattr(shot, "voiceover", None)
            shot_dialogue = getattr(shot, "dialogue", None)
            shot_camera_angle = getattr(shot, "camera_angle", None)
            shot_camera_movement = getattr(shot, "camera_movement", None)
            shot_lighting = getattr(shot, "lighting", None)
            shot_environment = getattr(shot, "environment", None)
            shot_continuity_notes = getattr(shot, "continuity_notes", None)
            shot_duration_seconds = getattr(shot, "duration_seconds", None)
            shot_transition = getattr(shot, "transition", None)
            shot_image_prompt_hint = getattr(shot, "image_prompt_hint", None)
            shot_negative_prompt_hint = getattr(shot, "negative_prompt_hint", None)
            shot_generation_class = getattr(shot, "generation_class", None)
            shot_generation_mode = getattr(shot, "generation_mode", None)

        result = ShotExecutionResult(
            shot_number=shot_number,
        )
        stage_results: list[StageResult] = []
        shot_cost = 0.0

        shot_context = _merge_context(base_context, {
            "shot_number": shot_number,
            "shot_description": shot_description,
        })

        # Inject optional cinematic metadata if present on the shot.
        if shot_camera_angle:
            shot_context["camera_style"] = shot_camera_angle
        if shot_lighting:
            shot_context["lighting_style"] = shot_lighting
        if shot_environment:
            shot_context["environment_bible"] = shot_environment
        if shot_continuity_notes:
            shot_context["continuity_notes"] = shot_continuity_notes

        # Inject Visual Continuity Bible context if available
        bible_data = base_context.get("continuity_bible") or base_context.get("visual_continuity_bible")
        if bible_data:
            try:
                from app.services.visual_continuity import VisualContinuityBible, build_shot_continuity_context
                bible_obj = (
                    bible_data
                    if isinstance(bible_data, VisualContinuityBible)
                    else VisualContinuityBible(**bible_data)
                )
                compact_cont = build_shot_continuity_context(bible_obj, shot)
                if compact_cont:
                    existing = shot_context.get("continuity_notes") or ""
                    shot_context["continuity_notes"] = f"{existing}\n{compact_cont}".strip()
            except Exception:
                pass

        if getattr(shot, "num_candidates", None) is not None:
            shot_context["num_keyframe_candidates"] = shot.num_candidates
        elif isinstance(shot, dict) and shot.get("num_candidates") is not None:
            shot_context["num_keyframe_candidates"] = shot.get("num_candidates")
        elif "num_keyframe_candidates" in base_context:
            shot_context["num_keyframe_candidates"] = base_context["num_keyframe_candidates"]
        elif "keyframe_candidates" in base_context:
            shot_context["num_keyframe_candidates"] = base_context["keyframe_candidates"]

        if shot_duration_seconds:
            shot_context["duration_seconds"] = shot_duration_seconds
        shot_context["aspect_ratio"] = base_context.get("aspect_ratio", "16:9")

        if shot_dialogue:
            shot_context["dialogue"] = shot_dialogue
        if shot_voiceover:
            shot_context["voiceover"] = shot_voiceover
        if shot_transition:
            shot_context["transition"] = shot_transition
        if shot_image_prompt_hint:
            shot_context["image_prompt_hint"] = shot_image_prompt_hint
        if shot_negative_prompt_hint:
            shot_context["negative_prompt_hint"] = shot_negative_prompt_hint

        logger.info(
            "shot_execution_started",
            shot_number=shot_number,
            description=shot_description,
            generation_class=shot_generation_class,
            generation_mode=shot_generation_mode,
        )

        is_image_motion = (shot_generation_mode == "image_motion")
        has_master_voice = bool(
            base_context.get("master_voice_path")
            or base_context.get("narration_timing")
            or (base_context.get("use_cinematic_director") and base_context.get("voice_path"))
        )

        if is_image_motion:
            stages = ["prompt", "image"] if has_master_voice else ["prompt", "image", "voice"]
        else:
            stages = ["prompt", "image", "video"] if has_master_voice else ["prompt", "image", "video", "voice"]

        for stage_key in stages:
            stage_result = await execute_stage(
                stage_key=stage_key,
                context=shot_context,
                db=self._db,
                max_retries=self._max_retries,
            )
            stage_results.append(stage_result)
            shot_cost += stage_result.cost_usd or 0.0

            if not stage_result.success:
                result.error = f"{stage_key} failed: {stage_result.error}"
                result.stage_results = stage_results
                result.execution_time_ms = (time.perf_counter() - shot_start) * 1000
                result.duration_seconds = 0.0
                result.cost_usd = shot_cost
                logger.warning(
                    "shot_execution_failed",
                    shot_number=shot_number,
                    stage=stage_key,
                    error=stage_result.error,
                )
                return result

            if stage_result.output:
                shot_context = _merge_context(shot_context, stage_result.output)

            # For image_motion mode: synthesize camera motion video from generated image after "image" stage
            if is_image_motion and stage_key == "image":
                image_file = (
                    _extract_str(shot_context, "image_path")
                    or _extract_str(shot_context, "storage_path")
                    or _extract_str(shot_context, "source_image_path")
                )
                if not image_file and shot_context.get("image_result"):
                    img_res = shot_context.get("image_result")
                    image_file = getattr(img_res, "storage_path", None) or (
                        img_res.get("storage_path") if isinstance(img_res, dict) else None
                    )
                motion_dur = float(shot_duration_seconds or 4.0)
                aspect_ratio = shot_context.get("aspect_ratio", "16:9")
                is_dry_run = bool(
                    shot_context.get("visual_dry_run")
                    or (image_file and str(image_file).startswith("dry_run://"))
                )
                if is_dry_run:
                    motion_video = f"dry_run://shot_{shot_number}_motion.mp4"
                else:
                    motion_video = await self._render_image_motion_clip(
                        image_path=image_file,
                        camera_movement=shot_camera_movement or "slow_push_in",
                        duration_seconds=motion_dur,
                        aspect_ratio=aspect_ratio,
                    )
                if not motion_video:
                    result.error = f"image_motion rendering failed for shot {shot_number}"
                    result.stage_results = stage_results
                    result.execution_time_ms = (time.perf_counter() - shot_start) * 1000
                    result.duration_seconds = 0.0
                    result.cost_usd = shot_cost
                    logger.warning("shot_image_motion_failed", shot_number=shot_number)
                    return result

                shot_context["video_path"] = motion_video
                shot_context["video_storage_path"] = motion_video

                # Synthetic StageResult for "video" stage with $0.00 cost
                video_res_stub = type("VideoResultStub", (), {"video_url": motion_video, "duration_seconds": motion_dur})()
                synth_video_stage = StageResult(
                    stage="video",
                    success=True,
                    output={
                        "video_path": motion_video,
                        "video_storage_path": motion_video,
                        "video_result": video_res_stub,
                        "generation_mode": "image_motion",
                    },
                    cost_usd=0.0,
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    execution_time_ms=0.0,
                )
                stage_results.append(synth_video_stage)

        # Collect outputs safely.
        result.positive_prompt = _extract_str(shot_context, "positive_prompt") or ""
        result.negative_prompt = _extract_str(shot_context, "negative_prompt") or ""
        result.image_path = (
            _extract_str(shot_context, "image_path")
            or _extract_str(shot_context, "storage_path")
            or _extract_str(shot_context, "source_image_path")
        )
        if not result.image_path and shot_context.get("image_result"):
            img_res = shot_context.get("image_result")
            result.image_path = getattr(img_res, "storage_path", None) or (
                img_res.get("storage_path") if isinstance(img_res, dict) else None
            )
        result.video_path = (
            _extract_str(shot_context, "video_path")
            or _extract_str(shot_context, "video_storage_path")
        )
        if has_master_voice:
            result.voice_path = None
        else:
            result.voice_path = (
                _extract_str(shot_context, "voice_path")
                or _extract_str(shot_context, "audio_path")
            )
        result.stage_results = stage_results
        result.cost_usd = shot_cost
        result.execution_time_ms = (time.perf_counter() - shot_start) * 1000
        result.generation_mode = str(shot_generation_mode) if shot_generation_mode else None
        result.generation_class = str(shot_generation_class) if shot_generation_class else None

        img_res = shot_context.get("image_result")
        if img_res:
            cand_urls = getattr(img_res, "candidate_urls", None) or (
                img_res.get("candidate_urls") if isinstance(img_res, dict) else []
            ) or []
            result.candidate_urls = cand_urls
            result.keyframe_selection = getattr(img_res, "keyframe_selection", None) or (
                img_res.get("keyframe_selection") if isinstance(img_res, dict) else None
            )
            result.num_candidates = len(cand_urls) if cand_urls else int(shot_context.get("num_keyframe_candidates") or 1)
        else:
            result.num_candidates = int(shot_context.get("num_keyframe_candidates") or 1)

        # Calculate true media duration of the shot
        shot_media_duration = 0.0
        for sr in stage_results:
            if sr.stage == "voice" and sr.output:
                v_res = sr.output.get("voice_result")
                if v_res and getattr(v_res, "duration_seconds", None):
                    shot_media_duration = max(shot_media_duration, float(v_res.duration_seconds))
                elif sr.output.get("target_duration_seconds"):
                    shot_media_duration = max(shot_media_duration, float(sr.output["target_duration_seconds"]))
            if sr.stage == "video" and sr.output:
                vid_res = sr.output.get("video_result")
                if vid_res and getattr(vid_res, "duration_seconds", None):
                    shot_media_duration = max(shot_media_duration, float(vid_res.duration_seconds))

        if shot_media_duration <= 0.0:
            if shot_duration_seconds:
                try:
                    shot_media_duration = float(shot_duration_seconds)
                except (ValueError, TypeError):
                    shot_media_duration = 4.0
            else:
                shot_media_duration = 4.0

        result.duration_seconds = shot_media_duration
        result.success = True

        logger.info(
            "shot_execution_succeeded",
            shot_number=shot_number,
            cost_usd=shot_cost,
            duration_seconds=result.duration_seconds,
        )

        logger.info(
            "shot_result_debug",
            video_path=result.video_path,
            image_path=result.image_path,
            voice_path=result.voice_path,
        )

        return result

    async def _render_image_motion_clip(
        self,
        image_path: str,
        camera_movement: str,
        duration_seconds: float,
        aspect_ratio: str = "16:9",
    ) -> str | None:
        """Render cinematic camera motion clip from a still image using FFmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.error("ffmpeg_not_found_for_image_motion")
            return None

        if not image_path:
            logger.error("image_file_not_found_for_motion", image_path=image_path)
            return None

        local_image: str | None = None
        is_temp_download = False
        try:
            if image_path.startswith(("http://", "https://")):
                from app.utils.asset_manager import ensure_local_asset
                local_image = await ensure_local_asset(
                    image_path, timeout_seconds=30.0, max_bytes=50 * 1024 * 1024
                )
                is_temp_download = True
            else:
                local_image = image_path

            if not local_image or not Path(local_image).exists() or Path(local_image).stat().st_size == 0:
                logger.error("image_file_not_found_for_motion", image_path=image_path, local_image=local_image)
                return None

            try:
                from PIL import Image
                with Image.open(local_image) as img:
                    img.verify()
            except Exception as exc:
                logger.error("image_validation_failed_for_motion", error=str(exc), image_path=image_path)
                return None

            from app.core.aspect_ratio import get_aspect_ratio_config
            config = get_aspect_ratio_config(aspect_ratio)
            target_w, target_h = config.width, config.height

            fps = 30
            total_frames = max(15, int(round(duration_seconds * fps)))
            output_path = Path(tempfile.gettempdir()) / f"arya_motion_{uuid.uuid4().hex}.mp4"

            move = (camera_movement or "slow_push_in").lower()

            if config.is_vertical:  # 9:16 (1080x1920)
                hi_w, hi_h = 2160, 3840
                if move in ("slow_push_in", "push_in", "zoom_in"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='min(zoom+0.0008,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("slow_pull_out", "pull_out", "zoom_out"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='if(lte(zoom,1.0),1.08,max(1.001,zoom-0.0008))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("pan_left", "drift_left"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='if(lte(on,1),iw-iw/zoom,max(0,x-1.2))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("pan_right", "drift_right"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='if(lte(on,1),0,min(x+1.2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("tilt_up",):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),ih-ih/zoom,max(0,y-1.2))':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("tilt_down",):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),0,min(y+1.2,ih-ih/zoom))':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("subtle_scale", "scale"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='min(zoom+0.0004,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                else:
                    vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
            else:  # 16:9 (1920x1080)
                hi_w, hi_h = 3840, 2160
                if move in ("slow_push_in", "push_in", "zoom_in"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='min(zoom+0.0008,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("slow_pull_out", "pull_out", "zoom_out"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='if(lte(zoom,1.0),1.08,max(1.001,zoom-0.0008))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("pan_left", "drift_left"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='if(lte(on,1),iw-iw/zoom,max(0,x-1.5))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("pan_right", "drift_right"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='if(lte(on,1),0,min(x+1.5,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("tilt_up",):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),ih-ih/zoom,max(0,y-1.2))':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("tilt_down",):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),0,min(y+1.2,ih-ih/zoom))':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                elif move in ("subtle_scale", "scale"):
                    vf = f"scale={hi_w}:{hi_h},zoompan=z='min(zoom+0.0004,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
                else:
                    vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"

            cmd = [
                ffmpeg,
                "-y",
                "-loop", "1",
                "-i", str(local_image),
                "-vf", vf,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-t", f"{duration_seconds:.3f}",
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
                logger.error("ffmpeg_image_motion_failed", stderr=proc.stderr[:1000])
                return None
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("ffmpeg_image_motion_empty_output")
                return None
            return str(output_path)
        except Exception as exc:
            logger.exception("ffmpeg_image_motion_exception", error=str(exc))
            return None
        finally:
            if is_temp_download and local_image and os.path.exists(local_image):
                try:
                    os.remove(local_image)
                except OSError:
                    pass


def _extract_str(context: dict[str, Any], key: str) -> str | None:
    """Safely extract a non-empty string value from context."""
    value = context.get(key)
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None