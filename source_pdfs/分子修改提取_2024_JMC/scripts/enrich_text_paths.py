#!/usr/bin/env python3
"""Recover additional directed paths from conservative medicinal-chemistry prose patterns."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "04_path_candidates" / "full_modification_path_candidates.csv"
OUTPUT_DIR = ROOT / "07_enriched_text_paths"
REVIEW_DIR = ROOT / "04_review"
COMPOUND = r"(?:\d+[a-z]{0,3}|[A-Z]{1,5}-?\d+[A-Za-z0-9-]*)"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "replacement_on_parent_leads_to_child",
        re.compile(
            rf"\breplacement\s+of\s+(?P<old>.+?)\s+(?:on|of)\s+.+?\b(?:of\s+)?(?P<parent>{COMPOUND})\s+"
            rf"(?:with|by)\s+(?P<new>.+?)(?:\s+was\s+|,\s*|;\s*).{{0,180}}?\b(?:leading\s+to|yielding|resulting\s+in)\s+"
            rf"(?:the\s+)?(?:compound|analogue|inhibitor|derivative)\s+(?P<child>{COMPOUND})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "when_replaced_resulting_child_relative_parent",
        re.compile(
            rf"\bwhen\s+(?P<old>.+?)\s+(?:on|in)\s+.+?\s+is\s+replaced\s+with\s+(?P<new>.+?),\s+"
            rf"(?:the\s+)?resulting\s+(?:analogue|compound|inhibitor|derivative)\s+(?P<child>{COMPOUND}).{{0,220}}?"
            rf"\b(?:relative\s+to|compared\s+to)\s+(?:compound|analogue|inhibitor|derivative)\s+(?P<parent>{COMPOUND})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "substitution_on_parent_led_to_child",
        re.compile(
            rf"\b(?P<new>[A-Za-z0-9'′-]+\s+substitution)\s+(?:on|in)\s+.+?\b(?:in|of)\s+(?P<parent>{COMPOUND})\s+"
            rf"led\s+to\s+(?:the\s+discovery\s+of\s+)?(?:compound|analogue|inhibitor|derivative)\s+(?P<child>{COMPOUND})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "introduced_to_child_compared_parent",
        re.compile(
            rf"\b(?P<new>.+?)\s+was\s+introduced\s+to\s+.+?\s+of\s+(?:compound\s+)?(?P<child>{COMPOUND}),"
            rf".{{0,220}}?\bcompared\s+to\s+(?:compound\s+)?(?P<parent>{COMPOUND})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "optimized_parent_yielding_child",
        re.compile(
            rf"\b(?:improvement|optimization)\s+of\s+.+?(?:derivative|compound|analogue)\s+(?P<parent>{COMPOUND})\b"
            rf".{{0,220}}?\b(?:yielding|led\s+to)\s+(?:the\s+)?(?:compound|analogue|inhibitor|derivative)\s+(?P<child>{COMPOUND})\b",
            re.IGNORECASE,
        ),
    ),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def clean(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" ,;:")
    return re.sub(r"^although\s+", "", normalized, flags=re.IGNORECASE)


def key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row["doi"].lower(),
        row["parent_compound"],
        row["derived_compound"],
        row["reported_from_group"].lower(),
        row["reported_to_group"].lower(),
    )


def main() -> int:
    original = read_csv(SOURCE)
    existing = {key(row) for row in original if row["parent_compound"] and row["derived_compound"]}
    additions: list[dict[str, object]] = []
    seen = set(existing)

    for row in original:
        if row["relation_type"] != "series_or_structure_review_required":
            continue
        text = row["evidence_text"]
        for rule_name, pattern in PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            groups = match.groupdict()
            parent, child = groups["parent"], groups["child"]
            from_group = clean(groups.get("old", ""))
            to_group = clean(groups.get("new", ""))
            candidate_key = (row["doi"].lower(), parent, child, from_group.lower(), to_group.lower())
            if candidate_key in seen:
                break
            seen.add(candidate_key)
            additions.append(
                {
                    "path_candidate_id": f"INF-{len(additions) + 1:06d}",
                    "source_path_candidate_id": row["path_candidate_id"],
                    "paper_id": row["paper_id"],
                    "doi": row["doi"],
                    "source_pdf": row["source_pdf"],
                    "page": row["page"],
                    "parent_compound": parent,
                    "derived_compound": child,
                    "reported_from_group": from_group,
                    "reported_to_group": to_group,
                    "relation_type": "inferred_directed_text_path",
                    "confidence": "conservative_prose_pattern_requires_structure_review",
                    "extraction_rule": rule_name,
                    "activity_mentions": row["activity_mentions"],
                    "evidence_text": text,
                    "structure_review_status": "needs_scheme_or_table_review",
                    "review_status": "unreviewed",
                }
            )
            break

    standard_fields = [
        "path_candidate_id", "paper_id", "doi", "source_pdf", "page", "parent_compound", "derived_compound",
        "reported_from_group", "reported_to_group", "relation_type", "confidence", "activity_mentions",
        "evidence_text", "structure_review_status", "review_status",
    ]
    merged = original + [
        {
            "path_candidate_id": row["path_candidate_id"],
            "paper_id": row["paper_id"],
            "doi": row["doi"],
            "source_pdf": row["source_pdf"],
            "page": row["page"],
            "parent_compound": row["parent_compound"],
            "derived_compound": row["derived_compound"],
            "reported_from_group": row["reported_from_group"],
            "reported_to_group": row["reported_to_group"],
            "relation_type": row["relation_type"],
            "confidence": row["confidence"],
            "activity_mentions": row["activity_mentions"],
            "evidence_text": row["evidence_text"],
            "structure_review_status": row["structure_review_status"],
            "review_status": row["review_status"],
        }
        for row in additions
    ]
    addition_fields = [
        "path_candidate_id", "source_path_candidate_id", "paper_id", "doi", "source_pdf", "page", "parent_compound",
        "derived_compound", "reported_from_group", "reported_to_group", "relation_type", "confidence",
        "extraction_rule", "activity_mentions", "evidence_text", "structure_review_status", "review_status",
    ]
    write_csv(OUTPUT_DIR / "inferred_directed_path_additions.csv", additions, addition_fields)
    write_csv(OUTPUT_DIR / "all_path_candidates_enriched.csv", merged, standard_fields)
    summary = {
        "original_path_candidates": len(original),
        "inferred_directed_additions": len(additions),
        "enriched_path_candidates": len(merged),
        "additions_by_rule": dict(Counter(row["extraction_rule"] for row in additions)),
    }
    (REVIEW_DIR / "enriched_text_path_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
