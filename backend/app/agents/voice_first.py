"""VoiceFirstAgent — generates full voiceover and provides timestamps.

This is the foundation of the voice-first workflow. Everything else
(video, images, assembly) syncs to this voice track.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.providers.capabilities import Capability
from app.providers.media_dispatch import build_media_generation_call
from app.services.execution_engine import ExecutionEngine


@dataclass
class VoiceSegment:
    text: str
    start_time: float
    end_time: float


@dataclass
class VoiceFirstResult:
    voice_path: str | None
    duration_seconds: float
    segments: list[VoiceSegment] = field(default_factory=list)


class VoiceFirstAgent(BaseAgent):
    name = "voice_first"

    def __init__(self, db: AsyncSession):
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict) -> AgentResult:
        script_content = context.get("script_content")
        if not script_content or not str(script_content).strip():
            return AgentResult(
                success=False,
                error="context.script_content is required and was empty",
            )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TTS,
            call=build_media_generation_call(
                capability=Capability.TTS,
                prompt=script_content,
            ),
            workflow_run_id=context.get("workflow_run_id"),
            stage="voice_first_generation",
        )

        if not exec_result.success:
            return AgentResult(success=False, error=exec_result.error)

        output = exec_result.output or {}
        voice_path = output.get("storage_path")
        duration = output.get("duration_seconds", 0.0)

        segments = self._estimate_segments(script_content, duration)

                # Download voice to local storage so URL doesn't expire
        local_voice_path = voice_path
        if voice_path and voice_path.startswith("http"):
            try:
                import httpx
                import tempfile
                local_file = Path(tempfile.gettempdir()) / f"arya_voice_{uuid.uuid4().hex}.wav"
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(voice_path)
                    resp.raise_for_status()
                local_file.write_bytes(resp.content)
                local_voice_path = str(local_file)
            except Exception:
                pass

        voice_result = VoiceFirstResult(
            voice_path=local_voice_path,
            duration_seconds=duration,
            segments=segments,
        )

        return AgentResult(
            success=True,
            output={
                "voice_first_result": voice_result,
                "voice_path": local_voice_path,
                "voice_duration_seconds": duration,
                "voice_segments": [s.__dict__ for s in segments],
            },
        )    

    def _estimate_segments(self, script: str, total_duration: float) -> list[VoiceSegment]:
        """Split script into segments and merge short ones for better video pacing."""
        sentences = re.split(r"(?<=[.!?])\s+", script.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        # Calculate word counts
        word_counts = [len(s.split()) for s in sentences]
        total_words = sum(word_counts)

        if total_words == 0:
            return []

        # Build raw segments with proportional timing
        raw_segments = []
        current_time = 0.0
        for sentence, word_count in zip(sentences, word_counts):
            segment_duration = (word_count / total_words) * total_duration
            segment_duration = max(segment_duration, 1.5)  # minimum 1.5s
            raw_segments.append({
                "text": sentence,
                "duration": segment_duration,
                "start": current_time,
            })
            current_time += segment_duration

        # Merge segments until each is 3-6 seconds (optimal for video shots)
        merged = []
        current = {"text": "", "start": 0.0, "duration": 0.0}
        
        for seg in raw_segments:
            if current["duration"] == 0:
                current = {"text": seg["text"], "start": seg["start"], "duration": seg["duration"]}
            elif current["duration"] + seg["duration"] <= 6.0:
                current["text"] += " " + seg["text"]
                current["duration"] += seg["duration"]
            else:
                merged.append(VoiceSegment(
                    text=current["text"],
                    start_time=round(current["start"], 2),
                    end_time=round(current["start"] + current["duration"], 2),
                ))
                current = {"text": seg["text"], "start": seg["start"], "duration": seg["duration"]}

        # Don't forget the last segment
        if current["duration"] > 0:
            merged.append(VoiceSegment(
                text=current["text"],
                start_time=round(current["start"], 2),
                end_time=round(current["start"] + current["duration"], 2),
            ))

        # If we still have too many shots, force-merge more aggressively
        while len(merged) > 5:
            # Merge shortest adjacent pair
            min_idx = 0
            min_combined = float('inf')
            for i in range(len(merged) - 1):
                combined = merged[i].end_time - merged[i].start_time + merged[i+1].end_time - merged[i+1].start_time
                if combined < min_combined:
                    min_combined = combined
                    min_idx = i
            
            # Merge min_idx and min_idx+1
            new_seg = VoiceSegment(
                text=merged[min_idx].text + " " + merged[min_idx+1].text,
                start_time=merged[min_idx].start_time,
                end_time=merged[min_idx+1].end_time,
            )
            merged = merged[:min_idx] + [new_seg] + merged[min_idx+2:]

        return merged