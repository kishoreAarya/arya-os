"""
Import every model module here so Alembic's autogenerate (and anything
else that inspects Base.metadata) sees every table.
"""
from app.models.core import Project, WorkflowRun  # noqa: F401
from app.models.content import Script, Storyboard, Prompt  # noqa: F401
from app.models.media import Image, GeneratedVideo, Asset, Video, Thumbnail  # noqa: F401
from app.models.provider import Provider, ProviderUsageLog  # noqa: F401
from app.models.system import Artifact, SystemLog  # noqa: F401
from app.models.analytics import (  # noqa: F401
    Analytics,
    PerformanceLearningFeedback,
    GenerationLearningEvent,
)
from app.models.approval import ApprovalCheckpoint, GenerationAttempt  # noqa: F401
from app.models.quality import QualityScoreDetail  # noqa: F401
from app.models.prompt_template import PromptTemplate  # noqa: F401
from app.models.feature_flag import FeatureFlag  # noqa: F401
