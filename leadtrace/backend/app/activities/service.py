from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activities.models import Activity, ActivityOperator
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.security.policies import Principal
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class ActivityValidationError(ValueError):
    pass


class ActivityOrderError(ActivityValidationError):
    pass


@dataclass(frozen=True, slots=True)
class ActivityList:
    workspace: PaperWorkspace
    compound_id: UUID
    activities: list[Activity]


@dataclass(frozen=True, slots=True)
class ActivityMutation:
    workspace: PaperWorkspace
    activity: Activity


def _clean_required(value: str | None, field: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ActivityValidationError(f"{field} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def activity_snapshot(row: Activity) -> dict[str, object]:
    return {
        "id": str(row.id),
        "paper_id": str(row.paper_id),
        "workspace_id": str(row.workspace_id),
        "compound_id": str(row.compound_id),
        "evidence_id": str(row.evidence_id) if row.evidence_id else None,
        "assay_name": row.assay_name,
        "metric": row.metric,
        "operator": row.operator.value,
        "value": str(row.value),
        "unit": row.unit,
        "context": row.context,
        "sort_order": row.sort_order,
    }


class ActivityService:
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
    def _evidence_id(
        session: Session, *, workspace_id: UUID, evidence_id: UUID | None
    ) -> UUID | None:
        if evidence_id is None:
            return None
        found = session.scalar(
            select(Evidence.id).where(
                Evidence.id == evidence_id,
                Evidence.workspace_id == workspace_id,
            )
        )
        if found is None:
            raise WorkspaceNotFoundError("Resource not found")
        return found

    def list_activities(
        self, session: Session, *, compound_id: UUID, actor: Principal
    ) -> ActivityList:
        workspace_id = self._workspace_id_for(session, Compound, compound_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        rows = list(
            session.scalars(
                select(Activity)
                .where(Activity.compound_id == compound_id)
                .order_by(Activity.sort_order, Activity.id)
            )
        )
        return ActivityList(aggregate.workspace, compound_id, rows)

    def create_activity(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
        evidence_id: UUID | None,
        assay_name: str,
        metric: str,
        operator: ActivityOperator,
        value: Decimal,
        unit: str | None,
        context_value: str | None,
    ) -> ActivityMutation:
        workspace_id = self._workspace_id_for(session, Compound, compound_id)
        created: dict[str, Activity] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            compound = session.scalar(
                select(Compound).where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
            )
            if compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            checked_evidence_id = self._evidence_id(
                session,
                workspace_id=context.workspace.id,
                evidence_id=evidence_id,
            )
            maximum = session.scalar(
                select(func.max(Activity.sort_order)).where(
                    Activity.compound_id == compound.id
                )
            )
            row = Activity(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                compound_id=compound.id,
                evidence_id=checked_evidence_id,
                assay_name=_clean_required(assay_name, "assay_name"),
                metric=_clean_required(metric, "metric"),
                operator=operator,
                value=value,
                unit=_clean_optional(unit),
                context=_clean_optional(context_value),
                sort_order=int(maximum if maximum is not None else -1) + 1,
            )
            session.add(row)
            session.flush()
            created["value"] = row
            return MutationChange(
                "activity", row.id, "activity.create", None, activity_snapshot(row)
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return ActivityMutation(result.workspace, created["value"])

    def update_activity(
        self,
        session: Session,
        *,
        activity_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, object],
    ) -> ActivityMutation:
        workspace_id = self._workspace_id_for(session, Activity, activity_id)
        changed: dict[str, Activity] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            row = session.scalar(
                select(Activity)
                .where(
                    Activity.id == activity_id,
                    Activity.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if row is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = activity_snapshot(row)
            if "evidence_id" in updates:
                row.evidence_id = self._evidence_id(
                    session,
                    workspace_id=context.workspace.id,
                    evidence_id=updates["evidence_id"],  # type: ignore[arg-type]
                )
            if "assay_name" in updates:
                row.assay_name = _clean_required(
                    updates["assay_name"], "assay_name"  # type: ignore[arg-type]
                )
            if "metric" in updates:
                row.metric = _clean_required(
                    updates["metric"], "metric"  # type: ignore[arg-type]
                )
            if "operator" in updates:
                row.operator = updates["operator"]  # type: ignore[assignment]
            if "value" in updates:
                row.value = updates["value"]  # type: ignore[assignment]
            if "unit" in updates:
                row.unit = _clean_optional(updates["unit"])  # type: ignore[arg-type]
            if "context" in updates:
                row.context = _clean_optional(updates["context"])  # type: ignore[arg-type]
            changed["value"] = row
            return MutationChange(
                "activity",
                row.id,
                "activity.update",
                before,
                activity_snapshot(row),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return ActivityMutation(result.workspace, changed["value"])

    def reorder_activities(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
        activity_ids: list[UUID],
    ) -> ActivityList:
        workspace_id = self._workspace_id_for(session, Compound, compound_id)
        ordered: dict[str, list[Activity]] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            compound = session.scalar(
                select(Compound).where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
            )
            if compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            rows = list(
                session.scalars(
                    select(Activity)
                    .where(Activity.compound_id == compound.id)
                    .order_by(Activity.sort_order, Activity.id)
                    .with_for_update()
                )
            )
            by_id = {row.id: row for row in rows}
            if (
                len(activity_ids) != len(set(activity_ids))
                or set(activity_ids) != set(by_id)
            ):
                raise ActivityOrderError(
                    "Activity order must contain every Compound Activity exactly once"
                )
            before = [str(row.id) for row in rows]
            result_rows = [by_id[row_id] for row_id in activity_ids]
            for index, row in enumerate(result_rows):
                row.sort_order = index
            ordered["value"] = result_rows
            return MutationChange(
                "activity_order",
                compound.id,
                "activity.reorder",
                {"activity_ids": before},
                {"activity_ids": [str(row_id) for row_id in activity_ids]},
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return ActivityList(result.workspace, compound_id, ordered["value"])

    def delete_activity(
        self,
        session: Session,
        *,
        activity_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for(session, Activity, activity_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            row = session.scalar(
                select(Activity)
                .where(
                    Activity.id == activity_id,
                    Activity.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if row is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = activity_snapshot(row)
            session.delete(row)
            return MutationChange("activity", row.id, "activity.delete", before, None)

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace


__all__ = [
    "ActivityList",
    "ActivityMutation",
    "ActivityOrderError",
    "ActivityService",
    "ActivityValidationError",
    "activity_snapshot",
]
