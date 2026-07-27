"""
Provider tables: Provider and ProviderUsageLog.

Beginner note: `Provider` is just a lookup table of every external
service you use (OpenRouter, Gemini, ComfyUI, RunPod...) so other
tables can reference "which provider made this" by ID instead of a
loose string. `ProviderUsageLog` is one row per actual API/GPU call —
this is what answers "how much did this video cost to make?" (the
cost-per-video tracking flagged in the architecture review).
"""
import uuid

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ProviderCategory
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Provider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # e.g. "runpod", "gemini"
    category: Mapped[ProviderCategory] = mapped_column(
        Enum(ProviderCategory, name="provider_category"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    is_fallback: Mapped[bool] = mapped_column(default=False)  # used per Fallback Providers in error handling
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderUsageLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per call out to a provider. Roll these up by
    workflow_run_id to get true cost-per-video."""

    __tablename__ = "provider_usage_logs"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. "script_generation"
    units_consumed: Mapped[float | None] = mapped_column(nullable=True)  # tokens, seconds, images, etc.
    unit_label: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "tokens" | "gpu_seconds" | "images"
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    succeeded: Mapped[bool] = mapped_column(default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
