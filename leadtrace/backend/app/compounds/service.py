from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.compounds.models import Compound
from app.lineages.models import LineageMember
from app.security.policies import Principal
from app.structures.models import Structure
from app.structure_images.models import StructureSourceImage
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import ChangeActorKind, PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class CompoundValidationError(ValueError):
    pass


class CompoundOrderError(CompoundValidationError):
    pass


class CompoundLabelConflictError(CompoundValidationError):
    pass


class CompoundReferencedError(RuntimeError):
    def __init__(self, *, lineage_references: int, activity_references: int) -> None:
        super().__init__("Compound is referenced by scientific records")
        self.lineage_references = lineage_references
        self.activity_references = activity_references


@dataclass(frozen=True, slots=True)
class CompoundList:
    workspace: PaperWorkspace
    compounds: list[Compound]


@dataclass(frozen=True, slots=True)
class CompoundMutation:
    workspace: PaperWorkspace
    compound: Compound


def compound_snapshot(compound: Compound) -> dict[str, object]:
    return {
        "id": str(compound.id),
        "paper_id": str(compound.paper_id),
        "workspace_id": str(compound.workspace_id),
        "compound_label": compound.compound_label,
        "display_name": compound.display_name,
        "description": compound.description,
        "sort_order": compound.sort_order,
        "created_by_kind": compound.created_by_kind.value,
    }


def structure_snapshot(structure: Structure) -> dict[str, object]:
    return {
        "id": str(structure.id),
        "paper_id": str(structure.paper_id),
        "workspace_id": str(structure.workspace_id),
        "compound_id": str(structure.compound_id),
        "smiles": structure.smiles,
        "canonical_smiles": structure.canonical_smiles,
        "molfile": structure.molfile,
        "inchi": structure.inchi,
        "inchikey": structure.inchikey,
        "depiction_asset_id": (
            str(structure.depiction_asset_id) if structure.depiction_asset_id else None
        ),
        "status": structure.status.value,
        "input_method": structure.input_method.value,
    }


def structure_source_image_snapshot(
    source_image: StructureSourceImage,
) -> dict[str, object]:
    return {
        "id": str(source_image.id),
        "paper_id": str(source_image.paper_id),
        "workspace_id": str(source_image.workspace_id),
        "compound_id": str(source_image.compound_id),
        "source_sha256": source_image.source_sha256,
        "page_number": source_image.page_number,
        "bbox": {
            "x0": float(source_image.x0),
            "y0": float(source_image.y0),
            "x1": float(source_image.x1),
            "y1": float(source_image.y1),
        },
        "source_context": source_image.source_context,
        "label": source_image.label,
        "reviewer_note": source_image.reviewer_note,
        "crop_status": source_image.crop_status.value,
        "crop_asset_id": (
            str(source_image.crop_asset_id) if source_image.crop_asset_id else None
        ),
    }


