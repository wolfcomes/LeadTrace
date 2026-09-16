from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceKind, EvidenceRole
from app.lineages.models import LineageEdge
from app.papers.models import Paper
from app.security.policies import Principal
from app.structure_images.schemas import NormalizedBBox
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class EvidenceValidationError(ValueError):
    pass


class EvidenceConflictError(RuntimeError):
    pass


class EvidenceReferencedError(RuntimeError):
    def __init__(self, *, edge_references: int, activity_references: int) -> None:
        super().__init__("Evidence is referenced by scientific records")
        self.edge_references = edge_references
        self.activity_references = activity_references


@dataclass(frozen=True, slots=True)
class EvidenceList:
    workspace: PaperWorkspace
    evidence: list[Evidence]


@dataclass(frozen=True, slots=True)
class EvidenceMutation:
    workspace: PaperWorkspace
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class LinkList:
    workspace: PaperWorkspace
    edge_id: UUID
    links: list[EdgeEvidenceLink]


@dataclass(frozen=True, slots=True)
class LinkMutation:
    workspace: PaperWorkspace
    link: EdgeEvidenceLink


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def evidence_snapshot(row: Evidence) -> dict[str, object]:
    bbox = None
    if row.x0 is not None:
        bbox = {
            "x0": float(row.x0),
            "y0": float(row.y0),
            "x1": float(row.x1),
            "y1": float(row.y1),
        }
    return {
        "id": str(row.id),
        "paper_id": str(row.paper_id),
        "workspace_id": str(row.workspace_id),
        "kind": row.kind.value,
        "source_sha256": row.source_sha256,
        "page_number": row.page_number,
        "bbox": bbox,
        "quoted_text": row.quoted_text,
        "caption": row.caption,
        "crop_asset_id": str(row.crop_asset_id) if row.crop_asset_id else None,
        "reviewer_note": row.reviewer_note,
    }


def link_snapshot(row: EdgeEvidenceLink) -> dict[str, object]:
    return {
        "id": str(row.id),
        "paper_id": str(row.paper_id),
        "workspace_id": str(row.workspace_id),
        "edge_id": str(row.edge_id),
        "evidence_id": str(row.evidence_id),
        "role": row.role.value,
    }


