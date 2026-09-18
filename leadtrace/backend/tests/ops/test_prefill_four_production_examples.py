from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json

import pytest

from app.ai_prefill.contracts import AiPrefillPayload
from leadtrace.ops.pilot.prefill_four_production_examples import (
    EXPECTED_PAYLOAD_COUNTS,
    TARGETS,
    ProductionPrefillError,
    assert_expected_counts,
    canonical_payload_hash,
    compare_reviewed_manifest,
    payload_counts,
    require_apply_success,
    validate_backup_for_apply,
    validate_payload,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "bibliography": {"doi": "10.1000/example"},
        "compounds": [
            {
                "ref": "parent",
                "compound_label": "1",
                "structure": {"smiles": "CCO"},
            },
            {
                "ref": "child",
                "compound_label": "2",
                "structure": {"smiles": "CCN"},
            },
        ],
        "lineages": [
            {
                "ref": "lineage",
                "lineage_label": "Lead series",
                "members": [
                    {"compound_ref": "parent", "role": "root"},
                    {"compound_ref": "child", "role": "terminal"},
                ],
                "edges": [
                    {
                        "ref": "edge",
                        "parent_compound_ref": "parent",
                        "child_compound_ref": "child",
                        "relation_type": "substitution",
                    }
                ],
            }
        ],
        "evidence": [
            {
                "ref": "evidence",
                "kind": "text",
                "page_number": 2,
                "quoted_text": "Compound 2 replaced the methyl group of compound 1.",
                "caption": "Results",
            }
        ],
        "edge_evidence_links": [
            {
                "edge_ref": "edge",
                "evidence_ref": "evidence",
                "role": "supports",
            }
        ],
    }


def test_targets_and_reviewed_counts_are_fixed_to_the_approved_four_papers() -> None:
    assert tuple(TARGETS) == (
        "LT-JMC-2024-67-05-004",
        "LT-JMC-2024-67-05-005",
        "LT-JMC-2024-67-05-010",
        "LT-JMC-2024-67-05-013",
    )
    assert EXPECTED_PAYLOAD_COUNTS == {
        "LT-JMC-2024-67-05-004": {
            "compounds": 11,
            "structures": 11,
            "structure_locators": 0,
            "lineages": 1,
            "edges": 6,
            "evidence": 6,
            "edge_evidence_links": 6,
            "activities": 0,
        },
        "LT-JMC-2024-67-05-005": {
            "compounds": 41,
            "structures": 41,
            "structure_locators": 0,
            "lineages": 5,
            "edges": 35,
            "evidence": 35,
            "edge_evidence_links": 35,
            "activities": 0,
        },
        "LT-JMC-2024-67-05-010": {
            "compounds": 6,
            "structures": 6,
            "structure_locators": 0,
            "lineages": 1,
            "edges": 5,
            "evidence": 5,
            "edge_evidence_links": 5,
            "activities": 0,
        },
        "LT-JMC-2024-67-05-013": {
            "compounds": 10,
            "structures": 10,
            "structure_locators": 0,
            "lineages": 1,
            "edges": 8,
            "evidence": 8,
            "edge_evidence_links": 8,
            "activities": 0,
        },
    }


def test_payload_hash_is_canonical_and_counts_are_structural() -> None:
    payload = AiPrefillPayload.model_validate(_payload())
    reordered = AiPrefillPayload.model_validate(
        {"schema_version": 1, **dict(reversed(list(_payload().items())[:-1])),
         "edge_evidence_links": _payload()["edge_evidence_links"]}
    )

    assert canonical_payload_hash(payload) == canonical_payload_hash(reordered)
    assert payload_counts(payload) == {
        "compounds": 2,
        "structures": 2,
        "structure_locators": 0,
        "lineages": 1,
        "edges": 1,
        "evidence": 1,
        "edge_evidence_links": 1,
        "activities": 0,
    }


def test_validate_payload_accepts_supported_edges_current_pdf_quote_and_rdkit() -> None:
    payload = AiPrefillPayload.model_validate(_payload())

    validate_payload(
        payload,
        expected_doi="10.1000/example",
        page_count=2,
        page_texts={
            1: "Title",
            2: "Compound 2 replaced the methyl group of compound 1.",
        },
    )


def test_validate_payload_rejects_an_edge_without_supporting_evidence() -> None:
    raw = deepcopy(_payload())
    raw["edge_evidence_links"] = []
    payload = AiPrefillPayload.model_validate(raw)

    with pytest.raises(ProductionPrefillError, match="supporting Evidence"):
        validate_payload(
            payload,
            expected_doi="10.1000/example",
            page_count=2,
            page_texts={1: "Title", 2: "Evidence"},
        )


