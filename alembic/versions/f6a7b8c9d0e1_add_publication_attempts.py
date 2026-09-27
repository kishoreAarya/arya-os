"""publication_attempts: durable idempotent publication-attempt core

Operator-authorized slice: one additive table for the OPERATOR
publishing path only (the Hermes publishing.request capability remains
dry-run and untouched). The attempt row is written BEFORE the first
irreversible external call; IN_PROGRESS is persisted before that call;
external ids are persisted as soon as safely available.

UNKNOWN is a durable manual-operations state (automated reconciliation
via provider lookups is a deferred contract — no adapter changes in
this slice).

Idempotency is enforced AT THE DATABASE: UNIQUE(intent_key,
attempt_number). intent_key identifies the publication intent
(video/platform/social/integration family); a duplicate submission of
the same intent resolves to the existing attempt — never a second
external publication.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-27 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_attempts",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("video_id", UUID(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("social_platform", sa.String(length=50), nullable=False),
        sa.Column("integration_id", sa.String(length=255), nullable=True),
        sa.Column("intent_key", sa.String(length=500), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "SUCCEEDED",
                "FAILED",
                "UNKNOWN",
                name="publication_attempt_status",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.Text(), nullable=True),
        sa.Column("external_content_id", sa.String(length=255), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("public_url", sa.String(length=1000), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_key", "attempt_number", name="uq_publication_attempts_intent_seq"),
    )
    op.create_index("ix_publication_attempts_video_id", "publication_attempts", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_publication_attempts_video_id", table_name="publication_attempts")
    op.drop_table("publication_attempts")
    op.execute("DROP TYPE IF EXISTS publication_attempt_status")
