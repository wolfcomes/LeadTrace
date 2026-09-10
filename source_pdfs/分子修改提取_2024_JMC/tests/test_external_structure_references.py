import csv
import json
from pathlib import Path

from rdkit import Chem

from build_external_structure_references import (
    EXTERNAL_REFERENCE_FIELDS,
    clean_source_smiles,
    build_external_reference_rows,
    write_external_reference_snapshot,
    build_from_manifest,
    read_csv,
)


def test_clean_source_smiles_removes_si_atom_annotation_without_changing_graph() -> None:
    raw = "CCO |a:1,2|"

    cleaned = clean_source_smiles(raw)

    assert cleaned == "CCO"
    assert Chem.MolToSmiles(Chem.MolFromSmiles(cleaned)) == "CCO"


def test_read_csv_repairs_unquoted_commas_inside_si_smiles_annotations(tmp_path: Path) -> None:
    source = tmp_path / "rgh.csv"
    source.write_text(
        "Compound_ID,SMILES,Ki,IC50\n"
        "10,CCO |a:1,2|,8.0,42\n",
        encoding="utf-8",
    )

    rows = read_csv(source)

    assert rows == [{
        "Compound_ID": "10",
        "SMILES": "CCO |a:1,2|",
        "Ki": "8.0",
        "IC50": "42",
    }]


def test_build_rows_matches_only_numbered_objects_and_keeps_fragment_objects_out() -> None:
    objects = [
        {
            "object_id": "OBJ-3",
            "paper_rank": "5",
            "paper_id": "paper-arene",
            "doi": "10.1021/acs.jmedchem.3c02127",
            "candidate_id": "PAGE-arene-CAND-002",
            "compound_label": "3",
            "object_type": "molecule_series_member",
            "crop_path": "/tmp/3.png",
        },
        {
            "object_id": "OBJ-R",
            "paper_rank": "5",
            "paper_id": "paper-arene",
            "doi": "10.1021/acs.jmedchem.3c02127",
            "candidate_id": "PAGE-arene-CAND-002",
            "compound_label": "R",
            "object_type": "variable_site",
            "crop_path": "/tmp/r.png",
        },
    ]
    source_rows = [{
        "Compound": "3",
        "SMILE": "CCN",
        "Kd Pu24T (uM)": "0.15",
    }]

    rows, unmatched = build_external_reference_rows(
        objects,
        source_rows,
        doi="10.1021/acs.jmedchem.3c02127",
        source_file="jm3c02127_si_002.csv",
        source_type="acs_figshare_si_csv",
        label_column="Compound",
        smiles_column="SMILE",
        source_locator_prefix="Compound=",
        mapping_status="numbered_label_matches_si_record",
        visual_match_status="requires_visual_graph_check",
    )

    assert len(rows) == 1
    assert rows[0]["compound_label"] == "3"
    assert rows[0]["smiles"] == "CCN"
    assert rows[0]["reference_status"] == "external_source_requires_visual_match"
    assert unmatched == []


def test_build_rows_applies_object_level_visual_match_review() -> None:
    objects = [{
        "object_id": "OBJ-3",
        "paper_rank": "5",
        "paper_id": "paper-arene",
        "doi": "10.1021/acs.jmedchem.3c02127",
        "candidate_id": "PAGE-arene-CAND-002",
        "compound_label": "3",
        "object_type": "molecule_series_member",
        "crop_path": "/tmp/3.png",
    }]
    source_rows = [{"Compound": "3", "SMILE": "CCN"}]

    rows, _ = build_external_reference_rows(
        objects,
        source_rows,
        doi="10.1021/acs.jmedchem.3c02127",
        source_file="jm3c02127_si_002.csv",
        source_type="acs_figshare_si_csv",
        label_column="Compound",
        smiles_column="SMILE",
        visual_review_by_object_id={"OBJ-3": {
            "review_status": "external_source_visual_match_confirmed",
            "visual_match_status": "pdf_figure_graph_confirmed",
        }},
    )

    assert rows[0]["reference_status"] == "external_source_visual_match_confirmed"
    assert rows[0]["visual_match_status"] == "pdf_figure_graph_confirmed"


