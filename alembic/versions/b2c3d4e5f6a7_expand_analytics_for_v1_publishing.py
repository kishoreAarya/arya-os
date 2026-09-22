"""expand analytics for v1 multi-platform publishing

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Allow video_id to be nullable for posts without a video table row
    op.alter_column("analytics", "video_id", nullable=True)

    # 2. Add multi-platform and provenance tracking columns
    op.add_column("analytics", sa.Column("workflow_run_id", sa.UUID(), nullable=True))
    op.add_column("analytics", sa.Column("asset_id", sa.UUID(), nullable=True))
    op.add_column("analytics", sa.Column("platform", sa.String(length=50), server_default="youtube", nullable=False))
    op.add_column("analytics", sa.Column("external_post_id", sa.String(length=255), nullable=True))
    op.add_column("analytics", sa.Column("source", sa.String(length=50), server_default="direct", nullable=False))
    op.add_column("analytics", sa.Column("idempotency_key", sa.String(length=255), nullable=True))

    # 3. Add normalized engagement metrics
    op.add_column("analytics", sa.Column("saves", sa.Integer(), nullable=True))
    op.add_column("analytics", sa.Column("engagement_rate", sa.Numeric(precision=6, scale=4), nullable=True))
    op.add_column("analytics", sa.Column("watch_time_seconds", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("analytics", sa.Column("completion_rate", sa.Numeric(precision=6, scale=4), nullable=True))
    op.add_column("analytics", sa.Column("clicks", sa.Integer(), nullable=True))
    op.add_column("analytics", sa.Column("revenue_usd", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("analytics", sa.Column("raw_metadata", sa.Text(), nullable=True))

    # 4. Foreign key constraints
    op.create_foreign_key("fk_analytics_workflow_run_id", "analytics", "workflow_runs", ["workflow_run_id"], ["id"])
    op.create_foreign_key("fk_analytics_asset_id", "analytics", "assets", ["asset_id"], ["id"])

    # 5. Fast query and deduplication indexes
    op.create_index("ix_analytics_idempotency_key", "analytics", ["idempotency_key"])
    op.create_index("ix_analytics_workflow_run_id", "analytics", ["workflow_run_id"])
    op.create_index("ix_analytics_external_post_id", "analytics", ["external_post_id"])


def downgrade() -> None:
    op.drop_index("ix_analytics_external_post_id", table_name="analytics")
    op.drop_index("ix_analytics_workflow_run_id", table_name="analytics")
    op.drop_index("ix_analytics_idempotency_key", table_name="analytics")
    op.drop_constraint("fk_analytics_asset_id", "analytics", type_="foreignkey")
    op.drop_constraint("fk_analytics_workflow_run_id", "analytics", type_="foreignkey")

    op.drop_column("analytics", "raw_metadata")
    op.drop_column("analytics", "revenue_usd")
    op.drop_column("analytics", "clicks")
    op.drop_column("analytics", "completion_rate")
    op.drop_column("analytics", "watch_time_seconds")
    op.drop_column("analytics", "engagement_rate")
    op.drop_column("analytics", "saves")
    op.drop_column("analytics", "idempotency_key")
    op.drop_column("analytics", "source")
    op.drop_column("analytics", "external_post_id")
    op.drop_column("analytics", "platform")
    op.drop_column("analytics", "asset_id")
    op.drop_column("analytics", "workflow_run_id")

    op.alter_column("analytics", "video_id", nullable=False)
