#!/usr/bin/env python3
"""Extract all text-evidenced molecular-modification paths from the JMC corpus.

The generated path table is comprehensive for modification statements found in
the PDF text layer. It is intentionally conservative about graph direction and
chemical structure: only an explicit compound pair in a sentence becomes a
directed candidate edge. Every remaining statement is retained for Scheme or
table review instead of being silently dropped.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import run_pilot as base


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

OUTPUT_ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = OUTPUT_ROOT / "02_text_extraction"
EVIDENCE_DIR = OUTPUT_ROOT / "03_sar_candidates"
PATH_DIR = OUTPUT_ROOT / "04_path_candidates"
REVIEW_DIR = OUTPUT_ROOT / "04_review"

COMPOUND = r"(?:\d+[a-z]{0,3}|[A-Z]{1,5}-?\d+[A-Za-z0-9-]*)"
DIRECTED_PARENT_CHILD = re.compile(
    rf"\b[Cc]ompound\s+(?P<child>{COMPOUND})\b(?:(?![.!?]).){{0,200}}?"
    rf"\b(?:diverges?|derives?|derived|modified|obtained)\b(?:(?![.!?]).){{0,120}}?"
    rf"\bparent\s+compound\s+(?P<parent>{COMPOUND})\b",
    re.IGNORECASE,
)
PARENT_REFERENCE = re.compile(
    rf"\b[Cc]ompound\s+(?P<child>{COMPOUND})\b(?:(?![.!?]).){{0,240}}?"
    rf"\bparent\s+compound\s+(?P<parent>{COMPOUND})\b",
    re.IGNORECASE,
)
PAREN_REPLACEMENT = re.compile(
    rf"\breplacement\s+of\s+(?P<old>.+?)\s+\((?P<parent>{COMPOUND})\)\s+"
    rf"(?:with|by)\s+(?P<new>.+?)\s+\((?P<child>{COMPOUND})\)",
    re.IGNORECASE,
)
LABEL_REPLACEMENT = re.compile(
    rf"\breplacement\s+of\s+(?P<old>.+?)\s+(?:of|on|in)\s+"
    rf"(?P<parent>{COMPOUND})\s+(?:with|by)\s+(?P<tail>[^.!?]+)",
    re.IGNORECASE,
)
LABEL_CHANGE = re.compile(
    rf"\bchange\s+of\s+(?P<old>.+?)\s+\((?P<parent>{COMPOUND})\)\s+"
    rf"to\s+(?P<tail>[^.!?]+)",
    re.IGNORECASE,
)
LABEL_CHANGED = re.compile(
    rf"\b(?P<old>.+?)\s+\((?P<parent>{COMPOUND})\)\s+was\s+"
    rf"changed\s+to\s+(?P<tail>[^.!?]+)",
    re.IGNORECASE,
)
COMPARATIVE_RESULT = re.compile(
    rf"\b(?:resulted\s+in|led\s+to|afforded|gave)\s+"
    rf"(?:the\s+)?(?:compound\s+)?(?P<child>{COMPOUND})\b"
    rf"(?:(?![.!?]).){{0,180}}?\bcompared\s+to\s+"
    rf"(?:compound\s+)?(?P<parent>{COMPOUND})\b",
    re.IGNORECASE,
)
OF_AS_IN = re.compile(
    rf"\breplacement\s+of\s+(?P<old>.+?)\s+of\s+(?P<parent>{COMPOUND})\s+by\s+(?P<tail>.+)",
    re.IGNORECASE,
)
AS_IN_CHILD = re.compile(
    rf"(?P<new>.+?)\s+as\s+in\s+(?P<child>{COMPOUND})(?=\s+or\s+|\s*,|\s+and\s+|\s+decreased|\s+increased|\s+led|\.|$)",
    re.IGNORECASE,
)
COMPARISON = re.compile(
    rf"\bcomparison\s+of\s+(?P<first>{COMPOUND})\s+and\s+(?P<second>{COMPOUND})\b",
    re.IGNORECASE,
)


def clean(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" ,;:")
    return re.sub(r"^(?:or|and)\s+", "", normalized, flags=re.IGNORECASE)


def _labelled_products(tail: str) -> list[tuple[str, str]]:
    """Return distinct descriptive product fragments and their labels."""
    products: list[tuple[str, str]] = []
    chunks = re.split(r"\s*(?:,|\bor\b|\band\b)\s*", tail, flags=re.IGNORECASE)
    for chunk in chunks:
        match = re.search(rf"\(\s*(?P<label>{COMPOUND})\s*\)", chunk)
        if not match:
            continue
        label = match.group("label")
        description = clean(chunk[:match.start()])
        item = (description, label)
        if item not in products:
            products.append(item)
    return products


def _multi_label_replacement_paths(
    row: dict[str, object], sequence: int, match: re.Match[str],
) -> list[dict[str, object]]:
    parent = match.group("parent")
    products = _labelled_products(match.group("tail"))
    return [
        one_path(
            row,
            sequence * 100 + index,
            parent,
            child,
            clean(match.group("old")),
            description,
            "explicit_directed_replacement",
            "explicit_text_pair",
        )
        for index, (description, child) in enumerate(products, start=1)
    ]


def one_path(
    row: dict[str, object],
    sequence: int,
    parent: str = "",
    child: str = "",
    old: str = "",
    new: str = "",
    relation: str = "series_or_structure_review_required",
    confidence: str = "text_evidence_only",
) -> dict[str, object]:
    return {
        "path_candidate_id": f"PATH-{sequence:07d}",
        "paper_id": row["paper_id"],
        "doi": row["doi"],
        "source_pdf": row["source_pdf"],
        "page": row["page"],
        "parent_compound": parent,
        "derived_compound": child,
        "reported_from_group": old,
        "reported_to_group": new,
        "relation_type": relation,
        "confidence": confidence,
        "activity_mentions": row["activity_mentions"],
        "evidence_text": row["evidence_text"],
        "structure_review_status": "needs_scheme_or_table_review",
        "review_status": "unreviewed",
    }


def paths_from_evidence(row: dict[str, object], sequence: int) -> list[dict[str, object]]:
    """Return one or more paths, preserving the source text on every row."""
    text = str(row["evidence_text"])
    parent_child = DIRECTED_PARENT_CHILD.search(text)
    if parent_child:
        return [
            one_path(
                row,
                sequence,
                parent_child["parent"],
                parent_child["child"],
                relation="explicit_directed_parent_child",
                confidence="explicit_text_pair",
            )
        ]

    parenthetical = PAREN_REPLACEMENT.search(text)
    if parenthetical:
        return [
            one_path(
                row,
                sequence,
                parenthetical["parent"],
                parenthetical["child"],
                clean(parenthetical["old"]),
                clean(parenthetical["new"]),
                "explicit_directed_replacement",
                "explicit_text_pair",
            )
        ]

    for pattern in (LABEL_REPLACEMENT, LABEL_CHANGE, LABEL_CHANGED):
        labelled = pattern.search(text)
        if not labelled:
            continue
        paths = _multi_label_replacement_paths(row, sequence, labelled)
        if paths:
            return paths

    comparative_result = COMPARATIVE_RESULT.search(text)
    if comparative_result:
        return [
            one_path(
                row,
                sequence,
                comparative_result["parent"],
                comparative_result["child"],
                relation="explicit_directed_comparison",
                confidence="explicit_text_pair",
            )
        ]

    as_in = OF_AS_IN.search(text)
    if as_in:
        pairs = list(AS_IN_CHILD.finditer(as_in["tail"]))
        if pairs:
            return [
                one_path(
                    row,
                    sequence * 100 + index,
                    as_in["parent"],
                    match["child"],
                    clean(as_in["old"]),
                    clean(match["new"]),
                    "explicit_directed_replacement",
                    "explicit_text_pair",
                )
                for index, match in enumerate(pairs, start=1)
            ]

    comparison = COMPARISON.search(text)
    if comparison:
        return [
            one_path(
                row,
                sequence,
                comparison["first"],
                comparison["second"],
                relation="explicit_unordered_comparison",
                confidence="comparison_requires_direction_review",
            )
        ]
    parent_reference = PARENT_REFERENCE.search(text)
    if parent_reference:
        return [
            one_path(
                row,
                sequence,
                parent_reference["parent"],
                parent_reference["child"],
                relation="parent_reference_requires_structure_review",
                confidence="parent_reference_not_a_confirmed_edge",
            )
        ]
    return [one_path(row, sequence)]


def main() -> int:
    for folder in (TEXT_DIR, EVIDENCE_DIR, PATH_DIR, REVIEW_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    manifest = base.build_manifest(base.source_files())
    text_records: list[dict[str, object]] = []
    evidence_rows: list[dict[str, object]] = []
    page_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for index, record in enumerate(manifest, start=1):
        if index == 1 or index % 25 == 0 or index == len(manifest):
            print(f"[{index}/{len(manifest)}] {record['filename']}", flush=True)
        try:
            text_record, evidence, pages = base.candidate_rows(record)
            for row in evidence:
                row["doi"] = text_record["doi"]
            text_records.append(text_record)
            evidence_rows.extend(evidence)
            page_rows.extend(pages)
        except Exception as exc:
            failures.append({**record, "error": repr(exc)})

    paths: list[dict[str, object]] = []
    for sequence, row in enumerate(
        (item for item in evidence_rows if item["evidence_type"] == "modification_statement"),
        start=1,
    ):
        paths.extend(paths_from_evidence(row, sequence))

    base.write_csv(
        TEXT_DIR / "full_document_text_index.csv",
        text_records,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes", "page_count", "text_characters", "doi", "text_status"],
    )
    base.write_csv(
        TEXT_DIR / "full_page_coverage.csv",
        page_rows,
        ["paper_id", "page", "text_characters", "has_modification_keyword", "has_activity_value"],
    )
    base.write_csv(
        EVIDENCE_DIR / "full_evidence_candidates.csv",
        evidence_rows,
        ["paper_id", "doi", "source_pdf", "page", "evidence_type", "compound_mentions", "activity_mentions", "evidence_text", "review_status", "confidence"],
    )
    base.write_csv(
        PATH_DIR / "full_modification_path_candidates.csv",
        paths,
        ["path_candidate_id", "paper_id", "doi", "source_pdf", "page", "parent_compound", "derived_compound", "reported_from_group", "reported_to_group", "relation_type", "confidence", "activity_mentions", "evidence_text", "structure_review_status", "review_status"],
    )
    base.write_csv(
        REVIEW_DIR / "full_failures.csv",
        failures,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes", "error"],
    )

    relation_counts = Counter(row["relation_type"] for row in paths)
    evidence_counts = Counter(row["evidence_type"] for row in evidence_rows)
    report = f"""# Full-Corpus Modification-Path Extraction

