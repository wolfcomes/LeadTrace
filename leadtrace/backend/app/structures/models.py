from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import (
    ObjectKind,
    RevisionedObject,
    StructureState,
)

__all__ = ["Structure", "StructureState"]


class Structure(RevisionedObject):
    __tablename__ = "structures"
    __table_args__ = (
        UniqueConstraint(
            "compound_id",
            "structure_key",
            name="uq_structures_compound_key",
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
    compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("compounds.id", ondelete="RESTRICT"),
        nullable=False,
    )
    structure_key: Mapped[str] = mapped_column(String(255), nullable=False)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.STRUCTURE}
