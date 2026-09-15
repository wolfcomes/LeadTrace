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
from app.assets.models import AssetAccessLevel, AssetCategory
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
from app.molecule_proposals.models import (
    MoleculeProposal,
    MoleculeProposalDisposition,
)
from app.papers.models import Paper
from app.revisions.models import ObjectRevision
from app.structures.models import Structure
from app.visual_objects.models import VisualObject
from app.visual_objects.models import (
    VisualObjectAssetBinding,
    VisualObjectRegionBinding,
    VisualRegion,
)


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
        assert _count(session, VisualRegion) == 1
        assert _count(session, MoleculeProposal) == 1
        assert _count(session, ObjectRevision) == 12
        assert _count(session, Asset) == 2
        assert _count(session, ImportAssetLink) == 4
        proposal = session.scalar(select(MoleculeProposal))
        assert proposal is not None
        proposal_revision = session.scalar(
            select(ObjectRevision).where(ObjectRevision.object_id == proposal.id)
        )
        assert proposal_revision is not None
        assert proposal_revision.proposal_disposition == (
            MoleculeProposalDisposition.PENDING.value
        )
        normalized = proposal_revision.snapshot["normalized_values"]
        assert normalized["raw_smiles"] == "CCO"
        assert normalized["token_confidences"] == [
            {"token": "C", "confidence": 0.9}
        ]
        assert normalized["model_version"] == "ocsr-v1"
        assert normalized["crop_asset_id"] == str(proposal.crop_asset_id)
        assert "crop_path" not in normalized
        assert str(baseline_fixture["workspace"]) not in json.dumps(
            proposal_revision.snapshot
        )
        visual = session.scalar(select(VisualObject))
        region = session.scalar(select(VisualRegion))
        assert visual is not None and region is not None
        region_revision = session.scalar(
            select(ObjectRevision).where(ObjectRevision.object_id == region.id)
        )
        assert region.asset_id is not None
        assert region.page_number == 1
        assert region_revision is not None
        assert region_revision.region_x0 == pytest.approx(0.25)
        assert region_revision.region_y0 == pytest.approx(0.3125)
        assert region_revision.region_x1 == pytest.approx(5 / 12)
        assert region_revision.region_y1 == pytest.approx(0.4375)
        assert region_revision.region_rotation == 0
        assert region_revision.snapshot["provenance"] == {
            "candidate_id": "CAND-1",
            "object_id": "OBJ-1",
        }
        region_binding = session.scalar(select(VisualObjectRegionBinding))
        crop_binding = session.scalar(select(VisualObjectAssetBinding))
        assert region_binding is not None
        assert region_binding.visual_object_id == visual.id
        assert region_binding.region_id == region.id
        assert region_binding.changeset_id is None
        assert crop_binding is not None
        assert crop_binding.visual_object_id == visual.id
        assert crop_binding.asset_id == proposal.crop_asset_id
        assert crop_binding.is_primary is True
        assert proposal.source_region_id == region.id
        evidence_stage = session.scalar(
            select(ImportStagingRecord).where(
                ImportStagingRecord.record_type == "evidence"
            )
        )
        assert evidence_stage is not None
        assert evidence_stage.raw_values["evidence_text"] == "line one\nline two"
        assert evidence_stage.source_row_locator == "row:2"


