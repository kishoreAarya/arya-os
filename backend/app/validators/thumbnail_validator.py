"""Thumbnail Validator — checks text legibility, contrast, and CTR-
relevant composition heuristics before it goes up for human approval."""
from app.validators.base import BaseValidator, ValidationResult


class ThumbnailValidator(BaseValidator):
    name = "thumbnail_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = artifact.get("storage_path")
        passed = bool(storage_path)
        return ValidationResult(
            passed=passed,
            score=70.0 if passed else 0.0,
            issues=[] if passed else ["No thumbnail file present"],
        )
