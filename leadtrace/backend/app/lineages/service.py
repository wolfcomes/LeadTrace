from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink
from app.lineages.models import (
    Lineage,
    LineageEdge,
    LineageEdgeReviewStatus,
    LineageMember,
    LineageMemberRole,
    LineageType,
)
from app.security.policies import Principal
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class LineageValidationError(ValueError):
    pass


class LineageOrderError(LineageValidationError):
    pass


class LineageConflictError(RuntimeError):
    pass


class LineageMemberReferencedError(RuntimeError):
    def __init__(self, edge_references: int) -> None:
        super().__init__("Lineage member is referenced by Edges")
        self.edge_references = edge_references


@dataclass(frozen=True, slots=True)
class LineageRecord:
    lineage: Lineage
    members: list[LineageMember]
    edges: list[LineageEdge]


@dataclass(frozen=True, slots=True)
class LineageList:
    workspace: PaperWorkspace
    records: list[LineageRecord]


@dataclass(frozen=True, slots=True)
class LineageMutation:
    workspace: PaperWorkspace
    record: LineageRecord


@dataclass(frozen=True, slots=True)
class MemberList:
    workspace: PaperWorkspace
    lineage_id: UUID
    members: list[LineageMember]


@dataclass(frozen=True, slots=True)
class MemberMutation:
    workspace: PaperWorkspace
    member: LineageMember


@dataclass(frozen=True, slots=True)
class EdgeList:
    workspace: PaperWorkspace
    lineage_id: UUID
    edges: list[LineageEdge]


@dataclass(frozen=True, slots=True)
class EdgeMutation:
    workspace: PaperWorkspace
    edge: LineageEdge


