#!/usr/bin/env python3
"""Prepare a deduplicated, visual-reviewable queue for modification paths."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parent.parent
BASE_PATH_CSV = ROOT / "04_path_candidates" / "full_modification_path_candidates.csv"
ENRICHED_PATH_CSV = ROOT / "07_enriched_text_paths" / "all_path_candidates_enriched.csv"
EVIDENCE_CSV = ROOT / "03_sar_candidates" / "full_evidence_candidates.csv"
INDEX_CSV = ROOT / "02_text_extraction" / "full_document_text_index.csv"
VISUAL_DIR = ROOT / "05_visual_review"
CONFIRMED_DIR = ROOT / "06_text_confirmed_paths"
REVIEW_DIR = ROOT / "04_review"
REFERENCE_RE = re.compile(r"\b(?:Scheme|Figure|Table)\s+(?:S)?\d+[A-Za-z]?\b", re.IGNORECASE)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def route_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row["doi"].lower(),
        row["parent_compound"],
        row["derived_compound"],
        row["reported_from_group"].lower(),
        row["reported_to_group"].lower(),
    )


def page_context(pdf_path: str, page_number: int) -> tuple[str, int, int]:
    document = fitz.open(pdf_path)
    page = document[page_number - 1]
    text = page.get_text("text")
    references = " | ".join(sorted(set(match.group(0) for match in REFERENCE_RE.finditer(text))))
    image_count = len(page.get_images(full=True))
    drawing_count = len(page.get_drawings())
    document.close()
    return references, image_count, drawing_count


def render_page(pdf_path: str, page_number: int, output_path: Path) -> None:
    document = fitz.open(pdf_path)
    page = document[page_number - 1]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    pixmap.save(output_path)
    document.close()


def priority(row: dict[str, str], compound_mentions: str) -> tuple[int, str]:
    score = 0
    if row["activity_mentions"]:
        score += 3
    if compound_mentions:
        score += 2
    if REFERENCE_RE.search(row["evidence_text"]):
        score += 2
    if re.search(r"\b(?:replacement|replaced|substitution|introduced|bioisoster)\b", row["evidence_text"], re.IGNORECASE):
        score += 2
    return score, "high" if score >= 5 else "medium" if score >= 3 else "normal"


def main() -> int:
    for folder in (VISUAL_DIR, CONFIRMED_DIR, REVIEW_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    render_dir = VISUAL_DIR / "explicit_path_pages"
    render_dir.mkdir(parents=True, exist_ok=True)

    path_source = ENRICHED_PATH_CSV if ENRICHED_PATH_CSV.exists() else BASE_PATH_CSV
    paths = read_csv(path_source)
    evidence = read_csv(EVIDENCE_CSV)
    index = read_csv(INDEX_CSV)
    title_by_paper = {row["paper_id"]: row["title_guess"] for row in index}
    evidence_compounds = {
        (row["paper_id"], row["page"], row["evidence_text"]): row["compound_mentions"]
        for row in evidence
    }

    explicit = [
        row
        for row in paths
        if row["relation_type"].startswith("explicit_directed")
        or row["relation_type"] == "inferred_directed_text_path"
    ]
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in explicit:
        grouped[route_key(row)].append(row)

    confirmed_rows: list[dict[str, object]] = []
    visual_rows: list[dict[str, object]] = []
    for number, duplicates in enumerate(grouped.values(), start=1):
        canonical = duplicates[0]
        visual_id = f"VIS-{number:04d}"
        image_name = f"{visual_id}_{canonical['path_candidate_id']}_page-{canonical['page']}.png"
        image_path = render_dir / image_name
        references, image_count, drawing_count = page_context(canonical["source_pdf"], int(canonical["page"]))
        render_page(canonical["source_pdf"], int(canonical["page"]), image_path)
        all_ids = " | ".join(item["path_candidate_id"] for item in duplicates)
        all_sources = " | ".join(sorted(set(item["source_pdf"] for item in duplicates)))
        base_row = {
            "visual_review_id": visual_id,
            "canonical_path_candidate_id": canonical["path_candidate_id"],
            "duplicate_path_candidate_ids": all_ids,
            "duplicate_count": len(duplicates),
            "paper_id": canonical["paper_id"],
            "title_guess": title_by_paper.get(canonical["paper_id"], ""),
            "doi": canonical["doi"],
            "source_pdf": canonical["source_pdf"],
            "all_source_pdfs": all_sources,
            "page": canonical["page"],
            "parent_compound": canonical["parent_compound"],
            "derived_compound": canonical["derived_compound"],
            "reported_from_group": canonical["reported_from_group"],
            "reported_to_group": canonical["reported_to_group"],
            "reported_activity_mentions": canonical["activity_mentions"],
            "evidence_text": canonical["evidence_text"],
            "page_references": references,
            "page_embedded_image_count": image_count,
            "page_vector_drawing_count": drawing_count,
            "rendered_page_png": str(image_path.resolve()),
            "structure_review_status": "ready_for_visual_review",
            "review_status": "unreviewed",
        }
        visual_rows.append(base_row)
        confirmed_rows.append(
            {
                **base_row,
                "path_status": "text_confirmed_structure_pending",
                "structure_smiles_parent": "",
                "structure_smiles_derived": "",
                "atom_level_change": "",
                "structure_confirmation_note": "Text establishes a directed modification; inspect the rendered page and cited Scheme/table before recording exact structures.",
            }
        )

    unresolved_rows: list[dict[str, object]] = []
    unresolved = [row for row in paths if row["relation_type"] == "series_or_structure_review_required"]
    for row in unresolved:
        compounds = evidence_compounds.get((row["paper_id"], row["page"], row["evidence_text"]), "")
        score, level = priority(row, compounds)
        unresolved_rows.append(
            {
                "path_candidate_id": row["path_candidate_id"],
                "paper_id": row["paper_id"],
                "title_guess": title_by_paper.get(row["paper_id"], ""),
                "doi": row["doi"],
                "source_pdf": row["source_pdf"],
                "page": row["page"],
                "compound_mentions": compounds,
                "activity_mentions": row["activity_mentions"],
                "priority_score": score,
                "priority": level,
                "evidence_text": row["evidence_text"],
                "review_status": "unreviewed",
            }
        )
    unresolved_rows.sort(key=lambda item: (-int(item["priority_score"]), item["doi"], int(item["page"])))

    visual_fields = [
        "visual_review_id", "canonical_path_candidate_id", "duplicate_path_candidate_ids", "duplicate_count",
        "paper_id", "title_guess", "doi", "source_pdf", "all_source_pdfs", "page",
        "parent_compound", "derived_compound", "reported_from_group", "reported_to_group",
        "reported_activity_mentions", "evidence_text", "page_references", "page_embedded_image_count",
        "page_vector_drawing_count", "rendered_page_png", "structure_review_status", "review_status",
    ]
    write_csv(VISUAL_DIR / "explicit_path_visual_review_queue.csv", visual_rows, visual_fields)
    write_csv(
        CONFIRMED_DIR / "explicit_text_confirmed_paths.csv",
        confirmed_rows,
        visual_fields + ["path_status", "structure_smiles_parent", "structure_smiles_derived", "atom_level_change", "structure_confirmation_note"],
    )
    write_csv(
        VISUAL_DIR / "unresolved_path_review_queue.csv",
        unresolved_rows,
        ["path_candidate_id", "paper_id", "title_guess", "doi", "source_pdf", "page", "compound_mentions", "activity_mentions", "priority_score", "priority", "evidence_text", "review_status"],
    )

    report = {
        "explicit_directed_rows_before_deduplication": len(explicit),
        "path_source": str(path_source.resolve()),
        "unique_explicit_directed_paths": len(visual_rows),
        "duplicate_rows_removed": len(explicit) - len(visual_rows),
        "rendered_visual_review_pages": len(visual_rows),
        "unresolved_paths_queued": len(unresolved_rows),
        "high_priority_unresolved_paths": sum(row["priority"] == "high" for row in unresolved_rows),
        "medium_priority_unresolved_paths": sum(row["priority"] == "medium" for row in unresolved_rows),
    }
    (REVIEW_DIR / "structure_review_preparation_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
