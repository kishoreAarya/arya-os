"""
Base validator contract.

Beginner note: an Agent's job is ONLY to generate something (a script,
an image, a video). A Validator's job is ONLY to judge something that
already exists. They must stay separate — an agent never grades its
own homework. n8n calls an agent, gets a draft back, then calls the
matching validator on that draft before deciding whether to move on,
retry, or send it to human approval.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    passed: bool
    score: float  # 0-100, written back to VersionedAssetMixin.quality_score
    dimension_scores: dict[str, float] = field(default_factory=dict)  # e.g. {"story": 82, "consistency": 91}
    issues: list[str] = field(default_factory=list)
    notes: str | None = None


class BaseValidator(ABC):
    """Every validator (Image, Prompt, Consistency, Story, Video,
    Thumbnail, Brand) implements this same shape so the pipeline can
    call any of them identically: `result = validator.validate(artifact)`.
    """

    name: str = "base_validator"

    @abstractmethod
    def validate(self, artifact: dict) -> ValidationResult:
        """`artifact` is a plain dict of whatever fields this validator
        needs (e.g. an image's storage_path, or a script's content).
        Concrete validators fill this in with real provider calls
        (a vision model, a text quality model, etc.) in Sprint 3+."""
        raise NotImplementedError
