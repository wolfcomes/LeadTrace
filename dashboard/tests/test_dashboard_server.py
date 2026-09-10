import json
import csv
from pathlib import Path
import threading
from urllib.request import Request, urlopen

import pytest

from dashboard import server


def test_overview_keeps_project_layers_separate() -> None:
    overview = server.load_overview()

    assert overview["counts"] == {
        "papers": 672,
        "pages": 13695,
        "evidence": 6939,
        "candidate_records": 5178,
        "explicit_paths": 16,
        "structure_crops": 4,
        "confirmed_paths": 0,
        "structure_slots": 32,
    }
    assert overview["quality"]["rdkit_valid"] >= 2
    assert overview["quality"]["rdkit_invalid"] >= 2
    assert overview["quality"]["inference_errors"] == 0
    assert overview["stages"][-1]["id"] == "confirmed"
    assert overview["stages"][-1]["status"] == "pending"


def test_overview_exposes_page_structure_ocr_progress_separately() -> None:
    ocr = server.load_overview()["structure_ocr"]

    assert ocr["candidate_rows"] == 880
    assert ocr["attempted_rows"] == 880
    assert ocr["pending_rows"] == 0
    assert ocr["valid_rdkit_rows"] == 530
    assert ocr["invalid_rdkit_rows"] == 350


def test_overview_does_not_load_first_page_paper_or_object_display_snapshot() -> None:
    overview = server.load_overview()
    index_source = server.DASHBOARD_ROOT.joinpath("index.html").read_text(encoding="utf-8")
    app_source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "first_page_structure" not in overview
    assert "firstPageStructureReview" not in index_source
    assert "renderFirstPageStructure" not in app_source


def test_paper_detail_includes_filtered_structure_objects_section() -> None:
    app_source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "renderPaperObjects" in app_source
    assert "paper-objects-section" in app_source
    assert 'data-detail-anchor="paper-objects-section"' in app_source


def test_paper_detail_renders_compound_lineage_before_objects_and_review_items() -> None:
    app_source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "renderCompoundLineages" in app_source
    assert "compound-lineage-section" in app_source
    assert 'data-detail-anchor="compound-lineage-section"' in app_source
    assert "ROOT TEMPLATE" in app_source
    assert "DIRECT PARENT" in app_source
    assert app_source.index("${renderCompoundLineages(detail)}") < app_source.index("${renderPaperObjects(detail)}")


def test_first_page_fragment_review_exposes_visual_scope_and_accuracy_gates() -> None:
    review = server.load_first_page_fragment_review()

    assert review["summary"]["papers"] == 20
    assert review["summary"]["candidate_rows"] == 31
    assert len(review["papers"]) == 20
    assert len(review["items"]) == 31
    assert review["summary"]["visual_scope_counts"]["fragment_or_series"] == 9
    assert review["summary"]["visual_scope_counts"]["non_structure_region"] == 13
    assert review["items"][0]["crop_url"].startswith("/assets/structure-ocr-crops/")
    assert review["items"][0]["human_review_status"] == "proposal_only_pending_human_review"
    assert "smiles_accuracy_state" in review["items"][0]


def test_first_page_review_exposes_molecule_level_objects_without_page_ocr_smiles() -> None:
    review = server.load_first_page_fragment_review()

    objects = review["molecule_objects"]
    assert review["molecule_summary"]["candidate_rows"] == 31
    assert review["molecule_summary"]["object_rows"] == 121
    assert len(objects) == 121
    assert {item["compound_label"] for item in objects if item["candidate_id"] == "PAGE-5d639341273b-CAND-001"} >= {"1", "2a", "2o"}
    assert sum(item["rdkit_status"] != "not_run" for item in objects) == 36
    assert all(item["review_status"] == "object_requires_human_review" for item in objects)
    assert all(item["rdkit_status"] == "not_run" for item in objects if item["smiles_source"] != "isolated_object_pending_ocsr")
    assert any(item["object_type"] == "linker_fragment" for item in objects)
    assert all(item["object_type"] not in {"non_structure_region", "three_d_structure_evidence"} for item in objects)
    assert any(item["crop_url"].startswith("/assets/molecule-review-crops/") for item in objects)


def test_first_page_fragment_inferences_are_indexed_with_safe_missing_values() -> None:
    inference = server.load_first_page_fragment_inferences()

    assert inference["summary"]["object_rows"] == 37
    assert inference["summary"]["fragment_smiles_rows"] == 20
    assert inference["summary"]["assembled_candidate_rows"] == 17
    linker = next(
        row for row in inference["rows"]
        if row["paper_id"] == "d8e4f69200f7" and row["compound_label"] == "Linker a"
    )
    assert linker["crop_url"].startswith("/assets/molecule-review-crops/")
    assert linker["fragment_smiles"] == "[*:1]c1ccc(CC[*:2])cc1"
    assert linker["assembled_smiles"] == "--"
    assert inference["by_object_id"][linker["object_id"]] is linker


