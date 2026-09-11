from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import ObjectKind, RevisionedObject


class Paper(RevisionedObject):
    __tablename__ = "papers"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.PAPER}
