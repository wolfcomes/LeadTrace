#!/usr/bin/env python3
"""Populate the Paper review layer from the complete text-path snapshot.

This stage is intentionally conservative. Text fields are copied into a
reviewable row for every enriched candidate. Exact endpoint structures are
filled only when the SI reference contains both compound SMILES. R groups and
linkers are represented as attachment-point notation, never as fabricated
complete molecules.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

from rdkit import Chem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATHS_PATH = PROJECT_ROOT / "07_enriched_text_paths" / "all_path_candidates_enriched.csv"
EVIDENCE_PATH = PROJECT_ROOT / "03_sar_candidates" / "full_evidence_candidates.csv"
MANIFEST_PATH = PROJECT_ROOT / "01_manifest" / "all_volume67_papers.csv"
REFERENCE_PATH = PROJECT_ROOT / "09_structure_confirmation" / "compound_smiles_reference.csv"
OUTPUT_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
AUTO_FILLED_PATH = OUTPUT_DIR / "auto_filled_review_items.csv"
PROGRESS_PATH = OUTPUT_DIR / "paper_processing_progress.csv"
SUMMARY_PATH = OUTPUT_DIR / "auto_fill_summary.json"

GENERIC_STRUCTURE_MARKERS = re.compile(
    r"\bR\d*\b|\bR[- ]?group\b|\blink(?:er|ers|ed|ing)?\b|"
    r"\b(?:bond|bonds)\b|\b(?:connected|linked)\b",
    re.IGNORECASE,
)
R_LABEL = re.compile(r"\bR\d*\b", re.IGNORECASE)
LINKER_FRAGMENT = re.compile(
    r"(?P<fragment>(?:[-−]?\s*(?:CH\d*|NH\d*|N|O|S|C|CO|CONH|C\(=O\))\s*){2,}[-−]?)\s*linker",
    re.IGNORECASE,
)
LINKER_DESCRIPTION = re.compile(
    r"(?P<description>[A-Za-z0-9α-ωΑ-Ω,\-−+()/ ]{3,80}?\s+linker(?:\s*\([^)]*\))?)",
    re.IGNORECASE,
)

AUTO_FIELDS = [
    "review_item_id", "paper_id", "doi", "page", "page_references",
    "parent_compound", "derived_compound", "reported_from_group",
    "reported_to_group", "activity", "evidence_text", "compound_mentions",
    "relation_type", "path_status", "structure_review_status",
    "structure_confirmation_status", "parent_smiles", "derived_smiles",
    "parent_canonical_smiles", "derived_canonical_smiles",
    "structure_representation_kind", "structure_expression", "attachment_points",
    "structure_source", "structure_source_locator", "auto_fill_status",
    "auto_fill_source", "source_path_candidate_id", "review_status",
]

PROGRESS_FIELDS = [
    "paper_id", "auto_fill_status", "auto_filled_entries", "structure_candidate_entries",
    "exact_structure_entries", "generic_structure_entries", "statement_only_entries",
]

STRUCTURE_QUEUE_FIELDS = [
    "review_item_id", "paper_id", "doi", "source_pdf", "page",
    "parent_compound", "derived_compound", "reported_from_group",
    "reported_to_group", "relation_type", "evidence_text", "structure_need",
    "page_has_table_or_scheme_signal", "page_has_figure_signal", "pdf_exists",
    "structure_review_queue_status",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def load_reference(rows: Iterable[Mapping[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    reference: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (str(row.get("doi", "")).strip(), str(row.get("compound_id", "")).strip())
        if not key[0] or not key[1] or not str(row.get("smiles", "")).strip():
            continue
        reference[key] = {key_name: str(value or "").strip() for key_name, value in row.items()}
    return reference


def classify_structure_need(row: Mapping[str, object]) -> str:
    if str(row.get("parent_compound", "")).strip() and str(row.get("derived_compound", "")).strip():
        return "exact_pair_candidate"
    if GENERIC_STRUCTURE_MARKERS.search(str(row.get("evidence_text", ""))):
        return "generic_r_group_or_linker"
    return "statement_only"


def _clean_expression(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,;:")


def extract_generic_structure_expression(text: str) -> dict[str, str]:
    """Describe R/linker chemistry without claiming a complete molecule."""
    labels = []
    for match in R_LABEL.finditer(text):
        label = match.group(0).upper()
        if label not in labels:
            labels.append(label)
    fragment = LINKER_FRAGMENT.search(text)
    if fragment:
        expression = _clean_expression(fragment.group("fragment"))
        return {
            "representation_kind": "linker_notation",
            "structure_expression": f"linker: {expression}",
            "attachment_points": "",
            "smiles": "",
        }
    description = LINKER_DESCRIPTION.search(text)
    if description:
        expression = _clean_expression(description.group("description"))
        return {
            "representation_kind": "linker_notation",
            "structure_expression": expression,
            "attachment_points": "",
            "smiles": "",
        }
    if labels:
        return {
            "representation_kind": "attachment_point_notation",
            "structure_expression": f"attachment point(s): {', '.join(labels)}",
            "attachment_points": ",".join(labels),
            "smiles": "",
        }
    if GENERIC_STRUCTURE_MARKERS.search(text):
        return {
            "representation_kind": "structure_description",
            "structure_expression": _clean_expression(text),
            "attachment_points": "",
            "smiles": "",
        }
    return {
        "representation_kind": "none",
        "structure_expression": "",
        "attachment_points": "",
        "smiles": "",
    }


def _canonical(smiles: str) -> str:
    molecule = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(molecule, isomericSmiles=True) if molecule is not None else ""


def _evidence_mentions_index(evidence: Iterable[Mapping[str, str]]) -> dict[tuple[str, str, str], str]:
    index: dict[tuple[str, str, str], str] = {}
    for row in evidence:
        key = (str(row.get("paper_id", "")), str(row.get("page", "")), str(row.get("evidence_text", "")))
        if row.get("compound_mentions"):
            index[key] = str(row["compound_mentions"])
    return index


def build_auto_filled_rows(
    paths: Iterable[Mapping[str, str]],
    evidence: Iterable[Mapping[str, str]],
    reference: Mapping[tuple[str, str], Mapping[str, str]],
) -> list[dict[str, str]]:
    mentions = _evidence_mentions_index(evidence)
    output: list[dict[str, str]] = []
    for path in paths:
        path = {key: str(value or "").strip() for key, value in path.items()}
        need = classify_structure_need(path)
        doi = path.get("doi", "")
        parent_id = path.get("parent_compound", "")
        derived_id = path.get("derived_compound", "")
        parent = reference.get((doi, parent_id), {})
        derived = reference.get((doi, derived_id), {})
        parent_smiles = str(parent.get("smiles", ""))
        derived_smiles = str(derived.get("smiles", ""))
        exact = need == "exact_pair_candidate" and bool(parent_smiles and derived_smiles)
        generic = extract_generic_structure_expression(path.get("evidence_text", ""))
        if exact:
            representation_kind = "exact_si_smiles"
            expression = ""
            attachment_points = ""
            source = "supporting_information_csv"
            source_locator = "; ".join(filter(None, [str(parent.get("source_locator", "")), str(derived.get("source_locator", ""))]))
            status = "text_populated_exact_structure"
        elif need == "generic_r_group_or_linker":
            representation_kind = generic["representation_kind"]
            expression = generic["structure_expression"]
            attachment_points = generic["attachment_points"]
            source = "pdf_text_generic_notation"
            source_locator = f"page={path.get('page', '')}"
            status = "text_populated_generic_structure"
        elif need == "exact_pair_candidate":
            representation_kind = "exact_pair_requires_structure_source"
            expression = ""
            attachment_points = ""
            source = "pdf_text_requires_scheme_or_si"
            source_locator = f"page={path.get('page', '')}"
            status = "text_populated_structure_candidate"
        else:
            representation_kind = "none"
            expression = ""
            attachment_points = ""
            source = ""
            source_locator = ""
            status = "text_populated_no_structure"
        key = (path.get("paper_id", ""), path.get("page", ""), path.get("evidence_text", ""))
        output.append({
            "review_item_id": path.get("path_candidate_id", ""),
            "paper_id": path.get("paper_id", ""),
            "doi": doi,
            "page": path.get("page", ""),
            "page_references": "",
            "parent_compound": parent_id,
            "derived_compound": derived_id,
            "reported_from_group": path.get("reported_from_group", ""),
            "reported_to_group": path.get("reported_to_group", ""),
            "activity": path.get("activity_mentions", ""),
            "evidence_text": path.get("evidence_text", ""),
            "compound_mentions": mentions.get(key, ""),
            "relation_type": path.get("relation_type", ""),
            "path_status": "candidate",
            "structure_review_status": path.get("structure_review_status", ""),
            "structure_confirmation_status": "confirmed_by_si_smiles" if exact else "needs_confirmation",
            "parent_smiles": parent_smiles if exact else "",
            "derived_smiles": derived_smiles if exact else "",
            "parent_canonical_smiles": _canonical(parent_smiles) if exact else "",
            "derived_canonical_smiles": _canonical(derived_smiles) if exact else "",
            "structure_representation_kind": representation_kind,
            "structure_expression": expression,
            "attachment_points": attachment_points,
            "structure_source": source,
            "structure_source_locator": source_locator,
            "auto_fill_status": status,
            "auto_fill_source": "07_enriched_text_paths/all_path_candidates_enriched.csv",
            "source_path_candidate_id": path.get("path_candidate_id", ""),
            "review_status": "unreviewed",
        })
    return output


def build_progress_rows(
    manifest: Iterable[Mapping[str, str]], filled: Iterable[Mapping[str, str]]
) -> list[dict[str, object]]:
    by_paper: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in filled:
        by_paper[str(row.get("paper_id", ""))].append(row)
    progress: list[dict[str, object]] = []
    for paper in manifest:
        paper_id = str(paper.get("paper_id", ""))
        rows = by_paper.get(paper_id, [])
        exact = sum(row.get("structure_representation_kind") == "exact_si_smiles" for row in rows)
        generic = sum(row.get("auto_fill_status") == "text_populated_generic_structure" for row in rows)
        candidates = sum(row.get("structure_representation_kind") != "none" for row in rows)
        if not rows:
            status = "no_modification_records"
        elif exact == len(rows):
            status = "auto_filled_with_exact_structures"
        else:
            status = "auto_filled_structure_review_required"
        progress.append({
            "paper_id": paper_id,
            "auto_fill_status": status,
            "auto_filled_entries": len(rows),
            "structure_candidate_entries": candidates,
            "exact_structure_entries": exact,
            "generic_structure_entries": generic,
            "statement_only_entries": len(rows) - candidates,
        })
    return progress


def build_structure_review_queue(paths: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """Create a resumable queue for page-level Scheme/Table structure review."""
    queue: list[dict[str, str]] = []
    for path in paths:
        text = str(path.get("evidence_text", ""))
        need = classify_structure_need(path)
        has_table_or_scheme = bool(re.search(r"\b(?:table|scheme)\b", text, re.IGNORECASE))
        has_figure = bool(re.search(r"\bfigure\b|\bfig\.\b", text, re.IGNORECASE))
        queue.append({
            "review_item_id": str(path.get("path_candidate_id", "")),
            "paper_id": str(path.get("paper_id", "")),
            "doi": str(path.get("doi", "")),
            "source_pdf": str(path.get("source_pdf", "")),
            "page": str(path.get("page", "")),
            "parent_compound": str(path.get("parent_compound", "")),
            "derived_compound": str(path.get("derived_compound", "")),
            "reported_from_group": str(path.get("reported_from_group", "")),
            "reported_to_group": str(path.get("reported_to_group", "")),
            "relation_type": str(path.get("relation_type", "")),
            "evidence_text": text,
            "structure_need": need,
            "page_has_table_or_scheme_signal": "1" if has_table_or_scheme else "0",
            "page_has_figure_signal": "1" if has_figure else "0",
            "pdf_exists": "1" if Path(str(path.get("source_pdf", ""))).is_file() else "0",
            "structure_review_queue_status": (
                "queued_generic_notation" if need == "generic_r_group_or_linker"
                else "queued_exact_pair" if need == "exact_pair_candidate"
                else "queued_statement_only"
            ),
        })
    return queue


def build_outputs(
    *, paths_path: Path = PATHS_PATH, evidence_path: Path = EVIDENCE_PATH,
    manifest_path: Path = MANIFEST_PATH, reference_path: Path = REFERENCE_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, object]:
    paths = read_csv(paths_path)
    evidence = read_csv(evidence_path)
    manifest = read_csv(manifest_path)
    reference = load_reference(read_csv(reference_path))
    filled = build_auto_filled_rows(paths, evidence, reference)
    progress = build_progress_rows(manifest, filled)
    structure_queue = build_structure_review_queue(paths)
    atomic_write_csv(output_dir / "auto_filled_review_items.csv", filled, AUTO_FIELDS)
    atomic_write_csv(output_dir / "paper_processing_progress.csv", progress, PROGRESS_FIELDS)
    atomic_write_csv(output_dir / "structure_review_queue.csv", structure_queue, STRUCTURE_QUEUE_FIELDS)
    counts = Counter(row["auto_fill_status"] for row in filled)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_papers": len(manifest),
        "input_path_rows": len(paths),
        "auto_filled_rows": len(filled),
        "papers_with_rows": sum(bool(row["auto_filled_entries"]) for row in progress),
        "papers_without_modification_records": sum(row["auto_fill_status"] == "no_modification_records" for row in progress),
        "auto_fill_status_counts": dict(counts),
        "exact_structure_rows": sum(row["structure_representation_kind"] == "exact_si_smiles" for row in filled),
        "generic_structure_rows": sum(row["auto_fill_status"] == "text_populated_generic_structure" for row in filled),
        "structure_review_required_rows": sum(row["structure_representation_kind"] != "exact_si_smiles" for row in filled),
        "structure_review_queue_rows": len(structure_queue),
        "source_paths": {
            "paths": str(paths_path.resolve()), "evidence": str(evidence_path.resolve()),
            "manifest": str(manifest_path.resolve()), "reference": str(reference_path.resolve()),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "auto_fill_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    summary = build_outputs(output_dir=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
