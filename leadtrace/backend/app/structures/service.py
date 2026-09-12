from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from rdkit import rdBase
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.chemistry.drawing import (
    DEFAULT_RENDER_VERSION,
    DrawingOptions,
    drawing_key,
    render_structure_png,
)
from app.chemistry.validation import (
    ExperimentalMaterial,
    SourceComparison,
    StructureValidation,
    validate_structure,
)
from app.compounds.models import Compound
from app.revisions.models import ObjectRevision, StructureState
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ChangesetItem
from app.security.policies import WorkflowState
from app.structures.models import Structure


class StructureValidationError(ValueError):
    """Raised when a structure draft violates scientific or ownership rules."""


class StructureVersionConflict(RuntimeError):
    """Raised when a structure changeset was changed after it was loaded."""

    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Structure draft changed concurrently: expected {expected_version}, "
            f"current {current_version}"
        )


@dataclass(frozen=True, slots=True)
class StructureDrawingResult:
    asset: Asset
    path: Path
    drawing_key: str
    reused: bool


def _state(value: str | StructureState) -> StructureState:
    try:
        return value if isinstance(value, StructureState) else StructureState(value.strip())
    except (AttributeError, ValueError) as error:
        raise StructureValidationError("Unknown structure state") from error


def _required_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise StructureValidationError(f"{field} is required")
    return cleaned


def _snapshot(
    *,
    structure_key: str,
    compound_id: UUID,
    validation: StructureValidation,
    structure_state: StructureState,
    source: str,
    drawing_asset_id: UUID | None,
) -> dict[str, object]:
    return {
        "structure_key": structure_key,
        "compound_id": str(compound_id),
        "input_smiles": validation.input_smiles or None,
        "canonical_smiles": validation.canonical_smiles,
        "canonical_isomeric_smiles": validation.canonical_isomeric_smiles,
        "formula": validation.formula,
        "molecular_weight": validation.molecular_weight,
        "component_count": validation.component_count,
        "selected_component_smiles": validation.selected_component_smiles,
        "has_dummy_atoms": validation.has_dummy_atoms,
        "has_radicals": validation.has_radicals,
        "has_stereochemistry": validation.has_stereochemistry,
        "is_salt": validation.is_salt,
        "experimental_material": validation.experimental_material.value,
        "source_comparison": validation.source_comparison.value,
        "source": source,
        "drawing_asset_id": str(drawing_asset_id) if drawing_asset_id else None,
        "validation_messages": list(validation.messages),
        "structure_state": structure_state.value,
    }


def _snapshot_hash(session: Session, snapshot: Mapping[str, object]) -> str:
    return str(
        session.scalar(
            select(func.leadtrace_jsonb_sha256(cast(dict(snapshot), JSONB)))
        )
    )


