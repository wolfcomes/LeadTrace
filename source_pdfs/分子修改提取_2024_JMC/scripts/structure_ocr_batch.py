#!/usr/bin/env python3
"""Build auditable structure crops and optional DECIMER proposals in batches.

The input queue is text-derived and remains read-only. This module only writes
under ``09_paper_review/auto_fill`` (or an explicitly supplied output folder).
Every OCSR result is a proposal and therefore stays ``proposal_requires_human_review``.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable, Mapping

import pymupdf as fitz
from rdkit import Chem
from rdkit import RDLogger

from ocsr_benchmark import configure_nvidia_library_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "structure_review_queue.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
DEFAULT_CROPS_DIR = DEFAULT_OUTPUT_DIR / "structure_ocr_crops"
DEFAULT_CANDIDATES = DEFAULT_OUTPUT_DIR / "structure_ocr_candidates.csv"
DEFAULT_PROPOSALS = DEFAULT_OUTPUT_DIR / "structure_ocr_proposals.csv"
DEFAULT_PROGRESS = DEFAULT_OUTPUT_DIR / "structure_ocr_progress.csv"
DEFAULT_SUMMARY = DEFAULT_OUTPUT_DIR / "structure_ocr_summary.json"

PAGE_CANDIDATE_FIELDS = (
    "candidate_id", "page_candidate_id", "paper_id", "doi", "source_pdf", "page",
    "region_kind", "crop_path", "x0", "y0", "x1", "y1", "candidate_score",
    "source_queue_item_ids", "compound_ids", "crop_status",
)

PROPOSAL_FIELDS = (
    "candidate_id", "page_candidate_id", "paper_id", "doi", "source_pdf", "page",
    "region_kind", "crop_path", "x0", "y0", "x1", "y1", "candidate_score",
    "source_queue_item_ids", "compound_ids", "raw_smiles", "token_confidences",
    "mean_token_confidence", "min_token_confidence", "inference_status",
    "inference_error", "rdkit_status", "canonical_smiles", "model_version",
    "proposal_quality", "review_status",
)

PROGRESS_FIELDS = (
    "paper_id", "source_pdf", "pages_seen", "pages_with_candidates",
    "candidate_count", "ocr_attempted", "ocr_ok", "rdkit_valid", "rdkit_invalid",
    "inference_errors", "structure_source_available", "progress_status", "updated_at",
)

COMPOUND_LABEL = re.compile(r"(?<![A-Za-z0-9])\d{1,3}[A-Za-z](?:[-–][A-Za-z])?(?![A-Za-z0-9])")
INFERENCE_REEXECUTED = "STRUCTURE_OCR_REEXECUTED"


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: Iterable[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _normalise_label(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _page_id(source_pdf: str, page: str) -> str:
    digest = hashlib.sha1(f"{Path(source_pdf).resolve()}::{page}".encode()).hexdigest()[:12]
    return f"PAGE-{digest}"


def _candidate_id(page_candidate_id: str, number: int) -> str:
    return f"{page_candidate_id}-CAND-{number:03d}"


def _rect_area(rect: fitz.Rect) -> float:
    return max(0.0, rect.width) * max(0.0, rect.height)


def _expanded(rect: fitz.Rect, margin: float, page_rect: fitz.Rect) -> fitz.Rect:
    result = fitz.Rect(rect.x0 - margin, rect.y0 - margin, rect.x1 + margin, rect.y1 + margin)
    return result & page_rect


def _iou(first: fitz.Rect, second: fitz.Rect) -> float:
    intersection = first & second
    overlap = _rect_area(intersection)
    if not overlap:
        return 0.0
    return overlap / (_rect_area(first) + _rect_area(second) - overlap)


def _clusters(rects: list[tuple[fitz.Rect, int, bool]], gap: float = 7.0) -> list[tuple[fitz.Rect, int, bool]]:
    """Cluster nearby vector strokes into likely molecule drawings."""
    if not rects:
        return []
    parents = list(range(len(rects)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        left, right = find(first), find(second)
        if left != right:
            parents[right] = left

    expanded_rects = [fitz.Rect(r.x0 - gap, r.y0 - gap, r.x1 + gap, r.y1 + gap) for r, _, _ in rects]
    for first, first_rect in enumerate(expanded_rects):
        for second in range(first + 1, len(expanded_rects)):
            if first_rect.intersects(expanded_rects[second]):
                union(first, second)

    grouped: dict[int, list[tuple[fitz.Rect, int, bool]]] = defaultdict(list)
    for index, item in enumerate(rects):
        grouped[find(index)].append(item)
    output = []
    for values in grouped.values():
        bbox = fitz.Rect(values[0][0])
        count = 0
        has_fill = False
        for rect, item_count, filled in values[1:]:
            bbox |= rect
            count += item_count
            has_fill = has_fill or filled
        count += values[0][1]
        has_fill = has_fill or values[0][2]
        output.append((bbox, count, has_fill))
    return output


def _label_rects(page: fitz.Page, labels: set[str]) -> list[fitz.Rect]:
    if not labels:
        return []
    output = []
    for word in page.get_text("words"):
        if _normalise_label(word[4]) in labels:
            output.append(fitz.Rect(word[:4]))
    return output


def extract_page_candidates(page: fitz.Page, labels: set[str] | None = None) -> list[dict[str, str]]:
    """Return small, traceable vector/image regions instead of whole-page crops."""
    labels = {_normalise_label(label) for label in (labels or set()) if label}
    page_rect = page.rect
    target_labels = _label_rects(page, labels)
    candidates: list[tuple[fitz.Rect, str, float]] = []

    drawings: list[tuple[fitz.Rect, int, bool]] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        item_count = len(drawing.get("items", []))
        if _rect_area(rect) > 0:
            drawings.append((rect, max(1, item_count), drawing.get("fill") is not None))
    for rect, item_count, has_fill in _clusters(drawings):
        if _rect_area(rect) < 18 or (rect.width < 8 and rect.height < 8):
            continue
        if has_fill:
            continue
        if (rect.width > rect.height * 8 or rect.height > rect.width * 8) and item_count < 20:
            continue
        if item_count < 3 and rect.width < 20 and rect.height < 20:
            continue
        crop = _expanded(rect, 8, page_rect)
        score = min(6.0, 1.0 + item_count / 8.0)
        if any(crop.intersects(label_rect) for label_rect in target_labels):
            score += 3.0
        candidates.append((crop, "vector_drawing", score))

    for image in page.get_image_info(xrefs=True):
        rect = fitz.Rect(image["bbox"])
        if _rect_area(rect) < 500:
            continue
        crop = _expanded(rect, 8, page_rect)
        score = 2.0
        if any(crop.intersects(label_rect) for label_rect in target_labels):
            score += 3.0
        candidates.append((crop, "embedded_image", score))

    # Keep overlapping detections once while retaining the more informative score.
    candidates.sort(key=lambda item: (-item[2], _rect_area(item[0])))
    deduplicated: list[tuple[fitz.Rect, str, float]] = []
    for candidate in candidates:
        if any(_iou(candidate[0], previous[0]) >= 0.85 for previous in deduplicated):
            continue
        deduplicated.append(candidate)

    output = []
    for rect, kind, score in deduplicated:
        output.append({
            "page": str(page.number + 1),
            "region_kind": kind,
            "x0": f"{rect.x0:.2f}", "y0": f"{rect.y0:.2f}",
            "x1": f"{rect.x1:.2f}", "y1": f"{rect.y1:.2f}",
            "candidate_score": f"{score:.2f}",
        })
    return output


def _focus(row: Mapping[str, str]) -> bool:
    return (
        row.get("structure_need") != "statement_only"
        or row.get("page_has_table_or_scheme_signal") == "1"
        or row.get("page_has_figure_signal") == "1"
    )


def _labels_for_rows(rows: Iterable[Mapping[str, str]]) -> set[str]:
    labels: set[str] = set()
    for row in rows:
        for key in ("parent_compound", "derived_compound"):
            value = str(row.get(key, "")).strip()
            if value:
                labels.add(_normalise_label(value))
        labels.update(_normalise_label(match.group(0)) for match in COMPOUND_LABEL.finditer(row.get("evidence_text", "")))
    return labels


def build_page_worklist(
    queue_rows: Iterable[Mapping[str, str]],
    crops_dir: Path = DEFAULT_CROPS_DIR,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Build one crop worklist row per candidate region, deduplicated by PDF page."""
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in queue_rows:
        if _focus(row) and row.get("source_pdf") and row.get("page"):
            grouped[(str(row["source_pdf"]), str(row["page"]))].append(row)
    page_keys = sorted(grouped, key=lambda item: (item[0], int(item[1]) if item[1].isdigit() else item[1]))
    selected = page_keys[offset: offset + limit if limit is not None else None]
    output: list[dict[str, str]] = []
    for source_pdf, page_number in selected:
        rows = grouped[(source_pdf, page_number)]
        page_candidate_id = _page_id(source_pdf, page_number)
        queue_ids = " | ".join(sorted({str(row.get("review_item_id", "")) for row in rows if row.get("review_item_id")}))
        compound_ids = " | ".join(sorted({
            str(row.get(key, "")) for row in rows for key in ("parent_compound", "derived_compound")
            if row.get(key)
        }))
        if not Path(source_pdf).is_file():
            continue
        try:
            document = fitz.open(source_pdf)
            page_index = int(page_number) - 1
            if not 0 <= page_index < document.page_count:
                document.close()
                continue
            regions = extract_page_candidates(document[page_index], _labels_for_rows(rows))
            document.close()
        except Exception:
            continue
        for number, region in enumerate(regions, start=1):
            candidate_id = _candidate_id(page_candidate_id, number)
            crop_path = Path(crops_dir) / f"{candidate_id}.png"
            output.append({
                "candidate_id": candidate_id,
                "page_candidate_id": page_candidate_id,
                "paper_id": str(rows[0].get("paper_id", "")),
                "doi": str(rows[0].get("doi", "")),
                "source_pdf": source_pdf,
                "page": page_number,
                **region,
                "crop_path": str(crop_path.resolve()),
                "source_queue_item_ids": queue_ids,
                "compound_ids": compound_ids,
                "crop_status": "pending",
            })
    return output


