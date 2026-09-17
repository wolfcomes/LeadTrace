from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.activities.models import Activity, ActivityOperator
from app.activities.service import activity_snapshot
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.compounds.models import Compound
from app.compounds.service import compound_snapshot, structure_snapshot
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceKind, EvidenceRole
from app.evidence.service import evidence_snapshot, link_snapshot
from app.lineages.models import (
    Lineage,
    LineageEdge,
    LineageEdgeReviewStatus,
    LineageMember,
    LineageMemberRole,
)
from app.lineages.service import edge_snapshot, lineage_snapshot, member_snapshot
from app.papers.models import Paper
from app.structure_images.models import CropStatus, StructureSourceImage
from app.structure_images.service import (
    StructureSourceImageService,
    source_image_snapshot,
)
from app.jobs.service import (
    cleanup_transaction_created_files,
    transaction_created_files,
)
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.structures.service import ParsedStructure, _parse_molfile, _parse_smiles
from app.users.models import User, UserRole
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperWorkspace,
    WorkspaceState,
)


class AiPrefillNotFoundError(LookupError):
    pass


class AiPrefillUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AiApplyResult:
    run: AiExtractionRun
    applied: bool
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class AiQueueResult:
    run: AiExtractionRun
    created: bool


def _clean_required(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _paper_snapshot(paper: Paper) -> dict[str, object]:
    return {
        "id": str(paper.id),
        "paper_key": paper.paper_key,
        "title": paper.title,
        "journal": paper.journal,
        "publication_year": paper.publication_year,
        "volume": paper.volume,
        "issue": paper.issue,
        "doi": paper.doi,
        "catalog_state": paper.catalog_state.value,
    }


class AiPrefillService:
    _science_models = (
        Compound,
        Structure,
        StructureSourceImage,
        Lineage,
        LineageMember,
        LineageEdge,
        Evidence,
        EdgeEvidenceLink,
        Activity,
    )

    def __init__(
        self,
        structure_image_service: StructureSourceImageService | None = None,
    ) -> None:
        self.structure_image_service = structure_image_service

    @staticmethod
    def _workspace_has_science(session: Session, workspace_id: UUID) -> bool:
        return any(
            session.scalar(
                select(exists().where(model.workspace_id == workspace_id))
            )
            for model in AiPrefillService._science_models
        )

    @staticmethod
    def _workspace_has_human_history(
        session: Session, workspace_id: UUID
    ) -> bool:
        return bool(
            session.scalar(
                select(
                    exists().where(
                        ChangeEvent.workspace_id == workspace_id,
                        ChangeEvent.actor_kind.in_(
                            [ChangeActorKind.REVIEWER, ChangeActorKind.ADMIN]
                        ),
                    )
                )
            )
        )

    def unavailable_reason(
        self,
        session: Session,
        *,
        workspace: PaperWorkspace,
    ) -> str | None:
        active = session.scalar(
            select(AiExtractionRun.id).where(
                AiExtractionRun.workspace_id == workspace.id,
                AiExtractionRun.status.in_(
                    [
                        AiExtractionRunStatus.QUEUED,
                        AiExtractionRunStatus.RUNNING,
                    ]
                ),
            )
        )
        if active is not None:
            return "AI prefill is already queued or running"
        if workspace.state is not WorkspaceState.EDITING:
            return "Workspace is not editable"
        if workspace.version != 1:
            return "Workspace has already been modified"
        if self._workspace_has_science(session, workspace.id):
            return "Workspace already contains scientific data"
        if self._workspace_has_human_history(session, workspace.id):
            return "Workspace has Reviewer or Admin history"
        return None

    def queue(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        requested_by_id: UUID,
        engine: str,
        engine_version: str,
    ) -> AiQueueResult:
        workspace = session.scalar(
            select(PaperWorkspace)
            .where(PaperWorkspace.id == workspace_id)
            .with_for_update()
        )
        if workspace is None:
            raise AiPrefillNotFoundError("Workspace not found")
        requester = session.get(User, requested_by_id)
        if requester is None or requester.role is not UserRole.ADMIN:
            raise AiPrefillNotFoundError("Admin not found")
        active = session.scalar(
            select(AiExtractionRun).where(
                AiExtractionRun.workspace_id == workspace_id,
                AiExtractionRun.status.in_(
                    [
                        AiExtractionRunStatus.QUEUED,
                        AiExtractionRunStatus.RUNNING,
                    ]
                ),
            )
        )
        if active is not None:
            return AiQueueResult(run=active, created=False)
        if self.unavailable_reason(session, workspace=workspace) is not None:
            raise AiPrefillUnavailableError(
                "AI prefill requires a blank, untouched editing Workspace"
            )
        run = AiExtractionRun(
            paper_id=workspace.paper_id,
            workspace_id=workspace.id,
            requested_by_id=requested_by_id,
            starting_workspace_version=workspace.version,
            status=AiExtractionRunStatus.QUEUED,
            engine=_clean_required(engine, "engine"),
            engine_version=_clean_required(engine_version, "engine_version"),
            dispatch_token=uuid4(),
            dispatched_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        return AiQueueResult(run=run, created=True)

    @staticmethod
    def _source_is_valid(
        source: PaperSource | None,
        payload: AiPrefillPayload,
    ) -> bool:
        if (
            source is None
            or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
        ):
            return False
        pages = [item.page_number for item in payload.structure_locators]
        pages.extend(item.page_number for item in payload.evidence)
        return all(page <= source.page_count for page in pages)

    @staticmethod
    def _parse_structures(
        payload: AiPrefillPayload,
    ) -> dict[str, ParsedStructure] | None:
        parsed: dict[str, ParsedStructure] = {}
        for item in payload.compounds:
            smiles = _clean_optional(item.structure.smiles)
            molfile = item.structure.molfile
            if molfile is not None and not molfile.strip():
                molfile = None
            if (smiles is None) == (molfile is None):
                return None
            structure = (
                _parse_smiles(smiles)
                if smiles is not None
                else _parse_molfile(molfile or "")
            )
            if not structure.parseable:
                return None
            parsed[item.ref] = structure
        return parsed

    @staticmethod
    def _event(
        run: AiExtractionRun,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        after_value: dict[str, object],
        before_value: dict[str, object] | None = None,
    ) -> ChangeEvent:
        return ChangeEvent(
            paper_id=run.paper_id,
            workspace_id=run.workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_value=before_value,
            after_value=after_value,
            actor_kind=ChangeActorKind.AI,
            actor_id=None,
            ai_run_id=run.id,
        )

    @staticmethod
    def _mark_terminal(
        run: AiExtractionRun,
        status: AiExtractionRunStatus,
        *,
        error_summary: str | None = None,
    ) -> None:
        run.status = status
        run.error_summary = error_summary
        run.completed_at = datetime.now(UTC)

    def apply(
        self,
        session: Session,
        *,
        run_id: UUID,
        payload: AiPrefillPayload,
        dispatch_token: UUID | None = None,
    ) -> AiApplyResult:
        run = session.scalar(
            select(AiExtractionRun)
            .where(AiExtractionRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise AiPrefillNotFoundError("AI extraction run not found")
        if dispatch_token is not None and (
            run.dispatch_token != dispatch_token
            or run.status is not AiExtractionRunStatus.RUNNING
        ):
            return AiApplyResult(run, applied=False, idempotent=True)
        if run.status is AiExtractionRunStatus.SUCCEEDED:
            return AiApplyResult(run, applied=False, idempotent=True)
        if run.status in {
            AiExtractionRunStatus.FAILED,
            AiExtractionRunStatus.SUPERSEDED,
        }:
            return AiApplyResult(run, applied=False, idempotent=True)

        workspace = session.scalar(
            select(PaperWorkspace)
            .where(PaperWorkspace.id == run.workspace_id)
            .with_for_update()
        )
        if workspace is None or workspace.paper_id != run.paper_id:
            raise AiPrefillNotFoundError("Workspace not found")
        run.status = AiExtractionRunStatus.RUNNING
        if run.started_at is None:
            run.started_at = datetime.now(UTC)
        if (
            workspace.state is not WorkspaceState.EDITING
            or workspace.version != run.starting_workspace_version
            or self._workspace_has_science(session, workspace.id)
            or self._workspace_has_human_history(session, workspace.id)
        ):
            self._mark_terminal(run, AiExtractionRunStatus.SUPERSEDED)
            session.flush()
            return AiApplyResult(run, applied=False)

        paper = session.get(Paper, run.paper_id)
        source = (
            session.get(PaperSource, paper.source_id) if paper is not None else None
        )
        if paper is None or not self._source_is_valid(source, payload):
            self._mark_terminal(
                run,
                AiExtractionRunStatus.FAILED,
                error_summary="AI payload failed source validation",
            )
            session.flush()
            return AiApplyResult(run, applied=False)
        parsed_structures = self._parse_structures(payload)
        if parsed_structures is None:
            self._mark_terminal(
                run,
                AiExtractionRunStatus.FAILED,
                error_summary="AI payload failed Structure validation",
            )
            session.flush()
            return AiApplyResult(run, applied=False)

        assert source is not None
        existing_created_files = transaction_created_files(session)
        try:
            with session.begin_nested():
                self._write_payload(
                    session,
                    run=run,
                    workspace=workspace,
                    paper=paper,
                    source=source,
                    payload=payload,
                    parsed_structures=parsed_structures,
                )
                session.flush()
        except Exception:
            cleanup_transaction_created_files(
                session,
                transaction_created_files(session) - existing_created_files,
            )
            self._mark_terminal(
                run,
                AiExtractionRunStatus.FAILED,
                error_summary="AI payload failed transactional validation",
            )
            session.flush()
            return AiApplyResult(run, applied=False)

        workspace.version += 1
        self._mark_terminal(run, AiExtractionRunStatus.SUCCEEDED)
        session.flush()
        return AiApplyResult(run, applied=True)

    def _write_payload(
        self,
        session: Session,
        *,
        run: AiExtractionRun,
        workspace: PaperWorkspace,
        paper: Paper,
        source: PaperSource,
        payload: AiPrefillPayload,
        parsed_structures: dict[str, ParsedStructure],
    ) -> None:
        before_paper = _paper_snapshot(paper)
        bibliography = payload.bibliography
        if bibliography.title is not None:
            paper.title = _clean_required(bibliography.title, "title")
        if bibliography.journal is not None:
            paper.journal = _clean_required(bibliography.journal, "journal")
        if bibliography.publication_year is not None:
            paper.publication_year = bibliography.publication_year
        if bibliography.volume is not None:
            paper.volume = _clean_required(bibliography.volume, "volume")
        if bibliography.issue is not None:
            paper.issue = _clean_required(bibliography.issue, "issue")
        if bibliography.doi is not None:
            paper.doi = _clean_required(bibliography.doi, "doi")
        after_paper = _paper_snapshot(paper)
        if before_paper != after_paper:
            session.add(
                self._event(
                    run,
                    entity_type="paper",
                    entity_id=paper.id,
                    action="paper.update",
                    before_value=before_paper,
                    after_value=after_paper,
                )
            )

        compounds: dict[str, Compound] = {}
        structures: list[tuple[str, Structure]] = []
        for sort_order, item in enumerate(payload.compounds):
            compound = Compound(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                compound_label=_clean_required(item.compound_label, "compound_label"),
                display_name=_clean_optional(item.display_name),
                description=_clean_optional(item.description),
                sort_order=sort_order,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(compound)
            compounds[item.ref] = compound
        session.flush()
        for compound in compounds.values():
            session.add(
                self._event(
                    run,
                    entity_type="compound",
                    entity_id=compound.id,
                    action="compound.create",
                    after_value=compound_snapshot(compound),
                )
            )

        for item in payload.compounds:
            compound = compounds[item.ref]
            parsed = parsed_structures[item.ref]
            smiles = _clean_optional(item.structure.smiles)
            molfile = item.structure.molfile
            structure = Structure(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                compound_id=compound.id,
                smiles=smiles,
                canonical_smiles=parsed.canonical_smiles,
                molfile=molfile,
                inchi=parsed.inchi,
                inchikey=parsed.inchikey,
                depiction_asset_id=None,
                status=StructureStatus.DRAFT,
                input_method=StructureInputMethod.AI_PREFILL,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(structure)
            structures.append((item.ref, structure))
        session.flush()
        for _, structure in structures:
            session.add(
                self._event(
                    run,
                    entity_type="structure",
                    entity_id=structure.id,
                    action="structure.create",
                    after_value=structure_snapshot(structure),
                )
            )

        source_images: list[StructureSourceImage] = []
        for item in payload.structure_locators:
            source_image = StructureSourceImage(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                compound_id=compounds[item.compound_ref].id,
                source_sha256=source.sha256,
                page_number=item.page_number,
                x0=item.bbox.x0,
                y0=item.bbox.y0,
                x1=item.bbox.x1,
                y1=item.bbox.y1,
                source_context=_clean_optional(item.source_context),
                label=_clean_optional(item.label),
                reviewer_note=None,
                crop_status=(
                    CropStatus.PENDING
                    if self.structure_image_service is not None
                    else CropStatus.FAILED
                ),
                crop_asset_id=None,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(source_image)
            source_images.append(source_image)
        session.flush()

        lineages: dict[str, Lineage] = {}
        members: list[LineageMember] = []
        for lineage_order, item in enumerate(payload.lineages):
            lineage = Lineage(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                lineage_label=_clean_required(item.lineage_label, "lineage_label"),
                description=_clean_optional(item.description),
                sort_order=lineage_order,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(lineage)
            lineages[item.ref] = lineage
        session.flush()
        for lineage in lineages.values():
            session.add(
                self._event(
                    run,
                    entity_type="lineage",
                    entity_id=lineage.id,
                    action="lineage.create",
                    after_value=lineage_snapshot(lineage),
                )
            )
        for item in payload.lineages:
            lineage = lineages[item.ref]
            for member_order, member_item in enumerate(item.members):
                member = LineageMember(
                    paper_id=run.paper_id,
                    workspace_id=workspace.id,
                    lineage_id=lineage.id,
                    compound_id=compounds[member_item.compound_ref].id,
                    role=LineageMemberRole(member_item.role),
                    sort_order=member_order,
                    created_by_kind=ChangeActorKind.AI,
                )
                session.add(member)
                members.append(member)
        session.flush()
        for member in members:
            session.add(
                self._event(
                    run,
                    entity_type="lineage_member",
                    entity_id=member.id,
                    action="lineage_member.create",
                    after_value=member_snapshot(member),
                )
            )

        edges: dict[str, LineageEdge] = {}
        for item in payload.lineages:
            lineage = lineages[item.ref]
            for edge_order, edge_item in enumerate(item.edges):
                edge = LineageEdge(
                    paper_id=run.paper_id,
                    workspace_id=workspace.id,
                    lineage_id=lineage.id,
                    parent_compound_id=compounds[
                        edge_item.parent_compound_ref
                    ].id,
                    child_compound_id=compounds[edge_item.child_compound_ref].id,
                    relation_type=_clean_required(
                        edge_item.relation_type, "relation_type"
                    ),
                    modification_summary=_clean_optional(
                        edge_item.modification_summary
                    ),
                    review_status=LineageEdgeReviewStatus.DRAFT,
                    sort_order=edge_order,
                    created_by_kind=ChangeActorKind.AI,
                )
                session.add(edge)
                edges[edge_item.ref] = edge
        session.flush()
        for edge in edges.values():
            session.add(
                self._event(
                    run,
                    entity_type="lineage_edge",
                    entity_id=edge.id,
                    action="lineage_edge.create",
                    after_value=edge_snapshot(edge),
                )
            )

        evidence_by_ref: dict[str, Evidence] = {}
        for item in payload.evidence:
            bbox = item.bbox
            row = Evidence(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                kind=EvidenceKind(item.kind),
                source_sha256=source.sha256,
                page_number=item.page_number,
                x0=bbox.x0 if bbox is not None else None,
                y0=bbox.y0 if bbox is not None else None,
                x1=bbox.x1 if bbox is not None else None,
                y1=bbox.y1 if bbox is not None else None,
                quoted_text=_clean_optional(item.quoted_text),
                caption=_clean_optional(item.caption),
                crop_asset_id=None,
                reviewer_note=None,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(row)
            evidence_by_ref[item.ref] = row
        session.flush()
        for row in evidence_by_ref.values():
            session.add(
                self._event(
                    run,
                    entity_type="evidence",
                    entity_id=row.id,
                    action="evidence.create",
                    after_value=evidence_snapshot(row),
                )
            )

        links: list[EdgeEvidenceLink] = []
        for item in payload.edge_evidence_links:
            link = EdgeEvidenceLink(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                edge_id=edges[item.edge_ref].id,
                evidence_id=evidence_by_ref[item.evidence_ref].id,
                role=EvidenceRole(item.role),
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(link)
            links.append(link)
        session.flush()
        for link in links:
            session.add(
                self._event(
                    run,
                    entity_type="edge_evidence_link",
                    entity_id=link.id,
                    action="edge_evidence_link.create",
                    after_value=link_snapshot(link),
                )
            )

        activities: list[Activity] = []
        per_compound_order: dict[str, int] = {}
        for item in payload.activities:
            sort_order = per_compound_order.get(item.compound_ref, 0)
            per_compound_order[item.compound_ref] = sort_order + 1
            row = Activity(
                paper_id=run.paper_id,
                workspace_id=workspace.id,
                compound_id=compounds[item.compound_ref].id,
                evidence_id=(
                    evidence_by_ref[item.evidence_ref].id
                    if item.evidence_ref is not None
                    else None
                ),
                assay_name=_clean_required(item.assay_name, "assay_name"),
                metric=_clean_required(item.metric, "metric"),
                operator=ActivityOperator(item.operator),
                value=item.value,
                unit=_clean_optional(item.unit),
                context=_clean_optional(item.context),
                sort_order=sort_order,
                created_by_kind=ChangeActorKind.AI,
            )
            session.add(row)
            activities.append(row)
        session.flush()
        for row in activities:
            session.add(
                self._event(
                    run,
                    entity_type="activity",
                    entity_id=row.id,
                    action="activity.create",
                    after_value=activity_snapshot(row),
                )
            )

        session.flush()
        if self.structure_image_service is not None:
            for source_image in source_images:
                self.structure_image_service.render_source_image_crop(
                    session,
                    source_image=source_image,
                    actor_id=run.requested_by_id,
                )
        for source_image in source_images:
            session.add(
                self._event(
                    run,
                    entity_type="structure_source_image",
                    entity_id=source_image.id,
                    action="structure_source_image.create",
                    after_value=source_image_snapshot(source_image),
                )
            )


__all__ = [
    "AiApplyResult",
    "AiPrefillNotFoundError",
    "AiPrefillService",
    "AiPrefillUnavailableError",
]
