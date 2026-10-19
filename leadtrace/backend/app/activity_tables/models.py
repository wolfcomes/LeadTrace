from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ActivityTable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = 'activity_tables'
    __table_args__ = (
        ForeignKeyConstraint(['workspace_id', 'paper_id'], ['paper_workspaces.id', 'paper_workspaces.paper_id'], ondelete='CASCADE'),
        CheckConstraint("kind IN ('source','custom')", name='ck_activity_table_kind'),
        CheckConstraint("review_status IN ('draft','reviewer_confirmed','unresolved')", name='ck_activity_table_review'),
        CheckConstraint("created_by_kind IN ('reviewer','admin','ai','system')", name='ck_activity_table_creator'),
        CheckConstraint("btrim(name) <> '' AND (kind <> 'source' OR (source_label IS NOT NULL AND btrim(source_label) <> ''))", name='ck_activity_table_identity'),
        CheckConstraint("mode IN ('any','all') AND sort IN ('label','similarity','default')", name='ck_activity_table_display'),
        CheckConstraint('page_number IS NULL OR page_number > 0', name='ck_activity_table_page'),
        Index('ix_activity_tables_workspace', 'workspace_id'),
    )
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    paper_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='custom')
    source_label: Mapped[str | None] = mapped_column(String(512))
    source_title: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    review_hint: Mapped[str | None] = mapped_column(Text)
    columns: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default='any')
    sort: Mapped[str] = mapped_column(String(16), nullable=False, default='label')
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default='draft')
    created_by_kind: Mapped[str] = mapped_column(String(16), nullable=False, default='reviewer')
