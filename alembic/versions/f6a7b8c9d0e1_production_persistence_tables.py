"""Add production persistence tables for sequences, shots, and jobs.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-28 14:47:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add status column to existing projects table
    op.add_column(
        "projects",
        sa.Column("status", sa.String(length=50), server_default="ACTIVE", nullable=False),
    )

    # 2. Create production_sequences table
    op.create_table(
        "production_sequences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=50), server_default="READY", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_production_sequences_project_id", "production_sequences", ["project_id"])
    op.create_index(
        "ix_production_sequences_project_order",
        "production_sequences",
        ["project_id", "order_index"],
    )

    # 3. Create production_shots table
    op.create_table(
        "production_shots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("shot_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("generation_type", sa.String(length=50), server_default="image", nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=50), server_default="16:9", nullable=False),
        sa.Column("resolution", sa.String(length=50), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="READY", nullable=False),
        sa.Column("first_frame", sa.String(length=1000), nullable=True),
        sa.Column("last_frame", sa.String(length=1000), nullable=True),
        sa.Column("reference_assets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("continuity_status", sa.String(length=50), server_default="PASS", nullable=True),
        sa.Column("predecessor_shot_id", sa.String(length=100), nullable=True),
        sa.Column("output_asset_url", sa.String(length=1000), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_id"], ["production_sequences.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_production_shots_project_id", "production_shots", ["project_id"])
    op.create_index("ix_production_shots_sequence_id", "production_shots", ["sequence_id"])
    op.create_index(
        "ix_production_shots_project_sequence",
        "production_shots",
        ["project_id", "sequence_id"],
    )
    op.create_index("ix_production_shots_status", "production_shots", ["status"])

    # 4. Create production_jobs table
    op.create_table(
        "production_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("shot_id", sa.UUID(), nullable=True),
        sa.Column("job_package_id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="CREATED", nullable=False),
        sa.Column("progress", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("external_job_id", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("job_package_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["production_shots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_production_jobs_project_id", "production_jobs", ["project_id"])
    op.create_index("ix_production_jobs_shot_id", "production_jobs", ["shot_id"])
    op.create_index("ix_production_jobs_job_package_id", "production_jobs", ["job_package_id"])
    op.create_index("ix_production_jobs_status", "production_jobs", ["status"])
    op.create_index(
        "ix_production_jobs_project_status",
        "production_jobs",
        ["project_id", "status"],
    )


def downgrade() -> None:
    # Drop in reverse order
    op.drop_index("ix_production_jobs_project_status", table_name="production_jobs")
    op.drop_index("ix_production_jobs_status", table_name="production_jobs")
    op.drop_index("ix_production_jobs_job_package_id", table_name="production_jobs")
    op.drop_index("ix_production_jobs_shot_id", table_name="production_jobs")
    op.drop_index("ix_production_jobs_project_id", table_name="production_jobs")
    op.drop_table("production_jobs")

    op.drop_index("ix_production_shots_status", table_name="production_shots")
    op.drop_index("ix_production_shots_project_sequence", table_name="production_shots")
    op.drop_index("ix_production_shots_sequence_id", table_name="production_shots")
    op.drop_index("ix_production_shots_project_id", table_name="production_shots")
    op.drop_table("production_shots")

    op.drop_index("ix_production_sequences_project_order", table_name="production_sequences")
    op.drop_index("ix_production_sequences_project_id", table_name="production_sequences")
    op.drop_table("production_sequences")

    op.drop_column("projects", "status")
