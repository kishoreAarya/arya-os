"""Audio Validator — evaluates generated voiceover / audio narration assets.

Evaluates:
1. Hard Technical Validation:
   - File existence and non-zero file size
   - Container readability and stream integrity (detects corrupt audio)
   - Presence of valid audio stream
   - Duration bounds (duration > 0 and >= minimums)
   - Severe speech truncation detection (comparison against script word count)
2. Quality Scoring Dimensions:
   - File integrity (valid container and recognizable audio codec)
   - Format quality (sample rate >= 16kHz/22.05kHz/44.1kHz, channel count)
   - Duration compliance (suitable duration, expected pace for speech)
   - Audio level / bitrate (healthy bitrate > 32kbps/64kbps)
"""
import json
import os
import subprocess
from typing import Any, Callable

from app.core.logging import get_logger
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.audio_validator")

# Configurable defaults
DEFAULT_MIN_DURATION_SECONDS = 0.5
DEFAULT_MAX_DURATION_SECONDS = 7200.0
DEFAULT_MIN_SAMPLE_RATE = 16000
DEFAULT_PASSING_THRESHOLD = 70.0

RECOGNIZED_AUDIO_CODECS = {
    "aac", "mp3", "opus", "flac", "pcm_s16le", "pcm_s24le", "vorbis", "wav"
}


