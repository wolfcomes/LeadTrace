"""Stage and reconcile authoritative baseline imports.

Revision ID: 0005_imports
Revises: 0004_scientific_domains
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_imports"
down_revision = "0004_scientific_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "integrity", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "asset_linkage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_import_batches_source_fingerprint",
        "import_batches",
        ["source_fingerprint"],
        unique=True,
    )
    op.create_foreign_key(
        "fk_assets_import_batch_id",
        "assets",
        "import_batches",
        ["import_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "import_staging_records",
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("original_id", sa.String(length=255), nullable=False),
        sa.Column("source_file", sa.String(length=1024), nullable=False),
        sa.Column("source_row_locator", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "normalized_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_batch_id",
            "record_type",
            "original_id",
            name="uq_import_staging_batch_record",
        ),
    )
    op.create_index(
        "ix_import_staging_batch_type",
        "import_staging_records",
        ["import_batch_id", "record_type"],
    )
    op.create_table(
        "import_release_candidates",
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_batch_id", name="uq_import_release_candidates_batch"
        ),
    )
    op.create_index(
        "uq_import_release_candidates_current",
        "import_release_candidates",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "import_asset_links",
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("original_id", sa.String(length=255), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_role", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_batch_id",
            "record_type",
            "original_id",
            "link_role",
            "asset_id",
            name="uq_import_asset_links_reference",
        ),
    )
    op.create_index(
        "ix_import_asset_links_record",
        "import_asset_links",
        ["record_type", "original_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_asset_links_record", table_name="import_asset_links")
    op.drop_table("import_asset_links")
    op.drop_index(
        "uq_import_release_candidates_current",
        table_name="import_release_candidates",
    )
    op.drop_table("import_release_candidates")
    op.drop_index(
        "ix_import_staging_batch_type",
        table_name="import_staging_records",
    )
    op.drop_table("import_staging_records")
    op.drop_constraint(
        "fk_assets_import_batch_id",
        "assets",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_import_batches_source_fingerprint",
        table_name="import_batches",
    )
    op.drop_table("import_batches")
