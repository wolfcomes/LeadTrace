import csv
import json
from pathlib import Path

import pytest

from build_compound_lineages import (
    ACTIVITY_FIELDS,
    EDGE_FIELDS,
    ENTITY_FIELDS,
    EVIDENCE_FIELDS,
    _canonical_complete_smiles,
    _compound_label_is_mentioned,
    _read_source_rows,
    _source_structure_and_activity_rows,
    load_confirmed_structures,
    load_confirmed_path_data,
    build_lineage_snapshot,
    load_lineage_annotations,
    normalize_label,
    pair_eligible,
    write_lineage_snapshot,
)


PAPER_ID = "7a695794fc7b"


def test_normalize_label_removes_descriptive_qualifier_without_fuzzy_matching() -> None:
    assert normalize_label("Compound 18 (CHF-6523)") == "18"
    assert normalize_label("36 [individual enantiomer]") == "36"
    assert normalize_label("BMS-HIT") == "bmshit"


def test_normalize_label_preserves_prime_qualified_compounds() -> None:
    assert normalize_label("26a") == "26a"
    assert normalize_label("26a′") == "26aprime"
    assert normalize_label("26a'") == "26aprime"


def test_snapshot_keeps_prime_compound_as_a_distinct_lineage_node() -> None:
    annotation = {
        "paper_id": "paper-prime",
        "doi": "10.1021/prime-label",
        "annotation_status": "evidence_annotated",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [{
            "lineage": "01",
            "root": "9",
            "parent": "26a",
            "derived": "26a′",
            "page": 7,
            "evidence_text": "The enantiomer 26a′ was evaluated against 26a.",
            "locator": "Table S2",
            "modification_site": "benzylic stereocenter",
            "from_group": "R",
            "to_group": "S",
            "relation_type": "stereochemical_inversion",
            "relation_status": "text_explicit",
            "relation_confidence": "high",
        }],
    }

    snapshot = build_lineage_snapshot(
        [{"paper_id": "paper-prime", "page": "7", "evidence_text": "The enantiomer 26a′ was evaluated against 26a."}],
        [],
        annotations={"paper-prime": annotation},
    )

    edge = snapshot["edges"][0]
    assert edge["parent_label"] == "26a"
    assert edge["derived_label"] == "26aprime"
    assert edge["parent_entity_id"] != edge["derived_entity_id"]


@pytest.mark.parametrize(
    ("raw_label", "expected"),
    [
        ("(R)-4", "r4"),
        ("(S)-XY-05", "sxy05"),
        ("(R)-4 (lead)", "r4"),
        ("(\u00a1\u00c0)-11", "11"),
    ],
)
def test_normalize_label_preserves_leading_stereo_descriptor(
    raw_label: str, expected: str,
) -> None:
    assert normalize_label(raw_label) == expected


def evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "paper_id": PAPER_ID,
            "doi": "10.1021/acs.jmedchem.4c02616",
            "page": "2",
            "evidence_text": (
                "Initially, compounds 3 and 4 were designed using a selenium-oxygen "
                "bioisostere strategy based on the danuglipron scaffold."
            ),
        },
        {
            "paper_id": PAPER_ID,
            "doi": "10.1021/acs.jmedchem.4c02616",
            "page": "4",
            "evidence_text": (
                "Further optimization of compound 3 involved modifications to the "
                "benzimidazole ring."
            ),
        },
        {
            "paper_id": PAPER_ID,
            "doi": "10.1021/acs.jmedchem.4c02616",
            "page": "5",
            "evidence_text": (
                "A Se-O bioisostere strategy was applied to compound 2n, leading to compound 23."
            ),
        },
        {
            "paper_id": PAPER_ID,
            "doi": "10.1021/acs.jmedchem.4c02616",
            "page": "5",
            "evidence_text": (
                "Based on compound 23, the substitution of trifluoromethyl with a cyano "
                "group yielded compound 24."
            ),
        },
    ]


def structures() -> list[dict[str, str]]:
    return [
        {"paper_id": PAPER_ID, "compound_label": "1", "preferred_name": "danuglipron", "canonical_smiles": "CCO", "structure_status": "structure_confirmed"},
        {"paper_id": PAPER_ID, "compound_label": "2n", "canonical_smiles": "CCN", "structure_status": "structure_confirmed"},
        {"paper_id": PAPER_ID, "compound_label": "3", "canonical_smiles": "CCC", "structure_status": "structure_confirmed"},
        {"paper_id": PAPER_ID, "compound_label": "5", "canonical_smiles": "CCCC", "structure_status": "structure_confirmed"},
        {"paper_id": PAPER_ID, "compound_label": "23", "canonical_smiles": "CCF", "structure_status": "structure_confirmed"},
        {"paper_id": PAPER_ID, "compound_label": "24", "canonical_smiles": "CCCl", "structure_status": "structure_confirmed"},
    ]


def activity_rows() -> list[dict[str, str]]:
    return [{
        "paper_id": PAPER_ID,
        "compound_label": "3",
        "target": "GLP-1R",
        "assay": "cAMP accumulation in HEK293 cells",
        "metric": "pEC50",
        "value": "0.58",
        "unit": "--",
        "qualifier": "=",
        "page": "2",
        "source_locator": "Table 1",
        "evidence_text": "Compound 3 retained full GLP-1R agonism.",
    }]


def test_snapshot_records_root_template_and_immediate_parent_separately() -> None:
    snapshot = build_lineage_snapshot(evidence_rows(), structures(), activity_rows())
    entities = {row["normalized_label"]: row for row in snapshot["entities"]}
    edges = {(row["parent_label"], row["derived_label"]): row for row in snapshot["edges"]}

    assert entities["1"]["preferred_name"] == "danuglipron"
    assert edges[("1", "3")]["root_template_entity_id"] == entities["1"]["compound_entity_id"]
    assert edges[("3", "5")]["root_template_entity_id"] == entities["1"]["compound_entity_id"]
    assert edges[("3", "5")]["parent_entity_id"] == entities["3"]["compound_entity_id"]
    assert edges[("2n", "23")]["root_template_entity_id"] == entities["2n"]["compound_entity_id"]
    assert edges[("23", "24")]["parent_entity_id"] == entities["23"]["compound_entity_id"]
    assert edges[("23", "24")]["iteration_depth"] == "2"


def test_unresolved_direct_parent_is_recorded_without_inventing_a_pair() -> None:
    snapshot = build_lineage_snapshot(evidence_rows(), structures(), activity_rows())
    unresolved = next(row for row in snapshot["edges"] if row["derived_label"] == "25")

    assert unresolved["root_template_label"] == "2n"
    assert unresolved["parent_entity_id"] == "--"
    assert unresolved["relation_status"] == "unresolved"
    assert pair_eligible(unresolved, snapshot["entities"]) is False


def test_pair_requires_a_direct_edge_and_two_complete_structures() -> None:
    snapshot = build_lineage_snapshot(evidence_rows(), structures(), activity_rows())
    edges = {(row["parent_label"], row["derived_label"]): row for row in snapshot["edges"]}

    assert pair_eligible(edges[("1", "3")], snapshot["entities"]) is True
    incomplete_entities = [dict(row) for row in snapshot["entities"]]
    next(row for row in incomplete_entities if row["normalized_label"] == "3")["canonical_smiles"] = "--"
    assert pair_eligible(edges[("1", "3")], incomplete_entities) is False


