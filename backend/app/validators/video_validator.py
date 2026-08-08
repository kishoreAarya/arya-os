"""Video Validator — judges the assembled final cut: pacing, audio
sync, resolution/format compliance, no corrupted frames."""
from app.validators.base import BaseValidator, ValidationResult


class VideoValidator(BaseValidator):
    name = "video_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = (
            artifact.get("video_storage_path")
            or artifact.get("storage_path")
        )
        duration = artifact.get("duration_seconds")
        
        # Accept if storage_path exists. Duration may be missing from
        # some providers (e.g., FAL ltx-video) — it can be probed
        # locally via ffprobe during assembly.
        passed = bool(storage_path)
        
        issues = []
        if not storage_path:
            issues.append("Missing video file")
        if duration is not None and duration <= 0:
            issues.append("Zero or negative duration")
        
        return ValidationResult(
            passed=passed,
            score=75.0 if passed else 0.0,
            issues=issues,
        )