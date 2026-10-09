"""Unassigned drafts and archived article generations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0032_article_lifecycle'
down_revision = '0031_ai_provenance'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('uq_review_tasks_active_paper', table_name='review_tasks')
    op.drop_constraint('ck_review_tasks_status','review_tasks',type_='check')
    op.drop_constraint('ck_paper_workspaces_state','paper_workspaces',type_='check')
    op.alter_column('review_tasks','assigned_reviewer_id',existing_type=postgresql.UUID(as_uuid=True),nullable=True)
    op.create_check_constraint('ck_review_tasks_status','review_tasks',"status IN ('unassigned','assigned','submitted','changes_requested','approved','archived')")
    op.create_check_constraint('ck_paper_workspaces_state','paper_workspaces',"state IN ('editing','submitted','approved','archived')")
    op.create_index('uq_review_tasks_active_paper','review_tasks',['paper_id'],unique=True,postgresql_where=sa.text("status NOT IN ('approved','archived')"))
    op.create_table('article_archives',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True),
        sa.Column('paper_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('papers.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('workspace_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('paper_workspaces.id',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('created_by_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('relative_path',sa.String(512),nullable=False,unique=True),
        sa.Column('manifest_sha256',sa.String(64),nullable=False),
        sa.Column('catalog_metadata',postgresql.JSONB(),nullable=False))
    op.create_index('ix_article_archives_paper_id','article_archives',['paper_id'])


def downgrade():
    # Refuse lossy downgrade once new lifecycle states have been used.
    connection=op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM review_tasks WHERE assigned_reviewer_id IS NULL OR status IN ('unassigned','archived')")):
        raise RuntimeError('Archive/unassigned generations must be resolved before downgrade')
    op.drop_table('article_archives')
    op.drop_index('uq_review_tasks_active_paper',table_name='review_tasks')
    op.drop_constraint('ck_review_tasks_status','review_tasks',type_='check')
    op.drop_constraint('ck_paper_workspaces_state','paper_workspaces',type_='check')
    op.alter_column('review_tasks','assigned_reviewer_id',existing_type=postgresql.UUID(as_uuid=True),nullable=False)
    op.create_check_constraint('ck_review_tasks_status','review_tasks',"status IN ('assigned','submitted','changes_requested','approved')")
    op.create_check_constraint('ck_paper_workspaces_state','paper_workspaces',"state IN ('editing','submitted','approved')")
    op.create_index('uq_review_tasks_active_paper','review_tasks',['paper_id'],unique=True,postgresql_where=sa.text("status <> 'approved'"))