def test_snapshot_has_no_object_containment_fields() -> None:
    snapshot = build_lineage_snapshot(evidence_rows(), structures(), activity_rows())

    assert all("parent_object_id" not in row for row in snapshot["edges"])
    assert all("derived_object_id" not in row for row in snapshot["edges"])
    assert all(row["relation_status"] != "structure_suggested" for row in snapshot["edges"])


def test_batch_04_annotations_do_not_contain_self_loop_edges() -> None:
    from generate_lineage_batch_04_annotations import build_annotations

    annotations = build_annotations()

    assert all(
        normalize_label(edge["parent"]) != normalize_label(edge["derived"])
        for annotation in annotations.values()
        for edge in annotation["edges"]
        if edge["parent"] != "--"
    )


def test_batch_04_reviewed_linker_edges_match_source_compounds() -> None:
    from generate_lineage_batch_04_annotations import build_annotations

    annotations = build_annotations()
    s2_edges = [
        edge for edge in annotations["566841ee4e78"]["edges"]
        if normalize_label(edge["derived"]) == "s2"
    ]
    compound_51_edges = [
        edge for edge in annotations["ede33eb21948"]["edges"]
        if normalize_label(edge["parent"]) == "51"
    ]

    assert len(s2_edges) == 1
    assert normalize_label(s2_edges[0]["parent"]) == "12f"
    assert s2_edges[0]["relation_status"] == "text_explicit"
    assert {
        normalize_label(edge["derived"]) for edge in compound_51_edges
    } == {"16"}


def test_jnj_1802_annotation_uses_article_labels_not_phantom_ab_suffixes() -> None:
    from generate_lineage_batch_04_annotations import build_annotations

    annotation = build_annotations()["548156debd90"]
    labels = {
        normalize_label(label)
        for edge in annotation["edges"]
        for label in (edge["root"], edge["parent"], edge["derived"])
        if label != "--"
    }

    assert "9" in labels
    assert not labels.intersection({"9a", "9b", "9c", "9d", "9e"})
    assert not labels.intersection({"10b", "11b", "12b", "13b"})
    assert {"10a", "11a", "12a", "13a"}.issubset(labels)


def test_jnj_1802_si_structure_repair_binds_compound_9() -> None:
    from publish_batch03_04_repairs import REVIEWED_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in REVIEWED_REPAIRS
    }
    repair = repairs[("548156debd90", "9")]

    assert repair["compound_entity_id"] == "CMP-548156debd90-9"
    assert repair["canonical_isomeric_smiles"] == (
        "COc1cc(NC(C(=O)c2c[nH]c3ccccc23)c2ccc(F)cc2)"
        "cc(S(=O)(=O)CCCO)c1"
    )
    assert repair["source_file"] == "jm3c02336_si_002.csv"
    assert repair["source_locator"] == "SI CSV row 10; article compound 9"


def test_pfpk_g_structural_repairs_cover_only_complete_single_component_graphs() -> None:
    from publish_batch03_04_repairs import REVIEWED_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in REVIEWED_REPAIRS
    }
    expected = {
        "10g": "O=C(CC(C(=O)c1ccc(F)cc1)c1ccncc1)C1CCN(C(=O)OCc2ccccc2)CC1",
        "11a": "O=C(OCc1ccccc1)N1CCC(c2cc(-c3ccnc(Br)c3)c(-c3ccc(F)cc3)[nH]2)CC1",
        "11g": "O=C(OCc1ccccc1)N1CCC(c2cc(-c3ccncc3)c(-c3ccc(F)cc3)[nH]2)CC1",
        "58": "CC(=O)c1cc(-c2cc(C3CCNCC3)[nH]c2-c2ccc(F)cc2)ccn1",
        "61": "O=Cc1c(C2CCN(C(=O)OCc3ccccc3)CC2)[nH]c(-c2ccc(F)cc2)c1-c1ccncc1",
    }

    for label, smiles in expected.items():
        repair = repairs[("9b9e5d0c40bc", label)]
        assert _canonical_complete_smiles(repair["canonical_isomeric_smiles"]) == (
            _canonical_complete_smiles(smiles)
        )
        assert "." not in repair["canonical_isomeric_smiles"]
        assert repair["compound_entity_id"] == f"CMP-9b9e5d0c40bc-{label}"


def test_pfpk_g_racemates_remain_unconfirmed_single_component_structures() -> None:
    from publish_batch03_04_repairs import REVIEWED_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in REVIEWED_REPAIRS
    }
    assert ("9b9e5d0c40bc", "40") not in repairs
    assert ("9b9e5d0c40bc", "41") not in repairs


def test_pfpk_external_structure_repairs_bind_compounds_3_4_and_5() -> None:
    from publish_batch03_04_repairs import (
        EXTERNAL_IDENTIFIER_REPAIRS,
        REVIEWED_REPAIRS,
    )

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in [*REVIEWED_REPAIRS, *EXTERNAL_IDENTIFIER_REPAIRS]
    }
    expected = {
        "3": (
            "Cc1cn2c(-c3ccnc(NCC4CC4)n3)c(-c3ccc(F)c(NS(C)(=O)=O)c3)"
            "nc2cc1CN(C)C",
            "RCSB PDB 5EZR, chemical component 4ZS",
        ),
        "4": (
            "CC(C)(CN)c1nc(-c2ccc(Cl)c(O)c2)c(-c2ccncc2)[nH]1",
            "PubChem CID 22185475",
        ),
        "5": (
            "O=C(c1nccs1)N1CC[C@@H](Nc2nccc(-n3cc(C4CC4)nc3-c3ccccc3)n2)C1",
            "RCSB PDB 8EM8, chemical component WLK",
        ),
    }

    for label, (smiles, source_locator) in expected.items():
        repair = repairs[("9b9e5d0c40bc", label)]
        assert _canonical_complete_smiles(
            repair["canonical_isomeric_smiles"]
        ) == _canonical_complete_smiles(smiles)
        assert "." not in repair["canonical_isomeric_smiles"]
        assert repair["compound_entity_id"] == f"CMP-9b9e5d0c40bc-{label}"
        assert repair["source_locator"] == source_locator


def test_pfpk_compound_2_binds_the_source_backed_thiazole_23_graph() -> None:
    from publish_batch03_04_repairs import EXTERNAL_IDENTIFIER_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in EXTERNAL_IDENTIFIER_REPAIRS
    }
    repair = repairs[("9b9e5d0c40bc", "2")]
    expected = (
        "CN1CCC(c2nc(-c3ccc(F)c(NS(C)(=O)=O)c3)"
        "c(-c3ccnc(NCC4CC4)n3)s2)CC1"
    )

    assert _canonical_complete_smiles(repair["canonical_isomeric_smiles"]) == (
        _canonical_complete_smiles(expected)
    )
    assert repair["compound_entity_id"] == "CMP-9b9e5d0c40bc-2"
    assert repair["query_name"] == "Tsagris compound 23"
    assert repair["source_locator"] == (
        "ChEMBL CHEMBL4286841; source document CHEMBL4265899, compound 23"
    )


