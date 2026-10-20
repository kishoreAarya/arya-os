"""durable workflow execution and approval resume

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-25 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add lease, heartbeat, and approval resumption columns to workflow_runs
    op.add_column("workflow_runs", sa.Column("last_completed_stage", sa.String(length=100), nullable=True))
    op.add_column("workflow_runs", sa.Column("execution_started_at", sa.DateTime(), nullable=True))
    op.add_column("workflow_runs", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
    op.add_column("workflow_runs", sa.Column("execution_attempt", sa.Integer(), server_default="0", nullable=False))
    op.add_column("workflow_runs", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.add_column("workflow_runs", sa.Column("waiting_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 2. Foreign key to approval_checkpoints
    op.create_foreign_key(
        "fk_workflow_runs_waiting_checkpoint_id",
        "workflow_runs",
        "approval_checkpoints",
        ["waiting_checkpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Indexes for fast recovery and stale heartbeat detection
    op.create_index("ix_workflow_runs_status_heartbeat", "workflow_runs", ["status", "last_heartbeat_at"])
    op.create_index("ix_workflow_runs_waiting_checkpoint_id", "workflow_runs", ["waiting_checkpoint_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_waiting_checkpoint_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status_heartbeat", table_name="workflow_runs")
    op.drop_constraint("fk_workflow_runs_waiting_checkpoint_id", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "waiting_checkpoint_id")
    op.drop_column("workflow_runs", "worker_id")
    op.drop_column("workflow_runs", "execution_attempt")
    op.drop_column("workflow_runs", "last_heartbeat_at")
    op.drop_column("workflow_runs", "execution_started_at")
    op.drop_column("workflow_runs", "last_completed_stage")
