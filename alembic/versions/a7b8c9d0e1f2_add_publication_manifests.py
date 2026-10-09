"""publication_manifests: immutable content-bound publication manifests

Phase 54B-I1 (foundation slice): one additive table plus three
additive nullable references. Binds publication approval to the exact
content and effective parameters.

- publication_manifests stores the EXACT canonical serialized bytes
  (Text — authoritative digest input; never JSONB) plus explicit
  indexable identity/digest columns. Digest uniqueness
  (uq_publication_manifests_digest) dedupes concurrent identical
  derivations.
- approval_checkpoints.publication_manifest_id (nullable FK): bound by
  AryaOS before the reviewer decides. NULL = legacy/unbound — those
  approvals fail closed for real publishing in the later
  gate-integration phase. NO BACKFILL: legacy approvals never reviewed
  this content and must not be retroactively content-bound.
- publication_attempts.manifest_id / manifest_digest (nullable): to be
  stamped atomically with the dispatch permit in the later phase.

Additive and non-destructive only. No enum changes, no data changes.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_manifests",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=False),
        sa.Column("video_id", UUID(), nullable=False),
        sa.Column("canonical_bytes", sa.Text(), nullable=False),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("video_storage_path", sa.String(length=1000), nullable=False),
        sa.Column("video_sha256", sa.String(length=64), nullable=False),
        sa.Column("video_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("thumbnail_storage_path", sa.String(length=1000), nullable=True),
        sa.Column("thumbnail_sha256", sa.String(length=64), nullable=True),
        sa.Column("thumbnail_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.UniqueConstraint("manifest_digest", name="uq_publication_manifests_digest"),
    )
    op.create_index(
        "ix_publication_manifests_workflow_run_id",
        "publication_manifests",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_publication_manifests_video_id", "publication_manifests", ["video_id"]
    )

    op.add_column(
        "approval_checkpoints",
        sa.Column("publication_manifest_id", UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_approval_checkpoints_publication_manifest",
        "approval_checkpoints",
        "publication_manifests",
        ["publication_manifest_id"],
        ["id"],
    )

    op.add_column(
        "publication_attempts", sa.Column("manifest_id", UUID(), nullable=True)
    )
    op.add_column(
        "publication_attempts",
        sa.Column("manifest_digest", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_publication_attempts_manifest",
        "publication_attempts",
        "publication_manifests",
        ["manifest_id"],
        ["id"],
    )


def downgrade() -> None:
    # Drops ONLY Phase 54B-I1 objects; every pre-existing table, column,
    # and row is untouched. Safe against databases containing user data.
    op.drop_constraint(
        "fk_publication_attempts_manifest", "publication_attempts", type_="foreignkey"
    )
    op.drop_column("publication_attempts", "manifest_digest")
    op.drop_column("publication_attempts", "manifest_id")
    op.drop_constraint(
        "fk_approval_checkpoints_publication_manifest",
        "approval_checkpoints",
        type_="foreignkey",
    )
    op.drop_column("approval_checkpoints", "publication_manifest_id")
    op.drop_index(
        "ix_publication_manifests_video_id", table_name="publication_manifests"
    )
    op.drop_index(
        "ix_publication_manifests_workflow_run_id", table_name="publication_manifests"
    )
    op.drop_table("publication_manifests")