def test_pfpk_compound_6_reconstructs_the_eck_isoxazole_3_graph() -> None:
    from publish_batch03_04_repairs import REVIEWED_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in REVIEWED_REPAIRS
    }
    repair = repairs[("9b9e5d0c40bc", "6")]
    expected = (
        "CS(=O)(=O)Cc1onc(-c2cccc(Cl)c2)c1-"
        "c1ccnc(N[C@@H]2CCN(C(=O)c3nccs3)C2)n1"
    )

    assert _canonical_complete_smiles(repair["canonical_isomeric_smiles"]) == (
        _canonical_complete_smiles(expected)
    )
    assert repair["compound_entity_id"] == "CMP-9b9e5d0c40bc-6"
    assert repair["stereochemistry_status"] == "source_encoded"
    assert "Eck et al. 2022 Figure 1, compound 3" in repair["source_locator"]


def test_pfpk_annotation_does_not_collapse_intermediate_series_to_bare_labels() -> None:
    from generate_lineage_batch_04_annotations import build_annotations

    annotation = build_annotations()["9b9e5d0c40bc"]
    derived_labels = {
        normalize_label(edge["derived"])
        for edge in annotation["edges"]
    }

    assert {"2", "3", "4", "5", "6"}.issubset(derived_labels)
    assert not derived_labels.intersection({"7", "8", "9"})


def test_cda_repair_keeps_variable_r_groups_unresolved() -> None:
    from publish_batch03_04_repairs import REVIEWED_REPAIRS

    repairs = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in REVIEWED_REPAIRS
    }

    assert repairs[("cda62beb2e03", "40")]["canonical_isomeric_smiles"] == (
        "N=C(N)n1nccc1"
    )
    assert ("cda62beb2e03", "39") not in repairs
    assert ("cda62beb2e03", "41") not in repairs


def test_default_annotation_snapshot_does_not_collapse_prime_labels() -> None:
    annotations = load_lineage_annotations()
    snapshot = build_lineage_snapshot([], [], annotations=annotations)
    paper_edges = [
        row for row in snapshot["edges"] if row["paper_id"] == "381572722037"
    ]

    assert any(row["derived_label"] == "26aprime" for row in paper_edges)
    assert all(
        row["parent_entity_id"] != row["derived_entity_id"]
        for row in paper_edges
        if row["parent_entity_id"] != "--"
    )


def test_evidence_match_requires_the_derived_compound_mention() -> None:
    snapshot = build_lineage_snapshot(evidence_rows(), structures(), activity_rows())
    edge = next(row for row in snapshot["edges"] if row["derived_label"] == "5")
    evidence = next(row for row in snapshot["evidence"] if row["lineage_edge_id"] == edge["lineage_edge_id"])

    assert "piperazine produced compound 5" in evidence["evidence_text"]
    assert "benzimidazole" not in evidence["evidence_text"]


def test_structure_source_precedence_preserves_matching_object_evidence() -> None:
    structure_rows = structures() + [
        {
            "paper_id": PAPER_ID,
            "compound_label": "3",
            "object_id": "OBJ-COMPOUND-3",
            "reconstructed_canonical_smiles": "CCO",
            "reconstruction_status": "model_visual_match_confirmed",
        }
    ]
    snapshot = build_lineage_snapshot(evidence_rows(), structure_rows, activity_rows())
    compound = next(row for row in snapshot["entities"] if row["normalized_label"] == "3")

    assert compound["canonical_smiles"] == "CCC"
    assert compound["structure_review_status"] == "structure_confirmed"
    assert compound["compound_object_ids"] == "OBJ-COMPOUND-3"


def test_external_annotation_builds_generic_depths_and_roles(tmp_path: Path) -> None:
    annotation = {
        "paper_id": "paper-new",
        "doi": "10.1021/example",
        "title": "Example optimization",
        "annotation_status": "evidence_annotated",
        "review_note": "--",
        "preferred_names": {"A": "starting lead"},
        "origins": {"A": "prior_art"},
        "activity_columns": [],
        "edges": [
            {
                "lineage": "01", "root": "A", "parent": "A", "derived": "B",
                "page": 2, "evidence_text": "Compound B was obtained by modifying compound A.",
                "locator": "Figure 1", "modification_site": "ring", "from_group": "H",
                "to_group": "F", "relation_type": "substituent_replacement",
                "relation_status": "text_explicit", "relation_confidence": "high",
            },
            {
                "lineage": "01", "root": "A", "parent": "B", "derived": "C",
                "page": 3, "evidence_text": "Further optimization of B gave compound C.",
                "locator": "Table 1", "modification_site": "linker", "from_group": "CH2",
                "to_group": "O", "relation_type": "linker_replacement",
                "relation_status": "text_explicit", "relation_confidence": "high",
            },
        ],
    }
    path = tmp_path / "paper-new.json"
    path.write_text(json.dumps(annotation), encoding="utf-8")
    annotations = load_lineage_annotations(tmp_path)
    snapshot = build_lineage_snapshot(
        [],
        [
            {"paper_id": "paper-new", "compound_label": "A", "canonical_smiles": "CC", "structure_status": "structure_confirmed"},
            {"paper_id": "paper-new", "compound_label": "B", "canonical_smiles": "CCC", "structure_status": "structure_confirmed"},
            {"paper_id": "paper-new", "compound_label": "C", "canonical_smiles": "CCCC", "structure_status": "structure_confirmed"},
        ],
        annotations=annotations,
    )
    entities = {row["normalized_label"]: row for row in snapshot["entities"]}
    edges = {row["derived_label"]: row for row in snapshot["edges"]}

    assert entities["a"]["preferred_name"] == "starting lead"
    assert entities["a"]["entity_origin"] == "prior_art"
    assert entities["b"]["entity_role"] == "iteration_intermediate"
    assert edges["b"]["iteration_depth"] == "1"
    assert edges["c"]["iteration_depth"] == "2"
    assert all(row["pair_eligible"] == "yes" for row in edges.values())


def test_iteration_depth_is_scoped_to_lineage_when_a_derived_compound_is_reused_as_a_root() -> None:
    annotation = {
        "paper_id": "paper-shared-stage",
        "doi": "10.1021/shared-stage",
        "title": "Shared stage example",
        "annotation_status": "evidence_annotated",
        "review_note": "--",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [
            {
                "lineage": "01", "root": "A", "parent": "A", "derived": "B",
                "page": 1, "evidence_text": "Modification of compound A gave compound B.",
                "locator": "Figure 1", "modification_site": "site", "from_group": "H",
                "to_group": "F", "relation_type": "substituent_replacement",
                "relation_status": "text_explicit", "relation_confidence": "high",
            },
            {
                "lineage": "02", "root": "B", "parent": "B", "derived": "C",
                "page": 2, "evidence_text": "Further modification of compound B gave compound C.",
                "locator": "Figure 2", "modification_site": "site", "from_group": "F",
                "to_group": "Cl", "relation_type": "substituent_replacement",
                "relation_status": "text_explicit", "relation_confidence": "high",
            },
        ],
    }
    snapshot = build_lineage_snapshot(
        [],
        [
            {"paper_id": "paper-shared-stage", "compound_label": "A", "canonical_smiles": "CC", "structure_status": "source_confirmed"},
            {"paper_id": "paper-shared-stage", "compound_label": "B", "canonical_smiles": "CCC", "structure_status": "source_confirmed"},
            {"paper_id": "paper-shared-stage", "compound_label": "C", "canonical_smiles": "CCCC", "structure_status": "source_confirmed"},
        ],
        annotations={"paper-shared-stage": annotation},
    )

    depths = {(row["lineage_id"], row["derived_label"]): row["iteration_depth"] for row in snapshot["edges"]}

    assert depths[("LINEAGE-paper-shared-stage-01", "b")] == "1"
    assert depths[("LINEAGE-paper-shared-stage-02", "c")] == "1"


