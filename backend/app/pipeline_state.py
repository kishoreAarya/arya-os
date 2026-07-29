"""
Modernized pipeline state machine for AI Viral Video Factory.

This module defines the complete workflow lifecycle and legal state transitions.
WorkflowRun.current_stage is the single source of truth for workflow progress.
"""

from enum import Enum
from typing import Optional


class PipelineStage(str, Enum):
    """Complete workflow lifecycle stages.
    
    Represents each significant milestone in video generation pipeline:
    research → scripting → storyboarding → voice → images → videos → thumbnail
    → approval → publication.
    
    FAILED is a terminal error state reachable from any non-terminal state.
    """

    # Workflow initialization
    CREATED = "created"

    # Content research & trending
    TREND_SELECTED = "trend_selected"

    # Scripting phase
    SCRIPT_GENERATED = "script_generated"

    # Shot planning
    STORYBOARD_GENERATED = "storyboard_generated"

    # Audio generation
    VOICE_GENERATED = "voice_generated"

    # Visual generation
    IMAGE_GENERATED = "image_generated"

    # Video composition
    VIDEO_GENERATED = "video_generated"

    # Metadata/branding
    THUMBNAIL_GENERATED = "thumbnail_generated"

    # Approval gate
    APPROVED = "approved"

    # Final delivery
    PUBLISHED = "published"

    # Terminal error state (can be reached from any non-terminal stage)
    FAILED = "failed"

    def __str__(self) -> str:
        """Human-readable stage name."""
        return self.value.replace("_", " ").title()

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check if value is a valid stage."""
        try:
            cls(value)
            return True
        except ValueError:
            return False


# Legal state transitions. A stage can transition to any stage in its set.
STAGE_TRANSITIONS: dict[PipelineStage, set[PipelineStage]] = {
    PipelineStage.CREATED: {
        PipelineStage.TREND_SELECTED,
        PipelineStage.FAILED,
    },
    PipelineStage.TREND_SELECTED: {
        PipelineStage.SCRIPT_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.SCRIPT_GENERATED: {
        PipelineStage.STORYBOARD_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.STORYBOARD_GENERATED: {
        PipelineStage.VOICE_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.VOICE_GENERATED: {
        PipelineStage.IMAGE_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.IMAGE_GENERATED: {
        PipelineStage.VIDEO_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.VIDEO_GENERATED: {
        PipelineStage.THUMBNAIL_GENERATED,
        PipelineStage.FAILED,
    },
    PipelineStage.THUMBNAIL_GENERATED: {
        PipelineStage.APPROVED,
        PipelineStage.FAILED,
    },
    PipelineStage.APPROVED: {
        PipelineStage.PUBLISHED,
        PipelineStage.FAILED,
    },
    # Terminal states: no outbound transitions
    PipelineStage.PUBLISHED: set(),
    PipelineStage.FAILED: set(),
}


class InvalidStageTransitionError(Exception):
    """Raised when attempting an illegal state transition."""

    def __init__(self, current: PipelineStage, target: PipelineStage) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition from {current} to {target}. "
            f"Valid targets: {', '.join(str(s.value) for s in STAGE_TRANSITIONS[current])}"
        )


class StateTransitionManager:
    """Validates and manages workflow state transitions.
    
    Provides:
    - Legal transition validation
    - Terminal state detection
    - Stage ordering/sequencing helpers
    """

    @staticmethod
    def can_transition(from_stage: PipelineStage, to_stage: PipelineStage) -> bool:
        """Check if transition is legal.
        
        Args:
            from_stage: Current stage
            to_stage: Target stage
            
        Returns:
            True if transition is allowed, False otherwise
        """
        return to_stage in STAGE_TRANSITIONS.get(from_stage, set())

    @staticmethod
    def validate_transition(from_stage: PipelineStage, to_stage: PipelineStage) -> None:
        """Validate transition; raise if illegal.
        
        Args:
            from_stage: Current stage
            to_stage: Target stage
            
        Raises:
            InvalidStageTransitionError: If transition is not allowed
        """
        if not StateTransitionManager.can_transition(from_stage, to_stage):
            raise InvalidStageTransitionError(from_stage, to_stage)

    @staticmethod
    def is_terminal(stage: PipelineStage) -> bool:
        """Check if stage is terminal (no outbound transitions).
        
        Args:
            stage: Pipeline stage
            
        Returns:
            True if stage is PUBLISHED or FAILED
        """
        return stage in (PipelineStage.PUBLISHED, PipelineStage.FAILED)

    @staticmethod
    def is_success_terminal(stage: PipelineStage) -> bool:
        """Check if stage is successful terminal state.
        
        Args:
            stage: Pipeline stage
            
        Returns:
            True if stage is PUBLISHED
        """
        return stage == PipelineStage.PUBLISHED

    @staticmethod
    def is_failure_terminal(stage: PipelineStage) -> bool:
        """Check if stage is failure terminal state.
        
        Args:
            stage: Pipeline stage
            
        Returns:
            True if stage is FAILED
        """
        return stage == PipelineStage.FAILED

    @staticmethod
    def next_stage_in_sequence(stage: PipelineStage) -> Optional[PipelineStage]:
        """Get the canonical next stage in normal workflow progression.
        
        Returns None if stage is terminal.
        
        Args:
            stage: Current pipeline stage
            
        Returns:
            Next stage in sequence, or None if terminal
        """
        sequence = [
            PipelineStage.CREATED,
            PipelineStage.TREND_SELECTED,
            PipelineStage.SCRIPT_GENERATED,
            PipelineStage.STORYBOARD_GENERATED,
            PipelineStage.VOICE_GENERATED,
            PipelineStage.IMAGE_GENERATED,
            PipelineStage.VIDEO_GENERATED,
            PipelineStage.THUMBNAIL_GENERATED,
            PipelineStage.APPROVED,
            PipelineStage.PUBLISHED,
        ]

        try:
            idx = sequence.index(stage)
            return sequence[idx + 1] if idx + 1 < len(sequence) else None
        except ValueError:
            # stage == FAILED or unknown
            return None

    @staticmethod
    def get_valid_targets(stage: PipelineStage) -> set[PipelineStage]:
        """Get all valid target stages from current stage.
        
        Args:
            stage: Current pipeline stage
            
        Returns:
            Set of valid target stages
        """
        return STAGE_TRANSITIONS.get(stage, set()).copy()

    @staticmethod
    def stage_order() -> list[PipelineStage]:
        """Get stages in normal workflow sequence.
        
        Excludes FAILED (error state).
        
        Returns:
            Ordered list of stages for happy-path workflow
        """
        return [
            PipelineStage.CREATED,
            PipelineStage.TREND_SELECTED,
            PipelineStage.SCRIPT_GENERATED,
            PipelineStage.STORYBOARD_GENERATED,
            PipelineStage.VOICE_GENERATED,
            PipelineStage.IMAGE_GENERATED,
            PipelineStage.VIDEO_GENERATED,
            PipelineStage.THUMBNAIL_GENERATED,
            PipelineStage.APPROVED,
            PipelineStage.PUBLISHED,
        ]

    @staticmethod
    def stage_position(stage: PipelineStage) -> Optional[int]:
        """Get 0-based position of stage in workflow sequence.
        
        Args:
            stage: Pipeline stage
            
        Returns:
            Position index, or None if FAILED
        """
        try:
            return StateTransitionManager.stage_order().index(stage)
        except ValueError:
            return None
