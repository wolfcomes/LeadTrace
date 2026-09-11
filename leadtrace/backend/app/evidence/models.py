from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import EvidenceState, ObjectKind, RevisionedObject

__all__ = ["Evidence", "EvidenceState"]


class Evidence(RevisionedObject):
    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "evidence_key",
            name="uq_evidence_paper_key",
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
    evidence_key: Mapped[str] = mapped_column(String(255), nullable=False)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.EVIDENCE}
