"""approval decision history: append-only events + REVOKE action

Operator-locked architecture: ApprovalCheckpoint stays the fast
current-state authorization cache; every decision becomes an immutable
ApprovalDecision event. Adds the first-class REVOKE enum value (distinct
from REJECT). Backfill: exactly ONE synthetic event per already-decided
checkpoint that carries decided_at (action/decided_at/reviewer_notes
copied verbatim — no invented timestamps). Checkpoints decided WITHOUT
decided_at (6 legacy seed rows: action=APPROVE, decided_at NULL,
updated_at==created_at, NULL digest — direct pre-Model-B DB seeding)
receive NO event and are NOT mutated: their pre-cutover decision
timestamp is unrecoverable and their history begins with the next real
decision; their standing APPROVE cache remains exactly as-is
(operator Option 1). Pending checkpoints receive no event.

Downgrade asymmetry: PostgreSQL cannot remove an enum value, so
downgrade drops only the approval_decisions table; 'REVOKE' remains a
dormant approval_action label.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-27 14:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, UUID


revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # First-class REVOKE (distinct from REJECT). PG16 permits ADD VALUE
    # in-transaction as long as the new value is not used in this txn
    # (the backfill below never writes 'REVOKE').
    op.execute("ALTER TYPE approval_action ADD VALUE IF NOT EXISTS 'REVOKE'")

    op.create_table(
        "approval_decisions",
        sa.Column("id", UUID(), nullable=False),
        sa.Column(
            "checkpoint_id",
            UUID(),
            sa.ForeignKey("approval_checkpoints.id"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            ENUM(
                "APPROVE",
                "REJECT",
                "RETRY",
                "MANUAL_EDIT",
                "CONTINUE",
                "REVOKE",
                name="approval_action",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", "sequence_number", name="uq_approval_decisions_checkpoint_seq"),
    )

    # Backfill: one synthetic event per decided checkpoint WITH decided_at.
    # Timestamps are copied verbatim — nothing is invented. The 6 legacy
    # decided-without-decided_at rows are deliberately excluded (operator
    # Option 1) and are not touched by this migration in any way.
    op.execute(
        """
        INSERT INTO approval_decisions
            (id, checkpoint_id, sequence_number, action, decided_at,
             decided_by, reviewer_notes, created_at, updated_at)
        SELECT gen_random_uuid(), id, 1, action, decided_at,
               NULL, reviewer_notes, decided_at, decided_at
        FROM approval_checkpoints
        WHERE action IS NOT NULL AND decided_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("approval_decisions")
    # NOTE: the 'REVOKE' approval_action enum value intentionally remains
    # (PostgreSQL cannot drop enum values); it is dormant after downgrade.