## Completed Scope

- Corpus manifest: {len(manifest)} J. Med. Chem. Volume 67 PDFs (Issue 1-22).
- PDFs processed: {len(text_records)}
- PDF failures: {len(failures)}
- Total pages processed: {sum(int(row['page_count']) for row in text_records)}
- PDFs with usable text layer: {sum(row['text_status'] == 'ok' for row in text_records)} / {len(text_records)}

## Evidence And Paths

- All candidate evidence rows: {len(evidence_rows)}
- Modification statements retained: {evidence_counts['modification_statement']}
- Activity statements retained: {evidence_counts['compound_activity_statement']}
- Modification-path candidate rows: {len(paths)}
- Explicit directed paths: {relation_counts['explicit_directed_parent_child'] + relation_counts['explicit_directed_replacement']}
- Explicit unordered comparisons: {relation_counts['explicit_unordered_comparison']}
- Parent-compound references requiring structure review: {relation_counts['parent_reference_requires_structure_review']}
- Paths requiring Scheme/table review: {relation_counts['series_or_structure_review_required']}

## Interpretation

The path table preserves every text-layer modification statement. A nonempty
`parent_compound` and `derived_compound` means the article sentence itself
identified a compound pair; blank pair fields mean the evidence refers to a
series, substituent pattern, or scaffold change that must be resolved from a
Scheme or table. `structure_review_status` remains deliberately unresolved for
every automatically extracted row.

## Next Review Queue

Prioritize rows with `relation_type` equal to `explicit_directed_parent_child`
or `explicit_directed_replacement`, then use each row's PDF and page reference
to confirm atom-level structure differences. Supporting Information remains
necessary for a complete synthetic-reaction route, reagents, and yields.
"""
    (REVIEW_DIR / "full_path_extraction_report.md").write_text(report, encoding="utf-8")
    summary = {
        "corpus_pdfs": len(manifest),
        "processed_pdfs": len(text_records),
        "failures": len(failures),
        "evidence_rows": len(evidence_rows),
        "evidence_types": dict(evidence_counts),
        "path_candidates": len(paths),
        "path_relation_types": dict(relation_counts),
    }
    (REVIEW_DIR / "full_path_extraction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