def test_annotation_loader_rejects_explicit_edge_without_direct_parent(tmp_path: Path) -> None:
    annotation = {
        "paper_id": "paper-invalid",
        "doi": "10.1021/invalid",
        "title": "Invalid annotation",
        "annotation_status": "evidence_annotated",
        "review_note": "--",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [{
            "lineage": "01", "root": "1", "parent": "--", "derived": "2",
            "page": 2, "evidence_text": "Compound 2 was prepared.", "locator": "Table 1",
            "modification_site": "--", "from_group": "--", "to_group": "--",
            "relation_type": "direct_optimization", "relation_status": "text_explicit",
            "relation_confidence": "high",
        }],
    }
    (tmp_path / "invalid.json").write_text(json.dumps(annotation), encoding="utf-8")

    with pytest.raises(ValueError, match="explicit edge requires a direct parent"):
        load_lineage_annotations(tmp_path)


def test_annotation_loader_accepts_qualified_si_labels_and_primary_number_mentions(tmp_path: Path) -> None:
    annotation = {
        "paper_id": "paper-qualified-label",
        "doi": "10.1021/qualified-label",
        "title": "Qualified labels",
        "annotation_status": "evidence_annotated",
        "review_note": "--",
        "preferred_names": {"18 (CHF-6523)": "CHF-6523"},
        "origins": {"18 (CHF-6523)": "in_paper"},
        "activity_columns": [],
        "edges": [
            {
                "lineage": "01",
                "root": "16",
                "parent": "16",
                "derived": "18 (CHF-6523)",
                "page": 7,
                "evidence_text": (
                    "Replacement of the decoration of compound 16 yielded compound "
                    "18 (CHF-6523)."
                ),
                "locator": "Table 6",
                "modification_site": "head group",
                "from_group": "dimethylamino",
                "to_group": "1-methylpiperazinyl",
                "relation_type": "substituent_replacement",
                "relation_status": "text_explicit",
                "relation_confidence": "high",
            },
            {
                "lineage": "01",
                "root": "16",
                "parent": "16",
                "derived": "36 (individual enantiomer 2, unknown absolute stereochemistry)",
                "page": 8,
                "evidence_text": "Compound 36 was tested as an individual enantiomer.",
                "locator": "Table 7",
                "modification_site": "stereochemistry",
                "from_group": "racemate",
                "to_group": "individual enantiomer",
                "relation_type": "other",
                "relation_status": "text_explicit",
                "relation_confidence": "medium",
            },
        ],
    }
    path = tmp_path / "qualified-label.json"
    path.write_text(json.dumps(annotation), encoding="utf-8")

    loaded = load_lineage_annotations(tmp_path)

    assert loaded["paper-qualified-label"]["edges"][0]["derived"] == "18 (CHF-6523)"
    assert loaded["paper-qualified-label"]["edges"][1]["derived"].startswith("36 (")


def test_compound_label_match_accepts_explicit_numeric_and_alphanumeric_ranges() -> None:
    assert _compound_label_is_mentioned("3", "Compounds 2-7 were tested.") is True
    assert _compound_label_is_mentioned("5m", "Compounds 5b-5z were tested.") is True
    assert _compound_label_is_mentioned("36b", "Compounds 36a-b were tested.") is True
    assert _compound_label_is_mentioned("A2", "Analogs A1-A3 were tested.") is True
    assert _compound_label_is_mentioned("C10", "Analogs C1-C19 were tested.") is True
    assert _compound_label_is_mentioned("29", "Compounds 22-24 were tested.") is False


def test_annotation_external_structure_binding_is_preserved() -> None:
    annotation = {
        "paper_id": "paper-external-structure",
        "doi": "10.1021/external-structure",
        "annotation_status": "evidence_annotated",
        "preferred_names": {"Lead": "Lead"},
        "origins": {"Lead": "external_reference"},
        "activity_columns": [],
        "external_structures": [{
            "compound_label": "Lead",
            "canonical_smiles": "CCO",
            "structure_status": "source_confirmed",
            "structure_source_type": "pubchem",
            "structure_source_file": "https://pubchem.ncbi.nlm.nih.gov/compound/123",
            "structure_source_locator": "CID=123",
            "structure_review_status": "external_source_confirmed",
        }],
        "edges": [{
            "lineage": "01", "root": "Lead", "parent": "Lead", "derived": "B",
            "page": 1, "evidence_text": "Modification of Lead yielded compound B.",
            "locator": "Figure 1", "modification_site": "site", "from_group": "H",
            "to_group": "F", "relation_type": "substituent_replacement",
            "relation_status": "text_explicit", "relation_confidence": "high",
        }],
    }
    snapshot = build_lineage_snapshot(
        [],
        [{"paper_id": "paper-external-structure", "compound_label": "B", "canonical_smiles": "CCC", "structure_status": "source_confirmed"}],
        annotations={"paper-external-structure": annotation},
    )

    lead = next(row for row in snapshot["entities"] if row["normalized_label"] == "lead")

    assert lead["canonical_smiles"] == "CCO"
    assert lead["structure_source_type"] == "pubchem"
    assert lead["structure_source_locator"] == "CID=123"


