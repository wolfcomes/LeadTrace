from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaperCatalogState(StrEnum):
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    SOURCE_ERROR = "source_error"


class Paper(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("paper_key", name="uq_papers_paper_key"),
        UniqueConstraint("source_id", name="uq_papers_source"),
        UniqueConstraint("doi", name="uq_papers_doi"),
        CheckConstraint("btrim(paper_key) <> ''", name="ck_papers_key_required"),
        CheckConstraint("btrim(title) <> ''", name="ck_papers_title_required"),
        CheckConstraint("btrim(journal) <> ''", name="ck_papers_journal_required"),
        CheckConstraint(
            "publication_year BETWEEN 1000 AND 9999",
            name="ck_papers_publication_year",
        ),
        CheckConstraint("btrim(volume) <> ''", name="ck_papers_volume_required"),
        CheckConstraint("btrim(issue) <> ''", name="ck_papers_issue_required"),
        CheckConstraint(
            "doi IS NULL OR btrim(doi) <> ''",
            name="ck_papers_doi_nonempty",
        ),
        CheckConstraint(
            "catalog_state IN ('extracted', 'verified', 'source_error')",
            name="ck_papers_catalog_state",
        ),
        ForeignKeyConstraint(
            ["current_published_version_id", "id"],
            ["published_paper_versions.id", "published_paper_versions.paper_id"],
            name="fk_papers_current_published_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_papers_current_published_version", "current_published_version_id"),
    )

    paper_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    journal: Mapped[str] = mapped_column(String(255), nullable=False)
    publication_year: Mapped[int] = mapped_column(Integer, nullable=False)
    volume: Mapped[str] = mapped_column(String(64), nullable=False)
    issue: Mapped[str] = mapped_column(String(64), nullable=False)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text(), nullable=True)
    abstract_source: Mapped[str | None] = mapped_column(Text(), nullable=True)
    pdb_references: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default='[]')
    catalog_state: Mapped[PaperCatalogState] = mapped_column(
        Enum(
            PaperCatalogState,
            name="paper_catalog_state",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=PaperCatalogState.EXTRACTED,
    )
    current_published_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )


__all__ = ["Paper", "PaperCatalogState"]
