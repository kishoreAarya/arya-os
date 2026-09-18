"""CinematicDirectorAgent — transforms script and narration into a structured CinematicPlan.

Implements the Human-Crafted Cinematic Story Production Bible:
- Grounded cinematic realism (controlled naturalism, motivated lighting)
- Intentional imperfection (human camera presence, motivated reframing)
- Irregular pacing (emotionally motivated non-uniform durations)
- Deterministic Class A/B/C shot planning (conserving video generation budget)
- Sound design intent (sound events, diegetic music, silence opportunities)
- Absolute prohibition against AI-generated text/subtitles/CTAs
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult, BaseAgent
from app.agents.storyboard import Shot, StoryboardResult
from app.core.logging import get_logger
from app.core.shot_classifier import (
    calculate_irregular_pacing,
    calculate_shot_cost,
    classify_shot,
    get_enforced_negative_prompt,
    sanitize_generation_prompt,
)
from app.providers.capabilities import Capability
from app.providers.text_dispatch import build_text_generation_call
from app.schemas.cinematic import (
    CameraMovementType,
    CinematicPlan,
    CinematicShotPlan,
    GenerationClass,
    GenerationMode,
    NarrativeBeatType,
    SoundDesignPlan,
)
from app.services.execution_engine import ExecutionEngine

logger = get_logger("arya.agents.cinematic_director")


def _build_cinematic_director_prompt(
    script_content: str,
    target_duration: float,
    aspect_ratio: str,
    style_bible: str | None = None,
    character_bible: str | None = None,
    environment_bible: str | None = None,
    camera_style: str | None = None,
    lighting_style: str | None = None,
    target_shots: int = 5,
    narration_timing: Any | None = None,
) -> str:
    lines = [
        "You are an elite cinematic film director, visual storyteller, and master of cinematography.",
        "You adhere strictly to the ARYA OS HUMAN-CRAFTED CINEMATIC PRODUCTION BIBLE.",
        "",
        "YOUR MISSION:",
        "Direct the provided script into a comprehensive, shot-by-shot CINEMATIC PRODUCTION PLAN.",
        "Every creative decision must have a narrative reason. Grounded realism. Motivated lighting. Natural framing.",
        "",
        "CRITICAL DIRECTING PRINCIPLES (CINEMATIC PRODUCTION BIBLE):",
        "1. STORY FIRST, TECHNOLOGY SECOND: Avoid sterile perfection and generic AI spectacle.",
        "2. SHOW -> IMPLY -> REVEAL: Do not merely illustrate spoken dialogue. Use subtext and visual storytelling.",
        "3. RHYTHMIC IRREGULARITY: DO NOT use uniform 4.0s shot durations everywhere. Shot durations MUST align with the spoken phrases, pauses, and emotional beats of the narration.",
        "4. SHOT GENERATION CLASSIFICATION (CLASS A / B / C):",
        "   - Class A (Critical Motion): True physical movement, fighting, running, door opening, dynamic interaction -> VIDEO.",
        "   - Class B (Atmospheric Motion): Corridor drift, empty street, bedroom mood, subtle environment -> IMAGE_MOTION or VIDEO.",
        "   - Class C (Information / Context): Documents, blueprints, monitors, relics, static details -> IMAGE_MOTION ($0 video cost).",
        "   Actively prioritize Class C and Class B image_motion where motion is not narrative-critical to optimize production cost.",
        "5. CAMERA PHILOSOPHY: Observational, motivated camera movement. Supported movements: slow_push_in, slow_pull_out, pan_left, pan_right, tilt_up, tilt_down, subtle_scale, static_locked.",
        "6. SOUND DESIGN INTENT: Specify environment ambient bed (room_tone, wind, etc.), Foley events (footstep, door_creak, metal_clank), and intentional silence for dramatic tension.",
        "7. ABSOLUTE PROHIBITION ON TEXT/UI: Models must NEVER generate subtitles, captions, buttons, UI, or text. These are added deterministically in post-production.",
        "8. HOOK INTEGRITY (SHOT 1): Shot 1 MUST immediately establish the concrete subject, situation, and conflict. Avoid vague atmospheric throat-clearing, meaningless hands, or abstract footage. Lock the viewer's attention to the core subject instantly.",
        "9. EMOTIONAL FINAL BEAT & NO CTAs: The final shot must conclude on a resonant emotional beat, dramatic freeze, chilling reveal, or atmospheric fade. NEVER include subscribe prompts, follow prompts, watermark placeholders, or CTA end-cards.",
        "10. DIVERSE MOTIVATED CAMERA WORK: Do NOT assign the same camera movement to all shots. Vary camera movements across shots (e.g., slow_push_in, pan_right, slow_pull_out, tilt_down, pan_left, subtle_scale) based on narrative beats.",
        "",
        f"PRODUCTION TARGETS:",
        f"- Target Total Duration: {target_duration} seconds",
        f"- Target Aspect Ratio: {aspect_ratio}",
        f"- Target Shot Count: {target_shots} shots",
    ]

    if narration_timing and getattr(narration_timing, "segments", None):
        lines.extend([
            "",
            "NARRATION TIMING & SPOKEN RHYTHM (TEMPORAL SPINE):",
            f"Measured Voice Duration: {getattr(narration_timing, 'total_duration_seconds', target_duration):.2f}s",
            f"Real Timestamps Available: {getattr(narration_timing, 'has_real_timestamps', False)}",
            "Spoken Segments / Phrases:",
        ])
        for seg in narration_timing.segments:
            emp = f" [EMPHASIS: {seg.emphasis_reason}]" if seg.has_emphasis else ""
            p = f" [Pause: {seg.pause_after_seconds:.2f}s]" if seg.pause_after_seconds > 0.1 else ""
            lines.append(
                f"  - Segment {seg.segment_index + 1} [{seg.start_seconds:.2f}s - {seg.end_seconds:.2f}s] ({seg.duration_seconds:.2f}s): "
                f'"{seg.text}"{emp}{p}'
            )
        lines.extend([
            "",
            "DIRECTOR'S AUDIO-DRIVEN EDITING INSTRUCTIONS:",
            "1. Align shot cut points to phrase boundaries and natural spoken pauses.",
            "2. Time visual reveals immediately before or after emphasis segments.",
            "3. Place reaction holds during breath gaps and dramatic pauses.",
        ])

    lines.extend([
        "",
        "OUTPUT RULES:",
        "- Return ONLY a valid JSON object. No markdown fences, no explanatory preambles or postscripts.",
        "- Root object keys must be:",
        '    "target_duration" (float),',
        '    "aspect_ratio" (string),',
        '    "emotional_arc" (string summary of emotional progression),',
        '    "visual_style" (string description of cinematography, lighting palette, and texture),',
        '    "shots" (list of shot objects).',
        "- Each shot object must contain:",
        '    "shot_number" (int, 1-indexed),',
        '    "duration_seconds" (float, e.g. 2.8, 4.5),',
        '    "narrative_beat" (string: "HOOK", "ESTABLISH", "CHARACTER", "ACTION", "ESCALATION", "REACTION", "REVEAL", "CONSEQUENCE", or "ENDING"),',
        '    "visual_purpose" (string, concrete visual storytelling purpose),',
        '    "continuity_dependency" (string or null, anchor or previous shot reference),',
        '    "narration_segment" (string, exact narration for this shot),',
        '    "purpose" (string, narrative/dramatic/information purpose),',
        '    "generation_class" (string: "A", "B", or "C"),',
        '    "generation_mode" (string: "video" or "image_motion"),',
        '    "subject" (string, subject in frame),',
        '    "action" (string, physical movement or subtle behavior),',
        '    "environment" (string, setting, atmospheric details),',
        '    "composition" (string, framing, negative space, layers),',
        '    "camera_angle" (string: Eye Level, Low Angle, High Angle, Canted),',
        '    "camera_movement" (string: slow_push_in, slow_pull_out, pan_left, pan_right, tilt_up, tilt_down, subtle_scale, static_locked),',
        '    "lens" (string: 24mm, 35mm, 50mm, 85mm, Anamorphic),',
        '    "lighting" (string, motivated light source, color temp, shadow depth),',
        '    "performance_behavior" (string, character micro-behaviors, eye movement, hesitation),',
        '    "sound_design" (object: {"sound_events": [strings], "music_type": string, "music_intensity": string, "silence_intentional": bool, "silence_reason": string or null}),',
        '    "continuity_notes" (string or null),',
        '    "generation_prompt" (string, detailed cinematic prompt fragment without text/UI instructions),',
        '    "negative_prompt" (string, negative prompt keywords).',
        "",
        "SCRIPT CONTENT:",
        f"{script_content}",
    ])

    if character_bible:
        lines.extend(["", f"Character Bible: {character_bible}"])
    if environment_bible:
        lines.extend(["", f"Environment Bible: {environment_bible}"])
    if style_bible:
        lines.extend(["", f"Style Bible: {style_bible}"])
    if camera_style:
        lines.extend(["", f"Camera Style: {camera_style}"])
    if lighting_style:
        lines.extend(["", f"Lighting Style: {lighting_style}"])

    return "\n".join(lines)


def _parse_cinematic_plan_json(raw_text: str, target_duration: float, aspect_ratio: str) -> CinematicPlan | None:
    """Attempt to parse raw text into a CinematicPlan."""
    text = raw_text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        return None

    parsed_shots: list[CinematicShotPlan] = []
    current_time = 0.0

    for idx, item in enumerate(raw_shots, start=1):
        if not isinstance(item, dict):
            continue
        shot_num = int(item.get("shot_number", idx))
        dur = float(item.get("duration_seconds", 4.0))
        if dur <= 0.0:
            dur = 3.0

        gen_class_raw = str(item.get("generation_class", "B")).upper()
        if gen_class_raw not in ("A", "B", "C"):
            gen_class_raw = "B"
        gen_class = GenerationClass(gen_class_raw)

        gen_mode_raw = str(item.get("generation_mode", "image_motion")).lower()
        if gen_mode_raw not in ("video", "image_motion"):
            gen_mode_raw = "video" if gen_class == GenerationClass.A else "image_motion"
        gen_mode = GenerationMode(gen_mode_raw)

        cam_move_raw = str(item.get("camera_movement", "slow_push_in")).lower()
        valid_moves = {m.value for m in CameraMovementType}
        if cam_move_raw not in valid_moves:
            cam_move_raw = "slow_push_in"

        # Sound design parsing
        sd_data = item.get("sound_design") or {}
        if not isinstance(sd_data, dict):
            sd_data = {}
        sound_design = SoundDesignPlan(
            sound_events=sd_data.get("sound_events", []),
            music_type=str(sd_data.get("music_type", "diegetic")),
            music_intensity=str(sd_data.get("music_intensity", "low")),
            silence_intentional=bool(sd_data.get("silence_intentional", False)),
            silence_reason=sd_data.get("silence_reason"),
        )

        beat_raw = str(item.get("narrative_beat", "")).upper()
        narrative_beat = None
        if beat_raw in NarrativeBeatType.__members__:
            narrative_beat = NarrativeBeatType(beat_raw)
        elif idx == 1:
            narrative_beat = NarrativeBeatType.HOOK
        elif idx == len(raw_shots):
            narrative_beat = NarrativeBeatType.ENDING
        else:
            narrative_beat = NarrativeBeatType.ACTION

        shot_plan = CinematicShotPlan(
            shot_number=shot_num,
            shot_id=f"shot_{idx}_{uuid.uuid4().hex[:6]}",
            start_time=current_time,
            duration_seconds=dur,
            narration_segment=str(item.get("narration_segment", "")).strip(),
            purpose=str(item.get("purpose", "")).strip(),
            narrative_beat=narrative_beat,
            visual_purpose=str(item.get("visual_purpose", "")).strip() or None,
            continuity_dependency=str(item.get("continuity_dependency", "")).strip() or None,
            generation_class=gen_class,
            generation_mode=gen_mode,
            subject=str(item.get("subject", "")).strip(),
            action=str(item.get("action", "")).strip(),
            environment=str(item.get("environment", "")).strip(),
            composition=str(item.get("composition", "Rule of Thirds")).strip(),
            camera_angle=str(item.get("camera_angle", "Eye Level")).strip(),
            camera_movement=cam_move_raw,
            lens=str(item.get("lens", "35mm")).strip(),
            lighting=str(item.get("lighting", "Motivated lighting")).strip(),
            performance_behavior=str(item.get("performance_behavior", "Natural behavior")).strip(),
            sound_design=sound_design,
            continuity_notes=item.get("continuity_notes"),
            generation_prompt=str(item.get("generation_prompt", "")).strip(),
            negative_prompt=str(item.get("negative_prompt", "")).strip(),
            cost_reason=str(item.get("cost_reason", "")),
            quality_reason=str(item.get("quality_reason", "")),
        )
        current_time += dur
        parsed_shots.append(shot_plan)

    if not parsed_shots:
        return None

    return CinematicPlan(
        target_duration=target_duration,
        aspect_ratio=aspect_ratio,
        emotional_arc=str(data.get("emotional_arc", "Engaging narrative escalation")),
        visual_style=str(data.get("visual_style", "Grounded cinematic realism with motivated lighting")),
        shots=parsed_shots,
        continuity_bible=data.get("continuity_bible"),
    )


def _build_fallback_cinematic_plan(
    script_content: str,
    target_duration: float,
    aspect_ratio: str,
    narration_timing: Any | None = None,
) -> CinematicPlan:
    """Deterministic fallback planner if LLM JSON parsing fails."""
    from app.core.audio_timing import align_shots_to_narration

    shots: list[CinematicShotPlan] = []
    current_time = 0.0

    if narration_timing and getattr(narration_timing, "segments", None):
        segments = narration_timing.segments
        shot_count = max(2, min(8, len(segments)))
        aligned = align_shots_to_narration(segments, target_shot_count=shot_count, total_duration=target_duration)

        fallback_moves = ["slow_push_in", "pan_right", "slow_pull_out", "tilt_down", "pan_left", "subtle_scale"]
        beat_cycle = [
            NarrativeBeatType.HOOK,
            NarrativeBeatType.ESTABLISH,
            NarrativeBeatType.CHARACTER,
            NarrativeBeatType.ACTION,
            NarrativeBeatType.ESCALATION,
            NarrativeBeatType.REVEAL,
            NarrativeBeatType.CONSEQUENCE,
            NarrativeBeatType.ENDING,
        ]
        for i, al in enumerate(aligned):
            dur = al["duration_seconds"]
            seg_text = al["narration"] or f"Cinematic narrative beat {i+1}"
            gen_class, gen_mode, cost_r, qual_r = classify_shot(
                action=seg_text,
                subject="Primary subject",
                environment="Atmospheric environment",
                purpose=f"Story beat {i+1}",
            )

            beat = (
                NarrativeBeatType.HOOK
                if i == 0
                else (NarrativeBeatType.ENDING if i == len(aligned) - 1 else beat_cycle[min(i, len(beat_cycle) - 2)])
            )

            shots.append(
                CinematicShotPlan(
                    shot_number=i + 1,
                    shot_id=f"shot_{i+1}_{uuid.uuid4().hex[:6]}",
                    start_time=round(current_time, 2),
                    duration_seconds=dur,
                    narration_segment=seg_text,
                    purpose=f"Narrative beat {i+1}",
                    narrative_beat=beat,
                    visual_purpose=f"Visual delivery of {beat.value} beat",
                    continuity_dependency=f"shot_{i}" if i > 0 else None,
                    generation_class=gen_class,
                    generation_mode=gen_mode,
                    subject="Cinematic subject in motivated composition",
                    action=seg_text,
                    environment="Atmospheric environment with selective focus",
                    composition="Rule of thirds, leading lines, selective depth",
                    camera_angle="Eye Level",
                    camera_movement=fallback_moves[i % len(fallback_moves)],
                    lens="35mm anamorphic",
                    lighting="Motivated directional practical lighting with natural contrast",
                    performance_behavior="Subtle observational presence",
                    sound_design=SoundDesignPlan(
                        sound_events=["subtle ambient room tone", "diegetic movement"],
                        music_type="diegetic",
                        music_intensity="low",
                    ),
                    generation_prompt=seg_text,
                    negative_prompt="",
                    cost_reason=cost_r,
                    quality_reason=qual_r,
                )
            )
            current_time += dur
    else:
        paragraphs = [p.strip() for p in script_content.splitlines() if p.strip()]
        if not paragraphs:
            paragraphs = [script_content.strip() or "A cinematic moment unfolds."]

        shot_count = max(2, min(8, len(paragraphs)))
        pacing = calculate_irregular_pacing(target_duration, shot_count)
        fallback_moves = ["slow_push_in", "pan_right", "slow_pull_out", "tilt_down", "pan_left", "subtle_scale"]
        beat_cycle = [
            NarrativeBeatType.HOOK,
            NarrativeBeatType.ESTABLISH,
            NarrativeBeatType.CHARACTER,
            NarrativeBeatType.ACTION,
            NarrativeBeatType.ESCALATION,
            NarrativeBeatType.REVEAL,
            NarrativeBeatType.CONSEQUENCE,
            NarrativeBeatType.ENDING,
        ]

        for i in range(shot_count):
            segment = paragraphs[i % len(paragraphs)]
            dur = pacing[i]
            gen_class, gen_mode, cost_r, qual_r = classify_shot(
                action=segment,
                subject="Primary subject",
                environment="Atmospheric environment",
                purpose=f"Cinematic story progression beat {i+1}",
            )

            beat = (
                NarrativeBeatType.HOOK
                if i == 0
                else (NarrativeBeatType.ENDING if i == shot_count - 1 else beat_cycle[min(i, len(beat_cycle) - 2)])
            )

            shots.append(
                CinematicShotPlan(
                    shot_number=i + 1,
                    shot_id=f"shot_{i+1}_{uuid.uuid4().hex[:6]}",
                    start_time=current_time,
                    duration_seconds=dur,
                    narration_segment=segment,
                    purpose=f"Narrative beat {i+1}",
                    narrative_beat=beat,
                    visual_purpose=f"Visual delivery of {beat.value} beat",
                    continuity_dependency=f"shot_{i}" if i > 0 else None,
                    generation_class=gen_class,
                    generation_mode=gen_mode,
                    subject="Cinematic subject in motivated composition",
                    action=segment,
                    environment="Lived-in environment with selective focus",
                    composition="Rule of thirds, leading lines, selective depth",
                    camera_angle="Eye Level",
                    camera_movement=fallback_moves[i % len(fallback_moves)],
                    lens="35mm anamorphic",
                    lighting="Motivated directional practical lighting with natural contrast",
                    performance_behavior="Subtle observational presence",
                    sound_design=SoundDesignPlan(
                        sound_events=["subtle ambient room tone", "diegetic movement"],
                        music_type="diegetic",
                        music_intensity="low",
                    ),
                    generation_prompt=segment,
                    negative_prompt="",
                    cost_reason=cost_r,
                    quality_reason=qual_r,
                )
            )
            current_time += dur

    return CinematicPlan(
        target_duration=target_duration,
        aspect_ratio=aspect_ratio,
        emotional_arc="Intimate beginning escalating to cinematic revelation",
        visual_style="Grounded cinematic realism, motivated lighting, human operator feel",
        shots=shots,
    )


class CinematicDirectorAgent(BaseAgent):
    """Directs a script into a fully realized, cost-optimized CinematicPlan."""

    name = "cinematic_director"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._execution_engine = ExecutionEngine(db)

    async def run(self, context: dict[str, Any]) -> AgentResult:
        """Execute the cinematic director agent.

        Consumes:
            script_content (required)
            duration / target_duration (optional, float/int)
            aspect_ratio (optional, str)
            narration_timing (optional, NarrationTiming or dict)
            style_bible, character_bible, environment_bible (optional)
        """
        from app.core.audio_timing import align_shots_to_narration
        from app.schemas.cinematic import (
            AmbientSoundIntent,
            FoleyEvent,
            MasterAudioPlan,
            NarrationTiming,
            SilenceInterval,
        )

        script_content = context.get("script_content") or context.get("script")
        if not script_content or not str(script_content).strip():
            return AgentResult(
                success=False,
                error="context.script_content is required and was empty",
            )

        # Parse narration timing if available
        narration_timing_raw = context.get("narration_timing")
        narration_timing: NarrationTiming | None = None
        if isinstance(narration_timing_raw, dict):
            try:
                narration_timing = NarrationTiming.model_validate(narration_timing_raw)
            except Exception as exc:
                logger.warning("narration_timing_validation_failed", error=str(exc))
        elif isinstance(narration_timing_raw, NarrationTiming):
            narration_timing = narration_timing_raw

        target_duration = 20.0
        if narration_timing and narration_timing.total_duration_seconds > 0:
            target_duration = narration_timing.total_duration_seconds
        else:
            raw_dur = context.get("duration") or context.get("target_duration")
            if raw_dur:
                try:
                    target_duration = float(raw_dur)
                except (ValueError, TypeError):
                    pass

        aspect_ratio = context.get("aspect_ratio", "16:9")
        target_shots = max(2, min(10, round(target_duration / 4.0)))

        prompt = _build_cinematic_director_prompt(
            script_content=str(script_content),
            target_duration=target_duration,
            aspect_ratio=aspect_ratio,
            style_bible=context.get("style_bible"),
            character_bible=context.get("character_bible"),
            environment_bible=context.get("environment_bible"),
            camera_style=context.get("camera_style"),
            lighting_style=context.get("lighting_style"),
            target_shots=target_shots,
            narration_timing=narration_timing,
        )

        exec_result = await self._execution_engine.execute(
            capability=Capability.TEXT_GENERATION,
            call=build_text_generation_call(prompt),
            workflow_run_id=context.get("workflow_run_id"),
            stage="cinematic_director",
        )

        if not exec_result.success:
            logger.warning("cinematic_director_llm_failed_using_fallback", error=exec_result.error)
            plan = _build_fallback_cinematic_plan(
                str(script_content), target_duration, aspect_ratio, narration_timing=narration_timing
            )
            provider_used = "fallback"
            cost_usd = 0.0
            duration_seconds = 0.0
        else:
            plan = _parse_cinematic_plan_json(str(exec_result.output or ""), target_duration, aspect_ratio)
            if not plan:
                logger.warning("cinematic_director_json_parse_failed_using_fallback")
                plan = _build_fallback_cinematic_plan(
                    str(script_content), target_duration, aspect_ratio, narration_timing=narration_timing
                )
            provider_used = exec_result.provider
            cost_usd = exec_result.cost_usd
            duration_seconds = exec_result.elapsed_time

        # Pacing: Use speech alignment if narration_timing exists, else irregular pacing
        if narration_timing and narration_timing.segments:
            aligned = align_shots_to_narration(
                segments=narration_timing.segments,
                target_shot_count=len(plan.shots),
                total_duration=target_duration,
            )
            pacing = [al["duration_seconds"] for al in aligned]
            for i, shot in enumerate(plan.shots):
                if i < len(aligned) and aligned[i]["narration"]:
                    shot.narration_segment = aligned[i]["narration"]
        else:
            pacing = calculate_irregular_pacing(target_duration, len(plan.shots))

        # Enforce camera movement variety across shots if parsed shots have identical movement
        movements = [s.camera_movement for s in plan.shots]
        if len(set(movements)) <= 1 and len(plan.shots) > 1:
            diverse_palette = [
                "slow_push_in",
                "pan_right",
                "slow_pull_out",
                "tilt_down",
                "pan_left",
                "subtle_scale",
            ]
            for idx, shot in enumerate(plan.shots):
                shot.camera_movement = diverse_palette[idx % len(diverse_palette)]

        total_estimated_cost = 0.0
        current_time = 0.0
        ambient_layers: list[AmbientSoundIntent] = []
        foley_events: list[FoleyEvent] = []
        silence_intervals: list[SilenceInterval] = []

        for i, shot in enumerate(plan.shots):
            # Apply audio-aligned or irregular pacing
            shot.duration_seconds = pacing[i]
            shot.start_time = round(current_time, 2)
            current_time += shot.duration_seconds

            # Enforce deterministic A/B/C classification & reasoning
            gen_class, gen_mode, cost_r, qual_r = classify_shot(
                action=shot.action,
                subject=shot.subject,
                environment=shot.environment,
                purpose=shot.purpose,
                force_class=shot.generation_class,
                force_mode=shot.generation_mode,
            )
            shot.generation_class = gen_class
            shot.generation_mode = gen_mode
            if not shot.cost_reason:
                shot.cost_reason = cost_r
            if not shot.quality_reason:
                shot.quality_reason = qual_r

            # Enforce Section 30 text/UI prohibition in prompts
            shot.negative_prompt = get_enforced_negative_prompt(shot.negative_prompt)
            shot.generation_prompt = sanitize_generation_prompt(shot.generation_prompt or shot.action or shot.subject)

            # Build shot-level sound design elements
            env_clean = (shot.environment or "room_tone").lower()
            env_name = "room_tone"
            for candidate in ["wind", "ocean", "forest", "rain", "machinery_hum", "underwater", "room_tone"]:
                if candidate in env_clean:
                    env_name = candidate
                    break

            ambient_intent = AmbientSoundIntent(
                environment=env_name,
                start_time=shot.start_time,
                duration=shot.duration_seconds,
                volume=0.08,
            )
            shot.sound_design.ambient_intent = ambient_intent
            ambient_layers.append(ambient_intent)

            # Deterministic Foley detection from shot action
            action_lower = (shot.action or "").lower()
            shot_foley: list[FoleyEvent] = []
            if "door" in action_lower:
                shot_foley.append(
                    FoleyEvent(event="door_creak", start_time=round(shot.start_time + 0.4, 2), duration=1.2, volume=0.5)
                )
            if "footstep" in action_lower or "walk" in action_lower or "step" in action_lower:
                shot_foley.append(
                    FoleyEvent(event="footstep", start_time=round(shot.start_time + 0.2, 2), duration=0.8, volume=0.4)
                )
            if "metal" in action_lower or "gear" in action_lower or "clock" in action_lower or "machine" in action_lower:
                shot_foley.append(
                    FoleyEvent(event="metal_clank", start_time=round(shot.start_time + 0.5, 2), duration=0.8, volume=0.4)
                )
            if "whisper" in action_lower or "breath" in action_lower or "gasp" in action_lower:
                shot_foley.append(
                    FoleyEvent(event="breathing", start_time=round(shot.start_time + 0.2, 2), duration=1.2, volume=0.4)
                )
            shot.sound_design.foley_events = shot_foley
            foley_events.extend(shot_foley)

            # Intentional silence detection
            if shot.sound_design.silence_intentional or "silence" in (shot.purpose or "").lower():
                sil_start = round(shot.start_time + max(0.0, shot.duration_seconds - 1.2), 2)
                sil_dur = min(1.2, shot.duration_seconds * 0.4)
                sil = SilenceInterval(
                    silence_start=sil_start,
                    silence_duration=sil_dur,
                    reason=shot.sound_design.silence_reason or "Dramatic suspense before cut",
                )
                shot.sound_design.intentional_silence = sil
                silence_intervals.append(sil)

            # Calculate estimated cost without inventing fake pricing
            shot.estimated_cost = calculate_shot_cost(
                generation_class=shot.generation_class,
                generation_mode=shot.generation_mode,
                provider=context.get("video_provider") or context.get("target_model"),
                model=context.get("video_model"),
            )
            if shot.estimated_cost is not None:
                total_estimated_cost += shot.estimated_cost

        plan.total_estimated_cost = round(total_estimated_cost, 4)

        # Task 22: Smart Visual Budget Allocation & Candidate Policy
        if (
            context.get("use_smart_allocation")
            or context.get("candidate_policy")
            or context.get("visual_budget_usd") is not None
            or context.get("max_kling_shots") is not None
        ):
            try:
                from app.services.smart_allocator import SmartShotAllocator
                from app.core.config import get_settings
                settings = get_settings()

                smart_allocator = SmartShotAllocator(
                    visual_budget_usd=context.get("visual_budget_usd"),
                    max_kling_shots=context.get("max_kling_shots"),
                    quality_floor=context.get("quality_floor"),
                    candidate_policy=context.get("candidate_policy"),
                    allocation_strategy=context.get("allocation_strategy"),
                    default_candidate_count=context.get("num_keyframe_candidates") or getattr(settings, "visual_keyframe_candidates", 1),
                    visual_profile=context.get("visual_profile"),
                )
                budget_plan = smart_allocator.allocate(
                    shots=plan.shots,
                    budget_usd=context.get("visual_budget_usd"),
                    max_kling=context.get("max_kling_shots"),
                    candidate_policy=context.get("candidate_policy"),
                    quality_floor=context.get("quality_floor"),
                )
                plan.visual_budget_plan = {
                    "target_budget_usd": budget_plan.target_budget_usd,
                    "allocated_cost_usd": budget_plan.allocated_cost_usd,
                    "kling_shot_count": budget_plan.kling_shot_count,
                    "image_motion_shot_count": budget_plan.image_motion_shot_count,
                    "total_candidates_generated": budget_plan.total_candidates_generated,
                    "budget_exceeded": budget_plan.budget_exceeded,
                    "overrun_reasons": budget_plan.overrun_reasons,
                }
            except Exception as exc:
                logger.warning("smart_allocation_failed", error=str(exc))
        plan.narration_timing = narration_timing
        plan.master_audio_plan = MasterAudioPlan(
            master_voice_path=context.get("master_voice_path") or context.get("voice_path"),
            music_path=context.get("music_path"),
            music_volume=float(context.get("music_volume") or 0.22),
            music_ducking_volume=float(context.get("music_ducking_volume") or 0.06),
            ambient_layers=ambient_layers,
            foley_events=foley_events,
            silence_intervals=silence_intervals,
            final_audio_duration=target_duration,
        )

        # Convert to standard Shot dataclasses for downstream compatibility
        shots: list[Shot] = [s.to_storyboard_shot() for s in plan.shots]
        storyboard_result = StoryboardResult(
            script_id=context.get("script_id"),
            shots=shots,
        )

        output: dict[str, Any] = {
            "cinematic_plan": plan,
            "shots": shots,
            "storyboard_result": storyboard_result,
            "aspect_ratio": aspect_ratio,
            "duration": target_duration,
            "total_estimated_cost": plan.total_estimated_cost,
            "master_audio_plan": plan.master_audio_plan.model_dump(),
        }
        if narration_timing:
            output["narration_timing"] = narration_timing.model_dump()
            output["has_real_timestamps"] = narration_timing.has_real_timestamps
            output["fallback_used"] = narration_timing.fallback_used

        # Carry forward script_id and first shot metadata
        script_id = context.get("script_id")
        if script_id:
            output["script_id"] = script_id
        if shots:
            output["shot_description"] = shots[0].description
            output["shot_number"] = shots[0].shot_number

        logger.info(
            "cinematic_director_completed",
            shot_count=len(shots),
            class_counts=plan.class_counts,
            target_duration=target_duration,
            total_estimated_cost=plan.total_estimated_cost,
            foley_count=len(foley_events),
            silence_count=len(silence_intervals),
        )

        return AgentResult(
            success=True,
            output=output,
            provider_used=provider_used,
            cost_usd=cost_usd,
            duration_seconds=duration_seconds,
        )