def test_generic_si_source_binds_smiles_and_declared_activity_columns(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("Compound,SMILES,Enzyme IC50 (nM)\nB,CCO,< 12\n", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "doi,source_file,source_type,delimiter,label_column,smiles_column,source_locator_prefix,visual_match_status\n"
        "10.1021/example,source.csv,acs_si_csv,,Compound,SMILES,Compound=,requires_visual_graph_check\n",
        encoding="utf-8",
    )
    annotations = {
        "paper-new": {
            "paper_id": "paper-new",
            "doi": "10.1021/example",
            "activity_columns": [{
                "column": "Enzyme IC50 (nM)", "target": "Example enzyme",
                "assay": "biochemical", "metric": "IC50", "unit": "nM",
            }],
            "edges": [],
        }
    }

    structures, activities = _source_structure_and_activity_rows(
        annotations=annotations,
        source_manifest=manifest,
    )

    assert structures[0]["paper_id"] == "paper-new"
    assert structures[0]["canonical_smiles"] == "CCO"
    assert activities[0]["compound_label"] == "b"
    assert activities[0]["target"] == "Example enzyme"
    assert activities[0]["metric"] == "IC50"
    assert activities[0]["qualifier"] == "<"
    assert activities[0]["value"] == "12"
    assert activities[0]["unit"] == "nM"


def test_unquoted_cxsmiles_commas_do_not_shift_si_activity_columns(tmp_path: Path) -> None:
    source = tmp_path / "cxsmiles.csv"
    source.write_text(
        "Compound_ID,SMILES,hV1a Ki (nM),hV1a IC50 (nM)\n"
        "8,ClC1=CC=CC=C1 |a:14,17|,0.8,1.0\n",
        encoding="utf-8",
    )

    row = _read_source_rows(source)[0]

    assert row["SMILES"] == "ClC1=CC=CC=C1 |a:14,17|"
    assert row["hV1a Ki (nM)"] == "0.8"
    assert row["hV1a IC50 (nM)"] == "1.0"
    assert _canonical_complete_smiles(row["SMILES"]) != "--"


def test_confirmed_path_data_expands_annotations_and_structures(tmp_path: Path) -> None:
    confirmed = tmp_path / "confirmed.csv"
    confirmed.write_text(
        "doi,page,parent_compound,derived_compound,reported_from_group,reported_to_group,evidence_text,parent_canonical_smiles,derived_canonical_smiles,confirmation_status\n"
        "10.1021/example,4,A,B,H,F,Replacement of H (A) with F yielded compound B.,CC,CCC,confirmed_by_si_smiles\n",
        encoding="utf-8",
    )

    annotations, structures = load_confirmed_path_data(
        confirmed,
        {"10.1021/example": "paper-new"},
    )

    assert annotations["paper-new"]["edges"][0]["root"] == "A"
    assert annotations["paper-new"]["edges"][0]["parent"] == "A"
    assert annotations["paper-new"]["edges"][0]["derived"] == "B"
    assert annotations["paper-new"]["edges"][0]["relation_status"] == "text_explicit"
    assert {row["compound_label"] for row in structures} == {"a", "b"}
    assert {row["canonical_smiles"] for row in structures} == {"CC", "CCC"}


def test_snapshot_writer_uses_stable_schemas(tmp_path: Path) -> None:
    paths = {
        "entities": tmp_path / "entities.csv",
        "edges": tmp_path / "edges.csv",
        "evidence": tmp_path / "evidence.csv",
        "activities": tmp_path / "activities.csv",
        "summary": tmp_path / "summary.json",
    }
    result = write_lineage_snapshot(evidence_rows(), structures(), activity_rows(), **paths)

    assert set(result["entities"][0]) == set(ENTITY_FIELDS)
    assert set(result["edges"][0]) == set(EDGE_FIELDS)
    assert set(result["evidence"][0]) == set(EVIDENCE_FIELDS)
    assert set(result["activities"][0]) == set(ACTIVITY_FIELDS)
    for name in ("entities", "edges", "evidence", "activities"):
        with paths[name].open(encoding="utf-8-sig", newline="") as handle:
            assert list(csv.DictReader(handle))
    assert json.loads(paths["summary"].read_text(encoding="utf-8"))["lineage_edge_rows"] >= 4


def test_snapshot_summary_separates_annotation_and_builtin_lineage_papers(tmp_path: Path) -> None:
    annotation = {
        "paper_id": "paper-new",
        "doi": "10.1021/example",
        "annotation_status": "evidence_annotated",
        "edges": [{
            "lineage": "01", "root": "A", "parent": "A", "derived": "B",
            "page": 1, "evidence_text": "Modification of compound A gave compound B.",
            "locator": "Figure 1", "modification_site": "ring", "from_group": "H",
            "to_group": "F", "relation_type": "substituent_replacement",
            "relation_status": "text_explicit", "relation_confidence": "high",
        }],
    }
    paths = {
        "entities": tmp_path / "entities.csv",
        "edges": tmp_path / "edges.csv",
        "evidence": tmp_path / "evidence.csv",
        "activities": tmp_path / "activities.csv",
        "summary": tmp_path / "summary.json",
    }
    result = write_lineage_snapshot(
        evidence_rows(),
        [*structures(),
         {"paper_id": "paper-new", "compound_label": "A", "canonical_smiles": "CC", "structure_status": "source_confirmed"},
         {"paper_id": "paper-new", "compound_label": "B", "canonical_smiles": "CCC", "structure_status": "source_confirmed"}],
        annotations={"paper-new": annotation},
        **paths,
    )

    assert result["summary"]["annotated_paper_rows"] == 1
    assert result["summary"]["builtin_paper_rows"] == 1
    assert result["summary"]["lineage_paper_rows"] == 2


def _confirmed_annotation() -> dict[str, object]:
    return {
        "paper_id": "paper-confirmed",
        "doi": "10.1021/confirmed",
        "annotation_status": "evidence_annotated",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [{
            "lineage": "01", "root": "A", "parent": "A", "derived": "B",
            "page": 1, "evidence_text": "Modification of compound A gave compound B.",
            "locator": "Figure 1", "modification_site": "ring", "from_group": "H",
            "to_group": "F", "relation_type": "substituent_replacement",
            "relation_status": "text_explicit", "relation_confidence": "high",
        }],
    }


def _confirmed_structure(label: str, smiles: str, **overrides: str) -> dict[str, str]:
    row = {
        "paper_id": "paper-confirmed",
        "compound_entity_id": f"CMP-paper-confirmed-{label.casefold()}",
        "compound_label": label,
        "normalized_label": label.casefold(),
        "canonical_isomeric_smiles": smiles,
        "confirmation_status": "structure_confirmed",
        "structure_review_status": "structure_confirmed",
        "structure_source_type": "machine_readable_structure_source",
        "structure_source_file": "structures.csv",
        "structure_source_locator": f"Compound={label}",
        "accepted_work_row_id": f"WORK-paper-confirmed-{label.casefold()}",
    }
    row.update(overrides)
    return row


def test_confirmed_structures_bind_without_objects_and_preserve_other_object_evidence() -> None:
    structure_rows = [
        _confirmed_structure("A", "CCO"),
        _confirmed_structure("B", "CCN"),
        {
            "paper_id": "paper-confirmed",
            "compound_label": "B",
            "object_id": "OBJ-B-001",
            "reconstructed_canonical_smiles": "CCC",
            "reconstruction_status": "model_visual_match_confirmed",
        },
    ]

    snapshot = build_lineage_snapshot(
        [], structure_rows,
        annotations={"paper-confirmed": _confirmed_annotation()},
    )
    entities = {row["normalized_label"]: row for row in snapshot["entities"]}

    assert entities["a"]["canonical_smiles"] == "CCO"
    assert entities["b"]["canonical_smiles"] == "CCN"
    assert entities["b"]["structure_status"] == "complete_structure_resolved"
    assert entities["b"]["structure_review_status"] == "structure_confirmed"
    assert entities["b"]["structure_source_file"] == "structures.csv"
    assert entities["b"]["compound_object_ids"] == "OBJ-B-001"
    assert snapshot["edges"][0]["pair_eligible"] == "yes"


def test_confirmed_structure_index_prefers_authoritative_normalized_label() -> None:
    snapshot = build_lineage_snapshot(
        [],
        [
            _confirmed_structure(
                "A (named lead)", "CCO", normalized_label="a",
                compound_entity_id="CMP-paper-confirmed-a",
            ),
            _confirmed_structure("B", "CCN"),
        ],
        annotations={"paper-confirmed": _confirmed_annotation()},
    )
    entities = {row["normalized_label"]: row for row in snapshot["entities"]}

    assert entities["a"]["canonical_smiles"] == "CCO"
    assert snapshot["edges"][0]["pair_eligible"] == "yes"


def test_pending_structure_rows_never_make_a_lineage_pair_eligible() -> None:
    pending = _confirmed_structure("B", "CCN")
    pending["confirmation_status"] = "pending"
    pending["structure_review_status"] = "pending"
    snapshot = build_lineage_snapshot(
        [], [_confirmed_structure("A", "CCO"), pending],
        annotations={"paper-confirmed": _confirmed_annotation()},
    )
    entities = {row["normalized_label"]: row for row in snapshot["entities"]}

    assert entities["b"]["canonical_smiles"] == "--"
    assert snapshot["edges"][0]["pair_eligible"] == "no"


def test_load_confirmed_structures_filters_nonfinal_rows(tmp_path: Path) -> None:
    path = tmp_path / "confirmed_compound_structures.csv"
    fieldnames = list(_confirmed_structure("A", "CCO"))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(_confirmed_structure("A", "CCO"))
        writer.writerow(_confirmed_structure(
            "B", "CCN",
            confirmation_status="pending",
            structure_review_status="pending",
        ))

    rows = load_confirmed_structures(path)

    assert len(rows) == 1
    assert rows[0]["compound_label"] == "A"
    assert rows[0]["confirmation_status"] == "structure_confirmed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"accepted_work_row_id": "--"},
        {"structure_source_file": "--"},
        {"structure_source_locator": "--"},
        {"compound_entity_id": "CMP-paper-confirmed-wrong"},
    ],
)
def test_load_confirmed_structures_requires_provenance_and_entity_key(
    tmp_path: Path, overrides: dict[str, str],
) -> None:
    path = tmp_path / "confirmed_compound_structures.csv"
    row = _confirmed_structure("A", "CCO", **overrides)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(ValueError, match="provenance|entity key"):
        load_confirmed_structures(path)


