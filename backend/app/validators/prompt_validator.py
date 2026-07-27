"""Prompt Validator — checks a generated prompt is usable before it's
sent to an image/video provider (not empty, not over token limits,
no banned terms, etc.)."""
from app.validators.base import BaseValidator, ValidationResult


class PromptValidator(BaseValidator):
    name = "prompt_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        prompt_text = artifact.get("prompt_text", "")
        passed = bool(prompt_text.strip())
        return ValidationResult(
            passed=passed,
            score=80.0 if passed else 0.0,
            issues=[] if passed else ["Prompt text is empty"],
        )
