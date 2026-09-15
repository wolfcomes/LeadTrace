from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaperSourceIntegrityState(StrEnum):
    REGISTERED = "registered"
    VERIFIED = "verified"
    MISSING = "missing"
    CORRUPT = "corrupt"


class PaperSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_sources"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_paper_sources_asset"),
        UniqueConstraint(
            "source_root_key",
            "source_key",
            name="uq_paper_sources_logical_key",
        ),
        UniqueConstraint("sha256", name="uq_paper_sources_sha256"),
        CheckConstraint(
            "btrim(source_root_key) <> ''",
            name="ck_paper_sources_root_key_required",
        ),
        CheckConstraint(
            "btrim(source_key) <> ''",
            name="ck_paper_sources_source_key_required",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_paper_sources_sha256",
        ),
        CheckConstraint("byte_size > 0", name="ck_paper_sources_positive_bytes"),
        CheckConstraint("page_count > 0", name="ck_paper_sources_positive_pages"),
        CheckConstraint(
            "integrity_state IN ('registered', 'verified', 'missing', 'corrupt')",
            name="ck_paper_sources_integrity_state",
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_root_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_state: Mapped[PaperSourceIntegrityState] = mapped_column(
        Enum(
            PaperSourceIntegrityState,
            name="paper_source_integrity_state",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=PaperSourceIntegrityState.REGISTERED,
    )


__all__ = ["PaperSource", "PaperSourceIntegrityState"]
