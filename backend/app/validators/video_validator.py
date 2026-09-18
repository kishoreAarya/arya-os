"""Video Validator — inspects video assets via ffprobe / media inspection.

Evaluates:
1. Hard Technical Validation:
   - File existence and container readability (detects corruption)
   - Presence of valid video stream
   - Duration > 0 and within min/max bounds
   - Resolution dimensions > 0
2. Media & Quality Scoring:
   - Stream integrity (codec recognition and container validity)
   - Resolution compliance (target/min resolution)
   - Frame rate stability (reasonable FPS bounds)
   - Duration compliance (alignment with target duration)
   - Audio/video duration consistency (A/V sync drift detection)
"""
import json
import os
import subprocess
from typing import Any, Callable

from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.video_validator")

# Configurable defaults
DEFAULT_MIN_DURATION_SECONDS = 0.5
DEFAULT_MAX_DURATION_SECONDS = 7200.0
DEFAULT_MIN_WIDTH = 480
DEFAULT_MIN_HEIGHT = 480
DEFAULT_MIN_FPS = 12.0
DEFAULT_MAX_FPS = 120.0
DEFAULT_MAX_AV_SYNC_DRIFT_SECONDS = 1.0
DEFAULT_PASSING_THRESHOLD = 70.0

RECOGNIZED_VIDEO_CODECS = {
    "h264", "hevc", "h265", "vp9", "vp8", "av1", "prores", "mpeg4"
}


def _parse_fps(fps_str: str | float | int | None) -> float | None:
    """Parses ffprobe r_frame_rate (e.g. '30/1', '24000/1001') to float."""
    if fps_str is None:
        return None
    if isinstance(fps_str, (int, float)):
        return float(fps_str)
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            num_f, den_f = float(num), float(den)
            return round(num_f / den_f, 2) if den_f != 0 else None
        return round(float(fps_str), 2)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