class EvidenceService:
    def __init__(self, workspace_service: WorkspaceService | None = None) -> None:
        self.workspace_service = workspace_service or WorkspaceService()

    @staticmethod
    def _workspace_id_for(session: Session, model, entity_id: UUID) -> UUID:
        workspace_id = session.scalar(
            select(model.workspace_id).where(model.id == entity_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        return workspace_id

    @staticmethod
    def _validate_locator(
        session: Session,
        *,
        paper_id: UUID,
        source_sha256: str,
        page_number: int,
    ) -> None:
        source = session.scalar(
            select(PaperSource)
            .join(Paper, Paper.source_id == PaperSource.id)
            .where(Paper.id == paper_id)
        )
        if (
            source is None
            or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or source.sha256 != source_sha256
        ):
            raise EvidenceValidationError("Evidence Source does not match this Paper")
        if page_number > source.page_count:
            raise EvidenceValidationError("Evidence page is outside the Paper Source")

    @staticmethod
    def _apply_bbox(row: Evidence, bbox: NormalizedBBox | None) -> None:
        if bbox is None:
            row.x0 = row.y0 = row.x1 = row.y1 = None
            return
        row.x0, row.y0 = bbox.x0, bbox.y0
        row.x1, row.y1 = bbox.x1, bbox.y1

    def list_evidence(
        self, session: Session, *, workspace_id: UUID, actor: Principal
    ) -> EvidenceList:
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        rows = list(
            session.scalars(
                select(Evidence)
                .where(Evidence.workspace_id == workspace_id)
                .order_by(Evidence.page_number, Evidence.id)
            )
        )
        return EvidenceList(aggregate.workspace, rows)

    def create_evidence(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: Principal,
        kind: EvidenceKind,
        source_sha256: str,
        page_number: int,
        bbox: NormalizedBBox | None,
        quoted_text: str | None,
        caption: str | None,
        reviewer_note: str | None,
    ) -> EvidenceMutation:
        created: dict[str, Evidence] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            self._validate_locator(
                session,
                paper_id=context.workspace.paper_id,
                source_sha256=source_sha256,
                page_number=page_number,
            )
            row = Evidence(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                kind=kind,
                source_sha256=source_sha256,
                page_number=page_number,
                quoted_text=_clean_optional(quoted_text),
                caption=_clean_optional(caption),
                crop_asset_id=None,
                reviewer_note=_clean_optional(reviewer_note),
            )
            self._apply_bbox(row, bbox)
            session.add(row)
            session.flush()
            created["value"] = row
            return MutationChange(
                "evidence", row.id, "evidence.create", None, evidence_snapshot(row)
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return EvidenceMutation(result.workspace, created["value"])

    def update_evidence(
        self,
        session: Session,
        *,
        evidence_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, object],
    ) -> EvidenceMutation:
        workspace_id = self._workspace_id_for(session, Evidence, evidence_id)
        changed: dict[str, Evidence] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            row = session.scalar(
                select(Evidence)
                .where(
                    Evidence.id == evidence_id,
                    Evidence.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if row is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = evidence_snapshot(row)
            source_sha256 = str(updates.get("source_sha256", row.source_sha256))
            page_number = int(updates.get("page_number", row.page_number))
            self._validate_locator(
                session,
                paper_id=context.workspace.paper_id,
                source_sha256=source_sha256,
                page_number=page_number,
            )
            row.source_sha256 = source_sha256
            row.page_number = page_number
            if "kind" in updates:
                row.kind = updates["kind"]  # type: ignore[assignment]
            if "bbox" in updates:
                self._apply_bbox(row, updates["bbox"])  # type: ignore[arg-type]
            for field in ("quoted_text", "caption", "reviewer_note"):
                if field in updates:
                    setattr(row, field, _clean_optional(updates[field]))  # type: ignore[arg-type]
            changed["value"] = row
            return MutationChange(
                "evidence",
                row.id,
                "evidence.update",
                before,
                evidence_snapshot(row),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return EvidenceMutation(result.workspace, changed["value"])

    def delete_evidence(
        self,
        session: Session,
        *,
        evidence_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, Evidence, evidence_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            row = session.scalar(
                select(Evidence)
                .where(
                    Evidence.id == evidence_id,
                    Evidence.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if row is None:
                raise WorkspaceNotFoundError("Resource not found")
            edge_references = int(
                session.scalar(
                    select(func.count())
                    .select_from(EdgeEvidenceLink)
                    .where(EdgeEvidenceLink.evidence_id == row.id)
                )
                or 0
            )
            activity_references = int(
                session.scalar(
                    select(func.count())
                    .select_from(Activity)
                    .where(Activity.evidence_id == row.id)
                )
                or 0
            )
            if edge_references or activity_references:
                raise EvidenceReferencedError(
                    edge_references=edge_references,
                    activity_references=activity_references,
                )
            before = evidence_snapshot(row)
            session.delete(row)
            return MutationChange("evidence", row.id, "evidence.delete", before, None)

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace

    def list_links(
        self, session: Session, *, edge_id: UUID, actor: Principal
    ) -> LinkList:
        workspace_id = self._workspace_id_for(session, LineageEdge, edge_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        rows = list(
            session.scalars(
                select(EdgeEvidenceLink)
                .where(EdgeEvidenceLink.edge_id == edge_id)
                .order_by(EdgeEvidenceLink.id)
            )
        )
        return LinkList(aggregate.workspace, edge_id, rows)

    def create_link(
        self,
        session: Session,
        *,
        edge_id: UUID,
        expected_version: int,
        actor: Principal,
        evidence_id: UUID,
        role: EvidenceRole,
    ) -> LinkMutation:
        workspace_id = self._workspace_id_for(session, LineageEdge, edge_id)
        created: dict[str, EdgeEvidenceLink] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            edge = session.scalar(
                select(LineageEdge).where(
                    LineageEdge.id == edge_id,
                    LineageEdge.workspace_id == context.workspace.id,
                )
            )
            evidence = session.scalar(
                select(Evidence).where(
                    Evidence.id == evidence_id,
                    Evidence.workspace_id == context.workspace.id,
                )
            )
            if edge is None or evidence is None:
                raise WorkspaceNotFoundError("Resource not found")
            duplicate = session.scalar(
                select(EdgeEvidenceLink.id).where(
                    EdgeEvidenceLink.edge_id == edge.id,
                    EdgeEvidenceLink.evidence_id == evidence.id,
                )
            )
            if duplicate is not None:
                raise EvidenceConflictError("Evidence is already linked to this Edge")
            link = EdgeEvidenceLink(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                edge_id=edge.id,
                evidence_id=evidence.id,
                role=role,
            )
            session.add(link)
            session.flush()
            created["value"] = link
            return MutationChange(
                "edge_evidence_link",
                link.id,
                "edge_evidence_link.create",
                None,
                link_snapshot(link),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return LinkMutation(result.workspace, created["value"])

    def update_link(
        self,
        session: Session,
        *,
        link_id: UUID,
        expected_version: int,
        actor: Principal,
        role: EvidenceRole,
    ) -> LinkMutation:
        workspace_id = self._workspace_id_for(session, EdgeEvidenceLink, link_id)
        changed: dict[str, EdgeEvidenceLink] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            link = session.scalar(
                select(EdgeEvidenceLink)
                .where(
                    EdgeEvidenceLink.id == link_id,
                    EdgeEvidenceLink.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if link is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = link_snapshot(link)
            link.role = role
            changed["value"] = link
            return MutationChange(
                "edge_evidence_link",
                link.id,
                "edge_evidence_link.update",
                before,
                link_snapshot(link),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return LinkMutation(result.workspace, changed["value"])

    def delete_link(
        self,
        session: Session,
        *,
        link_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, EdgeEvidenceLink, link_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            link = session.scalar(
                select(EdgeEvidenceLink)
                .where(
                    EdgeEvidenceLink.id == link_id,
                    EdgeEvidenceLink.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if link is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = link_snapshot(link)
            session.delete(link)
            return MutationChange(
                "edge_evidence_link",
                link.id,
                "edge_evidence_link.delete",
                before,
                None,
            )

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace


__all__ = [
    "EvidenceConflictError",
    "EvidenceList",
    "EvidenceMutation",
    "EvidenceReferencedError",
    "EvidenceService",
    "EvidenceValidationError",
    "LinkList",
    "LinkMutation",
    "evidence_snapshot",
    "link_snapshot",
]