def test_pair_eligibility_rejects_unconfirmed_entity_even_with_parseable_smiles() -> None:
    edge = {
        "relation_status": "text_explicit",
        "parent_entity_id": "CMP-A",
        "derived_entity_id": "CMP-B",
    }
    entities = [
        {
            "compound_entity_id": "CMP-A", "canonical_smiles": "CCO",
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "structure_confirmed",
        },
        {
            "compound_entity_id": "CMP-B", "canonical_smiles": "CCN",
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "pending",
        },
    ]

    assert pair_eligible(edge, entities) is False


def test_pair_eligibility_rejects_legacy_confirmation_states() -> None:
    edge = {
        "relation_status": "text_explicit",
        "parent_entity_id": "CMP-A",
        "derived_entity_id": "CMP-B",
    }
    entities = [
        {
            "compound_entity_id": "CMP-A", "canonical_smiles": "CCO",
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "source_confirmed",
        },
        {
            "compound_entity_id": "CMP-B", "canonical_smiles": "CCN",
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "structure_confirmed",
        },
    ]

    assert pair_eligible(edge, entities) is False


@pytest.mark.parametrize("smiles", ["CC[N+](C)(C)C.[I-]", "C[O]"])
def test_pair_eligibility_rejects_multicomponent_and_radical_structures(
    smiles: str,
) -> None:
    edge = {
        "relation_status": "text_explicit",
        "parent_entity_id": "CMP-A",
        "derived_entity_id": "CMP-B",
    }
    entities = [
        {
            "compound_entity_id": "CMP-A", "canonical_smiles": smiles,
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "structure_confirmed",
        },
        {
            "compound_entity_id": "CMP-B", "canonical_smiles": "CCN",
            "structure_status": "complete_structure_resolved",
            "structure_review_status": "structure_confirmed",
        },
    ]

    assert pair_eligible(edge, entities) is False


def test_batch05_selection_is_fixed_unique_and_previously_unpublished() -> None:
    from generate_lineage_batch_05_annotations import (
        BATCH_05_PAPERS,
        validate_batch_selection,
    )

    assert BATCH_05_PAPERS == (
        ("a1d7361647de", "10.1021/acs.jmedchem.4c01072"),
        ("9fc4e02fbcdb", "10.1021/acs.jmedchem.4c01766"),
        ("8968e9a60ef9", "10.1021/acs.jmedchem.3c01920"),
        ("e64c071652ca", "10.1021/acs.jmedchem.4c01464"),
        ("ba6944db3fe2", "10.1021/acs.jmedchem.4c01760"),
        ("23fa35c9b113", "10.1021/acs.jmedchem.4c01048"),
        ("5589366efa06", "10.1021/acs.jmedchem.4c02531"),
        ("f2e855803f5a", "10.1021/acs.jmedchem.4c01787"),
        ("8b306e91bc78", "10.1021/acs.jmedchem.3c01790"),
        ("1a7457834b7a", "10.1021/acs.jmedchem.4c01851"),
        ("cfc4a0d0ef41", "10.1021/acs.jmedchem.4c01221"),
        ("a797514debbc", "10.1021/acs.jmedchem.4c01303"),
        ("d168508d74ca", "10.1021/acs.jmedchem.4c01092"),
        ("0eb39d3b45ae", "10.1021/acs.jmedchem.4c01568"),
        ("f501045da21f", "10.1021/acs.jmedchem.4c01283"),
        ("c6fdd5c7e071", "10.1021/acs.jmedchem.3c02246"),
        ("2f3a5d2f7fb0", "10.1021/acs.jmedchem.3c01961"),
        ("83d4f2ab5b7c", "10.1021/acs.jmedchem.3c02473"),
        ("dfe42148eabf", "10.1021/acs.jmedchem.3c01976"),
        ("14c9ce88d1c2", "10.1021/acs.jmedchem.4c02093"),
        ("5531836ee3c3", "10.1021/acs.jmedchem.3c02460"),
        ("1535ba2a9a58", "10.1021/acs.jmedchem.4c00860"),
        ("c3b3eba1f5b3", "10.1021/acs.jmedchem.3c01347"),
        ("df798aa2ca88", "10.1021/acs.jmedchem.4c00856"),
    )
    assert len({paper_id for paper_id, _ in BATCH_05_PAPERS}) == 24
    assert len({doi.lower() for _, doi in BATCH_05_PAPERS}) == 24
    validate_batch_selection()


def test_batch06_selection_is_fixed_unique_and_previously_unpublished() -> None:
    from generate_lineage_batch_06_annotations import (
        BATCH_06_PAPERS,
        validate_batch_selection,
    )

    assert BATCH_06_PAPERS == (
        ("2c96aaf509b1", "10.1021/acs.jmedchem.4c03149"),
        ("56f50284cedf", "10.1021/acs.jmedchem.4c01645"),
        ("434e5748f070", "10.1021/acs.jmedchem.4c01744"),
        ("f3d107dabbcb", "10.1021/acs.jmedchem.3c02302"),
        ("1485ed4aa91b", "10.1021/acs.jmedchem.4c00555"),
        ("c150a5edd8dd", "10.1021/acs.jmedchem.4c01815"),
        ("8991dc7472bd", "10.1021/acs.jmedchem.3c02441"),
        ("1994543a9112", "10.1021/acs.jmedchem.4c00265"),
        ("bf54bac4775b", "10.1021/acs.jmedchem.4c02377"),
        ("feef9e819b88", "10.1021/acs.jmedchem.4c01727"),
        ("2a98b0589a08", "10.1021/acs.jmedchem.4c00734"),
        ("c958fce90ec5", "10.1021/acs.jmedchem.4c01395"),
        ("e4043323f96c", "10.1021/acs.jmedchem.4c02169"),
        ("65e19df86a4a", "10.1021/acs.jmedchem.4c01323"),
        ("cab92325187b", "10.1021/acs.jmedchem.3c02288"),
        ("8e421ecc451e", "10.1021/acs.jmedchem.3c02046"),
        ("07dcad0214c3", "10.1021/acs.jmedchem.3c02203"),
        ("7e503b3382bf", "10.1021/acs.jmedchem.4c01178"),
        ("4bd630dc5dc8", "10.1021/acs.jmedchem.4c00972"),
        ("2d5a56fffb44", "10.1021/acs.jmedchem.4c00357"),
        ("c6c61d0fc737", "10.1021/acs.jmedchem.4c00643"),
        ("096b579fa25f", "10.1021/acs.jmedchem.3c01934"),
        ("023145d60eea", "10.1021/acs.jmedchem.4c00513"),
        ("b09de250fcb3", "10.1021/acs.jmedchem.4c03205"),
    )
    assert len({paper_id for paper_id, _ in BATCH_06_PAPERS}) == 24
    assert len({doi.lower() for _, doi in BATCH_06_PAPERS}) == 24
    validate_batch_selection()


