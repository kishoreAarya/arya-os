"""
Content tables: Script, Storyboard, Prompt.

Beginner note: these map straight to the Media Pipeline in the
architecture doc (Research -> Script -> Storyboard -> Images...). All
three use VersionedAssetMixin, so a rejected script draft isn't lost —
it's just a row with status=REJECTED, and the next attempt is a new
row with parent_version_id pointing back at it.
"""
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import ArtifactType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, VersionedAssetMixin


class Script(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """The written script/narration text for one video."""

    __tablename__ = "scripts"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="scripts")
    storyboards: Mapped[list["Storyboard"]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )


class Storyboard(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """The shot-by-shot breakdown of a script — each entry describes
    one scene/shot before images or video get generated for it."""

    __tablename__ = "storyboards"

    script_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scripts.id"), nullable=False
    )
    # A list of shot dicts, e.g. [{"shot": 1, "description": "...", "shot_type": "close-up"}]
    shots: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    script: Mapped["Script"] = relationship(back_populates="storyboards")


class Prompt(Base, UUIDPrimaryKeyMixin, TimestampMixin, VersionedAssetMixin):
    """The exact prompt text sent to a generation provider (image/video/
    voice/music). Stored so you can reproduce or debug any output later —
    this is what makes the Artifact Registry actually useful, not just
    a pile of output files with no idea what produced them."""

    __tablename__ = "prompts"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="prompt_artifact_type"), nullable=False
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Nullable so hand-written/ad-hoc prompts remain valid — but every
    # prompt rendered from a template records exactly which version,
    # per Prompt Template Versioning (Hardening Pass #3, item 6).
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id"), nullable=True
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
