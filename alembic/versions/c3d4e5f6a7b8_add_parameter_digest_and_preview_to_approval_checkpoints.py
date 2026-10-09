"""add parameter_digest and parameter_preview to approval checkpoints

Approval Model B: an approval now binds the exact validated parameter
snapshot it authorizes. `parameter_digest` is the authorization binding
(SHA-256 hex via app.hermes.audit.compute_parameter_digest over
{"capability", "parameters"}); `parameter_preview` is bounded
human-review evidence only. Both nullable: existing rows keep NULL and
retain legacy Model-A semantics. No backfill; no other changes.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_checkpoints",
        sa.Column("parameter_digest", sa.Text(), nullable=True),
    )
    op.add_column(
        "approval_checkpoints",
        sa.Column("parameter_preview", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_checkpoints", "parameter_preview")
    op.drop_column("approval_checkpoints", "parameter_digest")