def _clean_required(value: str | None, field: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise CompoundValidationError(f"{field} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class CompoundService:
    def __init__(self, workspace_service: WorkspaceService | None = None) -> None:
        self.workspace_service = workspace_service or WorkspaceService()

    def list_compounds(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        actor: Principal,
    ) -> CompoundList:
        aggregate = self.workspace_service.get_workspace(
            session,
            workspace_id=workspace_id,
            actor=actor,
        )
        compounds = list(
            session.scalars(
                select(Compound)
                .where(Compound.workspace_id == workspace_id)
                .order_by(Compound.sort_order, Compound.id)
            )
        )
        return CompoundList(workspace=aggregate.workspace, compounds=compounds)

    def create_compound(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: Principal,
        compound_label: str,
        display_name: str | None,
        description: str | None,
    ) -> CompoundMutation:
        created: dict[str, Compound] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            clean_label = _clean_required(compound_label, "compound_label")
            clean_name = _clean_optional(display_name)
            clean_description = _clean_optional(description)
            duplicate = session.scalar(
                select(Compound.id).where(
                    Compound.workspace_id == context.workspace.id,
                    Compound.compound_label == clean_label,
                )
            )
            if duplicate is not None:
                raise CompoundLabelConflictError(
                    "compound_label already exists in this Workspace"
                )
            maximum_order = session.scalar(
                select(func.max(Compound.sort_order)).where(
                    Compound.workspace_id == context.workspace.id
                )
            )
            compound = Compound(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                compound_label=clean_label,
                display_name=clean_name,
                description=clean_description,
                sort_order=int(maximum_order if maximum_order is not None else -1) + 1,
                created_by_kind=ChangeActorKind.REVIEWER,
            )
            session.add(compound)
            session.flush()
            created["compound"] = compound
            return MutationChange(
                entity_type="compound",
                entity_id=compound.id,
                action="compound.create",
                before_value=None,
                after_value=compound_snapshot(compound),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return CompoundMutation(result.workspace, created["compound"])

    def update_compound(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, str | None],
    ) -> CompoundMutation:
        workspace_id = session.scalar(
            select(Compound.workspace_id).where(Compound.id == compound_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        updated: dict[str, Compound] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            compound = session.scalar(
                select(Compound)
                .where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            clean_updates: dict[str, str | None] = {}
            for field, value in updates.items():
                clean_updates[field] = (
                    _clean_required(value, field)
                    if field == "compound_label"
                    else _clean_optional(value)
                )
            new_label = clean_updates.get("compound_label")
            if new_label is not None:
                duplicate = session.scalar(
                    select(Compound.id).where(
                        Compound.workspace_id == context.workspace.id,
                        Compound.compound_label == new_label,
                        Compound.id != compound.id,
                    )
                )
                if duplicate is not None:
                    raise CompoundLabelConflictError(
                        "compound_label already exists in this Workspace"
                    )
            before = compound_snapshot(compound)
            for field, value in clean_updates.items():
                setattr(compound, field, value)
            after = compound_snapshot(compound)
            updated["compound"] = compound
            return MutationChange(
                entity_type="compound",
                entity_id=compound.id,
                action="compound.update",
                before_value=before,
                after_value=after,
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return CompoundMutation(result.workspace, updated["compound"])

    def reorder_compounds(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: Principal,
        compound_ids: list[UUID],
    ) -> CompoundList:
        ordered: dict[str, list[Compound]] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            if len(set(compound_ids)) != len(compound_ids):
                raise CompoundOrderError(
                    "Compound order must contain each Workspace Compound exactly once"
                )
            compounds = list(
                session.scalars(
                    select(Compound)
                    .where(Compound.workspace_id == context.workspace.id)
                    .order_by(Compound.sort_order, Compound.id)
                    .with_for_update()
                )
            )
            by_id = {compound.id: compound for compound in compounds}
            if set(by_id) != set(compound_ids):
                raise CompoundOrderError(
                    "Compound order must contain each Workspace Compound exactly once"
                )
            before = [str(compound.id) for compound in compounds]
            rows = [by_id[compound_id] for compound_id in compound_ids]
            for sort_order, compound in enumerate(rows):
                compound.sort_order = sort_order
            ordered["compounds"] = rows
            return MutationChange(
                entity_type="compound_order",
                entity_id=context.workspace.id,
                action="compound.reorder",
                before_value={"compound_ids": before},
                after_value={
                    "compound_ids": [str(compound_id) for compound_id in compound_ids]
                },
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return CompoundList(result.workspace, ordered["compounds"])

    def delete_compound(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = session.scalar(
            select(Compound.workspace_id).where(Compound.id == compound_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")

        def mutation(context: LockedWorkspace) -> MutationChange:
            compound = session.scalar(
                select(Compound)
                .where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            lineage_references = int(
                session.scalar(
                    select(func.count())
                    .select_from(LineageMember)
                    .where(LineageMember.compound_id == compound.id)
                )
                or 0
            )
            activity_references = int(
                session.scalar(
                    select(func.count())
                    .select_from(Activity)
                    .where(Activity.compound_id == compound.id)
                )
                or 0
            )
            if lineage_references or activity_references:
                raise CompoundReferencedError(
                    lineage_references=lineage_references,
                    activity_references=activity_references,
                )
            structure = session.scalar(
                select(Structure).where(Structure.compound_id == compound.id)
            )
            source_images = list(
                session.scalars(
                    select(StructureSourceImage)
                    .where(StructureSourceImage.compound_id == compound.id)
                    .order_by(
                        StructureSourceImage.page_number,
                        StructureSourceImage.y0,
                        StructureSourceImage.x0,
                        StructureSourceImage.id,
                    )
                )
            )
            before = {
                "compound": compound_snapshot(compound),
                "structure": structure_snapshot(structure) if structure else None,
                "structure_source_images": [
                    structure_source_image_snapshot(source_image)
                    for source_image in source_images
                ],
            }
            session.delete(compound)
            return MutationChange(
                entity_type="compound",
                entity_id=compound.id,
                action="compound.delete",
                before_value=before,
                after_value=None,
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return result.workspace


__all__ = [
    "CompoundLabelConflictError",
    "CompoundList",
    "CompoundMutation",
    "CompoundOrderError",
    "CompoundReferencedError",
    "CompoundService",
    "CompoundValidationError",
    "compound_snapshot",
    "structure_snapshot",
]