class AudioValidator(BaseValidator):
    name = "audio_validator"

    def __init__(
        self,
        min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
        min_sample_rate: int = DEFAULT_MIN_SAMPLE_RATE,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
        probe_fn: Callable[[str], dict] | None = None,
    ):
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.min_sample_rate = min_sample_rate
        self.passing_threshold = passing_threshold
        self.probe_fn = probe_fn

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = (
            artifact.get("storage_path")
            or artifact.get("audio_path")
            or artifact.get("voice_path")
            or artifact.get("music_path")
            or artifact.get("path")
        )

        issues: list[str] = []

        # 1. Hard Technical Check: path presence
        if not storage_path:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"audio": 0.0},
                issues=["No audio file path provided in artifact"],
                notes="Hard failure: missing storage_path.",
            )

        # 2. Extract probe metadata (injected data, custom probe_fn, or ffprobe)
        probe_data = artifact.get("probe_data")
        if probe_data is None and self.probe_fn is not None:
            try:
                probe_data = self.probe_fn(str(storage_path))
            except Exception as exc:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"audio": 0.0},
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
                    fd, tmp_download_path = tempfile.mkstemp(suffix=".audio", prefix="arya_val_aud_")
                    os.close(fd)
                    req = urllib.request.Request(inspect_path, headers={"User-Agent": "AryaOS/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_download_path, "wb") as f:
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
                        dimension_scores={"audio": 0.0},
                        issues=[f"Failed to retrieve remote audio: {exc}"],
                        notes=f"Hard failure: remote audio download failed: {exc}",
                    )

            if not os.path.exists(inspect_path):
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"audio": 0.0},
                    issues=[f"Audio file not found at path: {storage_path}"],
                    notes="Hard failure: file does not exist on disk.",
                )

            try:
                if os.path.getsize(inspect_path) == 0:
                    return ValidationResult(
                        passed=False,
                        score=0.0,
                        dimension_scores={"audio": 0.0},
                        issues=["Audio file is 0 bytes (empty file)"],
                        notes="Hard failure: empty file.",
                    )

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

        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        # Hard failure: no audio stream
        if not audio_streams:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"audio": 0.0, "stream_integrity": 0.0},
                issues=["No valid audio stream found in media file"],
                notes="Hard failure: media container has no audio stream.",
            )

        a_stream = audio_streams[0]

        # Duration resolution
        raw_duration = (
            a_stream.get("duration")
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
                dimension_scores={"audio": 0.0, "duration": 0.0},
                issues=["Zero or negative audio duration"],
                notes=f"Hard failure: duration is {duration}s.",
            )

        if duration < self.min_duration_seconds:
            return ValidationResult(
                passed=False,
                score=20.0,
                dimension_scores={"audio": 20.0, "duration": 5.0},
                issues=[f"Audio duration ({duration:.2f}s) is below minimum ({self.min_duration_seconds}s)"],
                notes="Hard failure: audio clip too short.",
            )

        # 4. Truncation check against script text
        script_text = (
            artifact.get("script_content")
            or artifact.get("voiceover")
            or artifact.get("text")
        )
        if script_text and isinstance(script_text, str):
            words = len(script_text.split())
            if words >= 10:
                # Average fast speaking rate: 3.5 words/second
                min_expected_sec = words / 3.5
                if duration < min_expected_sec * 0.4:
                    issues.append(
                        f"Audio duration ({duration:.1f}s) is severely truncated for script ({words} words, expected >= {min_expected_sec:.1f}s)"
                    )

        # 5. Dimension Quality Scoring
        # --- A. File Integrity & Codec (Max 30 pts) ---
        codec_name = str(a_stream.get("codec_name", "")).lower()
        if codec_name in RECOGNIZED_AUDIO_CODECS:
            integrity_score = 30.0
        elif codec_name:
            integrity_score = 22.0
        else:
            integrity_score = 15.0
            issues.append("Unidentified audio codec")

        # --- B. Format Quality (Max 25 pts) ---
        try:
            sample_rate = int(a_stream.get("sample_rate", 0))
        except (ValueError, TypeError):
            sample_rate = 0

        try:
            channels = int(a_stream.get("channels", 1))
        except (ValueError, TypeError):
            channels = 1

        if sample_rate >= 44100:
            format_score = 25.0  # Studio CD quality
        elif sample_rate >= 22050:
            format_score = 22.0  # Standard voiceover quality
        elif sample_rate >= self.min_sample_rate:
            format_score = 18.0  # Acceptable speech quality
        else:
            format_score = 10.0
            issues.append(f"Sample rate ({sample_rate} Hz) is below minimum ({self.min_sample_rate} Hz)")

        # --- C. Duration Compliance (Max 25 pts) ---
        if self.min_duration_seconds <= duration <= self.max_duration_seconds:
            dur_score = 25.0
        else:
            dur_score = 12.0
            issues.append(f"Audio duration ({duration:.1f}s) outside expected bounds")

        target_dur = artifact.get("target_duration_seconds")
        if target_dur is not None:
            dur_diff = abs(duration - float(target_dur))
            if dur_diff > 3.0:
                dur_score = max(5.0, dur_score - 8.0)
                issues.append(f"Duration ({duration:.1f}s) differs from target ({target_dur:.1f}s)")
            elif dur_diff > 1.0:
                dur_score = max(15.0, dur_score - 3.0)

        # --- D. Audio Level & Bitrate (Max 20 pts) ---
        raw_bitrate = a_stream.get("bit_rate") or format_info.get("bit_rate")
        try:
            bitrate_kbps = int(raw_bitrate) // 1000 if raw_bitrate else 128
        except (ValueError, TypeError):
            bitrate_kbps = 128

        if bitrate_kbps >= 128:
            bitrate_score = 20.0
        elif bitrate_kbps >= 64:
            bitrate_score = 17.0
        elif bitrate_kbps >= 32:
            bitrate_score = 14.0
        else:
            bitrate_score = 8.0
            issues.append(f"Low audio bitrate ({bitrate_kbps} kbps)")

        total_score = round(
            integrity_score + format_score + dur_score + bitrate_score, 1
        )
        passed = total_score >= self.passing_threshold and len(issues) == 0

        dimension_scores = {
            "file_integrity": round(integrity_score, 1),
            "format_quality": round(format_score, 1),
            "duration": round(dur_score, 1),
            "audio_level": round(bitrate_score, 1),
            "audio": total_score,
        }

        return ValidationResult(
            passed=passed,
            score=total_score,
            dimension_scores=dimension_scores,
            issues=issues,
            notes=f"Audio inspection completed. Codec: {codec_name}, Sample Rate: {sample_rate}Hz, Channels: {channels}, Duration: {duration:.2f}s.",
        )

    def _run_ffprobe(self, file_path: str) -> dict | ValidationResult:
        """Invokes ffprobe subprocess to inspect audio stream and format."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,size,bit_rate",
            "-show_entries", "stream=index,codec_type,codec_name,sample_rate,channels,duration,bit_rate",
            "-of", "json",
            file_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"audio": 0.0},
                    issues=[f"Corrupted audio file: ffprobe failed to decode ({res.stderr.strip()[:200]})"],
                    notes="Media inspection failed: corrupt or unreadable file.",
                )
            return json.loads(res.stdout)
        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"audio": 0.0},
                issues=["ffprobe timed out inspecting audio file"],
                notes="Timeout during ffprobe execution.",
            )
        except Exception as exc:
            return ValidationResult(
                passed=False,
                score=0.0,
                dimension_scores={"audio": 0.0},
                issues=[f"ffprobe execution error: {exc}"],
                notes="Exception running ffprobe.",
            )
