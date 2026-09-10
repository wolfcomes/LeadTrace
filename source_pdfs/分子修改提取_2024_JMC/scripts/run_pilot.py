#!/usr/bin/env python3
"""Build a traceable pilot corpus for J. Med. Chem. Volume 67 PDF articles.

This is deliberately an evidence-extraction pass, not a structure recognizer.
It records the exact page and text supporting each possible medicinal-chemistry
modification statement so later chemistry review can verify it against schemes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise SystemExit("PyMuPDF is required: install the 'pymupdf' Python package.") from exc

if hasattr(sys.stdout, "reconfigure"):
    # A Windows PowerShell console can default to GBK while article filenames
    # contain international author characters.
    sys.stdout.reconfigure(errors="backslashreplace")


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = SCRIPT_DIR.parent
COLLECTION_ROOT = OUTPUT_ROOT.parent
SOURCE_FOLDERS = [
    "case5 volume67 issue1-4",
    "case4 volume67 issue5-9",
    "case2 volume67 issue10-13",
    "case volume67 issue14-18",
    "case3 volume67 issue 19-22",
]
PILOT_PER_FOLDER = 6

DOI_RE = re.compile(r"10\.1021/acs\.jmedchem\.[0-9a-z]+", re.IGNORECASE)
COMPOUND_RE = re.compile(
    r"\b(?:compound|analogue|analog|derivative|lead|candidate)s?\s+"
    r"(?:\(?\s*)?(?:\d+[a-z]{0,3}|[A-Z]{1,5}-?\d+[A-Za-z0-9-]*)(?:\s*\))?",
    re.IGNORECASE,
)
ACTIVITY_RE = re.compile(
    r"\b(?:IC50|EC50|DC50|GI50|K[di]|IC\s*50|EC\s*50|K\s*[di])\b"
    r"[^.\n;]{0,100}?\b\d+(?:\.\d+)?\s*(?:pM|nM|uM|µM|mM)\b",
    re.IGNORECASE,
)
MODIFICATION_RE = re.compile(
    r"\b(?:replaced|replacement|substitut(?:e|ed|ion)|introduc(?:e|ed|tion)|"
    r"install(?:ed|ation)|exchanged|switched|modified|modification|optimized|"
    r"changed|converted|truncated|elongated|rigidified|cycli[sz]ed|bioisoster(?:e|ic))\b",
    re.IGNORECASE,
)
SAR_RE = re.compile(
    r"\b(?:structure[ -]activity|SAR|potency|selectivity|activity|affinity|"
    r"efficacy|pharmacokinetic|permeability|solubility|metabolic stability)\b",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+(?=[A-Z0-9])")


def safe_text(value: str) -> str:
    """Flatten extracted text for single-line CSV evidence records."""
    return re.sub(r"\s+", " ", value).strip()


def title_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^[a-z0-9-]+-et-al-\d{4}-", "", stem, flags=re.IGNORECASE)
    return stem.replace("-", " ").capitalize()


def source_files() -> list[Path]:
    papers: list[Path] = []
    for folder_name in SOURCE_FOLDERS:
        folder = COLLECTION_ROOT / folder_name
        if not folder.is_dir():
            raise FileNotFoundError(f"Expected source folder not found: {folder}")
        papers.extend(sorted(folder.glob("*.pdf"), key=lambda item: item.name.lower()))
    return papers


def paper_id(path: Path) -> str:
    relative = path.relative_to(COLLECTION_ROOT).as_posix()
    return hashlib.sha1(relative.encode("utf-8")).hexdigest()[:12]


def build_manifest(papers: list[Path]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in papers:
        records.append(
            {
                "paper_id": paper_id(path),
                "source_folder": path.parent.name,
                "source_pdf": str(path.resolve()),
                "filename": path.name,
                "filename_year": (re.search(r"-((?:19|20)\d{2})-", path.name) or [""])[1],
                "title_guess": title_from_filename(path),
                "file_size_bytes": str(path.stat().st_size),
            }
        )
    return records


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def select_pilot(manifest: list[dict[str, str]]) -> list[dict[str, str]]:
    # Keep the selection stable and balanced across the five issue ranges.
    return [
        record
        for folder_name in SOURCE_FOLDERS
        for record in [
            item for item in manifest if item["source_folder"] == folder_name
        ][:PILOT_PER_FOLDER]
    ]


def candidate_rows(record: dict[str, str]) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    path = Path(record["source_pdf"])
    document = fitz.open(path)
    page_texts = [page.get_text("text") for page in document]
    full_text = "\n".join(page_texts)
    doi_match = DOI_RE.search(full_text)
    text_record: dict[str, object] = {
        **record,
        "page_count": len(document),
        "text_characters": len(full_text),
        "doi": doi_match.group(0).lower() if doi_match else "",
        "text_status": "ok" if len(full_text.strip()) >= 1000 else "low_text",
    }
    evidence: list[dict[str, object]] = []
    pages: list[dict[str, object]] = []

    for page_number, raw_text in enumerate(page_texts, start=1):
        page_flat = safe_text(raw_text)
        pages.append(
            {
                "paper_id": record["paper_id"],
                "page": page_number,
                "text_characters": len(raw_text),
                "has_modification_keyword": bool(MODIFICATION_RE.search(raw_text)),
                "has_activity_value": bool(ACTIVITY_RE.search(raw_text)),
            }
        )
        for sentence in SENTENCE_SPLIT_RE.split(page_flat):
            sentence = safe_text(sentence)
            if len(sentence) < 40:
                continue
            compounds = COMPOUND_RE.findall(sentence)
            has_modification = bool(MODIFICATION_RE.search(sentence))
            has_activity = bool(ACTIVITY_RE.search(sentence))
            has_sar = bool(SAR_RE.search(sentence))
            if not (has_modification and (compounds or has_sar)) and not (has_activity and compounds):
                continue
            kind = "modification_statement" if has_modification else "compound_activity_statement"
            evidence.append(
                {
                    "paper_id": record["paper_id"],
                    "source_pdf": record["source_pdf"],
                    "page": page_number,
                    "evidence_type": kind,
                    "compound_mentions": " | ".join(sorted(set(safe_text(item) for item in compounds))),
                    "activity_mentions": " | ".join(sorted(set(ACTIVITY_RE.findall(sentence)))),
                    "evidence_text": sentence,
                    "review_status": "unreviewed",
                    "confidence": "candidate_only",
                }
            )
    document.close()
    return text_record, evidence, pages


def main() -> int:
    manifest_dir = OUTPUT_ROOT / "01_manifest"
    text_dir = OUTPUT_ROOT / "02_text_extraction"
    candidate_dir = OUTPUT_ROOT / "03_sar_candidates"
    review_dir = OUTPUT_ROOT / "04_review"
    for directory in (manifest_dir, text_dir, candidate_dir, review_dir):
        directory.mkdir(parents=True, exist_ok=True)

    papers = source_files()
    manifest = build_manifest(papers)
    write_csv(
        manifest_dir / "all_volume67_papers.csv",
        manifest,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes"],
    )
    pilot = select_pilot(manifest)
    write_csv(
        manifest_dir / "pilot_selection.csv",
        pilot,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes"],
    )

    text_records: list[dict[str, object]] = []
    all_evidence: list[dict[str, object]] = []
    all_pages: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for index, record in enumerate(pilot, start=1):
        print(f"[{index}/{len(pilot)}] {record['filename']}", flush=True)
        try:
            text_record, evidence, pages = candidate_rows(record)
            text_records.append(text_record)
            all_evidence.extend(evidence)
            all_pages.extend(pages)
        except Exception as exc:  # Preserve failures for repeatable recovery.
            failures.append({**record, "error": repr(exc)})

    write_csv(
        text_dir / "pilot_document_text_index.csv",
        text_records,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes", "page_count", "text_characters", "doi", "text_status"],
    )
    write_csv(
        text_dir / "pilot_page_coverage.csv",
        all_pages,
        ["paper_id", "page", "text_characters", "has_modification_keyword", "has_activity_value"],
    )
    write_csv(
        candidate_dir / "pilot_evidence_candidates.csv",
        all_evidence,
        ["paper_id", "source_pdf", "page", "evidence_type", "compound_mentions", "activity_mentions", "evidence_text", "review_status", "confidence"],
    )
    write_csv(
        review_dir / "pilot_failures.csv",
        failures,
        ["paper_id", "source_folder", "source_pdf", "filename", "filename_year", "title_guess", "file_size_bytes", "error"],
    )

    evidence_types = Counter(row["evidence_type"] for row in all_evidence)
    report = f"""# Pilot Extraction Report

