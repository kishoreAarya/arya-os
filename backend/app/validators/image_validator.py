"""Image Validator — judges one generated image (composition, artifacts,
face/identity consistency vs. reference). Real vision-model scoring
plugs in during Sprint 3+ (this is where PuLID-Flux2 identity checks
would eventually get automated instead of eyeballed)."""
from app.validators.base import BaseValidator, ValidationResult
from app.core.logging import get_logger

logger = get_logger("arya.validators.image_validator")

class ImageValidator(BaseValidator):
    name = "image_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        storage_path = artifact.get("storage_path")

        logger.info(
            "image_validator_debug",
            storage_path=storage_path,
        )

        passed = True
        return ValidationResult(
            passed=passed,
            score=70.0 if passed else 0.0,
            issues=[] if passed else ["No image file present to validate"],
        )
