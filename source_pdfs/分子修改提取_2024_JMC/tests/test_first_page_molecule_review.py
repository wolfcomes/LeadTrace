import csv
from pathlib import Path

from build_first_page_molecule_review import (
    OBJECT_FIELDS,
    build_molecule_objects,
    classify_object_smiles_state,
    write_molecule_snapshot,
)
from run_first_page_molecule_ocr import (
    merge_proposals_into_objects,
    select_ocr_objects,
    validate_proposal_smiles,
)


def candidate(candidate_id: str, visual_scope: str, crop_path: str = "") -> dict[str, str]:
    return {
        "paper_rank": "1",
        "paper_id": "paper-1",
        "title_guess": "Test paper",
        "source_pdf": "/tmp/paper.pdf",
        "candidate_id": candidate_id,
        "page_candidate_id": candidate_id.rsplit("-CAND-", 1)[0],
        "page": "2",
        "region_kind": "embedded_image",
        "crop_path": crop_path,
        "x0": "10",
        "y0": "20",
        "x1": "110",
        "y1": "220",
        "source_queue_item_ids": "PATH-1",
        "compound_ids": "1 | 2a",
        "visual_scope": visual_scope,
        "visual_scope_label": visual_scope,
        "visual_basis": "test visual annotation",
        "fragment_role": "test",
        "visible_notation": "R1; Linker a-e" if "fragment" in visual_scope else "--",
        "attachment_points": "R1; Linker a-e" if "fragment" in visual_scope else "--",
        "linked_review_item_ids": "PATH-1",
        "linked_entry_count": "1",
        "text_evidence": "R1 linker replacement",
        "parent_compounds": "1",
        "derived_compounds": "2a",
        "reported_changes": "R1 -> Linker",
        "inference_steps": "identify image -> split objects -> infer structure -> SMILES",
        "image_localization_status": "structure_region_identified",
        "fragment_recognition_status": "fragment_or_series_identified",
        "attachment_reasoning_status": "requires_review",
        "whole_molecule_smiles_status": "not_evaluable_fragment_only",
        "fragment_smiles_status": "not_evaluated",
        "raw_smiles": "CCO",
        "canonical_smiles": "CCO",
        "rdkit_status": "valid",
        "proposal_quality": "valid_but_needs_review",
        "smiles_accuracy_state": "fragment_syntax_valid_needs_connectivity_review",
        "review_status": "proposal_requires_human_review",
        "model_version": "2.7.2",
        "human_review_status": "proposal_only_pending_human_review",
        "annotation_version": "test",
    }


def test_series_candidate_expands_to_numbered_molecule_objects() -> None:
    rows = build_molecule_objects([
        candidate("PAGE-5d639341273b-CAND-001", "complete_molecule_series")
    ], render_crops=False)

    labels = {row["compound_label"] for row in rows}
    assert len(rows) >= 16
    assert {"1", "2a", "2o"}.issubset(labels)
    assert len({row["object_id"] for row in rows}) == len(rows)
    assert all(row["object_type"] == "molecule_series_member" for row in rows)


def test_fragment_candidate_keeps_scaffold_and_attachment_notation() -> None:
    rows = build_molecule_objects([
        candidate("PAGE-621e2220dc85-CAND-001", "fragment_or_series")
    ], render_crops=False)

    assert any(row["object_type"] == "linker_fragment" for row in rows)
    assert any(row["compound_label"] == "10a" for row in rows)
    assert all(row["smiles_accuracy_state"] != "whole_molecule_syntax_valid_needs_visual_review" for row in rows)
    assert any("Linker" in row["attachment_points"] for row in rows)


def test_non_structure_candidate_is_not_written_to_object_snapshot() -> None:
    rows = build_molecule_objects([
        candidate("PAGE-f4f94d8975c8-CAND-001", "non_structure_region")
    ], render_crops=False)

    assert rows == []
    assert classify_object_smiles_state("non_structure_region") == "not_applicable_non_structure"


def test_object_snapshot_drops_non_structure_objects_but_keeps_mixed_structure_objects() -> None:
    rows = build_molecule_objects([
        candidate("PAGE-f4f94d8975c8-CAND-001", "non_structure_region"),
        candidate("PAGE-3d1249a64e3d-CAND-002", "mixed_structure_evidence"),
    ], render_crops=False)

    assert rows
    assert all(row["object_type"] != "non_structure_region" for row in rows)
    assert any(row["object_type"] == "mixed_region_molecule" for row in rows)


def test_snapshot_is_idempotent_and_writes_all_object_fields(tmp_path: Path) -> None:
    candidates = [
        candidate("PAGE-5d639341273b-CAND-001", "complete_molecule_series"),
        candidate("PAGE-6f29995b606f-CAND-001", "fragment_or_series"),
    ]
    output = tmp_path / "objects.csv"
    summary = tmp_path / "summary.json"
    first, _ = write_molecule_snapshot(candidates, output, summary, render_crops=False)
    second, _ = write_molecule_snapshot(candidates, output, summary, render_crops=False)

    assert first == second
    assert set(first[0]) == set(OBJECT_FIELDS)
    with output.open(newline="", encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == len(first)


def test_ocr_selection_excludes_fragments_and_non_structure_regions() -> None:
    rows = [
        {"object_id": "whole", "smiles_source": "isolated_object_pending_ocsr", "crop_path": "/tmp/whole.png"},
        {"object_id": "fragment", "smiles_source": "attachment_point_notation_only", "crop_path": "/tmp/fragment.png"},
        {"object_id": "excluded", "smiles_source": "excluded_non_structure_region", "crop_path": "/tmp/chart.png"},
        {"object_id": "missing", "smiles_source": "isolated_object_pending_ocsr", "crop_path": "--"},
    ]

    assert [row["object_id"] for row in select_ocr_objects(rows)] == ["whole"]


def test_smiles_validation_marks_rdkit_valid_but_multi_component_output_suspicious() -> None:
    result = validate_proposal_smiles("CCO.[C-]#[O+].[C-]#[O+]")

    assert result["rdkit_status"] == "valid"
    assert result["proposal_quality"] == "valid_but_suspicious_needs_review"
    assert result["canonical_smiles"]
    assert result["heuristic_primary_component_smiles"] == "CCO"


def test_merging_ocr_proposals_is_idempotent_and_does_not_confirm_objects() -> None:
    objects = [{
        "object_id": "whole", "raw_smiles": "--", "canonical_smiles": "--",
        "heuristic_primary_component_smiles": "--",
        "rdkit_status": "not_run", "smiles_accuracy_state": "isolated_object_awaiting_ocsr",
        "review_status": "object_requires_human_review",
    }]
    proposals = [{
        "object_id": "whole", "raw_smiles": "CCO", "canonical_smiles": "CCO",
        "heuristic_primary_component_smiles": "CCO",
        "rdkit_status": "valid", "proposal_quality": "valid_but_needs_review",
    }]

    first = merge_proposals_into_objects(objects, proposals)
    second = merge_proposals_into_objects(first, proposals)

    assert first == second
    assert first[0]["raw_smiles"] == "CCO"
    assert first[0]["heuristic_primary_component_smiles"] == "CCO"
    assert first[0]["review_status"] == "object_requires_human_review"
    assert first[0]["smiles_accuracy_state"] == "isolated_object_syntax_valid_needs_visual_review"