def test_first_page_molecule_objects_attach_fragment_inference_without_promoting_candidates() -> None:
    review = server.load_first_page_fragment_review()
    by_label = {
        (item["paper_id"], item["compound_label"]): item
        for item in review["molecule_objects"]
    }

    linker = by_label[("d8e4f69200f7", "Linker a")]
    assert linker["attachment_inference"]["attachment_count"] == 2
    assert linker["attachment_inference"]["fragment_smiles"] == "[*:1]c1ccc(CC[*:2])cc1"
    assert linker["attachment_inference"]["assembled_smiles"] == "--"
    assert linker["attachment_inference"]["review_status"] == "candidate_requires_human_review"
    assert "confirmed_smiles" not in linker["attachment_inference"]

    candidate = next(
        item for item in review["molecule_objects"]
        if item["object_id"] == "OBJ-PAGE-889b08022bee-CAND-003-OBJ-001"
    )
    assert candidate["attachment_inference"]["assembled_smiles"]
    assert candidate["attachment_inference"]["assembly_status"] == "source_anchored_whole_molecule_candidate"
    assert candidate["attachment_inference"]["review_status"] == "candidate_requires_human_review"

    duplicate_label = next(
        item for item in review["molecule_objects"]
        if item["object_id"] == "OBJ-PAGE-d79ad4b6d9ff-CAND-001-OBJ-002"
    )
    assert duplicate_label["compound_label"] == "11"
    assert duplicate_label["attachment_inference"]["assembled_smiles"] == "--"

    missing = by_label[("f25aa649b48e", "R4")]
    assert missing["attachment_inference"]["fragment_smiles"] == "--"
    assert missing["attachment_inference"]["assembled_smiles"] == "--"
    assert missing["attachment_inference"]["attachment_status"] == "insufficient_visual_evidence"

    summary = review["molecule_summary"]
    assert summary["fragment_inference_rows"] == 37
    assert summary["fragment_smiles_rows"] == 20
    assert summary["assembled_candidate_rows"] == 17
    assert summary["attachment_status_counts"]["insufficient_visual_evidence"] == 15


def test_path_queue_supports_explicit_search_and_pagination() -> None:
    result = server.load_paths(scope="explicit", query="5-fluoro", page=1, page_size=5)

    assert result["total"] == 1
    assert {item["visual_review_id"] for item in result["items"]} == {"VIS-0012"}
    assert result["page_count"] == 1


def test_paper_catalog_has_672_records_and_20_item_pages() -> None:
    first_page = server.load_papers(page=1)
    second_page = server.load_papers(page=2)
    last_page = server.load_papers(page=34)

    assert first_page["total"] == 672
    assert first_page["page_size"] == 20
    assert first_page["page_count"] == 34
    assert len(first_page["items"]) == 20
    assert len(second_page["items"]) == 20
    assert len(last_page["items"]) == 12
    assert len({item["paper_id"] for item in first_page["items"]}) == 20
    assert first_page["items"][0]["paper_id"]
    assert first_page["items"][0]["title"]


def test_paper_catalog_preserves_manifest_order() -> None:
    first_page = server.load_papers(page=1)

    assert [item["paper_id"] for item in first_page["items"][:3]] == [
        "04effc6577c7",
        "b72748fcd28a",
        "e04dfea8eedb",
    ]


def test_paper_catalog_exposes_layer_counts_and_distinct_workflow_statuses() -> None:
    papers = server.load_papers(page=1, page_size=672)["items"]
    by_id = {item["paper_id"]: item for item in papers}

    assert by_id["04effc6577c7"]["workflow_status"] == "path_review"
    assert all(item["review_status"] == "unreviewed" for item in papers)
    assert all("evidence_count" in item and "candidate_count" in item for item in papers)
    assert {item["workflow_status"] for item in papers} >= {"path_review", "text_ready"}


def test_paper_catalog_supports_lineage_filter_without_changing_primary_workflow_status() -> None:
    result = server.load_papers(status="lineage", page=1, page_size=672)
    lineage_summary = server.load_compound_lineages()["summary"]

    assert result["total"] == lineage_summary["lineage_paper_rows"]
    assert {item["paper_id"] for item in result["items"]} >= {
        "7a695794fc7b", "9f857ab2a7e1", "613829463ff3",
    }
    assert all(item["lineage_edge_count"] > 0 for item in result["items"])
    assert all(item["workflow_status"] != "lineage" for item in result["items"])


def test_pipeline_filter_exposes_lineage_without_confirmed_option() -> None:
    html = server.DASHBOARD_ROOT.joinpath("index.html").read_text(encoding="utf-8")

    assert 'value="lineage"' in html
    assert 'value="confirmed"' not in html


def test_paper_catalog_exposes_image_molecule_and_pair_counts() -> None:
    papers = server.load_papers(page=1, page_size=672)["items"]
    by_id = {item["paper_id"]: item for item in papers}

    assert by_id["75843eeb816b"]["molecule_object_count"] == 22
    assert by_id["75843eeb816b"]["molecule_pair_count"] == 61
    assert by_id["7a695794fc7b"]["molecule_object_count"] == 27
    assert by_id["7a695794fc7b"]["molecule_pair_count"] == 21
    assert by_id["7a695794fc7b"]["lineage_count"] == 2
    assert by_id["7a695794fc7b"]["lineage_edge_count"] == 25
    assert by_id["04effc6577c7"]["molecule_object_count"] == 0
    assert by_id["04effc6577c7"]["molecule_pair_count"] == 22


def test_paper_detail_aggregates_all_linked_layers() -> None:
    detail = server.load_paper_detail("04effc6577c7")

    assert detail["paper"]["paper_id"] == "04effc6577c7"
    assert len(detail["evidence"]) == 34
    assert len(detail["candidates"]) == 33
    assert len(detail["explicit_paths"]) == 2
    assert len(detail["structures"]) == 2
    assert detail["structures"][0]["parent_canonical_smiles"]
    assert all("proposals" in path for path in detail["explicit_paths"])


