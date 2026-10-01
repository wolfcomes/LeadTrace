"""Article metadata, independent presentation versions and explicit view receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0029_reviewer_workbench'
down_revision = '0028_review_hints'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('papers', sa.Column('abstract', sa.Text(), nullable=True))
    op.add_column('papers', sa.Column('abstract_source', sa.Text(), nullable=True))
    op.add_column('papers', sa.Column('pdb_references', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.create_table('workspace_view_receipts',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('paper_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reviewer_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False), sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('signature', sa.String(64), nullable=False), sa.Column('viewed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('workspace_id','reviewer_id','kind','entity_id',name='uq_workspace_view_receipt'))
    op.create_table('lineage_presentations',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('paper_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lineage_id', sa.UUID(), sa.ForeignKey('lineages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('positions', postgresql.JSONB(), nullable=False), sa.Column('edge_controls', postgresql.JSONB(), nullable=False),
        sa.Column('updated_by_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('lineage_id','mode',name='uq_lineage_presentation_mode'))

def downgrade():
    op.drop_table('lineage_presentations')
    op.drop_table('workspace_view_receipts')
    for col in ('pdb_references', 'abstract_source', 'abstract'):
        op.drop_column('papers', col)
