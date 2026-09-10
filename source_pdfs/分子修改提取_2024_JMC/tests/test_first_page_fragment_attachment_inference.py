import csv
import json
from pathlib import Path

from rdkit import Chem

from first_page_fragment_attachment_inference import (
    ATTACHMENT_INFERENCE_FIELDS,
    build_fragment_inference_rows,
    write_fragment_inference_snapshot,
)


def fragment_object(
    object_id: str,
    *,
    paper_rank: str,
    paper_id: str,
    doi: str,
    candidate_id: str,
    label: str,
    object_type: str,
    attachment_points: str,
) -> dict[str, str]:
    return {
        "object_id": object_id,
        "paper_rank": paper_rank,
        "paper_id": paper_id,
        "doi": doi,
        "candidate_id": candidate_id,
        "page": "2",
        "object_type": object_type,
        "compound_label": label,
        "attachment_points": attachment_points,
        "crop_path": "/tmp/fragment.png",
        "parent_object_id": "--",
    }


def test_linker_is_emitted_as_a_two_endpoint_fragment() -> None:
    objects = [fragment_object(
        "OBJ-linker-a",
        paper_rank="4",
        paper_id="paper-4",
        doi="10.1021/acs.jmedchem.3c01980",
        candidate_id="PAGE-621e2220dc85-CAND-001",
        label="Linker a",
        object_type="linker_fragment",
        attachment_points="Linker a",
    )]

    rows = build_fragment_inference_rows(objects, [])

    assert rows[0]["attachment_status"] == "attachment_points_inferred"
    assert rows[0]["fragment_smiles"] == "[*:1]c1ccc(CC[*:2])cc1"
    assert rows[0]["assembled_smiles"] == "--"
    assert rows[0]["attachment_count"] == "2"
    assert Chem.MolFromSmiles(rows[0]["fragment_smiles"]) is not None


def test_source_anchored_fragment_keeps_full_candidate_pending_review() -> None:
    objects = [fragment_object(
        "OBJ-paper18-3",
        paper_rank="18",
        paper_id="paper-18",
        doi="10.1021/acs.jmedchem.4c02616",
        candidate_id="PAGE-880042186935-CAND-001",
        label="3",
        object_type="replacement_fragment",
        attachment_points="Site 1",
    )]
    source_records = [{
        "doi": "10.1021/acs.jmedchem.4c02616",
        "compound_label": "3",
        "smiles": "CCO",
        "source_file": "jm4c02616_si_003.csv",
        "source_locator": "Compound_ID=3",
    }]

    rows = build_fragment_inference_rows(objects, source_records)

    assert rows[0]["assembly_status"] == "source_anchored_whole_molecule_candidate"
    assert rows[0]["assembled_smiles"] == "CCO"
    assert rows[0]["review_status"] == "candidate_requires_human_review"
    assert rows[0]["source_evidence"] == "acs_figshare_si_csv"


def test_unknown_fragment_is_not_promoted_to_a_whole_molecule() -> None:
    objects = [fragment_object(
        "OBJ-unknown",
        paper_rank="14",
        paper_id="paper-14",
        doi="10.1021/example",
        candidate_id="PAGE-d867a063e9f9-CAND-001",
        label="R4",
        object_type="replacement_fragment",
        attachment_points="R4",
    )]

    rows = build_fragment_inference_rows(objects, [])

    assert rows[0]["attachment_status"] == "insufficient_visual_evidence"
    assert rows[0]["fragment_smiles"] == "--"
    assert rows[0]["assembled_smiles"] == "--"
    assert rows[0]["review_status"] == "candidate_requires_human_review"


def test_snapshot_writes_fragment_inference_fields_and_summary(tmp_path: Path) -> None:
    objects = [fragment_object(
        "OBJ-linker-a",
        paper_rank="4",
        paper_id="paper-4",
        doi="10.1021/acs.jmedchem.3c01980",
        candidate_id="PAGE-621e2220dc85-CAND-001",
        label="Linker a",
        object_type="linker_fragment",
        attachment_points="Linker a",
    )]
    output = tmp_path / "fragment_inferences.csv"
    summary = tmp_path / "summary.json"

    rows, result = write_fragment_inference_snapshot(objects, [], output, summary)

    assert set(rows[0]) == set(ATTACHMENT_INFERENCE_FIELDS)
    assert result["object_rows"] == 1
    assert result["attachment_points_inferred"] == 1
    assert json.loads(summary.read_text(encoding="utf-8"))["object_rows"] == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 1
