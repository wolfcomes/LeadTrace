#!/usr/bin/env python3
"""Publish the source-audited Batch05 / Batch06 stereochemistry repairs.

The module intentionally distinguishes three situations:

* a source-reported racemate or stereoisomer mixture;
* a source that does not assign one absolute stereochemical molecule; and
* an experimental entry whose full name explicitly assigns the omitted
  alpha center as R.

Only the third group receives a replacement isomeric SMILES.  The first two
groups retain their source rows in the work table but are withdrawn from the
authoritative single-molecule table.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

from rdkit import Chem
from rdkit.Chem.EnumerateStereoisomers import (
    EnumerateStereoisomers,
    StereoEnumerationOptions,
)

from lineage_structure_reconstruction import (
    DEFAULT_CONFIRMED_PATH,
    DEFAULT_WORK_PATH,
    build_reviewed_structure_work_row,
    normalize_compound_label,
    publish_reviewed_structure_candidates,
    publish_reviewed_structure_exclusions,
)


PAPER_0EB_MAIN_PDF = (
    "source_pdfs/case volume67 issue14-18/"
    "cole-et-al-2024-rational-design-synthesis-and-structure-activity-"
    "relationship-of-a-novel-isoquinolinone-based-series-of.pdf"
)
PAPER_0EB_SOURCE_FILE = "jm4c01568_si_002.csv"

# These labels have an explicit (R) experimental name in the article.  Seven
# other isolated records (3c and 3e-3j) are deliberately absent because the
# source calls them only "Enantiomer II" and does not assign absolute R/S.
ACTIVE_R_LABELS = tuple(
    normalize_compound_label(label)
    for label in (
        "3b", "3d",
        "4a", "4b", "4c", "4d", "4f", "4g", "4h", "4i", "4j", "4k", "4l",
        "5a", "5b", "5c", "5d", "5e", "5f", "5g", "5h",
        "6", "7", "8", "9", "10", "11", "12",
    )
)

ACTIVE_R_PDF_PAGES = {
    **{label: 16 for label in ("3b", "3d")},
    **{label: 17 for label in ("4a", "4b", "4c", "4d", "4f", "4g", "4h", "4i")},
    **{label: 18 for label in ("4j", "4k", "4l", "5a", "5b", "5c", "5d", "5e")},
    **{label: 19 for label in ("5f", "5g", "5h", "6", "7", "8", "9")},
    **{label: 20 for label in ("10", "11", "12")},
}

BATCH05_EXCLUSION_LABELS: dict[str, tuple[str, ...]] = {
    # Every listed graph has an unassigned alpha-carboxylic-acid center.  The
    # article explicitly reports 14 as two separated enantiomers and 50/53/54
    # as four-stereoisomer mixtures; it does not assign a unique experimental
    # stereoisomer for the remaining paper-local labels.
    "cfc4a0d0ef41": ("7", *tuple(str(number) for number in range(11, 62))),
    # 4e is explicitly a racemate.  The other seven labels are isolated as
    # Enantiomer II but have no source-supported absolute R/S assignment.
    "0eb39d3b45ae": ("3c", "3e", "3f", "3g", "3h", "3i", "3j", "4e"),
    # 33 is a two-diastereomer mixture; 31 and 44 contain additional centers
    # that are not fully assigned by the source.
    "1a7457834b7a": ("31", "33", "44"),
    # Source label 21 corresponds to explicitly racemic article compound 21f;
    # sulfoxides 3 and 5 have no assigned sulfur configuration.
    "2f3a5d2f7fb0": ("3", "5", "21"),
    # The common glutarimide stereocenter is not assigned for these materials.
    "f2e855803f5a": (
        "CC-90009",
        *tuple(f"LYG-{number}" for number in range(101, 109)),
        *tuple(f"LYG-{number}" for number in range(201, 208)),
        *tuple(f"LYG-{number}" for number in range(301, 310)),
        *tuple(f"LYG-{number}" for number in range(401, 422)),
    ),
}

BATCH06_EXCLUSION_LABELS: dict[str, tuple[str, ...]] = {
    # Both experimental entries explicitly say that the isolated material is
    # the pair of R/S ring diastereomers relative to the fixed R morpholine.
    "2a98b0589a08": ("12", "15"),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _exclusion_reason(paper_id: str, label: str) -> str:
    normalized = normalize_compound_label(label)
    if paper_id == "cfc4a0d0ef41":
        if normalized == "14":
            return (
                "Article PDF page 4 states that chiral separation of compound "
                "14 yielded two enantiomers; the source graph does not select "
                "one unique experimental stereoisomer."
            )
        if normalized in {"50", "53", "54"}:
            page = 27 if normalized == "50" else 29
            return (
                f"Article PDF page {page} explicitly reports compound "
                f"{normalized} as a mix of four stereoisomers; the source "
                "graph cannot represent that material as one molecule."
            )
        return (
            "Article PDF and the DOI-exact source table do not assign one "
            f"unique alpha-carboxylic-acid stereoisomer for compound {label}; "
            "the source connectivity remains auditable but is not a unique "
            "stereochemical molecule."
        )
    if paper_id == "0eb39d3b45ae":
        if normalized == "4e":
            return (
                "Article PDF pages 6 and 17 explicitly identify compound 4e "
                "as a racemate; the source graph is not one unique molecule."
            )
        return (
            f"Article experimental entry for compound {label} identifies the "
            "isolated material only as Enantiomer II; the source does not "
            "assign an absolute R/S configuration, so no arbitrary source-"
            "unsupported isomeric SMILES is published."
        )
    if paper_id == "1a7457834b7a":
        if normalized == "33":
            return (
                "Article PDF page 18 explicitly reports source compound 33 as "
                "the first-eluting mixture of two diastereomers."
            )
        return (
            f"The article source for compound {label} does not assign every "
            "stereogenic center represented by the Paper-local material; its "
            "connectivity is retained only as an auditable source candidate."
        )
    if paper_id == "2f3a5d2f7fb0":
        if normalized == "21":
            return (
                "Article PDF page 5 identifies source-table label 21 as "
                "racemic alpha-methyl compound 21f."
            )
        return (
            f"The article source for sulfoxide compound {label} assigns no "
            "absolute sulfur stereochemistry or enantiomer separation."
        )
    if paper_id == "f2e855803f5a":
        return (
            f"The article and DOI-exact structure source for compound {label} "
            "do not assign the glutarimide stereocenter as one unique "
            "experimental stereoisomer."
        )
    if paper_id == "2a98b0589a08":
        page = 14 if normalized == "12" else 16
        return (
            f"Article PDF page {page} explicitly reports compound {label} as "
            "the diastereomers containing both R and S sulfone-ring centers "
            "relative to the fixed R-methylmorpholine center."
        )
    raise ValueError(f"no reviewed exclusion reason for {paper_id}/{label}")


def _expected_exclusion_keys(
    manifest: Mapping[str, Iterable[str]],
) -> set[tuple[str, str]]:
    return {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in manifest.items()
        for label in labels
    }


def _build_exclusion_group(
    manifest: Mapping[str, Iterable[str]],
    *,
    work_rows: Iterable[Mapping[str, object]],
    confirmed_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    expected = _expected_exclusion_keys(manifest)
    work_by_id = {
        str(row.get("work_row_id") or "").strip(): dict(row)
        for row in work_rows
        if str(row.get("work_row_id") or "").strip()
    }
    confirmed_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in confirmed_rows:
        key = (
            str(row.get("paper_id") or "").strip(),
            normalize_compound_label(
                row.get("normalized_label") or row.get("compound_label")
            ),
        )
        if key not in expected:
            continue
        if key in confirmed_by_key:
            raise ValueError(f"duplicate confirmed exclusion key: {key}")
        confirmed_by_key[key] = dict(row)

    selected: dict[tuple[str, str], dict[str, object]] = {}
    for key in expected:
        confirmed = confirmed_by_key.get(key)
        if confirmed is not None:
            work_row_id = str(confirmed.get("accepted_work_row_id") or "").strip()
            work = work_by_id.get(work_row_id)
            if work is None:
                raise ValueError(
                    f"confirmed exclusion work row not found: {key[0]}/{key[1]}"
                )
            if (
                str(work.get("paper_id") or ""),
                normalize_compound_label(
                    work.get("normalized_label") or work.get("compound_label")
                ),
            ) != key:
                raise ValueError(
                    f"confirmed exclusion work-row key mismatch: {key[0]}/{key[1]}"
                )
            selected[key] = work
            continue

        # Idempotent reruns bind the already rejected immutable work row.
        rejected = [
            row for row in work_by_id.values()
            if (
                str(row.get("paper_id") or ""),
                normalize_compound_label(
                    row.get("normalized_label") or row.get("compound_label")
                ),
            ) == key
            and str(row.get("review_decision") or "") == "reject"
            and str(row.get("stereochemistry_status") or "") == "ambiguous"
            and str(row.get("reconstruction_reason") or "")
            == _exclusion_reason(*key)
        ]
        if len(rejected) != 1:
            raise ValueError(
                f"expected one current or previously rejected work row for "
                f"{key[0]}/{key[1]}; observed {len(rejected)}"
            )
        selected[key] = rejected[0]

    if set(selected) != expected:
        raise ValueError("reviewed exclusion manifest is incomplete")
    return [
        {
            "paper_id": paper_id,
            "compound_label": label,
            "work_row_id": str(selected[(paper_id, label)]["work_row_id"]),
            "stereochemistry_status": "ambiguous",
            "decision_note": _exclusion_reason(paper_id, label),
        }
        for paper_id, label in sorted(expected)
    ]


def build_reviewed_exclusions(
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, list[dict[str, str]]]:
    """Bind every reviewed exclusion to its authoritative immutable row."""
    work_rows = _read_csv(Path(work_path))
    confirmed_rows = _read_csv(Path(confirmed_path))
    return {
        "batch05": _build_exclusion_group(
            BATCH05_EXCLUSION_LABELS,
            work_rows=work_rows,
            confirmed_rows=confirmed_rows,
        ),
        "batch06": _build_exclusion_group(
            BATCH06_EXCLUSION_LABELS,
            work_rows=work_rows,
            confirmed_rows=confirmed_rows,
        ),
    }


def assign_single_unassigned_tetrahedral_cip(
    smiles: str,
    desired_cip: str,
) -> str:
    """Assign one and only one unassigned tetrahedral center by CIP label."""
    desired = str(desired_cip or "").strip().upper()
    if desired not in {"R", "S"}:
        raise ValueError("desired CIP label must be R or S")
    molecule = Chem.MolFromSmiles(str(smiles or "").strip())
    if molecule is None:
        raise ValueError("source structure is not RDKit-parseable")
    unassigned = [
        stereo for stereo in Chem.FindPotentialStereo(
            molecule, cleanIt=True, flagPossible=True,
        )
        if stereo.specified == Chem.StereoSpecified.Unspecified
        and str(stereo.type) == "Atom_Tetrahedral"
    ]
    if len(unassigned) != 1:
        raise ValueError(
            "source structure must contain exactly one unassigned tetrahedral "
            f"center; observed {len(unassigned)}"
        )
    center_index = int(unassigned[0].centeredOn)
    options = StereoEnumerationOptions(
        onlyUnassigned=True,
        unique=True,
        tryEmbedding=False,
    )
    matches: list[Chem.Mol] = []
    for candidate in EnumerateStereoisomers(molecule, options=options):
        Chem.AssignStereochemistry(candidate, cleanIt=True, force=True)
        atom = candidate.GetAtomWithIdx(center_index)
        if atom.HasProp("_CIPCode") and atom.GetProp("_CIPCode") == desired:
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError(
            f"expected one enumerated {desired} stereoisomer; observed "
            f"{len(matches)}"
        )
    return Chem.MolToSmiles(matches[0], canonical=True, isomericSmiles=True)


def _active_r_source_rows(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    expected = set(ACTIVE_R_LABELS)
    by_label: dict[str, dict[str, object]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        label = normalize_compound_label(
            row.get("normalized_label") or row.get("compound_label")
        )
        if (
            str(row.get("paper_id") or "") != "0eb39d3b45ae"
            or label not in expected
            or str(row.get("source_file") or "") != PAPER_0EB_SOURCE_FILE
            or str(row.get("reconstruction_method") or "")
            != "direct_source_structure"
            or str(row.get("binding_status") or "") != "matched"
        ):
            continue
        if label in by_label:
            raise ValueError(f"duplicate active-R source row: {label}")
        by_label[label] = row
    missing = sorted(expected - set(by_label))
    if missing:
        raise ValueError("active-R source rows are incomplete: " + ", ".join(missing))
    return by_label


def build_active_r_replacements(
    *,
    work_path: Path = DEFAULT_WORK_PATH,
) -> list[dict[str, str]]:
    """Create source-located replacements for all explicit (R) entries."""
    source_by_label = _active_r_source_rows(_read_csv(Path(work_path)))
    candidates: list[dict[str, str]] = []
    for label in ACTIVE_R_LABELS:
        source = source_by_label[label]
        corrected = assign_single_unassigned_tetrahedral_cip(
            str(source.get("canonical_isomeric_smiles") or ""), "R"
        )
        page = ACTIVE_R_PDF_PAGES[label]
        source_locator = (
            f"Main PDF page {page}, explicit (R) experimental entry for "
            f"compound {label}; {PAPER_0EB_SOURCE_FILE} "
            f"{source['source_locator']}; source work row "
            f"{source['work_row_id']}"
        )
        candidates.append(build_reviewed_structure_work_row(
            paper_id="0eb39d3b45ae",
            compound_entity_id=str(source["compound_entity_id"]),
            compound_label=label,
            canonical_isomeric_smiles=corrected,
            source_id=(
                f"article-and-si:0eb39d3b45ae:{source['work_row_id']}"
            ),
            source_file=f"{PAPER_0EB_MAIN_PDF}; {PAPER_0EB_SOURCE_FILE}",
            source_locator=source_locator,
            source_label=str(source["source_label"]),
            reconstruction_method="reviewed_complete_structure",
            source_match_status="reconstructed_source_graph_match",
            decision_note=(
                f"The DOI-exact source row supplies the complete connectivity "
                f"for compound {label}. The article's experimental name on "
                f"PDF page {page} explicitly assigns the omitted alpha center "
                "as R. RDKit enumeration selects the unique R-CIP graph while "
                "preserving every source-encoded stereocenter."
            ),
            stereochemistry_status="source_encoded",
            replacement_decision="explicit_replace",
        ))
    return candidates


def publish_batch05_06_audit_repairs(
    *,
    work_path: Path = DEFAULT_WORK_PATH,
    confirmed_path: Path = DEFAULT_CONFIRMED_PATH,
) -> dict[str, object]:
    """Withdraw reviewed non-unique rows, then publish explicit R repairs."""
    exclusions = build_reviewed_exclusions(
        work_path=work_path,
        confirmed_path=confirmed_path,
    )
    # Build every replacement before the first write.  A missing or
    # non-reconstructable source row must fail the complete batch preflight,
    # not leave the exclusion half of the publication applied on its own.
    replacements = build_active_r_replacements(work_path=work_path)
    all_exclusions = [*exclusions["batch05"], *exclusions["batch06"]]
    exclusion_result = publish_reviewed_structure_exclusions(
        all_exclusions,
        work_path=work_path,
        confirmed_path=confirmed_path,
    )
    result = publish_reviewed_structure_candidates(
        replacements,
        work_path=work_path,
        confirmed_path=confirmed_path,
    )
    return {
        "batch05_exclusions": exclusions["batch05"],
        "batch06_exclusions": exclusions["batch06"],
        "active_r_replacements": replacements,
        "work_rows": result["work_rows"],
        "confirmed_rows": result["confirmed_rows"],
        "post_exclusion_confirmed_rows": exclusion_result["confirmed_rows"],
    }


def main() -> None:
    result = publish_batch05_06_audit_repairs()
    print(f"published_batch05_exclusions={len(result['batch05_exclusions'])}")
    print(f"published_batch06_exclusions={len(result['batch06_exclusions'])}")
    print(f"published_active_r_replacements={len(result['active_r_replacements'])}")
    print(f"confirmed_rows={len(result['confirmed_rows'])}")


if __name__ == "__main__":
    main()
