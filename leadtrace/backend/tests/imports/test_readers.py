from __future__ import annotations

from pathlib import Path

from app.imports.readers.visuals import read_molecule_proposal_records
from app.imports.readers.manifest import read_csv_records


def test_csv_reader_preserves_raw_and_normalized_values_with_quoted_newlines(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    assert isinstance(source_root, Path)

    records = read_csv_records(
        source_root,
        "09_paper_review/auto_fill/compound_lineage_evidence.csv",
        record_type="evidence",
        id_field="lineage_evidence_id",
    )

    assert len(records) == 1
    record = records[0]
    assert record.original_id == "EVID-1"
    assert record.source_file == (
        "09_paper_review/auto_fill/compound_lineage_evidence.csv"
    )
    assert record.source_row_locator == "row:2"
    assert record.raw_values["evidence_text"] == "line one\nline two"
    assert record.normalized_values["evidence_text"] == "line one\nline two"
    assert len(record.source_hash) == 64


def test_csv_reader_normalizes_source_null_markers_without_changing_raw_values(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    assert isinstance(source_root, Path)

    records = read_csv_records(
        source_root,
        "09_paper_review/auto_fill/first_page_molecule_objects.csv",
        record_type="visual_object",
        id_field="object_id",
    )

    assert records[0].raw_values["source_crop_path"] == "--"
    assert records[0].normalized_values["source_crop_path"] is None


def test_proposal_reader_parses_tokens_and_normalizes_crop_reference(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    assert isinstance(source_root, Path)

    records = read_molecule_proposal_records(source_root)

    assert len(records) == 1
    proposal = records[0]
    assert proposal.record_type == "molecule_proposal"
    assert proposal.original_id == "OBJ-1"
    assert proposal.normalized_values["token_confidences"] == [
        {"token": "C", "confidence": 0.9}
    ]
    assert proposal.normalized_values["proposal_key"] == "ocsr:OBJ-1"
    assert proposal.normalized_values["model_run_key"] == (
        "ocsr-v1:2026-09-05T02:03:39+00:00"
    )
    assert proposal.normalized_values["crop_path"] == (
        "09_paper_review/auto_fill/molecule_review_crops/OBJ-1.png"
    )
