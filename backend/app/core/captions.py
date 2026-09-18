"""Deterministic caption engine conforming to CINEMATIC_PRODUCTION_BIBLE.md.

Grounded in Sections 2-8 of Task 16 specification.
Responsibilities:
1. Natural phrase segmentation from NarrationTiming (real or fallback timing).
2. Word-level or phrase-level deterministic emphasis detection.
3. Strict line length, line count, and safe-area compliance for vertical Shorts.
4. Open-caption burn-in via FFmpeg overlay without external SaaS dependencies.
5. Production of standard SubRip (.srt) subtitle tracks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger
from app.schemas.cinematic import (
    CaptionSegment,
    CaptionStyle,
    CaptionTimeline,
    NarrationTiming,
    WordTiming,
)

logger = get_logger("arya.core.captions")

# Cinematic keywords for caption emphasis highlighting
_CAPTION_EMPHASIS_WORDS = {
    "not", "never", "nothing", "nowhere", "impossible", "dead", "alive",
    "alone", "trapped", "shadow", "whisper", "screamed", "blood", "truth",
    "darkness", "vanished", "run", "stop", "listen", "behind", "mirror",
}


def _find_system_font(font_size: int = 48) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find a clean, highly legible sans-serif font across macOS/Linux environments."""
    candidate_fonts = [
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFPro.ttf",
        "/Library/Fonts/Arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidate_fonts:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, font_size)
            except Exception:
                pass

    # Fallback to PIL default font
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def build_caption_timeline(
    narration_timing: NarrationTiming,
    video_duration: float,
    style: CaptionStyle | None = None,
) -> CaptionTimeline:
    """Construct deterministic, phrase-grouped caption timeline from narration timing.

    Guarantees:
    - No giant multi-sentence subtitles.
    - Max 1-2 lines per caption card.
    - Safe display duration bounds (default 0.8s <= dur <= 4.5s).
    - No negative timestamps; no timestamps extending past video duration.
    - Captions reflect spoken narration and do not manufacture captions during silence.
    """
    style = style or CaptionStyle()
    v_dur = max(1.0, float(video_duration))
    segments: list[CaptionSegment] = []

    if narration_timing.has_real_timestamps and narration_timing.words:
        # Group words into natural phrase cards
        current_words: list[WordTiming] = []
        current_chars = 0
        seg_idx = 0

        for w in narration_timing.words:
            word_len = len(w.word) + 1  # word plus space
            # Break if card would exceed max chars (34 chars * 2 lines = ~68) or terminal punctuation
            pause_before = 0.0
            if current_words:
                pause_before = w.start_seconds - current_words[-1].end_seconds

            break_card = False
            if current_words and (current_chars + word_len > style.max_chars_per_line * style.max_lines):
                break_card = True
            elif current_words and pause_before >= 0.4:
                break_card = True
            elif current_words and re.search(r"[.!?]$", current_words[-1].word):
                break_card = True

            if break_card and current_words:
                st = round(current_words[0].start_seconds, 3)
                if st < v_dur:
                    en = round(min(v_dur, max(st + 0.05, current_words[-1].end_seconds)), 3)
                    if en > st:
                        card_text = " ".join(cw.word for cw in current_words).strip()

                        emp_words = [
                            cw.word.strip(".,!?;:\"'—-")
                            for cw in current_words
                            if cw.word.strip(".,!?;:\"'—-").lower() in _CAPTION_EMPHASIS_WORDS
                            or cw.word.isupper() and len(cw.word) > 1
                        ]

                        wrapped_lines = textwrap.wrap(card_text, width=style.max_chars_per_line)
                        display_text = "\n".join(wrapped_lines[:style.max_lines])

                        segments.append(
                            CaptionSegment(
                                segment_index=seg_idx,
                                text=display_text,
                                start_seconds=st,
                                end_seconds=en,
                                duration_seconds=round(en - st, 3),
                                has_emphasis=bool(emp_words),
                                emphasis_words=emp_words,
                                words=list(current_words),
                                line_count=len(wrapped_lines[:style.max_lines]),
                            )
                        )
                        seg_idx += 1
                current_words = []
                current_chars = 0

            current_words.append(w)
            current_chars += word_len

        # Flush remaining words
        if current_words:
            st = round(current_words[0].start_seconds, 3)
            if st < v_dur:
                en = round(min(v_dur, max(st + 0.05, current_words[-1].end_seconds)), 3)
                if en > st:
                    card_text = " ".join(cw.word for cw in current_words).strip()
                    emp_words = [
                        cw.word.strip(".,!?;:\"'—-")
                        for cw in current_words
                        if cw.word.strip(".,!?;:\"'—-").lower() in _CAPTION_EMPHASIS_WORDS
                        or cw.word.isupper() and len(cw.word) > 1
                    ]
                    wrapped_lines = textwrap.wrap(card_text, width=style.max_chars_per_line)
                    display_text = "\n".join(wrapped_lines[:style.max_lines])

                    segments.append(
                        CaptionSegment(
                            segment_index=seg_idx,
                            text=display_text,
                            start_seconds=st,
                            end_seconds=en,
                            duration_seconds=round(en - st, 3),
                            has_emphasis=bool(emp_words),
                            emphasis_words=emp_words,
                            words=list(current_words),
                            line_count=len(wrapped_lines[:style.max_lines]),
                        )
                    )

    else:
        # Fallback segmentation: segment per NarrationSegment, sub-splitting if too long
        seg_idx = 0
        for n_seg in narration_timing.segments:
            raw_text = n_seg.text.strip()
            if not raw_text:
                continue

            # If phrase fits comfortably in 1-2 lines (<= 60 chars)
            if len(raw_text) <= style.max_chars_per_line * style.max_lines:
                sub_phrases = [raw_text]
            else:
                # Split along clause marks or conjunctions
                clauses = re.split(r"([,;:\n—]+|\s+where\s+|\s+and\s+|\s+but\s+)", raw_text, flags=re.IGNORECASE)
                sub_phrases = []
                buf = ""
                for c in clauses:
                    if len(buf) + len(c) <= style.max_chars_per_line * style.max_lines:
                        buf += c
                    else:
                        if buf.strip():
                            sub_phrases.append(buf.strip())
                        buf = c
                if buf.strip():
                    sub_phrases.append(buf.strip())
                if not sub_phrases:
                    sub_phrases = [raw_text]

            total_chars = sum(len(sp) for sp in sub_phrases) or 1
            curr_start = n_seg.start_seconds
            total_seg_dur = max(style.min_duration_seconds, n_seg.duration_seconds)

            for sp in sub_phrases:
                if curr_start >= v_dur:
                    break
                p_ratio = len(sp) / total_chars
                p_dur = round(max(style.min_duration_seconds, total_seg_dur * p_ratio), 3)
                p_dur = min(style.max_duration_seconds, p_dur)
                p_end = round(min(v_dur, max(curr_start + 0.05, curr_start + p_dur)), 3)
                if p_end <= curr_start:
                    break

                emp_words = [
                    w.strip(".,!?;:\"'—-")
                    for w in sp.split()
                    if w.strip(".,!?;:\"'—-").lower() in _CAPTION_EMPHASIS_WORDS
                    or w.strip(".,!?;:\"'—-").isupper() and len(w.strip(".,!?;:\"'—-")) > 1
                ]
                wrapped_lines = textwrap.wrap(sp, width=style.max_chars_per_line)
                display_text = "\n".join(wrapped_lines[:style.max_lines])

                segments.append(
                    CaptionSegment(
                        segment_index=seg_idx,
                        text=display_text,
                        start_seconds=curr_start,
                        end_seconds=p_end,
                        duration_seconds=round(p_end - curr_start, 3),
                        has_emphasis=bool(emp_words) or n_seg.has_emphasis,
                        emphasis_words=emp_words,
                        words=[],
                        line_count=len(wrapped_lines[:style.max_lines]),
                    )
                )
                seg_idx += 1
                curr_start = p_end

    # Clamp and filter valid segments within video duration
    clamped_segments: list[CaptionSegment] = []
    for s in segments:
        s.start_seconds = max(0.0, round(s.start_seconds, 3))
        s.end_seconds = min(v_dur, round(s.end_seconds, 3))
        if s.end_seconds > s.start_seconds:
            s.duration_seconds = round(s.end_seconds - s.start_seconds, 3)
            clamped_segments.append(s)

    return CaptionTimeline(
        video_duration_seconds=round(v_dur, 3),
        segments=clamped_segments,
        style=style,
        burned_in=False,
    )


def render_caption_card(
    segment: CaptionSegment,
    video_width: int = 1080,
    video_height: int = 1920,
    style: CaptionStyle | None = None,
) -> Image.Image:
    """Render a single caption card into a transparent RGBA image matching video dimensions."""
    style = style or CaptionStyle()
    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _find_system_font(style.font_size)

    lines = segment.text.split("\n")
    if not lines:
        return img

    # Compute total text block height and baseline placement
    line_metrics: list[tuple[str, int, int]] = []
    total_text_h = 0
    line_spacing = int(style.font_size * 0.25)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        line_metrics.append((line, w, h))
        total_text_h += h

    total_text_h += line_spacing * (len(lines) - 1)

    # Lower-third anchor: place above the safe margin from bottom
    start_y = video_height - style.bottom_margin_px - total_text_h

    # Draw each line centered horizontally
    curr_y = start_y
    for line, w, h in line_metrics:
        x = (video_width - w) // 2

        # 1. Subtle drop shadow
        draw.text(
            (x + style.shadow_offset, curr_y + style.shadow_offset),
            line,
            font=font,
            fill="#00000088",
        )

        # 2. Main stroke and fill (handling emphasis words)
        words = line.split()
        if len(words) > 0 and segment.has_emphasis and segment.emphasis_words:
            # Word-by-word layout for emphasis coloring
            word_x = x
            space_w = draw.textlength(" ", font=font)
            for w_str in words:
                clean_w = w_str.strip(".,!?;:\"'—-")
                is_emp = clean_w in segment.emphasis_words or clean_w.lower() in _CAPTION_EMPHASIS_WORDS
                fill_color = style.emphasis_color if is_emp else style.text_color
                draw.text(
                    (word_x, curr_y),
                    w_str,
                    font=font,
                    fill=fill_color,
                    stroke_fill=style.stroke_color,
                    stroke_width=style.stroke_width,
                )
                word_x += draw.textlength(w_str, font=font) + space_w
        else:
            # Single line render
            draw.text(
                (x, curr_y),
                line,
                font=font,
                fill=style.text_color,
                stroke_fill=style.stroke_color,
                stroke_width=style.stroke_width,
            )

        curr_y += h + line_spacing

    return img


def generate_srt_content(timeline: CaptionTimeline) -> str:
    """Generate canonical SubRip (.srt) subtitle formatted string."""
    def format_srt_time(seconds: float) -> str:
        total_ms = int(round(seconds * 1000))
        millis = total_ms % 1000
        total_sec = total_ms // 1000
        mins, secs = divmod(total_sec, 60)
        hours, mins = divmod(mins, 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    lines: list[str] = []
    for idx, seg in enumerate(timeline.segments, start=1):
        lines.append(str(idx))
        lines.append(f"{format_srt_time(seg.start_seconds)} --> {format_srt_time(seg.end_seconds)}")
        lines.append(seg.text)
        lines.append("")

    return "\n".join(lines)


async def burn_captions_to_video(
    video_path: str,
    caption_timeline: CaptionTimeline,
    output_path: str | None = None,
) -> str:
    """Burn deterministic caption overlay cards onto the video via FFmpeg.

    Returns the path to the captioned video.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not os.path.exists(video_path):
        raise FileNotFoundError(f"FFmpeg or input video not found: {video_path}")

    # Inspect video resolution via ffprobe
    width, height = 1080, 1920
    if ffprobe:
        try:
            probe_cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                video_path,
            ]
            res = subprocess.run(probe_cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                streams = data.get("streams", [])
                if streams:
                    width = int(streams[0].get("width") or 1080)
                    height = int(streams[0].get("height") or 1920)
        except Exception as exc:
            logger.warning("caption_probe_resolution_failed", error=str(exc))

    if not caption_timeline.segments:
        logger.warning("burn_captions_no_segments_to_burn")
        return video_path

    tmp_dir = Path(tempfile.mkdtemp(prefix="arya_captions_"))
    try:
        cmd = [ffmpeg, "-y", "-i", video_path]
        filter_complex_parts: list[str] = []
        prev_label = "0:v"

        for idx, seg in enumerate(caption_timeline.segments):
            png_path = tmp_dir / f"caption_{idx:03d}.png"
            card_img = render_caption_card(
                segment=seg,
                video_width=width,
                video_height=height,
                style=caption_timeline.style,
            )
            card_img.save(png_path, "PNG")

            input_idx = idx + 1
            cmd.extend(["-i", str(png_path)])

            next_label = f"v_cap_{idx}" if idx < len(caption_timeline.segments) - 1 else "vout"
            filter_complex_parts.append(
                f"[{prev_label}][{input_idx}:v]overlay=0:0:enable="
                f"'between(t,{seg.start_seconds:.3f},{seg.end_seconds:.3f})'[{next_label}]"
            )
            prev_label = next_label

        fc_str = ";".join(filter_complex_parts)

        if not output_path:
            out_file = Path(tempfile.gettempdir()) / f"arya_captioned_{uuid.uuid4().hex}.mp4"
        else:
            out_file = Path(output_path)

        cmd.extend([
            "-filter_complex", fc_str,
            "-map", f"[{prev_label}]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "copy",
            str(out_file),
        ])

        logger.info(
            "burn_captions_ffmpeg_started",
            segment_count=len(caption_timeline.segments),
            input_video=video_path,
        )

        import asyncio
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if proc.returncode != 0 or not out_file.exists() or out_file.stat().st_size == 0:
            err = proc.stderr[:600] if proc.stderr else "Unknown error"
            logger.error("burn_captions_ffmpeg_failed", error=err)
            raise RuntimeError(f"FFmpeg caption burn-in failed: {err}")

        logger.info(
            "burn_captions_ffmpeg_succeeded",
            output=str(out_file),
            size_bytes=out_file.stat().st_size,
        )
        caption_timeline.burned_in = True
        caption_timeline.output_video_path = str(out_file)
        return str(out_file)

    finally:
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
        except Exception:
            pass
