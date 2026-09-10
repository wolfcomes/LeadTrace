#!/usr/bin/env python3
"""Build a fragment-aware structure review snapshot for the first 20 Papers.

The source PDF, OCR proposal, and text snapshots are read-only. This derived
view deliberately keeps a proposal's visual scope separate from RDKit syntax:
an invalid whole-molecule proposal is not the same problem as a valid SMILES
that came from a fragment, chart, or mixed crop.
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "01_manifest" / "all_volume67_papers.csv"
PROPOSALS_PATH = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "structure_ocr_proposals.csv"
AUTO_FILL_PATH = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "auto_filled_review_items.csv"
OUTPUT_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
OUTPUT_PATH = OUTPUT_DIR / "first_page_fragment_review.csv"
SUMMARY_PATH = OUTPUT_DIR / "first_page_fragment_review_summary.json"
FIRST_PAGE_SIZE = 20
MISSING = "--"
ANNOTATION_VERSION = "first_page_visual_annotation_v1_2026-09-04"

OUTPUT_FIELDS = (
    "paper_rank", "paper_id", "title_guess", "source_folder", "source_pdf",
    "candidate_id", "page_candidate_id", "page", "region_kind", "crop_path",
    "x0", "y0", "x1", "y1", "source_queue_item_ids", "compound_ids",
    "visual_scope", "visual_scope_label", "visual_basis", "fragment_role",
    "visible_notation", "attachment_points", "linked_review_item_ids",
    "linked_entry_count", "text_evidence", "parent_compounds", "derived_compounds",
    "reported_changes", "inference_steps", "image_localization_status",
    "fragment_recognition_status", "attachment_reasoning_status",
    "whole_molecule_smiles_status", "fragment_smiles_status", "raw_smiles",
    "canonical_smiles", "rdkit_status", "proposal_quality", "smiles_accuracy_state",
    "review_status",
    "model_version", "human_review_status", "annotation_version",
)

_R_NOTATION = re.compile(r"\bR\d*\b", re.IGNORECASE)
_LINKER_NOTATION = re.compile(r"\blink(?:er|ers|ed|ing)?\b", re.IGNORECASE)
_CHANGE_FIELDS = ("reported_from_group", "reported_to_group", "relation_type")

# These annotations were made by inspecting the 31 crops belonging to the
# first manifest page. They are a review-layer input, not a claim that OCR is
# chemically correct.
FIRST_PAGE_VISUAL_ANNOTATIONS: dict[str, dict[str, str]] = {
    "PAGE-0f8ace81cef4-CAND-001": {"scope": "non_structure_region", "basis": "3D protein-ligand binding scene; no isolated 2D molecule", "notation": "--"},
    "PAGE-13d2c22c5af1-CAND-001": {"scope": "non_structure_region", "basis": "text and annotation box", "notation": "--"},
    "PAGE-13d2c22c5af1-CAND-002": {"scope": "non_structure_region", "basis": "text and highlighted design label", "notation": "--"},
    "PAGE-13d2c22c5af1-CAND-003": {"scope": "non_structure_region", "basis": "arrow and annotation text", "notation": "--"},
    "PAGE-13d2c22c5af1-CAND-004": {"scope": "non_structure_region", "basis": "highlighted annotation text", "notation": "--"},
    "PAGE-621e2220dc85-CAND-001": {"scope": "fragment_or_series", "basis": "reaction Scheme with R1/R2 and Linker a-e", "notation": "R1; R2; Linker a-e"},
    "PAGE-f4f94d8975c8-CAND-001": {"scope": "non_structure_region", "basis": "kinase tree and activity plots", "notation": "--"},
    "PAGE-8b83aebf4c53-CAND-001": {"scope": "non_structure_region", "basis": "binding/activity chart", "notation": "--"},
    "PAGE-8b83aebf4c53-CAND-002": {"scope": "fragment_or_series", "basis": "compound series and R substitution panel", "notation": "R; R1; R2; R3; R4"},
    "PAGE-2389b5da8795-CAND-001": {"scope": "complete_molecule_candidate", "basis": "isolated 2D molecule with atom labels", "notation": "--"},
    "PAGE-884593225a2c-CAND-001": {"scope": "complete_molecule_candidate", "basis": "isolated 2D molecule with formula", "notation": "--"},
    "PAGE-889b08022bee-CAND-001": {"scope": "fragment_or_series", "basis": "molecule with variable site label B", "notation": "B"},
    "PAGE-889b08022bee-CAND-002": {"scope": "mixed_structure_evidence", "basis": "spectrum plus two molecular structures", "notation": "--"},
    "PAGE-889b08022bee-CAND-003": {"scope": "fragment_or_series", "basis": "substitution table with variable B fragments", "notation": "B"},
    "PAGE-d79ad4b6d9ff-CAND-001": {"scope": "complete_molecule_series", "basis": "series of isolated 2D molecules", "notation": "--"},
    "PAGE-d79ad4b6d9ff-CAND-002": {"scope": "complete_molecule_series", "basis": "molecular series in activity table", "notation": "--"},
    "PAGE-d79ad4b6d9ff-CAND-003": {"scope": "complete_molecule_series", "basis": "reference compounds shown as isolated 2D molecules", "notation": "--"},
    "PAGE-b55408efc1c7-CAND-001": {"scope": "non_structure_region", "basis": "protein electron-density scene", "notation": "--"},
    "PAGE-b70cf253ca57-CAND-001": {"scope": "complete_molecule_series", "basis": "activity table containing isolated 2D structures", "notation": "--"},
    "PAGE-0fad03c6457c-CAND-001": {"scope": "non_structure_region", "basis": "protein binding surface and ligand poses", "notation": "--"},
    "PAGE-954f1682ea6d-CAND-001": {"scope": "non_structure_region", "basis": "inhibition bar chart", "notation": "--"},
    "PAGE-b065f179c1dd-CAND-001": {"scope": "non_structure_region", "basis": "selectivity scatter plots", "notation": "--"},
    "PAGE-d867a063e9f9-CAND-001": {"scope": "fragment_or_series", "basis": "series plots with R1/R2/R3/R4 substituent fragments", "notation": "R1; R2; R3; R4"},
    "PAGE-d867a063e9f9-CAND-002": {"scope": "fragment_or_series", "basis": "series plot with R1/R2/R3/R4 substituent fragments", "notation": "R1; R2; R3; R4"},
    "PAGE-3d1249a64e3d-CAND-001": {"scope": "non_structure_region", "basis": "journal cover image", "notation": "--"},
    "PAGE-3d1249a64e3d-CAND-002": {"scope": "mixed_structure_evidence", "basis": "one 2D molecule beside cell images and assay label", "notation": "--"},
    "PAGE-5d639341273b-CAND-001": {"scope": "complete_molecule_series", "basis": "series of isolated 2D molecules with compound labels", "notation": "--"},
    "PAGE-6f29995b606f-CAND-001": {"scope": "fragment_or_series", "basis": "annotated structure with variable sites and linker", "notation": "Site 1; Site 2; Site 3; R1; R2"},
    "PAGE-6f29995b606f-CAND-002": {"scope": "non_structure_region", "basis": "food-intake activity plots", "notation": "--"},
    "PAGE-6f29995b606f-CAND-003": {"scope": "fragment_or_series", "basis": "two structures with highlighted substituent Site 3", "notation": "Site 3"},
    "PAGE-880042186935-CAND-001": {"scope": "fragment_or_series", "basis": "Site 1 structure plus substituent fragment table", "notation": "Site 1"},
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
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
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _value(row: Mapping[str, object], key: str) -> str:
    value = str(row.get(key, "") or "").strip()
    return value or MISSING


def _join_unique(values: Iterable[object], separator: str = " | ") -> str:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text != MISSING and text not in output:
            output.append(text)
    return separator.join(output) or MISSING


def _is_complete_scope(scope: str) -> bool:
    return scope in {"complete_molecule_candidate", "complete_molecule_series"}


def classify_visual_scope(row: Mapping[str, object]) -> str:
    """Return the source-image scope, never a chemical correctness claim."""
    candidate_id = str(row.get("candidate_id", "")).strip()
    annotation = FIRST_PAGE_VISUAL_ANNOTATIONS.get(candidate_id)
    if annotation:
        return annotation["scope"]
    searchable = " ".join(str(row.get(key, "")) for key in ("source_queue_item_ids", "compound_ids", "structure_expression", "evidence_text", "visible_notation"))
    if _R_NOTATION.search(searchable) or _LINKER_NOTATION.search(searchable):
        return "fragment_or_series"
    return "unknown"


def classify_smiles_accuracy(scope: str, rdkit_status: str, proposal_quality: str) -> str:
    if scope == "non_structure_region":
        return "not_applicable_non_structure"
    if scope == "mixed_structure_evidence":
        return "mixed_region_requires_split"
    if scope == "unknown":
        return "visual_scope_requires_review"
    if scope == "fragment_or_series":
        if rdkit_status == "valid" and proposal_quality == "valid_but_suspicious_needs_review":
            return "fragment_syntax_valid_but_suspicious"
        if rdkit_status == "valid":
            return "fragment_syntax_valid_needs_connectivity_review"
        return "fragment_smiles_invalid_needs_review"
    if rdkit_status == "valid":
        return "whole_molecule_syntax_valid_needs_visual_review"
    return "whole_molecule_smiles_invalid_needs_review"


def _annotation(row: Mapping[str, object], auto_rows: list[Mapping[str, object]]) -> dict[str, str]:
    candidate_id = str(row.get("candidate_id", "")).strip()
    known = FIRST_PAGE_VISUAL_ANNOTATIONS.get(candidate_id)
    expressions = [str(item.get("structure_expression", "")) for item in auto_rows]
    points = [str(item.get("attachment_points", "")) for item in auto_rows]
    source_text = " ".join(expressions + points)
    scope = known["scope"] if known else classify_visual_scope({**row, "structure_expression": source_text})
    notation = known["notation"] if known else _join_unique([*points, ", ".join(label.upper() for label in _R_NOTATION.findall(source_text))], separator="; ")
    basis = known["basis"] if known else "automatic scope fallback; visual confirmation required"
    if scope == "non_structure_region":
        role = "non_chemical_structure_region"
    elif scope == "mixed_structure_evidence":
        role = "structure_and_non_structure_mixed"
    elif scope == "fragment_or_series":
        role = "replacement_fragment_or_series"
    else:
        role = "whole_molecule_or_series"
    return {"scope": scope, "notation": notation or MISSING, "basis": basis, "role": role}


def _reasoning_fields(scope: str, rdkit_status: str, proposal_quality: str) -> dict[str, str]:
    accuracy = classify_smiles_accuracy(scope, rdkit_status, proposal_quality)
    if scope == "non_structure_region":
        return {
            "steps": "reject crop as non-2D-structure evidence -> do not evaluate SMILES",
            "localization": "rejected_non_structure_region",
            "fragment": "not_applicable",
            "attachment": "not_applicable",
            "whole": "not_applicable_non_structure",
            "fragment_smiles": "not_evaluated",
        }
    if scope == "mixed_structure_evidence":
        return {
            "steps": "locate molecular subregion -> split from chart/spectrum/image -> rerun OCSR on molecule only",
            "localization": "mixed_region_requires_split",
            "fragment": "mixed_requires_split",
            "attachment": "requires_crop_split",
            "whole": "mixed_region_requires_split",
            "fragment_smiles": "not_evaluated_until_split",
        }
    if scope == "fragment_or_series":
        return {
            "steps": "identify shared scaffold -> preserve R/site/linker notation -> infer local replacement -> validate fragment syntax -> confirm connectivity manually",
            "localization": "structure_region_identified",
            "fragment": "fragment_or_series_identified",
            "attachment": "notation_preserved_requires_connectivity_review",
            "whole": "not_evaluable_fragment_only",
            "fragment_smiles": "syntax_valid_fragment_proposal" if rdkit_status == "valid" else "invalid_fragment_proposal",
        }
    return {
        "steps": "identify isolated 2D molecule/series -> compare compound labels -> validate proposal with RDKit -> visually confirm atom and bond correspondence",
        "localization": "structure_region_identified",
        "fragment": "whole_molecule_candidate",
        "attachment": "not_applicable_complete_candidate",
        "whole": "syntax_valid_only" if rdkit_status == "valid" else "invalid_needs_review",
        "fragment_smiles": "not_evaluated",
    }


def build_first_page_rows(
    manifest: Iterable[Mapping[str, object]],
    proposals: Iterable[Mapping[str, object]],
    auto_fill: Iterable[Mapping[str, object]],
    page_size: int = FIRST_PAGE_SIZE,
) -> list[dict[str, str]]:
    first_page = [dict(row) for row in list(manifest)[:page_size]]
    paper_by_id = {str(row.get("paper_id", "")): (index, row) for index, row in enumerate(first_page, 1)}
    auto_by_item: dict[str, list[Mapping[str, object]]] = {}
    for item in auto_fill:
        item_id = str(item.get("review_item_id", "")).strip()
        if item_id:
            auto_by_item.setdefault(item_id, []).append(item)
    output: list[dict[str, str]] = []
    selected = [dict(row) for row in proposals if str(row.get("paper_id", "")) in paper_by_id]
    selected.sort(key=lambda row: (paper_by_id[str(row.get("paper_id", ""))][0], str(row.get("candidate_id", ""))))
    for proposal in selected:
        paper_id = str(proposal.get("paper_id", ""))
        rank, paper = paper_by_id[paper_id]
        linked_ids = [value.strip() for value in str(proposal.get("source_queue_item_ids", "")).split("|") if value.strip()]
        linked_auto = [item for item_id in linked_ids for item in auto_by_item.get(item_id, [])]
        annotation = _annotation(proposal, linked_auto)
        rdkit_status = str(proposal.get("rdkit_status", "") or "").strip() or MISSING
        proposal_quality = str(proposal.get("proposal_quality", "") or "").strip() or MISSING
        reasoning = _reasoning_fields(annotation["scope"], rdkit_status, proposal_quality)
        evidence = _join_unique(item.get("evidence_text", "") for item in linked_auto)
        parents = _join_unique(item.get("parent_compound", "") for item in linked_auto)
        derived = _join_unique(item.get("derived_compound", "") for item in linked_auto)
        changes = _join_unique(
            " -> ".join(str(item.get(field, "") or "").strip() for field in _CHANGE_FIELDS if str(item.get(field, "") or "").strip())
            for item in linked_auto
        )
        attachment_points = _join_unique(item.get("attachment_points", "") for item in linked_auto)
        if attachment_points == MISSING:
            attachment_points = annotation["notation"]
        output.append({
            "paper_rank": str(rank), "paper_id": paper_id, "title_guess": _value(paper, "title_guess"),
            "source_folder": _value(paper, "source_folder"), "source_pdf": _value(proposal, "source_pdf"),
            "candidate_id": _value(proposal, "candidate_id"), "page_candidate_id": _value(proposal, "page_candidate_id"),
            "page": _value(proposal, "page"), "region_kind": _value(proposal, "region_kind"), "crop_path": _value(proposal, "crop_path"),
            "x0": _value(proposal, "x0"), "y0": _value(proposal, "y0"), "x1": _value(proposal, "x1"), "y1": _value(proposal, "y1"),
            "source_queue_item_ids": _value(proposal, "source_queue_item_ids"), "compound_ids": _value(proposal, "compound_ids"),
            "visual_scope": annotation["scope"], "visual_scope_label": {
                "non_structure_region": "非结构区域", "mixed_structure_evidence": "结构与非结构混合",
                "fragment_or_series": "片段 / 系列结构", "complete_molecule_candidate": "完整分子候选",
                "complete_molecule_series": "完整分子系列", "unknown": "视觉范围未确定",
            }.get(annotation["scope"], "视觉范围未确定"),
            "visual_basis": annotation["basis"], "fragment_role": annotation["role"],
            "visible_notation": annotation["notation"],
            "attachment_points": attachment_points,
            "linked_review_item_ids": _join_unique(linked_ids), "linked_entry_count": str(len(linked_auto)),
            "text_evidence": evidence, "parent_compounds": parents, "derived_compounds": derived, "reported_changes": changes,
            "inference_steps": reasoning["steps"], "image_localization_status": reasoning["localization"],
            "fragment_recognition_status": reasoning["fragment"], "attachment_reasoning_status": reasoning["attachment"],
            "whole_molecule_smiles_status": reasoning["whole"], "fragment_smiles_status": reasoning["fragment_smiles"],
            "raw_smiles": _value(proposal, "raw_smiles"), "canonical_smiles": _value(proposal, "canonical_smiles"),
            "rdkit_status": rdkit_status, "proposal_quality": proposal_quality,
            "smiles_accuracy_state": classify_smiles_accuracy(annotation["scope"], rdkit_status, proposal_quality),
            "review_status": _value(proposal, "review_status"),
            "model_version": _value(proposal, "model_version"),
            "human_review_status": "proposal_only_pending_human_review",
            "annotation_version": ANNOTATION_VERSION,
        })
    return output


def write_first_page_snapshot(
    manifest: Iterable[Mapping[str, object]], proposals: Iterable[Mapping[str, object]], auto_fill: Iterable[Mapping[str, object]],
    output_path: Path = OUTPUT_PATH, summary_path: Path = SUMMARY_PATH, page_size: int = FIRST_PAGE_SIZE,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    manifest_rows = list(manifest)
    proposal_rows = list(proposals)
    auto_rows = list(auto_fill)
    first_page_rows = build_first_page_rows(manifest_rows, proposal_rows, auto_rows, page_size=page_size)
    first_page_ids = {str(row.get("paper_id", "")) for row in manifest_rows[:page_size]}
    selected_paper_ids = {row["paper_id"] for row in first_page_rows}
    rows_by_paper: dict[str, list[dict[str, str]]] = {}
    for row in first_page_rows:
        rows_by_paper.setdefault(row["paper_id"], []).append(row)
    paper_summaries = []
    for rank, paper in enumerate(manifest_rows[:page_size], 1):
        paper_id = str(paper.get("paper_id", ""))
        paper_rows = rows_by_paper.get(paper_id, [])
        scope_counts = Counter(row["visual_scope"] for row in paper_rows)
        paper_summaries.append({
            "paper_rank": rank,
            "paper_id": paper_id,
            "title_guess": str(paper.get("title_guess", "") or MISSING),
            "source_folder": str(paper.get("source_folder", "") or MISSING),
            "candidate_count": len(paper_rows),
            "non_structure_count": scope_counts.get("non_structure_region", 0),
            "fragment_or_series_count": scope_counts.get("fragment_or_series", 0),
            "complete_molecule_count": scope_counts.get("complete_molecule_candidate", 0) + scope_counts.get("complete_molecule_series", 0),
            "mixed_structure_count": scope_counts.get("mixed_structure_evidence", 0),
            "rdkit_valid_count": sum(row["rdkit_status"] == "valid" for row in paper_rows),
            "rdkit_invalid_count": sum(row["rdkit_status"] == "invalid" for row in paper_rows),
            "needs_human_review_count": len(paper_rows),
        })
    summary: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "annotation_version": ANNOTATION_VERSION,
        "first_page_size": page_size, "papers": len(first_page_ids), "papers_with_candidates": len(selected_paper_ids),
        "papers_without_candidates": len(first_page_ids - selected_paper_ids), "candidate_rows": len(first_page_rows),
        "proposal_only_rows": sum(row["human_review_status"] == "proposal_only_pending_human_review" for row in first_page_rows),
        "visual_scope_counts": dict(Counter(row["visual_scope"] for row in first_page_rows)),
        "smiles_accuracy_state_counts": dict(Counter(row["smiles_accuracy_state"] for row in first_page_rows)),
        "rdkit_status_counts": dict(Counter(row["rdkit_status"] for row in first_page_rows)),
        "proposal_quality_counts": dict(Counter(row["proposal_quality"] for row in first_page_rows)),
        "linked_review_items": len({value for row in first_page_rows for value in row["linked_review_item_ids"].split(" | ") if value and value != MISSING}),
        "paper_summaries": paper_summaries,
        "source_paths": {"manifest": str(MANIFEST_PATH.resolve()), "proposals": str(PROPOSALS_PATH.resolve()), "auto_fill": str(AUTO_FILL_PATH.resolve())},
    }
    _atomic_write_csv(output_path, first_page_rows)
    _atomic_write_json(summary_path, summary)
    return first_page_rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--proposals", type=Path, default=PROPOSALS_PATH)
    parser.add_argument("--auto-fill", type=Path, default=AUTO_FILL_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--page-size", type=int, default=FIRST_PAGE_SIZE)
    args = parser.parse_args()
    rows, summary = write_first_page_snapshot(
        read_csv(args.manifest), read_csv(args.proposals), read_csv(args.auto_fill), args.output, args.summary, args.page_size,
    )
    print(json.dumps({**summary, "output": str(args.output.resolve()), "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
