"""
Independent validator modules — one per quality dimension in the
architecture brief. These are called BY the pipeline (via n8n or a
FastAPI route), never called BY an agent. An agent generates; a
validator judges; they never share code, so an agent can never rubber-
stamp its own output.
"""
from app.validators.base import BaseValidator, ValidationResult  # noqa: F401
from app.validators.script_story_validator import StoryValidator  # noqa: F401
from app.validators.prompt_validator import PromptValidator  # noqa: F401
from app.validators.image_validator import ImageValidator  # noqa: F401
from app.validators.consistency_validator import ConsistencyValidator  # noqa: F401
from app.validators.video_validator import VideoValidator  # noqa: F401
from app.validators.thumbnail_validator import ThumbnailValidator  # noqa: F401
from app.validators.brand_validator import BrandValidator  # noqa: F401

VALIDATOR_REGISTRY: dict[str, BaseValidator] = {
    "story": StoryValidator(),
    "prompt": PromptValidator(),
    "image": ImageValidator(),
    "consistency": ConsistencyValidator(),
    "video": VideoValidator(),
    "thumbnail": ThumbnailValidator(),
    "brand": BrandValidator(),
}
