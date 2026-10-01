"""Keep concise review hints on existing scientific records.

Revision ID: 0028_review_hints
Revises: 0027_lineage_type
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_review_hints"
down_revision = "0027_lineage_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("compounds", "activities", "lineage_edges"):
        op.add_column(table, sa.Column("review_hint", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in ("lineage_edges", "activities", "compounds"):
        op.drop_column(table, "review_hint")
