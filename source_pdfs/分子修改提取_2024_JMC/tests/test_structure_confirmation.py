import csv
from pathlib import Path

import pytest

from structure_confirmation import (
    EXPLICIT_PATHS,
    REFERENCE_PATH,
    build_confirmation_rows,
    canonicalize_smiles,
    load_smiles_reference,
    render_structure_images,
)


def test_reference_covers_both_endpoints_of_all_explicit_paths() -> None:
    paths = list(csv.DictReader(EXPLICIT_PATHS.open(encoding="utf-8-sig", newline="")))
    reference = load_smiles_reference(REFERENCE_PATH)

    rows = build_confirmation_rows(paths, reference)

    assert len(rows) == 16
    assert all(row["parent_smiles"] and row["derived_smiles"] for row in rows)
    assert all(row["confirmation_status"] == "confirmed_by_si_smiles" for row in rows)
    assert all(row["structure_source"] == "supporting_information_csv" for row in rows)


def test_canonicalize_smiles_separates_valid_and_invalid_inputs() -> None:
    assert canonicalize_smiles("C1=CC=CC=C1")[0:2] == ("valid", "c1ccccc1")
    assert canonicalize_smiles("not a smiles")[0] == "invalid"


def test_render_structure_images_creates_parent_derived_and_path_panels(
    tmp_path: Path,
) -> None:
    paths = list(csv.DictReader(EXPLICIT_PATHS.open(encoding="utf-8-sig", newline="")))
    reference = load_smiles_reference(REFERENCE_PATH)
    rows = build_confirmation_rows(paths[:1], reference)

    rendered = render_structure_images(rows, tmp_path)

    assert len(rendered) == 1
    for key in ("structure_image_parent", "structure_image_derived", "path_panel_image"):
        image = Path(rendered[0][key])
        assert image.is_file()
        assert image.stat().st_size > 100
        assert image.parent == tmp_path


def test_build_confirmation_rows_rejects_duplicate_reference_keys() -> None:
    with pytest.raises(ValueError, match="duplicate compound reference"):
        load_smiles_reference(
            [
                {"doi": "10.1000/test", "compound_id": "1", "smiles": "C"},
                {"doi": "10.1000/test", "compound_id": "1", "smiles": "CC"},
            ]
        )
