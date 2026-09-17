from __future__ import annotations

import pytest

from app.chemistry.validation import (
    ChemistryValidationError,
    validate_structure,
)


def test_valid_smiles_returns_typed_rdkit_properties_without_confirming_it() -> None:
    result = validate_structure("C[C@H](O)Cl")

    assert result.parseable is True
    assert result.canonical_smiles == "CC(O)Cl"
    assert result.canonical_isomeric_smiles == "C[C@H](O)Cl"
    assert result.formula == "C2H5ClO"
    assert result.molecular_weight == pytest.approx(80.51, abs=0.02)
    assert result.component_count == 1
    assert result.has_stereochemistry is True
    assert not hasattr(result, "eligible_states")


def test_invalid_smiles_returns_a_safe_parse_message() -> None:
    result = validate_structure("not a smiles")

    assert result.parseable is False
    assert result.canonical_isomeric_smiles is None
    assert result.messages == ("SMILES_PARSE_FAILED",)


def test_multicomponent_material_requires_an_exact_component_selection() -> None:
    unresolved = validate_structure("CCO.[Na+]")

    assert unresolved.component_count == 2
    assert unresolved.selected_component_smiles is None
    assert "EXACT_COMPONENT_SELECTION_REQUIRED" in unresolved.messages

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