def test_apply_keeps_a_localization_blocker_for_invalid_object_geometry(
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

    def invalidate_local_bounds(rows: list[dict[str, str]]) -> None:
        rows[0]["local_x1"] = "1.2"

    _rewrite_csv(
        source_root
        / "09_paper_review"
        / "auto_fill"
        / "first_page_molecule_objects.csv",
        invalidate_local_bounds,
    )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with auth_session_factory.begin() as session:
        importer.apply(session)

    with auth_session_factory() as session:
        visual = session.scalar(select(VisualObject))
        assert visual is not None
        revision = session.scalar(
            select(ObjectRevision).where(ObjectRevision.object_id == visual.id)
        )
        assert revision is not None
        assert revision.snapshot["review_blockers"] == ["localization"]
        assert _count(session, VisualRegion) == 0
        assert _count(session, VisualObjectRegionBinding) == 0
        assert _count(session, VisualObjectAssetBinding) == 1


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
        assert _count(session, ImportAssetLink) == 5


def test_apply_rolls_back_if_a_fact_file_changes_after_reconciliation(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    facts = (
        source_root
        / "09_paper_review"
        / "auto_fill"
        / "compound_activities.csv"
    )
    original_stage = BaselineImporter._stage_records

    def mutate_then_stage(
        session: Session,
        batch_id: object,
        data: object,
    ) -> None:
        facts.write_bytes(facts.read_bytes() + b"\n")
        original_stage(session, batch_id, data)  # type: ignore[arg-type]

    monkeypatch.setattr(
        BaselineImporter,
        "_stage_records",
        staticmethod(mutate_then_stage),
    )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with pytest.raises(ImportValidationError, match="changed"):
        with auth_session_factory.begin() as session:
            importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 0
        assert _count(session, ImportReleaseCandidate) == 0
        assert _count(session, ObjectRevision) == 0


def test_apply_rejects_a_preexisting_corrupt_asset_instead_of_reusing_it(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    paper_pdf = baseline_fixture["paper_pdf"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(paper_pdf, Path)
    content = paper_pdf.read_bytes()
    with auth_session_factory.begin() as session:
        session.add(
            Asset(
                storage_key="source/baseline/source_pdfs/articles/paper.pdf",
                original_filename="paper.pdf",
                sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                mime_type="application/pdf",
                category=AssetCategory.ARTICLE_PDF,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.CORRUPT,
                derivation_metadata={},
                source_metadata={},
            )
        )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with pytest.raises(ImportValidationError, match="integrity"):
        with auth_session_factory.begin() as session:
            importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 0
        assert _count(session, ImportReleaseCandidate) == 0
        assert _count(session, Asset) == 1


def test_apply_rejects_a_preexisting_article_pdf_with_visitor_access(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    paper_pdf = baseline_fixture["paper_pdf"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(paper_pdf, Path)
    content = paper_pdf.read_bytes()
    with auth_session_factory.begin() as session:
        session.add(
            Asset(
                storage_key="source/baseline/source_pdfs/articles/paper.pdf",
                original_filename="paper.pdf",
                sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                mime_type="application/pdf",
                category=AssetCategory.ARTICLE_PDF,
                access_level=AssetAccessLevel.VISITOR,
                integrity_state=AssetIntegrityState.VERIFIED,
                derivation_metadata={},
                source_metadata={},
            )
        )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with pytest.raises(ImportValidationError, match="policy"):
        with auth_session_factory.begin() as session:
            importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 0
        assert _count(session, ImportReleaseCandidate) == 0
        assert _count(session, Asset) == 1


def test_apply_rejects_a_preexisting_article_pdf_with_the_wrong_category(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    paper_pdf = baseline_fixture["paper_pdf"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(paper_pdf, Path)
    content = paper_pdf.read_bytes()
    with auth_session_factory.begin() as session:
        session.add(
            Asset(
                storage_key="source/baseline/source_pdfs/articles/paper.pdf",
                original_filename="paper.pdf",
                sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                mime_type="application/pdf",
                category=AssetCategory.EXTERNAL_SOURCE,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.VERIFIED,
                derivation_metadata={},
                source_metadata={},
            )
        )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with pytest.raises(ImportValidationError, match="policy"):
        with auth_session_factory.begin() as session:
            importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 0
        assert _count(session, ImportReleaseCandidate) == 0
        assert _count(session, Asset) == 1


def test_apply_quarantines_a_truncated_image_and_requires_admin_access(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    crop = baseline_fixture["crop"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(crop, Path)
    crop.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    crop_key = next(
        item["path"]
        for item in manifest["files"]
        if item["path"].endswith("/OBJ-1.png")
    )
    for item in manifest["files"]:
        if item["path"] == crop_key:
            item["byte_size"] = crop.stat().st_size
            item["sha256"] = hashlib.sha256(crop.read_bytes()).hexdigest()
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
        asset = session.scalar(select(Asset).where(Asset.original_filename == "OBJ-1.png"))
        assert asset is not None
        assert asset.category is AssetCategory.REVIEWED_CROP
        assert asset.integrity_state is AssetIntegrityState.QUARANTINED
        assert asset.access_level is AssetAccessLevel.ADMIN


def test_apply_rejects_a_preexisting_quarantined_asset_without_admin_access(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    crop = baseline_fixture["crop"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(crop, Path)
    crop.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    crop_key = next(
        item["path"]
        for item in manifest["files"]
        if item["path"].endswith("/OBJ-1.png")
    )
    content_hash = hashlib.sha256(crop.read_bytes()).hexdigest()
    for item in manifest["files"]:
        if item["path"] == crop_key:
            item["byte_size"] = crop.stat().st_size
            item["sha256"] = content_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with auth_session_factory.begin() as session:
        session.add(
            Asset(
                storage_key=f"source/baseline/{crop_key}",
                original_filename="OBJ-1.png",
                sha256=content_hash,
                byte_size=crop.stat().st_size,
                mime_type="image/png",
                category=AssetCategory.REVIEWED_CROP,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.QUARANTINED,
                derivation_metadata={},
                source_metadata={},
            )
        )
    importer = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    )

    with pytest.raises(ImportValidationError, match="policy"):
        with auth_session_factory.begin() as session:
            importer.apply(session)

    with auth_session_factory() as session:
        assert _count(session, ImportBatch) == 0
        assert _count(session, ImportReleaseCandidate) == 0
        assert _count(session, Asset) == 1
