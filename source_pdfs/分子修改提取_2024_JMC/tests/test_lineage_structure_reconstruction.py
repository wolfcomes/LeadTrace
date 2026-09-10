import csv
from contextlib import contextmanager
import json
from pathlib import Path
import zipfile

import pytest
from rdkit import Chem

import lineage_structure_reconstruction as reconstruction
from lineage_structure_reconstruction import (
    MANIFEST_FIELDS,
    assemble_mapped_fragments,
    build_component_selection_work_row,
    build_external_identifier_work_row,
    build_source_manifest_rows,
    bind_structure_records,
    discover_figshare_source_rows,
    download_source_manifest_rows,
    inspect_and_bind_source_rows,
    atomic_write_csv,
    atomic_write_json,
    normalize_compound_label,
    normalize_doi,
    publish_reviewed_structure_candidates,
    publish_reviewed_structure_exclusions,
    publish_reviewed_structure_mismatches,
    run_structure_source_batch,
    select_confirmed_structures,
    validate_structure_candidate,
    sha256_file,
    verify_source_manifest_snapshot,
    write_source_manifest_snapshot,
)


REQUIRED_FIELDS = {
    "paper_id",
    "doi",
    "article_id",
    "source_file",
    "download_url",
    "extension",
    "content_class",
    "local_path",
    "download_status",
    "inspection_status",
}


def _canonical_smiles(smiles: str) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    assert molecule is not None
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def test_normalize_compound_label_keeps_local_identity_but_removes_qualifiers() -> None:
    assert normalize_compound_label(" Compound 18 ") == "18"
    assert normalize_compound_label("18 (CHF-6523)") == "18"
    assert normalize_compound_label("18a") == "18a"
    assert normalize_compound_label("compound no. 2n") == "2n"
    assert normalize_compound_label("R6") == "r6"
    assert normalize_compound_label("BMS-HIT") == "bmshit"
    assert normalize_compound_label("BMS HIT") == "bmshit"


@pytest.mark.parametrize(
    ("raw_label", "expected"),
    [
        ("(R)-4", "r4"),
        ("(S)-XY-05", "sxy05"),
        ("(R)-4 (lead)", "r4"),
        ("(\u00a1\u00c0)-11", "11"),
    ],
)
def test_normalize_compound_label_preserves_leading_stereo_descriptor(
    raw_label: str, expected: str,
) -> None:
    assert normalize_compound_label(raw_label) == expected


def test_normalize_compound_label_does_not_collapse_numeric_separators() -> None:
    labels = {
        normalize_compound_label("1-2"),
        normalize_compound_label("1.2"),
        normalize_compound_label("1/2"),
        normalize_compound_label("12"),
    }

    assert len(labels) == 4


def test_bind_structure_records_maps_exact_and_qualified_labels_within_one_paper() -> None:
    entities = [
        {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-18", "normalized_label": "18"},
        {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-18a", "normalized_label": "18a"},
        {"paper_id": "paper-b", "compound_entity_id": "CMP-paper-b-18", "normalized_label": "18"},
    ]
    records = [
        {
            "source_label": "Compound 18 (CHF-6523)",
            "raw_structure_text": "CCO",
            "canonical_isomeric_smiles": "CCO",
            "source_locator": {"row": 2},
            "record_status": "parsed",
            "rejection_reason": "",
        },
        {
            "source_label": "18a",
            "raw_structure_text": "CCN",
            "canonical_isomeric_smiles": "CCN",
            "source_locator": {"row": 3},
            "record_status": "parsed",
            "rejection_reason": "",
        },
    ]

    rows = bind_structure_records(
        paper_id="paper-a",
        entity_rows=entities,
        source_records=records,
        source_id="figshare:1:2",
        source_file="structures.csv",
    )

    assert [row["binding_status"] for row in rows] == ["matched", "matched"]
    assert [row["compound_entity_id"] for row in rows] == [
        "CMP-paper-a-18", "CMP-paper-a-18a",
    ]
    assert rows[0]["binding_method"] == "qualified_label_normalized"
    assert all(row["paper_id"] == "paper-a" for row in rows)
    assert rows[0]["structure_source_locator"] == "row=2"


def test_bind_structure_records_keeps_unknown_invalid_and_duplicate_records_auditable() -> None:
    entities = [{
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "normalized_label": "1",
    }]
    records = [
        {
            "source_label": "1",
            "raw_structure_text": "CCO",
            "canonical_isomeric_smiles": "CCO",
            "source_locator": {"row": 2},
            "record_status": "parsed",
            "rejection_reason": "",
        },
        {
            "source_label": "1",
            "raw_structure_text": "CCO",
            "canonical_isomeric_smiles": "CCO",
            "source_locator": {"row": 3},
            "record_status": "parsed",
            "rejection_reason": "",
        },
        {
            "source_label": "9",
            "raw_structure_text": "CCN",
            "canonical_isomeric_smiles": "CCN",
            "source_locator": {"row": 4},
            "record_status": "parsed",
            "rejection_reason": "",
        },
        {
            "source_label": "1",
            "raw_structure_text": "not-smiles",
            "canonical_isomeric_smiles": "",
            "source_locator": {"row": 5},
            "record_status": "rejected",
            "rejection_reason": "invalid_structure",
        },
        {
            "source_label": "",
            "raw_structure_text": "CCCl",
            "canonical_isomeric_smiles": "CCCl",
            "source_locator": {"row": 6},
            "record_status": "parsed",
            "rejection_reason": "",
        },
    ]

    rows = bind_structure_records(
        paper_id="paper-a",
        entity_rows=entities,
        source_records=records,
        source_id="source-1",
        source_file="structures.csv",
    )

    assert [row["binding_status"] for row in rows] == [
        "duplicate_source_records", "duplicate_source_records",
        "unmatched_label", "invalid_structure", "missing_source_label",
    ]
    assert all(row["candidate_status"] == "not_ready" for row in rows)
    assert rows[2]["binding_reason"] == "source_label_not_found_in_paper"
    assert rows[3]["binding_reason"] == "invalid_structure"


def test_bind_structure_records_does_not_cross_paper_namespaces() -> None:
    entities = [{
        "paper_id": "paper-b",
        "compound_entity_id": "CMP-paper-b-1",
        "normalized_label": "1",
    }]
    rows = bind_structure_records(
        paper_id="paper-a",
        entity_rows=entities,
        source_records=[{
            "source_label": "1",
            "raw_structure_text": "CCO",
            "canonical_isomeric_smiles": "CCO",
            "source_locator": {"row": 2},
            "record_status": "parsed",
            "rejection_reason": "",
        }],
        source_id="source-1",
        source_file="structures.csv",
    )

    assert rows[0]["binding_status"] == "unmatched_label"
    assert rows[0]["compound_entity_id"] == "--"


def test_assemble_mapped_fragments_replaces_one_attachment_point() -> None:
    result = assemble_mapped_fragments(
        "c1cc([*:1])ccc1",
        {"1": "[*:1]C(=O)N"},
    )

    assert result["status"] == "assembled"
    molecule = Chem.MolFromSmiles(str(result["canonical_isomeric_smiles"]))
    assert molecule is not None
    assert not any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms())
    assert result["canonical_isomeric_smiles"] == _canonical_smiles("NC(=O)c1ccccc1")


def test_assemble_mapped_fragments_supports_multiple_independent_sites() -> None:
    result = assemble_mapped_fragments(
        "c1cc([*:1])ccc1[*:2]",
        {"1": "[*:1]F", "2": "[*:2]Cl"},
    )

    assert result["status"] == "assembled"
    assert result["canonical_isomeric_smiles"] == _canonical_smiles("Fc1ccc(Cl)cc1")
    assert result["attachment_maps"] == ["1", "2"]


@pytest.mark.parametrize(
    ("scaffold", "fragments", "reason"),
    [
        ("c1cc([*:1])ccc1", {"2": "[*:2]F"}, "attachment_map_mismatch"),
        ("c1cc([*:1])ccc1[*:1]", {"1": "[*:1]F"}, "duplicate_attachment_map"),
        ("c1cc([*:1])ccc1", {"1": "[*:1]CC[*:2]"}, "fragment_map_mismatch"),
        ("c1ccccc1", {"1": "[*:1]F"}, "scaffold_attachment_map_not_found"),
    ],
)
def test_assemble_mapped_fragments_rejects_ambiguous_attachment_maps(
    scaffold: str, fragments: dict[str, str], reason: str,
) -> None:
    result = assemble_mapped_fragments(scaffold, fragments)

    assert result["status"] == "rejected"
    assert result["rejection_reason"] == reason
    assert result["canonical_isomeric_smiles"] == "--"


def test_assemble_mapped_fragments_rejects_remaining_dummy_atoms_and_bad_fragments() -> None:
    remaining_dummy = assemble_mapped_fragments(
        "c1cc([*:1])ccc1", {"1": "[*:1][*:9]"},
    )
    invalid = assemble_mapped_fragments(
        "c1cc([*:1])ccc1", {"1": "[*:1]C(C)(C)(C)C"},
    )

    assert remaining_dummy["rejection_reason"] == "unresolved_fragment_attachment"
    assert invalid["rejection_reason"] == "invalid_fragment_structure"


def test_assemble_mapped_fragments_preserves_supported_stereochemistry() -> None:
    result = assemble_mapped_fragments(
        "C[C@H]([*:1])O",
        {"1": "[*:1]F"},
    )

    assert result["status"] == "assembled"
    assert result["canonical_isomeric_smiles"] == _canonical_smiles("C[C@@H](O)F")


def test_assemble_mapped_fragments_preserves_double_bond_stereochemistry() -> None:
    result = assemble_mapped_fragments(
        "[*:1]/C=C/F",
        {"1": "[*:1]C"},
    )

    assert result["status"] == "assembled"
    assert result["canonical_isomeric_smiles"] == _canonical_smiles("C/C=C/F")


def _accepted_work_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "work_row_id": "WORK-paper-a-1-001",
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "compound_label": "1",
        "normalized_label": "1",
        "canonical_isomeric_smiles": "C[C@H](O)F",
        "raw_structure_text": "C[C@H](O)F",
        "record_status": "parsed",
        "binding_status": "matched",
        "candidate_status": "candidate_ready",
        "source_id": "figshare:1:2",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": "row=2",
        "source_match_status": "exact_machine_readable_match",
        "review_decision": "accept",
        "reconstruction_method": "direct_source_structure",
        "scaffold_smiles": "--",
        "r_group_assignments": "--",
        "attachment_mapping": "--",
        "component_selection_status": "not_needed",
        "stereochemistry_status": "supported",
    }
    row.update(overrides)
    return row


def test_validate_structure_candidate_separates_rdkit_validity_from_confirmation() -> None:
    pending = validate_structure_candidate({
        **_accepted_work_row(),
        "review_decision": "pending",
    })
    accepted = validate_structure_candidate(_accepted_work_row())

    assert pending["rdkit_status"] == "valid"
    assert pending["confirmation_eligible"] is False
    assert pending["confirmation_reason"] == "explicit_acceptance_required"
    assert accepted["rdkit_status"] == "valid"
    assert accepted["confirmation_eligible"] is True
    assert accepted["canonical_isomeric_smiles"] == _canonical_smiles("C[C@H](O)F")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"canonical_isomeric_smiles": "[*:1]CC"}, "unresolved_dummy_atom"),
        ({"canonical_isomeric_smiles": "CCO.CN"}, "mixture_or_salt_requires_component_selection"),
        ({"stereochemistry_status": "unsupported"}, "unsupported_stereochemistry"),
        ({"structure_source_file": "--"}, "source_locator_incomplete"),
        ({"source_match_status": "ocr_parse_only"}, "source_graph_match_required"),
        ({"canonical_isomeric_smiles": "C(C)(C)(C)(C)C"}, "invalid_structure"),
    ],
)
def test_validate_structure_candidate_rejects_incomplete_or_weak_candidates(
    overrides: dict[str, object], reason: str,
) -> None:
    result = validate_structure_candidate(_accepted_work_row(**overrides))

    assert result["rdkit_status"] in {"valid", "invalid"}
    assert result["confirmation_eligible"] is False
    assert result["confirmation_reason"] == reason


