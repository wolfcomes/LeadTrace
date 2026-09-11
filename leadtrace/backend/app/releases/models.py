from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.revisions.models import ObjectKind


class Release(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "releases"
    __table_args__ = (
        Index("uq_releases_key", "release_key", unique=True),
        Index(
            "uq_releases_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    release_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_candidate_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("import_release_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    published_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manifest_finalized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ReleaseItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "release_items"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "object_id",
            name="uq_release_items_object",
        ),
        UniqueConstraint(
            "release_id",
            "revision_id",
            name="uq_release_items_revision",
        ),
        UniqueConstraint(
            "release_id",
            "manifest_order",
            name="uq_release_items_manifest_order",
        ),
        ForeignKeyConstraint(
            ["object_id", "revision_id"],
            ["object_revisions.object_id", "object_revisions.id"],
            name="fk_release_items_object_revision",
            ondelete="RESTRICT",
        ),
        Index("ix_release_items_paper_kind", "release_id", "paper_id", "object_kind"),
    )

    release_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("releases.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_kind: Mapped[ObjectKind] = mapped_column(
        Enum(
            ObjectKind,
            name="release_item_object_kind",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    manifest_order: Mapped[int] = mapped_column(Integer, nullable=False)
