"""Create atomic budget reservations table and project budget limit column.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-10-08 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "j0e1f2a3b4c5"
down_revision: Union[str, None] = "i9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add budget_limit_usd to projects table
    op.add_column(
        "projects",
        sa.Column("budget_limit_usd", sa.Numeric(10, 4), nullable=True),
    )

    # 2. Create budget_reservations table
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("goal_id", sa.UUID(), nullable=False),
        sa.Column("plan_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reserved_amount_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("consumed_amount_usd", sa.Numeric(10, 4), server_default="0.0000", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="RESERVED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["autonomous_goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "plan_version", name="uq_budget_reservations_goal_plan_version"),
    )
    op.create_index("ix_budget_reservations_project_id", "budget_reservations", ["project_id"])
    op.create_index("ix_budget_reservations_goal_id", "budget_reservations", ["goal_id"])
    op.create_index(
        "ix_budget_reservations_project_status",
        "budget_reservations",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_reservations_project_status", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_goal_id", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_project_id", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    op.drop_column("projects", "budget_limit_usd")