class VideoValidator(BaseValidator):
    name = "video_validator"

    def __init__(
        self,
        min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
        min_width: int = DEFAULT_MIN_WIDTH,
        min_height: int = DEFAULT_MIN_HEIGHT,
        target_width: int | None = None,
        target_height: int | None = None,
        min_fps: float = DEFAULT_MIN_FPS,
        max_fps: float = DEFAULT_MAX_FPS,
        max_av_sync_drift_seconds: float = DEFAULT_MAX_AV_SYNC_DRIFT_SECONDS,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
        probe_fn: Callable[[str], dict] | None = None,
        captions_required: bool = False,
    ):
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.min_width = min_width
        self.min_height = min_height
        self.target_width = target_width
        self.target_height = target_height
        self.min_fps = min_fps
        self.max_fps = max_fps
        self.max_av_sync_drift_seconds = max_av_sync_drift_seconds
        self.passing_threshold = passing_threshold
        self.probe_fn = probe_fn
        self.captions_required = captions_required

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = (
            artifact.get("video_storage_path")
            or artifact.get("storage_path")
            or artifact.get("path")
        )

        issues: list[str] = []

        # 1. Hard Technical Check: path presence
        if not storage_path:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0},
                issues=["Missing video file path"],
                notes="Hard failure: no storage_path provided in artifact.",
            )

        # 2. Extract probe metadata (via injected data, probe_fn, or ffprobe)
        probe_data = artifact.get("probe_data")
        if probe_data is None and self.probe_fn is not None:
            try:
                probe_data = self.probe_fn(str(storage_path))
            except Exception as exc:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"video": 0.0},
                    issues=[f"Custom probe failed: {exc}"],
                    notes="Probe execution failure.",
                )

        if probe_data is None:
            inspect_path = str(storage_path)
            tmp_download_path: str | None = None
            if inspect_path.startswith(("http://", "https://")):
                import tempfile
                import urllib.request
                try:
                    fd, tmp_download_path = tempfile.mkstemp(suffix=".mp4", prefix="arya_val_vid_")
                    os.close(fd)
                    req = urllib.request.Request(inspect_path, headers={"User-Agent": "AryaOS/1.0"})
                    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_download_path, "wb") as f:
                        f.write(resp.read())
                    inspect_path = tmp_download_path
                except Exception as exc:
                    if tmp_download_path and os.path.exists(tmp_download_path):
                        try:
                            os.remove(tmp_download_path)
                        except OSError:
                            pass
                    return ValidationResult(
                        passed=False,
                        score=0.0,
                        dimension_scores={"video": 0.0},
                        issues=[f"Failed to retrieve remote video: {exc}"],
                        notes=f"Hard failure: remote video download failed: {exc}",
                    )

            if not os.path.exists(inspect_path):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"video": 0.0},
                    issues=[f"Video file not found at path: {storage_path}"],
                    notes="Hard failure: file does not exist on disk.",
                )
            try:
                probe_res = self._run_ffprobe(inspect_path)
            finally:
                if tmp_download_path and os.path.exists(tmp_download_path):
                    try:
                        os.remove(tmp_download_path)
                    except OSError:
                        pass
            if isinstance(probe_res, ValidationResult):
                return probe_res
            probe_data = probe_res

        # 3. Stream & Format Inspection
        streams = probe_data.get("streams", [])
        format_info = probe_data.get("format", {})

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        # Hard failure: no video stream
        if not video_streams:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0, "stream_integrity": 0.0},
                issues=["No valid video stream found in media file"],
                notes="Hard failure: no video stream present.",
            )

        v_stream = video_streams[0]

        # Duration resolution
        raw_duration = (
            v_stream.get("duration")
            or format_info.get("duration")
            or artifact.get("duration_seconds")
        )
        try:
            duration = float(raw_duration) if raw_duration is not None else 0.0
        except (ValueError, TypeError):
            duration = 0.0

        if duration <= 0:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0, "duration": 0.0},
                issues=["Zero or negative video duration"],
                notes=f"Hard failure: duration is {duration}s.",
            )

        # Resolution resolution
        width = v_stream.get("width")
        height = v_stream.get("height")
        if not width or not height or width <= 0 or height <= 0:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0, "resolution": 0.0},
                issues=["Invalid or missing video resolution dimensions"],
                notes="Hard failure: invalid dimensions.",
            )

        # 4. Dimension Quality Scoring
        # --- A. Stream Integrity (Max 25 pts) ---
        codec_name = str(v_stream.get("codec_name", "")).lower()
        if codec_name in RECOGNIZED_VIDEO_CODECS:
            stream_integrity = 25.0
        elif codec_name:
            stream_integrity = 18.0
        else:
            stream_integrity = 10.0
            issues.append("Unidentified video codec")

        # --- B. Resolution Compliance (Max 25 pts) ---
        if width < self.min_width or height < self.min_height:
            res_score = 10.0
            issues.append(f"Resolution {width}x{height} is below minimum {self.min_width}x{self.min_height}")
        elif (width >= 1920 and height >= 1080) or (width >= 1080 and height >= 1920):
            res_score = 25.0  # Full HD or 9:16 vertical HD
        elif (width >= 1280 and height >= 720) or (width >= 720 and height >= 1280):
            res_score = 22.0  # 720p HD
        else:
            res_score = 18.0  # Standard acceptable definition

        if self.target_width and self.target_height:
            if width != self.target_width or height != self.target_height:
                res_score = max(5.0, res_score - 5.0)
                issues.append(f"Resolution {width}x{height} does not match target {self.target_width}x{self.target_height}")

        target_ar = artifact.get("aspect_ratio")
        if target_ar:
            ratio = width / height if height > 0 else 0
            if target_ar == "9:16" and abs(ratio - 9 / 16) > 0.05:
                res_score = max(5.0, res_score - 8.0)
                issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected 9:16")
            elif target_ar == "16:9" and abs(ratio - 16 / 9) > 0.05:
                res_score = max(5.0, res_score - 8.0)
                issues.append(f"Aspect ratio ({ratio:.2f}) does not match expected 16:9")


        # --- C. Frame Rate Stability (Max 15 pts) ---
        fps = _parse_fps(v_stream.get("r_frame_rate"))
        if fps is not None:
            if self.min_fps <= fps <= self.max_fps:
                fps_score = 15.0
            else:
                fps_score = 7.0
                issues.append(f"Frame rate ({fps:.1f} fps) outside expected bounds ({self.min_fps}-{self.max_fps})")
        else:
            fps_score = 10.0

        # --- D. Duration Compliance (Max 20 pts) ---
        if self.min_duration_seconds <= duration <= self.max_duration_seconds:
            dur_score = 20.0
        elif duration < self.min_duration_seconds:
            dur_score = 5.0
            issues.append(f"Duration ({duration:.2f}s) is below minimum ({self.min_duration_seconds}s)")
        else:
            dur_score = 10.0
            issues.append(f"Duration ({duration:.2f}s) exceeds maximum ({self.max_duration_seconds}s)")

        target_dur = artifact.get("target_duration_seconds") or artifact.get("expected_duration_seconds")
        if target_dur is not None:
            dur_diff = abs(duration - float(target_dur))
            if dur_diff > 3.0:
                dur_score = max(5.0, dur_score - 8.0)
                issues.append(f"Duration ({duration:.1f}s) differs from target ({target_dur:.1f}s)")
            elif dur_diff > 1.0:
                dur_score = max(10.0, dur_score - 3.0)

        # --- E. Audio / Video Duration Consistency (Max 15 pts) ---
        if audio_streams:
            a_stream = audio_streams[0]
            raw_a_dur = a_stream.get("duration") or format_info.get("duration")
            try:
                a_dur = float(raw_a_dur) if raw_a_dur is not None else duration
            except (ValueError, TypeError):
                a_dur = duration

            drift = abs(duration - a_dur)
            if drift <= self.max_av_sync_drift_seconds:
                audio_score = 15.0
            else:
                audio_score = max(5.0, 15.0 - (drift * 5.0))
                issues.append(
                    f"A/V duration drift ({drift:.2f}s) exceeds tolerance ({self.max_av_sync_drift_seconds}s)"
                )
        else:
            if artifact.get("require_audio", False):
                audio_score = 0.0
                issues.append("Required audio stream is missing")
            else:
                audio_score = 12.0  # Silent clip default

        # --- F. Captions Validation (Section 8 & 17 of Cinematic Bible) ---
        from app.validators.caption_validator import CaptionValidator
        cap_val = CaptionValidator(captions_required=self.captions_required)
        cap_res = cap_val.validate(artifact)
        caption_score = cap_res.score
        if not cap_res.passed:
            issues.extend(cap_res.issues)

        total_score = round(
            stream_integrity + res_score + fps_score + dur_score + audio_score, 1
        )
        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "stream_integrity": round(stream_integrity, 1),
            "resolution": round(res_score, 1),
            "frame_rate": round(fps_score, 1),
            "duration": round(dur_score, 1),
            "audio_sync": round(audio_score, 1),
            "captions": round(caption_score, 1),
            "video": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Video inspection completed. Resolution: {width}x{height}, FPS: {fps}, Duration: {duration:.2f}s.",
        )

    def _run_ffprobe(self, file_path: str) -> dict | ValidationResult:
        """Invokes ffprobe subprocess to inspect the media file."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,size,bit_rate",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,duration,bit_rate",
            "-of", "json",
            file_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"video": 0.0},
                    issues=[f"Corrupted video file: ffprobe failed to decode ({res.stderr.strip()[:200]})"],
                    notes="Media inspection failed: corrupt or unreadable file.",
                )
            return json.loads(res.stdout)
        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0},
                issues=["ffprobe timed out inspecting media file"],
                notes="Timeout during ffprobe execution.",
            )
        except Exception as exc:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"video": 0.0},
                issues=[f"ffprobe execution error: {exc}"],
                notes="Exception running ffprobe.",
            )