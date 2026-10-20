"""Add performance indexes for workflow runs, approval checkpoints, and provider usage logs.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-25 22:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Index on workflow_runs(project_id)
    op.create_index("ix_workflow_runs_project_id", "workflow_runs", ["project_id"])

    # 2. Composite index on workflow_runs(project_id, created_at) for efficient project history listing
    op.create_index("ix_workflow_runs_project_created_at", "workflow_runs", ["project_id", "created_at"])

    # 3. Index on approval_checkpoints(workflow_run_id) for rapid checkpoint resolution
    op.create_index("ix_approval_checkpoints_workflow_run_id", "approval_checkpoints", ["workflow_run_id"])

    # 4. Index on provider_usage_logs(workflow_run_id) for fast cost rollup aggregation
    op.create_index("ix_provider_usage_logs_workflow_run_id", "provider_usage_logs", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_usage_logs_workflow_run_id", table_name="provider_usage_logs")
    op.drop_index("ix_approval_checkpoints_workflow_run_id", table_name="approval_checkpoints")
    op.drop_index("ix_workflow_runs_project_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_id", table_name="workflow_runs")
