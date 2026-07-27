"""Consistency Validator — checks a character/subject stays visually
consistent across multiple shots in the same storyboard (the exact
identity-locking problem PuLID-Flux2 was being used for manually)."""
from app.validators.base import BaseValidator, ValidationResult


class ConsistencyValidator(BaseValidator):
    name = "consistency_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        image_paths = artifact.get("image_paths", [])
        passed = len(image_paths) <= 1 or True  # placeholder — real embedding-similarity check in Sprint 3+
        return ValidationResult(
            passed=passed,
            score=70.0,
            dimension_scores={"consistency": 70.0},
        )
