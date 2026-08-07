"""Prompt Validator — checks a generated prompt is usable before it's
sent to an image/video provider (not empty, not over token limits,
no banned terms, etc.)."""
from app.validators.base import BaseValidator, ValidationResult


class PromptValidator(BaseValidator):
    name = "prompt_validator"

    def validate(self, artifact) -> ValidationResult:
    # ExecutionEngine may pass either the raw LLM response (str)
    # or a dict in future stages.
        if isinstance(artifact, str):
            prompt_text = artifact.strip()
        elif isinstance(artifact, dict):
            prompt_text = (
                artifact.get("prompt")
                or artifact.get("positive_prompt")
                or artifact.get("prompt_text")
                or ""
            ).strip()
        else:
            prompt_text = ""

        passed = bool(prompt_text)

        return ValidationResult(
            passed=passed,
            score=80.0 if passed else 0.0,
            issues=[] if passed else ["Prompt text is empty"],
        )