class StructureReviewService:
    """Create append-only, source-aware structure revisions in draft changesets."""

    @staticmethod
    def _editable_changeset(
        session: Session,
        *,
        changeset_id: UUID,
        expected_version: int,
        paper_id: UUID,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None or changeset.paper_id != paper_id:
            raise StructureValidationError("Changeset does not belong to this Paper")
        if changeset.version != expected_version:
            raise StructureVersionConflict(expected_version, changeset.version)
        if changeset.workflow_state not in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}:
            raise StructureValidationError("Only editable draft changesets can contain structures")
        return changeset

    @staticmethod
    def _ensure_item(
        session: Session,
        *,
        changeset: Changeset,
        structure: Structure,
        snapshot: Mapping[str, object],
        base_revision_id: UUID | None,
    ) -> ChangesetItem:
        item = session.scalar(
            select(ChangesetItem)
            .where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == structure.id,
            )
            .with_for_update()
        )
        if item is None:
            sequence = session.scalar(
                select(func.max(ChangesetItem.sequence)).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
            item = ChangesetItem(
                changeset_id=changeset.id,
                paper_id=changeset.paper_id,
                object_id=structure.id,
                object_kind="structure",
                base_revision_id=base_revision_id,
                proposed_snapshot=dict(snapshot),
                content_hash=_snapshot_hash(session, snapshot),
                sequence=int(sequence or 0) + 1,
            )
            session.add(item)
            session.flush()
        else:
            item.proposed_snapshot = dict(snapshot)
            item.content_hash = _snapshot_hash(session, snapshot)
            item.base_revision_id = item.base_revision_id or base_revision_id
        return item

    @staticmethod
    def _drawing_asset(session: Session, asset_id: UUID | None) -> None:
        if asset_id is None:
            return
        asset = session.get(Asset, asset_id)
        if (
            asset is None
            or asset.category is not AssetCategory.RDKIT_STRUCTURE
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
        ):
            raise StructureValidationError("drawing_asset_id must reference a verified RDKit asset")

    @staticmethod
    def _validated_snapshot(
        *,
        structure_key: str,
        compound_id: UUID,
        smiles: str | None,
        structure_state: str | StructureState,
        source: str,
        selected_component_smiles: str | None,
        experimental_material: ExperimentalMaterial,
        source_comparison: SourceComparison,
        source_verified: bool,
        human_confirmed: bool,
        drawing_asset_id: UUID | None,
    ) -> tuple[dict[str, object], StructureState, StructureValidation]:
        clean_key = _required_text(structure_key, "structure_key")
        clean_source = _required_text(source, "source")
        requested_state = _state(structure_state)
        validation = validate_structure(
            smiles or "",
            selected_component_smiles=selected_component_smiles,
            experimental_material=experimental_material,
            source_comparison=source_comparison,
            source_verified=source_verified,
            human_confirmed=human_confirmed,
        )
        if requested_state not in validation.eligible_states:
            raise StructureValidationError(
                f"Structure state {requested_state.value} is not eligible for this evidence"
            )
        return (
            _snapshot(
                structure_key=clean_key,
                compound_id=compound_id,
                validation=validation,
                structure_state=requested_state,
                source=clean_source,
                drawing_asset_id=drawing_asset_id,
            ),
            requested_state,
            validation,
        )

    def create_structure(
        self,
        session: Session,
        *,
        paper_id: UUID,
        compound_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        structure_key: str,
        smiles: str | None,
        structure_state: str | StructureState,
        source: str,
        reason: str,
        selected_component_smiles: str | None = None,
        experimental_material: ExperimentalMaterial = ExperimentalMaterial.UNIQUE,
        source_comparison: SourceComparison = SourceComparison.NOT_COMPARED,
        source_verified: bool = False,
        human_confirmed: bool = False,
        drawing_asset_id: UUID | None = None,
    ) -> tuple[Structure, ObjectRevision]:
        clean_reason = _required_text(reason, "reason")
        compound = session.get(Compound, compound_id)
        if compound is None or compound.paper_id != paper_id:
            raise StructureValidationError("Compound does not belong to this Paper")
        if session.scalar(
            select(Structure.id).where(
                Structure.compound_id == compound_id,
                Structure.structure_key == structure_key.strip(),
            )
        ) is not None:
            raise StructureValidationError("structure_key already exists for this Compound")
        self._drawing_asset(session, drawing_asset_id)
        snapshot, requested_state, validation = self._validated_snapshot(
            structure_key=structure_key,
            compound_id=compound_id,
            smiles=smiles,
            structure_state=structure_state,
            source=source,
            selected_component_smiles=selected_component_smiles,
            experimental_material=experimental_material,
            source_comparison=source_comparison,
            source_verified=source_verified,
            human_confirmed=human_confirmed,
            drawing_asset_id=drawing_asset_id,
        )
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=paper_id,
        )
        structure = Structure(
            paper_id=paper_id,
            compound_id=compound_id,
            structure_key=str(snapshot["structure_key"]),
        )
        session.add(structure)
        session.flush()
        item = self._ensure_item(
            session,
            changeset=changeset,
            structure=structure,
            snapshot=snapshot,
            base_revision_id=None,
        )
        revision = RevisionService().create_revision(
            session,
            object_identity=structure,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=snapshot,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
            structure_state=requested_state,
            canonical_smiles=validation.canonical_isomeric_smiles,
        )
        item.proposed_revision_id = revision.id
        changeset.version += 1
        session.flush()
        return structure, revision

    def update_structure(
        self,
        session: Session,
        *,
        structure_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        smiles: str | None,
        structure_state: str | StructureState,
        source: str,
        reason: str,
        selected_component_smiles: str | None = None,
        experimental_material: ExperimentalMaterial = ExperimentalMaterial.UNIQUE,
        source_comparison: SourceComparison = SourceComparison.NOT_COMPARED,
        source_verified: bool = False,
        human_confirmed: bool = False,
        drawing_asset_id: UUID | None = None,
    ) -> ObjectRevision:
        clean_reason = _required_text(reason, "reason")
        structure = session.scalar(
            select(Structure).where(Structure.id == structure_id).with_for_update()
        )
        if structure is None:
            raise StructureValidationError("Structure not found")
        latest = session.scalar(
            select(ObjectRevision)
            .where(ObjectRevision.object_id == structure_id)
            .order_by(ObjectRevision.revision_number.desc())
            .limit(1)
            .with_for_update()
        )
        if latest is None:
            raise StructureValidationError("Structure has no revision")
        self._drawing_asset(session, drawing_asset_id)
        snapshot, requested_state, validation = self._validated_snapshot(
            structure_key=structure.structure_key,
            compound_id=structure.compound_id,
            smiles=smiles,
            structure_state=structure_state,
            source=source,
            selected_component_smiles=selected_component_smiles,
            experimental_material=experimental_material,
            source_comparison=source_comparison,
            source_verified=source_verified,
            human_confirmed=human_confirmed,
            drawing_asset_id=drawing_asset_id,
        )
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=structure.paper_id,
        )
        item = self._ensure_item(
            session,
            changeset=changeset,
            structure=structure,
            snapshot=latest.snapshot,
            base_revision_id=latest.id,
        )
        revision = RevisionService().create_revision(
            session,
            object_identity=structure,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=snapshot,
            predecessor=latest,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
            structure_state=requested_state,
            canonical_smiles=validation.canonical_isomeric_smiles,
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        changeset.version += 1
        session.flush()
        return revision


class StructureDrawingService:
    """Render and register immutable, idempotent RDKit structure assets."""

    def __init__(self, managed_root: Path) -> None:
        self.managed_root = managed_root

    @staticmethod
    def _lock_key(session: Session, key: str) -> None:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_id = int(key[:16], 16)
        if lock_id >= 2**63:
            lock_id -= 2**64
        session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    def draw(
        self,
        session: Session,
        *,
        smiles: str,
        options: DrawingOptions = DrawingOptions(),
        render_version: str = DEFAULT_RENDER_VERSION,
        created_by_id: UUID | None = None,
        source_asset_id: UUID | None = None,
    ) -> StructureDrawingResult:
        store = LocalAssetStore(self.managed_root)
        key = drawing_key(
            smiles,
            options=options,
            rdkit_version=rdBase.rdkitVersion,
            render_version=render_version,
        )
        self._lock_key(session, key)
        existing = session.scalar(
            select(Asset)
            .where(
                Asset.category == AssetCategory.RDKIT_STRUCTURE,
                Asset.derivation_metadata["drawing_key"].as_string() == key,
                Asset.integrity_state == AssetIntegrityState.VERIFIED,
            )
            .with_for_update()
        )
        if existing is not None:
            path = store.path_for(existing.storage_key)
            if path.is_file():
                return StructureDrawingResult(existing, path, key, True)
            existing.integrity_state = AssetIntegrityState.MISSING

        validation = validate_structure(smiles)
        if not validation.parseable or validation.canonical_isomeric_smiles is None:
            raise StructureValidationError("A parseable SMILES is required for drawing")
        content = render_structure_png(validation.canonical_isomeric_smiles, options=options)
        stored = store.put_bytes(content, suffix=".png")
        inspected = store.inspect(stored.storage_key)
        asset, created = AssetService().register_inspected(
            session,
            storage_key=stored.storage_key,
            inspected=inspected,
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            source_asset_id=source_asset_id,
            created_by_id=created_by_id,
            source_metadata={
                "canonical_isomeric_smiles": validation.canonical_isomeric_smiles,
            },
            derivation_metadata={
                "drawing_key": key,
                "drawing_options": asdict(options),
                "rdkit_version": rdBase.rdkitVersion,
                "render_version": render_version,
            },
        )
        if not created:
            asset.integrity_state = AssetIntegrityState.VERIFIED
            asset.source_metadata = {
                "canonical_isomeric_smiles": validation.canonical_isomeric_smiles,
            }
            asset.derivation_metadata = {
                "drawing_key": key,
                "drawing_options": asdict(options),
                "rdkit_version": rdBase.rdkitVersion,
                "render_version": render_version,
            }
        session.flush()
        return StructureDrawingResult(asset, stored.path, key, False)
