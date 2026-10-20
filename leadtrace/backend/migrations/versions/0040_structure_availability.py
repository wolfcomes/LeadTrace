"""Separate structure availability from human review state."""
from alembic import op
import sqlalchemy as sa
revision = '0040_structure_availability'
down_revision = '0039_table_rows_evidence'
branch_labels = None
depends_on = None

def upgrade():
    for name, type_ in [('availability', sa.String(24)), ('availability_note', sa.Text()), ('identity_source', sa.Text()), ('checked_sources', sa.Text())]:
        op.add_column('structures', sa.Column(name, type_, nullable=True))
    op.create_check_constraint('ck_structures_availability', 'structures', "availability IS NULL OR availability IN ('available', 'not_reported', 'not_checked', 'unresolved')")

def downgrade():
    op.drop_constraint('ck_structures_availability', 'structures', type_='check')
    for name in ('checked_sources', 'identity_source', 'availability_note', 'availability'):
        op.drop_column('structures', name)