def test_paper_detail_exposes_its_image_first_molecule_objects_and_attachment_inferences() -> None:
    detail = server.load_paper_detail("d8e4f69200f7")

    assert detail["paper"]["detail_counts"]["molecule_objects"] == 50
    assert detail["paper"]["detail_counts"]["attachment_inferences"] == 5
    assert len(detail["molecule_objects"]) == 50
    linker = next(item for item in detail["molecule_objects"] if item["compound_label"] == "Linker a")
    assert linker["attachment_inference"]["fragment_smiles"] == "[*:1]c1ccc(CC[*:2])cc1"
    assert linker["attachment_inference"]["assembly_status"] == "fragment_only_requires_parent_assembly"
    assert detail["molecule_object_summary"] == {
        "object_rows": 50,
        "attachment_inference_rows": 5,
        "fragment_smiles_rows": 5,
        "assembled_candidate_rows": 0,
    }


def test_paper_detail_exposes_unified_review_items_with_missing_values() -> None:
    detail = server.load_paper_detail("04effc6577c7")

    assert len(detail["review_items"]) == 57
    lineage_items = [item for item in detail["review_items"] if item["source_kind"] == "molecule_pair"]
    assert len(lineage_items) == 22
    assert all(item["molecule_pair"]["parent_object_id"] == "--" for item in lineage_items)
    path_item = next(item for item in detail["review_items"] if item["candidate"]["path_candidate_id"] == "PATH-0000301")
    assert path_item["path"]["visual_review_id"] == "VIS-0001"
    assert path_item["structure"]["parent_canonical_smiles"]
    assert "activity" in path_item
    evidence_only = next(item for item in detail["review_items"] if item["candidate"] is None)
    assert evidence_only["path"] is None
    assert evidence_only["structure"] is None


def test_paper_detail_promotes_eligible_lineage_edges_to_unified_pair_review_items() -> None:
    detail = server.load_paper_detail("7a695794fc7b")

    pair_items = [item for item in detail["review_items"] if item["source_kind"] == "molecule_pair"]

    assert len(pair_items) == 21
    assert len({item["review_item_id"] for item in pair_items}) == 21
    item = next(
        item for item in pair_items
        if item["candidate"]["parent_compound"].startswith("1 / danuglipron")
        and item["candidate"]["derived_compound"] == "3"
    )
    assert item["review_item_id"].startswith("EDGE-7a695794fc7b-")
    assert item["candidate"]["parent_compound"] == "1 / danuglipron"
    assert item["candidate"]["derived_compound"] == "3"
    assert item["candidate"]["relation_type"] == "bioisosteric_replacement"
    assert item["review_status"] == "unreviewed"
    assert item["molecule_pair"]["pair_kind"] == "compound_optimization_lineage"
    assert item["molecule_pair"]["root_template_label"] == "1 / danuglipron"
    assert item["molecule_pair"]["parent_smiles"] != "--"
    assert item["molecule_pair"]["derived_smiles"] != "--"
    assert item["structure"] is None


def test_object_scaffold_associations_do_not_create_medicinal_chemistry_pairs() -> None:
    detail = server.load_paper_detail("7a695794fc7b")
    object_ids = {item["object_id"] for item in detail["molecule_objects"]}

    for item in detail["review_items"]:
        if item.get("source_kind") != "molecule_pair":
            continue
        pair = item["molecule_pair"]
        assert pair.get("parent_object_id") not in object_ids
        assert pair.get("derived_object_id") not in object_ids
        assert item["candidate"]["parent_compound"] != "shared scaffold"
        assert not item["candidate"]["derived_compound"].startswith("Site ")


def test_paper_detail_exposes_compound_optimization_lineages() -> None:
    detail = server.load_paper_detail("7a695794fc7b")

    assert len(detail["compound_lineages"]) == 2
    assert len(detail["compound_entities"]) == 27
    assert len(detail["compound_lineage_edges"]) == 25
    assert detail["paper"]["detail_counts"]["lineages"] == 2
    assert detail["paper"]["detail_counts"]["lineage_edges"] == 25
    assert detail["paper"]["detail_counts"]["unresolved_lineage_edges"] == 3

    first = detail["compound_lineages"][0]
    assert first["root_template"]["normalized_label"] == "1"
    assert first["root_template"]["preferred_name"] == "danuglipron"
    assert {(edge["parent_label"], edge["derived_label"]) for edge in first["edges"]} >= {
        ("1", "3"), ("3", "5"), ("3", "21"),
    }


def test_only_pair_eligible_lineage_edges_enter_unified_review() -> None:
    detail = server.load_paper_detail("7a695794fc7b")
    pairs = [item for item in detail["review_items"] if item["source_kind"] == "molecule_pair"]

    assert len(pairs) == 21
    assert all(item["molecule_pair"]["pair_kind"] == "compound_optimization_lineage" for item in pairs)
    assert all(item["molecule_pair"]["parent_object_id"] == "--" for item in pairs)
    assert all(
        (item["candidate"]["parent_compound"], item["candidate"]["derived_compound"])
        != ("2n", "23")
        for item in pairs
    )
    assert all(item["molecule_pair"]["derived_object_id"] == "--" for item in pairs)
    assert all(item["molecule_pair"]["root_template_entity_id"] for item in pairs)
    assert not any(item["candidate"]["derived_compound"] in {"25", "26", "27"} for item in pairs)


