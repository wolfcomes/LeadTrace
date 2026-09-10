#!/usr/bin/env python3
"""Publish the conservative structure decisions for lineage Batch 06.

This module deliberately keeps batch-specific source decisions separate from
the common structure confirmation gate. A parseable graph is not accepted
when the article reports a racemate or an unresolved stereoisomer mixture.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

from rdkit import Chem

from lineage_structure_reconstruction import (
    DEFAULT_CONFIRMED_PATH,
    DEFAULT_WORK_PATH,
    build_component_selection_work_row,
    normalize_compound_label,
    publish_reviewed_structure_candidates,
    publish_reviewed_structure_exclusions,
    publish_reviewed_structure_mismatches,
)


BATCH06_SMIP_PAPER = "023145d60eea"
BATCH06_SMIP_LABELS = tuple(
    f"SMIP-{number:03d}" for number in (*range(1, 30), *range(31, 39))
)

# These rows are explicitly reported as racemates or stereoisomer mixtures in
# the article. The source-table graph must not be promoted as one unique
# experimental molecule merely because RDKit can parse it.
BATCH06_STRUCTURE_EXCLUSION_LABELS: dict[str, tuple[str, ...]] = {
    "434e5748f070": tuple(str(number) for number in range(1, 45)),
    "feef9e819b88": tuple(
        [f"A{number}" for number in range(1, 10) if number != 4]
        + [f"B{number}" for number in range(1, 7)]
        + [f"C{number}" for number in range(1, 14)]
        + [
            f"D{number}" for number in range(1, 21)
            if number not in {15, 16, 17}
        ]
    ),
    "1994543a9112": (
        "58f", "58g", "58h", "58i", "58j", "58k", "58l", "58m",
        "58n", "58o", "58p", "58q", "58r", "58s", "58u", "58v",
        "73a", "73b", "73c", "73d", "73e", "73f",
    ),
    "07dcad0214c3": ("1",),
    "56f50284cedf": (
        "7-30A", "7-31A", "7-45A", "7-48A", "7-51A", "7-54A",
        "7-58A", "7-62A",
    ),
    "bf54bac4775b": (
        "20", "21", "24", "25", "27", "28", "29", "30", "31",
        "36", "37", "41", "42", "43",
        "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S10",
    ),
}

# These machine rows have the wrong connectivity or substituent identity for
# the corresponding paper-local compound, not merely unsupported stereo.
BATCH06_STRUCTURE_MISMATCH_LABELS: dict[str, tuple[str, ...]] = {
    "56f50284cedf": ("7-31B",),
    "1994543a9112": ("58c",),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _is_monatomic_bromide(fragment: Chem.Mol) -> bool:
    return (
        fragment.GetNumAtoms() == 1
        and fragment.GetAtomWithIdx(0).GetAtomicNum() == 35
        and fragment.GetAtomWithIdx(0).GetFormalCharge() == -1
    )


def select_smip_cation_component(source_smiles: str) -> str:
    """Return the exact source organic cation for a simple bromide salt.

    The rule is intentionally stricter than largest-fragment selection: there
    must be exactly two components, exactly one monatomic [Br-], exactly one
    carbon-containing component with net charge +1, and a neutral full salt.
    Covalent bromine remains part of the selected cation.
    """
    source = Chem.MolFromSmiles(str(source_smiles or "").strip())
    if source is None:
        raise ValueError("source salt is not RDKit-parseable")
    fragments = list(Chem.GetMolFrags(source, asMols=True, sanitizeFrags=True))
    bromides = [
        fragment for fragment in fragments if _is_monatomic_bromide(fragment)
    ]
    if len(bromides) != 1:
        raise ValueError("SMIP salt requires exactly one monatomic [Br-]")
    if len(fragments) != 2:
        raise ValueError("SMIP salt requires exactly two components")
    cation_candidates = []
    for fragment in fragments:
        if _is_monatomic_bromide(fragment):
            continue
        if (
            any(atom.GetAtomicNum() == 6 for atom in fragment.GetAtoms())
            and sum(atom.GetFormalCharge() for atom in fragment.GetAtoms()) == 1
        ):
            cation_candidates.append(fragment)
    if len(cation_candidates) != 1:
        raise ValueError("SMIP salt requires exactly one organic cation")
    if sum(atom.GetFormalCharge() for atom in source.GetAtoms()) != 0:
        raise ValueError("SMIP salt must have net charge zero")
    return Chem.MolToSmiles(
        cation_candidates[0], canonical=True, isomericSmiles=True,
    )


def build_batch06_component_selection_candidates(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Build reviewed cation candidates for all current SMIP source rows."""
    expected = {
        normalize_compound_label(label) for label in BATCH06_SMIP_LABELS
    }
    all_source_rows = [
        dict(row) for row in rows
        if str(row.get("paper_id") or "") == BATCH06_SMIP_PAPER
        and normalize_compound_label(row.get("compound_label")) in expected
        and str(row.get("binding_status") or "") == "matched"
    ]
    observed = {
        normalize_compound_label(row.get("compound_label"))
        for row in all_source_rows
    }
    if observed not in (set(), expected):
        missing = sorted(expected - observed)
        raise ValueError(
            "Batch 06 SMIP source rows are incomplete: " + ", ".join(missing)
        )
    resolved = {
        normalize_compound_label(row.get("compound_label"))
        for row in all_source_rows
        if str(row.get("component_selection_status") or "")
        == "explicit_component_selected"
    }
    selected_rows = [
        row for row in all_source_rows
        if normalize_compound_label(row.get("compound_label")) not in resolved
    ]
    if not selected_rows:
        return []

    candidates: list[dict[str, str]] = []
    for row in selected_rows:
        selected = select_smip_cation_component(
            str(row.get("raw_structure_text") or "")
        )
        candidates.append(build_component_selection_work_row(
            row,
            selected_component_smiles=selected,
            decision_note=(
                "The DOI-exact source row contains exactly one organic +1 "
                "cation and one disconnected monatomic [Br-]. Only the "
                "counterion is removed; covalent bromine and cation charge "
                "are retained exactly from the source component."
            ),
        ))
    return candidates


