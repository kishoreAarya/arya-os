"""approval TTL policy table + ratified global default

Ratified TTL contract: authorization freshness is derived at gate
evaluation time from the (cache-mirrored) latest APPROVE event timestamp
plus this policy — nothing is persisted on approvals or decisions.

Duration semantics (operator-ratified):
- The seeded global default is 604800 seconds = 7 days.
- This is the INITIAL OPERATIONAL POLICY DEFAULT — policy DATA, not
  application logic. The authorization implementation is entirely
  duration-agnostic; future TTL changes are made by updating this row
  (or adding per-stage overrides) WITHOUT changing application code or
  migration structure.
- Changing the policy value later MAY IMMEDIATELY AFFECT EXISTING
  STANDING APPROVALS (an approval older than the new window expires at
  its next evaluation). No preview/versioning is provided by design.
- Fail-closed: a timestamped approval with NO configured policy is
  never valid (terminal approval_ttl_policy_missing). Anchor-less
  legacy approvals (decided_at IS NULL — the six pre-cutover rows)
  are perpetual by separate contract and are NOT touched here.
- CHECK (ttl_seconds > 0): zero/negative durations are rejected as
  invalid policy data.

The five backfilled approvals with real decided_at (2026-09-25..27)
participate in TTL and remain valid under the 7-day default at cutover.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-27 16:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_ttl_policies",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ttl_seconds > 0", name="ck_approval_ttl_policies_positive"),
    )
    op.create_index(
        "uq_approval_ttl_policies_scope",
        "approval_ttl_policies",
        [sa.text("COALESCE(stage, '')")],
        unique=True,
    )
    # The ratified initial operational default: 604800 s = 7 days
    # (policy data — changeable without touching application logic).
    op.execute(
        "INSERT INTO approval_ttl_policies (id, stage, ttl_seconds, created_at, updated_at) "
        "VALUES (gen_random_uuid(), NULL, 604800, now(), now())"
    )


def downgrade() -> None:
    op.drop_index("uq_approval_ttl_policies_scope", table_name="approval_ttl_policies")
    op.drop_table("approval_ttl_policies")
