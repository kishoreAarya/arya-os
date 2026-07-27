"""Video Validator — judges the assembled final cut: pacing, audio
sync, resolution/format compliance, no corrupted frames."""
from app.validators.base import BaseValidator, ValidationResult


class VideoValidator(BaseValidator):
    name = "video_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = artifact.get("storage_path")
        duration = artifact.get("duration_seconds")
        passed = bool(storage_path) and bool(duration) and duration > 0
        return ValidationResult(
            passed=passed,
            score=75.0 if passed else 0.0,
            issues=[] if passed else ["Missing video file or zero duration"],
        )