def build_batch06_structure_exclusions(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Build immutable work-row exclusions for source-reported mixtures."""
    expected = {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in BATCH06_STRUCTURE_EXCLUSION_LABELS.items()
        for label in labels
    }
    matches: dict[tuple[str, str], dict[str, object]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        key = (
            str(row.get("paper_id") or ""),
            normalize_compound_label(row.get("compound_label")),
        )
        if key not in expected:
            continue
        work_row_id = str(row.get("work_row_id") or "").strip()
        if not work_row_id:
            raise ValueError(
                f"Batch 06 exclusion row has no work_row_id: {key}"
            )
        previous = matches.get(key)
        if previous is not None and previous.get("work_row_id") != work_row_id:
            raise ValueError(
                f"duplicate Batch 06 exclusion label: {key[0]}/{key[1]}"
            )
        matches[key] = row

    missing = sorted(expected - set(matches))
    if missing:
        formatted = ", ".join(
            f"{paper}/{label}" for paper, label in missing
        )
        raise ValueError(
            "Batch 06 exclusion rows are incomplete: " + formatted
        )

    exclusions = []
    for paper_id, label in sorted(expected):
        exclusions.append({
            "paper_id": paper_id,
            "compound_label": label,
            "work_row_id": str(matches[(paper_id, label)]["work_row_id"]),
            "stereochemistry_status": "ambiguous",
            "decision_note": (
                f"Paper {paper_id} reports compound {label} as a racemate, "
                "a stereoisomer mixture, or otherwise not as one uniquely "
                "assigned experimental stereoisomer; the machine-table "
                "stereochemical graph is therefore not publishable as a "
                "single confirmed molecule."
            ),
        })
    return exclusions


def build_batch06_structure_mismatches(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Build immutable work-row rejections for source-inconsistent graphs."""
    expected = {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in BATCH06_STRUCTURE_MISMATCH_LABELS.items()
        for label in labels
    }
    matches: dict[tuple[str, str], dict[str, object]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        key = (
            str(row.get("paper_id") or ""),
            normalize_compound_label(row.get("compound_label")),
        )
        if key not in expected:
            continue
        work_row_id = str(row.get("work_row_id") or "").strip()
        if not work_row_id:
            raise ValueError(f"Batch 06 mismatch row has no work_row_id: {key}")
        previous = matches.get(key)
        if previous is not None and previous.get("work_row_id") != work_row_id:
            raise ValueError(
                f"duplicate Batch 06 mismatch label: {key[0]}/{key[1]}"
            )
        matches[key] = row

    missing = sorted(expected - set(matches))
    if missing:
        formatted = ", ".join(f"{paper}/{label}" for paper, label in missing)
        raise ValueError("Batch 06 mismatch rows are incomplete: " + formatted)

    explanations = {
        ("56f50284cedf", normalize_compound_label("7-31B")): (
            "The machine row encodes a naphthalene-containing graph, whereas "
            "the article identifies 7-31B as the 4-methylcyclohexyl minor "
            "regioisomer and a 25:75 diastereomer mixture."
        ),
        ("1994543a9112", normalize_compound_label("58c")): (
            "The machine row duplicates the cyclobutyl structure of 58b, "
            "whereas the article identifies 58c as the isopropyl analogue; "
            "the reported material is also an epimer mixture."
        ),
    }
    return [
        {
            "paper_id": paper_id,
            "compound_label": label,
            "work_row_id": str(matches[(paper_id, label)]["work_row_id"]),
            "stereochemistry_status": "ambiguous",
            "decision_note": explanations[(paper_id, label)],
        }
        for paper_id, label in sorted(expected)
    ]


def publish_batch06_structure_reviews(
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, object]:
    """Publish SMIP component selections, then withdraw non-unique rows."""
    rows = _read_csv(Path(work_path))
    candidates = build_batch06_component_selection_candidates(rows)
    candidate_result = publish_reviewed_structure_candidates(
        candidates, work_path=work_path, confirmed_path=confirmed_path,
    )
    exclusions = build_batch06_structure_exclusions(
        candidate_result["work_rows"]
    )
    exclusion_result = publish_reviewed_structure_exclusions(
        exclusions, work_path=work_path, confirmed_path=confirmed_path,
    )
    mismatches = build_batch06_structure_mismatches(
        exclusion_result["work_rows"]
    )
    final_result = publish_reviewed_structure_mismatches(
        mismatches, work_path=work_path, confirmed_path=confirmed_path,
    )
    return {
        "component_candidates": candidates,
        "exclusions": exclusions,
        "mismatches": mismatches,
        "work_rows": final_result["work_rows"],
        "confirmed_rows": final_result["confirmed_rows"],
    }


def main() -> None:
    result = publish_batch06_structure_reviews()
    print(
        f"published_component_candidates="
        f"{len(result['component_candidates'])}"
    )
    print(f"published_exclusions={len(result['exclusions'])}")
    print(f"confirmed_rows={len(result['confirmed_rows'])}")


if __name__ == "__main__":
    main()
