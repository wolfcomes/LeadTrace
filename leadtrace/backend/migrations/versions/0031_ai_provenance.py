"""Model-neutral, append-only article AI provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0031_ai_provenance'
down_revision = '0030_compound_highlights'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ai_provenance',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('paper_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_key', sa.String(128), nullable=False),
        sa.Column('recorded_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('record', postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id','paper_id'], ['paper_workspaces.id','paper_workspaces.paper_id'], ondelete='RESTRICT'))
    op.create_index('uq_ai_provenance_workspace_run','ai_provenance',['workspace_id','run_key'],unique=True)


def downgrade():
    op.drop_table('ai_provenance')
