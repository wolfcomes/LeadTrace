"""Recoverable paper removal without altering scientific or audit history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0034_paper_removal'
down_revision = '0033_admin_ai_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('papers', sa.Column('removed_by_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('papers', sa.Column('removal_reason', sa.Text(), nullable=True))
    op.create_foreign_key('fk_papers_removed_by_id_users', 'papers', 'users', ['removed_by_id'], ['id'], ondelete='RESTRICT')
    op.create_check_constraint('ck_papers_removal_metadata', 'papers',
        "(removed_at IS NULL AND removed_by_id IS NULL AND removal_reason IS NULL) OR "
        "(removed_at IS NOT NULL AND removed_by_id IS NOT NULL AND removal_reason IS NOT NULL AND btrim(removal_reason) <> '')")


def downgrade():
    op.drop_constraint('ck_papers_removal_metadata', 'papers', type_='check')
    op.drop_constraint('fk_papers_removed_by_id_users', 'papers', type_='foreignkey')
    for name in ['removal_reason', 'removed_by_id', 'removed_at']:
        op.drop_column('papers', name)