def select_inference_candidates(
    candidates: Iterable[Mapping[str, str]], *, offset: int = 0, limit: int | None = None
) -> list[dict[str, str]]:
    """Choose a deterministic, high-signal slice from an existing crop manifest."""
    rows = [
        {field: str(row.get(field, "") or "") for field in PAGE_CANDIDATE_FIELDS}
        for row in candidates
        if str(row.get("crop_status", "")) == "rendered" and str(row.get("crop_path", ""))
    ]
    rows.sort(key=lambda row: (
        0 if row.get("region_kind") == "vector_drawing" else 1,
        -float(row.get("candidate_score", "0") or 0),
        row.get("candidate_id", ""),
    ))
    return rows[offset: offset + limit if limit is not None else None]


def render_candidate(candidate: Mapping[str, str], *, replace: bool = False) -> str:
    output = Path(candidate["crop_path"])
    if output.is_file() and not replace:
        return "existing"
    document = fitz.open(candidate["source_pdf"])
    try:
        page = document[int(candidate["page"]) - 1]
        clip = fitz.Rect(
            float(candidate["x0"]), float(candidate["y0"]),
            float(candidate["x1"]), float(candidate["y1"]),
        ) & page.rect
        if _rect_area(clip) <= 0:
            raise ValueError("candidate crop has no positive area")
        output.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), clip=clip, alpha=False).save(output)
    finally:
        document.close()
    return "rendered"


