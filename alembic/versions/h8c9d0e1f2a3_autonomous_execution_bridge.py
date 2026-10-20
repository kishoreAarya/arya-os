"""Create autonomous execution bridge tables (missions, autonomous_goals, autonomous_action_nodes, governance_decisions).

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-10-04 23:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "h8c9d0e1f2a3"
down_revision: Union[str, None] = "g7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create missions table
    op.create_table(
        "missions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PLANNED", nullable=False),
        sa.Column("priority", sa.String(length=20), server_default="NORMAL", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "progress_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "completion_criteria_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "execution_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_missions_project_id", "missions", ["project_id"])
    op.create_index(
        "ix_missions_project_status",
        "missions",
        ["project_id", "status"],
    )
    op.create_index("ix_missions_status", "missions", ["status"])

    # 2. Create autonomous_goals table
    op.create_table(
        "autonomous_goals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("mission_id", sa.UUID(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="DRAFT", nullable=False),
        sa.Column("current_plan_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "plan_dag_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "context_memory_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("final_summary", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autonomous_goals_project_id", "autonomous_goals", ["project_id"])
    op.create_index("ix_autonomous_goals_mission_id", "autonomous_goals", ["mission_id"])
    op.create_index(
        "ix_autonomous_goals_project_status",
        "autonomous_goals",
        ["project_id", "status"],
    )
    op.create_index("ix_autonomous_goals_status", "autonomous_goals", ["status"])

    # 3. Create autonomous_action_nodes table
    op.create_table(
        "autonomous_action_nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("goal_id", sa.UUID(), nullable=False),
        sa.Column("client_action_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("required_capability", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("risk_level", sa.String(length=20), server_default="LOW", nullable=False),
        sa.Column(
            "inputs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("outputs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), server_default="0.0", nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("production_job_id", sa.UUID(), nullable=True),
        sa.Column("approval_checkpoint_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["autonomous_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["production_job_id"], ["production_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_checkpoint_id"], ["approval_checkpoints.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autonomous_action_nodes_goal_id", "autonomous_action_nodes", ["goal_id"])
    op.create_index(
        "ix_autonomous_action_nodes_goal_status",
        "autonomous_action_nodes",
        ["goal_id", "status"],
    )
    op.create_index("ix_autonomous_action_nodes_status", "autonomous_action_nodes", ["status"])
    op.create_index("ix_autonomous_action_nodes_production_job_id", "autonomous_action_nodes", ["production_job_id"])
    op.create_index("ix_autonomous_action_nodes_approval_checkpoint_id", "autonomous_action_nodes", ["approval_checkpoint_id"])

    # 4. Create governance_decisions table
    op.create_table(
        "governance_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("goal_id", sa.UUID(), nullable=True),
        sa.Column("action_node_id", sa.UUID(), nullable=True),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("risk_level", sa.String(length=20), server_default="LOW", nullable=False),
        sa.Column(
            "policy_evaluations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["autonomous_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_node_id"], ["autonomous_action_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_governance_decisions_project_id", "governance_decisions", ["project_id"])
    op.create_index("ix_governance_decisions_goal_id", "governance_decisions", ["goal_id"])
    op.create_index("ix_governance_decisions_action_node_id", "governance_decisions", ["action_node_id"])


def downgrade() -> None:
    op.drop_index("ix_governance_decisions_action_node_id", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_goal_id", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_project_id", table_name="governance_decisions")
    op.drop_table("governance_decisions")

    op.drop_index("ix_autonomous_action_nodes_approval_checkpoint_id", table_name="autonomous_action_nodes")
    op.drop_index("ix_autonomous_action_nodes_production_job_id", table_name="autonomous_action_nodes")
    op.drop_index("ix_autonomous_action_nodes_status", table_name="autonomous_action_nodes")
    op.drop_index("ix_autonomous_action_nodes_goal_status", table_name="autonomous_action_nodes")
    op.drop_index("ix_autonomous_action_nodes_goal_id", table_name="autonomous_action_nodes")
    op.drop_table("autonomous_action_nodes")

    op.drop_index("ix_autonomous_goals_status", table_name="autonomous_goals")
    op.drop_index("ix_autonomous_goals_project_status", table_name="autonomous_goals")
    op.drop_index("ix_autonomous_goals_mission_id", table_name="autonomous_goals")
    op.drop_index("ix_autonomous_goals_project_id", table_name="autonomous_goals")
    op.drop_table("autonomous_goals")

    op.drop_index("ix_missions_status", table_name="missions")
    op.drop_index("ix_missions_project_status", table_name="missions")
    op.drop_index("ix_missions_project_id", table_name="missions")
    op.drop_table("missions")
