"""Unit tests for deterministic caption models, segmentation, and burn-in engine."""

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from app.core.captions import (
    _CAPTION_EMPHASIS_WORDS,
    build_caption_timeline,
    generate_srt_content,
    render_caption_card,
)
from app.schemas.cinematic import (
    CaptionSegment,
    CaptionStyle,
    CaptionTimeline,
    NarrationSegment,
    NarrationTiming,
    WordTiming,
)


def test_caption_segment_model_validation():
    seg = CaptionSegment(
        segment_index=0,
        text="The mirror was NOT empty.",
        start_seconds=1.2,
        end_seconds=3.5,
        duration_seconds=2.3,
        has_emphasis=True,
        emphasis_words=["NOT"],
        line_count=1,
    )
    assert seg.segment_index == 0
    assert seg.text == "The mirror was NOT empty."
    assert seg.has_emphasis is True
    assert seg.emphasis_words == ["NOT"]
    assert seg.duration_seconds == 2.3


def test_caption_style_defaults():
    style = CaptionStyle()
    assert style.font_size == 48
    assert style.max_chars_per_line == 34
    assert style.max_lines == 2
    assert style.min_duration_seconds == 0.8
    assert style.max_duration_seconds == 4.5
    assert style.placement == "lower_third"


def test_caption_timeline_from_real_word_timestamps():
    words = [
        WordTiming(word="At", start_seconds=0.0, end_seconds=0.2),
        WordTiming(word="the", start_seconds=0.2, end_seconds=0.4),
        WordTiming(word="bottom", start_seconds=0.4, end_seconds=0.8),
        WordTiming(word="of", start_seconds=0.8, end_seconds=1.0),
        WordTiming(word="the", start_seconds=1.0, end_seconds=1.2),
        WordTiming(word="ocean,", start_seconds=1.2, end_seconds=1.7),
        WordTiming(word="something", start_seconds=2.1, end_seconds=2.6),
        WordTiming(word="impossible", start_seconds=2.6, end_seconds=3.2),
        WordTiming(word="survives.", start_seconds=3.2, end_seconds=3.8),
    ]
    timing = NarrationTiming(
        text="At the bottom of the ocean, something impossible survives.",
        total_duration_seconds=4.0,
        has_real_timestamps=True,
        words=words,
        segments=[],
    )

    timeline = build_caption_timeline(timing, video_duration=4.0)
    assert isinstance(timeline, CaptionTimeline)
    assert len(timeline.segments) >= 2

    # Check first segment: "At the bottom of the ocean,"
    seg1 = timeline.segments[0]
    assert "ocean" in seg1.text.lower()
    assert seg1.start_seconds == 0.0
    assert seg1.end_seconds <= 2.1

    # Check second segment: contains emphasis "impossible"
    seg2 = timeline.segments[1]
    assert "impossible" in seg2.text.lower()
    assert seg2.has_emphasis is True
    assert "impossible" in [w.lower() for w in seg2.emphasis_words]


def test_caption_timeline_from_fallback_segments():
    n_segments = [
        NarrationSegment(
            segment_index=0,
            text="The ancient grandfather clock ticked in the darkness.",
            start_seconds=0.0,
            end_seconds=4.0,
            duration_seconds=4.0,
            words=[],
            pause_after_seconds=0.5,
        ),
        NarrationSegment(
            segment_index=1,
            text="The mirror was NOT empty.",
            start_seconds=4.5,
            end_seconds=7.0,
            duration_seconds=2.5,
            words=[],
            has_emphasis=True,
        ),
    ]
    timing = NarrationTiming(
        text="The ancient grandfather clock ticked in the darkness. The mirror was NOT empty.",
        total_duration_seconds=7.0,
        has_real_timestamps=False,
        words=[],
        segments=n_segments,
    )

    timeline = build_caption_timeline(timing, video_duration=7.5)
    assert len(timeline.segments) >= 2

    # Ensure none extend past video duration
    for s in timeline.segments:
        assert s.start_seconds >= 0.0
        assert s.end_seconds <= 7.5
        assert s.start_seconds < s.end_seconds
        assert len(s.text.split("\n")) <= 2
        for line in s.text.split("\n"):
            assert len(line) <= 45


def test_caption_timeline_clamps_to_video_duration():
    n_segments = [
        NarrationSegment(
            segment_index=0,
            text="A cold wind howled across the deserted moors.",
            start_seconds=0.0,
            end_seconds=6.0,
            duration_seconds=6.0,
            words=[],
        )
    ]
    timing = NarrationTiming(
        text="A cold wind howled across the deserted moors.",
        total_duration_seconds=6.0,
        has_real_timestamps=False,
        words=[],
        segments=n_segments,
    )

    timeline = build_caption_timeline(timing, video_duration=4.5)
    for s in timeline.segments:
        assert s.end_seconds <= 4.5


def test_generate_srt_content():
    timeline = CaptionTimeline(
        video_duration_seconds=5.0,
        segments=[
            CaptionSegment(
                segment_index=0,
                text="The door slowly opened.",
                start_seconds=0.5,
                end_seconds=2.5,
                duration_seconds=2.0,
            ),
            CaptionSegment(
                segment_index=1,
                text="Nobody was there.",
                start_seconds=2.8,
                end_seconds=4.5,
                duration_seconds=1.7,
            ),
        ],
    )
    srt = generate_srt_content(timeline)
    assert "1\n00:00:00,500 --> 00:00:02,500\nThe door slowly opened." in srt
    assert "2\n00:00:02,800 --> 00:00:04,500\nNobody was there." in srt


def test_render_caption_card():
    seg = CaptionSegment(
        segment_index=0,
        text="The mirror was NOT empty.",
        start_seconds=1.0,
        end_seconds=3.0,
        duration_seconds=2.0,
        has_emphasis=True,
        emphasis_words=["NOT"],
    )
    img = render_caption_card(seg, video_width=1080, video_height=1920)
    assert isinstance(img, Image.Image)
    assert img.size == (1080, 1920)
    assert img.mode == "RGBA"


def test_caption_timeline_words_exceeding_video_duration_never_negative_duration():
    """When narration timing contains words starting after video ends, no negative duration is emitted."""
    words = [
        WordTiming(word="Inside", start_seconds=1.0, end_seconds=2.0),
        WordTiming(word="the", start_seconds=2.0, end_seconds=3.0),
        WordTiming(word="cellar", start_seconds=3.0, end_seconds=4.0),
        WordTiming(word="something", start_seconds=12.5, end_seconds=13.5),
        WordTiming(word="whispered.", start_seconds=13.5, end_seconds=14.5),
    ]
    timing = NarrationTiming(
        text="Inside the cellar something whispered.",
        total_duration_seconds=15.0,
        has_real_timestamps=True,
        words=words,
        segments=[],
    )
    # Video duration is only 10.0s (shorter than the last two words)
    timeline = build_caption_timeline(timing, video_duration=10.0)
    assert isinstance(timeline, CaptionTimeline)
    for seg in timeline.segments:
        assert seg.duration_seconds > 0
        assert seg.start_seconds < 10.0
        assert seg.end_seconds <= 10.0

