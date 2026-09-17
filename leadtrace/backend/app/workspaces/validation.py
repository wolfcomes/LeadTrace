from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceRole
from app.lineages.models import Lineage, LineageEdge, LineageMember, LineageEdgeReviewStatus, LineageMemberRole
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure, StructureStatus
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
)


@dataclass(frozen=True, slots=True)
class SubmissionBlocker:
    code: str
    message: str
    entity_type: str
    entity_id: UUID | None = None
    section_key: PaperSection | None = None


@dataclass(frozen=True, slots=True)
class SubmissionValidation:
    blockers: list[SubmissionBlocker]

    @property
    def valid(self) -> bool:
        return not self.blockers


def _boundary_blockers(session: Session, workspace_id: UUID) -> list[SubmissionBlocker]:
    blockers: list[SubmissionBlocker] = []
    workspace = session.get(PaperWorkspace, workspace_id)
    if workspace is None:
        return [
            SubmissionBlocker(
                "RESOURCE_NOT_FOUND",
                "Workspace does not exist",
                "paper_workspace",
                workspace_id,
            )
        ]
    workspace_paper_id = workspace.paper_id
    models = (
        (Compound, "compound"),
        (Structure, "structure"),
        (StructureSourceImage, "structure_source_image"),
        (Lineage, "lineage"),
        (LineageMember, "lineage_member"),
        (LineageEdge, "lineage_edge"),
        (Evidence, "evidence"),
        (EdgeEvidenceLink, "edge_evidence_link"),
        (Activity, "activity"),
    )
    for model, entity_type in models:
        rows = session.scalars(select(model).where(model.workspace_id == workspace_id))
        for row in rows:
            if getattr(row, "paper_id", None) is None:
                continue
            # Composite FKs enforce this in normal writes; retain an explicit
            # submission-time diagnostic for rows inserted below the service.
            row_paper_id = getattr(row, "paper_id")
            if row_paper_id != workspace_paper_id:
                blockers.append(
                    SubmissionBlocker(
                        "BOUNDARY_VIOLATION",
                        f"{entity_type} crosses the Paper/Workspace boundary",
                        entity_type,
                        row.id,
                    )
                )
    return blockers


def validate_submission(session: Session, workspace_id: UUID) -> SubmissionValidation:
    blockers: list[SubmissionBlocker] = []
    sections = {
        row.section_key: row
        for row in session.scalars(
            select(PaperSectionReview).where(
                PaperSectionReview.workspace_id == workspace_id
            )
        )
    }
    for section_key in PaperSection:
        row = sections.get(section_key)
        if row is None or row.state is PaperSectionState.PENDING:
            blockers.append(
                SubmissionBlocker(
                    "SECTION_PENDING",
                    f"Section {section_key.value} still needs a disposition",
                    "paper_section_review",
                    row.id if row is not None else None,
                    section_key,
                )
            )

    compounds = list(
        session.scalars(
            select(Compound).where(Compound.workspace_id == workspace_id)
        )
    )
    structures = {
        row.compound_id: row
        for row in session.scalars(
            select(Structure).where(Structure.workspace_id == workspace_id)
        )
    }
    for compound in compounds:
        structure = structures.get(compound.id)
        if structure is None:
            blockers.append(
                SubmissionBlocker(
                    "STRUCTURE_NOT_CONFIRMED",
                    "Compound has no Structure disposition",
                    "compound",
                    compound.id,
                    PaperSection.STRUCTURES,
                )
            )
        elif structure.status is StructureStatus.DRAFT or (
            structure.status is StructureStatus.REVIEWER_CONFIRMED
            and (
                structure.canonical_smiles is None
                or not structure.canonical_smiles.strip()
            )
        ):
            blockers.append(
                SubmissionBlocker(
                    "STRUCTURE_NOT_CONFIRMED",
                    "Structure must be confirmed with canonical SMILES or explicitly unresolved",
                    "structure",
                    structure.id,
                    PaperSection.STRUCTURES,
                )
            )

    lineages = list(
        session.scalars(select(Lineage).where(Lineage.workspace_id == workspace_id))
    )
    members = list(
        session.scalars(
            select(LineageMember).where(LineageMember.workspace_id == workspace_id)
        )
    )
    members_by_lineage: dict[UUID, list[LineageMember]] = {}
    for member in members:
        members_by_lineage.setdefault(member.lineage_id, []).append(member)
    for lineage in lineages:
        lineage_members = members_by_lineage.get(lineage.id, [])
        if not any(member.role is LineageMemberRole.ROOT for member in lineage_members):
            blockers.append(
                SubmissionBlocker(
                    "LINEAGE_ROOT_REQUIRED",
                    "Lineage needs an explicit root disposition",
                    "lineage",
                    lineage.id,
                    PaperSection.LINEAGES,
                )
            )
        if not any(
            member.role is LineageMemberRole.TERMINAL for member in lineage_members
        ):
            blockers.append(
                SubmissionBlocker(
                    "LINEAGE_TERMINAL_REQUIRED",
                    "Lineage needs an explicit terminal disposition",
                    "lineage",
                    lineage.id,
                    PaperSection.LINEAGES,
                )
            )

    edges = list(
        session.scalars(select(LineageEdge).where(LineageEdge.workspace_id == workspace_id))
    )
    contentful_evidence_ids = {
        row.id
        for row in session.scalars(
            select(Evidence).where(Evidence.workspace_id == workspace_id)
        )
        if row.x0 is not None
        or bool(row.quoted_text and row.quoted_text.strip())
        or bool(row.caption and row.caption.strip())
    }
    supporting_edge_ids = {
        link.edge_id
        for link in session.scalars(
            select(EdgeEvidenceLink).where(
                EdgeEvidenceLink.workspace_id == workspace_id,
                EdgeEvidenceLink.role == EvidenceRole.SUPPORTS,
            )
        )
        if link.evidence_id in contentful_evidence_ids
    }
    for edge in edges:
        if edge.review_status is LineageEdgeReviewStatus.DRAFT:
            blockers.append(
                SubmissionBlocker(
                    "EDGE_NOT_DISPOSITIONED",
                    "Edge must be confirmed or explicitly unresolved",
                    "lineage_edge",
                    edge.id,
                    PaperSection.EDGE_EVIDENCE,
                )
            )
        elif (
            edge.review_status is LineageEdgeReviewStatus.REVIEWER_CONFIRMED
            and edge.id not in supporting_edge_ids
        ):
            blockers.append(
                SubmissionBlocker(
                    "EDGE_SUPPORTING_EVIDENCE_REQUIRED",
                    "Confirmed Edge needs supporting Evidence",
                    "lineage_edge",
                    edge.id,
                    PaperSection.EDGE_EVIDENCE,
                )
            )

    blockers.extend(_boundary_blockers(session, workspace_id))
    return SubmissionValidation(blockers)


__all__ = ["SubmissionBlocker", "SubmissionValidation", "validate_submission"]
