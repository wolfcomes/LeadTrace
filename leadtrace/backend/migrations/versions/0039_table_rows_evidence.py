"""Ordered Compound rows and source Table Evidence links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0039_table_rows_evidence'
down_revision = '0038_activity_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('activity_tables', sa.Column('compound_ids', JSONB, nullable=True))
    op.add_column('activity_tables', sa.Column('evidence_ids', JSONB, nullable=False, server_default='[]'))


def downgrade():
    op.drop_column('activity_tables', 'evidence_ids')
    op.drop_column('activity_tables', 'compound_ids')
