import csv
import json
from pathlib import Path
import types

import pymupdf as fitz

from structure_ocr_batch import (
    PROPOSAL_FIELDS,
    build_page_worklist,
    extract_page_candidates,
    merge_proposals,
    relaunch_for_inference,
    select_inference_candidates,
    validate_ocr_proposal,
)


def make_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=300, height=300)
    page.insert_text((30, 40), "Scheme 1. Compound 12a", fontsize=12)
    page.draw_line((50, 100), (100, 100), width=1.2)
    page.draw_line((100, 100), (125, 75), width=1.2)
    page.draw_line((100, 100), (125, 125), width=1.2)
    page.draw_rect(fitz.Rect(130, 70, 190, 130), width=1.2)
    document.save(path)
    document.close()


def test_extract_page_candidates_returns_traceable_vector_region(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    make_pdf(pdf)
    document = fitz.open(pdf)

    candidates = extract_page_candidates(document[0], labels={"12A"})

    assert candidates
    vector = next(candidate for candidate in candidates if candidate["region_kind"] == "vector_drawing")
    assert vector["page"] == "1"
    assert float(vector["x1"]) > float(vector["x0"])
    assert float(vector["y1"]) > float(vector["y0"])
    assert vector["candidate_score"]
    document.close()


def test_extract_page_candidates_drops_filled_table_cells_and_rule_lines() -> None:
    document = fitz.open()
    page = document.new_page(width=300, height=300)
    page.draw_rect(fitz.Rect(30, 40, 250, 70), color=None, fill=(0.9, 0.9, 0.9))
    page.draw_line((30, 90), (270, 90), width=1)

    candidates = extract_page_candidates(page)

    assert candidates == []
    document.close()


def test_build_page_worklist_deduplicates_pages_and_skips_unfocused_statement_rows(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    make_pdf(pdf)
    rows = [
        {
            "review_item_id": "PATH-1", "paper_id": "paper-1", "source_pdf": str(pdf),
            "page": "1", "structure_need": "generic_r_group_or_linker",
            "page_has_table_or_scheme_signal": "1", "page_has_figure_signal": "0",
            "parent_compound": "", "derived_compound": "12a", "evidence_text": "Scheme 1",
        },
        {
            "review_item_id": "PATH-2", "paper_id": "paper-1", "source_pdf": str(pdf),
            "page": "1", "structure_need": "statement_only",
            "page_has_table_or_scheme_signal": "0", "page_has_figure_signal": "0",
            "parent_compound": "", "derived_compound": "", "evidence_text": "potency improved",
        },
    ]

    worklist = build_page_worklist(rows, tmp_path / "crops")

    assert len(worklist) == 1
    assert worklist[0]["paper_id"] == "paper-1"
    assert worklist[0]["page"] == "1"
    assert worklist[0]["source_queue_item_ids"] == "PATH-1"


def test_validate_ocr_proposal_requires_proposal_status_and_preserves_invalid_smiles() -> None:
    row = {
        field: "" for field in PROPOSAL_FIELDS
    }
    row.update({
        "candidate_id": "PAGE-1-CAND-1", "raw_smiles": "C1CC", "inference_status": "ok",
        "rdkit_status": "invalid", "review_status": "proposal_requires_human_review",
    })

    checked = validate_ocr_proposal(row)

    assert checked["rdkit_status"] == "invalid"
    assert checked["canonical_smiles"] == ""
    assert checked["review_status"] == "proposal_requires_human_review"


def test_validate_ocr_proposal_marks_rdkit_valid_metal_or_noise_as_suspicious() -> None:
    row = {field: "" for field in PROPOSAL_FIELDS}
    row.update({
        "candidate_id": "PAGE-1-CAND-1", "raw_smiles": "CC.[Ag]", "inference_status": "ok",
    })

    checked = validate_ocr_proposal(row)

    assert checked["rdkit_status"] == "valid"
    assert checked["proposal_quality"] == "valid_but_suspicious_needs_review"


def test_merge_proposals_is_idempotent_and_does_not_overwrite_confirmed_rows(tmp_path: Path) -> None:
    output = tmp_path / "proposals.csv"
    existing = {
        field: "" for field in PROPOSAL_FIELDS
    }
    existing.update({
        "candidate_id": "PAGE-1-CAND-1", "canonical_smiles": "CC", "rdkit_status": "valid",
        "review_status": "reviewed", "inference_status": "ok",
    })
    incoming = {
        field: "" for field in PROPOSAL_FIELDS
    }
    incoming.update({
        "candidate_id": "PAGE-1-CAND-1", "canonical_smiles": "CCC", "rdkit_status": "valid",
        "review_status": "proposal_requires_human_review", "inference_status": "ok",
    })

    merge_proposals(output, [existing], [incoming])
    merge_proposals(output, [existing], [incoming])

    saved = list(csv.DictReader(output.open(encoding="utf-8-sig")))
    assert len(saved) == 1
    assert saved[0]["canonical_smiles"] == "CC"
    assert saved[0]["review_status"] == "reviewed"


def test_relaunch_for_inference_propagates_nvidia_loader_path(monkeypatch) -> None:
    calls = []

    monkeypatch.delenv("STRUCTURE_OCR_REEXECUTED", raising=False)
    monkeypatch.setattr(
        "structure_ocr_batch.configure_nvidia_library_path",
        lambda: "/nvidia/cuda/lib:/system/lib",
    )
    monkeypatch.setattr(
        "structure_ocr_batch.subprocess.run",
        lambda command, env, check: calls.append((command, env, check)) or types.SimpleNamespace(returncode=23),
    )

    assert relaunch_for_inference(["--limit", "1"]) == 23
    assert calls[0][0][-2:] == ["--limit", "1"]
    assert calls[0][1]["LD_LIBRARY_PATH"] == "/nvidia/cuda/lib:/system/lib"
    assert calls[0][1]["STRUCTURE_OCR_REEXECUTED"] == "1"


def test_select_inference_candidates_prioritizes_vector_and_high_score_rows() -> None:
    rows = [
        {"candidate_id": "image", "region_kind": "embedded_image", "candidate_score": "6", "crop_status": "rendered", "crop_path": "/tmp/image.png"},
        {"candidate_id": "vector-low", "region_kind": "vector_drawing", "candidate_score": "3", "crop_status": "rendered", "crop_path": "/tmp/vector-low.png"},
        {"candidate_id": "vector-high", "region_kind": "vector_drawing", "candidate_score": "5", "crop_status": "rendered", "crop_path": "/tmp/vector-high.png"},
        {"candidate_id": "broken", "region_kind": "vector_drawing", "candidate_score": "9", "crop_status": "error:ValueError", "crop_path": "/tmp/broken.png"},
    ]

    selected = select_inference_candidates(rows, offset=0, limit=3)

    assert [row["candidate_id"] for row in selected] == ["vector-high", "vector-low", "image"]


def test_build_progress_rows_includes_papers_without_structure_candidates() -> None:
    progress = __import__("structure_ocr_batch").build_progress_rows(
        [], [], paper_rows=[
            {"paper_id": "paper-1", "source_pdf": "/tmp/paper-1.pdf"},
            {"paper_id": "paper-2", "source_pdf": "/tmp/paper-2.pdf"},
        ]
    )

    assert len(progress) == 2
    assert progress[0]["progress_status"] == "no_structure_candidate_found"
    assert progress[0]["candidate_count"] == "0"
