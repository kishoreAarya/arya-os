"""Image Validator — judges one generated image (composition, artifacts,
face/identity consistency vs. reference). Real vision-model scoring
plugs in during Sprint 3+ (this is where PuLID-Flux2 identity checks
would eventually get automated instead of eyeballed)."""
from app.validators.base import BaseValidator, ValidationResult


class ImageValidator(BaseValidator):
    name = "image_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = artifact.get("storage_path")
        passed = bool(storage_path)
        return ValidationResult(
            passed=passed,
            score=70.0 if passed else 0.0,
            issues=[] if passed else ["No image file present to validate"],
        )
