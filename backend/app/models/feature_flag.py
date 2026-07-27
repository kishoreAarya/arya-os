"""
FeatureFlag — DB-backed toggles for experimental / risky behavior.

Beginner note: `Settings` (core/config.py) already has boolean fields
like `enable_autonomous_publishing` as .env-level defaults — good for
"what should this be on boot." This table is for flipping them at
runtime from the dashboard without redeploying (e.g. you're mid-run
and want to kill autonomous publishing right now). Precedence: DB row
if one exists for that name, otherwise fall back to the Settings
default — see app/services/feature_flags.py.
"""
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FeatureFlag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "feature_flags"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
