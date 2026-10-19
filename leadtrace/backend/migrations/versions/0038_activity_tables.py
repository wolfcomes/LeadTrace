"""Persist original-paper table definitions without duplicating measurements."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0038_activity_tables'
down_revision = '0037_reviewer_edit_history'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('activity_tables',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=False),
        sa.Column('paper_id', UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('source_label', sa.String(512)),
        sa.Column('source_title', sa.Text()),
        sa.Column('page_number', sa.Integer()),
        sa.Column('review_hint', sa.Text()),
        sa.Column('columns', JSONB, nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.Column('sort', sa.String(16), nullable=False),
        sa.Column('review_status', sa.String(32), nullable=False),
        sa.Column('created_by_kind', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'paper_id'], ['paper_workspaces.id', 'paper_workspaces.paper_id'], ondelete='CASCADE'),
        sa.CheckConstraint("kind IN ('source','custom')", name='ck_activity_table_kind'),
        sa.CheckConstraint("review_status IN ('draft','reviewer_confirmed','unresolved')", name='ck_activity_table_review'),
        sa.CheckConstraint("created_by_kind IN ('reviewer','admin','ai','system')", name='ck_activity_table_creator'),
        sa.CheckConstraint("btrim(name) <> '' AND (kind <> 'source' OR (source_label IS NOT NULL AND btrim(source_label) <> ''))", name='ck_activity_table_identity'),
        sa.CheckConstraint("mode IN ('any','all') AND sort IN ('label','similarity','default')", name='ck_activity_table_display'),
        sa.CheckConstraint('page_number IS NULL OR page_number > 0', name='ck_activity_table_page'))
    op.create_index('ix_activity_tables_workspace', 'activity_tables', ['workspace_id'])


def downgrade():
    op.drop_table('activity_tables')
