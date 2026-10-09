"""
Independent validator modules — one per quality dimension in the
architecture brief. These are called BY the pipeline (via n8n or a
FastAPI route), never called BY an agent. An agent generates; a
validator judges; they never share code, so an agent can never rubber-
stamp its own output.
"""
from app.validators.base import BaseValidator, ValidationResult  # noqa: F401
from app.validators.script_story_validator import StoryValidator
from app.validators.prompt_validator import PromptValidator
from app.validators.image_validator import ImageValidator
from app.validators.consistency_validator import ConsistencyValidator
from app.validators.video_validator import VideoValidator
from app.validators.thumbnail_validator import ThumbnailValidator
from app.validators.brand_validator import BrandValidator
from app.validators.audio_validator import AudioValidator
from app.validators.metadata_validator import MetadataValidator
from app.validators.caption_validator import CaptionValidator

VALIDATOR_REGISTRY: dict[str, BaseValidator] = {
    "story": StoryValidator(),
    "prompt": PromptValidator(),
    "image": ImageValidator(),
    "consistency": ConsistencyValidator(),
    "video": VideoValidator(),
    "thumbnail": ThumbnailValidator(),
    "brand": BrandValidator(),
    "audio": AudioValidator(),
    "voice": AudioValidator(),
    "music": AudioValidator(),
    "metadata": MetadataValidator(),
    "caption": CaptionValidator(),
}

