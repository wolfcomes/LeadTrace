import csv
from pathlib import Path

from auto_fill_review import (
    classify_structure_need,
    extract_generic_structure_expression,
    build_auto_filled_rows,
    build_progress_rows,
    build_structure_review_queue,
)


def test_classifies_exact_pairs_r_groups_and_statement_only_rows() -> None:
    assert classify_structure_need({"parent_compound": "12d", "derived_compound": "12g", "evidence_text": "replacement"}) == "exact_pair_candidate"
    assert classify_structure_need({"parent_compound": "", "derived_compound": "", "evidence_text": "The R3 group was changed."}) == "generic_r_group_or_linker"
    assert classify_structure_need({"parent_compound": "", "derived_compound": "", "evidence_text": "The series showed improved potency."}) == "statement_only"


def test_extracts_r_group_and_linker_without_fabricating_smiles() -> None:
    r_group = extract_generic_structure_expression("A more negatively charged group was introduced to the R3 of compound 12.")
    linker = extract_generic_structure_expression("The introduction of a -CH2-O-CH2- linker in compound 14 reduced potency.")

    assert r_group["representation_kind"] == "attachment_point_notation"
    assert "R3" in r_group["structure_expression"]
    assert r_group["smiles"] == ""
    assert linker["representation_kind"] == "linker_notation"
    assert "CH2" in linker["structure_expression"]
    assert linker["smiles"] == ""


def test_auto_fill_preserves_all_input_rows_and_marks_source() -> None:
    rows = [{
        "path_candidate_id": "PATH-0000001",
        "paper_id": "paper-1",
        "doi": "10.1000/example",
        "page": "3",
        "parent_compound": "12d",
        "derived_compound": "12g",
        "reported_from_group": "phenyl",
        "reported_to_group": "pyridine",
        "relation_type": "explicit_directed_replacement",
        "confidence": "explicit_text_pair",
        "activity_mentions": "decreased activity",
        "evidence_text": "The replacement of phenyl (12d) with pyridine (12g) decreased activity.",
        "structure_review_status": "needs_scheme_or_table_review",
        "review_status": "unreviewed",
    }]
    evidence = [{
        "paper_id": "paper-1", "page": "3", "evidence_text": rows[0]["evidence_text"],
        "compound_mentions": "12d, 12g",
    }]

    output = build_auto_filled_rows(rows, evidence, {})

    assert len(output) == 1
    assert output[0]["review_item_id"] == "PATH-0000001"
    assert output[0]["compound_mentions"] == "12d, 12g"
    assert output[0]["auto_fill_status"] == "text_populated_structure_candidate"
    assert output[0]["auto_fill_source"] == "07_enriched_text_paths/all_path_candidates_enriched.csv"


def test_progress_contains_zero_row_papers_and_counts_each_layer() -> None:
    manifest = [{"paper_id": "paper-1"}, {"paper_id": "paper-2"}]
    filled = [{"paper_id": "paper-1", "auto_fill_status": "text_populated_structure_candidate", "structure_representation_kind": "exact_si_smiles"}]

    progress = build_progress_rows(manifest, filled)

    assert len(progress) == 2
    by_id = {row["paper_id"]: row for row in progress}
    assert by_id["paper-1"]["auto_filled_entries"] == 1
    assert by_id["paper-1"]["exact_structure_entries"] == 1
    assert by_id["paper-2"]["auto_fill_status"] == "no_modification_records"


def test_structure_review_queue_records_pdf_location_and_table_signal() -> None:
    rows = [{
        "path_candidate_id": "PATH-1", "paper_id": "paper-1", "doi": "10.1000/x",
        "source_pdf": "/tmp/paper.pdf", "page": "4", "parent_compound": "",
        "derived_compound": "", "evidence_text": "The R group was changed in Table 2.",
    }]

    queue = build_structure_review_queue(rows)

    assert queue[0]["structure_review_queue_status"] == "queued_generic_notation"
    assert queue[0]["pdf_exists"] == "0"
    assert queue[0]["page_has_table_or_scheme_signal"] == "1"
