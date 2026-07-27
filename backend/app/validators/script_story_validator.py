"""
Story Validator — judges Script quality independently of the Script
Agent that wrote it. Real scoring logic (calling an LLM-as-judge, or
a rules-based check) plugs in during Sprint 3+; this stub defines the
contract so the pipeline can be wired up now and made smarter later.
"""
from app.validators.base import BaseValidator, ValidationResult


class StoryValidator(BaseValidator):
    name = "story_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        content = artifact.get("content", "")
        # Placeholder heuristic — replace with a real LLM-judge call in Sprint 3+.
        passed = len(content.strip()) > 50
        return ValidationResult(
            passed=passed,
            score=75.0 if passed else 20.0,
            dimension_scores={"story": 75.0 if passed else 20.0},
            issues=[] if passed else ["Script content too short to evaluate"],
        )
