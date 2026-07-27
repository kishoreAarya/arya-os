"""
PromptTemplate — the template a Prompt (app/models/content.py) was
rendered from.

Beginner note: `Prompt` stores the exact, final text sent to a
provider for one specific generation. `PromptTemplate` stores the
reusable, parameterized version behind it (e.g. "{style} shot of
{subject}, {lighting}, cinematic") so you can:
  - update wording for future videos without touching past ones
    (old Prompts keep pointing at the old template_version)
  - see which template version a published video actually used
  - deprecate a template without deleting the history that used it
"""
from sqlalchemy import Boolean, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ArtifactType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PromptTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One version of one named template. A new revision = a new row
    with the same `name`, `version` incremented — never an in-place
    edit, so historical Prompts stay reproducible."""

    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(150), nullable=False)  # e.g. "image_shot_prompt"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="prompt_template_artifact_type"), nullable=False
    )  # which pipeline stage this template renders a prompt for
    template_text: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "{style} shot of {subject}..."
    variables: Mapped[dict] = mapped_column(JSONB, default=dict)  # e.g. {"style": "str", "subject": "str"}
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)  # which model this was tuned for
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
