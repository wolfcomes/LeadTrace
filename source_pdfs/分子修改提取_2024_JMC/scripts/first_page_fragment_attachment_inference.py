#!/usr/bin/env python3
"""Infer attachment-point fragments without silently confirming whole molecules.

This layer sits between PDF fragment recognition and final structure review. It
stores endpoint-marked fragment SMILES when the drawing supports them and may
attach a source-backed whole-molecule candidate when the same compound label
is present in a local ACS SI CSV. Neither result replaces the conservative
whole-molecule reconstruction snapshot.
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

from build_external_structure_references import (
    clean_source_smiles,
    read_csv as read_source_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBJECTS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_SOURCE_MANIFEST = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "external_sources" / "acs_si_source_manifest.csv"
DEFAULT_SOURCE_DIRECTORY = DEFAULT_SOURCE_MANIFEST.parent
DEFAULT_DOCUMENTS = PROJECT_ROOT / "02_text_extraction" / "full_document_text_index.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_fragment_attachment_inferences.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_fragment_attachment_inference_summary.json"

MISSING = "--"
INFERENCE_VERSION = "first_page_fragment_attachment_inference_v1_2026-09-05"
FRAGMENT_OBJECT_TYPES = {"shared_scaffold", "replacement_fragment", "linker_fragment", "variable_site"}

ATTACHMENT_INFERENCE_FIELDS = (
    "object_id", "paper_rank", "paper_id", "doi", "candidate_id", "page",
    "object_type", "compound_label", "crop_path", "parent_object_id",
    "attachment_points", "fragment_smiles", "fragment_smiles_status",
    "attachment_count", "attachment_status", "assembled_smiles",
    "assembly_status", "assembly_method", "source_evidence", "source_file",
    "source_locator", "inference_note", "confidence", "review_status",
    "annotation_version", "updated_at",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


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
            writer = csv.DictWriter(handle, fieldnames=ATTACHMENT_INFERENCE_FIELDS)
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


def _label_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _doi_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _canonical(smiles: object) -> str:
    raw = str(smiles or "").strip()
    if not raw or raw == MISSING:
        return MISSING
    RDLogger.DisableLog("rdApp.error")
    try:
        molecule = Chem.MolFromSmiles(raw)
        return Chem.MolToSmiles(molecule, isomericSmiles=True) if molecule is not None else MISSING
    finally:
        RDLogger.EnableLog("rdApp.error")


def _attachment_count(smiles: str) -> int:
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return 0
    return sum(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms())


# These are endpoint-marked readings of clearly drawn fragments. The dummy
# atoms are intentional: they encode the visible bond endpoints, not guessed
# atoms in an unseen parent scaffold.
FRAGMENT_SMILES_BY_KEY: dict[tuple[str, str], str] = {
    ("PAGE-621e2220dc85-CAND-001", "Linker a"): "[*:1]c1ccc(CC[*:2])cc1",
    ("PAGE-621e2220dc85-CAND-001", "Linker b"): "[*:1]c1cccc(CC[*:2])c1",
    ("PAGE-621e2220dc85-CAND-001", "Linker c"): "[*:1]CCCCC[*:2]",
    ("PAGE-621e2220dc85-CAND-001", "Linker d"): "[*:1]CCOCC[*:2]",
    ("PAGE-621e2220dc85-CAND-001", "Linker e"): "[*:1]CCCCCC[*:2]",
    ("PAGE-889b08022bee-CAND-003", "11"): "[*:1]N",
    ("PAGE-889b08022bee-CAND-003", "13"): "[*:1]N(C)",
    ("PAGE-889b08022bee-CAND-003", "14"): "[*:1]N(C)C",
    ("PAGE-889b08022bee-CAND-003", "15"): "[*:1]N(C(C)C)",
    ("PAGE-889b08022bee-CAND-003", "16"): "[*:1]NC1COC1",
    ("PAGE-889b08022bee-CAND-003", "17"): "[*:1]NC1CCOCC1",
    ("PAGE-889b08022bee-CAND-003", "18"): "[*:1]NC1CCC(F)(F)CC1",
    ("PAGE-889b08022bee-CAND-003", "19"): "[*:1]CN",
    ("PAGE-889b08022bee-CAND-003", "20"): "[*:1]CN(C(C)C)",
    ("PAGE-889b08022bee-CAND-003", "21"): "[*:1]CN(C)C",
    ("PAGE-889b08022bee-CAND-003", "22"): "[*:1]CN1CCN(C)CC1",
    ("PAGE-889b08022bee-CAND-003", "23"): "[*:1]CN1CCOCC1",
    ("PAGE-889b08022bee-CAND-003", "24"): "[*:1]CNC1CCOCC1",
    ("PAGE-880042186935-CAND-001", "3"): "[*:1]C1CCN(C(C)C)CC1",
    ("PAGE-880042186935-CAND-001", "5"): "[*:1]N1CCN(C(C)C)CC1",
}


def _find_source_columns(rows: list[Mapping[str, object]]) -> tuple[str, str] | None:
    if not rows:
        return None
    columns = list(rows[0])
    label = next((column for column in columns if _label_key(column) in {
        "compound", "compoundid", "compoundcode", "compoundnumber", "id",
    }), None)
    smiles = next((column for column in columns if "smile" in _label_key(column)), None)
    return (label, smiles) if label and smiles else None


def load_external_si_records(
    manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    source_directory: Path = DEFAULT_SOURCE_DIRECTORY,
) -> list[dict[str, str]]:
    """Load all valid local SI rows, including rows not matched to whole objects."""
    records: list[dict[str, str]] = []
    for manifest in read_csv(manifest_path):
        source_path = Path(source_directory) / str(manifest.get("source_file", ""))
        if not source_path.is_file():
            continue
        delimiter = str(manifest.get("delimiter", "") or ",")
        source_rows = read_source_csv(source_path, delimiter=delimiter)
        columns = _find_source_columns(source_rows)
        if not columns:
            continue
        label_column, smiles_column = columns
        for source_row in source_rows:
            smiles = clean_source_smiles(source_row.get(smiles_column, ""))
            if smiles == MISSING:
                continue
            label = str(source_row.get(label_column, "") or "").strip()
            if not label:
                continue
            records.append({
                "doi": str(manifest.get("doi", "")),
                "compound_label": label,
                "smiles": smiles,
                "source_evidence": str(manifest.get("source_type", "acs_figshare_si_csv")),
                "source_file": str(manifest.get("source_file", "")),
                "source_locator": f"{manifest.get('source_locator_prefix', 'Compound=')}{label}",
            })
    return records


def _source_record_for(
    row: Mapping[str, object], source_records: Iterable[Mapping[str, object]], doi_by_paper: Mapping[str, object],
) -> dict[str, str] | None:
    doi = str(row.get("doi") or doi_by_paper.get(str(row.get("paper_id", "")), "")).strip()
    label = _label_key(row.get("compound_label", ""))
    if not doi or not label:
        return None
    exact: list[Mapping[str, object]] = []
    prefix: list[Mapping[str, object]] = []
    for record in source_records:
        if _doi_key(record.get("doi")) != _doi_key(doi):
            continue
        source_label = _label_key(record.get("compound_label", ""))
        if source_label == label:
            exact.append(record)
        elif source_label and source_label.startswith(label):
            prefix.append(record)
    selected = exact[0] if exact else (prefix[0] if len(prefix) == 1 else None)
    if not selected:
        return None
    result = {str(key): str(value or "") for key, value in selected.items()}
    result["smiles"] = _canonical(result.get("smiles"))
    return result if result["smiles"] != MISSING else None


def _fragment_smiles(row: Mapping[str, object]) -> str:
    key = (str(row.get("candidate_id", "")), str(row.get("compound_label", "")))
    value = FRAGMENT_SMILES_BY_KEY.get(key, MISSING)
    if value == MISSING:
        return MISSING
    return value if Chem.MolFromSmiles(value) is not None else MISSING


def build_fragment_inference_rows(
    objects: Iterable[Mapping[str, object]],
    source_records: Iterable[Mapping[str, object]],
    *,
    doi_by_paper: Mapping[str, object] | None = None,
) -> list[dict[str, str]]:
    doi_by_paper = doi_by_paper or {}
    output: list[dict[str, str]] = []
    for object_row in objects:
        object_type = str(object_row.get("object_type", ""))
        if object_type not in FRAGMENT_OBJECT_TYPES:
            continue
        fragment_smiles = _fragment_smiles(object_row)
        source_record = _source_record_for(object_row, source_records, doi_by_paper)
        assembled_smiles = source_record["smiles"] if source_record else MISSING
        if fragment_smiles != MISSING:
            fragment_status = "attachment_smiles_valid"
            attachment_status = "attachment_points_inferred"
            attachment_count = str(_attachment_count(fragment_smiles))
        elif source_record:
            fragment_status = "not_recovered_source_anchor_only"
            attachment_status = "attachment_points_unresolved_source_anchor"
            attachment_count = "0"
        else:
            fragment_status = "not_recovered"
            attachment_status = "insufficient_visual_evidence"
            attachment_count = "0"

        if source_record:
            assembly_status = "source_anchored_whole_molecule_candidate"
            assembly_method = "exact_compound_label_source_anchor"
            confidence = "medium_high_pending_visual_review"
            note = (
                "The exact compound label has a local SI structure candidate; this does not prove the fragment crop "
                "shows the whole molecule, so PDF graph and attachment placement still require human review."
            )
        elif fragment_smiles != MISSING:
            assembly_status = "fragment_only_requires_parent_assembly"
            assembly_method = "endpoint_marked_fragment_graph"
            confidence = "medium_pending_parent_attachment"
            note = (
                "The visible fragment graph and endpoint count were inferred from the PDF drawing; no whole-molecule "
                "SMILES was emitted because the parent attachment is not fully resolved."
            )
        else:
            assembly_status = "not_assembled"
            assembly_method = "none"
            confidence = "low"
            note = (
                "Visible R/Site/Linker notation does not uniquely identify the attachment atom from the current crop; "
                "no fragment or whole-molecule SMILES was emitted."
            )

        doi = str(object_row.get("doi") or doi_by_paper.get(str(object_row.get("paper_id", "")), "")).strip()
        values = {
            "object_id": str(object_row.get("object_id", "")),
            "paper_rank": str(object_row.get("paper_rank", "")),
            "paper_id": str(object_row.get("paper_id", "")),
            "doi": doi or MISSING,
            "candidate_id": str(object_row.get("candidate_id", "")),
            "page": str(object_row.get("page", "")),
            "object_type": object_type,
            "compound_label": str(object_row.get("compound_label", "")) or MISSING,
            "crop_path": str(object_row.get("crop_path", "")) or MISSING,
            "parent_object_id": str(object_row.get("parent_object_id", "")) or MISSING,
            "attachment_points": str(object_row.get("attachment_points", "")) or MISSING,
            "fragment_smiles": fragment_smiles,
            "fragment_smiles_status": fragment_status,
            "attachment_count": attachment_count,
            "attachment_status": attachment_status,
            "assembled_smiles": assembled_smiles,
            "assembly_status": assembly_status,
            "assembly_method": assembly_method,
            "source_evidence": str(source_record.get("source_evidence", "acs_figshare_si_csv")) if source_record else MISSING,
            "source_file": str(source_record.get("source_file", MISSING)) if source_record else MISSING,
            "source_locator": str(source_record.get("source_locator", MISSING)) if source_record else MISSING,
            "inference_note": note,
            "confidence": confidence,
            "review_status": "candidate_requires_human_review",
            "annotation_version": INFERENCE_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        output.append({field: str(values.get(field, MISSING) or MISSING) for field in ATTACHMENT_INFERENCE_FIELDS})
    return output


def write_fragment_inference_snapshot(
    objects: Iterable[Mapping[str, object]],
    source_records: Iterable[Mapping[str, object]],
    output_path: Path = DEFAULT_OUTPUT,
    summary_path: Path = DEFAULT_SUMMARY,
    *,
    doi_by_paper: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    rows = build_fragment_inference_rows(objects, source_records, doi_by_paper=doi_by_paper)
    status_counts = Counter(row["attachment_status"] for row in rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": INFERENCE_VERSION,
        "object_rows": len(rows),
        "fragment_smiles_rows": sum(row["fragment_smiles"] != MISSING for row in rows),
        "assembled_candidate_rows": sum(row["assembled_smiles"] != MISSING for row in rows),
        "attachment_points_inferred": status_counts.get("attachment_points_inferred", 0),
        "attachment_points_unresolved_source_anchor": status_counts.get("attachment_points_unresolved_source_anchor", 0),
        "insufficient_visual_evidence": status_counts.get("insufficient_visual_evidence", 0),
        "attachment_status_counts": dict(status_counts),
        "assembly_status_counts": dict(Counter(row["assembly_status"] for row in rows)),
        "review_status_counts": dict(Counter(row["review_status"] for row in rows)),
        "output_path": str(Path(output_path).resolve()),
    }
    _atomic_write_csv(output_path, rows)
    _atomic_write_json(summary_path, summary)
    return rows, summary


def _doi_index(path: Path) -> dict[str, str]:
    return {row.get("paper_id", ""): row.get("doi", "") for row in read_csv(path) if row.get("paper_id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_DIRECTORY)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    rows, summary = write_fragment_inference_snapshot(
        read_csv(args.objects),
        load_external_si_records(args.manifest, args.source_directory),
        args.output,
        args.summary,
        doi_by_paper=_doi_index(args.documents) if args.documents.is_file() else {},
    )
    print(json.dumps({**summary, "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