def test_snapshot_is_auditable_and_preserves_raw_source_text(tmp_path: Path) -> None:
    output = tmp_path / "external.csv"
    summary = tmp_path / "summary.json"
    rows, result = write_external_reference_snapshot(
        [{
            "object_id": "OBJ-10",
            "paper_rank": "8",
            "paper_id": "paper-rgh",
            "doi": "10.1021/acs.jmedchem.3c01868",
            "candidate_id": "PAGE-rgh-CAND-001",
            "compound_label": "10",
            "object_type": "molecule_series_member",
            "crop_path": "/tmp/10.png",
        }],
        [{"Compound_ID": "10", "SMILES": "CCO |a:1,2|"}],
        doi="10.1021/acs.jmedchem.3c01868",
        source_file="jm3c01868_si_002.csv",
        source_type="acs_figshare_si_csv",
        label_column="Compound_ID",
        smiles_column="SMILES",
        source_locator_prefix="Compound_ID=",
        mapping_status="numbered_label_matches_si_record",
        visual_match_status="figure_label_confirmed_requires_visual_graph_check",
        output_path=output,
        summary_path=summary,
    )

    assert set(rows[0]) == set(EXTERNAL_REFERENCE_FIELDS)
    assert rows[0]["raw_source_smiles"] == "CCO |a:1,2|"
    assert rows[0]["smiles"] == "CCO"
    assert result["matched_rows"] == 1
    assert json.loads(summary.read_text(encoding="utf-8"))["matched_rows"] == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 1


def test_manifest_build_can_join_doi_from_candidate_index_when_object_snapshot_lacks_doi(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("Compound,SMILES\n3,CCN\n", encoding="utf-8")
    objects = [{
        "object_id": "OBJ-3",
        "paper_rank": "5",
        "paper_id": "paper-arene",
        "compound_label": "3",
        "object_type": "molecule_series_member",
    }]
    output = tmp_path / "external.csv"
    summary = tmp_path / "summary.json"

    rows, result = build_from_manifest(
        objects,
        [{
            "doi": "10.1021/example",
            "source_file": "source.csv",
            "source_type": "acs_figshare_si_csv",
            "delimiter": ",",
            "label_column": "Compound",
            "smiles_column": "SMILES",
        }],
        tmp_path,
        output,
        summary,
        doi_by_paper={"paper-arene": "10.1021/example"},
    )

    assert len(rows) == 1
    assert result["matched_rows"] == 1


def test_manifest_summary_reports_mixed_visual_review_state(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("Compound,SMILES\n3,CCN\n4,CCO\n", encoding="utf-8")
    objects = [{
        "object_id": f"OBJ-{label}",
        "paper_rank": "5",
        "paper_id": "paper-arene",
        "compound_label": label,
        "object_type": "molecule_series_member",
    } for label in ("3", "4")]

    _, result = build_from_manifest(
        objects,
        [{
            "doi": "10.1021/example",
            "source_file": "source.csv",
            "source_type": "acs_figshare_si_csv",
            "delimiter": ",",
            "label_column": "Compound",
            "smiles_column": "SMILES",
        }],
        tmp_path,
        tmp_path / "external.csv",
        tmp_path / "summary.json",
        doi_by_paper={"paper-arene": "10.1021/example"},
        visual_review_by_object_id={"OBJ-3": {
            "review_status": "external_source_visual_match_confirmed",
            "visual_match_status": "pdf_figure_graph_confirmed",
        }},
    )

    assert result["source_status"] == "external_records_mixed_review_state"
    assert result["reference_status_counts"] == {
        "external_source_visual_match_confirmed": 1,
        "external_source_requires_visual_match": 1,
    }
