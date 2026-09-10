#!/usr/bin/env python3
"""Publish reviewed Batch 05 parent-component selections for simple salts."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Mapping

from rdkit import Chem

from lineage_structure_reconstruction import (
    DEFAULT_CONFIRMED_PATH,
    DEFAULT_WORK_PATH,
    build_component_selection_work_row,
    publish_reviewed_structure_candidates,
)


EXPECTED_COMPONENT_SELECTION_COUNTS = {
    "14c9ce88d1c2": 57,
    "a797514debbc": 45,
    "dfe42148eabf": 1,
    "f2e855803f5a": 2,
}

REVIEWED_COUNTERIONS = {"Cl", "O=CO"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _selected_parent_component(row: Mapping[str, object]) -> str:
    molecule = Chem.MolFromSmiles(str(row.get("raw_structure_text") or ""))
    if molecule is None:
        raise ValueError("Batch 05 component source is not RDKit-parseable")
    components = list(Chem.GetMolFrags(molecule, asMols=True))
    if len(components) != 2:
        raise ValueError("Batch 05 component selection requires exactly two components")

    ranked = sorted(
        (
            component.GetNumHeavyAtoms(),
            Chem.MolToSmiles(component, canonical=True, isomericSmiles=True),
        )
        for component in components
    )
    counterion_heavy_atoms, counterion = ranked[0]
    parent_heavy_atoms, parent = ranked[1]
    if counterion not in REVIEWED_COUNTERIONS or counterion_heavy_atoms > 3:
        raise ValueError(f"unreviewed Batch 05 counterion: {counterion}")
    if parent_heavy_atoms <= 10:
        raise ValueError("Batch 05 parent component is unexpectedly small")
    return parent


def build_component_selection_candidates(
    work_path: Path = DEFAULT_WORK_PATH,
) -> list[dict[str, str]]:
    rows = [
        row for row in _read_csv(work_path)
        if row.get("paper_id") in EXPECTED_COMPONENT_SELECTION_COUNTS
        and row.get("confirmation_reason")
        == "mixture_or_salt_requires_component_selection"
        and row.get("binding_status") == "matched"
    ]
    observed = Counter(row["paper_id"] for row in rows)
    if dict(observed) != EXPECTED_COMPONENT_SELECTION_COUNTS:
        raise ValueError(
            "Batch 05 reviewed component-selection boundary changed: "
            f"{dict(observed)}"
        )

    candidates: list[dict[str, str]] = []
    for row in rows:
        selected = _selected_parent_component(row)
        candidates.append(build_component_selection_work_row(
            row,
            selected_component_smiles=selected,
            decision_note=(
                "Batch 05 source review selected the sole drug-like organic "
                "parent component and excluded the explicitly represented "
                "chloride or formic-acid counterion/solvate."
            ),
        ))
    return candidates


def main() -> None:
    candidates = build_component_selection_candidates()
    result = publish_reviewed_structure_candidates(
        candidates,
        work_path=DEFAULT_WORK_PATH,
        confirmed_path=DEFAULT_CONFIRMED_PATH,
    )
    print(f"published_component_selections={len(candidates)}")
    print(f"confirmed_rows={len(result['confirmed_rows'])}")


if __name__ == "__main__":
    main()