def _clean_required(value: str | None, field: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise LineageValidationError(f"{field} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def lineage_snapshot(lineage: Lineage) -> dict[str, object]:
    return {
        "id": str(lineage.id),
        "paper_id": str(lineage.paper_id),
        "workspace_id": str(lineage.workspace_id),
        "lineage_label": lineage.lineage_label,
        **({"lineage_type": lineage.lineage_type.value} if lineage.lineage_type != LineageType.UNSPECIFIED else {}),
        "description": lineage.description,
        "sort_order": lineage.sort_order,
        "created_by_kind": lineage.created_by_kind.value,
    }


def member_snapshot(member: LineageMember) -> dict[str, object]:
    return {
        "id": str(member.id),
        "paper_id": str(member.paper_id),
        "workspace_id": str(member.workspace_id),
        "lineage_id": str(member.lineage_id),
        "compound_id": str(member.compound_id),
        "role": member.role.value,
        "sort_order": member.sort_order,
        "created_by_kind": member.created_by_kind.value,
    }


def edge_snapshot(edge: LineageEdge) -> dict[str, object]:
    return {
        "id": str(edge.id),
        "paper_id": str(edge.paper_id),
        "workspace_id": str(edge.workspace_id),
        "lineage_id": str(edge.lineage_id),
        "parent_compound_id": str(edge.parent_compound_id),
        "child_compound_id": str(edge.child_compound_id),
        "relation_type": edge.relation_type,
        "modification_summary": edge.modification_summary,
        "review_status": edge.review_status.value,
        "sort_order": edge.sort_order,
        "created_by_kind": edge.created_by_kind.value,
    }


def edge_evidence_link_snapshot(link: EdgeEvidenceLink) -> dict[str, object]:
    return {
        "id": str(link.id),
        "paper_id": str(link.paper_id),
        "workspace_id": str(link.workspace_id),
        "edge_id": str(link.edge_id),
        "evidence_id": str(link.evidence_id),
        "role": link.role.value,
    }


class LineageService:
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
    def _record(session: Session, lineage: Lineage) -> LineageRecord:
        members = list(
            session.scalars(
                select(LineageMember)
                .where(LineageMember.lineage_id == lineage.id)
                .order_by(LineageMember.sort_order, LineageMember.id)
            )
        )
        edges = list(
            session.scalars(
                select(LineageEdge)
                .where(LineageEdge.lineage_id == lineage.id)
                .order_by(LineageEdge.sort_order, LineageEdge.id)
            )
        )
        return LineageRecord(lineage, members, edges)

    def list_lineages(
        self, session: Session, *, workspace_id: UUID, actor: Principal
    ) -> LineageList:
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        lineages = list(
            session.scalars(
                select(Lineage)
                .where(Lineage.workspace_id == workspace_id)
                .order_by(Lineage.sort_order, Lineage.id)
            )
        )
        return LineageList(
            aggregate.workspace,
            [self._record(session, lineage) for lineage in lineages],
        )

    def create_lineage(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: Principal,
        lineage_label: str,
        description: str | None,
        lineage_type: LineageType = LineageType.UNSPECIFIED,
    ) -> LineageMutation:
        created: dict[str, Lineage] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            maximum = session.scalar(
                select(func.max(Lineage.sort_order)).where(
                    Lineage.workspace_id == context.workspace.id
                )
            )
            lineage = Lineage(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                lineage_label=_clean_required(lineage_label, "lineage_label"),
                lineage_type=LineageType(lineage_type),
                description=_clean_optional(description),
                sort_order=int(maximum if maximum is not None else -1) + 1,
            )
            session.add(lineage)
            session.flush()
            created["value"] = lineage
            return MutationChange(
                "lineage", lineage.id, "lineage.create", None, lineage_snapshot(lineage)
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return LineageMutation(result.workspace, self._record(session, created["value"]))

    def update_lineage(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, str | None],
    ) -> LineageMutation:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        changed: dict[str, Lineage] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            lineage = session.scalar(
                select(Lineage)
                .where(
                    Lineage.id == lineage_id,
                    Lineage.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if lineage is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = lineage_snapshot(lineage)
            if "lineage_label" in updates:
                lineage.lineage_label = _clean_required(
                    updates["lineage_label"], "lineage_label"
                )
            if "lineage_type" in updates:
                try:
                    lineage.lineage_type = LineageType(updates["lineage_type"])
                except (ValueError, TypeError) as error:
                    raise LineageValidationError("Invalid lineage_type") from error
            if "description" in updates:
                lineage.description = _clean_optional(updates["description"])
            changed["value"] = lineage
            return MutationChange(
                "lineage",
                lineage.id,
                "lineage.update",
                before,
                lineage_snapshot(lineage),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return LineageMutation(result.workspace, self._record(session, changed["value"]))

    def reorder_lineages(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: Principal,
        lineage_ids: list[UUID],
    ) -> LineageList:
        ordered: dict[str, list[Lineage]] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            rows = list(
                session.scalars(
                    select(Lineage)
                    .where(Lineage.workspace_id == context.workspace.id)
                    .order_by(Lineage.sort_order, Lineage.id)
                    .with_for_update()
                )
            )
            by_id = {row.id: row for row in rows}
            if (
                len(lineage_ids) != len(set(lineage_ids))
                or set(lineage_ids) != set(by_id)
            ):
                raise LineageOrderError(
                    "Lineage order must contain every Workspace Lineage exactly once"
                )
            before = [str(row.id) for row in rows]
            result_rows = [by_id[row_id] for row_id in lineage_ids]
            for index, row in enumerate(result_rows):
                row.sort_order = index
            ordered["value"] = result_rows
            return MutationChange(
                "lineage_order",
                context.workspace.id,
                "lineage.reorder",
                {"lineage_ids": before},
                {"lineage_ids": [str(row_id) for row_id in lineage_ids]},
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return LineageList(
            result.workspace,
            [self._record(session, row) for row in ordered["value"]],
        )

    def delete_lineage(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            lineage = session.scalar(
                select(Lineage)
                .where(
                    Lineage.id == lineage_id,
                    Lineage.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if lineage is None:
                raise WorkspaceNotFoundError("Resource not found")
            record = self._record(session, lineage)
            edge_ids = [edge.id for edge in record.edges]
            links = (
                list(
                    session.scalars(
                        select(EdgeEvidenceLink)
                        .where(EdgeEvidenceLink.edge_id.in_(edge_ids))
                        .order_by(EdgeEvidenceLink.id)
                    )
                )
                if edge_ids
                else []
            )
            before = {
                "lineage": lineage_snapshot(lineage),
                "members": [member_snapshot(row) for row in record.members],
                "edges": [edge_snapshot(row) for row in record.edges],
                "evidence_links": [
                    edge_evidence_link_snapshot(link) for link in links
                ],
            }
            session.delete(lineage)
            return MutationChange("lineage", lineage.id, "lineage.delete", before, None)

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace

    def list_members(
        self, session: Session, *, lineage_id: UUID, actor: Principal
    ) -> MemberList:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        rows = list(
            session.scalars(
                select(LineageMember)
                .where(LineageMember.lineage_id == lineage_id)
                .order_by(LineageMember.sort_order, LineageMember.id)
            )
        )
        return MemberList(aggregate.workspace, lineage_id, rows)

    def add_member(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
        compound_id: UUID,
        role: LineageMemberRole,
    ) -> MemberMutation:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        created: dict[str, LineageMember] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            lineage = session.scalar(
                select(Lineage).where(
                    Lineage.id == lineage_id,
                    Lineage.workspace_id == context.workspace.id,
                )
            )
            compound = session.scalar(
                select(Compound).where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
            )
            if lineage is None or compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            duplicate = session.scalar(
                select(LineageMember.id).where(
                    LineageMember.lineage_id == lineage.id,
                    LineageMember.compound_id == compound.id,
                )
            )
            if duplicate is not None:
                raise LineageConflictError("Compound is already a Lineage member")
            maximum = session.scalar(
                select(func.max(LineageMember.sort_order)).where(
                    LineageMember.lineage_id == lineage.id
                )
            )
            member = LineageMember(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                lineage_id=lineage.id,
                compound_id=compound.id,
                role=role,
                sort_order=int(maximum if maximum is not None else -1) + 1,
            )
            session.add(member)
            session.flush()
            created["value"] = member
            return MutationChange(
                "lineage_member",
                member.id,
                "lineage_member.create",
                None,
                member_snapshot(member),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return MemberMutation(result.workspace, created["value"])

    def update_member(
        self,
        session: Session,
        *,
        member_id: UUID,
        expected_version: int,
        actor: Principal,
        role: LineageMemberRole,
    ) -> MemberMutation:
        workspace_id = self._workspace_id_for(session, LineageMember, member_id)
        changed: dict[str, LineageMember] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            member = session.scalar(
                select(LineageMember)
                .where(
                    LineageMember.id == member_id,
                    LineageMember.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if member is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = member_snapshot(member)
            member.role = role
            changed["value"] = member
            return MutationChange(
                "lineage_member",
                member.id,
                "lineage_member.update",
                before,
                member_snapshot(member),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return MemberMutation(result.workspace, changed["value"])

    def reorder_members(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
        member_ids: list[UUID],
    ) -> MemberList:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        ordered: dict[str, list[LineageMember]] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            rows = list(
                session.scalars(
                    select(LineageMember)
                    .where(
                        LineageMember.lineage_id == lineage_id,
                        LineageMember.workspace_id == context.workspace.id,
                    )
                    .order_by(LineageMember.sort_order, LineageMember.id)
                    .with_for_update()
                )
            )
            by_id = {row.id: row for row in rows}
            if (
                len(member_ids) != len(set(member_ids))
                or set(member_ids) != set(by_id)
            ):
                raise LineageOrderError(
                    "Member order must contain every Lineage member exactly once"
                )
            before = [str(row.id) for row in rows]
            result_rows = [by_id[row_id] for row_id in member_ids]
            for index, row in enumerate(result_rows):
                row.sort_order = index
            ordered["value"] = result_rows
            return MutationChange(
                "lineage_member_order",
                lineage_id,
                "lineage_member.reorder",
                {"member_ids": before},
                {"member_ids": [str(row_id) for row_id in member_ids]},
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return MemberList(result.workspace, lineage_id, ordered["value"])

    def delete_member(
        self,
        session: Session,
        *,
        member_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, LineageMember, member_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            member = session.scalar(
                select(LineageMember)
                .where(
                    LineageMember.id == member_id,
                    LineageMember.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if member is None:
                raise WorkspaceNotFoundError("Resource not found")
            references = int(
                session.scalar(
                    select(func.count())
                    .select_from(LineageEdge)
                    .where(
                        LineageEdge.lineage_id == member.lineage_id,
                        or_(
                            LineageEdge.parent_compound_id == member.compound_id,
                            LineageEdge.child_compound_id == member.compound_id,
                        ),
                    )
                )
                or 0
            )
            if references:
                raise LineageMemberReferencedError(references)
            before = member_snapshot(member)
            session.delete(member)
            return MutationChange(
                "lineage_member", member.id, "lineage_member.delete", before, None
            )

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace

    @staticmethod
    def _validate_edge(
        session: Session,
        *,
        lineage_id: UUID,
        workspace_id: UUID,
        parent_compound_id: UUID,
        child_compound_id: UUID,
        exclude_edge_id: UUID | None = None,
    ) -> None:
        if parent_compound_id == child_compound_id:
            raise LineageValidationError("Edge cannot connect a Compound to itself")
        member_count = int(
            session.scalar(
                select(func.count())
                .select_from(LineageMember)
                .where(
                    LineageMember.lineage_id == lineage_id,
                    LineageMember.workspace_id == workspace_id,
                    LineageMember.compound_id.in_(
                        [parent_compound_id, child_compound_id]
                    ),
                )
            )
            or 0
        )
        if member_count != 2:
            raise LineageValidationError("Both Edge endpoints must be Lineage members")
        statement = select(LineageEdge.id).where(
            LineageEdge.lineage_id == lineage_id,
            LineageEdge.parent_compound_id == parent_compound_id,
            LineageEdge.child_compound_id == child_compound_id,
        )
        if exclude_edge_id is not None:
            statement = statement.where(LineageEdge.id != exclude_edge_id)
        if session.scalar(statement.limit(1)) is not None:
            raise LineageConflictError("Directed Edge already exists")

    def list_edges(
        self, session: Session, *, lineage_id: UUID, actor: Principal
    ) -> EdgeList:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        rows = list(
            session.scalars(
                select(LineageEdge)
                .where(LineageEdge.lineage_id == lineage_id)
                .order_by(LineageEdge.sort_order, LineageEdge.id)
            )
        )
        return EdgeList(aggregate.workspace, lineage_id, rows)

    def create_edge(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
        parent_compound_id: UUID,
        child_compound_id: UUID,
        relation_type: str,
        modification_summary: str | None,
        review_status: LineageEdgeReviewStatus,
    ) -> EdgeMutation:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        created: dict[str, LineageEdge] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            lineage = session.scalar(
                select(Lineage).where(
                    Lineage.id == lineage_id,
                    Lineage.workspace_id == context.workspace.id,
                )
            )
            if lineage is None:
                raise WorkspaceNotFoundError("Resource not found")
            self._validate_edge(
                session,
                lineage_id=lineage.id,
                workspace_id=context.workspace.id,
                parent_compound_id=parent_compound_id,
                child_compound_id=child_compound_id,
            )
            maximum = session.scalar(
                select(func.max(LineageEdge.sort_order)).where(
                    LineageEdge.lineage_id == lineage.id
                )
            )
            edge = LineageEdge(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                lineage_id=lineage.id,
                parent_compound_id=parent_compound_id,
                child_compound_id=child_compound_id,
                relation_type=_clean_required(relation_type, "relation_type"),
                modification_summary=_clean_optional(modification_summary),
                review_status=review_status,
                sort_order=int(maximum if maximum is not None else -1) + 1,
            )
            session.add(edge)
            session.flush()
            created["value"] = edge
            return MutationChange(
                "lineage_edge", edge.id, "lineage_edge.create", None, edge_snapshot(edge)
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return EdgeMutation(result.workspace, created["value"])

    def update_edge(
        self,
        session: Session,
        *,
        edge_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, object],
    ) -> EdgeMutation:
        workspace_id = self._workspace_id_for(session, LineageEdge, edge_id)
        changed: dict[str, LineageEdge] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            edge = session.scalar(
                select(LineageEdge)
                .where(
                    LineageEdge.id == edge_id,
                    LineageEdge.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if edge is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = edge_snapshot(edge)
            parent_id = updates.get("parent_compound_id", edge.parent_compound_id)
            child_id = updates.get("child_compound_id", edge.child_compound_id)
            assert isinstance(parent_id, UUID) and isinstance(child_id, UUID)
            self._validate_edge(
                session,
                lineage_id=edge.lineage_id,
                workspace_id=context.workspace.id,
                parent_compound_id=parent_id,
                child_compound_id=child_id,
                exclude_edge_id=edge.id,
            )
            edge.parent_compound_id = parent_id
            edge.child_compound_id = child_id
            if "relation_type" in updates:
                edge.relation_type = _clean_required(
                    str(updates["relation_type"]), "relation_type"
                )
            if "modification_summary" in updates:
                edge.modification_summary = _clean_optional(
                    updates["modification_summary"]  # type: ignore[arg-type]
                )
            if "review_status" in updates:
                edge.review_status = updates["review_status"]  # type: ignore[assignment]
            changed["value"] = edge
            return MutationChange(
                "lineage_edge",
                edge.id,
                "lineage_edge.update",
                before,
                edge_snapshot(edge),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return EdgeMutation(result.workspace, changed["value"])

    def reorder_edges(
        self,
        session: Session,
        *,
        lineage_id: UUID,
        expected_version: int,
        actor: Principal,
        edge_ids: list[UUID],
    ) -> EdgeList:
        workspace_id = self._workspace_id_for(session, Lineage, lineage_id)
        ordered: dict[str, list[LineageEdge]] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            rows = list(
                session.scalars(
                    select(LineageEdge)
                    .where(
                        LineageEdge.lineage_id == lineage_id,
                        LineageEdge.workspace_id == context.workspace.id,
                    )
                    .order_by(LineageEdge.sort_order, LineageEdge.id)
                    .with_for_update()
                )
            )
            by_id = {row.id: row for row in rows}
            if len(edge_ids) != len(set(edge_ids)) or set(edge_ids) != set(by_id):
                raise LineageOrderError(
                    "Edge order must contain every Lineage Edge exactly once"
                )
            before = [str(row.id) for row in rows]
            result_rows = [by_id[row_id] for row_id in edge_ids]
            for index, row in enumerate(result_rows):
                row.sort_order = index
            ordered["value"] = result_rows
            return MutationChange(
                "lineage_edge_order",
                lineage_id,
                "lineage_edge.reorder",
                {"edge_ids": before},
                {"edge_ids": [str(row_id) for row_id in edge_ids]},
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return EdgeList(result.workspace, lineage_id, ordered["value"])

    def delete_edge(
        self,
        session: Session,
        *,
        edge_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, LineageEdge, edge_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            edge = session.scalar(
                select(LineageEdge)
                .where(
                    LineageEdge.id == edge_id,
                    LineageEdge.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if edge is None:
                raise WorkspaceNotFoundError("Resource not found")
            links = list(
                session.scalars(
                    select(EdgeEvidenceLink).where(EdgeEvidenceLink.edge_id == edge.id)
                )
            )
            before = {
                "edge": edge_snapshot(edge),
                "evidence_links": [
                    edge_evidence_link_snapshot(link) for link in links
                ],
            }
            session.delete(edge)
            return MutationChange(
                "lineage_edge", edge.id, "lineage_edge.delete", before, None
            )

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace


__all__ = [
    "EdgeList",
    "EdgeMutation",
    "LineageConflictError",
    "LineageList",
    "LineageMemberReferencedError",
    "LineageMutation",
    "LineageOrderError",
    "LineageRecord",
    "LineageService",
    "LineageValidationError",
    "MemberList",
    "MemberMutation",
    "edge_snapshot",
    "lineage_snapshot",
    "member_snapshot",
]