def test_batch06_annotations_are_complete_and_conservative() -> None:
    from generate_lineage_batch_06_annotations import (
        BATCH_06_PAPERS,
        BATCH_06_VERSION,
        build_annotations,
    )

    annotations = build_annotations()
    expected_dois = dict(BATCH_06_PAPERS)

    assert set(annotations) == set(expected_dois)
    for paper_id, payload in annotations.items():
        assert payload["doi"].lower() == expected_dois[paper_id]
        assert payload["annotation_version"] == BATCH_06_VERSION
        assert payload["edges"]

        directed_edges: set[tuple[str, str]] = set()
        for edge in payload["edges"]:
            parent = normalize_label(edge["parent"])
            derived = normalize_label(edge["derived"])
            assert derived
            assert parent != derived

            relation_status = edge["relation_status"]
            if relation_status == "unresolved":
                assert edge["parent"] == "--"
            else:
                assert edge["parent"] != "--"
                assert relation_status in {
                    "text_explicit", "figure_explicit", "human_confirmed",
                }
                assert _compound_label_is_mentioned(
                    edge["derived"], edge["evidence_text"],
                )

            pair = (parent, derived)
            assert pair not in directed_edges
            directed_edges.add(pair)


def test_batch06_round_membership_does_not_become_an_immediate_parent() -> None:
    from generate_lineage_batch_06_annotations import build_annotations

    annotations = build_annotations()

    nlrp_rows = {
        normalize_label(row["derived"]): row
        for row in annotations["2d5a56fffb44"]["edges"]
    }
    assert nlrp_rows["59"]["parent"] == "20"
    assert nlrp_rows["63"]["parent"] == "54"
    assert nlrp_rows["64"]["parent"] == "55"
    for label in ("60", "61", "62"):
        assert nlrp_rows[label]["parent"] == "--"
        assert nlrp_rows[label]["relation_status"] == "unresolved"

    mcl_rows = {
        normalize_label(row["derived"]): row
        for row in annotations["c6c61d0fc737"]["edges"]
    }
    assert mcl_rows["21"]["parent"] == "20"
    assert mcl_rows["22"]["parent"] == "21"
    for label in ["20", *[str(number) for number in range(23, 48)]]:
        assert mcl_rows[label]["parent"] == "--"
        assert mcl_rows[label]["relation_status"] == "unresolved"


def test_batch06_rorgt_annotation_preserves_source_named_parentage() -> None:
    from generate_lineage_batch_06_annotations import build_annotations

    rows = {
        row["derived"]: row
        for row in build_annotations()["feef9e819b88"]["edges"]
    }

    assert rows["A2"]["parent"] == "A1"
    assert rows["A3"]["parent"] == "A1"
    assert rows["A2"]["relation_type"] == "substituent_transposition"
    assert rows["A3"]["relation_type"] == "substituent_transposition"
    for label in ("A4", "A5", "A6"):
        assert rows[label]["parent"] == "--"
        assert rows[label]["relation_status"] == "unresolved"
    assert rows["A9"]["parent"] == "A6"

    for number in range(1, 21):
        assert rows[f"D{number}"]["parent"] == "A1"
    for label in ("(R)-D4", "(S)-D4"):
        assert rows[label]["parent"] == "D4"
        assert rows[label]["relation_type"] == "stereoisomer_resolution"

    for prefix, last in (("B", 6), ("C", 13)):
        for number in range(1, last + 1):
            assert rows[f"{prefix}{number}"]["parent"] == "--"


def test_batch06_cephalosporin_annotation_keeps_preheader_campaign_members() -> None:
    from generate_lineage_batch_06_annotations import build_annotations

    rows = {
        row["derived"]: row
        for row in build_annotations()["1994543a9112"]["edges"]
    }

    for label in ("24a", "24b", "24c", "24d", "24e"):
        assert rows[label]["parent"] == "cefiderocol"
        assert rows[label]["relation_status"] == "figure_explicit"
    for label in ("58a", "58b", "58c"):
        assert rows[label]["parent"] == "--"
        assert rows[label]["relation_status"] == "unresolved"


def test_batch06_annotation_writer_emits_loadable_paper_local_json(
    tmp_path: Path,
) -> None:
    from generate_lineage_batch_06_annotations import (
        BATCH_06_PAPERS,
        write_annotations,
    )

    paths = write_annotations(tmp_path)
    loaded = load_lineage_annotations(tmp_path)

    assert {path.name for path in paths} == {
        f"{paper_id}.json" for paper_id, _ in BATCH_06_PAPERS
    }
    assert set(loaded) == {paper_id for paper_id, _ in BATCH_06_PAPERS}
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["paper_id"] == path.stem
        for path in paths
    )


def test_batch05_annotations_are_complete_and_conservative() -> None:
    from generate_lineage_batch_05_annotations import (
        BATCH_05_PAPERS,
        BATCH_05_VERSION,
        build_annotations,
    )

    annotations = build_annotations()
    expected_dois = dict(BATCH_05_PAPERS)

    assert set(annotations) == set(expected_dois)
    for paper_id, payload in annotations.items():
        assert payload["doi"].lower() == expected_dois[paper_id]
        assert payload["annotation_version"] == BATCH_05_VERSION
        assert payload["edges"]

        directed_edges: set[tuple[str, str]] = set()
        for edge in payload["edges"]:
            parent = normalize_label(edge["parent"])
            derived = normalize_label(edge["derived"])
            assert derived
            assert parent != derived

            relation_status = edge["relation_status"]
            if relation_status == "unresolved":
                assert edge["parent"] == "--"
            else:
                assert edge["parent"] != "--"
                assert relation_status in {
                    "text_explicit", "figure_explicit", "human_confirmed",
                }
                assert _compound_label_is_mentioned(
                    edge["derived"], edge["evidence_text"],
                )

            pair = (parent, derived)
            assert pair not in directed_edges
            directed_edges.add(pair)


def test_batch05_c6fdd_annotation_uses_only_observed_suffixed_series_labels() -> None:
    from generate_lineage_batch_05_annotations import build_annotations

    edges = build_annotations()["c6fdd5c7e071"]["edges"]
    derived_labels = {edge["derived"] for edge in edges}

    assert derived_labels.isdisjoint({"43", "47", "53", "55"})
    assert {
        "43a", "43b", "43c",
        "47a", "47b", "47c",
        "53a", "53b",
        "55a", "55b",
    } <= derived_labels