def test_validate_structure_candidate_holds_radicals_for_source_review() -> None:
    result = validate_structure_candidate(_accepted_work_row(
        canonical_isomeric_smiles="C[O]",
        raw_structure_text="C[O]",
    ))

    assert result["rdkit_status"] == "valid"
    assert result["confirmation_eligible"] is False
    assert result["confirmation_reason"] == "unresolved_radical"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"raw_structure_text": "CCN"}, "source_structure_mismatch"),
        ({"record_status": "rejected"}, "source_record_not_parsed"),
        ({
            "reconstruction_method": "mapped_fragment_assembly",
            "reconstruction_status": "not_started",
            "scaffold_smiles": "--",
            "r_group_assignments": "--",
            "attachment_mapping": "--",
        }, "reconstruction_not_completed"),
    ],
)
def test_validate_structure_candidate_checks_source_and_reconstruction_audit(
    overrides: dict[str, object], reason: str,
) -> None:
    result = validate_structure_candidate(_accepted_work_row(**overrides))

    assert result["confirmation_eligible"] is False
    assert result["confirmation_reason"] == reason


def test_select_confirmed_structures_requires_acceptance_and_emits_one_final_state() -> None:
    rows = select_confirmed_structures([
        _accepted_work_row(review_decision="pending"),
        _accepted_work_row(
            work_row_id="WORK-paper-a-1-002",
            canonical_isomeric_smiles="CCN",
            raw_structure_text="CCN",
            structure_source_locator="row=3",
        ),
    ])

    assert len(rows) == 1
    assert rows[0]["accepted_work_row_id"] == "WORK-paper-a-1-002"
    assert rows[0]["confirmation_status"] == "structure_confirmed"
    assert rows[0]["structure_review_status"] == "structure_confirmed"
    assert rows[0]["canonical_isomeric_smiles"] == "CCN"


def test_candidate_publication_marks_disagreeing_accepted_rows_as_conflicts(
    tmp_path: Path,
) -> None:
    rows = [
        _accepted_work_row(),
        _accepted_work_row(
            work_row_id="WORK-paper-a-1-002",
            canonical_isomeric_smiles="CCN",
            raw_structure_text="CCN",
            structure_source_locator="row=3",
        ),
    ]

    result = publish_reviewed_structure_candidates(
        rows,
        work_path=tmp_path / "work.csv",
        confirmed_path=tmp_path / "confirmed.csv",
    )

    assert result["confirmed_rows"] == []
    assert {row["confirmation_reason"] for row in result["work_rows"]} == {
        "candidate_conflict",
    }
    assert {row["review_decision"] for row in result["work_rows"]} == {"pending"}


def test_select_confirmed_structures_preserves_existing_confirmation_on_conflict() -> None:
    existing = {
        "confirmed_structure_id": "CONF-paper-a-1-existing",
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "compound_label": "1",
        "normalized_label": "1",
        "canonical_isomeric_smiles": "CCO",
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": "prior_confirmed_source",
        "structure_source_file": "old.csv",
        "structure_source_locator": "row=9",
        "accepted_work_row_id": "WORK-old",
    }
    rows = select_confirmed_structures(
        [_accepted_work_row(canonical_isomeric_smiles="CCN")],
        existing_rows=[existing],
    )

    assert rows == [existing]


def test_select_confirmed_structures_does_not_preserve_invalid_existing_graph() -> None:
    existing = {
        "confirmed_structure_id": "CONF-paper-a-1-existing",
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "compound_label": "1",
        "normalized_label": "1",
        "canonical_isomeric_smiles": "C[O]",
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": "row=2",
        "accepted_work_row_id": "WORK-old",
    }

    assert select_confirmed_structures([], existing_rows=[existing]) == []


def test_select_confirmed_structures_allows_only_explicit_replacement_of_existing_value() -> None:
    existing = {
        "confirmed_structure_id": "CONF-paper-a-1-existing",
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "compound_label": "1",
        "normalized_label": "1",
        "canonical_isomeric_smiles": "CCO",
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": "prior_confirmed_source",
        "structure_source_file": "old.csv",
        "structure_source_locator": "row=9",
        "accepted_work_row_id": "WORK-old",
    }
    rows = select_confirmed_structures(
        [_accepted_work_row(
            canonical_isomeric_smiles="CCN",
            raw_structure_text="CCN",
            replacement_decision="explicit_replace",
        )],
        existing_rows=[existing],
    )

    assert len(rows) == 1
    assert rows[0]["canonical_isomeric_smiles"] == "CCN"
    assert rows[0]["accepted_work_row_id"] == "WORK-paper-a-1-001"


def test_select_confirmed_structures_rebinds_missing_work_to_same_graph() -> None:
    existing = {
        "confirmed_structure_id": "CONF-paper-a-1-existing",
        "paper_id": "paper-a",
        "compound_entity_id": "CMP-paper-a-1",
        "compound_label": "1",
        "normalized_label": "1",
        "canonical_isomeric_smiles": "CCO",
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "old.csv",
        "structure_source_locator": "row=9",
        "accepted_work_row_id": "WORK-missing",
    }
    replacement_work = _accepted_work_row(
        work_row_id="WORK-paper-a-reviewed",
        canonical_isomeric_smiles="CCO",
        raw_structure_text="CCO",
    )

    rows = select_confirmed_structures(
        [replacement_work], existing_rows=[existing],
    )

    assert len(rows) == 1
    assert rows[0]["canonical_isomeric_smiles"] == "CCO"
    assert rows[0]["accepted_work_row_id"] == "WORK-paper-a-reviewed"


def test_discover_figshare_source_rows_queries_every_exact_article(tmp_path: Path) -> None:
    post_calls: list[tuple[str, dict[str, object]]] = []
    get_calls: list[str] = []

    def post_json(url: str, payload: dict[str, object]) -> object:
        post_calls.append((url, payload))
        return [
            {"id": 20, "resource_doi": "10.1021/example", "url": "https://api.test/20"},
            {"id": 21, "resource_doi": "10.1021/example", "url": "https://api.test/21"},
            {"id": 99, "resource_doi": "10.1021/not-example", "url": "https://api.test/99"},
        ]

    def get_json(url: str) -> object:
        get_calls.append(url)
        article_id = url.rsplit("/", 1)[-1]
        return {"id": article_id, "files": [{
            "id": int(article_id) * 10,
            "name": f"source_{article_id}.csv",
            "download_url": f"https://download.test/{article_id}",
            "size": 20,
        }]}

    rows = discover_figshare_source_rows(
        [{"paper_id": "paper-a", "doi": "10.1021/example"}],
        post_json=post_json,
        get_json=get_json,
        download_root=tmp_path,
    )

    assert len(post_calls) == 1
    assert post_calls[0][1] == {"resource_doi": "10.1021/example", "limit": 100}
    assert get_calls == ["https://api.test/20", "https://api.test/21"]
    assert [row["source_id"] for row in rows] == ["figshare:20:200", "figshare:21:210"]


def test_download_source_manifest_rows_downloads_machine_candidates_atomically(tmp_path: Path) -> None:
    csv_bytes = b"Compound,SMILES\n1,CCO\n"
    rows = [
        {
            **{field: "" for field in MANIFEST_FIELDS},
            "source_id": "figshare:1:10", "paper_id": "paper-a", "article_id": "1",
            "file_id": "10", "source_file": "structures.csv", "extension": "csv",
            "download_url": "https://download.test/10", "size_bytes": str(len(csv_bytes)),
            "source_md5": "", "local_path": str(tmp_path / "paper-a" / "1" / "10_structures.csv"),
            "download_status": "pending", "inspection_status": "pending",
            "content_class": "uninspected",
        },
        {
            **{field: "" for field in MANIFEST_FIELDS},
            "source_id": "figshare:2:20", "paper_id": "paper-a", "article_id": "2",
            "file_id": "20", "source_file": "article.pdf", "extension": "pdf",
            "download_url": "https://download.test/20", "size_bytes": "999",
            "local_path": str(tmp_path / "paper-a" / "2" / "20_article.pdf"),
            "download_status": "pending", "inspection_status": "pending",
            "content_class": "uninspected",
        },
    ]
    calls: list[str] = []

    def fetch_bytes(url: str) -> bytes:
        calls.append(url)
        return csv_bytes

    downloaded = download_source_manifest_rows(
        rows,
        fetch_bytes=fetch_bytes,
        download_root=tmp_path,
    )

    assert calls == ["https://download.test/10"]
    assert downloaded[0]["download_status"] == "downloaded"
    assert downloaded[0]["sha256"] == sha256_file(Path(downloaded[0]["local_path"]))
    assert downloaded[1]["download_status"] == "deferred"
    assert not Path(downloaded[1]["local_path"]).exists()


