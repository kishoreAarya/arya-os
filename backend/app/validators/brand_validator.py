"""Brand Validator — checks output against your own channel's style
guide (tone, banned words/topics, required intro/outro elements).
This is the one validator you'll want to customize most, since "brand"
is entirely defined by you, not a generic quality bar."""
from app.validators.base import BaseValidator, ValidationResult


class BrandValidator(BaseValidator):
    name = "brand_validator"

    def validate(self, artifact: dict) -> ValidationResult:
        # Placeholder — wire up your own banned-terms list / tone check here.
        return ValidationResult(passed=True, score=100.0)