def test_batch05_annotation_writer_emits_loadable_paper_local_json(
    tmp_path: Path,
) -> None:
    from generate_lineage_batch_05_annotations import (
        BATCH_05_PAPERS,
        write_annotations,
    )

    paths = write_annotations(tmp_path)
    loaded = load_lineage_annotations(tmp_path)

    assert {path.name for path in paths} == {
        f"{paper_id}.json" for paper_id, _ in BATCH_05_PAPERS
    }
    assert set(loaded) == {paper_id for paper_id, _ in BATCH_05_PAPERS}
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["paper_id"] == path.stem
        for path in paths
    )


def test_batch05_component_selections_are_limited_to_reviewed_counterions() -> None:
    from publish_batch05_component_selections import (
        EXPECTED_COMPONENT_SELECTION_COUNTS,
        build_component_selection_candidates,
    )

    candidates = build_component_selection_candidates()

    assert EXPECTED_COMPONENT_SELECTION_COUNTS == {
        "14c9ce88d1c2": 57,
        "a797514debbc": 45,
        "dfe42148eabf": 1,
        "f2e855803f5a": 2,
    }

    counts: dict[str, int] = {}
    for row in candidates:
        paper_id = row["paper_id"]
        counts[paper_id] = counts.get(paper_id, 0) + 1
        assert row["confirmation_reason"] == "eligible"
        assert row["component_selection_status"] == "explicit_component_selected"
        assert row["reconstruction_method"] == "explicit_component_selection"
        assert "." not in row["canonical_isomeric_smiles"]
        assert row["review_decision"] == "accept"
        assert row["raw_structure_text"].count(".") == 1

    assert counts == EXPECTED_COMPONENT_SELECTION_COUNTS


def test_batch05_duplicate_source_repairs_are_exact_and_source_located() -> None:
    from publish_batch05_duplicate_source_repairs import (
        EXPECTED_PRIMARY_LOCATORS,
        build_duplicate_source_repair_candidates,
    )

    candidates = build_duplicate_source_repair_candidates()
    by_label = {row["normalized_label"]: row for row in candidates}

    assert EXPECTED_PRIMARY_LOCATORS == {
        "i15": "row=122",
        "i16": "row=123",
        "i19": "row=126",
    }
    assert set(by_label) == set(EXPECTED_PRIMARY_LOCATORS)
    assert len(candidates) == 3

    for label, row in by_label.items():
        assert row["paper_id"] == "5531836ee3c3"
        assert row["compound_entity_id"] == f"CMP-5531836ee3c3-{label}"
        assert row["source_locator"] == EXPECTED_PRIMARY_LOCATORS[label]
        assert row["reconstruction_method"] == "reviewed_complete_structure"
        assert row["source_match_status"] == "exact_complete_structure_match"
        assert row["review_decision"] == "accept"
        assert row["confirmation_reason"] == "eligible"
        assert _canonical_complete_smiles(row["canonical_isomeric_smiles"])


def test_batch05_prior_art_repairs_use_exact_identifiers_or_paper_source() -> None:
    from publish_batch05_prior_art_repairs import (
        EXTERNAL_IDENTIFIER_REPAIRS,
        REVIEWED_FIGURE_REPAIRS,
        build_prior_art_repair_candidates,
    )

    external = {
        (row["paper_id"], normalize_label(row["compound_label"])): row
        for row in EXTERNAL_IDENTIFIER_REPAIRS
    }
    assert set(external) == {
        ("23fa35c9b113", "1"),
        ("23fa35c9b113", "2a"),
        ("23fa35c9b113", "2b"),
        ("23fa35c9b113", "2c"),
        ("5589366efa06", "sgcpikfyve1"),
        ("f2e855803f5a", "cc90009"),
    }
    assert {row["pubchem_cid"] for row in external.values()} == {
        "5288382", "6505803", "5288674", "9893658", "165368936",
        "118647211",
    }

    candidates = build_prior_art_repair_candidates()
    by_key = {
        (row["paper_id"], row["normalized_label"]): row
        for row in candidates
    }
    figure_keys = {
        (row["paper_id"], normalize_label(row["compound_label"]))
        for row in REVIEWED_FIGURE_REPAIRS
    }
    assert figure_keys == {
        ("a1d7361647de", "1"),
        ("a1d7361647de", "3"),
        ("cfc4a0d0ef41", "7"),
        ("df798aa2ca88", "4a"),
        ("e64c071652ca", "m17b15"),
    }
    assert set(by_key) == (
        set(external) | figure_keys | {("8968e9a60ef9", "dla")}
    )
    for row in candidates:
        assert row["review_decision"] == "accept"
        assert row["confirmation_reason"] == "eligible"
        assert _canonical_complete_smiles(row["canonical_isomeric_smiles"])

    dla = by_key[("8968e9a60ef9", "dla")]
    assert dla["compound_entity_id"] == "CMP-8968e9a60ef9-dla"
    assert dla["source_label"] == "DA"
    assert dla["source_locator"] == "row=64"
    assert dla["source_match_status"] == "exact_complete_structure_match"

    for key in figure_keys:
        row = by_key[key]
        assert row["reconstruction_method"] == "reviewed_complete_structure"
        assert row["source_match_status"] == "visual_graph_match"
        assert row["structure_source_type"] == "source_figure_reconstruction"


def test_figure_explicit_evidence_retains_figure_strength() -> None:
    annotation = {
        "paper_id": "paper-figure",
        "doi": "10.1021/figure-evidence",
        "annotation_status": "evidence_annotated",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [{
            "lineage": "01",
            "root": "1",
            "parent": "1",
            "derived": "2",
            "page": 3,
            "evidence_text": "Figure 2 shows compound 2 designed from compound 1.",
            "locator": "Figure 2",
            "modification_site": "aryl substituent",
            "from_group": "H",
            "to_group": "F",
            "relation_type": "substituent_addition",
            "relation_status": "figure_explicit",
            "relation_confidence": "high",
        }],
    }

    snapshot = build_lineage_snapshot(
        [{
            "paper_id": "paper-figure",
            "page": "3",
            "evidence_text": "Figure 2 shows compound 2 designed from compound 1.",
        }],
        [],
        annotations={"paper-figure": annotation},
    )

    assert snapshot["evidence"][0]["evidence_strength"] == "figure_explicit"


def test_annotation_evidence_is_not_replaced_by_unrelated_same_page_text() -> None:
    reviewed = "Changing compound 1 from pyridyl to phenyl produced compound 2."
    unrelated = (
        "Compounds 14-19 introduced pyrimidine and thiophene around compound 2."
    )
    annotation = {
        "paper_id": "paper-owned-evidence",
        "doi": "10.1021/owned-evidence",
        "annotation_status": "evidence_annotated",
        "preferred_names": {},
        "origins": {},
        "activity_columns": [],
        "edges": [{
            "lineage": "01",
            "root": "1",
            "parent": "1",
            "derived": "2",
            "page": 5,
            "evidence_text": reviewed,
            "locator": "Molecular design; Table 1",
            "modification_site": "aryl group",
            "from_group": "pyridyl",
            "to_group": "phenyl",
            "relation_type": "substituent_replacement",
            "relation_status": "figure_explicit",
            "relation_confidence": "high",
        }],
    }

    snapshot = build_lineage_snapshot(
        [{
            "paper_id": "paper-owned-evidence",
            "page": "5",
            "evidence_text": unrelated,
        }],
        [],
        annotations={"paper-owned-evidence": annotation},
    )

    assert snapshot["evidence"][0]["evidence_text"] == reviewed
