from __future__ import annotations

import unicodedata
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import ObjectKind, RevisionedObject


def normalize_local_label(label: str) -> str:
    normalized = unicodedata.normalize("NFC", label.strip())
    if not normalized:
        raise ValueError("Paper-local compound label is required")
    return normalized


class Compound(RevisionedObject):
    __tablename__ = "compounds"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "local_identity",
            name="uq_compounds_paper_local_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    local_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    display_label: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.COMPOUND}
