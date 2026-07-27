"""
QualityScoreDetail — the breakdown behind each artifact's single
`quality_score` column.

Beginner note: `VersionedAssetMixin.quality_score` holds one overall
0-100 number per artifact. But the brief also wants dimension-specific
scores like "Consistency Quality" or "Story Quality" that don't map
to one single table — Story Quality applies to a Script, Consistency
Quality might span several Images. This table holds those, so
PerformanceLearningFeedback can later correlate specific dimensions
(e.g. "High Image Quality -> Higher CTR") against YouTube analytics.
"""
import uuid

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class QualityScoreDetail(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "quality_score_details"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    reference_table: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dimension: Mapped[str] = mapped_column(String(50), nullable=False)  # "story" | "consistency" | "overall_video" | etc.
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)  # 0-100
    scored_by: Mapped[str | None] = mapped_column(String(100), nullable=True)  # which validator produced this
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
