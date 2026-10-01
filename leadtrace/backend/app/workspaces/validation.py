from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.compounds.models import Compound, CompoundHighlight
from app.evidence.models import EdgeEvidenceLink, Evidence
from app.lineages.models import Lineage, LineageEdge, LineageMember, LineageEdgeReviewStatus, LineageMemberRole
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure, StructureStatus
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
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
        (CompoundHighlight, "compound_highlight"),
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
    from app.workspaces.review_progress import get_progress, SECTION_VIEW_GROUP
    workspace = session.get(PaperWorkspace, workspace_id)
    task = session.get(ReviewTask, workspace.review_task_id) if workspace else None
    progress = get_progress(session, workspace_id, task.assigned_reviewer_id) if task else None
    progress_sections = {x['section_key']: x for x in progress['sections']} if progress else {}
    for section_key in PaperSection:
        row = sections.get(section_key)
        coverage = progress_sections.get(SECTION_VIEW_GROUP.get(section_key.value))
        auto_complete = coverage and coverage['complete']
        if row is None or (row.state is PaperSectionState.PENDING and not auto_complete):
            blockers.append(
                SubmissionBlocker(
                    "SECTION_PENDING",
                    f"Section {section_key.value} still needs a disposition",
                    "paper_section_review",
                    row.id if row is not None else None,
                    section_key,
                )
            )

    if progress and progress['tracking_started']:
        for item in progress['items']:
            if not item['viewed']:
                blockers.append(SubmissionBlocker(
                    'RECORD_NOT_VIEWED', 'Open the current record before submitting',
                    {'edge': 'lineage_edge', 'structure': 'compound'}.get(item['kind'], item['kind']),
                    UUID(item['entity_id']), PaperSection(item['section_key'])))

    for highlight in session.scalars(select(CompoundHighlight).where(CompoundHighlight.workspace_id == workspace_id)):
        if highlight.review_status == 'draft':
            blockers.append(SubmissionBlocker('COMPOUND_HIGHLIGHT_NOT_REVIEWED',
                'Article selection must be confirmed or explicitly unresolved', 'compound_highlight',
                highlight.id, PaperSection.BIBLIOGRAPHY))

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

    blockers.extend(_boundary_blockers(session, workspace_id))
    return SubmissionValidation(blockers)


__all__ = ["SubmissionBlocker", "SubmissionValidation", "validate_submission"]
