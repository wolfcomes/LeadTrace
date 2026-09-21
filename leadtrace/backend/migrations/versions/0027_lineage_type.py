"""Classify SAR and synthesis Lineages without guessing legacy semantics.

Revision ID: 0027_lineage_type
Revises: 0026_ai_prefill_preview_receipts
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_lineage_type"
down_revision = "0026_ai_prefill_preview_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lineages", sa.Column("lineage_type", sa.String(16), nullable=False, server_default="unspecified"))
    op.create_check_constraint("ck_lineages_type", "lineages", "lineage_type IN ('sar', 'synthesis', 'unspecified')")


def downgrade() -> None:
    op.drop_constraint("ck_lineages_type", "lineages", type_="check")
    op.drop_column("lineages", "lineage_type")