def test_molecule_pair_review_item_has_stable_identity_and_does_not_duplicate_text_path() -> None:
    first = server.load_paper_detail("75843eeb816b")
    second = server.load_paper_detail("75843eeb816b")

    first_pairs = [item for item in first["review_items"] if item["source_kind"] == "molecule_pair"]
    second_pairs = [item for item in second["review_items"] if item["source_kind"] == "molecule_pair"]

    assert [item["review_item_id"] for item in first_pairs] == [item["review_item_id"] for item in second_pairs]
    assert not any(item["review_item_id"] == "PATH-0000073" for item in first_pairs)


def test_molecule_pair_review_item_uses_existing_edit_and_confirmation_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    reviewed_path = tmp_path / "reviewed_entries.csv"
    monkeypatch.setattr(server, "PAPER_REVIEWED_ENTRIES_PATH", reviewed_path)
    item_id = next(
        item["review_item_id"]
        for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    saved = server.save_review_item(
        "7a695794fc7b", item_id,
        {"review_status": "in_review", "review_note": "Check image connectivity."},
    )
    assert saved["review_status"] == "in_review"
    confirmed = server.confirm_review_item("7a695794fc7b", item_id)

    assert confirmed["review_status"] == "reviewed"
    rows = server.read_csv_rows(reviewed_path)
    assert any(row["review_item_id"] == item_id and row["source_kind"] == "molecule_pair" for row in rows)
    with pytest.raises(server.ReviewItemLocked):
        server.delete_review_item("7a695794fc7b", item_id)


def test_molecule_pair_confirmation_syncs_inferred_structure_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    reviewed_path = tmp_path / "reviewed_entries.csv"
    monkeypatch.setattr(server, "PAPER_REVIEWED_ENTRIES_PATH", reviewed_path)
    item = next(
        item for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
        and item["candidate"]["derived_compound"] == "3"
    )

    confirmed = server.confirm_review_item("7a695794fc7b", item["review_item_id"])

    assert confirmed["review_status"] == "reviewed"
    row = next(
        row for row in server.read_csv_rows(reviewed_path)
        if row["review_item_id"] == item["review_item_id"]
    )
    assert row["source_kind"] == "molecule_pair"
    assert row["pair_kind"] == "compound_optimization_lineage"
    assert row["parent_object_id"] == "--"
    assert row["derived_object_id"] == "--"
    assert row["root_template"] == "1 / danuglipron"
    assert row["parent_entity_id"] == item["molecule_pair"]["parent_entity_id"]
    assert row["derived_entity_id"] == item["molecule_pair"]["derived_entity_id"]
    assert row["parent_smiles"] == item["molecule_pair"]["parent_smiles"]
    assert row["derived_smiles"] == item["molecule_pair"]["derived_smiles"]


def test_confirm_preserves_saved_molecule_pair_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    reviewed_path = tmp_path / "reviewed_entries.csv"
    monkeypatch.setattr(server, "PAPER_REVIEWED_ENTRIES_PATH", reviewed_path)
    item_id = next(
        item["review_item_id"] for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    server.save_review_item(
        "7a695794fc7b",
        item_id,
        {
            "review_status": "in_review",
            "parent_compound": "shared scaffold (reviewed)",
            "fragment_smiles": "[*:1]C1CCN(C(C)C)CC1",
            "assembled_smiles": "CCO",
            "review_note": "Connection checked against the source figure.",
        },
    )
    server.confirm_review_item("7a695794fc7b", item_id)

    row = next(row for row in server.read_csv_rows(reviewed_path) if row["review_item_id"] == item_id)
    assert row["parent_compound"] == "shared scaffold (reviewed)"
    assert row["assembled_smiles"] == "CCO"
    assert row["review_note"] == "Connection checked against the source figure."


def test_dashboard_exposes_molecule_pair_specific_edit_fields() -> None:
    source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "MOLECULE_PAIR_FIELD_GROUP" in source
    assert "fragment_smiles: moleculePair.fragment_smiles" in source
    assert "assembled_smiles: moleculePair.assembled_smiles" in source
    assert "renderMoleculePairFields(item)" in source


def test_molecule_pair_fragment_smiles_accepts_mapped_attachment_atoms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = next(
        item["review_item_id"] for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    server.save_review_item(
        "7a695794fc7b", item_id,
        {"fragment_smiles": "[*:1]C1CCN(C(C)C)CC1"},
    )

    item = next(
        item for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["review_item_id"] == item_id
    )
    assert item["molecule_pair"]["fragment_smiles"] == "[*:1]C1CCN(C(C)C)CC1"


def test_molecule_pair_smiles_rejects_whitespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = next(
        item["review_item_id"] for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    with pytest.raises(ValueError, match="fragment_smiles must contain a valid SMILES format"):
        server.save_review_item(
            "7a695794fc7b", item_id,
            {"fragment_smiles": "[*:1] invalid"},
        )


def test_molecule_pair_complete_candidate_gets_rdkit_structure_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "MOLECULE_PAIR_STRUCTURES_ROOT", tmp_path)
    item = next(
        item for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    pair = item["molecule_pair"]

    assert pair["parent_smiles"] != "--"
    assert pair["derived_smiles"] != "--"
    assert "complete_structure_image_url" not in pair
    for image_url in (
        pair["parent_complete_structure_image_url"],
        pair["derived_complete_structure_image_url"],
    ):
        assert image_url.startswith("/assets/molecule-pair-structures/")
        image_path = server.resolve_asset("molecule-pair-structures", Path(image_url).name)
        assert image_path.is_file()


def test_molecule_pair_missing_side_only_omits_that_structure_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "MOLECULE_PAIR_STRUCTURES_ROOT", tmp_path)
    pair = {"parent_smiles": "CCO", "derived_smiles": "--"}

    server._refresh_molecule_pair_structures(pair)

    assert pair["parent_complete_structure_image_url"].startswith("/assets/molecule-pair-structures/")
    assert pair["derived_complete_structure_image_url"] == ""
    assert len(list(tmp_path.iterdir())) == 1


def test_molecule_pair_renderer_uses_complete_rdkit_image_before_source_crops() -> None:
    source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "parent_complete_structure_image_url" in source
    assert "derived_complete_structure_image_url" in source
    assert "BEFORE / PARENT COMPLETE MOLECULE" in source
    assert "AFTER / DERIVED COMPLETE MOLECULE" in source
    assert "molecule-pair-complete-structure" in source
    assert "molecule-pair-source-evidence" in source
    assert source.index("molecule-pair-complete-structure") < source.index("molecule-pair-source-evidence")


def test_paper_detail_does_not_render_molecule_object_section_or_tab() -> None:
    source = server.DASHBOARD_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "renderPaperMoleculeObjectReview(detail)" not in source
    assert "molecule-objects-section" not in source


def test_molecule_pair_redraws_when_derived_smiles_is_revised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(server, "MOLECULE_PAIR_STRUCTURES_ROOT", tmp_path / "structures")
    item_id = next(
        item["review_item_id"] for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    server.save_review_item(
        "7a695794fc7b", item_id,
        {"derived_smiles": "CCO"},
    )
    revised = next(
        item for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["review_item_id"] == item_id
    )

    assert revised["molecule_pair"]["derived_smiles"] == "CCO"
    assert revised["molecule_pair"]["assembled_smiles"] == "--"
    assert revised["molecule_pair"]["derived_complete_structure_image_url"].endswith(".png")
    revised_image = server.resolve_asset(
        "molecule-pair-structures",
        Path(revised["molecule_pair"]["derived_complete_structure_image_url"]).name,
    )
    assert revised_image.is_file()


def test_molecule_pair_redraws_parent_when_parent_smiles_is_revised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(server, "MOLECULE_PAIR_STRUCTURES_ROOT", tmp_path / "structures")
    item_id = next(
        item["review_item_id"] for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["source_kind"] == "molecule_pair"
    )

    server.save_review_item(
        "7a695794fc7b", item_id,
        {"parent_smiles": "CCO"},
    )
    revised = next(
        item for item in server.load_paper_detail("7a695794fc7b")["review_items"]
        if item["review_item_id"] == item_id
    )

    assert revised["molecule_pair"]["parent_smiles"] == "CCO"
    assert revised["molecule_pair"]["parent_complete_structure_image_url"].endswith(".png")
    parent_image = server.resolve_asset(
        "molecule-pair-structures",
        Path(revised["molecule_pair"]["parent_complete_structure_image_url"]).name,
    )
    assert parent_image.is_file()


def test_paper_detail_exposes_auto_fill_and_generic_structure_notation() -> None:
    detail = server.load_paper_detail("b72748fcd28a")

    generic = next(
        item for item in detail["review_items"]
        if item.get("auto_fill", {}).get("structure_representation_kind") == "linker_notation"
    )
    assert generic["auto_fill"]["auto_fill_status"] == "text_populated_generic_structure"
    assert generic["structure"]["structure_expression"]
    assert generic["structure"]["structure_source"] == "pdf_text_generic_notation"


def test_paper_detail_attaches_structure_ocr_proposals_to_matching_review_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proposals_path = tmp_path / "structure_ocr_proposals.csv"
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    (crop_root / "candidate.png").write_bytes(b"png")
    with proposals_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "candidate_id", "page_candidate_id", "paper_id", "doi", "source_pdf", "page",
            "region_kind", "crop_path", "x0", "y0", "x1", "y1", "candidate_score",
            "source_queue_item_ids", "compound_ids", "raw_smiles", "token_confidences",
            "mean_token_confidence", "min_token_confidence", "inference_status", "inference_error",
            "rdkit_status", "canonical_smiles", "model_version", "proposal_quality", "review_status",
        ])
        writer.writeheader()
        writer.writerow({
            "candidate_id": "PAGE-1-CAND-1", "page_candidate_id": "PAGE-1", "paper_id": "04effc6577c7",
            "doi": "10.1021/example", "source_pdf": "/tmp/paper.pdf", "page": "5",
            "region_kind": "embedded_image", "crop_path": str(crop_root / "candidate.png"),
            "x0": "1", "y0": "2", "x1": "3", "y1": "4", "candidate_score": "5",
            "source_queue_item_ids": "PATH-0000301", "compound_ids": "12d | 12g", "raw_smiles": "CCO",
            "token_confidences": "[]", "mean_token_confidence": "0.9", "min_token_confidence": "0.9",
            "inference_status": "ok", "inference_error": "", "rdkit_status": "valid",
            "canonical_smiles": "CCO", "model_version": "2.7.2", "proposal_quality": "valid_but_needs_review",
            "review_status": "proposal_requires_human_review",
        })
    monkeypatch.setattr(server, "STRUCTURE_OCR_PROPOSALS_PATH", proposals_path)
    monkeypatch.setattr(server, "STRUCTURE_OCR_CROPS_ROOT", crop_root)

    detail = server.load_paper_detail("04effc6577c7")

    item = next(item for item in detail["review_items"] if item["review_item_id"] == "PATH-0000301")
    assert item["proposals"][0]["canonical_smiles"] == "CCO"
    assert item["proposals"][0]["crop_url"].startswith("/assets/structure-ocr-crops/")
    assert item["proposals"][0]["review_status"] == "proposal_requires_human_review"


def test_review_item_override_is_persisted_separately_from_source_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    detail = server.load_paper_detail("04effc6577c7")
    item_id = detail["review_items"][0]["review_item_id"]

    saved = server.save_review_item(
        "04effc6577c7",
        item_id,
        {"review_status": "in_review", "review_note": "Check activity wording."},
    )

    assert saved["review_status"] == "in_review"
    refreshed = server.load_paper_detail("04effc6577c7")
    refreshed_item = next(item for item in refreshed["review_items"] if item["review_item_id"] == item_id)
    assert refreshed_item["review_status"] == "in_review"
    assert refreshed_item["review_note"] == "Check activity wording."


def test_review_item_rejects_unknown_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")

    with pytest.raises(server.ReviewItemNotFound):
        server.save_review_item("04effc6577c7", "missing-item", {"review_status": "in_review"})


def test_review_item_content_override_uses_typed_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    detail = server.load_paper_detail("04effc6577c7")
    item_id = next(item["review_item_id"] for item in detail["review_items"] if item["candidate"])

    server.save_review_item(
        "04effc6577c7",
        item_id,
        {
            "page": "12",
            "parent_compound": "12d",
            "derived_compound": "12g",
            "reported_from_group": "phenyl ring",
            "reported_to_group": "thiophene",
            "activity": "decreased activity",
            "evidence_text": "Revised evidence text.",
            "parent_smiles": "CCO",
            "derived_smiles": "CCN",
            "review_status": "in_review",
        },
    )

    updated = next(item for item in server.load_paper_detail("04effc6577c7")["review_items"] if item["review_item_id"] == item_id)
    assert updated["page"] == 12
    assert updated["candidate"]["parent_compound"] == "12d"
    assert updated["activity"] == "decreased activity"
    assert updated["evidence"]["evidence_text"] == "Revised evidence text."
    assert updated["structure"]["parent_canonical_smiles"] == "CCO"


def test_review_item_rejects_invalid_field_formats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = server.load_paper_detail("04effc6577c7")["review_items"][0]["review_item_id"]

    with pytest.raises(ValueError, match="page"):
        server.save_review_item("04effc6577c7", item_id, {"page": "page twelve"})
    with pytest.raises(ValueError, match="SMILES"):
        server.save_review_item("04effc6577c7", item_id, {"parent_smiles": "not a smiles!"})


def test_review_item_can_be_added_and_deleted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")

    created = server.add_review_item(
        "04effc6577c7",
        {
            "page": "9",
            "parent_compound": "9a",
            "derived_compound": "9b",
            "activity": "IC50 10 nM",
            "evidence_text": "Manual review entry.",
        },
    )
    item_id = created["review_item_id"]
    assert any(item["review_item_id"] == item_id for item in server.load_paper_detail("04effc6577c7")["review_items"])

    server.delete_review_item("04effc6577c7", item_id)
    assert all(item["review_item_id"] != item_id for item in server.load_paper_detail("04effc6577c7")["review_items"])


def test_new_review_item_cannot_start_as_reviewed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")

    with pytest.raises(ValueError, match="confirm endpoint"):
        server.add_review_item(
            "04effc6577c7",
            {"review_status": "reviewed", "evidence_text": "Must be confirmed"},
        )


def test_existing_review_item_cannot_be_marked_reviewed_without_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = server.load_paper_detail("04effc6577c7")["review_items"][0]["review_item_id"]

    with pytest.raises(ValueError, match="confirm endpoint"):
        server.save_review_item("04effc6577c7", item_id, {"review_status": "reviewed"})


def test_added_and_deleted_items_respect_locked_paper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    server.save_review_override("04effc6577c7", {"review_status": "reviewed"})

    with pytest.raises(server.ReviewLocked):
        server.add_review_item("04effc6577c7", {"page": "9", "evidence_text": "Blocked"})
    existing_item_id = server.load_paper_detail("04effc6577c7")["review_items"][0]["review_item_id"]
    with pytest.raises(server.ReviewLocked):
        server.delete_review_item("04effc6577c7", existing_item_id)


def test_confirm_review_item_writes_curated_total_table_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    reviewed_path = tmp_path / "reviewed_entries.csv"
    monkeypatch.setattr(server, "PAPER_REVIEWED_ENTRIES_PATH", reviewed_path)
    item_id = server.load_paper_detail("04effc6577c7")["review_items"][0]["review_item_id"]

    result = server.confirm_review_item("04effc6577c7", item_id)

    assert result["review_status"] == "reviewed"
    assert reviewed_path.is_file()
    rows = server.read_csv_rows(reviewed_path)
    assert any(row["paper_id"] == "04effc6577c7" and row["review_item_id"] == item_id for row in rows)

    with pytest.raises(server.ReviewItemLocked):
        server.save_review_item("04effc6577c7", item_id, {"activity": "changed after confirmation"})


def test_review_override_is_atomic_and_merges_into_paper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override_path = tmp_path / "09_paper_review" / "paper_review_overrides.json"
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", override_path)

    saved = server.save_review_override(
        "04effc6577c7",
        {
            "review_status": "in_review",
            "title_override": "Revised title",
            "correction_note": "Check the scheme reference.",
            "review_note": "Started review.",
        },
    )

    assert saved["review_status"] == "in_review"
    assert override_path.is_file()
    assert server.load_papers(page=1)["items"][0]["review_status"] == "in_review"
    assert server.load_paper_detail("04effc6577c7")["paper"]["title"] == "Revised title"


def test_review_override_rejects_unknown_paper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")

    with pytest.raises(server.PaperNotFound):
        server.save_review_override("missing-paper", {"review_status": "in_review"})


def test_reviewed_paper_cannot_be_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    server.save_review_override("04effc6577c7", {"review_status": "reviewed", "review_note": "Final"})

    with pytest.raises(server.ReviewLocked):
        server.save_review_override("04effc6577c7", {"review_status": "needs_follow_up"})


def test_unresolved_queue_filters_priority_without_loading_every_row() -> None:
    result = server.load_paths(scope="unresolved", priority="high", page=1, page_size=20)

    assert result["total"] == 597
    assert len(result["items"]) == 20
    assert all(item["priority"] == "high" for item in result["items"])


def test_path_detail_links_available_proposals_and_evidence_assets() -> None:
    detail = server.load_path_detail("VIS-0012")

    assert detail["visual_review_id"] == "VIS-0012"
    assert detail["parent_compound"] == "42"
    assert detail["derived_compound"] == "48"
    assert detail["evidence_page_url"].startswith("/assets/pages/")
    assert detail["proposals"][0]["compound_id"] == "48"
    assert detail["proposals"][0]["crop_url"].startswith("/assets/crops/")


def test_path_detail_separates_generated_smiles_structures_from_article_evidence() -> None:
    detail = server.load_path_detail("VIS-0001")

    assert detail["parent_canonical_smiles"]
    assert detail["derived_canonical_smiles"]
    assert detail["structure_source"] == "supporting_information_csv"
    assert detail["structure_confirmation_status"] == "confirmed_by_si_smiles"
    assert detail["structure_image_parent_url"].startswith("/assets/structures/")
    assert detail["structure_image_derived_url"].startswith("/assets/structures/")
    assert detail["path_panel_image_url"].startswith("/assets/structures/")
    assert detail["evidence_page_url"].startswith("/assets/pages/")


def test_proposal_payload_marks_crop_as_input_and_exposes_generated_structure() -> None:
    proposal = server.load_proposals("VIS-0012")[0]

    assert proposal["crop_url"].startswith("/assets/crops/")
    assert proposal["structure_image_url"].startswith("/assets/structures/")
    assert proposal["source_evidence_page_url"].startswith("/assets/pages/")
    assert proposal["source_canonical_smiles"]


def test_resolve_asset_rejects_path_traversal() -> None:
    with pytest.raises(server.AssetNotFound):
        server.resolve_asset("crops", "../structure_crop_manifest.csv")


def test_json_serialization_has_no_nan_values() -> None:
    payload = server.load_overview()

    encoded = json.dumps(payload, allow_nan=False)
    assert '"candidate_records": 5178' in encoded


@pytest.fixture
def dashboard_url() -> str:
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.DashboardHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def get_json(url: str) -> dict[str, object]:
    with urlopen(url) as response:
        return json.loads(response.read())


def test_generated_structure_asset_is_served_separately_from_source_page(dashboard_url: str) -> None:
    with urlopen(f"{dashboard_url}/assets/structures/VIS-0001_parent.png") as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        assert len(response.read()) > 100


def test_http_endpoints_expose_overview_paths_and_proposals(dashboard_url: str) -> None:
    overview = get_json(f"{dashboard_url}/api/overview")
    paths = get_json(f"{dashboard_url}/api/paths?scope=explicit&page_size=2")
    proposals = get_json(f"{dashboard_url}/api/proposals?visual_review_id=VIS-0012")

    assert overview["counts"]["papers"] == 672
    assert paths["total"] == 16
    assert len(paths["items"]) == 2
    assert proposals["items"][0]["compound_id"] == "48"


def test_http_first_page_fragment_review_endpoint(dashboard_url: str) -> None:
    review = get_json(f"{dashboard_url}/api/first-page-structure")

    assert review["summary"]["papers"] == 20
    assert len(review["papers"]) == 20
    assert len(review["items"]) == 31
    assert len(review["molecule_objects"]) == 121
    assert all(item["object_type"] not in {"non_structure_region", "three_d_structure_evidence"} for item in review["molecule_objects"])


def test_http_first_page_molecule_objects_endpoint(dashboard_url: str) -> None:
    review = get_json(f"{dashboard_url}/api/first-page-molecule-objects")

    assert review["summary"]["object_rows"] == 121
    assert len(review["objects"]) == 121
    linker = next(
        item for item in review["objects"]
        if item["paper_id"] == "d8e4f69200f7" and item["compound_label"] == "Linker a"
    )
    assert linker["attachment_inference"]["fragment_smiles"] == "[*:1]c1ccc(CC[*:2])cc1"
    assert linker["attachment_inference"]["assembled_smiles"] == "--"
    json.dumps(review, allow_nan=False)


def test_http_papers_endpoint_uses_20_item_pagination(dashboard_url: str) -> None:
    papers = get_json(f"{dashboard_url}/api/papers?page=2")

    assert papers["total"] == 672
    assert papers["page"] == 2
    assert papers["page_size"] == 20
    assert len(papers["items"]) == 20


def test_http_paper_detail_endpoint_exposes_nested_records(dashboard_url: str) -> None:
    detail = get_json(f"{dashboard_url}/api/papers/04effc6577c7")

    assert detail["paper"]["paper_id"] == "04effc6577c7"
    assert len(detail["explicit_paths"]) == 2
    assert detail["explicit_paths"][0]["proposals"] == []
    assert len(detail["review_items"]) == 57


def test_http_paper_detail_exposes_only_the_selected_paper_molecule_objects(dashboard_url: str) -> None:
    detail = get_json(f"{dashboard_url}/api/papers/d8e4f69200f7")

    assert len(detail["molecule_objects"]) == 50
    assert all(item["paper_id"] == "d8e4f69200f7" for item in detail["molecule_objects"])
    assert detail["molecule_object_summary"]["attachment_inference_rows"] == 5
    json.dumps(detail, allow_nan=False)


def test_http_review_endpoint_persists_override(
    dashboard_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    payload = json.dumps(
        {
            "review_status": "in_review",
            "title_override": "HTTP revised title",
            "correction_note": "A correction",
            "review_note": "A note",
        }
    ).encode()

    from urllib.request import Request

    request = Request(
        f"{dashboard_url}/api/papers/04effc6577c7/review",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        result = json.loads(response.read())

    assert result["paper"]["review_status"] == "in_review"
    assert result["paper"]["title"] == "HTTP revised title"


def test_http_review_item_endpoint_persists_item_override(
    dashboard_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = get_json(f"{dashboard_url}/api/papers/04effc6577c7")["review_items"][0]["review_item_id"]
    payload = json.dumps({"review_status": "in_review", "review_note": "Check this entry."}).encode()

    from urllib.request import Request

    request = Request(
        f"{dashboard_url}/api/papers/04effc6577c7/review-items/{item_id}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        result = json.loads(response.read())

    updated = next(item for item in result["review_items"] if item["review_item_id"] == item_id)
    assert updated["review_status"] == "in_review"
    assert updated["review_note"] == "Check this entry."


def test_http_review_item_lifecycle_add_delete_confirm_and_lock(
    dashboard_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(server, "PAPER_REVIEWED_ENTRIES_PATH", tmp_path / "reviewed_entries.csv")
    base_url = f"{dashboard_url}/api/papers/04effc6577c7"

    add_request = Request(
        f"{base_url}/review-items",
        data=json.dumps({
            "page": "9",
            "parent_compound": "9a",
            "derived_compound": "9b",
            "activity": "IC50 10 nM",
            "evidence_text": "Manual HTTP entry",
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(add_request) as response:
        assert response.status == 201
        added_detail = json.loads(response.read())
    added = next(item for item in added_detail["review_items"] if item["source_kind"] == "manual")
    item_id = added["review_item_id"]

    delete_request = Request(f"{base_url}/review-items/{item_id}", method="DELETE")
    with urlopen(delete_request) as response:
        assert response.status == 200
    assert all(item["review_item_id"] != item_id for item in get_json(f"{base_url}")["review_items"])

    add_again = Request(
        f"{base_url}/review-items",
        data=b'{"page":"10","evidence_text":"Confirm this"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(add_again) as response:
        added_detail = json.loads(response.read())
    item_id = next(item["review_item_id"] for item in added_detail["review_items"] if item["source_kind"] == "manual")

    confirm_request = Request(f"{base_url}/review-items/{item_id}/confirm", method="POST")
    with urlopen(confirm_request) as response:
        assert response.status == 200
        confirmed = json.loads(response.read())
    assert confirmed["item"]["review_status"] == "reviewed"
    reviewed_rows = server.read_csv_rows(tmp_path / "reviewed_entries.csv")
    assert any(row["review_item_id"] == item_id for row in reviewed_rows)

    with pytest.raises(Exception) as error:
        urlopen(Request(
            f"{base_url}/review-items/{item_id}",
            data=b'{"activity":"too late"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        ))
    assert "HTTP Error 409" in str(error.value)


def test_http_review_item_rejects_invalid_page(
    dashboard_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "PAPER_REVIEW_OVERRIDES_PATH", tmp_path / "overrides.json")
    item_id = get_json(f"{dashboard_url}/api/papers/04effc6577c7")["review_items"][0]["review_item_id"]
    with pytest.raises(Exception) as error:
        urlopen(Request(
            f"{dashboard_url}/api/papers/04effc6577c7/review-items/{item_id}",
            data=b'{"page":"not-a-page"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        ))
    assert "HTTP Error 400" in str(error.value)


def test_http_review_endpoint_rejects_unknown_paper(dashboard_url: str) -> None:
    from urllib.request import Request

    request = Request(
        f"{dashboard_url}/api/papers/missing/review",
        data=b'{"review_status":"in_review"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(Exception) as error:
        urlopen(request)
    assert "HTTP Error 404" in str(error.value)


def test_http_asset_endpoint_and_path_traversal_rejection(dashboard_url: str) -> None:
    with urlopen(f"{dashboard_url}/assets/crops/CROP-0002_derived_3f.png") as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        assert len(response.read()) > 100

    with pytest.raises(Exception) as error:
        urlopen(f"{dashboard_url}/assets/crops/%2E%2E%2Fstructure_crop_manifest.csv")
    assert "HTTP Error 404" in str(error.value)
