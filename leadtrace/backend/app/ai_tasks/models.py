"""Durable administrative scientific jobs; no credentials or raw reasoning in rows."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import String, Integer, DateTime, ForeignKey, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDPrimaryKeyMixin


class AiTaskSettings(Base):
    __tablename__ = 'ai_task_settings'
    __table_args__ = (CheckConstraint('id = 1',name='ck_ai_task_settings_singleton'),
                     CheckConstraint('max_concurrent BETWEEN 1 AND 16',name='ck_ai_task_capacity'))
    id: Mapped[int] = mapped_column(Integer,primary_key=True,default=1)
    max_concurrent: Mapped[int] = mapped_column(Integer,nullable=False,default=4,server_default='4')
    worker_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = 'ai_tasks'
    __table_args__ = (Index('uq_ai_tasks_idempotency','requested_by_id','idempotency_key',unique=True),
                     Index('ix_ai_tasks_queue','state','created_at'),Index('ix_ai_tasks_paper','paper_id','created_at'))
    paper_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),ForeignKey('papers.id'),nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),ForeignKey('paper_workspaces.id'),nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),ForeignKey('users.id'),nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64),nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64),nullable=False)
    action: Mapped[str] = mapped_column(String(16),nullable=False)
    preset_id: Mapped[str] = mapped_column(String(64),nullable=False)
    adapter: Mapped[str] = mapped_column(String(16),nullable=False)
    model: Mapped[str] = mapped_column(String(200),nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(String(32),nullable=False)
    workspace_version: Mapped[int] = mapped_column(Integer,nullable=False)
    task_version: Mapped[int] = mapped_column(Integer,nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64),nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer,nullable=False)
    state: Mapped[str] = mapped_column(String(32),nullable=False,default='queued')
    delivery_state: Mapped[str] = mapped_column(String(32),nullable=False,default='pending')
    stage: Mapped[str] = mapped_column(String(64),nullable=False,default='queued')
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    attempt: Mapped[int] = mapped_column(Integer,nullable=False,default=1)
    parent_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True),ForeignKey('ai_tasks.id'))
    owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSONB,nullable=False,default=dict)
    result_summary: Mapped[dict] = mapped_column(JSONB,nullable=False,default=dict)
