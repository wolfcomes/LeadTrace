from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdMolDescriptors


class ChemistryValidationError(ValueError):
    """Raised when a requested chemical interpretation is inconsistent."""


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
    messages: tuple[str, ...]


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
) -> StructureValidation:
    input_smiles = smiles.strip()
    molecule = _parse(input_smiles) if input_smiles else None
    if molecule is None:
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
            messages=(("NO_UNIQUE_SMILES",) if not input_smiles else ("SMILES_PARSE_FAILED",)),
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
        messages=tuple(messages),
    )
