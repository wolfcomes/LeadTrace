from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdMolDescriptors

from app.revisions.models import StructureState


class ChemistryValidationError(ValueError):
    """Raised when a requested chemical interpretation is inconsistent."""


class ExperimentalMaterial(StrEnum):
    UNIQUE = "unique"
    NON_UNIQUE_STEREOCHEMISTRY = "non_unique_stereochemistry"
    MULTICOMPONENT = "multicomponent"
    CONSTITUTION_ONLY = "constitution_only"


class SourceComparison(StrEnum):
    NOT_COMPARED = "not_compared"
    MATCH = "match"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class StructureValidation:
    input_smiles: str
    parseable: bool
    canonical_smiles: str | None
    canonical_isomeric_smiles: str | None
    formula: str | None
    molecular_weight: float | None
    component_count: int
    selected_component_smiles: str | None
    has_dummy_atoms: bool
    has_radicals: bool
    has_stereochemistry: bool
    is_salt: bool
    experimental_material: ExperimentalMaterial
    source_comparison: SourceComparison
    messages: tuple[str, ...]
    eligible_states: tuple[StructureState, ...]


def _parse(smiles: str) -> Chem.Mol | None:
    with rdBase.BlockLogs():
        return Chem.MolFromSmiles(smiles)


def _canonical(molecule: Chem.Mol, *, isomeric: bool) -> str:
    return Chem.MolToSmiles(
        molecule,
        canonical=True,
        isomericSmiles=isomeric,
    )


def _selected_component(
    molecule: Chem.Mol,
    selected_component_smiles: str | None,
) -> tuple[Chem.Mol, str | None, int, list[str]]:
    components = tuple(Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True))
    component_count = len(components)
    messages: list[str] = []
    if component_count <= 1:
        if selected_component_smiles:
            candidate = _parse(selected_component_smiles.strip())
            if candidate is None or _canonical(candidate, isomeric=True) != _canonical(
                molecule, isomeric=True
            ):
                raise ChemistryValidationError(
                    "The exact component selection is not present in the source SMILES"
                )
        return molecule, None, component_count, messages
    if not selected_component_smiles:
        messages.append("EXACT_COMPONENT_SELECTION_REQUIRED")
        return molecule, None, component_count, messages
    selected = _parse(selected_component_smiles.strip())
    if selected is None or len(Chem.GetMolFrags(selected)) != 1:
        raise ChemistryValidationError("The exact component selection is invalid")
    selected_canonical = _canonical(selected, isomeric=True)
    available = {_canonical(component, isomeric=True): component for component in components}
    if selected_canonical not in available:
        raise ChemistryValidationError(
            "The exact component selection is not present in the source SMILES"
        )
    messages.append("EXACT_COMPONENT_SELECTED")
    return available[selected_canonical], selected_canonical, component_count, messages


def validate_structure(
    smiles: str,
    *,
    selected_component_smiles: str | None = None,
    experimental_material: ExperimentalMaterial = ExperimentalMaterial.UNIQUE,
    source_comparison: SourceComparison = SourceComparison.NOT_COMPARED,
    source_verified: bool = False,
    human_confirmed: bool = False,
) -> StructureValidation:
    input_smiles = smiles.strip()
    molecule = _parse(input_smiles) if input_smiles else None
    if molecule is None:
        states = [StructureState.PROPOSAL]
        if experimental_material is ExperimentalMaterial.NON_UNIQUE_STEREOCHEMISTRY:
            states.append(StructureState.NON_UNIQUE_STEREOCHEMISTRY)
        if experimental_material is ExperimentalMaterial.MULTICOMPONENT:
            states.append(StructureState.MULTICOMPONENT_UNRESOLVED)
        if source_comparison is SourceComparison.MISMATCH:
            states.append(StructureState.SOURCE_STRUCTURE_MISMATCH)
        states.append(StructureState.REJECTED)
        return StructureValidation(
            input_smiles=input_smiles,
            parseable=False,
            canonical_smiles=None,
            canonical_isomeric_smiles=None,
            formula=None,
            molecular_weight=None,
            component_count=0,
            selected_component_smiles=None,
            has_dummy_atoms=False,
            has_radicals=False,
            has_stereochemistry=False,
            is_salt=False,
            experimental_material=experimental_material,
            source_comparison=source_comparison,
            messages=(("NO_UNIQUE_SMILES",) if not input_smiles else ("SMILES_PARSE_FAILED",)),
            eligible_states=tuple(states),
        )

    validated, selected, component_count, messages = _selected_component(
        molecule,
        selected_component_smiles,
    )
    source_components = Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True)
    is_salt = component_count > 1 and any(
        sum(atom.GetFormalCharge() for atom in component.GetAtoms()) != 0
        for component in source_components
    )
    has_dummy_atoms = any(atom.GetAtomicNum() == 0 for atom in validated.GetAtoms())
    has_radicals = any(atom.GetNumRadicalElectrons() for atom in validated.GetAtoms())
    has_stereochemistry = bool(
        Chem.FindMolChiralCenters(validated, includeUnassigned=True, includeCIP=True)
        or any(bond.GetStereo() != Chem.BondStereo.STEREONONE for bond in validated.GetBonds())
    )
    canonical = _canonical(validated, isomeric=False)
    canonical_isomeric = _canonical(validated, isomeric=True)
    states = [StructureState.PROPOSAL, StructureState.PARSEABLE_CANDIDATE]
    if source_verified:
        states.append(StructureState.SOURCE_BOUND_CANDIDATE)
    if component_count > 1 and selected is None:
        states.append(StructureState.MULTICOMPONENT_UNRESOLVED)
    if experimental_material is ExperimentalMaterial.NON_UNIQUE_STEREOCHEMISTRY:
        states.append(StructureState.NON_UNIQUE_STEREOCHEMISTRY)
    if experimental_material is ExperimentalMaterial.MULTICOMPONENT:
        if StructureState.MULTICOMPONENT_UNRESOLVED not in states:
            states.append(StructureState.MULTICOMPONENT_UNRESOLVED)
    if experimental_material is ExperimentalMaterial.CONSTITUTION_ONLY:
        states.append(StructureState.CONSTITUTION_CONFIRMED)
    if source_comparison is SourceComparison.MISMATCH:
        states.append(StructureState.SOURCE_STRUCTURE_MISMATCH)

    confirmation_blocked = (
        component_count > 1 and selected is None
        or has_dummy_atoms
        or has_radicals
        or experimental_material is not ExperimentalMaterial.UNIQUE
        or source_comparison is not SourceComparison.MATCH
        or not source_verified
        or not human_confirmed
    )
    if not confirmation_blocked:
        states.append(StructureState.STRUCTURE_CONFIRMED)
    states.append(StructureState.REJECTED)
    return StructureValidation(
        input_smiles=input_smiles,
        parseable=True,
        canonical_smiles=canonical,
        canonical_isomeric_smiles=canonical_isomeric,
        formula=rdMolDescriptors.CalcMolFormula(validated),
        molecular_weight=Descriptors.MolWt(validated),
        component_count=component_count,
        selected_component_smiles=selected,
        has_dummy_atoms=has_dummy_atoms,
        has_radicals=has_radicals,
        has_stereochemistry=has_stereochemistry,
        is_salt=is_salt,
        experimental_material=experimental_material,
        source_comparison=source_comparison,
        messages=tuple(messages),
        eligible_states=tuple(states),
    )
