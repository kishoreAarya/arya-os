"""Add durable approval provenance and principal type classification.

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-10-05 22:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "i9d0e1f2a3b4"
down_revision: Union[str, None] = "h8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add principal_type to api_keys with fail-secure default 'service_account'
    op.add_column(
        "api_keys",
        sa.Column(
            "principal_type",
            sa.String(length=50),
            server_default="service_account",
            nullable=False,
        ),
    )

    # 2. Add durable approval provenance columns to approval_checkpoints
    op.add_column(
        "approval_checkpoints",
        sa.Column("decided_by_principal_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "approval_checkpoints",
        sa.Column("decided_by_actor_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "approval_checkpoints",
        sa.Column("decided_by_principal_name", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_approval_checkpoints_decided_by_principal_id_api_keys",
        "approval_checkpoints",
        "api_keys",
        ["decided_by_principal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_approval_checkpoints_decided_by_principal_id",
        "approval_checkpoints",
        ["decided_by_principal_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_checkpoints_decided_by_principal_id",
        table_name="approval_checkpoints",
    )
    op.drop_constraint(
        "fk_approval_checkpoints_decided_by_principal_id_api_keys",
        "approval_checkpoints",
        type_="foreignkey",
    )
    op.drop_column("approval_checkpoints", "decided_by_principal_name")
    op.drop_column("approval_checkpoints", "decided_by_actor_type")
    op.drop_column("approval_checkpoints", "decided_by_principal_id")
    op.drop_column("api_keys", "principal_type")