def test_validate_payload_rejects_a_paraphrase_not_present_on_declared_page() -> None:
    payload = AiPrefillPayload.model_validate(_payload())

    with pytest.raises(ProductionPrefillError, match="not found on PDF page 2"):
        validate_payload(
            payload,
            expected_doi="10.1000/example",
            page_count=2,
            page_texts={1: "Title", 2: "Different source text"},
        )


def test_validate_payload_rejects_an_unparseable_structure() -> None:
    raw = deepcopy(_payload())
    raw["compounds"][0]["structure"] = {"smiles": "not a smiles"}  # type: ignore[index]
    payload = AiPrefillPayload.model_validate(raw)

    with pytest.raises(ProductionPrefillError, match="Structure validation"):
        validate_payload(
            payload,
            expected_doi="10.1000/example",
            page_count=2,
            page_texts={
                1: "Title",
                2: "Compound 2 replaced the methyl group of compound 1.",
            },
        )


def test_validate_payload_rejects_activity_without_source_evidence() -> None:
    raw = deepcopy(_payload())
    raw["activities"] = [
        {
            "compound_ref": "child",
            "assay_name": "binding",
            "metric": "IC50",
            "operator": "=",
            "value": "1.0",
            "unit": "nM",
        }
    ]
    payload = AiPrefillPayload.model_validate(raw)

    with pytest.raises(ProductionPrefillError, match="Activity requires Evidence"):
        validate_payload(
            payload,
            expected_doi="10.1000/example",
            page_count=2,
            page_texts={
                1: "Title",
                2: "Compound 2 replaced the methyl group of compound 1.",
            },
        )


def test_expected_counts_reject_pipeline_output_drift() -> None:
    payload = AiPrefillPayload.model_validate(_payload())

    with pytest.raises(ProductionPrefillError, match="counts changed"):
        assert_expected_counts(
            "LT-JMC-2024-67-05-004",
            payload,
        )


def test_apply_failure_is_raised_so_the_outer_transaction_rolls_back() -> None:
    class Run:
        status = "failed"
        error_summary = "transactional validation failed"

    class Result:
        applied = False
        run = Run()

    with pytest.raises(ProductionPrefillError, match="transactional validation"):
        require_apply_success("LT-JMC-2024-67-05-004", Result())


def test_apply_requires_payload_hashes_from_reviewed_dry_run_manifest() -> None:
    reviewed = {
        "schema_version": 1,
        "mode": "dry-run",
        "papers": {
            "LT-JMC-2024-67-05-004": {
                "payload_sha256": "a" * 64,
                "counts": EXPECTED_PAYLOAD_COUNTS["LT-JMC-2024-67-05-004"],
            }
        },
    }
    current = {
        "LT-JMC-2024-67-05-004": {
            "payload_sha256": "b" * 64,
            "counts": EXPECTED_PAYLOAD_COUNTS["LT-JMC-2024-67-05-004"],
        }
    }

    with pytest.raises(ProductionPrefillError, match="payload hash changed"):
        compare_reviewed_manifest(reviewed, current)


def test_apply_requires_a_verified_database_backup_newer_than_dry_run(
    tmp_path,
) -> None:
    artifact = tmp_path / "database.dump.age"
    artifact.write_bytes(b"encrypted backup")
    started = datetime.now(UTC)
    metadata = {
        "schema_version": 1,
        "backup_id": "prefill-four-test-database",
        "backup_scope": "database",
        "started_at": started.isoformat(),
        "completed_at": (started + timedelta(seconds=1)).isoformat(),
        "outcome": "success",
        "versions": {
            "application": "0.1.0",
            "schema": "0025_ai_prefill_runs",
            "release": "paper-centric-pilot",
        },
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:test",
            "payloads_encrypted": True,
        },
        "destination": {"kind": "separate_disk", "identity": "test"},
        "artifacts": {
            "database_dump": {
                "path": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": artifact.stat().st_size,
            }
        },
    }
    metadata_path = tmp_path / "backup-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    reviewed = {
        "generated_at": (started - timedelta(seconds=1)).isoformat(),
    }

    result = validate_backup_for_apply(metadata_path, reviewed)

    assert result["backup_id"] == "prefill-four-test-database"
    assert result["database_dump_sha256"] == metadata["artifacts"][
        "database_dump"
    ]["sha256"]

    reviewed["generated_at"] = (started + timedelta(minutes=1)).isoformat()
    with pytest.raises(ProductionPrefillError, match="predates the reviewed dry-run"):
        validate_backup_for_apply(metadata_path, reviewed)
