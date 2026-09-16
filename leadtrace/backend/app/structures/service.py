from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from rdkit import Chem, rdBase
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.chemistry.drawing import (
    DEFAULT_RENDER_VERSION,
    DrawingOptions,
    drawing_key,
    render_structure_png,
)
from app.chemistry.validation import validate_structure
from app.compounds.models import Compound
from app.compounds.service import structure_snapshot
from app.security.policies import Principal
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class StructureValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StructureMutation:
    workspace: PaperWorkspace
    structure: Structure


@dataclass(frozen=True, slots=True)
class StructureRead:
    workspace: PaperWorkspace
    structure: Structure | None


@dataclass(frozen=True, slots=True)
class StructureDepiction:
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class ParsedStructure:
    parseable: bool
    canonical_smiles: str | None
    inchi: str | None
    inchikey: str | None


@dataclass(frozen=True, slots=True)
class StructureDrawingResult:
    asset: Asset
    path: Path
    drawing_key: str
    reused: bool


def _clean_smiles(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _preserve_molfile(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


def _parse_smiles(smiles: str) -> ParsedStructure:
    validation = validate_structure(smiles)
    canonical = validation.canonical_isomeric_smiles
    if not validation.parseable or canonical is None:
        return ParsedStructure(False, None, None, None)
    molecule = Chem.MolFromSmiles(canonical)
    if molecule is None:
        return ParsedStructure(False, None, None, None)
    return ParsedStructure(
        True,
        canonical,
        Chem.MolToInchi(molecule),
        Chem.MolToInchiKey(molecule),
    )


def _parse_molfile(molfile: str) -> ParsedStructure:
    molecule = None
    # An empty Molfile title line is structural. Trimming API input removes it,
    # so retry with that valid empty title restored.
    for candidate in (molfile, f"\n{molfile}"):
        with rdBase.BlockLogs():
            molecule = Chem.MolFromMolBlock(
                candidate,
                sanitize=True,
                removeHs=True,
                strictParsing=True,
            )
        if molecule is not None:
            break
    if molecule is None:
        return ParsedStructure(False, None, None, None)
    smiles = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    validation = validate_structure(smiles)
    canonical = validation.canonical_isomeric_smiles
    if not validation.parseable or canonical is None:
        return ParsedStructure(False, None, None, None)
    canonical_molecule = Chem.MolFromSmiles(canonical)
    if canonical_molecule is None:
        return ParsedStructure(False, None, None, None)
    return ParsedStructure(
        True,
        canonical,
        Chem.MolToInchi(canonical_molecule),
        Chem.MolToInchiKey(canonical_molecule),
    )


class StructureDrawingService:
    def __init__(self, managed_root: Path) -> None:
        self.managed_root = managed_root

    @staticmethod
    def _lock_key(session: Session, key: str) -> None:
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
        key = drawing_key(
            smiles,
            options=options,
            rdkit_version=rdBase.rdkitVersion,
            render_version=render_version,
        )
        self._lock_key(session, key)
        store = LocalAssetStore(self.managed_root)
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
            content = AssetService.read_verified_content(existing, store)
            if content is not None:
                existing.access_level = AssetAccessLevel.ADMIN
                return StructureDrawingResult(
                    existing,
                    store.path_for(existing.storage_key),
                    key,
                    True,
                )

        validation = validate_structure(smiles)
        canonical_smiles = validation.canonical_isomeric_smiles
        if not validation.parseable or canonical_smiles is None:
            raise StructureValidationError(
                "A parseable SMILES is required for drawing"
            )
        content = render_structure_png(canonical_smiles, options=options)
        stored = store.put_bytes(
            content,
            suffix=".png",
            namespace=f"rdkit-structure/{key}",
        )
        inspected = store.inspect(stored.storage_key)
        asset, _ = AssetService().register_inspected(
            session,
            storage_key=stored.storage_key,
            inspected=inspected,
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED,
            source_asset_id=source_asset_id,
            created_by_id=created_by_id,
            source_metadata={"canonical_smiles": canonical_smiles},
            derivation_metadata={
                "drawing_key": key,
                "drawing_options": asdict(options),
                "rdkit_version": rdBase.rdkitVersion,
                "render_version": render_version,
            },
        )
        asset.access_level = AssetAccessLevel.ADMIN
        asset.integrity_state = AssetIntegrityState.VERIFIED
        asset.source_metadata = {"canonical_smiles": canonical_smiles}
        asset.derivation_metadata = {
            "drawing_key": key,
            "drawing_options": asdict(options),
            "rdkit_version": rdBase.rdkitVersion,
            "render_version": render_version,
        }
        return StructureDrawingResult(asset, stored.path, key, False)


class StructureService:
    def __init__(
        self,
        managed_root: Path,
        workspace_service: WorkspaceService | None = None,
    ) -> None:
        self.managed_root = managed_root
        self.workspace_service = workspace_service or WorkspaceService()
        self.drawing_service = StructureDrawingService(managed_root)

    @staticmethod
    def _harden_depiction_asset(
        session: Session,
        asset_id: UUID | None,
    ) -> Asset | None:
        if asset_id is None:
            return None
        asset = session.get(Asset, asset_id)
        if asset is None or asset.category is not AssetCategory.RDKIT_STRUCTURE:
            return None
        asset.access_level = AssetAccessLevel.ADMIN
        return asset

    @staticmethod
    def _read_verified_depiction(
        asset: Asset,
        store: LocalAssetStore,
    ) -> bytes | None:
        return AssetService.read_verified_content(asset, store)

    def get_structure(
        self,
        session: Session,
        *,
        compound_id: UUID,
        actor: Principal,
    ) -> StructureRead:
        workspace_id = session.scalar(
            select(Compound.workspace_id).where(Compound.id == compound_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        aggregate = self.workspace_service.get_workspace(
            session,
            workspace_id=workspace_id,
            actor=actor,
        )
        structure = session.scalar(
            select(Structure).where(
                Structure.compound_id == compound_id,
                Structure.workspace_id == aggregate.workspace.id,
            )
        )
        return StructureRead(aggregate.workspace, structure)

    def get_depiction(
        self,
        session: Session,
        *,
        compound_id: UUID,
        actor: Principal,
    ) -> StructureDepiction | None:
        result = self.get_structure(
            session,
            compound_id=compound_id,
            actor=actor,
        )
        if result.structure is None or result.structure.depiction_asset_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        asset_store = LocalAssetStore(self.managed_root)
        asset = self._harden_depiction_asset(
            session,
            result.structure.depiction_asset_id,
        )
        if (
            asset is None
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.mime_type != "image/png"
        ):
            raise WorkspaceNotFoundError("Resource not found")
        content = self._read_verified_depiction(asset, asset_store)
        if content is None:
            return None
        return StructureDepiction(content=content, media_type=asset.mime_type)

    def upsert_structure(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
        status: StructureStatus,
        input_method: StructureInputMethod,
        smiles: str | None,
        molfile: str | None,
    ) -> StructureMutation:
        workspace_id = session.scalar(
            select(Compound.workspace_id).where(Compound.id == compound_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")

        result_row: dict[str, Structure] = {}

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
            clean_smiles = _clean_smiles(smiles)
            clean_molfile = _preserve_molfile(molfile)
            clear_status = status in {
                StructureStatus.UNRESOLVED,
                StructureStatus.NOT_REPORTED,
            }
            if clear_status:
                if clean_smiles is not None or clean_molfile is not None:
                    raise StructureValidationError(
                        "unresolved and not_reported Structures cannot contain "
                        "structure content"
                    )
                parsed = ParsedStructure(False, None, None, None)
            else:
                if (clean_smiles is None) == (clean_molfile is None):
                    raise StructureValidationError(
                        "Exactly one of smiles or molfile is required"
                    )
                if input_method is StructureInputMethod.STRUCTURE_EDITOR:
                    if clean_molfile is None:
                        raise StructureValidationError(
                            "structure_editor input requires molfile content"
                        )
                    parsed = _parse_molfile(clean_molfile)
                else:
                    if clean_smiles is None:
                        raise StructureValidationError(
                            "AI-prefill and manual SMILES input require smiles content"
                        )
                    parsed = _parse_smiles(clean_smiles)
                if not parsed.parseable and status is not StructureStatus.DRAFT:
                    raise StructureValidationError(
                        "Only draft Structures may keep unparseable content"
                    )
            structure = session.scalar(
                select(Structure)
                .where(Structure.compound_id == compound.id)
                .with_for_update()
            )
            before = structure_snapshot(structure) if structure else None
            comparable = {
                "smiles": clean_smiles,
                "canonical_smiles": parsed.canonical_smiles,
                "molfile": clean_molfile,
                "inchi": parsed.inchi,
                "inchikey": parsed.inchikey,
                "status": status.value,
                "input_method": input_method.value,
            }
            if structure is not None and all(
                before[field] == value for field, value in comparable.items()
            ):
                self._harden_depiction_asset(
                    session,
                    structure.depiction_asset_id,
                )
                result_row["structure"] = structure
                return MutationChange(
                    entity_type="structure",
                    entity_id=structure.id,
                    action="structure.update",
                    before_value=before,
                    after_value=before,
                )

            depiction_asset_id = None
            if parsed.canonical_smiles is not None:
                depiction_asset_id = self.drawing_service.draw(
                    session,
                    smiles=parsed.canonical_smiles,
                    created_by_id=actor.user_id,
                ).asset.id
            if structure is None:
                structure = Structure(
                    paper_id=compound.paper_id,
                    workspace_id=compound.workspace_id,
                    compound_id=compound.id,
                    smiles=clean_smiles,
                    canonical_smiles=parsed.canonical_smiles,
                    molfile=clean_molfile,
                    inchi=parsed.inchi,
                    inchikey=parsed.inchikey,
                    depiction_asset_id=depiction_asset_id,
                    status=status,
                    input_method=input_method,
                )
                session.add(structure)
                session.flush()
                action = "structure.create"
            else:
                structure.smiles = clean_smiles
                structure.canonical_smiles = parsed.canonical_smiles
                structure.molfile = clean_molfile
                structure.inchi = parsed.inchi
                structure.inchikey = parsed.inchikey
                structure.depiction_asset_id = depiction_asset_id
                structure.status = status
                structure.input_method = input_method
                action = "structure.update"
            after = structure_snapshot(structure)
            result_row["structure"] = structure
            return MutationChange(
                entity_type="structure",
                entity_id=structure.id,
                action=action,
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
        return StructureMutation(result.workspace, result_row["structure"])


__all__ = [
    "StructureDepiction",
    "StructureDrawingService",
    "StructureDrawingResult",
    "StructureMutation",
    "StructureRead",
    "StructureService",
    "StructureValidationError",
]
