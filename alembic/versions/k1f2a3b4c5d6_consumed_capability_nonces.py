"""Create consumed_capability_nonces table for durable single-use capability protection.

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-10-09 16:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "k1f2a3b4c5d6"
down_revision: Union[str, None] = "j0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consumed_capability_nonces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("execution_nonce", sa.String(length=128), nullable=False),
        sa.Column("action_node_id", sa.String(length=64), nullable=False),
        sa.Column("goal_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("reservation_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("capability_signature", sa.String(length=128), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("lease_token", sa.String(length=100), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_nonce", name="uq_consumed_capability_nonce"),
    )
    op.create_index("ix_consumed_capability_nonces_nonce", "consumed_capability_nonces", ["execution_nonce"])
    op.create_index("ix_consumed_capability_nonces_action_node_id", "consumed_capability_nonces", ["action_node_id"])
    op.create_index("ix_consumed_capability_nonces_goal_id", "consumed_capability_nonces", ["goal_id"])
    op.create_index("ix_consumed_capability_nonces_project_id", "consumed_capability_nonces", ["project_id"])
    op.create_index("ix_consumed_capability_nonces_reservation_id", "consumed_capability_nonces", ["reservation_id"])


def downgrade() -> None:
    op.drop_index("ix_consumed_capability_nonces_reservation_id", table_name="consumed_capability_nonces")
    op.drop_index("ix_consumed_capability_nonces_project_id", table_name="consumed_capability_nonces")
    op.drop_index("ix_consumed_capability_nonces_goal_id", table_name="consumed_capability_nonces")
    op.drop_index("ix_consumed_capability_nonces_action_node_id", table_name="consumed_capability_nonces")
    op.drop_index("ix_consumed_capability_nonces_nonce", table_name="consumed_capability_nonces")
    op.drop_table("consumed_capability_nonces")
