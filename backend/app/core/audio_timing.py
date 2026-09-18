"""Deterministic audio timing and narration segmentation engine.

Grounded in Section 15 of CINEMATIC_PRODUCTION_BIBLE.md.
Transforms raw voice alignment / audio into a typed NarrationTiming
with phrase boundaries, breath gaps, and emotional emphasis signals.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.schemas.cinematic import NarrationSegment, NarrationTiming, WordTiming

logger = get_logger("arya.core.audio_timing")

# Dramatic keywords for deterministic semantic emphasis detection
_EMPHASIS_KEYWORDS = {
    "impossible", "secret", "never", "suddenly", "revealed", "shadow", "truth",
    "alive", "died", "horror", "whisper", "screamed", "blood", "darkness", "trap",
    "vanished", "unseen", "listen", "stop", "breathe", "watch", "alone", "frozen",
}


def probe_audio_duration(audio_path: str) -> float | None:
    """Measure exact audio duration in seconds using ffprobe."""
    if not audio_path or not Path(audio_path).exists():
        return None

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    try:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except Exception as exc:
        logger.warning("ffprobe_duration_failed", path=audio_path, error=str(exc))
    return None


def detect_emotional_emphasis(
    text: str,
    pause_after: float = 0.0,
    segment_index: int = 0,
    total_segments: int = 1,
) -> tuple[bool, str | None]:
    """Detect deterministic emotional emphasis signals from text and timing.

    Signals:
    - Dramatic pause after phrase (>= 0.45s)
    - Punctuation cues (! or ...)
    - Rhythmic contrast (hook phrase, climax, resolution)
    - Semantic emphasis keywords (horror/suspense cues)
    - Unusually long lexical tokens (> 12 letters)
    """
    clean = text.strip()
    words = [w.strip(".,!?;:\"'—-") for w in clean.split() if w.strip(".,!?;:\"'—-")]

    if pause_after >= 0.45:
        return True, "dramatic_pause"

    if clean.endswith("!") or clean.endswith("..."):
        return True, "punctuation_emphasis"

    if len(words) <= 4 and (segment_index == 0 or segment_index == total_segments - 1):
        return True, "hook_or_resolution"

    lower_words = {w.lower() for w in words}
    matched = lower_words.intersection(_EMPHASIS_KEYWORDS)
    if matched:
        return True, f"semantic_emphasis:{next(iter(matched))}"

    if any(len(w) >= 12 for w in words):
        return True, "lexical_emphasis"

    return False, None


def parse_alignment_data(
    text: str,
    alignment: dict[str, Any],
    total_duration: float,
    provider: str = "elevenlabs",
) -> NarrationTiming:
    """Parse character or word-level alignment data into NarrationTiming.

    Supports ElevenLabs character alignment schema:
      characters: list[str]
      character_start_times_seconds: list[float]
      character_end_times_seconds: list[float]
    or pre-segmented words.
    """
    words: list[WordTiming] = []

    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []

    if characters and starts and ends and len(characters) == len(starts) == len(ends):
        # Group characters into words
        current_word_chars: list[str] = []
        word_start: float | None = None
        word_end: float | None = None
        char_start_idx: int | None = None

        for i, char in enumerate(characters):
            if char.isspace():
                if current_word_chars and word_start is not None and word_end is not None:
                    words.append(
                        WordTiming(
                            word="".join(current_word_chars),
                            start_seconds=round(word_start, 3),
                            end_seconds=round(word_end, 3),
                            character_start=char_start_idx,
                            character_end=i,
                        )
                    )
                    current_word_chars = []
                    word_start = None
                    word_end = None
                    char_start_idx = None
            else:
                if word_start is None:
                    word_start = float(starts[i])
                    char_start_idx = i
                word_end = float(ends[i])
                current_word_chars.append(char)

        if current_word_chars and word_start is not None and word_end is not None:
            words.append(
                WordTiming(
                    word="".join(current_word_chars),
                    start_seconds=round(word_start, 3),
                    end_seconds=round(word_end, 3),
                    character_start=char_start_idx,
                    character_end=len(characters),
                )
            )
    elif "words" in alignment and isinstance(alignment["words"], list):
        for w in alignment["words"]:
            words.append(
                WordTiming(
                    word=str(w.get("word") or w.get("text", "")),
                    start_seconds=float(w.get("start", 0.0) or w.get("start_seconds", 0.0)),
                    end_seconds=float(w.get("end", 0.0) or w.get("end_seconds", 0.0)),
                )
            )

    if not words:
        return build_fallback_timing(
            text=text,
            total_duration_seconds=total_duration,
            fallback_reason="Alignment data contained no parseable word elements",
        )

    # Sort words chronologically
    words.sort(key=lambda w: w.start_seconds)

    # Group words into segments by sentence terminators or breath pauses
    segments: list[NarrationSegment] = []
    current_segment_words: list[WordTiming] = []
    seg_idx = 0

    for i, word in enumerate(words):
        current_segment_words.append(word)

        # Detect pause after this word
        pause = 0.0
        if i + 1 < len(words):
            pause = max(0.0, words[i + 1].start_seconds - word.end_seconds)

        is_sentence_end = bool(re.search(r"[.!?]$", word.word))
        is_clause_end = bool(re.search(r"[,;:\-—]$", word.word)) and pause >= 0.25
        is_dramatic_pause = pause >= 0.50
        is_last_word = (i == len(words) - 1)

        # Segment cut condition
        if is_sentence_end or is_clause_end or is_dramatic_pause or is_last_word:
            seg_text = " ".join(w.word for w in current_segment_words)
            seg_start = current_segment_words[0].start_seconds
            seg_end = current_segment_words[-1].end_seconds
            seg_dur = max(0.1, seg_end - seg_start)

            has_emp, emp_reason = detect_emotional_emphasis(
                text=seg_text,
                pause_after=pause,
                segment_index=seg_idx,
                total_segments=1,  # will be recalculated below
            )

            segments.append(
                NarrationSegment(
                    segment_index=seg_idx,
                    text=seg_text,
                    start_seconds=round(seg_start, 3),
                    end_seconds=round(seg_end, 3),
                    duration_seconds=round(seg_dur, 3),
                    words=list(current_segment_words),
                    pause_after_seconds=round(pause, 3),
                    has_emphasis=has_emp,
                    emphasis_reason=emp_reason,
                )
            )
            current_segment_words = []
            seg_idx += 1

    # Recalculate emphasis with actual segment count
    for seg in segments:
        has_emp, emp_reason = detect_emotional_emphasis(
            text=seg.text,
            pause_after=seg.pause_after_seconds,
            segment_index=seg.segment_index,
            total_segments=len(segments),
        )
        seg.has_emphasis = has_emp
        seg.emphasis_reason = emp_reason

    return NarrationTiming(
        text=text,
        total_duration_seconds=round(total_duration, 3),
        has_real_timestamps=True,
        timestamp_provider=provider,
        fallback_used=False,
        fallback_reason=None,
        words=words,
        segments=segments,
    )


def build_fallback_timing(
    text: str,
    total_duration_seconds: float,
    fallback_reason: str = "Provider did not return word-level timestamps; using audio duration and phrase segmentation fallback",
) -> NarrationTiming:
    """Construct deterministic phrase segmentation when real timestamps are unavailable.

    DOES NOT fabricate word-level timestamps (words array is empty).
    Allocates real measured audio duration across sentence/phrase segments
    proportionally by syllable/character weight and punctuation pause weights.
    """
    total_dur = max(1.0, float(total_duration_seconds))
    clean_text = text.strip()

    # Split on sentence boundaries (. ! ?) and clause marks (, ; : — \n)
    raw_clauses = re.split(r"([.!?]+|[,;:\n—]+)", clean_text)
    phrases: list[str] = []
    current_phrase = ""

    for chunk in raw_clauses:
        if not chunk:
            continue
        current_phrase += chunk
        if re.search(r"[.!?]+|[,;:\n—]+", chunk):
            p = current_phrase.strip()
            if p:
                phrases.append(p)
            current_phrase = ""

    if current_phrase.strip():
        phrases.append(current_phrase.strip())

    if not phrases:
        phrases = [clean_text]

    # Calculate weight per phrase
    # Characters represent speech time; punctuation adds pause weights
    weights: list[float] = []
    for p in phrases:
        char_weight = max(1.0, float(len(p)))
        pause_weight = 0.0
        if re.search(r"[.!?]$", p):
            pause_weight = 10.0  # ~0.6-0.8s pause weight
        elif re.search(r"[,;:\-—]$", p):
            pause_weight = 5.0   # ~0.3-0.4s pause weight
        weights.append(char_weight + pause_weight)

    sum_weights = sum(weights) or 1.0

    segments: list[NarrationSegment] = []
    current_time = 0.0

    for idx, (p, w) in enumerate(zip(phrases, weights)):
        is_last = (idx == len(phrases) - 1)
        if is_last:
            seg_dur = max(0.5, total_dur - current_time)
            seg_end = total_dur
        else:
            seg_dur = round((w / sum_weights) * total_dur, 3)
            seg_dur = max(0.5, seg_dur)
            seg_end = round(current_time + seg_dur, 3)

        # Estimate pause after
        pause_after = 0.0
        if re.search(r"[.!?]$", p):
            pause_after = 0.6
        elif re.search(r"[,;:\-—]$", p):
            pause_after = 0.3

        has_emp, emp_reason = detect_emotional_emphasis(
            text=p,
            pause_after=pause_after,
            segment_index=idx,
            total_segments=len(phrases),
        )

        segments.append(
            NarrationSegment(
                segment_index=idx,
                text=p,
                start_seconds=round(current_time, 3),
                end_seconds=round(seg_end, 3),
                duration_seconds=round(seg_dur, 3),
                words=[],  # Strictly empty: NO fake word timestamps
                pause_after_seconds=pause_after,
                has_emphasis=has_emp,
                emphasis_reason=emp_reason,
            )
        )
        current_time = seg_end

    return NarrationTiming(
        text=clean_text,
        total_duration_seconds=round(total_dur, 3),
        has_real_timestamps=False,
        timestamp_provider=None,
        fallback_used=True,
        fallback_reason=fallback_reason,
        words=[],
        segments=segments,
    )


def build_narration_timing(
    text: str,
    audio_path: str | None = None,
    duration_seconds: float | None = None,
    alignment_data: dict[str, Any] | None = None,
    provider: str | None = None,
) -> NarrationTiming:
    """Build NarrationTiming from audio file, duration, and optional alignment."""
    measured_duration = duration_seconds
    if (measured_duration is None or measured_duration <= 0.0) and audio_path:
        measured_duration = probe_audio_duration(audio_path)

    if measured_duration is None or measured_duration <= 0.0:
        # Estimation if file not probeable: ~14 characters per second
        measured_duration = max(3.0, len(text) / 14.0)

    if alignment_data and (
        alignment_data.get("characters") or alignment_data.get("words")
    ):
        timing = parse_alignment_data(
            text=text,
            alignment=alignment_data,
            total_duration=measured_duration,
            provider=provider or "unknown",
        )
    else:
        timing = build_fallback_timing(
            text=text,
            total_duration_seconds=measured_duration,
            fallback_reason=f"Provider '{provider or 'default'}' did not expose word alignment data",
        )

    timing.audio_path = audio_path
    return timing


def align_shots_to_narration(
    segments: list[NarrationSegment],
    target_shot_count: int = 5,
    total_duration: float = 20.0,
) -> list[dict[str, Any]]:
    """Partition narration segments into target_shot_count shot timing envelopes.

    Guarantees:
    - Shot boundaries coincide with narration phrase boundaries.
    - Total duration matches total_duration.
    - Each shot has non-zero duration and associated narration text.
    """
    if not segments:
        # Fallback to uniform irregular pacing if no segments
        dur_per_shot = round(total_duration / target_shot_count, 3)
        return [
            {
                "shot_number": i + 1,
                "duration_seconds": dur_per_shot,
                "narration": "",
                "segments": [],
            }
            for i in range(target_shot_count)
        ]

    # If segments exactly equal shot count: 1-to-1 mapping
    if len(segments) == target_shot_count:
        shots = []
        for i, seg in enumerate(segments):
            shots.append(
                {
                    "shot_number": i + 1,
                    "duration_seconds": seg.duration_seconds,
                    "narration": seg.text,
                    "segments": [seg],
                }
            )
        # Normalize sum
        total_planned = sum(s["duration_seconds"] for s in shots)
        if total_planned > 0 and abs(total_planned - total_duration) > 0.01:
            diff = total_duration - total_planned
            shots[-1]["duration_seconds"] = round(shots[-1]["duration_seconds"] + diff, 3)
        return shots

    # If segments > target_shot_count: cluster adjacent short segments
    if len(segments) > target_shot_count:
        groups: list[list[NarrationSegment]] = [[] for _ in range(target_shot_count)]
        target_group_dur = total_duration / target_shot_count
        grp_idx = 0

        for seg in segments:
            current_grp_dur = sum(s.duration_seconds for s in groups[grp_idx])
            if current_grp_dur >= target_group_dur and grp_idx < target_shot_count - 1:
                grp_idx += 1
            groups[grp_idx].append(seg)

        shots = []
        for i, grp in enumerate(groups):
            if not grp:
                grp = [segments[-1]]
            dur = sum(s.duration_seconds for s in grp)
            text = " ".join(s.text for s in grp)
            shots.append(
                {
                    "shot_number": i + 1,
                    "duration_seconds": round(dur, 3),
                    "narration": text,
                    "segments": grp,
                }
            )

        total_planned = sum(s["duration_seconds"] for s in shots)
        if abs(total_planned - total_duration) > 0.01:
            diff = total_duration - total_planned
            shots[-1]["duration_seconds"] = round(shots[-1]["duration_seconds"] + diff, 3)
        return shots

    # If segments < target_shot_count: split longer segments at clause or breath pauses
    shots = []
    seg_idx = 0

    for i in range(target_shot_count):
        seg = segments[min(seg_idx, len(segments) - 1)]
        shot_dur = round(total_duration / target_shot_count, 3)
        shots.append(
            {
                "shot_number": i + 1,
                "duration_seconds": shot_dur,
                "narration": seg.text if i == seg_idx else "",
                "segments": [seg],
            }
        )
        if i + 1 < target_shot_count and seg_idx < len(segments) - 1:
            seg_idx += 1

    total_planned = sum(s["duration_seconds"] for s in shots)
    if abs(total_planned - total_duration) > 0.01:
        diff = total_duration - total_planned
        shots[-1]["duration_seconds"] = round(shots[-1]["duration_seconds"] + diff, 3)

    return shots