def test_inspect_bind_and_confirm_exact_machine_readable_source(tmp_path: Path) -> None:
    source = tmp_path / "structures.csv"
    source.write_text(
        "Compound Code,SMILES\nCompound 1,CCO\n9,CCN\n2,[*:1]CC\n",
        encoding="utf-8",
    )
    manifest = [{
        **{field: "" for field in MANIFEST_FIELDS},
        "source_id": "figshare:1:10", "paper_id": "paper-a", "article_id": "1",
        "file_id": "10", "source_file": "structures.csv", "extension": "csv",
        "local_path": str(source), "download_status": "downloaded",
        "inspection_status": "pending", "content_class": "uninspected",
    }]
    entities = [
        {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1", "normalized_label": "1"},
        {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-2", "normalized_label": "2"},
    ]

    inspected_manifest, work_rows = inspect_and_bind_source_rows(manifest, entities)
    confirmed = select_confirmed_structures(work_rows)

    assert inspected_manifest[0]["content_class"] == "machine_readable_structure_table"
    assert inspected_manifest[0]["inspection_status"] == "inspected"
    work_by_label = {row["source_label"]: row for row in work_rows}
    assert work_by_label["Compound 1"]["binding_status"] == "matched"
    assert work_by_label["Compound 1"]["review_decision"] == "accept"
    assert work_by_label["Compound 1"]["source_match_status"] == "exact_machine_readable_match"
    assert work_by_label["9"]["binding_status"] == "unmatched_label"
    assert work_by_label["9"]["review_decision"] == "pending"
    assert work_by_label["2"]["binding_status"] == "matched"
    assert work_by_label["2"]["review_decision"] == "pending"
    assert work_by_label["2"]["candidate_status"] == "not_ready"
    assert work_by_label["2"]["confirmation_reason"] == "unresolved_dummy_atom"
    assert len(confirmed) == 1
    assert confirmed[0]["compound_entity_id"] == "CMP-paper-a-1"
    assert confirmed[0]["confirmation_status"] == "structure_confirmed"


def test_run_structure_source_batch_writes_auditable_outputs(tmp_path: Path) -> None:
    source_bytes = b"Compound,SMILES\n1,CCO\n"

    def post_json(url: str, payload: dict[str, object]) -> object:
        return [{
            "id": 10,
            "resource_doi": "10.1021/example",
            "url": "https://api.test/10",
        }]

    def get_json(url: str) -> object:
        return {"id": 10, "files": [{
            "id": 100,
            "name": "structures.csv",
            "download_url": "https://download.test/100",
            "size": len(source_bytes),
        }]}

    outputs = {
        "manifest_path": tmp_path / "structure_source_manifest.csv",
        "snapshot_path": tmp_path / "structure_source_snapshot.json",
        "work_path": tmp_path / "compound_structure_work.csv",
        "confirmed_path": tmp_path / "confirmed_compound_structures.csv",
        "summary_path": tmp_path / "lineage_structure_reconstruction_summary.json",
    }
    result = run_structure_source_batch(
        [{"paper_id": "paper-a", "doi": "10.1021/example"}],
        [{
            "paper_id": "paper-a", "doi": "10.1021/example",
            "compound_entity_id": "CMP-paper-a-1", "normalized_label": "1",
        }],
        post_json=post_json,
        get_json=get_json,
        fetch_bytes=lambda url: source_bytes,
        download_root=tmp_path / "sources",
        **outputs,
    )

    assert all(path.is_file() for path in outputs.values())
    assert verify_source_manifest_snapshot(
        csv_path=outputs["manifest_path"],
        json_path=outputs["snapshot_path"],
    )["row_count"] == 1
    assert result["summary"]["paper_rows"] == 1
    assert result["summary"]["work_rows"] == 1
    assert result["summary"]["confirmed_rows"] == 1
    assert result["summary"]["confirmed_selected_entity_rows"] == 1
    assert result["summary"]["confirmed_selected_paper_rows"] == 1
    assert result["summary"]["per_paper"]["paper-a"]["confirmed_entities"] == 1
    with outputs["confirmed_path"].open(encoding="utf-8", newline="") as handle:
        confirmed_rows = list(csv.DictReader(handle))
    assert confirmed_rows[0]["confirmation_status"] == "structure_confirmed"


def test_run_structure_source_batch_holds_publication_lock_for_shared_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    lock_active = False

    @contextmanager
    def tracked_lock(path: Path):
        nonlocal lock_active
        assert path == tmp_path / ".structure-candidate-publication.lock"
        assert lock_active is False
        lock_active = True
        try:
            yield
        finally:
            lock_active = False

    def assert_locked_read(path: Path) -> list[dict[str, str]]:
        assert lock_active is True
        return []

    def assert_locked_manifest(*args, **kwargs) -> dict[str, object]:
        assert lock_active is True
        return {"row_count": 0, "manifest_sha256": "test"}

    def assert_locked_csv(*args, **kwargs) -> None:
        assert lock_active is True

    def assert_locked_json(*args, **kwargs) -> None:
        assert lock_active is True

    monkeypatch.setattr(reconstruction, "_publication_lock", tracked_lock)
    monkeypatch.setattr(reconstruction, "_read_csv_rows", assert_locked_read)
    monkeypatch.setattr(reconstruction, "discover_figshare_source_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(reconstruction, "download_source_manifest_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(reconstruction, "inspect_and_bind_source_rows", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(reconstruction, "write_source_manifest_snapshot", assert_locked_manifest)
    monkeypatch.setattr(reconstruction, "atomic_write_csv", assert_locked_csv)
    monkeypatch.setattr(reconstruction, "atomic_write_json", assert_locked_json)

    result = run_structure_source_batch(
        [{"paper_id": "paper-a", "doi": "10.1021/example"}],
        [],
        manifest_path=tmp_path / "manifest.csv",
        snapshot_path=tmp_path / "manifest.json",
        work_path=tmp_path / "work.csv",
        confirmed_path=tmp_path / "confirmed.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert lock_active is False
    assert result["summary"]["paper_rows"] == 1


@pytest.mark.parametrize(
    "header", ["Compound Number", "NO.", "compounds", "identification number"],
)
def test_real_source_label_header_aliases_are_recognized(
    tmp_path: Path, header: str,
) -> None:
    source = tmp_path / "structures.csv"
    source.write_text(f"{header},SMILES\nA1,CCO\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["records"][0]["source_label"] == "A1"
    assert result["records"][0]["record_status"] == "parsed"


@pytest.mark.parametrize(
    ("label_header", "structure_header"),
    [
        ("compound number", "Canonical Smiles (PP)"),
        ("Comp", "SMILES code"),
        ("Manuscript Compound #", "SMILES"),
        ("entry", "SMILES"),
        ("Compond No. MS", "SMILES Stringd"),
    ],
)
def test_real_si_header_aliases_are_recognized(
    tmp_path: Path, label_header: str, structure_header: str,
) -> None:
    source = tmp_path / "structures.csv"
    source.write_text(
        f"{label_header};{structure_header}\n42;CCO\n", encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["records"][0]["source_label"] == "42"
    assert result["records"][0]["canonical_isomeric_smiles"] == "CCO"


def test_multiline_csv_header_uses_the_row_with_compound_and_smiles_columns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structures.csv"
    source.write_text(
        ",,Primary Assay\nName,Compound,SMILES\nLead,3,CCO\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["records"][0]["source_label"] == "3"
    assert result["records"][0]["source_locator"] == {"row": 3}


def test_blank_structure_header_is_inferred_only_from_valid_smiles_column(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structures.csv"
    source.write_text(
        "Comp. No;\n14a;CCO\n14b;CCN\n", encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert [row["source_label"] for row in result["records"]] == ["14a", "14b"]
    assert result["detected_columns"][0]["structure_column"] == "<inferred>"


def test_run_structure_source_batch_can_reinspect_an_existing_manifest_without_network(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sources" / "paper-a" / "1" / "10_structures.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Compound Number,SMILES\n1,CCO\n", encoding="utf-8")
    manifest_path = tmp_path / "structure_source_manifest.csv"
    manifest_row = {
        **{field: "" for field in MANIFEST_FIELDS},
        "source_id": "figshare:1:10", "paper_id": "paper-a", "doi": "10.1021/example",
        "article_id": "1", "file_id": "10", "source_file": "structures.csv",
        "extension": "csv", "local_path": str(source), "download_status": "downloaded",
        "inspection_status": "inspected", "content_class": "machine_readable_structure_table",
        "sha256": sha256_file(source),
    }
    snapshot_path = tmp_path / "snapshot.json"
    write_source_manifest_snapshot(
        [manifest_row], csv_path=manifest_path, json_path=snapshot_path,
    )

    def no_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("network should not be called")

    result = run_structure_source_batch(
        [{"paper_id": "paper-a", "doi": "10.1021/example"}],
        [{
            "paper_id": "paper-a", "doi": "10.1021/example",
            "compound_entity_id": "CMP-paper-a-1", "normalized_label": "1",
        }],
        post_json=no_network,
        get_json=no_network,
        fetch_bytes=no_network,
        reuse_manifest=True,
        download_root=tmp_path / "sources",
        manifest_path=manifest_path,
        snapshot_path=snapshot_path,
        work_path=tmp_path / "work.csv",
        confirmed_path=tmp_path / "confirmed.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert result["summary"]["confirmed_rows"] == 1


def test_reuse_manifest_rejects_modified_downloaded_source(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "paper-a" / "1" / "10_structures.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Compound Number,SMILES\n1,CCO\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.csv"
    snapshot_path = tmp_path / "snapshot.json"
    manifest_row = {
        **{field: "" for field in MANIFEST_FIELDS},
        "source_id": "figshare:1:10", "paper_id": "paper-a",
        "doi": "10.1021/example", "article_id": "1", "file_id": "10",
        "source_file": "structures.csv", "extension": "csv",
        "local_path": str(source), "download_status": "downloaded",
        "inspection_status": "inspected",
        "content_class": "machine_readable_structure_table",
        "sha256": sha256_file(source),
    }
    write_source_manifest_snapshot(
        [manifest_row], csv_path=manifest_path, json_path=snapshot_path,
    )
    source.write_text("Compound Number,SMILES\n1,CCN\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source file checksum mismatch"):
        run_structure_source_batch(
            [{"paper_id": "paper-a", "doi": "10.1021/example"}],
            [{
                "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
                "normalized_label": "1",
            }],
            reuse_manifest=True,
            download_root=tmp_path / "sources",
            manifest_path=manifest_path,
            snapshot_path=snapshot_path,
            work_path=tmp_path / "work.csv",
            confirmed_path=tmp_path / "confirmed.csv",
            summary_path=tmp_path / "summary.json",
        )


def test_external_identifier_candidate_uses_the_same_confirmation_gate(tmp_path: Path) -> None:
    candidate = build_external_identifier_work_row(
        paper_id="paper-a",
        compound_entity_id="CMP-paper-a-lead",
        compound_label="Lead",
        query_name="Named inhibitor",
        canonical_isomeric_smiles="C[C@H](O)F",
        source_url="https://pubchem.example/cid/123",
        source_locator="CID=123",
    )

    validation = validate_structure_candidate(candidate)
    result = publish_reviewed_structure_candidates(
        [candidate],
        work_path=tmp_path / "work.csv",
        confirmed_path=tmp_path / "confirmed.csv",
    )

    assert validation["confirmation_eligible"] is True
    assert candidate["source_match_status"] == "exact_external_identifier_match"
    assert result["confirmed_rows"][0]["confirmation_status"] == "structure_confirmed"
    assert result["confirmed_rows"][0]["structure_source_locator"] == "CID=123"


def test_explicit_component_selection_requires_an_exact_source_component() -> None:
    source = _accepted_work_row(
        canonical_isomeric_smiles="CCO.O=C(O)C(F)(F)F",
        raw_structure_text="CCO.OC(=O)C(F)(F)F",
        candidate_status="not_ready",
        review_decision="pending",
        confirmation_reason="mixture_or_salt_requires_component_selection",
    )

    selected = build_component_selection_work_row(
        source,
        selected_component_smiles="CCO",
        decision_note="Source explicitly reports the TFA salt; retain parent molecule.",
    )

    assert selected["work_row_id"] != source["work_row_id"]
    assert selected["canonical_isomeric_smiles"] == "CCO"
    assert selected["component_selection_status"] == "explicit_component_selected"
    assert validate_structure_candidate(selected)["confirmation_eligible"] is True

    with pytest.raises(ValueError, match="not an exact component"):
        build_component_selection_work_row(
            source,
            selected_component_smiles="CCN",
            decision_note="Invalid selection",
        )


def test_candidate_publication_revalidates_existing_work_rows(tmp_path: Path) -> None:
    radical = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        **_accepted_work_row(
            work_row_id="WORK-paper-a-radical",
            canonical_isomeric_smiles="C[O]",
            raw_structure_text="C[O]",
        ),
        "rdkit_status": "valid",
        "confirmation_reason": "eligible",
    }
    work_path = tmp_path / "work.csv"
    confirmed_path = tmp_path / "confirmed.csv"
    atomic_write_csv(
        work_path, [radical], fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )
    atomic_write_csv(
        confirmed_path,
        [{
            "confirmed_structure_id": "CONF-paper-a-1",
            "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
            "compound_label": "1", "normalized_label": "1",
            "canonical_isomeric_smiles": "C[O]",
            "confirmation_status": "structure_confirmed",
            "structure_review_status": "structure_confirmed",
            "structure_source_type": "machine_readable_structure_source",
            "structure_source_file": "structures.csv",
            "structure_source_locator": "row=2",
            "accepted_work_row_id": "WORK-paper-a-radical",
        }],
        fieldnames=reconstruction.CONFIRMED_STRUCTURE_FIELDS,
    )
    external = build_external_identifier_work_row(
        paper_id="paper-b", compound_entity_id="CMP-paper-b-lead",
        compound_label="lead", query_name="Named lead",
        canonical_isomeric_smiles="CCN",
        source_url="https://pubchem.example/cid/123", source_locator="CID=123",
    )

    result = publish_reviewed_structure_candidates(
        [external], work_path=work_path, confirmed_path=confirmed_path,
    )
    radical_after = next(
        row for row in result["work_rows"]
        if row["work_row_id"] == "WORK-paper-a-radical"
    )

    assert radical_after["review_decision"] == "pending"
    assert radical_after["candidate_status"] == "not_ready"
    assert radical_after["confirmation_reason"] == "unresolved_radical"
    assert {row["paper_id"] for row in result["confirmed_rows"]} == {"paper-b"}


def test_reviewed_stereochemistry_exclusion_withdraws_an_auto_confirmation(
    tmp_path: Path,
) -> None:
    source = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        **_accepted_work_row(
            work_row_id="WORK-paper-a-racemate",
            canonical_isomeric_smiles="C[C@H](O)F",
            raw_structure_text="C[C@H](O)F",
        ),
        "rdkit_status": "valid",
        "confirmation_reason": "eligible",
    }
    work_path = tmp_path / "work.csv"
    confirmed_path = tmp_path / "confirmed.csv"
    atomic_write_csv(
        work_path, [source], fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )
    atomic_write_csv(
        confirmed_path,
        [{
            "confirmed_structure_id": "CONF-paper-a-1",
            "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
            "compound_label": "1", "normalized_label": "1",
            "canonical_isomeric_smiles": _canonical_smiles("C[C@H](O)F"),
            "confirmation_status": "structure_confirmed",
            "structure_review_status": "structure_confirmed",
            "structure_source_type": "machine_readable_structure_source",
            "structure_source_file": "structures.csv",
            "structure_source_locator": "row=2",
            "accepted_work_row_id": "WORK-paper-a-racemate",
        }],
        fieldnames=reconstruction.CONFIRMED_STRUCTURE_FIELDS,
    )

    result = publish_reviewed_structure_exclusions(
        [{
            "work_row_id": "WORK-paper-a-racemate",
            "stereochemistry_status": "ambiguous",
            "decision_note": (
                "The article reports this compound as a racemic mixture; "
                "the source-table single stereoisomer is not the reported material."
            ),
        }],
        work_path=work_path,
        confirmed_path=confirmed_path,
    )

    assert result["confirmed_rows"] == []
    excluded = result["work_rows"][0]
    assert excluded["candidate_status"] == "not_ready"
    assert excluded["review_decision"] == "reject"
    assert excluded["stereochemistry_status"] == "ambiguous"
    assert excluded["confirmation_reason"] == "unsupported_stereochemistry"
    assert "racemic mixture" in excluded["reconstruction_reason"]


def test_reviewed_source_mismatch_withdraws_and_persists_as_rejected(
    tmp_path: Path,
) -> None:
    source = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        **_accepted_work_row(
            work_row_id="WORK-paper-a-wrong-graph",
            canonical_isomeric_smiles="CCO",
            raw_structure_text="CCO",
        ),
        "rdkit_status": "valid",
        "confirmation_reason": "eligible",
    }
    work_path = tmp_path / "work.csv"
    confirmed_path = tmp_path / "confirmed.csv"
    atomic_write_csv(
        work_path, [source], fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )
    atomic_write_csv(
        confirmed_path,
        [{
            "confirmed_structure_id": "CONF-paper-a-1",
            "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
            "compound_label": "1", "normalized_label": "1",
            "canonical_isomeric_smiles": _canonical_smiles("CCO"),
            "confirmation_status": "structure_confirmed",
            "structure_review_status": "structure_confirmed",
            "structure_source_type": "machine_readable_structure_source",
            "structure_source_file": "structures.csv",
            "structure_source_locator": "row=2",
            "accepted_work_row_id": "WORK-paper-a-wrong-graph",
        }],
        fieldnames=reconstruction.CONFIRMED_STRUCTURE_FIELDS,
    )

    result = publish_reviewed_structure_mismatches(
        [{
            "work_row_id": "WORK-paper-a-wrong-graph",
            "stereochemistry_status": "ambiguous",
            "decision_note": (
                "The machine row has ethanol connectivity, whereas the "
                "paper-local compound is an isopropyl analogue."
            ),
        }],
        work_path=work_path,
        confirmed_path=confirmed_path,
    )

    assert result["confirmed_rows"] == []
    rejected = result["work_rows"][0]
    assert rejected["candidate_status"] == "not_ready"
    assert rejected["review_decision"] == "reject"
    assert rejected["source_match_status"] == "source_structure_mismatch"
    assert rejected["stereochemistry_status"] == "ambiguous"
    assert rejected["confirmation_reason"] == "source_structure_mismatch"
    assert "isopropyl analogue" in rejected["reconstruction_reason"]

    republished = publish_reviewed_structure_candidates(
        [], work_path=work_path, confirmed_path=confirmed_path,
    )
    assert republished["confirmed_rows"] == []
    assert republished["work_rows"][0]["review_decision"] == "reject"
    assert republished["work_rows"][0]["confirmation_reason"] == (
        "source_structure_mismatch"
    )


def test_batch06_smip_component_selection_requires_exact_bromide_cation_pair() -> None:
    from publish_batch06_structure_reviews import select_smip_cation_component

    source = "COc1ccc2c(c1)c[n+](CCO)c1ccc(Br)cc21.[Br-]"
    selected = select_smip_cation_component(source)

    assert selected == _canonical_smiles(
        "COc1ccc2c(c1)c[n+](CCO)c1ccc(Br)cc21"
    )
    assert "[n+]" in selected
    assert "Br" in selected

    with pytest.raises(ValueError, match=r"exactly one monatomic \[Br-\]"):
        select_smip_cation_component("C[N+](C)(C)C.[Br-].[Br-]")
    with pytest.raises(ValueError, match="organic cation"):
        select_smip_cation_component("CCO.[Br-]")
    with pytest.raises(ValueError, match=r"exactly one monatomic \[Br-\]"):
        select_smip_cation_component("C[N+](C)(C)C.[Cl-]")


def test_batch06_structure_exclusions_are_label_exact_and_complete() -> None:
    from publish_batch06_structure_reviews import (
        BATCH06_STRUCTURE_MISMATCH_LABELS,
        BATCH06_STRUCTURE_EXCLUSION_LABELS,
        build_batch06_structure_exclusions,
        build_batch06_structure_mismatches,
    )

    rows = []
    for paper_id, labels in BATCH06_STRUCTURE_EXCLUSION_LABELS.items():
        for index, label in enumerate(labels, start=1):
            rows.append({
                "paper_id": paper_id,
                "compound_label": label,
                "normalized_label": normalize_compound_label(label),
                "work_row_id": f"WORK-{paper_id}-{index}",
            })

    exclusions = build_batch06_structure_exclusions(rows)
    actual = {
        (row["paper_id"], normalize_compound_label(row["compound_label"]))
        for row in exclusions
    }
    expected = {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in BATCH06_STRUCTURE_EXCLUSION_LABELS.items()
        for label in labels
    }
    assert actual == expected
    assert len(exclusions) == 44 + 44 + 22 + 1 + 8 + 22
    assert all(row["stereochemistry_status"] == "ambiguous" for row in exclusions)
    assert all(row["decision_note"] for row in exclusions)
    assert ("1994543a9112", "58m") in actual
    assert ("1994543a9112", "86b") not in actual
    for retained in ("A4", "D15", "D16", "D17"):
        assert ("feef9e819b88", normalize_compound_label(retained)) not in actual
    for excluded in (
        "7-30A", "7-31A", "7-45A", "7-48A", "7-51A", "7-54A",
        "7-58A", "7-62A",
    ):
        assert (
            "56f50284cedf", normalize_compound_label(excluded)
        ) in actual
    assert (
        "56f50284cedf", normalize_compound_label("7-31B")
    ) not in actual

    mismatch_rows = []
    for paper_id, labels in BATCH06_STRUCTURE_MISMATCH_LABELS.items():
        for index, label in enumerate(labels, start=1):
            mismatch_rows.append({
                "paper_id": paper_id,
                "compound_label": label,
                "normalized_label": normalize_compound_label(label),
                "work_row_id": f"WORK-mismatch-{paper_id}-{index}",
            })
    mismatches = build_batch06_structure_mismatches(mismatch_rows)
    assert {
        (row["paper_id"], normalize_compound_label(row["compound_label"]))
        for row in mismatches
    } == {
        ("56f50284cedf", normalize_compound_label("7-31B")),
        ("1994543a9112", normalize_compound_label("58c")),
    }
    assert all(row["stereochemistry_status"] == "ambiguous" for row in mismatches)


def test_batch06_stx721_excludes_only_unsupported_stereochemical_assignments() -> None:
    from publish_batch06_structure_reviews import (
        BATCH06_STRUCTURE_EXCLUSION_LABELS,
    )

    excluded = {
        normalize_compound_label(label)
        for label in BATCH06_STRUCTURE_EXCLUSION_LABELS["bf54bac4775b"]
    }
    assert excluded == {
        normalize_compound_label(label)
        for label in (
            "20", "21", "24", "25", "27", "28", "29", "30", "31",
            "36", "37", "41", "42", "43",
            "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S10",
        )
    }
    for supported in (
        "1", "S1", "22", "23", "32", "S9", "35", "38", "39", "40",
        "44", "45", "47", "48", "49", "50", "51", "52", "53",
    ):
        assert normalize_compound_label(supported) not in excluded


def test_batch06_smip_component_candidates_preserve_source_components() -> None:
    from publish_batch06_structure_reviews import build_batch06_component_selection_candidates

    source_row = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        "work_row_id": "WORK-023145d60eea-smip006",
        "paper_id": "023145d60eea",
        "compound_entity_id": "CMP-023145d60eea-smip006",
        "compound_label": "SMIP-006",
        "normalized_label": "smip006",
        "raw_structure_text": "COc1ccc2c(c1)c[n+](CCO)c1ccc(Br)cc21.[Br-]",
        "canonical_isomeric_smiles": "COc1ccc2c(c1)c[n+](CCO)c1ccc(Br)cc21.[Br-]",
        "source_id": "figshare:source",
        "source_file": "structures.csv",
        "source_locator": "row=7",
        "binding_status": "matched",
        "binding_method": "exact_label",
        "record_status": "parsed",
        "rejection_reason": "--",
        "source_match_status": "exact_machine_readable_match",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": "row=7",
        "candidate_status": "candidate_ready",
        "review_decision": "accept",
        "confirmation_status": "pending",
        "reconstruction_method": "direct_source_structure",
        "reconstruction_status": "not_needed",
        "reconstruction_reason": "--",
        "component_selection_status": "not_needed",
        "stereochemistry_status": "source_encoded",
        "replacement_decision": "preserve_existing",
        "rdkit_status": "valid",
        "confirmation_reason": "mixture_or_salt_requires_component_selection",
    }

    source_rows = [
        {
            **source_row,
            "compound_label": label,
            "normalized_label": normalize_compound_label(label),
            "work_row_id": f"WORK-023145d60eea-{index}",
        }
        for index, label in enumerate(
            __import__(
                "publish_batch06_structure_reviews",
                fromlist=["BATCH06_SMIP_LABELS"],
            ).BATCH06_SMIP_LABELS,
            start=1,
        )
    ]
    candidates = build_batch06_component_selection_candidates(source_rows)
    assert len(candidates) == 37
    candidate = next(
        row for row in candidates if row["compound_label"] == "SMIP-006"
    )
    assert candidate["component_selection_status"] == "explicit_component_selected"
    assert candidate["canonical_isomeric_smiles"] == _canonical_smiles(
        "COc1ccc2c(c1)c[n+](CCO)c1ccc(Br)cc21"
    )
    assert candidate["raw_structure_text"].count("[Br-]") == 1


def test_batch06_smip_component_candidates_are_idempotent_per_paper_label() -> None:
    from publish_batch06_structure_reviews import (
        BATCH06_SMIP_LABELS,
        build_batch06_component_selection_candidates,
    )

    source_row = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        "paper_id": "023145d60eea",
        "compound_entity_id": "CMP-023145d60eea-smip",
        "compound_label": "SMIP-001",
        "normalized_label": "smip001",
        "raw_structure_text": "COc1ccc2cc[n+](CCO)cc2c1.[Br-]",
        "canonical_isomeric_smiles": "COc1ccc2cc[n+](CCO)cc2c1.[Br-]",
        "source_id": "figshare:source",
        "source_file": "structures.csv",
        "source_locator": "row=2",
        "binding_status": "matched",
        "record_status": "parsed",
        "rejection_reason": "--",
        "source_match_status": "exact_machine_readable_match",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": "row=2",
        "candidate_status": "candidate_ready",
        "review_decision": "accept",
        "confirmation_status": "pending",
        "reconstruction_method": "direct_source_structure",
        "reconstruction_status": "not_needed",
        "reconstruction_reason": "--",
        "component_selection_status": "not_needed",
        "stereochemistry_status": "source_encoded",
        "replacement_decision": "preserve_existing",
        "rdkit_status": "valid",
        "confirmation_reason": "mixture_or_salt_requires_component_selection",
    }
    rows = [
        {
            **source_row,
            "compound_label": label,
            "normalized_label": normalize_compound_label(label),
            "work_row_id": f"WORK-source-{index}",
            "source_locator": f"row={index + 1}",
            "structure_source_locator": f"row={index + 1}",
        }
        for index, label in enumerate(BATCH06_SMIP_LABELS)
    ]
    prior = build_batch06_component_selection_candidates(rows)[0]
    rerun_rows = [*rows, prior]

    candidates = build_batch06_component_selection_candidates(rerun_rows)

    assert len(candidates) == 36
    assert all(
        row["compound_label"] != prior["compound_label"] for row in candidates
    )


def test_candidate_publication_allows_one_explicit_replacement_graph(
    tmp_path: Path,
) -> None:
    old = _accepted_work_row(
        work_row_id="WORK-paper-a-old",
        canonical_isomeric_smiles="CCO",
        raw_structure_text="CCO",
    )
    replacement = {
        **_accepted_work_row(
            work_row_id="WORK-paper-a-replacement",
            canonical_isomeric_smiles="CCN",
            raw_structure_text="CCN",
        ),
        "replacement_decision": "explicit_replace",
    }
    work_path = tmp_path / "work.csv"
    confirmed_path = tmp_path / "confirmed.csv"
    atomic_write_csv(
        work_path, [old], fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )
    atomic_write_csv(
        confirmed_path,
        [{
            "confirmed_structure_id": "CONF-paper-a-1",
            "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
            "compound_label": "1", "normalized_label": "1",
            "canonical_isomeric_smiles": "CCO",
            "confirmation_status": "structure_confirmed",
            "structure_review_status": "structure_confirmed",
            "structure_source_type": "machine_readable_structure_source",
            "structure_source_file": "structures.csv",
            "structure_source_locator": "row=2",
            "accepted_work_row_id": "WORK-paper-a-old",
        }],
        fieldnames=reconstruction.CONFIRMED_STRUCTURE_FIELDS,
    )

    result = publish_reviewed_structure_candidates(
        [replacement], work_path=work_path, confirmed_path=confirmed_path,
    )

    assert result["confirmed_rows"][0]["canonical_isomeric_smiles"] == "CCN"
    assert result["confirmed_rows"][0]["accepted_work_row_id"] == (
        "WORK-paper-a-replacement"
    )
    old_after = next(
        row for row in result["work_rows"]
        if row["work_row_id"] == "WORK-paper-a-old"
    )
    assert old_after["confirmation_reason"] == "candidate_conflict"
    assert old_after["review_decision"] == "pending"


def test_source_label_correction_recovers_excel_scientific_notation() -> None:
    source = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        "work_row_id": "WORK-paper-a-source",
        "paper_id": "paper-a",
        "compound_entity_id": "--",
        "compound_label": "190e01",
        "source_label": "1.90E+01",
        "normalized_label": "190e01",
        "canonical_isomeric_smiles": "CCO",
        "raw_structure_text": "CCO",
        "source_id": "figshare:1:10",
        "source_file": "structures.csv",
        "source_locator": "row=6",
        "record_status": "parsed",
        "binding_status": "unmatched_label",
        "candidate_status": "not_ready",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": "row=6",
        "stereochemistry_status": "source_encoded",
        "review_decision": "pending",
    }

    corrected = reconstruction.build_source_label_correction_work_row(
        source,
        compound_entity_id="CMP-paper-a-19e",
        compound_label="19e",
        decision_note="Rows are ordered 19d, 1.90E+01, 19f.",
    )

    assert corrected["work_row_id"] != source["work_row_id"]
    assert corrected["source_label"] == "1.90E+01"
    assert corrected["normalized_label"] == "19e"
    assert corrected["compound_entity_id"] == "CMP-paper-a-19e"
    assert corrected["binding_method"] == "audited_source_label_correction"
    assert corrected["structure_source_type"] == "reviewed_source_label_correction"
    assert corrected["source_match_status"] == "exact_machine_readable_match"
    assert corrected["review_decision"] == "accept"
    assert corrected["confirmation_reason"] == "eligible"


def test_source_label_correction_rejects_nonmatching_target() -> None:
    source = {
        **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
        "work_row_id": "WORK-paper-a-source",
        "paper_id": "paper-a",
        "compound_label": "190e01",
        "source_label": "1.90E+01",
        "normalized_label": "190e01",
        "canonical_isomeric_smiles": "CCO",
        "raw_structure_text": "CCO",
        "source_id": "figshare:1:10",
        "source_file": "structures.csv",
        "source_locator": "row=6",
        "record_status": "parsed",
        "binding_status": "unmatched_label",
        "structure_source_type": "machine_readable_structure_source",
    }

    with pytest.raises(ValueError, match="does not encode target label"):
        reconstruction.build_source_label_correction_work_row(
            source,
            compound_entity_id="CMP-paper-a-22e",
            compound_label="22e",
            decision_note="Mismatched target.",
        )


def test_reviewed_structure_work_row_requires_audited_source_evidence() -> None:
    row = reconstruction.build_reviewed_structure_work_row(
        paper_id="paper-a",
        compound_entity_id="CMP-paper-a-hit",
        compound_label="BMS-HIT",
        canonical_isomeric_smiles="COc1ccccc1",
        source_id="doi:10.1021/example",
        source_file="article.pdf",
        source_locator="PDF page 2, Figure 2",
        source_label="BMS-HIT",
        reconstruction_method="reviewed_complete_structure",
        source_match_status="visual_graph_match",
        decision_note="Complete graph independently checked against Figure 2.",
    )

    assert row["binding_status"] == "matched"
    assert row["candidate_status"] == "candidate_ready"
    assert row["structure_source_type"] == "source_figure_reconstruction"
    assert row["review_decision"] == "accept"
    assert row["confirmation_reason"] == "eligible"


def test_reviewed_r_group_expansion_requires_attachment_audit() -> None:
    with pytest.raises(ValueError, match="reconstruction_audit_incomplete"):
        reconstruction.build_reviewed_structure_work_row(
            paper_id="paper-a",
            compound_entity_id="CMP-paper-a-39",
            compound_label="39",
            canonical_isomeric_smiles="Clc1ccccc1Cl",
            source_id="figshare:1:10",
            source_file="structures.csv",
            source_locator="row=39; PDF page 3",
            source_label="39",
            reconstruction_method="r_group_expansion",
            source_match_status="reconstructed_source_graph_match",
            decision_note="R6 is chlorine according to the synthesis and formula.",
        )


def test_reinspection_preserves_reviewed_nonmachine_work_rows(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "paper-a" / "1" / "10_structures.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Compound,SMILES\n1,CCO\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.csv"
    manifest_row = {
        **{field: "" for field in MANIFEST_FIELDS},
        "source_id": "figshare:1:10", "paper_id": "paper-a", "doi": "10.1021/example",
        "article_id": "1", "file_id": "10", "source_file": "structures.csv",
        "extension": "csv", "local_path": str(source), "download_status": "downloaded",
        "inspection_status": "inspected", "content_class": "machine_readable_structure_table",
        "sha256": sha256_file(source),
    }
    snapshot_path = tmp_path / "snapshot.json"
    write_source_manifest_snapshot(
        [manifest_row], csv_path=manifest_path, json_path=snapshot_path,
    )
    work_path = tmp_path / "work.csv"
    external = build_external_identifier_work_row(
        paper_id="paper-a",
        compound_entity_id="CMP-paper-a-lead",
        compound_label="Lead",
        query_name="Named inhibitor",
        canonical_isomeric_smiles="CCN",
        source_url="https://pubchem.example/cid/123",
        source_locator="CID=123",
    )
    atomic_write_csv(work_path, [external], fieldnames=reconstruction.STRUCTURE_WORK_FIELDS)

    result = run_structure_source_batch(
        [{"paper_id": "paper-a", "doi": "10.1021/example"}],
        [
            {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1", "normalized_label": "1"},
            {"paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-lead", "normalized_label": "lead"},
        ],
        reuse_manifest=True,
        download_root=tmp_path / "sources",
        manifest_path=manifest_path,
        snapshot_path=snapshot_path,
        work_path=work_path,
        confirmed_path=tmp_path / "confirmed.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert {row["compound_label"] for row in result["work_rows"]} == {"1", "Lead"}
    assert len(result["confirmed_rows"]) == 2


def test_partial_batch_preserves_unselected_manifest_and_machine_work(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    manifest_rows = []
    work_rows = []
    for paper_id, article_id, smiles in (
        ("paper-a", "1", "CCO"),
        ("paper-b", "2", "CCN"),
    ):
        source = sources / paper_id / article_id / "10_structures.csv"
        source.parent.mkdir(parents=True)
        source.write_text(
            f"Compound,SMILES\n1,{smiles}\n", encoding="utf-8",
        )
        manifest_rows.append({
            **{field: "" for field in MANIFEST_FIELDS},
            "source_id": f"figshare:{article_id}:10", "paper_id": paper_id,
            "doi": f"10.1021/{paper_id}", "article_id": article_id,
            "file_id": "10", "source_file": "structures.csv",
            "extension": "csv", "local_path": str(source),
            "download_status": "downloaded", "inspection_status": "inspected",
            "content_class": "machine_readable_structure_table",
            "sha256": sha256_file(source),
        })
        work_rows.append({
            **{field: "--" for field in reconstruction.STRUCTURE_WORK_FIELDS},
            "work_row_id": f"WORK-{paper_id}", "paper_id": paper_id,
            "compound_entity_id": f"CMP-{paper_id}-1", "compound_label": "1",
            "normalized_label": "1", "structure_source_type":
            "machine_readable_structure_source",
        })
    manifest_path = tmp_path / "manifest.csv"
    snapshot_path = tmp_path / "snapshot.json"
    work_path = tmp_path / "work.csv"
    write_source_manifest_snapshot(
        manifest_rows, csv_path=manifest_path, json_path=snapshot_path,
    )
    atomic_write_csv(
        work_path, work_rows, fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )

    result = run_structure_source_batch(
        [{"paper_id": "paper-a", "doi": "10.1021/paper-a"}],
        [{
            "paper_id": "paper-a", "compound_entity_id": "CMP-paper-a-1",
            "normalized_label": "1",
        }],
        reuse_manifest=True,
        download_root=sources,
        manifest_path=manifest_path,
        snapshot_path=snapshot_path,
        work_path=work_path,
        confirmed_path=tmp_path / "confirmed.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert {row["paper_id"] for row in result["manifest"]} == {
        "paper-a", "paper-b",
    }
    assert {row["paper_id"] for row in result["work_rows"]} == {
        "paper-a", "paper-b",
    }


def _write_basic_xlsx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    root_relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    workbook = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Structures" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""
    workbook_relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>
"""
    shared_strings = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
  <si><t>Isomeric SMILES</t></si>
  <si><t>XLSX-1</t></si>
  <si><t>C[C@H](O)F</t></si>
</sst>
"""
    worksheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Compound Code</t></is></c>
      <c r="B1" t="s"><v>0</v></c>
    </row>
    <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
    <row r="3"><c r="A3" t="inlineStr"><is><t>XLSX-2</t></is></c><c r="B3" t="inlineStr"><is><t>CCO</t></is></c></row>
  </sheetData>
</worksheet>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def figshare_payloads() -> tuple[dict[str, list[dict[str, object]]], dict[str, dict[str, object]]]:
    searches = {
        "https://doi.org/10.1021/acs.jmedchem.4c00322": [
            {"id": 200, "resource_doi": "10.1021/ACS.JMEDCHEM.4C00322"},
        ],
        "10.1021/acs.jmedchem.4c00001": [
            {"id": 100, "resource_doi": "10.1021/acs.jmedchem.4c00001"},
        ],
    }
    details = {
        "200": {
            "id": 200,
            "files": [
                {
                    "id": 22,
                    "name": "jm4c00322_si_006.CSV",
                    "download_url": "https://ndownloader.figshare.com/files/22",
                    "size": 120,
                    "computed_md5": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                },
                {
                    "id": 21,
                    "name": "jm4c00322_si_001.pdf",
                    "download_url": "https://ndownloader.figshare.com/files/21",
                    "size": 900,
                    "supplied_md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            ],
        },
        "100": {
            "id": 100,
            "files": [
                {
                    "id": 11,
                    "name": "structures.sdf",
                    "download_url": "https://ndownloader.figshare.com/files/11",
                    "size": 450,
                },
            ],
        },
    }
    return searches, details


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" DOI: 10.1021/ACS.JMEDCHEM.4C00322 ", "10.1021/acs.jmedchem.4c00322"),
        ("https://doi.org/10.1021/acs.jmedchem.4c00322", "10.1021/acs.jmedchem.4c00322"),
        ("http://dx.doi.org/10.1000/ABC(12)", "10.1000/abc(12)"),
        ("10.1021/acs.jmedchem.4c00322?download=1", ""),
        ("acs.jmedchem.4c00322", ""),
        (None, ""),
    ],
)
def test_normalize_doi_is_conservative(raw: object, expected: str) -> None:
    assert normalize_doi(raw) == expected


def test_manifest_rows_have_required_fields_and_pending_inspection(tmp_path: Path) -> None:
    searches, details = figshare_payloads()
    papers = [{"paper_id": "paper-yoda1", "doi": "DOI:10.1021/acs.jmedchem.4c00322"}]

    rows = build_source_manifest_rows(
        papers,
        searches,
        details,
        download_root=tmp_path / "sources",
    )

    assert REQUIRED_FIELDS <= set(MANIFEST_FIELDS)
    assert len(rows) == 2
    assert all(set(row) == set(MANIFEST_FIELDS) for row in rows)
    assert {row["extension"] for row in rows} == {"csv", "pdf"}
    assert {row["content_class"] for row in rows} == {"uninspected"}
    assert {row["download_status"] for row in rows} == {"pending"}
    assert {row["inspection_status"] for row in rows} == {"pending"}
    assert rows[0]["doi"] == "10.1021/acs.jmedchem.4c00322"
    assert rows[0]["local_path"].startswith(str(tmp_path / "sources" / "paper-yoda1" / "200"))


def test_extension_never_promotes_a_file_to_a_structure_source(tmp_path: Path) -> None:
    searches, details = figshare_payloads()

    rows = build_source_manifest_rows(
        [{"paper_id": "paper-machine", "doi": "10.1021/acs.jmedchem.4c00001"}],
        searches,
        details,
        download_root=tmp_path,
    )

    assert rows[0]["extension"] == "sdf"
    assert rows[0]["content_class"] == "uninspected"
    assert rows[0]["inspection_status"] == "pending"


def test_manifest_order_and_source_ids_are_independent_of_payload_order(tmp_path: Path) -> None:
    searches, details = figshare_payloads()
    papers = [
        {"paper_id": "paper-yoda1", "doi": "10.1021/acs.jmedchem.4c00322"},
        {"paper_id": "paper-machine", "doi": "10.1021/acs.jmedchem.4c00001"},
    ]

    rows = build_source_manifest_rows(papers, searches, details, download_root=tmp_path)
    reversed_rows = build_source_manifest_rows(
        list(reversed(papers)),
        dict(reversed(list(searches.items()))),
        {
            key: {**value, "files": list(reversed(value["files"]))}
            for key, value in reversed(list(details.items()))
        },
        download_root=tmp_path,
    )

    assert rows == reversed_rows
    assert [row["source_id"] for row in rows] == [
        "figshare:100:11",
        "figshare:200:21",
        "figshare:200:22",
    ]
    assert len({row["local_path"] for row in rows}) == len(rows)


def test_mismatched_or_invalid_doi_payloads_do_not_create_rows(tmp_path: Path) -> None:
    rows = build_source_manifest_rows(
        [
            {"paper_id": "paper-invalid", "doi": "not-a-doi"},
            {"paper_id": "paper-mismatch", "doi": "10.1021/acs.jmedchem.4c00002"},
        ],
        {
            "10.1021/acs.jmedchem.4c00002": [
                {"id": 300, "resource_doi": "10.1021/acs.jmedchem.4c99999"},
            ],
        },
        {
            "300": {
                "id": 300,
                "files": [{"id": 1, "name": "wrong.csv", "download_url": "https://example.test/1"}],
            },
        },
        download_root=tmp_path,
    )

    assert rows == []


def test_snapshot_writes_deterministic_csv_and_json_atomically(tmp_path: Path) -> None:
    searches, details = figshare_payloads()
    rows = build_source_manifest_rows(
        [{"paper_id": "paper-yoda1", "doi": "10.1021/acs.jmedchem.4c00322"}],
        searches,
        details,
        download_root=tmp_path / "sources",
    )
    csv_path = tmp_path / "nested" / "structure_source_manifest.csv"
    json_path = tmp_path / "nested" / "structure_source_snapshot.json"

    snapshot = write_source_manifest_snapshot(rows, csv_path=csv_path, json_path=json_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        written_rows = list(reader)
        assert tuple(reader.fieldnames or ()) == MANIFEST_FIELDS
    written_snapshot = json.loads(json_path.read_text(encoding="utf-8"))
    assert written_rows == rows
    assert written_snapshot == snapshot
    assert snapshot["schema_version"] == "lineage_structure_source_manifest_v1"
    assert snapshot["row_count"] == len(rows)
    assert snapshot["manifest_sha256"] == sha256_file(csv_path)
    assert snapshot["rows"] == rows
    assert not list((tmp_path / "nested").glob(".*.tmp"))


def test_atomic_writers_preserve_existing_files_after_write_failure(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "manifest.csv"
    json_path = tmp_path / "snapshot.json"
    csv_path.write_text("old csv\n", encoding="utf-8")
    json_path.write_text("old json\n", encoding="utf-8")

    def broken_rows():
        yield {field: "" for field in MANIFEST_FIELDS}
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        atomic_write_csv(csv_path, broken_rows(), fieldnames=MANIFEST_FIELDS)
    with pytest.raises(TypeError):
        atomic_write_json(json_path, {"not_serializable": object()})

    assert csv_path.read_text(encoding="utf-8") == "old csv\n"
    assert json_path.read_text(encoding="utf-8") == "old json\n"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("chunk_size", [0, -1, True, 1.5, "1024"])
def test_sha256_rejects_invalid_chunk_sizes(tmp_path: Path, chunk_size: object) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"scientific provenance")

    with pytest.raises((TypeError, ValueError)):
        sha256_file(source, chunk_size=chunk_size)  # type: ignore[arg-type]


def test_invalid_computed_md5_falls_back_to_valid_supplied_md5(tmp_path: Path) -> None:
    searches, details = figshare_payloads()
    details["200"]["files"][0]["computed_md5"] = "invalid"
    details["200"]["files"][0]["supplied_md5"] = "c" * 32

    rows = build_source_manifest_rows(
        [{"paper_id": "paper-yoda1", "doi": "10.1021/acs.jmedchem.4c00322"}],
        searches,
        details,
        download_root=tmp_path,
    )

    csv_row = next(row for row in rows if row["extension"] == "csv")
    assert csv_row["source_md5"] == "c" * 32


def test_null_and_unsafe_required_identifiers_never_create_manifest_rows(
    tmp_path: Path,
) -> None:
    searches, details = figshare_payloads()
    unsafe_papers = [
        {"paper_id": None, "doi": "10.1021/acs.jmedchem.4c00322"},
        {"paper_id": "../escape", "doi": "10.1021/acs.jmedchem.4c00322"},
        {"paper_id": "/absolute", "doi": "10.1021/acs.jmedchem.4c00322"},
    ]
    details["200"]["files"].append({
        "id": None,
        "name": "null.csv",
        "download_url": None,
        "size": None,
    })

    rows = build_source_manifest_rows(
        unsafe_papers,
        searches,
        details,
        download_root=tmp_path,
    )

    assert rows == []


def test_optional_nulls_are_empty_and_local_path_stays_under_root(tmp_path: Path) -> None:
    searches = {"10.1021/example": [{"id": 42, "resource_doi": "10.1021/example"}]}
    details = {"42": {"files": [{
        "id": 9,
        "name": "bad<>:\"/\\|?*" + "x" * 260 + ".CSV",
        "download_url": None,
        "size": None,
        "computed_md5": None,
        "supplied_md5": None,
    }]}}
    root = tmp_path / "sources"

    rows = build_source_manifest_rows(
        [{"paper_id": "paper.safe-1", "doi": "10.1021/example"}],
        searches,
        details,
        download_root=root,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["download_url"] == ""
    assert row["size_bytes"] == ""
    assert row["source_md5"] == ""
    assert row["extension"] == "csv"
    assert len(row["source_file"]) <= 180
    assert not any(character in row["source_file"] for character in '<>:"/\\|?*')
    Path(row["local_path"]).resolve().relative_to(root.resolve())


def test_case_collisions_do_not_make_manifest_order_input_dependent(tmp_path: Path) -> None:
    searches = {"10.1021/example": [{"id": 42, "resource_doi": "10.1021/example"}]}
    details = {"42": {"files": [{
        "id": 9,
        "name": "source.csv",
        "download_url": "https://example.test/9",
    }]}}
    papers = [
        {"paper_id": "Paper", "doi": "10.1021/example"},
        {"paper_id": "paper", "doi": "10.1021/example"},
    ]

    rows = build_source_manifest_rows(papers, searches, details, download_root=tmp_path)
    reversed_rows = build_source_manifest_rows(
        list(reversed(papers)), searches, details, download_root=tmp_path
    )

    assert rows == reversed_rows


def test_conflicting_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    searches = {"10.1021/example": [
        {"id": 42, "resource_doi": "10.1021/example"},
        {"id": "42", "resource_doi": "10.1021/example"},
    ]}
    details = {"42": {"files": [
        {"id": 9, "name": "one.csv", "download_url": "https://example.test/one"},
        {"id": "9", "name": "two.csv", "download_url": "https://example.test/two"},
    ]}}

    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_source_manifest_rows(
            [{"paper_id": "paper", "doi": "10.1021/example"}],
            searches,
            details,
            download_root=tmp_path,
        )


def test_conflicting_normalized_article_detail_ids_are_rejected(tmp_path: Path) -> None:
    searches = {"10.1021/example": [{"id": 42, "resource_doi": "10.1021/example"}]}
    details = {
        42: {"files": [{
            "id": 9,
            "name": "one.csv",
            "download_url": "https://example.test/one",
        }]},
        "42": {"files": [{
            "id": 9,
            "name": "two.csv",
            "download_url": "https://example.test/two",
        }]},
    }

    with pytest.raises(ValueError, match="conflicting duplicate article detail"):
        build_source_manifest_rows(
            [{"paper_id": "paper", "doi": "10.1021/example"}],
            searches,
            details,
            download_root=tmp_path,
        )


def test_snapshot_publication_failure_preserves_both_prior_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "manifest.csv"
    json_path = tmp_path / "snapshot.json"
    csv_path.write_text("old csv\n", encoding="utf-8")
    json_path.write_text("old json\n", encoding="utf-8")

    def fail_json(*args: object, **kwargs: object) -> None:
        raise RuntimeError("json publication failed")

    monkeypatch.setattr(reconstruction, "atomic_write_json", fail_json)

    with pytest.raises(RuntimeError, match="json publication failed"):
        write_source_manifest_snapshot([], csv_path=csv_path, json_path=json_path)

    assert csv_path.read_text(encoding="utf-8") == "old csv\n"
    assert json_path.read_text(encoding="utf-8") == "old json\n"


def test_snapshot_verification_detects_csv_json_mismatch(tmp_path: Path) -> None:
    csv_path = tmp_path / "manifest.csv"
    json_path = tmp_path / "snapshot.json"
    write_source_manifest_snapshot([], csv_path=csv_path, json_path=json_path)
    csv_path.write_text("changed after snapshot\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_source_manifest_snapshot(csv_path=csv_path, json_path=json_path)


def test_inspect_comma_csv_preserves_duplicate_labels_as_separate_records(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structures.dat"
    source.write_text(
        "Compound Code,SMILES\nlead-7,CCO\nlead-7,CCN\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result == {
        "content_class": "machine_readable_structure_table",
        "inspection_status": "inspected",
        "detected_format": "csv",
        "detected_columns": [{
            "sheet": None,
            "label_column": "Compound Code",
            "structure_column": "SMILES",
        }],
        "records": [
            {
                "source_label": "lead-7",
                "raw_structure_text": "CCO",
                "canonical_isomeric_smiles": "CCO",
                "source_locator": {"row": 2},
                "record_status": "rejected",
                "rejection_reason": "conflicting_label_structure",
            },
            {
                "source_label": "lead-7",
                "raw_structure_text": "CCN",
                "canonical_isomeric_smiles": "CCN",
                "source_locator": {"row": 3},
                "record_status": "rejected",
                "rejection_reason": "conflicting_label_structure",
            },
        ],
        "issues": [
            {
                "code": "conflicting_label_structure",
                "message": "The same source label maps to conflicting structures.",
                "source_locator": {"row": 2},
            },
            {
                "code": "conflicting_label_structure",
                "message": "The same source label maps to conflicting structures.",
                "source_locator": {"row": 3},
            },
        ],
    }


@pytest.mark.parametrize(
    ("label_header", "structure_header"),
    [
        ("Compound", "Smiles"),
        ("Compound_ID", "canonical"),
        ("Compound No.", "canonical_smiles"),
        ("ID", "isomeric"),
        ("n", "isomeric SMILES"),
    ],
)
def test_csv_header_aliases_are_normalized(
    tmp_path: Path, label_header: str, structure_header: str,
) -> None:
    source = tmp_path / "aliases.csv"
    source.write_text(
        f"{label_header},{structure_header}\ncompound-1,CCO\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": label_header,
        "structure_column": structure_header,
    }]
    assert result["records"][0]["source_label"] == "compound-1"


def test_semicolon_csv_detects_n_and_smile_columns(tmp_path: Path) -> None:
    source = tmp_path / "semicolon.csv"
    source.write_text("n;SMILE\n17;C1CCCCC1\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["detected_format"] == "csv"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "n",
        "structure_column": "SMILE",
    }]
    assert result["records"] == [{
        "source_label": "17",
        "raw_structure_text": "C1CCCCC1",
        "canonical_isomeric_smiles": "C1CCCCC1",
        "source_locator": {"row": 2},
        "record_status": "parsed",
        "rejection_reason": "",
    }]


def test_acs_smiles_string_header_is_a_structure_column(tmp_path: Path) -> None:
    source = tmp_path / "acs.csv"
    source.write_text(
        "Compound Code;SMILES string;Activity\n17;C1CCCCC1;7.2\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["records"][0]["canonical_isomeric_smiles"] == "C1CCCCC1"


def test_unquoted_cxsmiles_comma_is_rejoined_before_parsing(tmp_path: Path) -> None:
    source = tmp_path / "acs.csv"
    source.write_text(
        "Compound Code,SMILES string,Activity\n"
        "17,CCO |a:14,17|,7.2\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["records"][0]["raw_structure_text"] == "CCO |a:14,17|"
    assert result["records"][0]["canonical_isomeric_smiles"] == "CCO"


def test_malformed_csv_is_reported_as_an_inspection_failure(tmp_path: Path) -> None:
    source = tmp_path / "malformed.csv"
    source.write_text('Compound,SMILES\n1,"CCO\n2,CCN\n', encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "uninspected"
    assert result["inspection_status"] == "inspection_failed"
    assert result["detected_format"] == "csv"
    assert result["issues"][0]["code"] == "malformed_delimited_text"


def test_invalid_smiles_remains_as_a_rejected_auditable_record(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("ID,SMILES\nbad-1,not-a-smiles\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["records"] == [{
        "source_label": "bad-1",
        "raw_structure_text": "not-a-smiles",
        "canonical_isomeric_smiles": "",
        "source_locator": {"row": 2},
        "record_status": "rejected",
        "rejection_reason": "invalid_structure",
    }]
    assert result["issues"] == [{
        "code": "invalid_structure",
        "message": "RDKit could not parse the structure text.",
        "source_locator": {"row": 2},
    }]


@pytest.mark.parametrize("raw_smiles", [
    "CCO garbage",
    "CCO\tgarbage",
    "CCO\ninvalid",
    "CC\nO",
])
def test_smiles_with_unconsumed_text_are_rejected(
    tmp_path: Path, raw_smiles: str,
) -> None:
    source = tmp_path / "trailing.csv"
    quoted_smiles = raw_smiles.replace('"', '""')
    source.write_text(
        "Compound,SMILES\ncompound-1,\"" + quoted_smiles + "\"\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["records"][0]["record_status"] == "rejected"
    assert result["records"][0]["rejection_reason"] == "invalid_structure"


def test_cxsmiles_is_preserved_raw_and_metadata_is_stripped_only_for_parsing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "cxsmiles.csv"
    source.write_text(
        'Compound,SMILES\ncx-1," CCO |$C2;O1$| "\n',
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["records"][0]["raw_structure_text"] == " CCO |$C2;O1$| "
    assert result["records"][0]["canonical_isomeric_smiles"] == "CCO"
    assert result["records"][0]["record_status"] == "parsed"


def test_csv_canonicalization_preserves_stereochemistry(tmp_path: Path) -> None:
    source = tmp_path / "stereo.csv"
    raw_smiles = "N[C@@H](C)C(=O)O"
    source.write_text(
        f"Compound_ID,SMILES\nstereo-1,{raw_smiles}\n",
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    canonical = result["records"][0]["canonical_isomeric_smiles"]
    assert canonical == _canonical_smiles(raw_smiles)
    assert "@" in canonical


def test_csv_with_each_complete_row_wrapped_in_quotes_is_parsed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wrapped_rows.csv"
    source.write_text(
        '"Compound,SMILE,Binding affinity (pKi)"\n'
        '"37,CCO,7.33"\n'
        '"38,CCN,5.97"\n',
        encoding="utf-8",
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "Compound",
        "structure_column": "SMILE",
    }]
    assert [record["source_label"] for record in result["records"]] == [
        "37", "38",
    ]
    assert [record["canonical_isomeric_smiles"] for record in result["records"]] == [
        "CCO", "CCN",
    ]
    assert [record["source_locator"] for record in result["records"]] == [
        {"row": 2}, {"row": 3},
    ]


@pytest.mark.parametrize(
    ("source_bytes", "expected_label_column", "expected_labels"),
    [
        (
            b"Compound ID paper,IUPAC Name,SMILES\n1,ethanol,CCO\n",
            "Compound ID paper",
            ["1"],
        ),
        (
            b"Example Nbr;SMILES;Activity\n6;CCN;10\n",
            "Example Nbr",
            ["6"],
        ),
        (
            b"Compound identifier,SMILES string,Activity\n11,CCC,5\n",
            "Compound identifier",
            ["11"],
        ),
        (
            "序号,SMILES,Activity\nE1,CCCl,7\n".encode("gb18030"),
            "序号",
            ["E1"],
        ),
    ],
)
def test_observed_batch05_label_headers_are_bound_without_position_guessing(
    tmp_path: Path,
    source_bytes: bytes,
    expected_label_column: str,
    expected_labels: list[str],
) -> None:
    source = tmp_path / "observed.csv"
    source.write_bytes(source_bytes)

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"][0]["label_column"] == expected_label_column
    assert [record["source_label"] for record in result["records"]] == expected_labels


def test_batch06_cr_only_csv_preserves_rows_and_cmpd_labels() -> None:
    source = (
        reconstruction.DEFAULT_DOWNLOAD_ROOT
        / "bf54bac4775b"
        / "28233050"
        / "51768437_jm4c02377_si_002.csv"
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["inspection_status"] == "inspected"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "Cmpd",
        "structure_column": "SMILES",
    }]
    assert len(result["records"]) == 63
    assert all(record["record_status"] == "parsed" for record in result["records"])
    assert result["records"][0]["source_label"] == "1"
    assert result["records"][-1]["source_label"] == "S10"


def test_cp1252_csv_uses_first_header_and_skips_repeated_headers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "repeated_headers.csv"
    source.write_bytes(
        b"\xef\xbb\xbfCompound,SMILE,Assay\r\n"
        b"24a,CCO,\xa3\r\n"
        b"58a,CCN,1\r\n"
        b"Compound,SMILE,Assay,Assay 2\r\n"
        b"58d,CCC,2,3\r\n"
        b"Compound,SMILE\r\n"
        b"58e,CCCl\r\n"
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "\u00ef\u00bb\u00bfCompound",
        "structure_column": "SMILE",
    }]
    assert [record["source_label"] for record in result["records"]] == [
        "24a", "58a", "58d", "58e",
    ]
    assert all(record["record_status"] == "parsed" for record in result["records"])


def test_batch06_cephalosporin_csv_preserves_all_repeated_header_sections() -> None:
    source = (
        reconstruction.DEFAULT_DOWNLOAD_ROOT
        / "1994543a9112"
        / "25574105"
        / "45563747_jm4c00265_si_001.csv"
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    labels = [record["source_label"] for record in result["records"]]
    assert len(labels) == 38
    assert labels[:10] == [
        "Cefiderocol", "Meropenem", "24a", "24b", "24c", "24d",
        "24e", "58a", "58b", "58c",
    ]
    assert "Compound" not in labels
    assert labels[-2:] == ["86a", "86b"]
    assert all(record["record_status"] == "parsed" for record in result["records"])


def test_batch06_compd_abbreviation_is_an_explicit_label_header() -> None:
    source = (
        reconstruction.DEFAULT_DOWNLOAD_ROOT
        / "7e503b3382bf"
        / "26368881"
        / "47915073_jm4c01178_si_002.csv"
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "Compd.",
        "structure_column": "SMILES",
    }]
    assert len(result["records"]) == 31
    assert [record["source_label"] for record in result["records"][:3]] == [
        "IMT1B", "M1", "M2",
    ]
    assert all(record["record_status"] == "parsed" for record in result["records"])


def test_batch06_strings_smiles_header_is_an_explicit_structure_column() -> None:
    source = (
        reconstruction.DEFAULT_DOWNLOAD_ROOT
        / "feef9e819b88"
        / "27765248"
        / "50532101_jm4c01727_si_002.csv"
    )

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["detected_columns"] == [{
        "sheet": None,
        "label_column": "Compounds",
        "structure_column": "Strings(SMILES)",
    }]
    assert len(result["records"]) == 48
    assert result["records"][0]["source_label"] == "A1"
    assert all(record["record_status"] == "parsed" for record in result["records"])


def test_csv_without_structure_column_is_a_non_structure_table(
    tmp_path: Path,
) -> None:
    source = tmp_path / "misleading.sdf"
    source.write_text("Compound Code,Activity\n1,7.2\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result == {
        "content_class": "non_structure_table",
        "inspection_status": "inspected",
        "detected_format": "csv",
        "detected_columns": [],
        "records": [],
        "issues": [{
            "code": "structure_column_not_found",
            "message": "No recognized structure column was found.",
            "source_locator": None,
        }],
    }


def test_one_column_csv_without_structure_column_is_a_non_structure_table(
    tmp_path: Path,
) -> None:
    source = tmp_path / "activity_only.csv"
    source.write_text("Activity\n7.2\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result == {
        "content_class": "non_structure_table",
        "inspection_status": "inspected",
        "detected_format": "csv",
        "detected_columns": [],
        "records": [],
        "issues": [{
            "code": "structure_column_not_found",
            "message": "No recognized structure column was found.",
            "source_locator": None,
        }],
    }


def test_sdf_uses_label_alias_then_falls_back_to_name(tmp_path: Path) -> None:
    source = tmp_path / "structures.txt"
    first = Chem.MolFromSmiles("F[C@H](Cl)Br")
    second = Chem.MolFromSmiles("CCN")
    assert first is not None and second is not None
    first.SetProp("_Name", "ignored-name")
    first.SetProp("Compound_ID", "SDF-1")
    second.SetProp("_Name", "SDF-2")
    writer = Chem.SDWriter(str(source))
    try:
        writer.write(first)
        writer.write(second)
    finally:
        writer.close()

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["inspection_status"] == "inspected"
    assert result["detected_format"] == "sdf"
    assert result["detected_columns"] == []
    assert [record["source_label"] for record in result["records"]] == [
        "SDF-1", "SDF-2",
    ]
    assert [record["source_locator"] for record in result["records"]] == [
        {"record_index": 1}, {"record_index": 2},
    ]
    assert result["records"][0]["canonical_isomeric_smiles"] == (
        Chem.MolToSmiles(first, canonical=True, isomericSmiles=True)
    )
    assert "M  END" in result["records"][0]["raw_structure_text"]
    assert result["issues"] == []


def test_empty_sdf_is_not_reported_as_a_successful_structure_table(
    tmp_path: Path,
) -> None:
    source = tmp_path / "empty.sdf"
    source.write_text("$$$$\n", encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "uninspected"
    assert result["inspection_status"] == "inspection_failed"
    assert result["issues"][0]["code"] == "empty_structure_source"


def test_labeled_mol_is_parsed_as_one_record_from_content(tmp_path: Path) -> None:
    source = tmp_path / "single.csv"
    molecule = Chem.MolFromSmiles("C[C@H](O)F")
    assert molecule is not None
    molecule.SetProp("_Name", "MOL-1")
    mol_block = Chem.MolToMolBlock(molecule)
    source.write_text(mol_block, encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["detected_format"] == "mol"
    assert result["content_class"] == "machine_readable_structure_table"
    assert result["records"] == [{
        "source_label": "MOL-1",
        "raw_structure_text": mol_block,
        "canonical_isomeric_smiles": Chem.MolToSmiles(
            molecule, canonical=True, isomericSmiles=True,
        ),
        "source_locator": {"record_index": 1},
        "record_status": "parsed",
        "rejection_reason": "",
    }]


def test_unlabeled_mol_is_retained_as_an_auditable_parsed_record(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unlabeled.mol"
    molecule = Chem.MolFromSmiles("CCO")
    assert molecule is not None
    mol_block = "\n" + Chem.MolToMolBlock(molecule).split("\n", 1)[1]
    source.write_text(mol_block, encoding="utf-8")

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["records"][0]["source_label"] == ""
    assert result["records"][0]["record_status"] == "parsed"
    assert result["issues"][0]["code"] == "source_label_not_found"


def test_basic_xlsx_parses_shared_and_inline_strings_without_excel_engine(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structures.bin"
    _write_basic_xlsx(source)

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "machine_readable_structure_table"
    assert result["inspection_status"] == "inspected"
    assert result["detected_format"] == "xlsx"
    assert result["detected_columns"] == [{
        "sheet": "Structures",
        "label_column": "Compound Code",
        "structure_column": "Isomeric SMILES",
    }]
    assert result["records"] == [
        {
            "source_label": "XLSX-1",
            "raw_structure_text": "C[C@H](O)F",
            "canonical_isomeric_smiles": _canonical_smiles("C[C@H](O)F"),
            "source_locator": {"sheet": "Structures", "row": 2},
            "record_status": "parsed",
            "rejection_reason": "",
        },
        {
            "source_label": "XLSX-2",
            "raw_structure_text": "CCO",
            "canonical_isomeric_smiles": "CCO",
            "source_locator": {"sheet": "Structures", "row": 3},
            "record_status": "parsed",
            "rejection_reason": "",
        },
    ]
    assert result["issues"] == []


def test_legacy_binary_xls_reports_clear_unsupported_status(tmp_path: Path) -> None:
    source = tmp_path / "legacy.csv"
    source.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy workbook")

    result = reconstruction.inspect_structure_source(source)

    assert result == {
        "content_class": "uninspected",
        "inspection_status": "unsupported_missing_dependency",
        "detected_format": "xls",
        "detected_columns": [],
        "records": [],
        "issues": [{
            "code": "legacy_xls_parser_unavailable",
            "message": "Legacy binary XLS requires an optional parser dependency.",
            "source_locator": None,
        }],
    }


def test_invalid_non_utf8_and_non_cp1252_bytes_are_audited(tmp_path: Path) -> None:
    source = tmp_path / "invalid.bytes"
    source.write_bytes(b"Compound,SMILES\n1,\x81\n")

    result = reconstruction.inspect_structure_source(source)

    assert result["content_class"] == "uninspected"
    assert result["inspection_status"] == "inspection_failed"
    assert result["issues"][0]["code"] == "text_decode_error"


def test_batch05_06_audit_repair_manifest_has_exact_reviewed_boundary() -> None:
    from publish_batch05_06_audit_repairs import (
        BATCH05_EXCLUSION_LABELS,
        BATCH06_EXCLUSION_LABELS,
        ACTIVE_R_LABELS,
    )

    batch05 = {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in BATCH05_EXCLUSION_LABELS.items()
        for label in labels
    }
    batch06 = {
        (paper_id, normalize_compound_label(label))
        for paper_id, labels in BATCH06_EXCLUSION_LABELS.items()
        for label in labels
    }

    assert len(batch05) == 112
    assert len(batch06) == 2
    assert len(ACTIVE_R_LABELS) == 28
    assert set(BATCH06_EXCLUSION_LABELS) == {"2a98b0589a08"}
    assert set(BATCH06_EXCLUSION_LABELS["2a98b0589a08"]) == {"12", "15"}
    assert ("0eb39d3b45ae", "4e") in batch05
    assert ("cfc4a0d0ef41", "50") in batch05
    assert ("cfc4a0d0ef41", "53") in batch05
    assert ("cfc4a0d0ef41", "54") in batch05
    assert normalize_compound_label("4e") not in ACTIVE_R_LABELS
    assert {
        normalize_compound_label(label)
        for label in ("3c", "3e", "3f", "3g", "3h", "3i", "3j")
    }.isdisjoint(ACTIVE_R_LABELS)


def test_batch05_06_audit_exclusions_bind_current_confirmed_work_rows() -> None:
    from publish_batch05_06_audit_repairs import build_reviewed_exclusions

    result = build_reviewed_exclusions()

    assert len(result["batch05"]) == 112
    assert len(result["batch06"]) == 2
    assert len({row["work_row_id"] for row in result["batch05"]}) == 112
    assert len({row["work_row_id"] for row in result["batch06"]}) == 2
    assert all(row["stereochemistry_status"] == "ambiguous" for row in result["batch05"])
    assert all(row["stereochemistry_status"] == "ambiguous" for row in result["batch06"])
    assert all("source" in row["decision_note"].casefold() or "article" in row["decision_note"].casefold() for row in result["batch05"])


def test_assign_single_unassigned_tetrahedral_cip_selects_requested_isomer() -> None:
    from publish_batch05_06_audit_repairs import (
        assign_single_unassigned_tetrahedral_cip,
    )

    repaired = assign_single_unassigned_tetrahedral_cip("CC(O)F", "R")
    molecule = Chem.MolFromSmiles(repaired)

    assert molecule is not None
    assigned = [
        atom.GetProp("_CIPCode")
        for atom in molecule.GetAtoms()
        if atom.HasProp("_CIPCode")
    ]
    assert assigned == ["R"]
    assert not [
        stereo for stereo in Chem.FindPotentialStereo(
            molecule, cleanIt=True, flagPossible=True,
        )
        if stereo.specified == Chem.StereoSpecified.Unspecified
        and str(stereo.type) == "Atom_Tetrahedral"
    ]


def test_batch05_active_enantiomer_repairs_assign_r_and_preserve_connectivity() -> None:
    from publish_batch05_06_audit_repairs import (
        ACTIVE_R_LABELS,
        build_active_r_replacements,
    )

    replacements = build_active_r_replacements()
    by_label = {row["normalized_label"]: row for row in replacements}

    assert set(by_label) == set(ACTIVE_R_LABELS)
    assert len(replacements) == 28
    assert all(row["replacement_decision"] == "explicit_replace" for row in replacements)
    assert all(row["stereochemistry_status"] == "source_encoded" for row in replacements)
    assert all(row["confirmation_reason"] == "eligible" for row in replacements)

    source_rows = reconstruction._read_csv_rows(reconstruction.DEFAULT_WORK_PATH)
    source_by_label = {
        row["normalized_label"]: row
        for row in source_rows
        if row["paper_id"] == "0eb39d3b45ae"
        and row["normalized_label"] in ACTIVE_R_LABELS
        and row["source_file"] == "jm4c01568_si_002.csv"
        and row["reconstruction_method"] == "direct_source_structure"
    }
    assert set(source_by_label) == set(ACTIVE_R_LABELS)

    for label, repaired in by_label.items():
        source_molecule = Chem.MolFromSmiles(
            source_by_label[label]["canonical_isomeric_smiles"]
        )
        repaired_molecule = Chem.MolFromSmiles(
            repaired["canonical_isomeric_smiles"]
        )
        assert source_molecule is not None and repaired_molecule is not None
        assert not [
            stereo for stereo in Chem.FindPotentialStereo(
                repaired_molecule, cleanIt=True, flagPossible=True,
            )
            if stereo.specified == Chem.StereoSpecified.Unspecified
            and str(stereo.type) == "Atom_Tetrahedral"
        ]
        Chem.RemoveStereochemistry(source_molecule)
        Chem.RemoveStereochemistry(repaired_molecule)
        assert Chem.MolToSmiles(source_molecule) == Chem.MolToSmiles(repaired_molecule)

    # Compounds 11 and 12 already encode the indoline center.  The repair
    # must add the omitted alpha-(R) center without collapsing that distinction.
    assert by_label["11"]["canonical_isomeric_smiles"] != by_label["12"]["canonical_isomeric_smiles"]
    for label in ("11", "12"):
        molecule = Chem.MolFromSmiles(by_label[label]["canonical_isomeric_smiles"])
        assert molecule is not None
        assert len([
            atom for atom in molecule.GetAtoms() if atom.HasProp("_CIPCode")
        ]) == 2


def test_machine_source_stereo_status_detects_unassigned_real_centers() -> None:
    assert reconstruction.source_stereochemistry_status("CCO") == "source_encoded"
    assert reconstruction.source_stereochemistry_status(
        "C[C@H](O)F"
    ) == "source_encoded"
    assert reconstruction.source_stereochemistry_status(
        "CC(O)F"
    ) == "source_unspecified"
    assert reconstruction.source_stereochemistry_status(
        "CC=CC"
    ) == "source_unspecified"


def test_source_unspecified_candidate_with_real_stereo_is_not_confirmable() -> None:
    candidate = {
        "canonical_isomeric_smiles": "CC(O)F",
        "raw_structure_text": "CC(O)F",
        "record_status": "parsed",
        "reconstruction_method": "direct_source_structure",
        "source_match_status": "exact_machine_readable_match",
        "binding_status": "matched",
        "stereochemistry_status": "source_unspecified",
        "candidate_status": "candidate_ready",
        "compound_entity_id": "CMP-paper-1",
        "structure_source_file": "source.csv",
        "structure_source_locator": "row=2",
        "review_decision": "accept",
    }

    result = validate_structure_candidate(candidate)

    assert result["confirmation_eligible"] is False
    assert result["confirmation_reason"] == "unsupported_stereochemistry"


def test_machine_stereo_gate_does_not_reinterpret_reviewed_figure_decision() -> None:
    candidate = {
        "canonical_isomeric_smiles": "CC(O)F",
        "raw_structure_text": "CC(O)F",
        "record_status": "parsed",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "binding_status": "matched",
        "stereochemistry_status": "source_unspecified",
        "candidate_status": "candidate_ready",
        "compound_entity_id": "CMP-paper-1",
        "structure_source_file": "article.pdf",
        "structure_source_locator": "PDF page 3, Figure 2",
        "review_decision": "accept",
    }

    result = validate_structure_candidate(candidate)

    assert result["confirmation_eligible"] is True
    assert result["confirmation_reason"] == "eligible"


def _batch05_06_audit_temp_tables(tmp_path: Path) -> tuple[Path, Path]:
    work_path = tmp_path / "compound_structure_work.csv"
    confirmed_path = tmp_path / "confirmed_compound_structures.csv"
    work_path.write_bytes(reconstruction.DEFAULT_WORK_PATH.read_bytes())
    confirmed_path.write_bytes(reconstruction.DEFAULT_CONFIRMED_PATH.read_bytes())
    return work_path, confirmed_path


def test_batch05_06_audit_publisher_applies_exact_reviewed_changes(
    tmp_path: Path,
) -> None:
    from publish_batch05_06_audit_repairs import (
        ACTIVE_R_LABELS,
        BATCH05_EXCLUSION_LABELS,
        BATCH06_EXCLUSION_LABELS,
        publish_batch05_06_audit_repairs,
    )

    work_path, confirmed_path = _batch05_06_audit_temp_tables(tmp_path)
    before_confirmed = reconstruction._read_csv_rows(confirmed_path)

    result = publish_batch05_06_audit_repairs(
        work_path=work_path,
        confirmed_path=confirmed_path,
    )

    after_work = reconstruction._read_csv_rows(work_path)
    after_confirmed = reconstruction._read_csv_rows(confirmed_path)
    confirmed_by_key = {
        (row["paper_id"], row["normalized_label"]): row
        for row in after_confirmed
    }
    exclusion_keys = {
        (paper_id, normalize_compound_label(label))
        for manifest in (BATCH05_EXCLUSION_LABELS, BATCH06_EXCLUSION_LABELS)
        for paper_id, labels in manifest.items()
        for label in labels
    }
    replacement_keys = {
        ("0eb39d3b45ae", label) for label in ACTIVE_R_LABELS
    }
    before_confirmed_keys = {
        (row["paper_id"], row["normalized_label"])
        for row in before_confirmed
    }
    present_exclusions_before = exclusion_keys & before_confirmed_keys

    assert len(result["batch05_exclusions"]) == 112
    assert len(result["batch06_exclusions"]) == 2
    assert len(result["active_r_replacements"]) == 28
    # The authoritative fixture can be either immediately before its first
    # publication or already repaired.  A partial 1-113-row state is never a
    # valid starting boundary.
    assert len(present_exclusions_before) in {0, 114}
    assert len(after_confirmed) == (
        len(before_confirmed) - len(present_exclusions_before)
    )
    assert exclusion_keys.isdisjoint(confirmed_by_key)
    assert replacement_keys <= set(confirmed_by_key)

    work_by_id = {row["work_row_id"]: row for row in after_work}
    for key in replacement_keys:
        confirmed = confirmed_by_key[key]
        accepted = work_by_id[confirmed["accepted_work_row_id"]]
        assert accepted["replacement_decision"] == "explicit_replace"
        assert accepted["reconstruction_method"] == "reviewed_complete_structure"
        molecule = Chem.MolFromSmiles(confirmed["canonical_isomeric_smiles"])
        assert molecule is not None
        assert not [
            stereo for stereo in Chem.FindPotentialStereo(
                molecule, cleanIt=True, flagPossible=True,
            )
            if stereo.specified == Chem.StereoSpecified.Unspecified
            and str(stereo.type) == "Atom_Tetrahedral"
        ]

    for label in ("11", "12"):
        molecule = Chem.MolFromSmiles(
            confirmed_by_key[("0eb39d3b45ae", label)][
                "canonical_isomeric_smiles"
            ]
        )
        assert molecule is not None
        assert len([
            atom for atom in molecule.GetAtoms() if atom.HasProp("_CIPCode")
        ]) == 2


def test_batch05_06_audit_publisher_is_idempotent(tmp_path: Path) -> None:
    from publish_batch05_06_audit_repairs import (
        publish_batch05_06_audit_repairs,
    )

    work_path, confirmed_path = _batch05_06_audit_temp_tables(tmp_path)
    publish_batch05_06_audit_repairs(
        work_path=work_path,
        confirmed_path=confirmed_path,
    )
    first_work = work_path.read_bytes()
    first_confirmed = confirmed_path.read_bytes()

    publish_batch05_06_audit_repairs(
        work_path=work_path,
        confirmed_path=confirmed_path,
    )

    assert work_path.read_bytes() == first_work
    assert confirmed_path.read_bytes() == first_confirmed


def test_batch05_06_audit_preflight_failure_leaves_tables_unchanged(
    tmp_path: Path,
) -> None:
    from publish_batch05_06_audit_repairs import (
        ACTIVE_R_LABELS,
        PAPER_0EB_SOURCE_FILE,
        publish_batch05_06_audit_repairs,
    )

    work_path, confirmed_path = _batch05_06_audit_temp_tables(tmp_path)
    rows = reconstruction._read_csv_rows(work_path)
    rows = [
        row for row in rows
        if not (
            row["paper_id"] == "0eb39d3b45ae"
            and row["normalized_label"] == ACTIVE_R_LABELS[0]
            and row["source_file"] == PAPER_0EB_SOURCE_FILE
            and row["reconstruction_method"] == "direct_source_structure"
        )
    ]
    reconstruction.atomic_write_csv(
        work_path,
        rows,
        fieldnames=reconstruction.STRUCTURE_WORK_FIELDS,
    )
    before_work = work_path.read_bytes()
    before_confirmed = confirmed_path.read_bytes()

    with pytest.raises(ValueError, match="active-R source rows are incomplete"):
        publish_batch05_06_audit_repairs(
            work_path=work_path,
            confirmed_path=confirmed_path,
        )

    assert work_path.read_bytes() == before_work
    assert confirmed_path.read_bytes() == before_confirmed
