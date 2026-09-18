"""Cinematic production plan schemas conforming to CINEMATIC_PRODUCTION_BIBLE.md."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerationClass(str, Enum):
    """Shot generation classification per Section 25 of Cinematic Production Bible."""

    A = "A"  # Critical motion -> Actual AI video generation
    B = "B"  # Atmospheric motion -> AI video or image + motion
    C = "C"  # Information / Context -> High-fidelity image + FFmpeg camera motion ($0 video cost)


class GenerationMode(str, Enum):
    """Underlying generation mode for a shot."""

    VIDEO = "video"  # Generative AI video
    IMAGE_MOTION = "image_motion"  # Image generation + FFmpeg cinematic camera motion


class CameraMovementType(str, Enum):
    """Cinematic camera movement types per Section 26 of Cinematic Production Bible."""

    SLOW_PUSH_IN = "slow_push_in"
    SLOW_PULL_OUT = "slow_pull_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    SUBTLE_SCALE = "subtle_scale"
    STATIC_LOCKED = "static_locked"


class NarrativeBeatType(str, Enum):
    """Visual storytelling narrative beats for comprehensive story coverage."""

    HOOK = "HOOK"
    ESTABLISH = "ESTABLISH"
    CHARACTER = "CHARACTER"
    ACTION = "ACTION"
    ESCALATION = "ESCALATION"
    REACTION = "REACTION"
    REVEAL = "REVEAL"
    CONSEQUENCE = "CONSEQUENCE"
    ENDING = "ENDING"


class WordTiming(BaseModel):
    """Word-level alignment and timing."""

    word: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    character_start: int | None = None
    character_end: int | None = None

    model_config = ConfigDict(extra="ignore")


class NarrationSegment(BaseModel):
    """Deterministic spoken phrase/sentence segment."""

    segment_index: int = Field(ge=0)
    text: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)
    words: list[WordTiming] = Field(default_factory=list)
    pause_after_seconds: float = 0.0
    has_emphasis: bool = False
    emphasis_reason: str | None = None

    model_config = ConfigDict(extra="ignore")


class NarrationTiming(BaseModel):
    """Temporal spine of the film with real/fallback voice timing."""

    text: str
    total_duration_seconds: float = Field(ge=0.0)
    audio_path: str | None = None
    has_real_timestamps: bool = False
    timestamp_provider: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    words: list[WordTiming] = Field(default_factory=list)
    segments: list[NarrationSegment] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class FoleyEvent(BaseModel):
    """Shot-level Foley/SFX event."""

    event: str = Field(description="e.g. footstep, door_creak, metal_clank, breathing, heartbeat, impact")
    start_time: float = Field(ge=0.0, description="Timestamp within video in seconds")
    duration: float = Field(default=1.0, gt=0.0, description="Duration in seconds")
    volume: float = Field(default=0.5, ge=0.0, le=1.0, description="Relative volume")
    source_path: str | None = Field(default=None, description="Local path to audio file if available")

    model_config = ConfigDict(extra="ignore")


class AmbientSoundIntent(BaseModel):
    """Shot-level ambient sound bed."""

    environment: str = Field(description="e.g. room_tone, wind, ocean, forest, rain, machinery_hum")
    start_time: float = Field(default=0.0, ge=0.0)
    duration: float = Field(default=4.0, gt=0.0)
    volume: float = Field(default=0.08, ge=0.0, le=1.0, description="Ambient bed volume (~ -22dB)")
    source_path: str | None = None

    model_config = ConfigDict(extra="ignore")


class SilenceInterval(BaseModel):
    """Intentional silence for dramatic tension/reveal."""

    silence_start: float = Field(ge=0.0)
    silence_duration: float = Field(gt=0.0)
    reason: str = Field(description="e.g. suspense before reveal, shock reaction")

    model_config = ConfigDict(extra="ignore")


class SoundDesignPlan(BaseModel):
    """Sound intent for a shot per Sections 16-19 of Cinematic Production Bible."""

    sound_events: list[str] = Field(default_factory=list)
    music_type: str = Field(default="diegetic", description="diegetic, atmospheric score, minimal, silence")
    music_intensity: str = Field(default="low", description="low, medium, high")
    silence_intentional: bool = Field(default=False)
    silence_reason: str | None = Field(default=None)
    ambient_intent: AmbientSoundIntent | None = None
    foley_events: list[FoleyEvent] = Field(default_factory=list)
    intentional_silence: SilenceInterval | None = None

    model_config = ConfigDict(extra="ignore")


class CaptionSegment(BaseModel):
    """Deterministic, strongly-typed subtitle/caption phrase segment."""

    segment_index: int = Field(ge=0)
    text: str = Field(description="Display text for the caption card (1-2 lines)")
    start_seconds: float = Field(ge=0.0, description="Start timestamp in seconds")
    end_seconds: float = Field(ge=0.0, description="End timestamp in seconds")
    duration_seconds: float = Field(ge=0.0, description="Display duration in seconds")
    has_emphasis: bool = Field(default=False, description="Whether this segment contains emphasis")
    emphasis_words: list[str] = Field(default_factory=list, description="Specific words emphasized")
    words: list[WordTiming] = Field(default_factory=list, description="Word-level timings when available")
    line_count: int = Field(default=1, ge=1, le=2)

    model_config = ConfigDict(extra="ignore")


class CaptionStyle(BaseModel):
    """Visual typography and safe-area styling for vertical shorts captions."""

    font_size: int = 48
    font_family: str = "Helvetica"
    text_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 4
    shadow_offset: int = 3
    emphasis_color: str = "#FFD700"  # Subtle cinematic gold emphasis
    placement: str = "lower_third"
    bottom_margin_px: int = 240  # Safe margins away from Shorts UI
    max_chars_per_line: int = 34
    max_lines: int = 2
    min_duration_seconds: float = 0.8
    max_duration_seconds: float = 4.5

    model_config = ConfigDict(extra="ignore")


class CaptionTimeline(BaseModel):
    """Complete timeline of caption segments burned into the production."""

    video_duration_seconds: float = Field(ge=0.0)
    segments: list[CaptionSegment] = Field(default_factory=list)
    style: CaptionStyle = Field(default_factory=CaptionStyle)
    burned_in: bool = Field(default=False)
    output_video_path: str | None = None

    model_config = ConfigDict(extra="ignore")

    @property
    def total_segments(self) -> int:
        return len(self.segments)


class SFXCacheEntry(BaseModel):
    """Cache entry for a resolved or synthesized SFX/ambient sound asset."""

    key: str = Field(description="sound_type:normalized_description")
    sound_type: str = Field(description="ambient | foley | diegetic | transition")
    normalized_description: str
    asset_path: str
    duration_seconds: float = Field(ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    provider: str = "local_asset"
    model: str = "procedural"
    created_at: str | None = None
    hit_count: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="ignore")


class SFXResolutionResult(BaseModel):
    """Result of resolving sound design cues into concrete local audio assets."""

    resolved_foley: list[FoleyEvent] = Field(default_factory=list)
    resolved_ambient: list[AmbientSoundIntent] = Field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    total_cost_usd: float = 0.0
    omitted_count: int = 0

    model_config = ConfigDict(extra="ignore")


class MasterAudioPlan(BaseModel):
    """Aggregated audio plan for final video assembly and mixing."""

    master_voice_path: str | None = None
    music_path: str | None = None
    music_volume: float = 0.22
    music_ducking_volume: float = 0.06
    ambient_layers: list[AmbientSoundIntent] = Field(default_factory=list)
    foley_events: list[FoleyEvent] = Field(default_factory=list)
    silence_intervals: list[SilenceInterval] = Field(default_factory=list)
    final_audio_duration: float | None = None
    caption_timeline: CaptionTimeline | None = None

    model_config = ConfigDict(extra="ignore")


class CinematicShotPlan(BaseModel):
    """Production direction and execution plan for a single cinematic shot."""

    shot_number: int = Field(ge=1, description="1-indexed sequence number")
    shot_id: str = Field(default_factory=lambda: f"shot_{uuid.uuid4().hex[:8]}")
    start_time: float = Field(default=0.0, ge=0.0, description="Start timestamp in seconds")
    duration_seconds: float = Field(default=4.0, gt=0.0, description="Shot duration in seconds")
    narration_segment: str = Field(default="", description="Spoken voiceover/narration for this shot")
    purpose: str = Field(default="", description="Narrative, dramatic, or information purpose")
    generation_class: GenerationClass = Field(default=GenerationClass.B)
    generation_mode: GenerationMode = Field(default=GenerationMode.IMAGE_MOTION)
    subject: str = Field(default="", description="Main subject/character in frame")
    action: str = Field(default="", description="Observable physical action or micro-behavior")
    environment: str = Field(default="", description="Specific location, architecture, time of day, atmosphere")
    composition: str = Field(default="Rule of Thirds", description="Framing and visual hierarchy")
    camera_angle: str = Field(default="Eye Level", description="Camera perspective")
    camera_movement: str = Field(default="slow_push_in", description="Camera movement")
    lens: str = Field(default="35mm", description="Focal length and lens character")
    lighting: str = Field(default="Motivated practical lighting", description="Lighting direction, color, shadows")
    performance_behavior: str = Field(default="Subtle, natural human presence", description="Micro-behaviors, pauses, reactions")
    sound_design: SoundDesignPlan = Field(default_factory=SoundDesignPlan)
    narrative_beat: NarrativeBeatType | None = Field(default=None, description="Narrative beat role in the visual story")
    visual_purpose: str | None = Field(default=None, description="Concrete visual storytelling purpose")
    continuity_dependency: str | None = Field(default=None, description="Dependency on preceding shot or keyframe anchor")
    continuity_notes: str | None = Field(default=None)
    generation_prompt: str = Field(default="", description="Positive AI generation prompt fragment")
    negative_prompt: str = Field(default="", description="Negative AI prompt with strict UI/text prohibition")
    provider: str | None = Field(default=None, description="AI provider or local engine")
    model: str | None = Field(default=None, description="Specific model identifier")
    estimated_cost: float | None = Field(default=0.0, description="Estimated generation cost in USD (0.0 for Class C)")
    cost_reason: str = Field(default="", description="Why this shot uses this generation mode")
    quality_reason: str = Field(default="", description="How this choice serves cinematic quality")
    num_candidates: int | None = Field(default=None, description="Configured keyframe candidate count")
    budget_overrun_reason: str | None = Field(default=None, description="Reason if shot was promoted above budget")

    model_config = ConfigDict(extra="ignore")

    def to_storyboard_shot(self) -> Any:
        """Convert to the standard Shot dataclass used across Arya OS workflows."""
        from app.agents.storyboard import Shot

        desc = f"{self.subject}. {self.action}." if self.action else self.subject
        if not desc:
            desc = self.purpose or f"Shot {self.shot_number}"

        return Shot(
            shot_number=self.shot_number,
            description=desc,
            shot_type="medium",
            duration_seconds=int(round(self.duration_seconds)),
            camera_angle=self.camera_angle,
            camera_movement=self.camera_movement,
            lens=self.lens,
            framing=self.composition,
            lighting=self.lighting,
            mood=self.performance_behavior,
            environment=self.environment,
            continuity_notes=self.continuity_notes,
            dialogue="",
            voiceover=self.narration_segment,
            transition="Cut",
            image_prompt_hint=self.generation_prompt,
            negative_prompt_hint=self.negative_prompt,
            generation_class=self.generation_class.value,
            generation_mode=self.generation_mode.value,
            estimated_cost=self.estimated_cost,
            cost_reason=self.cost_reason,
            quality_reason=self.quality_reason,
            purpose=self.purpose,
            sound_design=self.sound_design.model_dump(),
            narrative_beat=self.narrative_beat.value if self.narrative_beat else None,
            visual_purpose=self.visual_purpose,
            num_candidates=self.num_candidates,
            budget_overrun_reason=self.budget_overrun_reason,
        )


class CinematicPlan(BaseModel):
    """Complete cinematic production plan for a story or video."""

    target_duration: float = Field(gt=0.0, description="Target total duration in seconds")
    aspect_ratio: str = Field(default="16:9", description="'16:9' or '9:16'")
    emotional_arc: str = Field(default="", description="Overall emotional progression across shots")
    visual_style: str = Field(default="", description="Overarching cinematography and lighting style")
    total_estimated_cost: float | None = Field(default=0.0, description="Sum of estimated generation costs in USD")
    shots: list[CinematicShotPlan] = Field(default_factory=list)
    narration_timing: NarrationTiming | None = None
    master_audio_plan: MasterAudioPlan | None = None
    caption_timeline: CaptionTimeline | None = None
    continuity_bible: dict[str, Any] | None = Field(default=None, description="Visual continuity bible data")
    visual_budget_plan: dict[str, Any] | None = Field(default=None, description="Task 22 Visual budget allocation plan")

    model_config = ConfigDict(extra="ignore")

    @property
    def planned_duration(self) -> float:
        """Sum of all shot durations in the plan."""
        return sum(s.duration_seconds for s in self.shots)

    @property
    def class_counts(self) -> dict[str, int]:
        """Distribution of shots across Class A, B, and C."""
        counts = {"A": 0, "B": 0, "C": 0}
        for s in self.shots:
            counts[s.generation_class.value] = counts.get(s.generation_class.value, 0) + 1
        return counts
