"""Durable Admin AI tasks and global concurrency settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0033_admin_ai_tasks'
down_revision='0032_article_lifecycle'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('ai_task_settings',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('max_concurrent',sa.Integer(),nullable=False,server_default='4'),sa.Column('worker_seen_at',sa.DateTime(timezone=True)),sa.CheckConstraint('id=1',name='ck_ai_task_settings_singleton'),sa.CheckConstraint('max_concurrent BETWEEN 1 AND 16',name='ck_ai_task_capacity'))
    op.execute('INSERT INTO ai_task_settings(id,max_concurrent) VALUES (1,4)')
    op.create_table('ai_tasks',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('paper_id',pg.UUID(as_uuid=True),sa.ForeignKey('papers.id'),nullable=False),
        sa.Column('workspace_id',pg.UUID(as_uuid=True),sa.ForeignKey('paper_workspaces.id'),nullable=False),
        sa.Column('requested_by_id',pg.UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        *[sa.Column(n,sa.String(length),nullable=False) for n,length in [('idempotency_key',64),('request_digest',64),('action',16),('preset_id',64),('adapter',16),('model',200),('reasoning_effort',32),('source_sha256',64),('state',32),('delivery_state',32),('stage',64)]],
        *[sa.Column(n,sa.Integer(),nullable=False) for n in ('workspace_version','task_version','timeout_seconds','attempt')],
        sa.Column('parent_job_id',pg.UUID(as_uuid=True),sa.ForeignKey('ai_tasks.id')),
        sa.Column('owner',sa.String(128)),sa.Column('lease_token',pg.UUID(as_uuid=True)),
        sa.Column('error_code',sa.String(64)),sa.Column('error_message',sa.String(1000)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        *[sa.Column(n,sa.DateTime(timezone=True)) for n in ('started_at','finished_at','heartbeat_at')],
        sa.Column('config',pg.JSONB(),nullable=False),sa.Column('result_summary',pg.JSONB(),nullable=False))
    op.create_index('uq_ai_tasks_idempotency','ai_tasks',['requested_by_id','idempotency_key'],unique=True)
    op.create_index('ix_ai_tasks_queue','ai_tasks',['state','created_at'])
    op.create_index('ix_ai_tasks_paper','ai_tasks',['paper_id','created_at'])

def downgrade():
    op.drop_table('ai_tasks');op.drop_table('ai_task_settings')