def validate_ocr_proposal(row: Mapping[str, object]) -> dict[str, str]:
    """Normalize an OCSR result; validity never promotes it beyond proposal status."""
    checked = {field: str(row.get(field, "") or "") for field in PROPOSAL_FIELDS}
    raw_smiles = checked["raw_smiles"].strip()
    if checked["inference_status"] == "ok" and raw_smiles:
        RDLogger.DisableLog("rdApp.error")
        try:
            molecule = Chem.MolFromSmiles(raw_smiles)
        finally:
            RDLogger.EnableLog("rdApp.error")
        if molecule is None:
            checked["rdkit_status"] = "invalid"
            checked["canonical_smiles"] = ""
            checked["proposal_quality"] = "invalid_smiles_needs_review"
        else:
            checked["rdkit_status"] = "valid"
            checked["canonical_smiles"] = Chem.MolToSmiles(molecule, isomericSmiles=True)
            common_atoms = {"B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I", "Si", "Se"}
            suspicious = (
                any(atom.GetSymbol() not in common_atoms for atom in molecule.GetAtoms())
                or len(raw_smiles) > 180
                or raw_smiles.count(".") > 4
            )
            checked["proposal_quality"] = (
                "valid_but_suspicious_needs_review" if suspicious else "valid_but_needs_review"
            )
    elif checked["inference_status"] == "error":
        checked["rdkit_status"] = "not_run"
        checked["proposal_quality"] = "inference_error_needs_review"
    else:
        checked["rdkit_status"] = checked["rdkit_status"] or "not_run"
        checked["proposal_quality"] = checked["proposal_quality"] or "no_structure_proposal"
    checked["review_status"] = "proposal_requires_human_review"
    return checked


