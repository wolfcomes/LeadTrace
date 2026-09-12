from __future__ import annotations

import pytest

from app.chemistry.validation import (
    ChemistryValidationError,
    ExperimentalMaterial,
    SourceComparison,
    validate_structure,
)
from app.revisions.models import StructureState


def test_valid_smiles_returns_typed_rdkit_properties_without_confirming_it() -> None:
    result = validate_structure("C[C@H](O)Cl")

    assert result.parseable is True
    assert result.canonical_smiles == "CC(O)Cl"
    assert result.canonical_isomeric_smiles == "C[C@H](O)Cl"
    assert result.formula == "C2H5ClO"
    assert result.molecular_weight == pytest.approx(80.51, abs=0.02)
    assert result.component_count == 1
    assert result.has_stereochemistry is True
    assert StructureState.PARSEABLE_CANDIDATE in result.eligible_states
    assert StructureState.STRUCTURE_CONFIRMED not in result.eligible_states


def test_invalid_smiles_returns_a_safe_parse_message() -> None:
    result = validate_structure("not a smiles")

    assert result.parseable is False
    assert result.canonical_isomeric_smiles is None
    assert result.messages == ("SMILES_PARSE_FAILED",)
    assert result.eligible_states == (StructureState.PROPOSAL, StructureState.REJECTED)


def test_multicomponent_material_requires_an_exact_component_selection() -> None:
    unresolved = validate_structure("CCO.[Na+]")

    assert unresolved.component_count == 2
    assert unresolved.selected_component_smiles is None
    assert "EXACT_COMPONENT_SELECTION_REQUIRED" in unresolved.messages
    assert StructureState.MULTICOMPONENT_UNRESOLVED in unresolved.eligible_states

    selected = validate_structure("CCO.[Na+]", selected_component_smiles="OCC")
    assert selected.selected_component_smiles == "CCO"
    assert selected.canonical_isomeric_smiles == "CCO"
    assert selected.component_count == 2
    assert "EXACT_COMPONENT_SELECTED" in selected.messages

    with pytest.raises(ChemistryValidationError, match="exact component"):
        validate_structure("CCO.[Na+]", selected_component_smiles="CCN")


def test_salt_flag_does_not_misclassify_a_neutral_mixture() -> None:
    salt = validate_structure("C[N+](C)(C)C.[Cl-]")
    neutral_mixture = validate_structure("CCO.CCO")

    assert salt.is_salt is True
    assert neutral_mixture.is_salt is False


@pytest.mark.parametrize(
    ("smiles", "flag"),
    [("C*", "has_dummy_atoms"), ("[CH3]", "has_radicals")],
)
def test_incomplete_chemical_graph_features_are_explicit(smiles: str, flag: str) -> None:
    result = validate_structure(smiles)

    assert getattr(result, flag) is True
    assert StructureState.STRUCTURE_CONFIRMED not in result.eligible_states


def test_scientific_context_controls_confirmation_eligibility() -> None:
    non_unique = validate_structure(
        "CC(O)Cl",
        experimental_material=ExperimentalMaterial.NON_UNIQUE_STEREOCHEMISTRY,
        source_comparison=SourceComparison.MATCH,
        source_verified=True,
        human_confirmed=True,
    )
    mismatch = validate_structure(
        "CCO",
        source_comparison=SourceComparison.MISMATCH,
        source_verified=True,
        human_confirmed=True,
    )
    confirmed = validate_structure(
        "CCO",
        source_comparison=SourceComparison.MATCH,
        source_verified=True,
        human_confirmed=True,
    )

    assert StructureState.NON_UNIQUE_STEREOCHEMISTRY in non_unique.eligible_states
    assert StructureState.STRUCTURE_CONFIRMED not in non_unique.eligible_states
    assert StructureState.SOURCE_STRUCTURE_MISMATCH in mismatch.eligible_states
    assert StructureState.STRUCTURE_CONFIRMED not in mismatch.eligible_states
    assert StructureState.STRUCTURE_CONFIRMED in confirmed.eligible_states


def test_non_unique_experimental_material_does_not_require_a_unique_smiles() -> None:
    result = validate_structure(
        "",
        experimental_material=ExperimentalMaterial.NON_UNIQUE_STEREOCHEMISTRY,
        source_comparison=SourceComparison.MATCH,
        source_verified=True,
        human_confirmed=True,
    )

    assert result.parseable is False
    assert result.canonical_isomeric_smiles is None
    assert result.messages == ("NO_UNIQUE_SMILES",)
    assert StructureState.NON_UNIQUE_STEREOCHEMISTRY in result.eligible_states
    assert StructureState.STRUCTURE_CONFIRMED not in result.eligible_states
