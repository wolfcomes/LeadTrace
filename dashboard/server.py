"""Small local web server for the lead-optimization project dashboard."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import mimetypes
import os
import re
import tempfile
import sys
from threading import RLock
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from rdkit import Chem
from rdkit.Chem import Draw


DASHBOARD_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_ROOT.parent
PIPELINE_ROOT = PROJECT_ROOT / "source_pdfs" / "分子修改提取_2024_JMC"
VISUAL_PAGES_ROOT = PIPELINE_ROOT / "05_visual_review" / "explicit_path_pages"
CROPS_ROOT = PIPELINE_ROOT / "08_ocsr_benchmark" / "crops"
STRUCTURES_ROOT = PIPELINE_ROOT / "09_structure_confirmation" / "generated_structures"
SUMMARY_PATH = PIPELINE_ROOT / "08_ocsr_benchmark" / "benchmark_summary.json"
STRUCTURE_CONFIRMATION_PATH = PIPELINE_ROOT / "09_structure_confirmation" / "confirmed_path_structures.csv"
PAPER_PAGE_SIZE = 20
PAPER_REVIEW_DIR = PIPELINE_ROOT / "09_paper_review"
PAPER_REVIEW_OVERRIDES_PATH = PAPER_REVIEW_DIR / "paper_review_overrides.json"
PAPER_REVIEWED_ENTRIES_PATH = PAPER_REVIEW_DIR / "reviewed_entries.csv"
AUTO_FILL_DIR = PAPER_REVIEW_DIR / "auto_fill"
AUTO_FILLED_REVIEW_ITEMS_PATH = AUTO_FILL_DIR / "auto_filled_review_items.csv"
STRUCTURE_OCR_PROPOSALS_PATH = AUTO_FILL_DIR / "structure_ocr_proposals.csv"
STRUCTURE_OCR_CROPS_ROOT = AUTO_FILL_DIR / "structure_ocr_crops"
FIRST_PAGE_FRAGMENT_REVIEW_PATH = AUTO_FILL_DIR / "first_page_fragment_review.csv"
FIRST_PAGE_FRAGMENT_SUMMARY_PATH = AUTO_FILL_DIR / "first_page_fragment_review_summary.json"
FIRST_PAGE_MOLECULE_OBJECTS_PATH = AUTO_FILL_DIR / "first_page_molecule_objects.csv"
FIRST_PAGE_MOLECULE_SUMMARY_PATH = AUTO_FILL_DIR / "first_page_molecule_summary.json"
FIRST_PAGE_MOLECULE_PROPOSALS_PATH = AUTO_FILL_DIR / "first_page_molecule_proposals.csv"
MOLECULE_REVIEW_CROPS_ROOT = AUTO_FILL_DIR / "molecule_review_crops"
FIRST_PAGE_FRAGMENT_INFERENCE_PATH = AUTO_FILL_DIR / "first_page_fragment_attachment_inferences.csv"
FIRST_PAGE_FRAGMENT_INFERENCE_SUMMARY_PATH = AUTO_FILL_DIR / "first_page_fragment_attachment_inference_summary.json"
MOLECULE_PAIR_STRUCTURES_ROOT = AUTO_FILL_DIR / "molecule_pair_structures"
COMPOUND_ENTITIES_PATH = AUTO_FILL_DIR / "compound_entities.csv"
COMPOUND_LINEAGE_EDGES_PATH = AUTO_FILL_DIR / "compound_lineage_edges.csv"
COMPOUND_LINEAGE_EVIDENCE_PATH = AUTO_FILL_DIR / "compound_lineage_evidence.csv"
COMPOUND_ACTIVITIES_PATH = AUTO_FILL_DIR / "compound_activities.csv"
COMPOUND_LINEAGE_SUMMARY_PATH = AUTO_FILL_DIR / "compound_lineage_summary.json"
PAPER_REVIEW_STATUSES = {"unreviewed", "in_review", "needs_follow_up", "reviewed"}
PAPER_REVIEW_FIELDS = {"review_status", "title_override", "correction_note", "review_note"}
PAPER_REVIEW_ITEM_FIELDS = {"review_status", "correction_note", "review_note"}
PAPER_REVIEW_CONTENT_FIELDS = {
    "page", "page_references", "compound_mentions", "activity", "evidence_text",
    "parent_compound", "derived_compound", "reported_from_group", "reported_to_group",
    "relation_type", "structure_review_status", "path_status",
    "structure_confirmation_status", "parent_smiles", "derived_smiles",
    "parent_canonical_smiles", "derived_canonical_smiles",
    "fragment_smiles", "assembled_smiles", "attachment_status", "assembly_status",
    "inference_note", "root_template",
}
PAPER_REVIEW_ITEM_ALL_FIELDS = PAPER_REVIEW_ITEM_FIELDS | PAPER_REVIEW_CONTENT_FIELDS
PAPER_REVIEWED_ENTRY_FIELDS = [
    "paper_id", "review_item_id", "page", "page_references", "parent_compound",
    "derived_compound", "reported_from_group", "reported_to_group", "activity",
    "evidence_text", "compound_mentions", "relation_type", "path_status",
    "structure_review_status", "structure_confirmation_status", "parent_smiles",
    "derived_smiles", "parent_canonical_smiles", "derived_canonical_smiles",
    "fragment_smiles", "assembled_smiles", "attachment_status", "assembly_status",
    "inference_note", "parent_object_id", "derived_object_id", "pair_kind", "pair_status",
    "lineage_id", "lineage_edge_id", "root_template_entity_id", "root_template",
    "parent_entity_id", "derived_entity_id", "relation_status", "relation_confidence",
    "review_status", "review_note", "correction_note", "source_kind", "updated_at",
]
PAPER_REVIEW_LOCK = RLock()

PATH_FILES = {
    "explicit": PIPELINE_ROOT / "06_text_confirmed_paths" / "explicit_text_confirmed_paths.csv",
    "unresolved": PIPELINE_ROOT / "05_visual_review" / "unresolved_path_review_queue.csv",
}
COUNT_FILES = {
    "papers": PIPELINE_ROOT / "01_manifest" / "all_volume67_papers.csv",
    "pages": PIPELINE_ROOT / "02_text_extraction" / "full_page_coverage.csv",
    "evidence": PIPELINE_ROOT / "03_sar_candidates" / "full_evidence_candidates.csv",
    "candidate_records": PIPELINE_ROOT / "07_enriched_text_paths" / "all_path_candidates_enriched.csv",
    "explicit_paths": PATH_FILES["explicit"],
    "structure_crops": PIPELINE_ROOT / "08_ocsr_benchmark" / "structure_crop_manifest.csv",
}
PROPOSALS_PATH = PIPELINE_ROOT / "08_ocsr_benchmark" / "ocsr_proposals.csv"
PAPER_FILES = {
    "manifest": COUNT_FILES["papers"],
    "documents": PIPELINE_ROOT / "02_text_extraction" / "full_document_text_index.csv",
    "evidence": PIPELINE_ROOT / "03_sar_candidates" / "full_evidence_candidates.csv",
    "candidates": COUNT_FILES["candidate_records"],
    "explicit": PATH_FILES["explicit"],
    "structures": STRUCTURE_CONFIRMATION_PATH,
}


class DashboardDataError(RuntimeError):
    """Raised when a dashboard data source cannot be read."""


class AssetNotFound(FileNotFoundError):
    """Raised when a requested evidence asset is not in an approved directory."""


class PathNotFound(KeyError):
    """Raised when a requested explicit path does not exist."""


class PaperNotFound(KeyError):
    """Raised when a requested Paper is not in the corpus manifest."""


class ReviewLocked(RuntimeError):
    """Raised when a reviewed Paper would be changed by a later request."""


class ReviewItemNotFound(KeyError):
    """Raised when a requested Paper review item does not exist."""


class ReviewItemLocked(RuntimeError):
    """Raised when a confirmed review item would be changed or deleted."""


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV snapshot without mutating or caching the source."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except OSError as error:
        raise DashboardDataError(f"could not read {path}") from error


def load_auto_fill_rows() -> dict[str, dict[str, str]]:
    """Load the read-only automatic fill layer keyed by review item ID."""
    if not AUTO_FILLED_REVIEW_ITEMS_PATH.is_file():
        return {}
    return {
        row.get("review_item_id", ""): row
        for row in read_csv_rows(AUTO_FILLED_REVIEW_ITEMS_PATH)
        if row.get("review_item_id")
    }


def read_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardDataError(f"could not read {path}") from error
    if not isinstance(value, dict):
        raise DashboardDataError(f"expected an object in {path}")
    return value


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _confirmed_count(rows: list[dict[str, str]]) -> int:
    return sum(
        row.get("path_status", "") in {"confirmed", "structure_confirmed", "final"}
        or row.get("review_status", "") in {"confirmed", "final"}
        for row in rows
    )


def _proposal_quality() -> dict[str, int]:
    rows = []
    if PROPOSALS_PATH.is_file():
        rows.extend(read_csv_rows(PROPOSALS_PATH))
    if STRUCTURE_OCR_PROPOSALS_PATH.is_file():
        rows.extend(read_csv_rows(STRUCTURE_OCR_PROPOSALS_PATH))
    statuses = Counter(row.get("rdkit_status", "not_run") for row in rows)
    inference = Counter(row.get("inference_status", "unknown") for row in rows)
    return {
        "proposals": len(rows),
        "rdkit_valid": statuses.get("valid", 0),
        "rdkit_invalid": statuses.get("invalid", 0),
        "rdkit_not_run": statuses.get("not_run", 0),
        "inference_errors": inference.get("error", 0),
    }


def _structure_ocr_progress() -> dict[str, int]:
    """Summarize the separate page-crop OCSR queue without counting legacy crops."""
    path = AUTO_FILL_DIR / "structure_ocr_progress.csv"
    if not path.is_file():
        return {
            "papers": 0, "papers_with_candidates": 0, "candidate_rows": 0,
            "attempted_rows": 0, "pending_rows": 0, "valid_rdkit_rows": 0,
            "invalid_rdkit_rows": 0, "inference_error_rows": 0,
        }
    rows = read_csv_rows(path)
    candidate_rows = sum(_integer(row.get("candidate_count")) for row in rows)
    attempted_rows = sum(_integer(row.get("ocr_attempted")) for row in rows)
    return {
        "papers": len(rows),
        "papers_with_candidates": sum(_integer(row.get("candidate_count")) > 0 for row in rows),
        "candidate_rows": candidate_rows,
        "attempted_rows": attempted_rows,
        "pending_rows": max(0, candidate_rows - attempted_rows),
        "valid_rdkit_rows": sum(_integer(row.get("rdkit_valid")) for row in rows),
        "invalid_rdkit_rows": sum(_integer(row.get("rdkit_invalid")) for row in rows),
        "inference_error_rows": sum(_integer(row.get("inference_errors")) for row in rows),
    }


def _structure_rows() -> dict[str, dict[str, str]]:
    if not STRUCTURE_CONFIRMATION_PATH.is_file():
        return {}
    rows = read_csv_rows(STRUCTURE_CONFIRMATION_PATH)
    return {row.get("visual_review_id", ""): row for row in rows if row.get("visual_review_id")}


def _paper_status(*, explicit_paths: int, candidate_count: int, evidence_count: int) -> str:
    if explicit_paths:
        return "path_review"
    if candidate_count:
        return "candidate_review"
    if evidence_count:
        return "evidence_review"
    return "text_ready"


def _paper_status_label(status: str) -> str:
    return {
        "text_ready": "TEXT READY",
        "evidence_review": "EVIDENCE REVIEW",
        "candidate_review": "CANDIDATE REVIEW",
        "path_review": "PATH REVIEW",
    }.get(status, status.replace("_", " ").upper())


def load_review_overrides() -> dict[str, dict[str, object]]:
    """Load the separate human review layer without touching pipeline files."""
    if not PAPER_REVIEW_OVERRIDES_PATH.is_file():
        return {}
    payload = read_json(PAPER_REVIEW_OVERRIDES_PATH)
    papers = payload.get("papers", {})
    if not isinstance(papers, dict):
        raise DashboardDataError(f"expected papers object in {PAPER_REVIEW_OVERRIDES_PATH}")
    return {
        str(paper_id): value
        for paper_id, value in papers.items()
        if isinstance(value, dict)
    }


def _manifest_paper_ids() -> set[str]:
    return {
        row.get("paper_id", "")
        for row in read_csv_rows(PAPER_FILES["manifest"])
        if row.get("paper_id")
    }


def _paper_by_id(paper_id: str) -> dict[str, object]:
    record = next((item for item in _paper_records() if item["paper_id"] == paper_id), None)
    if record is None:
        raise PaperNotFound(paper_id)
    return record


def _atomic_save_review_overrides(overrides: dict[str, dict[str, object]]) -> None:
    payload = {"version": 1, "papers": overrides}
    PAPER_REVIEW_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=PAPER_REVIEW_OVERRIDES_PATH.parent,
        prefix="paper_review_", suffix=".tmp", delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    os.replace(temporary_path, PAPER_REVIEW_OVERRIDES_PATH)


def _validate_review_content(changes: dict[str, object]) -> dict[str, object]:
    """Normalize the field formats used by editable review entries."""
    normalized: dict[str, object] = {}
    for key, value in changes.items():
        if key not in PAPER_REVIEW_CONTENT_FIELDS:
            continue
        if key == "page":
            if value in (None, ""):
                normalized[key] = 0
                continue
            try:
                page = int(str(value))
            except (TypeError, ValueError) as error:
                raise ValueError("page must be an integer") from error
            if page < 1:
                raise ValueError("page must be an integer greater than 0")
            normalized[key] = page
            continue
        text = str(value or "").strip()
        if key in {
            "parent_smiles", "derived_smiles", "parent_canonical_smiles",
            "derived_canonical_smiles", "fragment_smiles", "assembled_smiles",
        }:
            if text and not re.fullmatch(r"[A-Za-z0-9@+\-\[\]()=#$%./\\*:]+", text):
                raise ValueError(f"{key} must contain a valid SMILES format")
        normalized[key] = text
    return normalized


def save_review_override(paper_id: str, changes: dict[str, object]) -> dict[str, object]:
    """Persist one validated Paper review record with an atomic replacement."""
    if paper_id not in _manifest_paper_ids():
        raise PaperNotFound(paper_id)
    if not isinstance(changes, dict):
        raise ValueError("review payload must be an object")
    unknown = set(changes) - PAPER_REVIEW_FIELDS
    if unknown:
        raise ValueError(f"unsupported review fields: {', '.join(sorted(unknown))}")
    with PAPER_REVIEW_LOCK:
        overrides = load_review_overrides()
        existing = overrides.get(paper_id, {})
        if existing.get("review_status") == "reviewed":
            raise ReviewLocked(paper_id)
        review_status = str(changes.get("review_status", existing.get("review_status", "unreviewed")))
        if review_status not in PAPER_REVIEW_STATUSES:
            raise ValueError("review_status must be unreviewed, in_review, needs_follow_up, or reviewed")
        normalized = {
            "review_status": review_status,
            "title_override": str(changes.get("title_override", existing.get("title_override", ""))).strip(),
            "correction_note": str(changes.get("correction_note", existing.get("correction_note", ""))).strip(),
            "review_note": str(changes.get("review_note", existing.get("review_note", ""))).strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        overrides[paper_id] = normalized
        _atomic_save_review_overrides(overrides)
    return normalized


def save_review_item(
    paper_id: str, review_item_id: str, changes: dict[str, object], *, allow_reviewed: bool = False
) -> dict[str, object]:
    """Persist the human review state for one unified Paper entry."""
    if not isinstance(changes, dict):
        raise ValueError("review payload must be an object")
    unknown = set(changes) - PAPER_REVIEW_ITEM_ALL_FIELDS
    if unknown:
        raise ValueError(f"unsupported review item fields: {', '.join(sorted(unknown))}")
    normalized_content = _validate_review_content(changes)
    detail = load_paper_detail(paper_id)
    item = next(
        (value for value in detail["review_items"] if value["review_item_id"] == review_item_id),
        None,
    )
    if item is None:
        raise ReviewItemNotFound(review_item_id)
    if detail["paper"].get("review_status") == "reviewed":
        raise ReviewLocked(paper_id)
    if item.get("review_status") == "reviewed":
        raise ReviewItemLocked(review_item_id)
    with PAPER_REVIEW_LOCK:
        overrides = load_review_overrides()
        paper_override = overrides.setdefault(paper_id, {})
        item_overrides = paper_override.setdefault("review_items", {})
        if not isinstance(item_overrides, dict):
            item_overrides = {}
            paper_override["review_items"] = item_overrides
        existing = item_overrides.get(review_item_id, {})
        if not isinstance(existing, dict):
            existing = {}
        if existing.get("review_status") == "reviewed":
            raise ReviewItemLocked(review_item_id)
        review_status = str(changes.get("review_status", existing.get("review_status", item["review_status"])))
        if review_status not in PAPER_REVIEW_STATUSES:
            raise ValueError("review_status must be unreviewed, in_review, needs_follow_up, or reviewed")
        if review_status == "reviewed" and not allow_reviewed:
            raise ValueError("review items must be confirmed through the confirm endpoint")
        normalized = {
            "review_status": review_status,
            "correction_note": str(changes.get("correction_note", existing.get("correction_note", ""))).strip(),
            "review_note": str(changes.get("review_note", existing.get("review_note", ""))).strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # The confirmation endpoint intentionally submits only the status.
        # Preserve content that was already saved as a draft in that case.
        normalized.update({
            key: value for key, value in existing.items()
            if key in PAPER_REVIEW_CONTENT_FIELDS and key not in normalized
        })
        normalized.update(normalized_content)
        item_overrides[review_item_id] = normalized
        _atomic_save_review_overrides(overrides)
    return normalized


def _reviewed_entry_row(item: dict[str, object]) -> dict[str, str]:
    candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    path = item.get("path") if isinstance(item.get("path"), dict) else {}
    structure = item.get("structure") if isinstance(item.get("structure"), dict) else {}
    molecule_pair = item.get("molecule_pair") if isinstance(item.get("molecule_pair"), dict) else {}

    def value(*keys: str) -> str:
        for source in (item, candidate, evidence, path, structure, molecule_pair):
            for key in keys:
                current = source.get(key) if isinstance(source, dict) else None
                if current not in (None, ""):
                    return str(current)
        return ""

    return {
        "paper_id": str(item.get("paper_id", "")),
        "review_item_id": str(item.get("review_item_id", "")),
        "page": value("page"),
        "page_references": value("page_references"),
        "parent_compound": value("parent_compound"),
        "derived_compound": value("derived_compound"),
        "reported_from_group": value("reported_from_group", "from_group"),
        "reported_to_group": value("reported_to_group", "to_group"),
        "activity": value("activity", "activity_mentions"),
        "evidence_text": value("evidence_text"),
        "compound_mentions": value("compound_mentions"),
        "relation_type": value("relation_type"),
        "path_status": value("path_status"),
        "structure_review_status": value("structure_review_status"),
        "structure_confirmation_status": value("structure_confirmation_status", "confirmation_status"),
        "parent_smiles": value("parent_smiles"),
        "derived_smiles": value("derived_smiles"),
        "parent_canonical_smiles": value("parent_canonical_smiles"),
        "derived_canonical_smiles": value("derived_canonical_smiles"),
        "fragment_smiles": value("fragment_smiles"),
        "assembled_smiles": value("assembled_smiles"),
        "attachment_status": value("attachment_status"),
        "assembly_status": value("assembly_status"),
        "inference_note": value("inference_note"),
        "parent_object_id": value("parent_object_id"),
        "derived_object_id": value("derived_object_id"),
        "pair_kind": value("pair_kind"),
        "pair_status": value("pair_status"),
        "lineage_id": value("lineage_id"),
        "lineage_edge_id": value("lineage_edge_id"),
        "root_template_entity_id": value("root_template_entity_id"),
        "root_template": value("root_template", "root_template_label"),
        "parent_entity_id": value("parent_entity_id"),
        "derived_entity_id": value("derived_entity_id"),
        "relation_status": value("relation_status"),
        "relation_confidence": value("relation_confidence"),
        "review_status": value("review_status"),
        "review_note": value("review_note"),
        "correction_note": value("correction_note"),
        "source_kind": value("source_kind"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _read_reviewed_entries() -> list[dict[str, str]]:
    return read_csv_rows(PAPER_REVIEWED_ENTRIES_PATH) if PAPER_REVIEWED_ENTRIES_PATH.is_file() else []


def _atomic_save_reviewed_entries(rows: list[dict[str, str]]) -> None:
    PAPER_REVIEWED_ENTRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=PAPER_REVIEWED_ENTRIES_PATH.parent,
        prefix="reviewed_entries_", suffix=".tmp", delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=PAPER_REVIEWED_ENTRY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, PAPER_REVIEWED_ENTRIES_PATH)


def confirm_review_item(paper_id: str, review_item_id: str) -> dict[str, object]:
    """Mark one entry reviewed and sync its flattened values to the curated table."""
    detail = load_paper_detail(paper_id)
    item = next((value for value in detail["review_items"] if value["review_item_id"] == review_item_id), None)
    if item is None:
        raise ReviewItemNotFound(review_item_id)
    if item.get("review_status") == "reviewed":
        raise ReviewItemLocked(review_item_id)
    save_review_item(paper_id, review_item_id, {"review_status": "reviewed"}, allow_reviewed=True)
    refreshed = load_paper_detail(paper_id)
    item = next(value for value in refreshed["review_items"] if value["review_item_id"] == review_item_id)
    rows = _read_reviewed_entries()
    current = _reviewed_entry_row(item)
    rows = [row for row in rows if not (row.get("paper_id") == paper_id and row.get("review_item_id") == review_item_id)]
    rows.append(current)
    _atomic_save_reviewed_entries(rows)
    return item


def add_review_item(paper_id: str, changes: dict[str, object]) -> dict[str, object]:
    """Add a manual entry to the Paper review layer."""
    paper = _paper_by_id(paper_id)
    if paper.get("review_status") == "reviewed":
        raise ReviewLocked(paper_id)
    if not isinstance(changes, dict):
        raise ValueError("review item payload must be an object")
    unknown = set(changes) - PAPER_REVIEW_ITEM_ALL_FIELDS
    if unknown:
        raise ValueError(f"unsupported review item fields: {', '.join(sorted(unknown))}")
    normalized = _validate_review_content(changes)
    review_status = str(changes.get("review_status", "unreviewed"))
    if review_status not in PAPER_REVIEW_STATUSES:
        raise ValueError("review_status must be unreviewed, in_review, needs_follow_up, or reviewed")
    if review_status == "reviewed":
        raise ValueError("new review items must be confirmed through the confirm endpoint")
    with PAPER_REVIEW_LOCK:
        overrides = load_review_overrides()
        added_items = overrides.setdefault(paper_id, {}).setdefault("added_items", {})
        if not isinstance(added_items, dict):
            added_items = {}
            overrides[paper_id]["added_items"] = added_items
        used = {str(value).removeprefix("MANUAL-") for value in added_items}
        number = 1
        while f"{number:06d}" in used:
            number += 1
        item_id = f"MANUAL-{number:06d}"
        record = {**normalized, "review_status": review_status, "review_note": str(changes.get("review_note", "")), "correction_note": str(changes.get("correction_note", "")), "updated_at": datetime.now(timezone.utc).isoformat()}
        added_items[item_id] = record
        _atomic_save_review_overrides(overrides)
    return next(item for item in load_paper_detail(paper_id)["review_items"] if item["review_item_id"] == item_id)


def delete_review_item(paper_id: str, review_item_id: str) -> None:
    """Hide an entry from the curated Paper review set without editing source data."""
    detail = load_paper_detail(paper_id)
    if detail["paper"].get("review_status") == "reviewed":
        raise ReviewLocked(paper_id)
    item = next((value for value in detail["review_items"] if value["review_item_id"] == review_item_id), None)
    if item is None:
        raise ReviewItemNotFound(review_item_id)
    if item.get("review_status") == "reviewed":
        raise ReviewItemLocked(review_item_id)
    with PAPER_REVIEW_LOCK:
        overrides = load_review_overrides()
        paper_override = overrides.setdefault(paper_id, {})
        deleted_items = paper_override.setdefault("deleted_items", [])
        if not isinstance(deleted_items, list):
            deleted_items = []
            paper_override["deleted_items"] = deleted_items
        if review_item_id not in deleted_items:
            deleted_items.append(review_item_id)
        _atomic_save_review_overrides(overrides)


def _complete_molecule_smiles(value: object) -> str:
    """Return a canonical complete-molecule SMILES, rejecting fragments and placeholders."""
    candidate = str(value or "").strip()
    if not candidate or candidate in {"--", "None", "null"}:
        return ""
    molecule = Chem.MolFromSmiles(candidate)
    if molecule is None or any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
        return ""
    return Chem.MolToSmiles(molecule, canonical=True)


def _molecule_object_complete_smiles(molecule_object: dict[str, object]) -> str:
    """Use object OCSR only when the source object is explicitly a whole molecule."""
    if molecule_object.get("object_type") not in {"complete_molecule", "molecule_series_member"}:
        return ""
    if molecule_object.get("smiles_accuracy_state") == "fragment_not_whole_molecule":
        return ""
    for key in ("heuristic_primary_component_smiles", "canonical_smiles", "raw_smiles"):
        smiles = _complete_molecule_smiles(molecule_object.get(key))
        if smiles:
            return smiles
    return ""


def _pair_smiles(value: object, fallback: object = "--") -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate in {"None", "null"}:
        candidate = str(fallback or "").strip()
    return candidate if candidate else "--"


def _molecule_pair_structure_image(smiles: object, side: str) -> str:
    """Render one complete molecule side and return its dashboard asset URL."""
    candidate = _complete_molecule_smiles(smiles)
    if not candidate:
        return ""
    digest = hashlib.sha256(f"{side}:{candidate}".encode("utf-8")).hexdigest()[:20]
    filename = f"molecule-pair-{side}-{digest}.png"
    output_path = MOLECULE_PAIR_STRUCTURES_ROOT / filename
    MOLECULE_PAIR_STRUCTURES_ROOT.mkdir(parents=True, exist_ok=True)
    if not output_path.is_file():
        molecule = Chem.MolFromSmiles(candidate)
        Draw.MolToFile(molecule, str(output_path), size=(900, 620))
    return _asset_url("molecule-pair-structures", filename)


def _refresh_molecule_pair_structures(molecule_pair: dict[str, object]) -> None:
    """Refresh canonical values and both complete-structure images from pair SMILES."""
    for side in ("parent", "derived"):
        smiles_key = f"{side}_smiles"
        canonical_key = f"{side}_canonical_smiles"
        image_key = f"{side}_complete_structure_image_url"
        value = _pair_smiles(molecule_pair.get(smiles_key))
        if value == "--":
            value = _pair_smiles(molecule_pair.get(canonical_key))
        molecule_pair[smiles_key] = value
        molecule_pair[canonical_key] = _complete_molecule_smiles(value) or "--"
        molecule_pair[image_key] = _molecule_pair_structure_image(value, side)


def load_compound_lineages(paper_id: str | None = None) -> dict[str, object]:
    """Load normalized compound entities and direct optimization edges."""
    entity_rows = read_csv_rows(COMPOUND_ENTITIES_PATH) if COMPOUND_ENTITIES_PATH.is_file() else []
    edge_rows = read_csv_rows(COMPOUND_LINEAGE_EDGES_PATH) if COMPOUND_LINEAGE_EDGES_PATH.is_file() else []
    evidence_rows = read_csv_rows(COMPOUND_LINEAGE_EVIDENCE_PATH) if COMPOUND_LINEAGE_EVIDENCE_PATH.is_file() else []
    activity_rows = read_csv_rows(COMPOUND_ACTIVITIES_PATH) if COMPOUND_ACTIVITIES_PATH.is_file() else []
    if paper_id is not None:
        entity_rows = [row for row in entity_rows if row.get("paper_id") == paper_id]
        edge_rows = [row for row in edge_rows if row.get("paper_id") == paper_id]
        evidence_rows = [row for row in evidence_rows if row.get("paper_id") == paper_id]
        activity_rows = [row for row in activity_rows if row.get("paper_id") == paper_id]

    entities: list[dict[str, object]] = []
    for row in entity_rows:
        item: dict[str, object] = dict(row)
        smiles = _complete_molecule_smiles(row.get("canonical_smiles"))
        item["canonical_smiles"] = smiles or "--"
        item["structure_image_url"] = _molecule_pair_structure_image(smiles, "entity") if smiles else ""
        item["compound_object_ids"] = [
            value.strip() for value in str(row.get("compound_object_ids", "")).split("|")
            if value.strip() not in {"", "--"}
        ]
        entities.append(item)

    evidence: list[dict[str, object]] = []
    for row in evidence_rows:
        item = dict(row)
        item["page"] = _integer(row.get("page"))
        item["source_object_ids"] = [
            value.strip() for value in str(row.get("source_object_ids", "")).split("|")
            if value.strip() not in {"", "--"}
        ]
        evidence.append(item)
    activities: list[dict[str, object]] = []
    for row in activity_rows:
        item = dict(row)
        item["page"] = _integer(row.get("page")) if str(row.get("page", "")) not in {"", "--"} else 0
        activities.append(item)

    entities_by_id = {str(row.get("compound_entity_id", "")): row for row in entities}
    evidence_by_edge: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in evidence:
        evidence_by_edge[str(row.get("lineage_edge_id", ""))].append(row)
    activities_by_entity: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in activities:
        activities_by_entity[str(row.get("compound_entity_id", ""))].append(row)

    edges: list[dict[str, object]] = []
    for row in edge_rows:
        item = dict(row)
        edge_id = str(row.get("lineage_edge_id", ""))
        parent_id = str(row.get("parent_entity_id", ""))
        derived_id = str(row.get("derived_entity_id", ""))
        root_id = str(row.get("root_template_entity_id", ""))
        item["page"] = min(
            (int(evidence_row.get("page", 0)) for evidence_row in evidence_by_edge[edge_id] if int(evidence_row.get("page", 0)) > 0),
            default=0,
        )
        item["iteration_depth"] = _integer(row.get("iteration_depth"))
        item["pair_eligible"] = str(row.get("pair_eligible", "")).casefold() == "yes"
        item["root_template"] = entities_by_id.get(root_id)
        item["parent"] = entities_by_id.get(parent_id)
        item["derived"] = entities_by_id.get(derived_id)
        item["evidence"] = evidence_by_edge[edge_id]
        item["parent_activities"] = activities_by_entity.get(parent_id, [])
        item["derived_activities"] = activities_by_entity.get(derived_id, [])
        edges.append(item)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in edges:
        grouped[str(edge.get("lineage_id", ""))].append(edge)
    lineages = []
    for lineage_id, lineage_edges in sorted(grouped.items()):
        lineage_edges.sort(key=lambda edge: (int(edge.get("iteration_depth", 0)), str(edge.get("derived_label", ""))))
        root = next((edge.get("root_template") for edge in lineage_edges if edge.get("root_template")), None)
        lineages.append({
            "lineage_id": lineage_id,
            "root_template": root,
            "edges": lineage_edges,
            "edge_count": len(lineage_edges),
            "pair_eligible_count": sum(bool(edge.get("pair_eligible")) for edge in lineage_edges),
            "unresolved_edge_count": sum(edge.get("relation_status") == "unresolved" for edge in lineage_edges),
        })
    summary = read_json(COMPOUND_LINEAGE_SUMMARY_PATH) if COMPOUND_LINEAGE_SUMMARY_PATH.is_file() else {}
    return {
        "summary": summary,
        "entities": entities,
        "edges": edges,
        "evidence": evidence,
        "activities": activities,
        "lineages": lineages,
    }


def _paper_records() -> list[dict[str, object]]:
    """Aggregate the pipeline into one record per paper in the corpus manifest."""
    manifest = read_csv_rows(PAPER_FILES["manifest"])
    documents = {row.get("paper_id", ""): row for row in read_csv_rows(PAPER_FILES["documents"])}
    evidence_counts = Counter(row.get("paper_id", "") for row in read_csv_rows(PAPER_FILES["evidence"]))
    candidate_counts = Counter(row.get("paper_id", "") for row in read_csv_rows(PAPER_FILES["candidates"]))
    explicit_counts = Counter(row.get("paper_id", "") for row in read_csv_rows(PAPER_FILES["explicit"]))
    explicit_by_visual_id = {
        row.get("visual_review_id", ""): row
        for row in read_csv_rows(PAPER_FILES["explicit"])
        if row.get("visual_review_id")
    }
    structure_counts = Counter(
        explicit_by_visual_id.get(row.get("visual_review_id", ""), {}).get("paper_id", "")
        for row in read_csv_rows(PAPER_FILES["structures"])
    ) if PAPER_FILES["structures"].is_file() else Counter()
    molecule_objects = load_first_page_molecule_objects().get("objects", [])
    if not isinstance(molecule_objects, list):
        molecule_objects = []
    molecule_objects_by_paper: dict[str, list[dict[str, object]]] = {}
    for molecule_object in molecule_objects:
        if isinstance(molecule_object, dict):
            molecule_objects_by_paper.setdefault(str(molecule_object.get("paper_id", "")), []).append(molecule_object)
    lineage_snapshot = load_compound_lineages()
    lineage_edges = lineage_snapshot.get("edges", [])
    if not isinstance(lineage_edges, list):
        lineage_edges = []
    lineage_edges_by_paper: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in lineage_edges:
        if isinstance(edge, dict):
            lineage_edges_by_paper[str(edge.get("paper_id", ""))].append(edge)
    overrides = load_review_overrides()
    records: list[dict[str, object]] = []
    for row in manifest:
        paper_id = row.get("paper_id", "")
        document = documents.get(paper_id, {})
        doi = document.get("doi", "")
        explicit_paths = explicit_counts.get(paper_id, 0)
        candidate_count = candidate_counts.get(paper_id, 0)
        evidence_count = evidence_counts.get(paper_id, 0)
        workflow_status = _paper_status(
            explicit_paths=explicit_paths,
            candidate_count=candidate_count,
            evidence_count=evidence_count,
        )
        override = overrides.get(paper_id, {})
        title_override = str(override.get("title_override", ""))
        paper_molecule_objects = molecule_objects_by_paper.get(paper_id, [])
        paper_lineage_edges = lineage_edges_by_paper.get(paper_id, [])
        records.append(
            {
                "paper_id": paper_id,
                "title": document.get("title_guess") or row.get("title_guess", ""),
                "title_source": "review_override" if title_override else ("text_index" if document.get("title_guess") else "manifest"),
                "title_original": document.get("title_guess") or row.get("title_guess", ""),
                "doi": doi,
                "year": document.get("filename_year") or row.get("filename_year", ""),
                "source_folder": document.get("source_folder") or row.get("source_folder", ""),
                "filename": document.get("filename") or row.get("filename", ""),
                "source_pdf": document.get("source_pdf") or row.get("source_pdf", ""),
                "page_count": _integer(document.get("page_count")),
                "text_characters": _integer(document.get("text_characters")),
                "text_status": document.get("text_status", "not_indexed"),
                "evidence_count": evidence_count,
                "candidate_count": candidate_count,
                "explicit_path_count": explicit_paths,
                "structure_path_count": structure_counts.get(doi, 0),
                "molecule_object_count": len(paper_molecule_objects),
                "molecule_record_count": len(paper_molecule_objects),
                "molecule_pair_count": sum(bool(edge.get("pair_eligible")) for edge in paper_lineage_edges),
                "lineage_count": len({str(edge.get("lineage_id", "")) for edge in paper_lineage_edges}),
                "lineage_edge_count": len(paper_lineage_edges),
                "molecule_candidate_count": sum(
                    str(item.get("canonical_smiles", "")).strip() not in {"", "--"}
                    or str((item.get("attachment_inference") or {}).get("assembled_smiles", "")).strip() not in {"", "--"}
                    for item in paper_molecule_objects
                ),
                "workflow_status": workflow_status,
                "workflow_status_label": _paper_status_label(workflow_status),
                "review_status": str(override.get("review_status", "unreviewed")),
                "title_override": title_override,
                "correction_note": str(override.get("correction_note", "")),
                "review_note": str(override.get("review_note", "")),
                "review_updated_at": str(override.get("updated_at", "")),
            }
        )
        if title_override:
            records[-1]["title"] = title_override
    return records


def load_papers(
    *,
    query: str = "",
    status: str = "all",
    page: int = 1,
    page_size: int = PAPER_PAGE_SIZE,
    review_status: str = "all",
) -> dict[str, object]:
    """Return a paginated, one-record-per-paper catalog."""
    records = _paper_records()
    needle = query.strip().casefold()
    if needle:
        records = [record for record in records if needle in _searchable_text(record)]
    if status == "lineage":
        records = [record for record in records if record["lineage_edge_count"] > 0]
    elif status != "all":
        records = [record for record in records if record["workflow_status"] == status]
    if review_status != "all":
        if review_status not in PAPER_REVIEW_STATUSES:
            raise ValueError("review_status is invalid")
        records = [record for record in records if record["review_status"] == review_status]
    page_size = max(1, min(int(page_size), 1000))
    page_count = max(1, math.ceil(len(records) / page_size))
    page = max(1, min(int(page), page_count))
    start = (page - 1) * page_size
    return {
        "items": records[start : start + page_size],
        "total": len(records),
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "default_page_size": PAPER_PAGE_SIZE,
        "status": status,
        "review_status": review_status,
    }


def _normalize_evidence(row: dict[str, str], index: int) -> dict[str, object]:
    return {
        "id": f"{row.get('paper_id', '')}:evidence:{index}",
        "paper_id": row.get("paper_id", ""),
        "doi": row.get("doi", ""),
        "page": _integer(row.get("page")),
        "evidence_type": row.get("evidence_type", ""),
        "compound_mentions": row.get("compound_mentions", ""),
        "activity_mentions": row.get("activity_mentions", ""),
        "evidence_text": row.get("evidence_text", ""),
        "review_status": row.get("review_status", "unreviewed"),
        "confidence": _number(row.get("confidence")),
        "source_pdf": row.get("source_pdf", ""),
    }


def _normalize_candidate(row: dict[str, str]) -> dict[str, object]:
    return {
        "id": row.get("path_candidate_id", ""),
        "path_candidate_id": row.get("path_candidate_id", ""),
        "paper_id": row.get("paper_id", ""),
        "doi": row.get("doi", ""),
        "page": _integer(row.get("page")),
        "parent_compound": row.get("parent_compound", ""),
        "derived_compound": row.get("derived_compound", ""),
        "from_group": row.get("reported_from_group", ""),
        "to_group": row.get("reported_to_group", ""),
        "relation_type": row.get("relation_type", ""),
        "confidence": row.get("confidence", ""),
        "activity": row.get("activity_mentions", ""),
        "evidence_text": row.get("evidence_text", ""),
        "structure_review_status": row.get("structure_review_status", ""),
        "review_status": row.get("review_status", "unreviewed"),
        "source_pdf": row.get("source_pdf", ""),
    }


def _normalize_structure(row: dict[str, str]) -> dict[str, object]:
    return {
        "visual_review_id": row.get("visual_review_id", ""),
        "page": _integer(row.get("page")),
        "page_references": row.get("page_references", ""),
        "parent_compound": row.get("parent_compound", ""),
        "derived_compound": row.get("derived_compound", ""),
        "parent_smiles": row.get("parent_smiles", ""),
        "derived_smiles": row.get("derived_smiles", ""),
        "parent_canonical_smiles": row.get("parent_canonical_smiles", ""),
        "derived_canonical_smiles": row.get("derived_canonical_smiles", ""),
        "parent_rdkit_status": row.get("parent_rdkit_status", "not_run"),
        "derived_rdkit_status": row.get("derived_rdkit_status", "not_run"),
        "structure_source": row.get("structure_source", ""),
        "confirmation_status": row.get("confirmation_status", ""),
        "path_status": row.get("path_status", ""),
        "review_status": row.get("review_status", "unreviewed"),
        "parent_image_url": _asset_url("structures", Path(row.get("structure_image_parent", "")).name),
        "derived_image_url": _asset_url("structures", Path(row.get("structure_image_derived", "")).name),
        "path_image_url": _asset_url("structures", Path(row.get("path_panel_image", "")).name),
        "notes": row.get("notes", ""),
    }


def _review_item(
    *,
    evidence: dict[str, object] | None,
    candidate: dict[str, object] | None,
    path: dict[str, object] | None,
    structure: dict[str, object] | None,
    overrides: dict[str, object],
) -> dict[str, object]:
    """Combine one evidence statement with every downstream record it owns."""
    evidence = dict(evidence) if evidence else None
    candidate = dict(candidate) if candidate else None
    path = dict(path) if path else None
    structure = dict(structure) if structure else None
    if path:
        path["proposals"] = list(path.get("proposals", []))
    proposals = path.get("proposals", []) if path else []
    default_status = str(
        overrides.get("review_status")
        or (candidate or {}).get("review_status")
        or (path or {}).get("review_status")
        or (evidence or {}).get("review_status")
        or "unreviewed"
    )
    review_item_id = str(
        (candidate or {}).get("path_candidate_id")
        or (evidence or {}).get("id")
        or "review-item"
    )
    activity = (
        (candidate or {}).get("activity")
        or (evidence or {}).get("activity_mentions")
        or (path or {}).get("activity")
        or None
    )
    item = {
        "review_item_id": review_item_id,
        "source_kind": "candidate" if candidate else "evidence",
        "paper_id": (evidence or candidate or path or {}).get("paper_id", ""),
        "page": (evidence or candidate or path or {}).get("page"),
        "page_references": (path or {}).get("page_references") or None,
        "compound_mentions": (evidence or {}).get("compound_mentions") or None,
        "activity": activity,
        "evidence": evidence,
        "candidate": candidate,
        "path": path,
        "structure": structure,
        "proposals": proposals,
        "review_status": default_status,
        "review_note": str(overrides.get("review_note", "")),
        "correction_note": str(overrides.get("correction_note", "")),
    }
    return _apply_review_item_content(item, overrides)


def load_structure_ocr_proposals() -> dict[str, list[dict[str, object]]]:
    """Load page-crop OCSR proposals keyed by the source review-item IDs."""
    if not STRUCTURE_OCR_PROPOSALS_PATH.is_file():
        return {}
    by_item: dict[str, list[dict[str, object]]] = {}
    for row in read_csv_rows(STRUCTURE_OCR_PROPOSALS_PATH):
        item_ids = [value.strip() for value in row.get("source_queue_item_ids", "").split("|") if value.strip()]
        proposal = {
            "candidate_id": row.get("candidate_id", ""),
            "page_candidate_id": row.get("page_candidate_id", ""),
            "paper_id": row.get("paper_id", ""),
            "doi": row.get("doi", ""),
            "source_pdf": row.get("source_pdf", ""),
            "page": _integer(row.get("page")),
            "region_kind": row.get("region_kind", ""),
            "crop_url": _asset_url("structure-ocr-crops", Path(row.get("crop_path", "")).name),
            "source_queue_item_ids": item_ids,
            "compound_ids": row.get("compound_ids", ""),
            "raw_smiles": row.get("raw_smiles", ""),
            "mean_token_confidence": row.get("mean_token_confidence", ""),
            "min_token_confidence": row.get("min_token_confidence", ""),
            "inference_status": row.get("inference_status", ""),
            "inference_error": row.get("inference_error", ""),
            "rdkit_status": row.get("rdkit_status", ""),
            "canonical_smiles": row.get("canonical_smiles", ""),
            "model_version": row.get("model_version", ""),
            "proposal_quality": row.get("proposal_quality", ""),
            "review_status": row.get("review_status", "proposal_requires_human_review"),
            "source_evidence_page_url": _asset_url("pages", ""),
        }
        for item_id in item_ids:
            by_item.setdefault(item_id, []).append(proposal)
    return by_item


def load_first_page_fragment_review() -> dict[str, object]:
    """Load the chemistry-first, fragment-aware first-page review snapshot."""
    if not FIRST_PAGE_FRAGMENT_REVIEW_PATH.is_file():
        return {"summary": {}, "papers": [], "items": []}
    rows = read_csv_rows(FIRST_PAGE_FRAGMENT_REVIEW_PATH)
    summary = read_json(FIRST_PAGE_FRAGMENT_SUMMARY_PATH) if FIRST_PAGE_FRAGMENT_SUMMARY_PATH.is_file() else {}
    items: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        crop_path = str(row.get("crop_path", "")).strip()
        item["crop_url"] = (
            _asset_url("structure-ocr-crops", Path(crop_path).name)
            if crop_path and crop_path != "--" else ""
        )
        item["source_queue_item_ids"] = [
            value.strip() for value in str(row.get("source_queue_item_ids", "")).split("|")
            if value.strip() and value.strip() != "--"
        ]
        item["linked_review_item_ids"] = [
            value.strip() for value in str(row.get("linked_review_item_ids", "")).split("|")
            if value.strip() and value.strip() != "--"
        ]
        item["page"] = _integer(row.get("page"))
        items.append(item)
    papers = summary.get("paper_summaries", [])
    if not isinstance(papers, list):
        papers = []
    molecule_review = load_first_page_molecule_objects(papers)
    return {
        "summary": summary, "papers": papers, "items": items,
        "molecule_summary": molecule_review["summary"],
        "molecule_papers": molecule_review["papers"],
        "molecule_objects": molecule_review["objects"],
    }


def _empty_first_page_fragment_inference() -> dict[str, object]:
    return {
        "fragment_smiles": "--",
        "fragment_smiles_status": "--",
        "attachment_count": "--",
        "attachment_status": "--",
        "assembled_smiles": "--",
        "assembly_status": "--",
        "assembly_method": "--",
        "source_evidence": "--",
        "source_file": "--",
        "source_locator": "--",
        "inference_note": "--",
        "confidence": "--",
        "review_status": "--",
        "crop_url": "",
    }


def load_first_page_fragment_inferences() -> dict[str, object]:
    """Load attachment reasoning as a read-only supplement to molecule objects."""
    if not FIRST_PAGE_FRAGMENT_INFERENCE_PATH.is_file():
        return {"summary": {}, "rows": [], "by_object_id": {}}
    summary = (
        read_json(FIRST_PAGE_FRAGMENT_INFERENCE_SUMMARY_PATH)
        if FIRST_PAGE_FRAGMENT_INFERENCE_SUMMARY_PATH.is_file() else {}
    )
    rows: list[dict[str, object]] = []
    for row in read_csv_rows(FIRST_PAGE_FRAGMENT_INFERENCE_PATH):
        item = dict(_empty_first_page_fragment_inference())
        item.update(row)
        for key in (
            "object_id", "paper_id", "doi", "candidate_id", "object_type", "compound_label",
            "crop_path", "parent_object_id", "attachment_points", "fragment_smiles",
            "fragment_smiles_status", "attachment_status", "assembled_smiles", "assembly_status",
            "assembly_method", "source_evidence", "source_file", "source_locator", "inference_note",
            "confidence", "review_status", "annotation_version", "updated_at",
        ):
            if not str(item.get(key, "")).strip():
                item[key] = "--"
        crop_path = str(row.get("crop_path", "")).strip()
        item["crop_url"] = (
            _asset_url("molecule-review-crops", Path(crop_path).name)
            if crop_path and crop_path != "--" else ""
        )
        raw_attachment_count = str(row.get("attachment_count", "")).strip()
        item["attachment_count"] = _integer(raw_attachment_count) if raw_attachment_count not in {"", "--"} else "--"
        item["paper_rank"] = _integer(row.get("paper_rank"))
        item["page"] = _integer(row.get("page"))
        rows.append(item)

    by_object_id = {
        str(row["object_id"]): row
        for row in rows
        if str(row.get("object_id", "")) not in {"", "--"}
    }
    return {"summary": summary, "rows": rows, "by_object_id": by_object_id}


def load_first_page_molecule_objects(base_papers: list[object] | None = None) -> dict[str, object]:
    """Load object-level structure localization without promoting any SMILES."""
    if not FIRST_PAGE_MOLECULE_OBJECTS_PATH.is_file():
        return {"summary": {}, "papers": base_papers or [], "objects": []}
    rows = read_csv_rows(FIRST_PAGE_MOLECULE_OBJECTS_PATH)
    summary = read_json(FIRST_PAGE_MOLECULE_SUMMARY_PATH) if FIRST_PAGE_MOLECULE_SUMMARY_PATH.is_file() else {}
    fragment_inferences = load_first_page_fragment_inferences()
    inference_summary = fragment_inferences.get("summary", {})
    inference_rows = fragment_inferences.get("rows", [])
    inference_by_object_id = fragment_inferences.get("by_object_id", {})
    if not isinstance(inference_summary, dict):
        inference_summary = {}
    if not isinstance(inference_rows, list):
        inference_rows = []
    if not isinstance(inference_by_object_id, dict):
        inference_by_object_id = {}
    attachment_status_counts = inference_summary.get("attachment_status_counts", {})
    assembly_status_counts = inference_summary.get("assembly_status_counts", {})
    if not isinstance(attachment_status_counts, dict):
        attachment_status_counts = dict(Counter(str(row.get("attachment_status", "--")) for row in inference_rows))
    if not isinstance(assembly_status_counts, dict):
        assembly_status_counts = dict(Counter(str(row.get("assembly_status", "--")) for row in inference_rows))
    summary = {
        **summary,
        "fragment_inference_rows": _integer(inference_summary.get("object_rows"), len(inference_rows)),
        "fragment_smiles_rows": _integer(
            inference_summary.get("fragment_smiles_rows"),
        ) or sum(str(row.get("fragment_smiles", "--")) not in {"", "--"} for row in inference_rows),
        "assembled_candidate_rows": _integer(
            inference_summary.get("assembled_candidate_rows"),
        ) or sum(str(row.get("assembled_smiles", "--")) not in {"", "--"} for row in inference_rows),
        "attachment_status_counts": attachment_status_counts,
        "assembly_status_counts": assembly_status_counts,
    }
    proposal_rows = read_csv_rows(FIRST_PAGE_MOLECULE_PROPOSALS_PATH) if FIRST_PAGE_MOLECULE_PROPOSALS_PATH.is_file() else []
    if proposal_rows:
        summary = {
            **summary,
            "ocr_attempted": len(proposal_rows),
            "ocr_inference_ok": sum(row.get("inference_status") == "ok" for row in proposal_rows),
            "ocr_inference_errors": sum(row.get("inference_status") == "error" for row in proposal_rows),
            "ocr_rdkit_valid": sum(row.get("rdkit_status") == "valid" for row in proposal_rows),
            "ocr_rdkit_invalid": sum(row.get("rdkit_status") == "invalid" for row in proposal_rows),
        }
    proposal_by_id = {row.get("object_id", ""): row for row in proposal_rows if row.get("object_id")}
    objects: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        proposal = proposal_by_id.get(row.get("object_id", ""), {})
        for key in ("inference_status", "inference_error", "mean_token_confidence", "min_token_confidence", "proposal_quality", "model_version", "heuristic_primary_component_smiles"):
            if proposal.get(key):
                item[key] = proposal[key]
        source_crop = str(row.get("source_crop_path", "")).strip()
        crop_path = str(row.get("crop_path", "")).strip()
        item["source_crop_url"] = (
            _asset_url("structure-ocr-crops", Path(source_crop).name)
            if source_crop and source_crop != "--" else ""
        )
        item["crop_url"] = (
            _asset_url("molecule-review-crops", Path(crop_path).name)
            if crop_path and crop_path != "--" else ""
        )
        item["paper_rank"] = _integer(row.get("paper_rank"))
        item["page"] = _integer(row.get("page"))
        attachment_inference = inference_by_object_id.get(row.get("object_id", ""))
        item["attachment_inference"] = (
            dict(attachment_inference)
            if isinstance(attachment_inference, dict)
            else _empty_first_page_fragment_inference()
        )
        objects.append(item)

    grouped: dict[str, list[dict[str, object]]] = {}
    for item in objects:
        grouped.setdefault(str(item.get("paper_id", "")), []).append(item)
    papers: list[dict[str, object]] = []
    for base in base_papers or []:
        paper = dict(base) if isinstance(base, dict) else {"paper_id": "", "paper_rank": ""}
        paper_id = str(paper.get("paper_id", ""))
        paper_objects = grouped.get(paper_id, [])
        paper.update({
            "object_count": len(paper_objects),
            "isolated_ocsr_count": sum(item.get("smiles_source") == "isolated_object_pending_ocsr" for item in paper_objects),
            "fragment_count": sum(item.get("object_type") in {"shared_scaffold", "replacement_fragment", "linker_fragment", "variable_site"} for item in paper_objects),
            "excluded_count": sum(item.get("object_type") in {"non_structure_region", "three_d_structure_evidence"} for item in paper_objects),
            "requires_split_count": sum(item.get("smiles_source") in {"series_member_shared_region", "excluded_until_local_split", "attachment_point_notation_only", "local_boundary_requires_review"} for item in paper_objects),
        })
        papers.append(paper)
    if not papers:
        papers = list(grouped.values())
    return {"summary": summary, "papers": papers, "objects": objects}


def _apply_review_item_content(
    item: dict[str, object], overrides: dict[str, object]
) -> dict[str, object]:
    """Overlay editable content onto the normalized nested records."""
    evidence = item.get("evidence")
    candidate = item.get("candidate")
    path = item.get("path")
    structure = item.get("structure")
    molecule_pair = item.get("molecule_pair")
    content = {key: value for key, value in overrides.items() if key in PAPER_REVIEW_CONTENT_FIELDS}
    if content and candidate is None and any(
        key in content for key in {"parent_compound", "derived_compound", "reported_from_group", "reported_to_group", "relation_type"}
    ):
        candidate = {
            "id": item["review_item_id"], "path_candidate_id": item["review_item_id"],
            "paper_id": item.get("paper_id", ""), "doi": "", "page": item.get("page", 0),
            "parent_compound": "", "derived_compound": "", "from_group": "", "to_group": "",
            "relation_type": "", "confidence": "", "activity": "", "evidence_text": "",
            "structure_review_status": "", "review_status": "unreviewed", "source_pdf": "",
        }
        item["candidate"] = candidate
        item["source_kind"] = "candidate"
    if content and structure is None and item.get("source_kind") != "molecule_pair" and any(
        key in content for key in {"parent_smiles", "derived_smiles", "parent_canonical_smiles", "derived_canonical_smiles"}
    ):
        structure = {
            "visual_review_id": (path or {}).get("visual_review_id", ""),
            "page": item.get("page", 0), "page_references": item.get("page_references", ""),
            "parent_compound": "", "derived_compound": "", "parent_smiles": "",
            "derived_smiles": "", "parent_canonical_smiles": "", "derived_canonical_smiles": "",
            "parent_rdkit_status": "not_run", "derived_rdkit_status": "not_run",
            "structure_source": "manual_review", "confirmation_status": "manual_pending",
            "path_status": "manual_pending", "review_status": "unreviewed",
            "parent_image_url": "", "derived_image_url": "", "path_image_url": "", "notes": "",
        }
        item["structure"] = structure

    def set_value(record: object, key: str, value: object) -> None:
        if isinstance(record, dict):
            record[key] = value

    for key, value in content.items():
        if key == "page":
            item["page"] = value
            set_value(evidence, "page", value)
            set_value(candidate, "page", value)
            set_value(path, "page", value)
            set_value(structure, "page", value)
        elif key == "page_references":
            item["page_references"] = value
            set_value(path, "page_references", value)
            set_value(structure, "page_references", value)
        elif key == "compound_mentions":
            item["compound_mentions"] = value
            set_value(evidence, "compound_mentions", value)
        elif key == "activity":
            item["activity"] = value
            set_value(evidence, "activity_mentions", value)
            set_value(candidate, "activity", value)
            set_value(path, "activity", value)
        elif key == "evidence_text":
            set_value(evidence, "evidence_text", value)
            set_value(candidate, "evidence_text", value)
            set_value(path, "evidence_text", value)
        elif key == "parent_compound":
            set_value(candidate, "parent_compound", value)
            set_value(path, "parent_compound", value)
            set_value(structure, "parent_compound", value)
        elif key == "derived_compound":
            set_value(candidate, "derived_compound", value)
            set_value(path, "derived_compound", value)
            set_value(structure, "derived_compound", value)
        elif key == "root_template":
            set_value(molecule_pair, "root_template_label", value)
            set_value(item.get("lineage_edge"), "root_template_label", value)
        elif key == "reported_from_group":
            set_value(candidate, "from_group", value)
            set_value(path, "from_group", value)
        elif key == "reported_to_group":
            set_value(candidate, "to_group", value)
            set_value(path, "to_group", value)
        elif key in {"relation_type", "structure_review_status"}:
            set_value(candidate, key, value)
        elif key in {"path_status", "structure_confirmation_status"}:
            path_key = "confirmation_status" if key == "structure_confirmation_status" else key
            set_value(path, key, value)
            set_value(structure, path_key, value)
        elif key in {"parent_smiles", "derived_smiles", "parent_canonical_smiles", "derived_canonical_smiles"}:
            if item.get("source_kind") == "molecule_pair" and isinstance(molecule_pair, dict):
                molecule_pair[key] = value
                if key in {"parent_smiles", "derived_smiles"} and not str(value or "").strip():
                    molecule_pair[f"{key.removesuffix('_smiles')}_canonical_smiles"] = "--"
            else:
                set_value(structure, key, value)
                if key == "parent_smiles" and isinstance(structure, dict) and not structure.get("parent_canonical_smiles"):
                    structure["parent_canonical_smiles"] = value
                if key == "derived_smiles" and isinstance(structure, dict) and not structure.get("derived_canonical_smiles"):
                    structure["derived_canonical_smiles"] = value
        elif key in {"fragment_smiles", "assembled_smiles", "attachment_status", "assembly_status", "inference_note"}:
            set_value(item.get("molecule_pair"), key, value)
    if isinstance(molecule_pair, dict):
        if molecule_pair.get("pair_kind") != "compound_optimization_lineage":
            if "derived_smiles" in content and "assembled_smiles" not in content:
                molecule_pair["assembled_smiles"] = content["derived_smiles"]
            elif "assembled_smiles" in content and "derived_smiles" not in content:
                molecule_pair["derived_smiles"] = content["assembled_smiles"]
        _refresh_molecule_pair_structures(molecule_pair)
    return item


def _apply_auto_fill(item: dict[str, object], auto_fill: Mapping[str, str] | None) -> dict[str, object]:
    """Attach automatic classifications without changing curated review values."""
    if not auto_fill:
        return item
    item["auto_fill"] = {
        "auto_fill_status": auto_fill.get("auto_fill_status", ""),
        "structure_representation_kind": auto_fill.get("structure_representation_kind", "none"),
        "structure_expression": auto_fill.get("structure_expression", ""),
        "attachment_points": auto_fill.get("attachment_points", ""),
        "structure_source": auto_fill.get("structure_source", ""),
        "structure_source_locator": auto_fill.get("structure_source_locator", ""),
        "auto_fill_source": auto_fill.get("auto_fill_source", ""),
    }
    structure = item.get("structure")
    if not isinstance(structure, dict) and auto_fill.get("structure_representation_kind") != "none":
        item["structure"] = {
            "visual_review_id": "",
            "page": item.get("page", 0),
            "page_references": item.get("page_references", ""),
            "parent_compound": item.get("candidate", {}).get("parent_compound", "") if isinstance(item.get("candidate"), dict) else "",
            "derived_compound": item.get("candidate", {}).get("derived_compound", "") if isinstance(item.get("candidate"), dict) else "",
            "parent_smiles": auto_fill.get("parent_smiles", ""),
            "derived_smiles": auto_fill.get("derived_smiles", ""),
            "parent_canonical_smiles": auto_fill.get("parent_canonical_smiles", ""),
            "derived_canonical_smiles": auto_fill.get("derived_canonical_smiles", ""),
            "parent_rdkit_status": "valid" if auto_fill.get("parent_canonical_smiles") else "not_run",
            "derived_rdkit_status": "valid" if auto_fill.get("derived_canonical_smiles") else "not_run",
            "structure_source": auto_fill.get("structure_source", ""),
            "confirmation_status": auto_fill.get("structure_confirmation_status", "needs_confirmation"),
            "path_status": item.get("path", {}).get("path_status", "candidate") if isinstance(item.get("path"), dict) else "candidate",
            "review_status": item.get("review_status", "unreviewed"),
            "parent_image_url": "",
            "derived_image_url": "",
            "path_image_url": "",
            "representation_kind": auto_fill.get("structure_representation_kind", "none"),
            "structure_expression": auto_fill.get("structure_expression", ""),
            "attachment_points": auto_fill.get("attachment_points", ""),
            "notes": auto_fill.get("structure_expression", ""),
        }
    elif isinstance(structure, dict):
        structure.setdefault("structure_expression", auto_fill.get("structure_expression", ""))
        structure.setdefault("representation_kind", auto_fill.get("structure_representation_kind", "none"))
        structure.setdefault("attachment_points", auto_fill.get("attachment_points", ""))
    return item


def _lineage_activity_text(rows: object) -> str:
    if not isinstance(rows, list):
        return "--"
    values = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric", "") or "").strip()
        value = str(row.get("value", "") or "").strip()
        if not metric or not value or value == "--":
            continue
        qualifier = str(row.get("qualifier", "") or "=").strip()
        unit = str(row.get("unit", "") or "").strip()
        values.append(" ".join(part for part in (metric, qualifier, value, unit if unit != "--" else "") if part))
    return "; ".join(values) or "--"


def _lineage_pair_review_items(
    paper_id: str,
    lineage_edges: list[dict[str, object]],
    objects: list[dict[str, object]],
    item_overrides: dict[str, object],
    deleted_items: set[str],
    existing_review_item_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """Create complete-molecule review pairs from eligible lineage edges only."""
    existing_review_item_ids = existing_review_item_ids or set()
    object_by_id = {str(row.get("object_id", "")): row for row in objects}
    items: list[dict[str, object]] = []
    for edge in lineage_edges:
        if not bool(edge.get("pair_eligible")):
            continue
        edge_id = str(edge.get("lineage_edge_id", ""))
        if not edge_id or edge_id in deleted_items or edge_id in existing_review_item_ids:
            continue
        parent = edge.get("parent") if isinstance(edge.get("parent"), dict) else {}
        derived = edge.get("derived") if isinstance(edge.get("derived"), dict) else {}
        root = edge.get("root_template") if isinstance(edge.get("root_template"), dict) else {}
        evidence_rows = edge.get("evidence") if isinstance(edge.get("evidence"), list) else []
        evidence_row = evidence_rows[0] if evidence_rows and isinstance(evidence_rows[0], dict) else {}
        parent_object_ids = parent.get("compound_object_ids") if isinstance(parent.get("compound_object_ids"), list) else []
        derived_object_ids = derived.get("compound_object_ids") if isinstance(derived.get("compound_object_ids"), list) else []
        parent_object = object_by_id.get(str(parent_object_ids[0]), {}) if parent_object_ids else {}
        derived_object = object_by_id.get(str(derived_object_ids[0]), {}) if derived_object_ids else {}
        parent_label = str(parent.get("display_label") or edge.get("parent_label") or "--")
        derived_label = str(derived.get("display_label") or edge.get("derived_label") or "--")
        root_label = str(root.get("display_label") or edge.get("root_template_label") or "--")
        page = _integer(evidence_row.get("page") or edge.get("page"))
        evidence_text = str(evidence_row.get("evidence_text") or "--")
        activity = _lineage_activity_text(edge.get("derived_activities"))
        override = item_overrides.get(edge_id, {})
        if not isinstance(override, dict):
            override = {}
        evidence = {
            "id": str(evidence_row.get("lineage_evidence_id") or f"{edge_id}:evidence"),
            "paper_id": paper_id,
            "doi": str(edge.get("doi", "")),
            "page": page,
            "evidence_type": "compound_lineage",
            "compound_mentions": f"{parent_label}; {derived_label}",
            "activity_mentions": activity,
            "evidence_text": evidence_text,
            "review_status": str(evidence_row.get("review_status") or "unreviewed"),
            "confidence": str(edge.get("relation_confidence") or "--"),
            "source_pdf": "",
        }
        candidate = {
            "id": edge_id,
            "path_candidate_id": edge_id,
            "paper_id": paper_id,
            "doi": str(edge.get("doi", "")),
            "page": page,
            "parent_compound": parent_label,
            "derived_compound": derived_label,
            "from_group": str(edge.get("from_group") or "--"),
            "to_group": str(edge.get("to_group") or "--"),
            "relation_type": str(edge.get("relation_type") or "direct_optimization"),
            "confidence": str(edge.get("relation_confidence") or "--"),
            "activity": activity,
            "evidence_text": evidence_text,
            "structure_review_status": "complete_structures_resolved",
            "review_status": str(edge.get("review_status") or "unreviewed"),
            "source_pdf": "",
        }
        molecule_pair = {
            "pair_id": edge_id,
            "pair_kind": "compound_optimization_lineage",
            "pair_status": str(edge.get("relation_status") or "requires_relation_review"),
            "lineage_id": str(edge.get("lineage_id") or "--"),
            "lineage_edge_id": edge_id,
            "root_template_entity_id": str(edge.get("root_template_entity_id") or "--"),
            "root_template_label": root_label,
            "parent_entity_id": str(edge.get("parent_entity_id") or "--"),
            "derived_entity_id": str(edge.get("derived_entity_id") or "--"),
            "relation_status": str(edge.get("relation_status") or "--"),
            "relation_confidence": str(edge.get("relation_confidence") or "--"),
            # Object links are supporting image evidence, never the pair identity.
            "parent_object_id": "--",
            "derived_object_id": "--",
            "parent_object": parent_object,
            "derived_object": derived_object,
            "parent_crop_url": str(parent_object.get("crop_url", "")),
            "derived_crop_url": str(derived_object.get("crop_url", "")),
            "fragment_smiles": "--",
            "parent_smiles": str(parent.get("canonical_smiles") or "--"),
            "derived_smiles": str(derived.get("canonical_smiles") or "--"),
            "parent_canonical_smiles": str(parent.get("canonical_smiles") or "--"),
            "derived_canonical_smiles": str(derived.get("canonical_smiles") or "--"),
            "assembled_smiles": "--",
            "attachment_status": "not_applicable_lineage_pair",
            "assembly_status": "complete_structures_resolved",
            "inference_note": evidence_text,
            "review_status": str(edge.get("review_status") or "unreviewed"),
        }
        item = {
            "review_item_id": edge_id,
            "source_kind": "molecule_pair",
            "paper_id": paper_id,
            "page": page,
            "page_references": str(evidence_row.get("source_locator") or "--"),
            "compound_mentions": evidence["compound_mentions"],
            "activity": activity,
            "evidence": evidence,
            "candidate": candidate,
            "path": {
                "path_status": str(edge.get("relation_status") or "--"),
                "structure_confirmation_status": "complete_structures_resolved",
                "structure_review_status": "complete_structures_resolved",
            },
            "structure": None,
            "proposals": [],
            "molecule_pair": molecule_pair,
            "lineage_edge": edge,
            "review_status": str(override.get("review_status", edge.get("review_status") or "unreviewed")),
            "review_note": str(override.get("review_note", "")),
            "correction_note": str(override.get("correction_note", "")),
        }
        _refresh_molecule_pair_structures(molecule_pair)
        items.append(_apply_review_item_content(item, override))
    return items


def _unified_review_items(
    *, paper_id: str, evidence: list[dict[str, object]],
    candidates: list[dict[str, object]], explicit_paths: list[dict[str, object]],
    structures: list[dict[str, object]], overrides: dict[str, object],
    molecule_objects: list[dict[str, object]] | None = None,
    lineage_edges: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    auto_fill_rows = load_auto_fill_rows()
    structure_ocr_by_item = load_structure_ocr_proposals()
    paths_by_candidate = {
        str(path.get("path_candidate_id")): path
        for path in explicit_paths
        if path.get("path_candidate_id")
    }
    structures_by_path = {
        str(structure.get("visual_review_id")): structure
        for structure in structures
        if structure.get("visual_review_id")
    }
    evidence_by_key: dict[tuple[object, object], list[dict[str, object]]] = {}
    for statement in evidence:
        key = (statement.get("page"), statement.get("evidence_text"))
        evidence_by_key.setdefault(key, []).append(statement)
    item_overrides = overrides.get("review_items", {})
    if not isinstance(item_overrides, dict):
        item_overrides = {}
    deleted_items = overrides.get("deleted_items", [])
    if not isinstance(deleted_items, list):
        deleted_items = []
    deleted_items = {str(value) for value in deleted_items}
    items: list[dict[str, object]] = []
    matched_evidence_keys: set[tuple[object, object]] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("path_candidate_id", ""))
        if candidate_id in deleted_items:
            continue
        key = (candidate.get("page"), candidate.get("evidence_text"))
        statement = evidence_by_key.get(key, [None])[0]
        if statement is not None:
            matched_evidence_keys.add(key)
        path = paths_by_candidate.get(candidate_id)
        structure = structures_by_path.get(str(path.get("visual_review_id"))) if path else None
        item_id = candidate_id or str((statement or {}).get("id", ""))
        item_override = item_overrides.get(item_id, {})
        if not isinstance(item_override, dict):
            item_override = {}
        item = _apply_auto_fill(_review_item(
            evidence=statement, candidate=candidate, path=path,
            structure=structure, overrides=item_override,
        ), auto_fill_rows.get(item_id))
        item["proposals"] = list(item.get("proposals", [])) + structure_ocr_by_item.get(item_id, [])
        items.append(item)
    for statement in evidence:
        key = (statement.get("page"), statement.get("evidence_text"))
        item_id = str(statement.get("id", ""))
        if item_id in deleted_items:
            continue
        if key in matched_evidence_keys:
            continue
        item_override = item_overrides.get(item_id, {})
        if not isinstance(item_override, dict):
            item_override = {}
        items.append(_apply_auto_fill(_review_item(
            evidence=statement, candidate=None, path=None,
            structure=None, overrides=item_override,
        ), auto_fill_rows.get(item_id)))
    added_items = overrides.get("added_items", {})
    if isinstance(added_items, dict):
        for item_id, record in added_items.items():
            item_id = str(item_id)
            if item_id in deleted_items or not isinstance(record, dict):
                continue
            items.append(_manual_review_item(paper_id, item_id, record, item_overrides.get(item_id, {})))
    items.extend(_lineage_pair_review_items(
        paper_id, lineage_edges or [], molecule_objects or [], item_overrides, deleted_items,
        {str(item.get("review_item_id", "")) for item in items},
    ))
    return items


def _manual_review_item(
    paper_id: str, item_id: str, record: dict[str, object], override: object
) -> dict[str, object]:
    values = dict(record)
    if isinstance(override, dict):
        values.update(override)
    page = _integer(values.get("page"))
    evidence = {
        "id": f"{paper_id}:manual:evidence:{item_id}", "paper_id": paper_id,
        "doi": "", "page": page, "evidence_type": "manual_review",
        "compound_mentions": str(values.get("compound_mentions", "")),
        "activity_mentions": str(values.get("activity", "")),
        "evidence_text": str(values.get("evidence_text", "")),
        "review_status": str(values.get("review_status", "unreviewed")),
        "confidence": 0.0, "source_pdf": "",
    }
    candidate = {
        "id": item_id, "path_candidate_id": item_id, "paper_id": paper_id,
        "doi": "", "page": page,
        "parent_compound": str(values.get("parent_compound", "")),
        "derived_compound": str(values.get("derived_compound", "")),
        "from_group": str(values.get("reported_from_group", "")),
        "to_group": str(values.get("reported_to_group", "")),
        "relation_type": str(values.get("relation_type", "manual_review")),
        "confidence": "", "activity": str(values.get("activity", "")),
        "evidence_text": str(values.get("evidence_text", "")),
        "structure_review_status": str(values.get("structure_review_status", "manual_review")),
        "review_status": str(values.get("review_status", "unreviewed")), "source_pdf": "",
    }
    has_structure = any(values.get(key) for key in ("parent_smiles", "derived_smiles", "parent_canonical_smiles", "derived_canonical_smiles"))
    structure = {
        "visual_review_id": "", "page": page,
        "page_references": str(values.get("page_references", "")),
        "parent_compound": candidate["parent_compound"], "derived_compound": candidate["derived_compound"],
        "parent_smiles": str(values.get("parent_smiles", "")), "derived_smiles": str(values.get("derived_smiles", "")),
        "parent_canonical_smiles": str(values.get("parent_canonical_smiles", values.get("parent_smiles", ""))),
        "derived_canonical_smiles": str(values.get("derived_canonical_smiles", values.get("derived_smiles", ""))),
        "parent_rdkit_status": "not_run", "derived_rdkit_status": "not_run",
        "structure_source": "manual_review", "confirmation_status": "manual_pending",
        "path_status": "manual_pending", "review_status": str(values.get("review_status", "unreviewed")),
        "parent_image_url": "", "derived_image_url": "", "path_image_url": "", "notes": "",
    } if has_structure else None
    item = {
        "review_item_id": item_id, "source_kind": "manual", "paper_id": paper_id,
        "page": page, "page_references": str(values.get("page_references", "")) or None,
        "compound_mentions": str(values.get("compound_mentions", "")) or None,
        "activity": str(values.get("activity", "")) or None,
        "evidence": evidence, "candidate": candidate, "path": None, "structure": structure,
        "proposals": [], "review_status": str(values.get("review_status", "unreviewed")),
        "review_note": str(values.get("review_note", "")),
        "correction_note": str(values.get("correction_note", "")),
    }
    return _apply_review_item_content(item, values)


def _paper_progress(
    paper: dict[str, object], evidence_count: int, candidate_count: int,
    explicit_path_count: int, structure_count: int,
) -> list[dict[str, object]]:
    text_ready = paper.get("text_status") == "ok"
    structure_denominator = explicit_path_count * 2
    structure_count = structure_count * 2
    return [
        {"id": "text", "label": "Text extraction", "count": 1 if text_ready else 0, "denominator": 1, "status": "complete" if text_ready else "pending", "detail": paper.get("text_status", "not indexed")},
        {"id": "evidence", "label": "SAR evidence", "count": evidence_count, "denominator": evidence_count, "status": "ready" if evidence_count else "pending", "detail": f"{evidence_count} statements"},
        {"id": "candidates", "label": "Candidate records", "count": candidate_count, "denominator": candidate_count, "status": "ready" if candidate_count else "pending", "detail": f"{candidate_count} records"},
        {"id": "paths", "label": "Explicit paths", "count": explicit_path_count, "denominator": explicit_path_count, "status": "ready" if explicit_path_count else "pending", "detail": f"{explicit_path_count} text-confirmed paths"},
        {"id": "structures", "label": "Structure generation", "count": structure_count, "denominator": structure_denominator, "status": "ready" if structure_denominator and structure_count == structure_denominator else "pending", "detail": f"{structure_count} of {structure_denominator} SMILES slots" if structure_denominator else "No explicit paths"},
        {"id": "review", "label": "Human review", "count": 1 if paper.get("review_status") == "reviewed" else 0, "denominator": 1, "status": "complete" if paper.get("review_status") == "reviewed" else "pending", "detail": _paper_status_label(str(paper.get("review_status", "unreviewed")))},
    ]


def load_paper_detail(paper_id: str) -> dict[str, object]:
    """Aggregate every available pipeline layer belonging to one Paper."""
    paper = _paper_by_id(paper_id)
    evidence = [
        _normalize_evidence(row, index)
        for index, row in enumerate(read_csv_rows(PAPER_FILES["evidence"]), start=1)
        if row.get("paper_id") == paper_id
    ]
    candidates = [
        _normalize_candidate(row)
        for row in read_csv_rows(PAPER_FILES["candidates"])
        if row.get("paper_id") == paper_id
    ]
    explicit_rows = [
        row for row in read_csv_rows(PAPER_FILES["explicit"])
        if row.get("paper_id") == paper_id
    ]
    explicit_paths = []
    all_proposals = []
    for row in explicit_rows:
        path = _normalize_path(row, "explicit")
        path["proposals"] = load_proposals(row.get("visual_review_id", ""))
        explicit_paths.append(path)
        all_proposals.extend(path["proposals"])
    structures_by_id = _structure_rows()
    structures = [
        _normalize_structure(structures_by_id[row.get("visual_review_id", "")])
        for row in explicit_rows
        if row.get("visual_review_id") in structures_by_id
    ]
    all_molecule_objects = load_first_page_molecule_objects().get("objects", [])
    if not isinstance(all_molecule_objects, list):
        all_molecule_objects = []
    molecule_objects = [
        item for item in all_molecule_objects
        if isinstance(item, dict) and item.get("paper_id") == paper_id
    ]
    lineage_snapshot = load_compound_lineages(paper_id)
    lineage_edges = lineage_snapshot.get("edges", [])
    if not isinstance(lineage_edges, list):
        lineage_edges = []
    review_items = _unified_review_items(
        paper_id=paper_id, evidence=evidence, candidates=candidates,
        explicit_paths=explicit_paths, structures=structures,
        overrides=load_review_overrides().get(paper_id, {}),
        molecule_objects=molecule_objects,
        lineage_edges=lineage_edges,
    )
    attachment_inferences = [
        item.get("attachment_inference", {})
        for item in molecule_objects
        if isinstance(item.get("attachment_inference"), dict)
        and item["attachment_inference"].get("review_status") not in {"", "--"}
    ]
    molecule_object_summary = {
        "object_rows": len(molecule_objects),
        "attachment_inference_rows": len(attachment_inferences),
        "fragment_smiles_rows": sum(
            inference.get("fragment_smiles") not in {"", "--"}
            for inference in attachment_inferences
        ),
        "assembled_candidate_rows": sum(
            inference.get("assembled_smiles") not in {"", "--"}
            for inference in attachment_inferences
        ),
    }
    paper["progress"] = _paper_progress(
        paper, len(evidence), len(candidates), len(explicit_paths), len(structures)
    )
    paper["detail_counts"] = {
        "evidence": len(evidence),
        "candidates": len(candidates),
        "explicit_paths": len(explicit_paths),
        "structures": len(structures),
        "proposals": len(all_proposals),
        "review_items": len(review_items),
        "molecule_objects": molecule_object_summary["object_rows"],
        "attachment_inferences": molecule_object_summary["attachment_inference_rows"],
        "molecule_pairs": sum(item.get("source_kind") == "molecule_pair" for item in review_items),
        "molecule_candidates": sum(
            item.get("source_kind") == "molecule_pair"
            and (
                str((item.get("molecule_pair") or {}).get("fragment_smiles", "")).strip() not in {"", "--"}
                or str((item.get("molecule_pair") or {}).get("assembled_smiles", "")).strip() not in {"", "--"}
            )
            for item in review_items
        ),
        "lineages": len(lineage_snapshot.get("lineages", [])),
        "lineage_edges": len(lineage_edges),
        "unresolved_lineage_edges": sum(edge.get("relation_status") == "unresolved" for edge in lineage_edges),
    }
    return {
        "paper": paper,
        "evidence": evidence,
        "candidates": candidates,
        "explicit_paths": explicit_paths,
        "structures": structures,
        "proposals": all_proposals,
        "review_items": review_items,
        "molecule_object_summary": molecule_object_summary,
        "molecule_objects": molecule_objects,
        "compound_lineage_summary": lineage_snapshot.get("summary", {}),
        "compound_entities": lineage_snapshot.get("entities", []),
        "compound_lineage_edges": lineage_edges,
        "compound_lineage_evidence": lineage_snapshot.get("evidence", []),
        "compound_activities": lineage_snapshot.get("activities", []),
        "compound_lineages": lineage_snapshot.get("lineages", []),
    }


def load_overview() -> dict[str, object]:
    """Build the project-level view while preserving each data layer."""
    counts = {
        key: len(read_csv_rows(path)) if path.is_file() else 0
        for key, path in COUNT_FILES.items()
    }
    explicit_rows = read_csv_rows(PATH_FILES["explicit"])
    unresolved_rows = read_csv_rows(PATH_FILES["unresolved"])
    enriched_rows = read_csv_rows(COUNT_FILES["candidate_records"])
    manifest_rows = read_csv_rows(COUNT_FILES["structure_crops"])
    summary = read_json(SUMMARY_PATH) if SUMMARY_PATH.is_file() else {}
    quality = _proposal_quality()
    structure_ocr = _structure_ocr_progress()
    structures = _structure_rows()
    confirmed = _confirmed_count(explicit_rows)
    counts["confirmed_paths"] = confirmed
    explicit_path_count = counts["explicit_paths"]
    structure_total = explicit_path_count * 2
    counts["structure_slots"] = structure_total

    stages = [
        {"id": "corpus", "label": "Corpus", "count": counts["papers"], "unit": "papers", "status": "complete", "progress": 100},
        {"id": "text", "label": "Text extraction", "count": counts["papers"], "unit": "papers", "status": "complete", "progress": 100},
        {"id": "evidence", "label": "SAR evidence", "count": counts["evidence"], "unit": "statements", "status": "complete", "progress": 100},
        {"id": "candidates", "label": "Candidate records", "count": counts["candidate_records"], "unit": "records", "status": "in_progress", "progress": 0, "detail": f"{len(unresolved_rows)} queued for review"},
        {"id": "text_paths", "label": "Explicit text paths", "count": explicit_path_count, "unit": "paths", "status": "in_progress", "progress": 0, "detail": "structure confirmation pending"},
        {"id": "structures", "label": "Structure generation", "count": sum(row.get("confirmation_status") == "confirmed_by_si_smiles" for row in structures.values()) * 2, "unit": "SMILES slots", "status": "in_progress", "progress": round(sum(row.get("confirmation_status") == "confirmed_by_si_smiles" for row in structures.values()) * 2 / structure_total * 100) if structure_total else 0, "denominator": structure_total, "detail": f"{sum(row.get('confirmation_status') == 'confirmed_by_si_smiles' for row in structures.values()) * 2} of {structure_total} generated; human review pending"},
        {"id": "confirmed", "label": "Confirmed paths", "count": confirmed, "unit": "paths", "status": "complete" if confirmed == explicit_path_count and explicit_path_count else "pending", "progress": round(confirmed / explicit_path_count * 100) if explicit_path_count else 0, "detail": "human confirmation required"},
    ]
    return {
        "counts": counts,
        "quality": quality,
        "structure_ocr": structure_ocr,
        "structure_generation": {
            "paths_with_two_smiles": sum(row.get("confirmation_status") == "confirmed_by_si_smiles" for row in structures.values()),
            "smiles_slots": sum(
                bool(row.get("parent_rdkit_status") == "valid" and row.get("parent_canonical_smiles"))
                for row in structures.values()
            ) + sum(
                bool(row.get("derived_rdkit_status") == "valid" and row.get("derived_canonical_smiles"))
                for row in structures.values()
            ),
            "pending_human_review": sum(row.get("confirmation_status") == "confirmed_by_si_smiles" for row in structures.values()),
        },
        "stages": stages,
        "queues": {
            "unresolved": len(unresolved_rows),
            "high_priority": sum(row.get("priority") == "high" for row in unresolved_rows),
            "medium_priority": sum(row.get("priority") == "medium" for row in unresolved_rows),
            "normal_priority": sum(row.get("priority") == "normal" for row in unresolved_rows),
            "explicit_pending": sum(row.get("path_status") != "confirmed" for row in explicit_rows),
        },
        "model": {
            "version": summary.get("model_version", "unknown"),
            "gpu": summary.get("gpu", "unknown"),
            "matrix_sum": summary.get("matrix_sum", "unknown"),
        },
        "snapshot": {
            "pipeline_root": str(PIPELINE_ROOT),
            "summary_mtime": SUMMARY_PATH.stat().st_mtime if SUMMARY_PATH.is_file() else None,
            "candidate_snapshot": len(enriched_rows),
        },
    }


def _path_id(row: dict[str, str], scope: str) -> str:
    return row.get("visual_review_id", "") if scope == "explicit" else row.get("path_candidate_id", "")


def _searchable_text(row: dict[str, str]) -> str:
    return " ".join(str(value) for value in row.values()).casefold()


def _normalize_path(row: dict[str, str], scope: str) -> dict[str, object]:
    if scope == "explicit":
        path_id = row.get("visual_review_id", "")
        structure = _structure_rows().get(path_id, {})
        return {
            "id": path_id,
            "scope": scope,
            "visual_review_id": path_id,
            "path_candidate_id": row.get("canonical_path_candidate_id", ""),
            "title": row.get("title_guess", ""),
            "doi": row.get("doi", ""),
            "page": _integer(row.get("page")),
            "parent_compound": row.get("parent_compound", ""),
            "derived_compound": row.get("derived_compound", ""),
            "from_group": row.get("reported_from_group", ""),
            "to_group": row.get("reported_to_group", ""),
            "activity": row.get("reported_activity_mentions", ""),
            "evidence_text": row.get("evidence_text", ""),
            "page_references": row.get("page_references", ""),
            "structure_review_status": row.get("structure_review_status", ""),
            "review_status": row.get("review_status", ""),
            "path_status": row.get("path_status", ""),
            "priority": "structure",
            "priority_score": 0,
            "evidence_page_url": _asset_url("pages", row.get("rendered_page_png", "")),
            "parent_smiles": structure.get("parent_smiles", row.get("structure_smiles_parent", "")),
            "derived_smiles": structure.get("derived_smiles", row.get("structure_smiles_derived", "")),
            "parent_canonical_smiles": structure.get("parent_canonical_smiles", ""),
            "derived_canonical_smiles": structure.get("derived_canonical_smiles", ""),
            "parent_rdkit_status": structure.get("parent_rdkit_status", "not_run"),
            "derived_rdkit_status": structure.get("derived_rdkit_status", "not_run"),
            "atom_level_change": structure.get("atom_level_change", row.get("atom_level_change", "")),
            "structure_source": structure.get("structure_source", ""),
            "structure_confirmation_status": structure.get("confirmation_status", ""),
            "structure_image_parent_url": _asset_url("structures", Path(structure.get("structure_image_parent", "")).name),
            "structure_image_derived_url": _asset_url("structures", Path(structure.get("structure_image_derived", "")).name),
            "path_panel_image_url": _asset_url("structures", Path(structure.get("path_panel_image", "")).name),
            "confirmation_note": structure.get("notes", row.get("structure_confirmation_note", "")),
        }
    path_id = row.get("path_candidate_id", "")
    return {
        "id": path_id,
        "scope": scope,
        "visual_review_id": "",
        "path_candidate_id": path_id,
        "title": row.get("title_guess", ""),
        "doi": row.get("doi", ""),
        "page": _integer(row.get("page")),
        "parent_compound": row.get("parent_compound", ""),
        "derived_compound": row.get("derived_compound", ""),
        "from_group": row.get("reported_from_group", ""),
        "to_group": row.get("reported_to_group", ""),
        "activity": row.get("activity_mentions", ""),
        "evidence_text": row.get("evidence_text", ""),
        "page_references": "",
        "structure_review_status": "needs_scheme_or_table_review",
        "review_status": row.get("review_status", ""),
        "path_status": "candidate",
        "priority": row.get("priority", "normal"),
        "priority_score": _number(row.get("priority_score")),
        "evidence_page_url": "",
        "parent_smiles": "",
        "derived_smiles": "",
        "atom_level_change": "",
        "confirmation_note": "",
    }


def load_paths(
    *,
    scope: str = "explicit",
    query: str = "",
    priority: str = "all",
    status: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, object]:
    """Return a bounded, normalized path queue for the client."""
    if scope not in PATH_FILES and scope != "all":
        raise ValueError("scope must be explicit, unresolved, or all")
    scopes = [scope] if scope != "all" else ["explicit", "unresolved"]
    records = [
        _normalize_path(row, selected_scope)
        for selected_scope in scopes
        for row in read_csv_rows(PATH_FILES[selected_scope])
    ]
    needle = query.strip().casefold()
    if needle:
        records = [record for record in records if needle in _searchable_text(record)]
    if priority != "all":
        records = [record for record in records if record["priority"] == priority]
    if status != "all":
        records = [record for record in records if record["review_status"] == status or record["path_status"] == status]
    records.sort(key=lambda item: (-float(item["priority_score"]), str(item["id"])))
    page_size = max(1, min(int(page_size), 100))
    page_count = max(1, math.ceil(len(records) / page_size))
    page = max(1, min(int(page), page_count))
    start = (page - 1) * page_size
    return {
        "items": records[start : start + page_size],
        "total": len(records),
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "scope": scope,
    }


def load_proposals(visual_review_id: str | None = None) -> list[dict[str, object]]:
    rows = read_csv_rows(PROPOSALS_PATH) if PROPOSALS_PATH.is_file() else []
    structures = _structure_rows()
    explicit_paths = {
        row.get("visual_review_id", ""): row
        for row in read_csv_rows(PATH_FILES["explicit"])
        if row.get("visual_review_id")
    }
    if visual_review_id:
        rows = [row for row in rows if row.get("visual_review_id") == visual_review_id]
    proposals = []
    for row in rows:
        structure = structures.get(row.get("visual_review_id", ""), {})
        path = explicit_paths.get(row.get("visual_review_id", ""), {})
        role = row.get("compound_role", "")
        structure_image = structure.get(
            "structure_image_parent" if role == "parent" else "structure_image_derived", ""
        )
        source_canonical = structure.get(
            "parent_canonical_smiles" if role == "parent" else "derived_canonical_smiles", ""
        )
        token_confidences: list[object] = []
        try:
            value = json.loads(row.get("token_confidences", "[]"))
            if isinstance(value, list):
                token_confidences = value
        except json.JSONDecodeError:
            pass
        proposals.append(
            {
                "crop_id": row.get("crop_id", ""),
                "visual_review_id": row.get("visual_review_id", ""),
                "compound_role": row.get("compound_role", ""),
                "compound_id": row.get("compound_id", ""),
                "crop_url": _asset_url("crops", Path(row.get("crop_path", "")).name),
                "raw_smiles": row.get("raw_smiles", ""),
                "token_confidences": token_confidences,
                "mean_token_confidence": row.get("mean_token_confidence", ""),
                "min_token_confidence": row.get("min_token_confidence", ""),
                "inference_status": row.get("inference_status", ""),
                "inference_error": row.get("inference_error", ""),
                "rdkit_status": row.get("rdkit_status", ""),
                "canonical_smiles": row.get("canonical_smiles", ""),
                "model_version": row.get("model_version", ""),
                "review_status": row.get("review_status", ""),
                "structure_image_url": _asset_url("structures", Path(structure_image).name),
                "path_panel_image_url": _asset_url("structures", Path(structure.get("path_panel_image", "")).name),
                "source_evidence_page_url": _asset_url("pages", path.get("rendered_page_png", "")),
                "source_canonical_smiles": source_canonical,
                "structure_source": structure.get("structure_source", ""),
            }
        )
    return proposals


def load_path_detail(visual_review_id: str) -> dict[str, object]:
    rows = read_csv_rows(PATH_FILES["explicit"])
    row = next((item for item in rows if item.get("visual_review_id") == visual_review_id), None)
    if row is None:
        raise PathNotFound(visual_review_id)
    detail = _normalize_path(row, "explicit")
    detail["proposals"] = load_proposals(visual_review_id)
    return detail


def _asset_url(kind: str, filename: str) -> str:
    if not filename:
        return ""
    return f"/assets/{kind}/{Path(filename).name}"


def resolve_asset(kind: str, filename: str) -> Path:
    """Resolve only a basename under the two approved evidence directories."""
    roots = {
        "pages": VISUAL_PAGES_ROOT,
        "crops": CROPS_ROOT,
        "structures": STRUCTURES_ROOT,
        "structure-ocr-crops": STRUCTURE_OCR_CROPS_ROOT,
        "molecule-review-crops": MOLECULE_REVIEW_CROPS_ROOT,
        "molecule-pair-structures": MOLECULE_PAIR_STRUCTURES_ROOT,
    }
    root = roots.get(kind)
    decoded = unquote(filename)
    if root is None or not decoded or Path(decoded).name != decoded:
        raise AssetNotFound(filename)
    candidate = (root / decoded).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise AssetNotFound(filename) from error
    if not candidate.is_file():
        raise AssetNotFound(filename)
    return candidate


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP adapter around snapshot data and the separate Paper review layer."""

    server_version = "JMCProgressDashboard/1.0"

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(DASHBOARD_ROOT), **kwargs)

    def _send_json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)
        try:
            if path == "/api/overview":
                self._send_json(load_overview())
                return
            if path == "/api/first-page-structure":
                self._send_json(load_first_page_fragment_review())
                return
            if path == "/api/first-page-molecule-objects":
                fragment_review = load_first_page_fragment_review()
                self._send_json(load_first_page_molecule_objects(fragment_review.get("papers", [])))
                return
            if path == "/api/papers":
                self._send_json(
                    load_papers(
                        query=params.get("q", [""])[0],
                        status=params.get("status", ["all"])[0],
                        review_status=params.get("review_status", ["all"])[0],
                        page=_integer(params.get("page", ["1"])[0], 1),
                        page_size=_integer(params.get("page_size", [str(PAPER_PAGE_SIZE)])[0], PAPER_PAGE_SIZE),
                    )
                )
                return
            if path.startswith("/api/papers/"):
                paper_id = unquote(path.removeprefix("/api/papers/"))
                self._send_json(load_paper_detail(paper_id))
                return
            if path == "/api/paths":
                self._send_json(
                    load_paths(
                        scope=params.get("scope", ["explicit"])[0],
                        query=params.get("q", [""])[0],
                        priority=params.get("priority", ["all"])[0],
                        status=params.get("status", ["all"])[0],
                        page=_integer(params.get("page", ["1"])[0], 1),
                        page_size=_integer(params.get("page_size", ["20"])[0], 20),
                    )
                )
                return
            if path == "/api/proposals":
                self._send_json({"items": load_proposals(params.get("visual_review_id", [""])[0] or None)})
                return
            if path.startswith("/api/paths/"):
                visual_review_id = unquote(path.removeprefix("/api/paths/"))
                self._send_json(load_path_detail(visual_review_id))
                return
            if path.startswith("/assets/"):
                parts = path.split("/", 3)
                if len(parts) != 4:
                    raise AssetNotFound(path)
                asset = resolve_asset(parts[2], parts[3])
                body = asset.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(str(asset))[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/":
                self.path = "/index.html"
            super().do_GET()
        except PathNotFound:
            self._send_error_json("path not found", HTTPStatus.NOT_FOUND)
        except PaperNotFound:
            self._send_error_json("paper not found", HTTPStatus.NOT_FOUND)
        except ReviewLocked:
            self._send_error_json("paper review is locked", HTTPStatus.CONFLICT)
        except AssetNotFound:
            self._send_error_json("asset not found", HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except DashboardDataError as error:
            self._send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/api/papers/") and path.endswith("/review-items"):
            paper_id = unquote(path.removeprefix("/api/papers/").removesuffix("/review-items").rstrip("/"))
            try:
                content_length = _integer(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 1_000_000:
                    raise ValueError("request body is missing or too large")
                try:
                    payload = json.loads(self.rfile.read(content_length))
                except json.JSONDecodeError as error:
                    raise ValueError("request body must be valid JSON") from error
                add_review_item(paper_id, payload)
                self._send_json(load_paper_detail(paper_id), HTTPStatus.CREATED)
            except PaperNotFound:
                self._send_error_json("paper not found", HTTPStatus.NOT_FOUND)
            except ReviewLocked:
                self._send_error_json("paper review is locked", HTTPStatus.CONFLICT)
            except ValueError as error:
                self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
            except DashboardDataError as error:
                self._send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path.startswith("/api/papers/") and "/review-items/" in path:
            prefix, encoded_item_id = path.split("/review-items/", 1)
            paper_id = unquote(prefix.removeprefix("/api/papers/"))
            action = ""
            if encoded_item_id.endswith("/confirm"):
                encoded_item_id, action = encoded_item_id.removesuffix("/confirm"), "confirm"
            review_item_id = unquote(encoded_item_id)
            try:
                if action == "confirm":
                    item = confirm_review_item(paper_id, review_item_id)
                    self._send_json({"item": item, "paper": load_paper_detail(paper_id)["paper"]})
                    return
                content_length = _integer(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 1_000_000:
                    raise ValueError("request body is missing or too large")
                try:
                    payload = json.loads(self.rfile.read(content_length))
                except json.JSONDecodeError as error:
                    raise ValueError("request body must be valid JSON") from error
                save_review_item(paper_id, review_item_id, payload)
                self._send_json(load_paper_detail(paper_id))
            except PaperNotFound:
                self._send_error_json("paper not found", HTTPStatus.NOT_FOUND)
            except ReviewItemNotFound:
                self._send_error_json("review item not found", HTTPStatus.NOT_FOUND)
            except ReviewItemLocked:
                self._send_error_json("review item is locked", HTTPStatus.CONFLICT)
            except ReviewLocked:
                self._send_error_json("paper review is locked", HTTPStatus.CONFLICT)
            except ValueError as error:
                self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
            except DashboardDataError as error:
                self._send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if not path.startswith("/api/papers/") or not path.endswith("/review"):
            self._send_error_json("unsupported endpoint", HTTPStatus.NOT_FOUND)
            return
        paper_id = unquote(path.removeprefix("/api/papers/").removesuffix("/review").rstrip("/"))
        try:
            content_length = _integer(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1_000_000:
                raise ValueError("request body is missing or too large")
            try:
                payload = json.loads(self.rfile.read(content_length))
            except json.JSONDecodeError as error:
                raise ValueError("request body must be valid JSON") from error
            save_review_override(paper_id, payload)
            self._send_json(load_paper_detail(paper_id))
        except PaperNotFound:
            self._send_error_json("paper not found", HTTPStatus.NOT_FOUND)
        except ReviewLocked:
            self._send_error_json("paper review is locked", HTTPStatus.CONFLICT)
        except ValueError as error:
            self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except DashboardDataError as error:
            self._send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not path.startswith("/api/papers/") or "/review-items/" not in path:
            self._send_error_json("unsupported endpoint", HTTPStatus.NOT_FOUND)
            return
        prefix, encoded_item_id = path.split("/review-items/", 1)
        paper_id = unquote(prefix.removeprefix("/api/papers/"))
        review_item_id = unquote(encoded_item_id)
        try:
            delete_review_item(paper_id, review_item_id)
            self._send_json(load_paper_detail(paper_id))
        except PaperNotFound:
            self._send_error_json("paper not found", HTTPStatus.NOT_FOUND)
        except ReviewItemNotFound:
            self._send_error_json("review item not found", HTTPStatus.NOT_FOUND)
        except ReviewItemLocked:
            self._send_error_json("review item is locked", HTTPStatus.CONFLICT)
        except ReviewLocked:
            self._send_error_json("paper review is locked", HTTPStatus.CONFLICT)
        except DashboardDataError as error:
            self._send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: object) -> None:
        print(f"dashboard: {format % args}", file=sys.stderr)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard available at http://{host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
