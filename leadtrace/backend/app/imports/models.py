from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class ImportBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index(
            "uq_import_batches_source_fingerprint",
            "source_fingerprint",
            unique=True,
        ),
    )

    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    integrity: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    asset_linkage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ImportStagingRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_staging_records"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id",
            "record_type",
            "original_id",
            name="uq_import_staging_batch_record",
        ),
        Index(
            "ix_import_staging_batch_type",
            "import_batch_id",
            "record_type",
        ),
    )

    import_batch_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    original_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_row_locator: Mapped[str] = mapped_column(String(128), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_values: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    normalized_values: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )


class ImportReleaseCandidate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_release_candidates"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id",
            name="uq_import_release_candidates_batch",
        ),
        Index(
            "uq_import_release_candidates_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    import_batch_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ImportAssetLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_asset_links"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id",
            "record_type",
            "original_id",
            "link_role",
            "asset_id",
            name="uq_import_asset_links_reference",
        ),
        Index("ix_import_asset_links_record", "record_type", "original_id"),
    )

    import_batch_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    original_id: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    link_role: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
