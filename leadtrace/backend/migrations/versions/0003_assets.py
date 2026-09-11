"""Register and protect file assets.

Revision ID: 0003_assets
Revises: 0002_identity_hardening
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_assets"
down_revision = "0002_identity_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("access_level", sa.String(length=16), nullable=False),
        sa.Column("integrity_state", sa.String(length=16), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "derivation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_key",
            "sha256",
            name="uq_assets_storage_key_sha256",
        ),
    )
    op.create_index(
        "ix_assets_category_integrity",
        "assets",
        ["category", "integrity_state"],
    )
    op.create_index("ix_assets_sha256", "assets", ["sha256"])
    op.create_table(
        "asset_scan_checkpoints",
        sa.Column("source_root_key", sa.String(length=128), nullable=False),
        sa.Column("source_key", sa.String(length=1024), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_root_key",
            "source_key",
            "content_sha256",
            name="uq_asset_scan_checkpoint_source_content",
        ),
    )
    op.create_index(
        "ix_asset_scan_checkpoint_source",
        "asset_scan_checkpoints",
        ["source_root_key", "source_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_scan_checkpoint_source",
        table_name="asset_scan_checkpoints",
    )
    op.drop_table("asset_scan_checkpoints")
    op.drop_index("ix_assets_sha256", table_name="assets")
    op.drop_index("ix_assets_category_integrity", table_name="assets")
    op.drop_table("assets")
