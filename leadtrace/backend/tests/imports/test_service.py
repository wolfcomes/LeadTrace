from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity
from app.assets.models import Asset, AssetIntegrityState
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportReleaseCandidate,
    ImportStagingRecord,
)
from app.imports.service import BaselineImporter, ImportValidationError
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.revisions.models import ObjectRevision
from app.structures.models import Structure
from app.visual_objects.models import VisualObject


def _count(session: Session, model: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _rewrite_csv(path: Path, transform: object) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = list(reader)
    assert callable(transform)
    transform(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_apply_is_staged_atomic_and_idempotent(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with auth_session_factory.begin() as session:
        first = importer.apply(session)
    with auth_session_factory.begin() as session:
        second = importer.apply(session)

    assert first.created is True
    assert second.created is False
    assert second.batch_id == first.batch_id
    assert second.release_candidate_id == first.release_candidate_id
    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 1
        assert _count(session, ImportReleaseCandidate) == 1
        candidate = session.scalar(select(ImportReleaseCandidate))
        assert candidate is not None
        assert candidate.status == "imported_baseline"
        assert candidate.is_current is False
        assert _count(session, Paper) == 1
        assert _count(session, Compound) == 2
        assert _count(session, Structure) == 2
        assert _count(session, Evidence) == 1
        assert _count(session, Activity) == 1
        assert _count(session, Lineage) == 1
        assert _count(session, LineageEdge) == 1
        assert _count(session, VisualObject) == 1
        assert _count(session, ObjectRevision) == 10
        assert _count(session, Asset) == 2
        assert _count(session, ImportAssetLink) == 3
        evidence_stage = session.scalar(
            select(ImportStagingRecord).where(
                ImportStagingRecord.record_type == "evidence"
            )
        )
        assert evidence_stage is not None
        assert evidence_stage.raw_values["evidence_text"] == "line one\nline two"
        assert evidence_stage.source_row_locator == "row:2"


def test_validation_failure_leaves_existing_candidate_unchanged(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )
    with auth_session_factory.begin() as session:
        existing = importer.apply(session)

    invalid_expected = {
        "counts": {**expected["counts"], "compound_entities": 999},
        "integrity_expectations": expected["integrity_expectations"],
    }
    invalid_importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=invalid_expected,
        source_manifest_path=manifest_path,
    )
    with pytest.raises(ImportValidationError, match="reconcile"):
        with auth_session_factory.begin() as session:
            invalid_importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 1
        assert _count(session, ImportReleaseCandidate) == 1
        candidate = session.scalar(select(ImportReleaseCandidate))
        assert candidate is not None
        assert candidate.id == existing.release_candidate_id
        assert candidate.is_current is False


def test_apply_quarantines_a_non_utf8_source_table_without_losing_exact_link(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    workspace = baseline_fixture["workspace"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(workspace, Path)
    auto = source_root / "09_paper_review" / "auto_fill"
    source_table = auto / "lineage_structure_sources" / "legacy.csv"
    source_table.parent.mkdir(parents=True)
    source_table.write_bytes(b"name,value\ncaf\xe9,1\n")

    def set_structure_source(rows: list[dict[str, str]]) -> None:
        rows[0]["structure_source_file"] = "legacy.csv"

    _rewrite_csv(auto / "confirmed_compound_structures.csv", set_structure_source)

    def set_source_manifest(rows: list[dict[str, str]]) -> None:
        rows[0]["paper_id"] = "paper-1"
        rows[0]["source_file"] = "legacy.csv"
        rows[0]["local_path"] = str(source_table)

    _rewrite_csv(auto / "structure_source_manifest.csv", set_source_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": source_table.relative_to(workspace).as_posix(),
            "byte_size": source_table.stat().st_size,
            "mtime_ns": source_table.stat().st_mtime_ns,
            "sha256": hashlib.sha256(source_table.read_bytes()).hexdigest(),
            "category": "table",
        }
    )
    manifest["file_count"] += 1
    manifest["total_bytes"] += source_table.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with auth_session_factory.begin() as session:
        importer.apply(session)

    with auth_session_factory() as session:
        asset = session.scalar(
            select(Asset).where(Asset.original_filename == "legacy.csv")
        )
        assert asset is not None
        assert asset.integrity_state is AssetIntegrityState.QUARANTINED
        assert _count(session, ImportAssetLink) == 4