def merge_proposals(
    output_path: Path,
    existing_rows: Iterable[Mapping[str, object]],
    incoming_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Merge a batch idempotently, retaining any human-reviewed proposal."""
    by_id: dict[str, dict[str, str]] = {}
    for row in existing_rows:
        normalised = {field: str(row.get(field, "") or "") for field in PROPOSAL_FIELDS}
        if normalised["candidate_id"]:
            by_id[normalised["candidate_id"]] = normalised
    if Path(output_path).is_file():
        for row in read_csv(Path(output_path)):
            normalised = {field: str(row.get(field, "") or "") for field in PROPOSAL_FIELDS}
            if normalised["candidate_id"]:
                by_id[normalised["candidate_id"]] = normalised
    for row in incoming_rows:
        checked = validate_ocr_proposal(row)
        current = by_id.get(checked["candidate_id"])
        if current and current.get("review_status") in {"reviewed", "confirmed"}:
            continue
        by_id[checked["candidate_id"]] = checked
    merged = [by_id[key] for key in sorted(by_id)]
    atomic_write_csv(output_path, merged, PROPOSAL_FIELDS)
    return merged


def _render_and_collect(candidates: list[dict[str, str]]) -> None:
    for candidate in candidates:
        try:
            render_candidate(candidate)
            candidate["crop_status"] = "rendered"
        except Exception as error:
            candidate["crop_status"] = f"error:{type(error).__name__}"


def _load_predictor(cache: Path):
    from ocsr_benchmark import probe_decimer_models

    configure_nvidia_library_path()
    evidence = probe_decimer_models(cache)
    import DECIMER

    predictor = getattr(DECIMER, "predict_SMILES", None)
    if predictor is None:
        raise RuntimeError("DECIMER does not expose predict_SMILES")
    return predictor, str(evidence["version"])


def infer_candidates(candidates: Iterable[Mapping[str, str]], cache: Path) -> list[dict[str, str]]:
    predictor, model_version = _load_predictor(cache)
    output = []
    for candidate in candidates:
        row = {field: str(candidate.get(field, "") or "") for field in PROPOSAL_FIELDS}
        row.update({
            "raw_smiles": "", "token_confidences": "[]", "mean_token_confidence": "",
            "min_token_confidence": "", "inference_status": "error", "inference_error": "",
            "rdkit_status": "not_run", "canonical_smiles": "", "model_version": model_version,
            "proposal_quality": "inference_error_needs_review",
            "review_status": "proposal_requires_human_review",
        })
        try:
            raw_smiles, confidences = predictor(candidate["crop_path"], confidence=True)
            raw_smiles = str(raw_smiles or "")
            confidence_rows = []
            for item in confidences or []:
                token, score = (item["token"], item["confidence"]) if isinstance(item, Mapping) else item
                confidence_rows.append({"token": str(token), "confidence": float(score)})
            scores = [row["confidence"] for row in confidence_rows]
            row.update({
                "raw_smiles": raw_smiles,
                "token_confidences": json.dumps(confidence_rows, ensure_ascii=True, separators=(",", ":")),
                "mean_token_confidence": str(sum(scores) / len(scores)) if scores else "",
                "min_token_confidence": str(min(scores)) if scores else "",
                "inference_status": "ok",
            })
        except Exception as error:
            row["inference_error"] = f"{type(error).__name__}: {error}"
        output.append(validate_ocr_proposal(row))
    return output


def relaunch_for_inference(argv: list[str]) -> int:
    """Restart before TensorFlow import so NVIDIA package libraries are visible."""
    library_path = configure_nvidia_library_path()
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = library_path
    environment[INFERENCE_REEXECUTED] = "1"
    completed = subprocess.run(
        [os.sys.executable, str(Path(__file__).resolve()), *argv],
        env=environment,
        check=False,
    )
    return completed.returncode


def build_progress_rows(
    candidates: Iterable[Mapping[str, str]],
    proposals: Iterable[Mapping[str, str]],
    *,
    paper_rows: Iterable[Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    proposal_by_id = {str(row.get("candidate_id", "")): row for row in proposals}
    by_paper: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    paper_sources: dict[str, str] = {}
    for row in paper_rows or []:
        paper_id = str(row.get("paper_id", ""))
        if paper_id:
            paper_sources.setdefault(paper_id, str(row.get("source_pdf", "")))
    for candidate in candidates:
        paper_id = str(candidate.get("paper_id", ""))
        by_paper[paper_id].append(candidate)
        paper_sources[paper_id] = str(candidate.get("source_pdf", ""))
    output = []
    keys = set(paper_sources) | set(by_paper)
    for paper_id in sorted(keys):
        source_pdf = paper_sources[paper_id]
        rows = by_paper[paper_id]
        page_count = len({row.get("page", "") for row in rows})
        page_count_with_candidates = page_count
        related = [proposal_by_id.get(row.get("candidate_id", ""), {}) for row in rows]
        attempted = sum(bool(row.get("inference_status")) and row.get("inference_status") != "pending" for row in related)
        ok = sum(row.get("inference_status") == "ok" for row in related)
        valid = sum(row.get("rdkit_status") == "valid" for row in related)
        invalid = sum(row.get("rdkit_status") == "invalid" for row in related)
        errors = sum(row.get("inference_status") == "error" for row in related)
        if not rows:
            status = "no_structure_candidate_found"
        elif attempted == len(rows):
            status = "ocr_completed_with_review_required"
        else:
            status = "crops_ready_for_ocr"
        output.append({
            "paper_id": paper_id, "source_pdf": source_pdf, "pages_seen": str(page_count),
            "pages_with_candidates": str(page_count_with_candidates), "candidate_count": str(len(rows)),
            "ocr_attempted": str(attempted), "ocr_ok": str(ok), "rdkit_valid": str(valid),
            "rdkit_invalid": str(invalid), "inference_errors": str(errors),
            "structure_source_available": "1" if rows else "0", "progress_status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return output


def run_batch(
    *, queue_path: Path = DEFAULT_QUEUE, crops_dir: Path = DEFAULT_CROPS_DIR,
    candidates_path: Path = DEFAULT_CANDIDATES, proposals_path: Path = DEFAULT_PROPOSALS,
    progress_path: Path = DEFAULT_PROGRESS, summary_path: Path = DEFAULT_SUMMARY,
    cache: Path | None = None, offset: int = 0, limit: int | None = None,
    resume: bool = True, infer: bool = True, from_candidates: bool = False,
    candidate_offset: int = 0, candidate_limit: int | None = None,
) -> dict[str, object]:
    queue = read_csv(queue_path)
    previous_candidates = read_csv(candidates_path) if resume and candidates_path.is_file() else []
    candidates = (
        select_inference_candidates(previous_candidates, offset=candidate_offset, limit=candidate_limit)
        if from_candidates and previous_candidates
        else build_page_worklist(queue, crops_dir, offset=offset, limit=limit)
    )
    if not from_candidates:
        _render_and_collect(candidates)
    candidate_by_id = {row["candidate_id"]: row for row in previous_candidates if row.get("candidate_id")}
    candidate_by_id.update({row["candidate_id"]: row for row in candidates})
    all_candidates = [candidate_by_id[key] for key in sorted(candidate_by_id)]
    atomic_write_csv(candidates_path, all_candidates, PAGE_CANDIDATE_FIELDS)

    old_proposals = read_csv(proposals_path) if resume and proposals_path.is_file() else []
    processed_ids = {row.get("candidate_id") for row in old_proposals if row.get("candidate_id")}
    to_infer = [row for row in candidates if row.get("crop_status") == "rendered" and row.get("candidate_id") not in processed_ids]
    incoming = infer_candidates(to_infer, cache or PROJECT_ROOT / "08_ocsr_benchmark" / "decimer_model") if infer and to_infer else []
    proposals = merge_proposals(proposals_path, old_proposals, incoming)
    manifest_path = PROJECT_ROOT / "01_manifest" / "all_volume67_papers.csv"
    manifest = read_csv(manifest_path) if manifest_path.is_file() else []
    queue_papers = []
    seen_papers: set[str] = set()
    for row in queue:
        if row.get("paper_id") and row["paper_id"] not in seen_papers:
            queue_papers.append({"paper_id": row["paper_id"], "source_pdf": row.get("source_pdf", "")})
            seen_papers.add(row["paper_id"])
    for row in manifest:
        if row.get("paper_id") and row["paper_id"] not in seen_papers:
            queue_papers.append(row)
            seen_papers.add(row["paper_id"])
    progress = build_progress_rows(all_candidates, proposals, paper_rows=queue_papers)
    atomic_write_csv(progress_path, progress, PROGRESS_FIELDS)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "queue_rows": len(queue),
        "focused_pages_in_batch": len({(row["source_pdf"], row["page"]) for row in candidates}),
        "candidate_rows_total": len(all_candidates), "candidate_rows_in_batch": len(candidates),
        "ocr_attempted_total": sum(row.get("inference_status") in {"ok", "error"} for row in proposals),
        "ocr_valid_rdkit_total": sum(row.get("rdkit_status") == "valid" for row in proposals),
        "ocr_invalid_rdkit_total": sum(row.get("rdkit_status") == "invalid" for row in proposals),
        "ocr_inference_error_total": sum(row.get("inference_status") == "error" for row in proposals),
        "proposal_rows_requiring_review": sum(row.get("review_status") == "proposal_requires_human_review" for row in proposals),
        "output_candidates": str(candidates_path.resolve()), "output_proposals": str(proposals_path.resolve()),
        "output_progress": str(progress_path.resolve()), "output_summary": str(summary_path.resolve()),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--crops-dir", type=Path, default=DEFAULT_CROPS_DIR)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / "08_ocsr_benchmark" / "decimer_model")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-infer", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--from-candidates", action="store_true", help="infer an existing crop manifest without rescanning PDFs")
    parser.add_argument("--candidate-offset", type=int, default=0)
    parser.add_argument("--candidate-limit", type=int)
    args = parser.parse_args(argv)
    if not args.no_infer and os.environ.get(INFERENCE_REEXECUTED) != "1":
        return relaunch_for_inference(list(argv) if argv is not None else os.sys.argv[1:])
    summary = run_batch(
        queue_path=args.queue, crops_dir=args.crops_dir, candidates_path=args.candidates,
        proposals_path=args.proposals, progress_path=args.progress, summary_path=args.summary,
        cache=args.cache_dir, offset=args.offset, limit=args.limit,
        resume=not args.no_resume, infer=not args.no_infer, from_candidates=args.from_candidates,
        candidate_offset=args.candidate_offset, candidate_limit=args.candidate_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
