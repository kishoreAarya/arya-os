"""python
VideoAssembler — assembles multiple generated shot videos into one
final publishable video.

This is a transitional abstraction.  The current implementation simply
selects the last generated clip; a future iteration will invoke
FFmpeg to concatenate, cross-fade, and add audio tracks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

    Current implementation (pass-through): returns the last video clip
    from the summary.  FFmpeg-based concatenation will be wired in
    later without changing the public interface.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def assemble(self, summary: ShotExecutionSummary) -> VideoAssemblyResult:
        """Select the final video from the shot execution summary.

        Args:
            summary: The aggregated output of ShotExecutor.

        Returns:
            VideoAssemblyResult with the selected clip metadata.
        """
        if summary is None:
            logger.warning("video_assembler_empty_summary")
            return VideoAssemblyResult(
                success=False,
                error="ShotExecutionSummary is None",
            )

        # Derive video paths from the per-shot results.
        video_paths = summary.video_clips

        clip_count = len(video_paths)

        if clip_count == 0:
            logger.warning("video_assembler_no_clips")
            return VideoAssemblyResult(
                success=False,
                error="No video clips found in ShotExecutionSummary",
            )

        final_video_path = video_paths[-1]

        logger.info(
            "video_assembler_completed",
            clip_count=clip_count,
            final_video_path=final_video_path,
            duration_seconds=summary.total_duration,
        )

        return VideoAssemblyResult(
            final_video_path=final_video_path,
            clip_count=clip_count,
            duration_seconds=summary.total_duration,
            success=True,
        )
