"""Unit tests for audio timing, alignment parsing, and phrase segmentation.

Covers Section 16 requirements:
- Voice timing (valid, malformed, missing timestamps, duration, word ordering)
- Segmentation (sentence boundaries, punctuation, pause detection, phrase grouping, dramatic pauses)
"""

import pytest
from app.core.audio_timing import (
    align_shots_to_narration,
    build_fallback_timing,
    build_narration_timing,
    detect_emotional_emphasis,
    parse_alignment_data,
)
from app.schemas.cinematic import NarrationTiming, WordTiming


def test_valid_timestamps_parsing():
    """Verify ElevenLabs character alignment format parses into NarrationTiming."""
    # Characters: "Deep under the sea."
    text = "Deep under the sea."
    chars = list(text)
    # Simulate realistic character timestamps
    starts = [0.0 + i * 0.08 for i in range(len(chars))]
    ends = [s + 0.08 for s in starts]
    # Add a natural pause after "Deep"
    starts[5] = 0.6  # "u" in "under"
    for i in range(6, len(chars)):
        starts[i] = starts[i - 1] + 0.08
        ends[i] = starts[i] + 0.08

    alignment = {
        "characters": chars,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }

    timing = parse_alignment_data(
        text=text,
        alignment=alignment,
        total_duration=3.5,
        provider="elevenlabs",
    )

    assert isinstance(timing, NarrationTiming)
    assert timing.has_real_timestamps is True
    assert timing.fallback_used is False
    assert timing.timestamp_provider == "elevenlabs"
    assert len(timing.words) == 4
    assert [w.word for w in timing.words] == ["Deep", "under", "the", "sea."]
    assert timing.words[0].start_seconds == 0.0
    assert timing.words[0].end_seconds > 0.0
    assert timing.total_duration_seconds == 3.5


def test_malformed_timestamps_graceful_handling():
    """Mismatched array lengths or corrupt data degrades gracefully to fallback without throwing."""
    text = "Something went wrong with the alignment data."
    alignment = {
        "characters": ["A", "B", "C"],
        "character_start_times_seconds": [0.0, 0.1],  # mismatched length
        "character_end_times_seconds": [0.1, 0.2, 0.3],
    }

    timing = build_narration_timing(
        text=text,
        duration_seconds=5.0,
        alignment_data=alignment,
        provider="elevenlabs",
    )

    assert isinstance(timing, NarrationTiming)
    assert timing.has_real_timestamps is False
    assert timing.fallback_used is True
    assert timing.words == []  # Never fabricates fake word timestamps
    assert len(timing.segments) >= 1
    assert timing.total_duration_seconds == 5.0


def test_missing_timestamps_fallback():
    """When provider returns no alignment, system gracefully builds fallback segmentation."""
    text = "In the dark of night. The impossible happened."
    timing = build_narration_timing(
        text=text,
        duration_seconds=6.0,
        alignment_data=None,
        provider="replicate",
    )

    assert timing.has_real_timestamps is False
    assert timing.fallback_used is True
    assert timing.words == []  # Strictly empty: NO fake word timestamps
    assert len(timing.segments) == 2
    assert "In the dark of night." in timing.segments[0].text
    assert "The impossible happened." in timing.segments[1].text
    assert timing.total_duration_seconds == 6.0
    assert timing.segments[-1].end_seconds == 6.0


def test_word_ordering():
    """Unsorted input words are ordered chronologically."""
    text = "one two three"
    alignment = {
        "words": [
            {"word": "three", "start": 1.5, "end": 2.0},
            {"word": "one", "start": 0.0, "end": 0.5},
            {"word": "two", "start": 0.6, "end": 1.0},
        ]
    }

    timing = parse_alignment_data(text=text, alignment=alignment, total_duration=2.5)
    assert [w.word for w in timing.words] == ["one", "two", "three"]
    assert timing.words[0].start_seconds == 0.0
    assert timing.words[1].start_seconds == 0.6
    assert timing.words[2].start_seconds == 1.5


def test_sentence_boundary_segmentation():
    """Text with multiple sentences splits into distinct segments."""
    text = "First sentence here. Second sentence follows! Third question appears?"
    timing = build_fallback_timing(text=text, total_duration_seconds=12.0)

    assert len(timing.segments) == 3
    assert "First sentence" in timing.segments[0].text
    assert "Second sentence" in timing.segments[1].text
    assert "Third question" in timing.segments[2].text
    assert sum(s.duration_seconds for s in timing.segments) == pytest.approx(12.0, abs=0.01)


def test_punctuation_clause_segmentation():
    """Commas and semicolons create natural rhythm clauses in fallback segmentation."""
    text = "Beneath the ice, where light never reaches, an ancient relic glows."
    timing = build_fallback_timing(text=text, total_duration_seconds=9.0)

    assert len(timing.segments) >= 2
    assert timing.segments[0].start_seconds == 0.0
    assert timing.segments[-1].end_seconds == 9.0


def test_pause_detection_and_dramatic_pauses():
    """Dramatic pauses (>= 0.45s) are flagged with emotional emphasis."""
    has_emp, reason = detect_emotional_emphasis("Hold your breath.", pause_after=0.6, segment_index=0, total_segments=3)
    assert has_emp is True
    assert reason == "dramatic_pause"

    has_emp2, reason2 = detect_emotional_emphasis("A terrifying truth!", pause_after=0.1, segment_index=1, total_segments=3)
    assert has_emp2 is True
    assert reason2 == "punctuation_emphasis"

    has_emp3, reason3 = detect_emotional_emphasis("The shadow moved.", pause_after=0.1, segment_index=1, total_segments=3)
    assert has_emp3 is True
    assert "semantic_emphasis" in reason3


def test_phrase_grouping_align_shots():
    """align_shots_to_narration distributes segments across target shots preserving total duration."""
    timing = build_fallback_timing(
        text="A quiet village slept. But deep in the woods, a beast stirred. Nobody heard the scream.",
        total_duration_seconds=20.0,
    )
    shots = align_shots_to_narration(timing.segments, target_shot_count=5, total_duration=20.0)

    assert len(shots) == 5
    assert sum(s["duration_seconds"] for s in shots) == pytest.approx(20.0, abs=0.01)
    for s in shots:
        assert s["duration_seconds"] > 0.0