## Scope

- Corpus: Journal of Medicinal Chemistry, Volume 67 issue folders 1-22.
- Corpus manifest: {len(manifest)} PDFs.
- Pilot selection: {len(pilot)} PDFs, six alphabetically stable files per issue-range folder.
- Scope limitation: extraction uses PDF text only. It does not claim to reconstruct molecular structures or reaction schemes.

## Results

- PDFs processed successfully: {len(text_records)}
- PDF failures: {len(failures)}
- Total pages processed: {sum(int(row['page_count']) for row in text_records)}
- PDFs with usable text layer: {sum(row['text_status'] == 'ok' for row in text_records)} / {len(text_records)}
- Candidate evidence rows: {len(all_evidence)}
- Candidate modification statements: {evidence_types['modification_statement']}
- Candidate compound-activity statements: {evidence_types['compound_activity_statement']}

## How To Review

1. Start with `03_sar_candidates/pilot_evidence_candidates.csv`.
2. Open its `source_pdf` and inspect the cited `page` before accepting a row.
3. Set `review_status` to `accepted`, `rejected`, or `needs_structure_review` in a review copy.
4. Only accepted rows should become structured molecular modification records in the next stage.

## Next Stage

Use accepted evidence to identify compound pairs, then inspect the cited scheme/table to assign modified position, original group, new group, and an auditable structure representation. Supporting Information will be needed for complete synthetic-route extraction.
"""
    (review_dir / "pilot_report.md").write_text(report, encoding="utf-8")
    summary = {
        "corpus_pdfs": len(manifest),
        "pilot_pdfs": len(pilot),
        "processed_pdfs": len(text_records),
        "failures": len(failures),
        "evidence_rows": len(all_evidence),
        "evidence_types": dict(evidence_types),
    }
    (review_dir / "pilot_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
