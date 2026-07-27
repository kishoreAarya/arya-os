"""
Enums shared across models.

Beginner note: an enum is just a fixed list of allowed values, so a
column can't accidentally hold a typo like "publised" instead of
"published". Postgres enforces these at the database level.
"""
import enum


class WorkflowStatus(str, enum.Enum):
    """Where a video is in the pipeline right now."""
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowMode(str, enum.Enum):
    """How much human involvement a run requires."""
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"


class ValidationStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ArtifactType(str, enum.Enum):
    SCRIPT = "script"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    MUSIC = "music"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
    PROMPT = "prompt"
    LOG = "log"


class ProviderCategory(str, enum.Enum):
    """What kind of work a provider does — matches the Provider Layer
    in the architecture doc (OpenRouter, Gemini, ComfyUI, RunPod, etc.)."""
    LLM = "llm"
    IMAGE_GEN = "image_generation"
    VIDEO_GEN = "video_generation"
    VOICE_GEN = "voice_generation"
    MUSIC_GEN = "music_generation"
    COMPUTE = "compute"  # e.g. RunPod GPU rental


class AssetStatus(str, enum.Enum):
    """Lifecycle status for any versioned artifact (script, storyboard,
    prompt, image, video, thumbnail). This is what lets you see the
    full history: Prompt V1 -> Image V1 -> Rejected, Prompt V2 ->
    Image V2 -> Approved, without ever deleting the rejected attempt."""
    DRAFT = "draft"
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalStage(str, enum.Enum):
    """Every checkpoint a human can intervene at before publish."""
    TREND_SELECTION = "trend_selection"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    PROMPT = "prompt"
    IMAGE = "image"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"


class PipelineStage(str, enum.Enum):
    """The granular state machine for one WorkflowRun's journey through
    the pipeline. This is stored in `WorkflowRun.current_stage` (already
    a free string column — no migration needed to start writing these
    values into it) and validated through STAGE_TRANSITIONS in
    app/services/pipeline_state.py, so a run can never silently skip or
    reverse a stage. `WorkflowStatus` above stays as the coarse
    pending/running/awaiting_approval/completed/failed status; this enum
    is the fine-grained "where exactly" answer used for resuming after
    a crash without re-running completed (and re-billed) stages."""

    CREATED = "created"
    TREND_SELECTED = "trend_selected"
    SCRIPT_GENERATED = "script_generated"
    STORYBOARD_GENERATED = "storyboard_generated"
    PROMPT_GENERATED = "prompt_generated"
    IMAGE_GENERATED = "image_generated"
    VALIDATION_FAILED = "validation_failed"
    RETRY = "retry"
    APPROVED = "approved"
    VIDEO_GENERATED = "video_generated"
    PUBLISHED = "published"
    ANALYTICS_COLLECTED = "analytics_collected"
    LEARNING_UPDATED = "learning_updated"


class ApprovalAction(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    RETRY = "retry"
    MANUAL_EDIT = "manual_edit"
    CONTINUE = "continue"


class LearningType(str, enum.Enum):
    """Keeps Generation Learning (pre-publish, validator-driven) and
    Performance Learning (post-publish, YouTube-analytics-driven)
    strictly separate, per the architecture decision."""
    GENERATION = "generation"
    PERFORMANCE = "performance"


class PublishStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
