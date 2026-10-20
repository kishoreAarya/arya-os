"""Add dependency_state column to production_shots table.

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-28 22:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "production_shots",
        sa.Column(
            "dependency_state",
            sa.String(length=50),
            server_default="INDEPENDENT",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_production_shots_dependency_state",
        "production_shots",
        ["dependency_state"],
    )


def downgrade() -> None:
    op.drop_index("ix_production_shots_dependency_state", table_name="production_shots")
    op.drop_column("production_shots", "dependency_state")
