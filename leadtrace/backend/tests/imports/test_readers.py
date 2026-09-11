from __future__ import annotations

from pathlib import Path

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
