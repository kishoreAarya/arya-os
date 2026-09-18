"""Caption Validator — validates deterministic subtitle/caption timelines.

Grounded in Sections 8 & 17 of Task 16 specification and CINEMATIC_PRODUCTION_BIBLE.md.
Evaluates:
1. Presence: Captions are mandatory when captions_required=True.
2. Temporal Integrity:
   - No negative timestamps
   - End > start (no impossible durations)
   - Duration within readable bounds (0.2s <= dur <= 12.0s)
   - No caption extends beyond video duration
3. Formatting & Readability:
   - No empty caption segments
   - Max characters per line <= 48
   - Max 2 lines per card
   - Chronological ordering
4. Distinguishes:
   - captions present
   - captions absent
   - captions invalid
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.schemas.cinematic import CaptionSegment, CaptionTimeline
from app.validators.base import BaseValidator, ValidationResult

logger = get_logger("arya.validators.caption_validator")

MAX_LINE_LENGTH_CHARS = 48
MAX_LINES_PER_CARD = 2
MIN_SEGMENT_DURATION = 0.2
MAX_SEGMENT_DURATION = 12.0


class CaptionValidator(BaseValidator):
    name = "caption_validator"

    def __init__(self, captions_required: bool = False) -> None:
        self.captions_required = captions_required

    def validate(self, artifact: dict[str, Any]) -> ValidationResult:
        """Validate caption timeline against video and narration duration."""
        captions_required = bool(
            artifact.get("captions_required", self.captions_required)
        )

        # 1. Extract caption data
        raw_captions = (
            artifact.get("caption_timeline")
            or artifact.get("captions")
            or artifact.get("caption_segments")
        )

        raw_items: list[dict[str, Any]] = []
        if isinstance(raw_captions, CaptionTimeline):
            raw_items = [s.model_dump() for s in raw_captions.segments]
        elif isinstance(raw_captions, dict):
            raw_items = raw_captions.get("segments", [])
        elif isinstance(raw_captions, list):
            for item in raw_captions:
                if isinstance(item, CaptionSegment):
                    raw_items.append(item.model_dump())
                elif isinstance(item, dict):
                    raw_items.append(item)

        # 2. Check presence vs requirements
        if not raw_items:
            if captions_required:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    dimension_scores={"captions": 0.0, "status": 0.0},
                    issues=["Captions are mandatory for cinematic productions but are absent"],
                    notes="captions absent: required by cinematic specification but missing from output.",
                )
            else:
                return ValidationResult(
                    passed=True,
                    score=100.0,
                    dimension_scores={"captions": 100.0, "status": 100.0},
                    issues=[],
                    notes="captions absent: optional for this workflow.",
                )

        # 3. Video & narration duration context
        v_dur_raw = (
            artifact.get("video_duration_seconds")
            or artifact.get("video_duration")
            or artifact.get("duration_seconds")
            or artifact.get("duration")
        )
        try:
            video_duration = float(v_dur_raw) if v_dur_raw else None
        except (ValueError, TypeError):
            video_duration = None

        narration_dur_raw = artifact.get("voice_duration_seconds") or artifact.get("narration_duration")
        try:
            narration_duration = float(narration_dur_raw) if narration_dur_raw else None
        except (ValueError, TypeError):
            narration_duration = None

        # 4. Detailed validation of each segment
        issues: list[str] = []
        prev_start = -0.001

        for idx, seg in enumerate(raw_items):
            text = str(seg.get("text", "")).strip()
            try:
                st = float(seg.get("start_seconds", 0.0))
            except (ValueError, TypeError):
                issues.append(f"Caption segment {idx} has invalid start timestamp")
                st = 0.0
            try:
                en = float(seg.get("end_seconds", 0.0))
            except (ValueError, TypeError):
                issues.append(f"Caption segment {idx} has invalid end timestamp")
                en = 0.0
            dur = en - st

            # Empty text check
            if not text:
                issues.append(f"Caption segment {idx} has empty text")
                continue

            # Negative timestamp check
            if st < 0.0:
                issues.append(f"Caption segment {idx} has negative start timestamp: {st:.2f}s")

            # Impossible duration
            if en <= st:
                issues.append(f"Caption segment {idx} has impossible duration (end {en:.2f}s <= start {st:.2f}s)")

            # Duration bounds
            if dur < MIN_SEGMENT_DURATION:
                issues.append(f"Caption segment {idx} duration ({dur:.2f}s) is below minimum readable limit ({MIN_SEGMENT_DURATION}s)")
            elif dur > MAX_SEGMENT_DURATION:
                issues.append(f"Caption segment {idx} duration ({dur:.2f}s) exceeds maximum readable limit ({MAX_SEGMENT_DURATION}s)")

            # Beyond video duration
            if video_duration is not None and en > (video_duration + 0.75):
                issues.append(f"Caption segment {idx} end time ({en:.2f}s) extends beyond video duration ({video_duration:.2f}s)")

            # Chronological order
            if st < prev_start:
                issues.append(f"Caption segment {idx} is out of chronological sequence (start {st:.2f}s < prev {prev_start:.2f}s)")
            prev_start = st

            # Line length and line count (Safe area & legibility)
            lines = text.split("\n")
            if len(lines) > MAX_LINES_PER_CARD:
                issues.append(f"Caption segment {idx} exceeds maximum {MAX_LINES_PER_CARD} lines (found {len(lines)})")
            for line_idx, line in enumerate(lines):
                if len(line) > MAX_LINE_LENGTH_CHARS:
                    issues.append(
                        f"Caption segment {idx} line {line_idx+1} exceeds {MAX_LINE_LENGTH_CHARS} chars "
                        f"(length: {len(line)}, text: '{line[:30]}...')"
                    )

        # 5. Narration overlap check
        if narration_duration and raw_items:
            first_start = float(raw_items[0].get("start_seconds", 0.0))
            last_end = float(raw_items[-1].get("end_seconds", 0.0))
            if first_start > 3.0:
                issues.append(f"First caption starts too late ({first_start:.2f}s) relative to narration start")
            if last_end < (narration_duration * 0.7):
                issues.append(
                    f"Captions end prematurely ({last_end:.2f}s) compared to narration duration ({narration_duration:.2f}s)"
                )

        # 6. Scoring and result determination
        if issues:
            score = max(0.0, round(100.0 - (18.0 * len(issues)), 1))
            return ValidationResult(
                passed=False,
                score=score,
                dimension_scores={
                    "captions": score,
                    "status": 0.0,
                    "issues_count": float(len(issues)),
                },
                issues=issues,
                notes=f"captions invalid: {len(issues)} issue(s) detected across {len(raw_items)} segments.",
            )

        return ValidationResult(
            passed=True,
            score=100.0,
            dimension_scores={
                "captions": 100.0,
                "status": 100.0,
                "segment_count": float(len(raw_items)),
            },
            issues=[],
            notes=f"captions present: {len(raw_items)} valid segments conforming to cinematic style.",
        )
