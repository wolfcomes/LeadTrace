from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import ObjectKind, RevisionedObject


class MoleculeProposalDisposition(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class MoleculeProposal(RevisionedObject):
    """Stable identity for immutable machine OCSR evidence."""

    __tablename__ = "molecule_proposals"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "visual_object_id",
            "proposal_key",
            "model_run_key",
            name="uq_molecule_proposals_identity",
        ),
        Index("ix_molecule_proposals_paper", "paper_id"),
        Index("ix_molecule_proposals_visual_object", "visual_object_id"),
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
    visual_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("visual_objects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    proposal_key: Mapped[str] = mapped_column(String(255), nullable=False)
    model_run_key: Mapped[str] = mapped_column(String(255), nullable=False)
    crop_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_region_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("visual_regions.id", ondelete="RESTRICT"),
        nullable=True,
    )

    __mapper_args__ = {"polymorphic_identity": ObjectKind.MOLECULE_PROPOSAL}
