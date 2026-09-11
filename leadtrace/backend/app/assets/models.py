from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssetCategory(StrEnum):
    ARTICLE_PDF = "article_pdf"
    SI_PDF = "si_pdf"
    SI_TABLE = "si_table"
    SI_ARCHIVE = "si_archive"
    EXTERNAL_SOURCE = "external_source"
    PAGE_RENDER = "page_render"
    PAGE_THUMBNAIL = "page_thumbnail"
    EVIDENCE_CROP = "evidence_crop"
    OCSR_INPUT = "ocsr_input"
    OCSR_PROPOSAL = "ocsr_proposal"
    REVIEWED_CROP = "reviewed_crop"
    RDKIT_STRUCTURE = "rdkit_structure"
    PAIR_PANEL = "pair_panel"
    IMPORT_MANIFEST = "import_manifest"
    VALIDATION_REPORT = "validation_report"
    RELEASE_EXPORT = "release_export"
    UPLOAD_STAGING = "upload_staging"
    RENDER_CACHE = "render_cache"
    QUARANTINE = "quarantine"


class AssetAccessLevel(StrEnum):
    VISITOR = "visitor"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class AssetIntegrityState(StrEnum):
    REGISTERED = "registered"
    VERIFIED = "verified"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    MISSING = "missing"
    CORRUPT = "corrupt"


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint(
            "storage_key",
            "sha256",
            name="uq_assets_storage_key_sha256",
        ),
        Index("ix_assets_sha256", "sha256"),
        Index("ix_assets_category_integrity", "category", "integrity_state"),
    )

    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[AssetCategory] = mapped_column(
        Enum(
            AssetCategory,
            name="asset_category",
            native_enum=False,
            length=40,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    access_level: Mapped[AssetAccessLevel] = mapped_column(
        Enum(
            AssetAccessLevel,
            name="asset_access_level",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    integrity_state: Mapped[AssetIntegrityState] = mapped_column(
        Enum(
            AssetIntegrityState,
            name="asset_integrity_state",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    import_batch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    derivation_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AssetScanCheckpoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_scan_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "source_root_key",
            "source_key",
            "content_sha256",
            name="uq_asset_scan_checkpoint_source_content",
        ),
        Index(
            "ix_asset_scan_checkpoint_source",
            "source_root_key",
            "source_key",
        ),
    )

    source_root_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
