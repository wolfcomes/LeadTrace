#!/usr/bin/env python3
"""Publish audited Batch 05 repairs for identical duplicate source rows.

The source CSV for Paper 5531836ee3c3 repeats three compounds in a trailing
summary block.  The general binder intentionally refuses every duplicate
label.  This module records the narrower human-reviewed decision: both rows
encode the same complete graph, and the row in the primary table is retained.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from lineage_structure_reconstruction import (
    DEFAULT_CONFIRMED_PATH,
    DEFAULT_WORK_PATH,
    build_reviewed_structure_work_row,
    publish_reviewed_structure_candidates,
)


PAPER_ID = "5531836ee3c3"

EXPECTED_PRIMARY_LOCATORS = {
    "i15": "row=122",
    "i16": "row=123",
    "i19": "row=126",
}

EXPECTED_SUMMARY_LOCATORS = {
    "i15": "row=146",
    "i16": "row=147",
    "i19": "row=148",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_duplicate_source_repair_candidates(
    work_path: Path = DEFAULT_WORK_PATH,
) -> list[dict[str, str]]:
    """Return the three source-located candidates after duplicate audit."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(work_path):
        label = row.get("normalized_label", "")
        if (
            row.get("paper_id") == PAPER_ID
            and label in EXPECTED_PRIMARY_LOCATORS
            and row.get("binding_status") == "duplicate_source_records"
        ):
            grouped[label].append(row)

    if set(grouped) != set(EXPECTED_PRIMARY_LOCATORS):
        raise ValueError(
            "Batch 05 duplicate-source boundary changed: "
            f"observed labels={sorted(grouped)}"
        )

    candidates: list[dict[str, str]] = []
    for label in EXPECTED_PRIMARY_LOCATORS:
        source_rows = grouped[label]
        if len(source_rows) != 2:
            raise ValueError(
                f"expected exactly two duplicate rows for {label}; "
                f"observed {len(source_rows)}"
            )

        observed_locators = {row["source_locator"] for row in source_rows}
        expected_locators = {
            EXPECTED_PRIMARY_LOCATORS[label],
            EXPECTED_SUMMARY_LOCATORS[label],
        }
        if observed_locators != expected_locators:
            raise ValueError(
                f"duplicate source locators changed for {label}: "
                f"{sorted(observed_locators)}"
            )

        canonical_structures = {
            row["canonical_isomeric_smiles"] for row in source_rows
        }
        raw_structures = {row["raw_structure_text"] for row in source_rows}
        if len(canonical_structures) != 1 or len(raw_structures) != 1:
            raise ValueError(
                f"duplicate source rows disagree structurally for {label}"
            )

        primary = next(
            row for row in source_rows
            if row["source_locator"] == EXPECTED_PRIMARY_LOCATORS[label]
        )
        candidates.append(build_reviewed_structure_work_row(
            paper_id=PAPER_ID,
            compound_entity_id=f"CMP-{PAPER_ID}-{label}",
            compound_label=label,
            canonical_isomeric_smiles=primary["canonical_isomeric_smiles"],
            source_id=primary["source_id"],
            source_file=primary["source_file"],
            source_locator=primary["source_locator"],
            source_label=primary["source_label"],
            reconstruction_method="reviewed_complete_structure",
            source_match_status="exact_complete_structure_match",
            decision_note=(
                "The primary table row and the repeated summary row encode "
                "the same complete canonical graph. The primary table row "
                "is retained after an exact duplicate-source audit."
            ),
            stereochemistry_status="source_encoded",
        ))

    return candidates


def main() -> None:
    candidates = build_duplicate_source_repair_candidates()
    result = publish_reviewed_structure_candidates(
        candidates,
        work_path=DEFAULT_WORK_PATH,
        confirmed_path=DEFAULT_CONFIRMED_PATH,
    )
    confirmed_keys = {
        (row["paper_id"], row["normalized_label"])
        for row in result["confirmed_rows"]
    }
    for row in candidates:
        key = (row["paper_id"], row["normalized_label"])
        if key not in confirmed_keys:
            raise RuntimeError(f"duplicate-source repair was not confirmed: {key}")
    print(f"published_duplicate_repairs={len(candidates)}")
    print(f"confirmed_rows={len(result['confirmed_rows'])}")


if __name__ == "__main__":
    main()
