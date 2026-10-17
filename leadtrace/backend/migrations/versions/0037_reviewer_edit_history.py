"""Persist reversible reviewer edits and per-workspace history cursors."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = '0037_reviewer_edit_history'
down_revision = '0036_optimization_start'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('workspace_edits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('paper_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reviewer_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('before_state', JSONB, nullable=False),
        sa.Column('after_state', JSONB, nullable=False))
    op.create_index('ix_workspace_edits_workspace_id','workspace_edits',['workspace_id'])
    op.create_table('workspace_edit_cursors',
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('paper_workspaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('reviewer_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('expected_version', sa.Integer(), nullable=False),
        sa.Column('undo_ids', JSONB, nullable=False),
        sa.Column('redo_ids', JSONB, nullable=False))

def downgrade():
    op.drop_table('workspace_edit_cursors')
    op.drop_table('workspace_edits')
