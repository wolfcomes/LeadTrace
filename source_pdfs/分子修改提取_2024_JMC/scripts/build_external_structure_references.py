#!/usr/bin/env python3
"""Build source-backed structure records from ACS Supporting Information CSVs.

ACS Figshare CSVs are treated as external provenance, not as an instruction to
overwrite the confirmed dataset.  The output contains only exact matches to
already-localized complete molecule objects.  Fragment objects are excluded so
an SI record cannot accidentally turn an R/Site/Linker fragment into a whole
molecule.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping

from rdkit import Chem
from rdkit import RDLogger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBJECTS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_CANDIDATES = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "structure_ocr_candidates.csv"
DEFAULT_SOURCE_MANIFEST = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "external_sources" / "acs_si_source_manifest.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_external_references.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_external_reference_summary.json"
DEFAULT_VISUAL_REVIEWS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_external_visual_match_reviews.csv"
MISSING = "--"
REFERENCE_VERSION = "external_structure_references_v1_2026-09-05"
ELIGIBLE_OBJECT_TYPES = {"complete_molecule", "molecule_series_member", "mixed_region_molecule"}

EXTERNAL_REFERENCE_FIELDS = (
    "reference_id", "object_id", "paper_rank", "paper_id", "doi", "candidate_id", "page",
    "compound_label", "object_type", "crop_path", "source_file", "source_type",
    "source_locator", "source_label", "raw_source_smiles", "smiles", "canonical_smiles",
    "label_match_type", "reference_status", "visual_match_status", "source_record_json",
    "annotation_version", "updated_at",
)


def read_csv(path: Path, *, delimiter: str = ",") -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            fieldnames = next(reader)
        except StopIteration:
            return []
        smiles_index = next(
            (index for index, field in enumerate(fieldnames)
             if "smiles" in _normalise_label(field) or "smile" in _normalise_label(field)),
            None,
        )
        rows: list[dict[str, str]] = []
        for fields in reader:
            if not fields:
                continue
            # A few ACS SI exports leave commas inside ``|a:...|`` annotations
            # unquoted. Rejoin those fields before mapping values to headers.
            if smiles_index is not None and len(fields) > len(fieldnames):
                extra_fields = len(fields) - len(fieldnames)
                end = smiles_index + extra_fields + 1
                fields = (
                    fields[:smiles_index]
                    + [delimiter.join(fields[smiles_index:end])]
                    + fields[end:]
                )
            if len(fields) < len(fieldnames):
                fields = fields + [""] * (len(fieldnames) - len(fields))
            rows.append(dict(zip(fieldnames, fields)))
        return rows


def _atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=EXTERNAL_REFERENCE_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _normalise_label(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _source_label_key(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    exact = _normalise_label(raw)
    # Some SI files append a stereochemical or material note to the compound
    # identifier, e.g. "36 (individual enantiomer...)".
    prefix = re.match(r"^([A-Za-z]*\d+[A-Za-z]*)", raw)
    return exact, _normalise_label(prefix.group(1)) if prefix else ""


def clean_source_smiles(value: object) -> str:
    """Remove SI atom-map annotations while retaining the actual SMILES graph."""
    raw = str(value or "").strip()
    cleaned = re.sub(r"\s*\|[^|]*\|\s*$", "", raw).strip()
    if not cleaned or cleaned == MISSING:
        return MISSING
    RDLogger.DisableLog("rdApp.error")
    try:
        molecule = Chem.MolFromSmiles(cleaned)
    finally:
        RDLogger.EnableLog("rdApp.error")
    if molecule is None:
        return MISSING
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def _find_columns(source_rows: list[Mapping[str, object]], label_column: str | None, smiles_column: str | None) -> tuple[str, str]:
    if not source_rows:
        raise ValueError("source CSV has no rows")
    columns = list(source_rows[0].keys())
    if label_column and label_column not in columns:
        raise ValueError(f"label column {label_column!r} is not present")
    if smiles_column and smiles_column not in columns:
        raise ValueError(f"SMILES column {smiles_column!r} is not present")
    label = label_column or next((column for column in columns if _normalise_label(column) in {"compound", "compoundid", "compoundcode", "compoundnumber", "id"}), None)
    smiles = smiles_column or next((column for column in columns if "smiles" in _normalise_label(column) or "smile" in _normalise_label(column)), None)
    if not label or not smiles:
        raise ValueError(f"could not identify label/SMILES columns from {columns!r}")
    return label, smiles


def build_external_reference_rows(
    objects: Iterable[Mapping[str, object]], source_rows: Iterable[Mapping[str, object]], *,
    doi: str, source_file: str, source_type: str, label_column: str | None = None,
    smiles_column: str | None = None, source_locator_prefix: str = "Compound=",
    mapping_status: str = "numbered_label_matches_si_record",
    visual_match_status: str = "requires_visual_graph_check",
    visual_review_by_object_id: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Match SI records to whole-molecule objects and return rows plus unmatched data."""
    object_index: dict[str, list[Mapping[str, object]]] = {}
    for row in objects:
        if str(row.get("object_type", "")) not in ELIGIBLE_OBJECT_TYPES:
            continue
        if str(row.get("doi", "")).strip().casefold() != str(doi).strip().casefold():
            continue
        label = _normalise_label(row.get("compound_label", ""))
        if label:
            object_index.setdefault(label, []).append(row)

    source_list = [dict(row) for row in source_rows]
    label_column, smiles_column = _find_columns(source_list, label_column, smiles_column)
    output: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    used_object_ids: set[str] = set()
    visual_review_by_object_id = visual_review_by_object_id or {}
    for source_row in source_list:
        source_label = str(source_row.get(label_column, "") or "").strip()
        exact_key, prefix_key = _source_label_key(source_label)
        candidates = object_index.get(exact_key, [])
        match_type = "exact_label"
        if not candidates and prefix_key:
            candidates = object_index.get(prefix_key, [])
            match_type = "source_label_prefix"
        candidates = [row for row in candidates if str(row.get("object_id", "")) not in used_object_ids]
        raw_smiles = str(source_row.get(smiles_column, "") or "").strip()
        smiles = clean_source_smiles(raw_smiles)
        if not candidates or smiles == MISSING:
            unmatched.append({
                "source_label": source_label, "raw_source_smiles": raw_smiles,
                "reason": "no_eligible_object_match" if not candidates else "invalid_source_smiles",
                "source_file": source_file,
            })
            continue
        object_row = candidates[0]
        object_id = str(object_row.get("object_id", ""))
        used_object_ids.add(object_id)
        visual_review = visual_review_by_object_id.get(object_id, {})
        reviewed_reference_status = str(
            visual_review.get("review_status") or "external_source_requires_visual_match"
        )
        reviewed_visual_match_status = str(
            visual_review.get("visual_match_status") or visual_match_status
        )
        source_record = {str(key): str(value or "") for key, value in source_row.items()}
        output.append({
            "reference_id": f"{object_id}::external::{_normalise_label(source_label)}",
            "object_id": object_id,
            "paper_rank": str(object_row.get("paper_rank", "")),
            "paper_id": str(object_row.get("paper_id", "")),
            "doi": str(doi),
            "candidate_id": str(object_row.get("candidate_id", "")),
            "page": str(object_row.get("page", "")),
            "compound_label": str(object_row.get("compound_label", "")) or MISSING,
            "object_type": str(object_row.get("object_type", "")),
            "crop_path": str(object_row.get("crop_path", "")) or MISSING,
            "source_file": str(source_file),
            "source_type": str(source_type),
            "source_locator": f"{source_locator_prefix}{source_label}",
            "source_label": source_label,
            "raw_source_smiles": raw_smiles or MISSING,
            "smiles": smiles,
            "canonical_smiles": smiles,
            "label_match_type": match_type,
            "reference_status": reviewed_reference_status,
            "visual_match_status": reviewed_visual_match_status,
            "source_record_json": json.dumps(source_record, ensure_ascii=True, separators=(",", ":")),
            "annotation_version": REFERENCE_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return output, unmatched


def _manifest_rows(path: Path) -> list[dict[str, str]]:
    return read_csv(path)


def write_external_reference_snapshot(
    objects: Iterable[Mapping[str, object]], source_rows: Iterable[Mapping[str, object]], *,
    doi: str, source_file: str, source_type: str, label_column: str | None = None,
    smiles_column: str | None = None, source_locator_prefix: str = "Compound=",
    mapping_status: str = "numbered_label_matches_si_record",
    visual_match_status: str = "requires_visual_graph_check",
    visual_review_by_object_id: Mapping[str, Mapping[str, object]] | None = None,
    output_path: Path = DEFAULT_OUTPUT, summary_path: Path = DEFAULT_SUMMARY,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    rows, unmatched = build_external_reference_rows(
        objects, source_rows, doi=doi, source_file=source_file, source_type=source_type,
        label_column=label_column, smiles_column=smiles_column,
        source_locator_prefix=source_locator_prefix, mapping_status=mapping_status,
        visual_match_status=visual_match_status,
        visual_review_by_object_id=visual_review_by_object_id,
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": REFERENCE_VERSION,
        "source_file": source_file,
        "doi": doi,
        "matched_rows": len(rows),
        "unmatched_rows": len(unmatched),
        "unmatched": unmatched,
        "output_path": str(Path(output_path).resolve()),
    }
    _atomic_write_csv(output_path, rows)
    _atomic_write_json(summary_path, summary)
    return rows, summary


def _delimiter_for_file(path: Path) -> str:
    return ";" if path.name == "jm4c02172_si_002.csv" else ","


def build_from_manifest(
    objects: Iterable[Mapping[str, object]], manifest_rows: Iterable[Mapping[str, object]],
    source_directory: Path, output_path: Path = DEFAULT_OUTPUT, summary_path: Path = DEFAULT_SUMMARY,
    *, doi_by_paper: Mapping[str, object] | None = None,
    visual_review_by_object_id: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    doi_by_paper = doi_by_paper or {}
    visual_review_by_object_id = visual_review_by_object_id or {}
    joined_objects = [
        {
            **dict(row),
            "doi": str(row.get("doi") or doi_by_paper.get(str(row.get("paper_id", "")), "")),
        }
        for row in objects
    ]
    all_rows: list[dict[str, str]] = []
    all_unmatched: list[dict[str, str]] = []
    manifest = [dict(row) for row in manifest_rows]
    for source in manifest:
        source_path = Path(source_directory) / str(source["source_file"])
        if not source_path.is_file():
            all_unmatched.append({"source_file": str(source["source_file"]), "reason": "source_file_missing"})
            continue
        source_rows = read_csv(source_path, delimiter=str(source.get("delimiter", "") or ","))
        rows, unmatched = build_external_reference_rows(
            joined_objects, source_rows, doi=str(source["doi"]), source_file=str(source["source_file"]),
            source_type=str(source.get("source_type", "acs_figshare_si_csv")),
            label_column=str(source.get("label_column", "")) or None,
            smiles_column=str(source.get("smiles_column", "")) or None,
            source_locator_prefix=str(source.get("source_locator_prefix", "Compound=")),
            visual_match_status=str(source.get("visual_match_status", "requires_visual_graph_check")),
            visual_review_by_object_id=visual_review_by_object_id,
        )
        all_rows.extend(rows)
        all_unmatched.extend(unmatched)
    reference_status_counts = Counter(row["reference_status"] for row in all_rows)
    if not all_rows:
        source_status = "no_external_records_matched"
    elif set(reference_status_counts) == {"external_source_requires_visual_match"}:
        source_status = "external_records_require_visual_match"
    elif set(reference_status_counts) == {"external_source_visual_match_confirmed"}:
        source_status = "external_records_visual_match_confirmed"
    else:
        source_status = "external_records_mixed_review_state"
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": REFERENCE_VERSION,
        "source_files": len(manifest),
        "matched_rows": len(all_rows),
        "unmatched_rows": len(all_unmatched),
        "matched_object_ids": len({row["object_id"] for row in all_rows}),
        "source_status": source_status,
        "reference_status_counts": dict(reference_status_counts),
        "visual_match_status_counts": dict(Counter(row["visual_match_status"] for row in all_rows)),
        "unmatched_sample": all_unmatched[:100],
        "output_path": str(Path(output_path).resolve()),
    }
    _atomic_write_csv(output_path, all_rows)
    _atomic_write_json(summary_path, summary)
    return all_rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_MANIFEST.parent)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--visual-reviews", type=Path, default=DEFAULT_VISUAL_REVIEWS)
    args = parser.parse_args(argv)
    visual_reviews = read_csv(args.visual_reviews) if args.visual_reviews.is_file() else []
    rows, summary = build_from_manifest(
        read_csv(args.objects), _manifest_rows(args.manifest), args.source_directory,
        args.output, args.summary,
        doi_by_paper={row.get("paper_id", ""): row.get("doi", "") for row in read_csv(args.candidates)} if args.candidates.is_file() else {},
        visual_review_by_object_id={row.get("object_id", ""): row for row in visual_reviews if row.get("object_id")},
    )
    print(json.dumps({**summary, "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
