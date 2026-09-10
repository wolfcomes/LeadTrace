import csv
import json
from pathlib import Path

from rdkit import Chem

from first_page_molecule_reconstruction import (
    RECONSTRUCTION_FIELDS,
    build_reconstruction_rows,
    choose_primary_component,
    classify_reconstruction,
    consensus_smiles,
    write_reconstruction_snapshot,
)


def molecule_object(label: str = "2a", object_type: str = "molecule_series_member") -> dict[str, str]:
    return {
        "object_id": f"OBJ-{label}",
        "paper_rank": "18",
        "paper_id": "paper-18",
        "title_guess": "A series",
        "candidate_id": "PAGE-series-CAND-001",
        "page": "2",
        "object_type": object_type,
        "object_role": "numbered_series_member",
        "compound_label": label,
        "crop_path": "/tmp/object.png",
        "smiles_source": "isolated_object_pending_ocsr",
        "review_status": "object_requires_human_review",
        "attachment_points": "--",
    }


def proposal(object_id: str, raw_smiles: str) -> dict[str, str]:
    return {
        "object_id": object_id,
        "raw_smiles": raw_smiles,
        "canonical_smiles": "--",
        "heuristic_primary_component_smiles": "--",
        "rdkit_status": "valid",
        "inference_status": "ok",
        "proposal_quality": "valid_but_suspicious_needs_review",
        "model_version": "test",
    }


def test_primary_component_rejects_metals_isotopes_and_repeated_noise() -> None:
    raw = "CCO.[Zn].[2H][2H]." + ".".join(["CCCC"] * 20)

    result = choose_primary_component(raw)

    assert result["cleaned_candidate_smiles"] == "CCO"
    assert result["removed_component_count"] == "22"
    assert result["selection_reason"] == "largest_plausible_organic_component"


def test_primary_component_does_not_choose_a_huge_carbon_noise_chain() -> None:
    raw = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC.C1=CC=CC=C1"

    result = choose_primary_component(raw)

    assert Chem.MolToSmiles(Chem.MolFromSmiles(result["cleaned_candidate_smiles"])) == "c1ccccc1"
    assert result["selection_reason"] == "largest_plausible_organic_component"


def test_consensus_requires_normalized_graph_agreement() -> None:
    result = consensus_smiles(["C(C)O", "CCO", "CCN"])

    assert result["consensus_smiles"] == "CCO"
    assert result["consensus_count"] == "2"
    assert result["variant_count"] == "3"
    assert result["consensus_state"] == "graph_consensus_found"


def test_fragments_are_not_promoted_to_whole_molecule_smiles() -> None:
    row = molecule_object("R1", "replacement_fragment")

    assert classify_reconstruction(row, {}) == {
        "reconstruction_status": "fragment_requires_attachment_review",
        "reconstructed_smiles": "--",
        "smiles_source": "attachment_point_notation_only",
    }


def test_build_rows_uses_exact_reference_before_model_candidate() -> None:
    objects = [molecule_object("10")]
    proposals = [proposal("OBJ-10", "CCN.[Zn]")]
    references = [{
        "doi": "10.1021/example",
        "compound_id": "10",
        "smiles": "C(C)O",
        "source_type": "supporting_information_csv",
        "source_file": "example_si.csv",
        "source_locator": "Compound=10",
    }]
    objects[0]["doi"] = "10.1021/example"

    rows = build_reconstruction_rows(objects, proposals, references)

    assert rows[0]["reconstructed_smiles"] == "CCO"
    assert rows[0]["reconstruction_status"] == "exact_source_confirmed"
    assert rows[0]["smiles_source"] == "supporting_information_csv"
    assert rows[0]["raw_model_smiles"] == "CCN.[Zn]"


def test_build_rows_keeps_external_source_as_pending_visual_match() -> None:
    objects = [molecule_object("10")]
    objects[0]["doi"] = "10.1021/acs.jmedchem.3c01868"
    proposals = [proposal("OBJ-10", "CCN.[Zn]")]
    external_references = [{
        "doi": "10.1021/acs.jmedchem.3c01868",
        "compound_label": "10",
        "source_label": "10 (individual enantiomer, unknown absolute stereochemistry)",
        "smiles": "C(C)O",
        "source_type": "acs_figshare_si_csv",
        "source_file": "jm3c01868_si_002.csv",
        "source_locator": "Compound_ID=10",
        "reference_status": "external_source_requires_visual_match",
        "visual_match_status": "requires_visual_graph_check",
    }]

    rows = build_reconstruction_rows(objects, proposals, external_references)

    assert rows[0]["reference_smiles"] == "C(C)O"
    assert rows[0]["reconstructed_smiles"] == "CCO"
    assert rows[0]["reconstruction_status"] == "external_source_requires_visual_match"
    assert rows[0]["reconstruction_confidence"] == "medium_pending_visual_match"
    assert rows[0]["smiles_source"] == "acs_figshare_si_csv"


def test_build_rows_can_record_visual_reviewed_model_candidate_without_external_source() -> None:
    objects = [molecule_object("2a")]
    proposals = [proposal("OBJ-2a", "CCO.[Zn]")]
    model_reviews = [{
        "object_id": "OBJ-2a",
        "review_status": "model_visual_match_confirmed",
        "visual_match_status": "pdf_figure_graph_confirmed",
        "review_basis": "Figure_1_and_RDKit_render",
    }]

    rows = build_reconstruction_rows(objects, proposals, [], model_visual_reviews=model_reviews)

    assert rows[0]["reconstructed_smiles"] == "CCO"
    assert rows[0]["reconstruction_status"] == "model_visual_match_confirmed"
    assert rows[0]["reconstruction_confidence"] == "medium_high_visual_review"
    assert rows[0]["smiles_source"] == "OCSR_visual_match_reviewed"


def test_snapshot_writes_auditable_fields_and_summary(tmp_path: Path) -> None:
    objects = [molecule_object("2a")]
    proposals = [proposal("OBJ-2a", "CCO.[Zn]")]
    output = tmp_path / "reconstructions.csv"
    summary = tmp_path / "summary.json"

    rows, result = write_reconstruction_snapshot(objects, proposals, [], output, summary)

    assert set(rows[0]) == set(RECONSTRUCTION_FIELDS)
    assert result["object_rows"] == 1
    assert result["candidate_rows"] == 1
    assert result["external_source_visual_match_confirmed"] == 0
    assert result["external_source_requires_visual_match"] == 0
    assert json.loads(summary.read_text(encoding="utf-8"))["object_rows"] == 1
    with output.open(newline="", encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 1


def test_snapshot_passes_model_visual_reviews_to_rows(tmp_path: Path) -> None:
    objects = [molecule_object("2a")]
    proposals = [proposal("OBJ-2a", "CCO.[Zn]")]
    output = tmp_path / "reconstructions.csv"
    summary = tmp_path / "summary.json"
    model_reviews = [{
        "object_id": "OBJ-2a",
        "review_status": "model_visual_match_confirmed",
    }]

    rows, result = write_reconstruction_snapshot(
        objects, proposals, [], output, summary,
        model_visual_reviews=model_reviews,
    )

    assert rows[0]["reconstruction_status"] == "model_visual_match_confirmed"
    assert result["model_visual_match_confirmed"] == 1
