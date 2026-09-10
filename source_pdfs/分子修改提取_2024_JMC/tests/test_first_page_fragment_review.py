import csv
import json
from pathlib import Path

from build_first_page_fragment_review import (
    OUTPUT_FIELDS,
    build_first_page_rows,
    classify_smiles_accuracy,
    classify_visual_scope,
    write_first_page_snapshot,
)


def manifest_row(paper_id: str, rank: int) -> dict[str, str]:
    return {
        "paper_id": paper_id,
        "source_folder": "case5 volume67 issue1-4",
        "source_pdf": f"/tmp/{paper_id}.pdf",
        "title_guess": f"Paper {rank}",
    }


def proposal_row(candidate_id: str, paper_id: str, raw_smiles: str = "CCO") -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "page_candidate_id": candidate_id.rsplit("-CAND-", 1)[0],
        "paper_id": paper_id,
        "doi": "10.1021/example",
        "source_pdf": f"/tmp/{paper_id}.pdf",
        "page": "3",
        "region_kind": "embedded_image",
        "crop_path": f"/tmp/{candidate_id}.png",
        "x0": "1",
        "y0": "2",
        "x1": "3",
        "y1": "4",
        "candidate_score": "2",
        "source_queue_item_ids": "PATH-1",
        "compound_ids": "12a | 12b",
        "raw_smiles": raw_smiles,
        "token_confidences": "[]",
        "mean_token_confidence": "0.9",
        "min_token_confidence": "0.8",
        "inference_status": "ok",
        "inference_error": "",
        "rdkit_status": "valid" if raw_smiles == "CCO" else "invalid",
        "canonical_smiles": "CCO" if raw_smiles == "CCO" else "",
        "model_version": "2.7.2",
        "proposal_quality": "valid_but_needs_review" if raw_smiles == "CCO" else "invalid_smiles_needs_review",
        "review_status": "proposal_requires_human_review",
    }


def test_first_page_rows_selects_twenty_manifest_papers_and_marks_fragment_scope() -> None:
    manifest = [manifest_row(f"paper-{index}", index) for index in range(1, 22)]
    proposals = [proposal_row("PAGE-fragment-CAND-001", "paper-1")]
    auto_fill = [{
        "review_item_id": "PATH-1", "paper_id": "paper-1", "structure_expression": "attachment point(s): R1, R2",
        "attachment_points": "R1,R2", "evidence_text": "R1 linker replacement", "parent_compound": "12a",
        "derived_compound": "12b", "auto_fill_status": "text_populated_generic_structure",
    }]

    rows = build_first_page_rows(manifest, proposals, auto_fill)

    assert len(rows) == 1
    assert rows[0]["paper_rank"] == "1"
    assert rows[0]["visual_scope"] == "fragment_or_series"
    assert rows[0]["fragment_role"] == "replacement_fragment_or_series"
    assert rows[0]["attachment_points"] == "R1,R2"
    assert rows[0]["whole_molecule_smiles_status"] == "not_evaluable_fragment_only"
    assert rows[0]["review_status"] == "proposal_requires_human_review"


def test_accuracy_distinguishes_rdkit_syntax_from_visual_scope() -> None:
    assert classify_visual_scope({"candidate_id": "PAGE-6f29995b606f-CAND-002"}) == "non_structure_region"
    assert classify_smiles_accuracy("fragment_or_series", "valid", "valid_but_suspicious_needs_review") == "fragment_syntax_valid_but_suspicious"
    assert classify_smiles_accuracy("complete_molecule_candidate", "valid", "valid_but_needs_review") == "whole_molecule_syntax_valid_needs_visual_review"
    assert classify_smiles_accuracy("mixed_structure_evidence", "valid", "valid_but_needs_review") == "mixed_region_requires_split"
    assert classify_smiles_accuracy("non_structure_region", "valid", "valid_but_suspicious_needs_review") == "not_applicable_non_structure"


def test_write_snapshot_reports_only_proposals_and_deterministic_counts(tmp_path: Path) -> None:
    manifest = [manifest_row("paper-1", 1), manifest_row("paper-2", 2)]
    proposals = [
        proposal_row("PAGE-fragment-CAND-001", "paper-1"),
        proposal_row("PAGE-other-CAND-001", "paper-2", raw_smiles="C1CC"),
    ]
    proposals[1]["source_queue_item_ids"] = "PATH-2"
    auto_fill = [{
        "review_item_id": "PATH-1", "paper_id": "paper-1", "structure_expression": "R1 linker",
        "attachment_points": "R1", "evidence_text": "R1 linker replacement",
    }]
    rows, summary = write_first_page_snapshot(
        manifest, proposals, auto_fill, tmp_path / "first_page_structure_review.csv", tmp_path / "summary.json", page_size=2
    )

    assert set(rows[0]) == set(OUTPUT_FIELDS)
    assert summary["papers"] == 2
    assert summary["candidate_rows"] == 2
    assert summary["proposal_only_rows"] == 2
    assert summary["visual_scope_counts"]["fragment_or_series"] == 1
    assert summary["rdkit_status_counts"]["invalid"] == 1
    assert len(summary["paper_summaries"]) == 2
    assert summary["paper_summaries"][0]["paper_rank"] == 1
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["candidate_rows"] == 2
    with (tmp_path / "first_page_structure_review.csv").open(newline="", encoding="utf-8-sig") as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == 2
