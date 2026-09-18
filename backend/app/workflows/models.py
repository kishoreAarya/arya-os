"""
Arya OS — Workflow Orchestration Models.

Pydantic models shared by the Runner, Orchestrator, API Router, and
WorkflowState during workflow execution.

These are orchestration-level data structures only. They are NOT
SQLAlchemy ORM models and do NOT duplicate any database schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import WorkflowStatus


class WorkflowInput(BaseModel):
    """Input parameters for initiating a new workflow.

    Attributes:
        topic: The subject matter of the content to produce.
        preset: Optional creator preset name (e.g. "documentary_short").
        language: The target language for the content.
        style: The visual or narrative style to apply.
        duration: The target duration in seconds.
        platform: The target publishing platform (e.g., "youtube").
        aspect_ratio: Video aspect ratio (16:9 or 9:16).
        metadata: Optional additional parameters for the pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1, description="Content topic")
    preset: Optional[str] = Field(default=None, description="Creator preset identifier (e.g. 'documentary_short')")
    language: str = Field(default="en", min_length=1, description="Target language")
    style: Optional[str] = Field(default=None, description="Visual/narrative style")
    duration: Optional[int] = Field(default=None, ge=5, le=300, description="Target duration in seconds")
    platform: str = Field(default="youtube", min_length=1, description="Target platform")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio (16:9 or 9:16)")
    music_enabled: bool = Field(default=True, description="Enable background music generation")
    music_volume: float = Field(default=0.25, ge=0.0, le=1.0, description="Background music volume")
    music_ducking_volume: float = Field(default=0.08, ge=0.0, le=1.0, description="Ducking threshold / volume under speech")
    music_style: Optional[str] = Field(default=None, description="Music style override (e.g. ambient, lofi, orchestral)")
    music_mood: Optional[str] = Field(default=None, description="Music mood override (e.g. dramatic, energetic, calm)")
    music_provider: Optional[str] = Field(default=None, description="Specific music generation provider")
    music_model: Optional[str] = Field(default=None, description="Specific music generation model")
    voice_provider: Optional[str] = Field(default=None, description="Specific TTS provider (e.g. 'elevenlabs', 'replicate')")
    voice_id: Optional[str] = Field(default=None, description="Specific voice ID for TTS")
    voice_model: Optional[str] = Field(default=None, description="Specific model ID for TTS")
    video_provider: Optional[str] = Field(default=None, description="Specific video generation provider (e.g. 'kling', 'replicate')")
    video_model: Optional[str] = Field(default=None, description="Specific model ID for video generation")
    use_cinematic_director: bool = Field(default=False, description="Enable CinematicDirectorAgent and Class A/B/C shot planning")
    cinematic_mode: bool = Field(default=False, description="Alias for use_cinematic_director")
    captions_enabled: bool = Field(default=False, description="Enable deterministic burned-in captions")
    captions_required: bool = Field(default=False, description="Enforce mandatory captions validation for cinematic workflows")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _apply_preset(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("preset"):
            from app.core.presets import get_preset

            preset_obj = get_preset(data["preset"])
            defaults: dict[str, Any] = {
                "language": preset_obj.language,
                "style": preset_obj.style,
                "duration": preset_obj.duration,
                "platform": preset_obj.platform,
                "aspect_ratio": preset_obj.aspect_ratio,
                "music_enabled": preset_obj.music_enabled,
                "music_volume": preset_obj.music_volume,
                "music_ducking_volume": preset_obj.music_ducking_volume,
                "music_style": preset_obj.music_style,
                "music_mood": preset_obj.music_mood,
                "captions_enabled": getattr(preset_obj, "captions_enabled", False),
            }
            if preset_obj.music_provider:
                defaults["music_provider"] = preset_obj.music_provider
            if preset_obj.music_model:
                defaults["music_model"] = preset_obj.music_model
            if getattr(preset_obj, "voice_provider", None):
                defaults["voice_provider"] = preset_obj.voice_provider
            if getattr(preset_obj, "voice_id", None):
                defaults["voice_id"] = preset_obj.voice_id
            if getattr(preset_obj, "voice_model", None):
                defaults["voice_model"] = preset_obj.voice_model
            if getattr(preset_obj, "video_provider", None):
                defaults["video_provider"] = preset_obj.video_provider
            if getattr(preset_obj, "video_model", None):
                defaults["video_model"] = preset_obj.video_model
            if getattr(preset_obj, "captions_enabled", False):
                defaults["captions_required"] = True
            if preset_obj.name == "cinematic_story":
                defaults["use_cinematic_director"] = True
                defaults["cinematic_mode"] = True
                defaults["captions_enabled"] = True
                defaults["captions_required"] = True

            for k, v in defaults.items():
                if k not in data or data[k] is None:
                    data[k] = v
        return data

    @model_validator(mode="after")
    def _verify_required_fields(self) -> WorkflowInput:
        if not self.style:
            raise ValueError("Field 'style' is required when no valid preset is specified.")
        if self.duration is None:
            raise ValueError("Field 'duration' is required when no valid preset is specified.")
        return self

    @field_validator("topic", "language", "platform")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("style")
    @classmethod
    def _strip_style_whitespace(cls, v: str | None) -> str | None:
        return v.strip() if v else v

    @field_validator("aspect_ratio")
    @classmethod
    def _validate_aspect_ratio(cls, v: str | None) -> str:
        from app.core.aspect_ratio import validate_aspect_ratio
        return validate_aspect_ratio(v)



class StageResult(BaseModel):
    """Result of executing one pipeline stage.

    Bridges the internal AgentResult dataclass to the orchestration
    layer's structured output.

    Attributes:
        stage: The stage key that was executed.
        success: Whether the stage completed successfully.
        output: The data produced by the stage.
        error: Error message if the stage failed.
        started_at: When stage execution began.
        completed_at: When stage execution finished.
        execution_time_ms: Time taken to execute the stage in milliseconds.
        provider_used: The provider that served the request.
        cost_usd: Cost incurred for this stage in USD.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(..., description="Stage key that was executed")
    success: bool = Field(..., description="Whether the stage succeeded")
    output: Dict[str, Any] = Field(
        default_factory=dict, description="Stage output data"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if stage failed"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Stage start time"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="Stage completion time"
    )
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Execution time in milliseconds"
    )
    provider_used: Optional[str] = Field(
        default=None, description="Provider that served the request"
    )
    cost_usd: float = Field(
        default=0.0, ge=0.0, description="Cost incurred in USD"
    )


class WorkflowResult(BaseModel):
    """Final result of a workflow execution.

    Returned by the Runner after the Orchestrator completes or fails.

    Attributes:
        workflow_id: UUID of the WorkflowRun.
        status: Final WorkflowStatus value.
        success: Whether the entire workflow succeeded.
        completed_stages: Stage keys that finished successfully.
        failed_stage: Stage key that caused failure, if any.
        stage_results: Detailed results from each executed stage.
        error: Error message if the workflow failed.
        started_at: When the workflow started.
        completed_at: When the workflow finished.
        total_execution_time_ms: Total time taken in milliseconds.
        total_cost_usd: Sum of all stage costs in USD.
        artifacts: Accumulated outputs from all stages.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: uuid.UUID = Field(..., description="UUID of the WorkflowRun")
    status: WorkflowStatus = Field(..., description="Final workflow status")
    success: bool = Field(..., description="Whether the workflow succeeded")
    completed_stages: List[str] = Field(
        default_factory=list, description="Successfully completed stages"
    )
    failed_stage: Optional[str] = Field(
        default=None, description="Stage that failed, if any"
    )
    stage_results: List[StageResult] = Field(
        default_factory=list, description="Results from each stage"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if workflow failed"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Workflow start time"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="Workflow completion time"
    )
    total_execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Total execution time in milliseconds"
    )
    total_cost_usd: float = Field(
        default=0.0, ge=0.0, description="Total cost in USD"
    )
    artifacts: Dict[str, Any] = Field(
        default_factory=dict, description="Accumulated stage outputs"
    )
