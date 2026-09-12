from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
from uuid import UUID

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity
from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.imports.models import ImportBatch
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.releases.manifest import capture_release_artifact_manifest
from app.releases.models import Release, ReleaseItem
from app.revisions.models import (
    ActivityState,
    EvidenceState,
    StructureState,
)
from app.revisions.service import RevisionService
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import MoleculeObjectType, VisualObject, VisualRegion
from app.releases.aggregate import _reference_ids
import leadtrace.ops.restore.verify_restored_system as restore_verification
from leadtrace.ops.backup.verify_backup import verify_backup
from leadtrace.ops.restore.verify_restored_system import (
    _safe_database_counts,
    _verify_http_workflow,
    verify_asset_restore,
    verify_restored_system,
)


EXPECTED_RELEASE_AGGREGATE = {
    "counts": {
        "corpus_papers": 1,
        "lineage_papers": 1,
        "lineages": 1,
        "compound_entities": 2,
        "lineage_edges": 1,
        "activity_rows": 1,
        "complete_structures": 2,
        "structure_confirmed": 2,
        "missing_or_non_unique": 0,
        "pair_ready_edges": 1,
        "papers_with_pair_ready": 1,
    },
    "integrity": {
        "self_loops": 0,
        "duplicate_directed_edges": 0,
        "unresolved_pair_ready_edges": 0,
        "dangling_entity_references": 0,
        "dangling_evidence_references": 0,
        "invalid_pair_endpoints": 0,
        "published_missing_or_corrupt_assets": 0,
    },
}


def test_release_reference_keys_are_scoped_to_their_paper() -> None:
    first_paper = UUID(int=1)
    second_paper = UUID(int=2)
    first_compound = UUID(int=3)
    second_compound = UUID(int=4)
    keys = {
        (first_paper, "CMP-1"): first_compound,
        (second_paper, "CMP-1"): second_compound,
    }

    assert _reference_ids("CMP-1", keys=keys, paper_id=second_paper) == (
        second_compound,
    )


def _published_revision(
    session: Session,
    *,
    domain_object: object,
    actor_id: UUID,
    snapshot: dict[str, object],
    structure_state: StructureState | None = None,
    evidence_state: EvidenceState | None = None,
    activity_state: ActivityState | None = None,
    canonical_smiles: str | None = None,
    relation_status: str | None = None,
):
    return RevisionService().create_revision(
        session,
        object_identity=domain_object,  # type: ignore[arg-type]
        actor_id=actor_id,
        reason="Restore aggregate fixture",
        snapshot=snapshot,
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
        structure_state=structure_state,
        evidence_state=evidence_state,
        activity_state=activity_state,
        canonical_smiles=canonical_smiles,
        relation_status=relation_status,
    )


def _seed_current_release(
    session_factory: sessionmaker[Session],
    *,
    invalid_activity_evidence: bool = False,
    source_root: Path | None = None,
) -> dict[str, UUID]:
    with session_factory.begin() as session:
        actor = UserService().create_user(
            session,
            username="restore.aggregate.admin",
            display_name="Restore aggregate admin",
            role=UserRole.ADMIN,
            initial_password="Fixture-password-123!",
        )
        session.add(
            ImportBatch(
                source_fingerprint="f" * 64,
                status="completed",
                counts={key: 999 for key in EXPECTED_RELEASE_AGGREGATE["counts"]},
                integrity={
                    key: 0 for key in EXPECTED_RELEASE_AGGREGATE["integrity"]
                },
                asset_linkage={},
                completed_at=datetime.now(UTC),
            )
        )
        paper = Paper(paper_key="aggregate-paper", doi="10.1000/aggregate")
        session.add(paper)
        session.flush()
        compounds = [
            Compound(
                paper_id=paper.id,
                local_identity=f"CMP-{index}",
                display_label=f"Compound {index}",
                normalized_label=f"compound {index}",
            )
            for index in (1, 2)
        ]
        lineage = Lineage(paper_id=paper.id, lineage_key="LINEAGE-1")
        evidence = Evidence(paper_id=paper.id, evidence_key="EVID-1")
        session.add_all([*compounds, lineage, evidence])
        session.flush()
        structures = [
            Structure(
                paper_id=paper.id,
                compound_id=compound.id,
                structure_key=f"STRUCTURE-{index}",
            )
            for index, compound in enumerate(compounds, start=1)
        ]
        activity = Activity(
            paper_id=paper.id,
            compound_id=compounds[1].id,
            activity_key="ACT-1",
        )
        edge = LineageEdge(
            paper_id=paper.id,
            lineage_id=lineage.id,
            edge_key="EDGE-1",
            parent_compound_id=compounds[0].id,
            derived_compound_id=compounds[1].id,
        )
        source_asset = None
        if source_root is not None:
            source_root.mkdir(parents=True, exist_ok=True)
            source_file = source_root / "source.txt"
            source_file.write_bytes(b"release source asset\n")
            source_asset = Asset(
                storage_key="source/baseline/source.txt",
                original_filename=source_file.name,
                sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
                byte_size=source_file.stat().st_size,
                mime_type="text/plain",
                category=AssetCategory.EXTERNAL_SOURCE,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.VERIFIED,
                derivation_metadata={},
                source_metadata={},
                created_by_id=actor.id,
            )
            session.add(source_asset)
            session.flush()
        visual_region = VisualRegion(
            paper_id=paper.id,
            region_key="REGION-1",
            page_number=1,
            asset_id=source_asset.id if source_asset is not None else None,
        )
        visual_object = VisualObject(
            paper_id=paper.id,
            object_key="VISUAL-1",
            object_type=MoleculeObjectType.LINKER,
        )
        session.add_all([*structures, activity, edge, visual_region, visual_object])
        session.flush()

        revisions = [
            _published_revision(
                session,
                domain_object=paper,
                actor_id=actor.id,
                snapshot={"paper_key": paper.paper_key},
            ),
            *[
                _published_revision(
                    session,
                    domain_object=compound,
                    actor_id=actor.id,
                    snapshot={
                        "paper_id": str(paper.id),
                        "local_identity": compound.local_identity,
                    },
                )
                for compound in compounds
            ],
            *[
                _published_revision(
                    session,
                    domain_object=structure,
                    actor_id=actor.id,
                    snapshot={
                        "compound_id": str(structure.compound_id),
                        "canonical_smiles": "CCO",
                        "structure_state": "structure_confirmed",
                    },
                    structure_state=StructureState.STRUCTURE_CONFIRMED,
                    canonical_smiles="CCO",
                )
                for structure in structures
            ],
            _published_revision(
                session,
                domain_object=lineage,
                actor_id=actor.id,
                snapshot={"paper_id": str(paper.id), "lineage_key": "LINEAGE-1"},
            ),
            _published_revision(
                session,
                domain_object=evidence,
                actor_id=actor.id,
                snapshot={
                    "compound_ids": [str(compounds[0].id), str(compounds[1].id)],
                    "evidence_key": "EVID-1",
                },
                evidence_state=EvidenceState.CONFIRMED,
            ),
            _published_revision(
                session,
                domain_object=activity,
                actor_id=actor.id,
                snapshot={
                    "compound_id": str(compounds[1].id),
                    "evidence_ids": (
                        ["NOT-A-REAL-EVIDENCE"]
                        if invalid_activity_evidence
                        else [str(evidence.id)]
                    ),
                },
                activity_state=ActivityState.CONFIRMED,
            ),
            _published_revision(
                session,
                domain_object=edge,
                actor_id=actor.id,
                snapshot={
                    "lineage_id": str(lineage.id),
                    "parent_compound_id": str(compounds[0].id),
                    "derived_compound_id": str(compounds[1].id),
                    "evidence_ids": [str(evidence.id)],
                    "pair_ready": True,
                    "relation_status": "confirmed",
                },
                relation_status="confirmed",
            ),
            _published_revision(
                session,
                domain_object=visual_region,
                actor_id=actor.id,
                snapshot={"page_number": 1, "region_key": "REGION-1"},
            ),
            _published_revision(
                session,
                domain_object=visual_object,
                actor_id=actor.id,
                snapshot={
                    "object_key": "VISUAL-1",
                    "object_type": MoleculeObjectType.LINKER.value,
                },
            ),
        ]
        session.flush()
        release = Release(
            release_key="aggregate-r1",
            title="Aggregate release",
            notes="",
            metrics={},
            published_by_id=actor.id,
            published_at=datetime.now(UTC),
            is_current=True,
            manifest_finalized=False,
        )
        session.add(release)
        session.flush()
        objects = [
            paper,
            *compounds,
            *structures,
            lineage,
            evidence,
            activity,
            edge,
            visual_region,
            visual_object,
        ]
        for order, (domain_object, revision) in enumerate(zip(objects, revisions, strict=True)):
            session.add(
                ReleaseItem(
                    release_id=release.id,
                    object_id=domain_object.id,
                    revision_id=revision.id,
                    paper_id=paper.id,
                    object_kind=domain_object.object_kind,
                    manifest_order=order,
                )
            )
        session.flush()
        capture_release_artifact_manifest(session, release.id)
        release.manifest_finalized = True
        session.flush()
        return {
            "release_id": release.id,
            "removed_compound_id": compounds[1].id,
            "edge_id": edge.id,
        }


def test_restored_asset_tree_matches_manifest_without_reporting_storage_paths(
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "restored-assets"
    (asset_root / "objects").mkdir(parents=True)
    content = b"restored bytes"
    restored_file = asset_root / "objects" / "one.bin"
    restored_file.write_bytes(content)
    manifest = {
        "schema_version": 1,
        "asset_root_name": "assets",
        "file_count": 1,
        "total_bytes": len(content),
        "files": [
            {
                "path": "objects/one.bin",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "assets.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_asset_restore(manifest_path, asset_root)

    assert report.ok is True
    assert report.file_count == 1
    assert str(asset_root) not in json.dumps(report.as_dict())


def test_restored_asset_tree_reports_hash_mismatch_without_leaking_paths(
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "restored-assets"
    asset_root.mkdir()
    restored_file = asset_root / "one.bin"
    restored_file.write_bytes(b"tampered")
    manifest = {
        "schema_version": 1,
        "asset_root_name": "assets",
        "file_count": 1,
        "total_bytes": 8,
        "files": [
                {"path": "one.bin", "size_bytes": 8, "sha256": "0" * 64}
        ],
    }
    manifest_path = tmp_path / "assets.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_asset_restore(manifest_path, asset_root)

    assert report.ok is False
    assert report.errors == ("asset_hash_mismatch",)
    assert str(asset_root) not in json.dumps(report.as_dict())


def test_database_restore_counts_are_recomputed_from_the_current_release(
    auth_session_factory: sessionmaker[Session],
    empty_postgresql_database_url: str,
) -> None:
    _seed_current_release(auth_session_factory)

    aggregate = _safe_database_counts(empty_postgresql_database_url)

    assert aggregate["counts"] == EXPECTED_RELEASE_AGGREGATE["counts"]
    assert aggregate["integrity"] == EXPECTED_RELEASE_AGGREGATE["integrity"]


def test_database_restore_counts_detect_a_missing_release_item(
    auth_session_factory: sessionmaker[Session],
    empty_postgresql_database_url: str,
) -> None:
    seeded = _seed_current_release(auth_session_factory)
    with auth_session_factory.begin() as session:
        session.execute(text("ALTER TABLE release_items DISABLE TRIGGER protect_release_item"))
        try:
            session.execute(
                delete(ReleaseItem).where(
                    ReleaseItem.release_id == seeded["release_id"],
                    ReleaseItem.object_id == seeded["removed_compound_id"],
                )
            )
        finally:
            session.execute(text("ALTER TABLE release_items ENABLE TRIGGER protect_release_item"))

    aggregate = _safe_database_counts(empty_postgresql_database_url)

    assert aggregate["counts"]["compound_entities"] == 1  # type: ignore[index]
    assert aggregate["integrity"]["dangling_entity_references"] > 0  # type: ignore[index]


def test_database_restore_integrity_detects_changed_release_relationships(
    auth_session_factory: sessionmaker[Session],
    empty_postgresql_database_url: str,
) -> None:
    seeded = _seed_current_release(auth_session_factory)
    with auth_session_factory.begin() as session:
        edge = session.get(LineageEdge, seeded["edge_id"])
        assert edge is not None
        edge.parent_compound_id = None

    aggregate = _safe_database_counts(empty_postgresql_database_url)

    assert aggregate["integrity"]["invalid_pair_endpoints"] > 0  # type: ignore[index]


def test_database_restore_integrity_counts_unparseable_references(
    auth_session_factory: sessionmaker[Session],
    empty_postgresql_database_url: str,
) -> None:
    _seed_current_release(
        auth_session_factory,
        invalid_activity_evidence=True,
    )

    aggregate = _safe_database_counts(empty_postgresql_database_url)

    assert aggregate["integrity"]["dangling_evidence_references"] == 1  # type: ignore[index]


def test_database_restore_validates_configured_source_assets(
    auth_session_factory: sessionmaker[Session],
    empty_postgresql_database_url: str,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    managed_root = tmp_path / "managed"
    _seed_current_release(auth_session_factory, source_root=source_root)

    without_source_root = _safe_database_counts(
        empty_postgresql_database_url,
        asset_root=managed_root,
    )
    with_source_root = _safe_database_counts(
        empty_postgresql_database_url,
        asset_root=managed_root,
        source_roots={"baseline": source_root},
    )

    assert without_source_root["integrity"]["published_missing_or_corrupt_assets"] == 1  # type: ignore[index]
    assert with_source_root["integrity"]["published_missing_or_corrupt_assets"] == 0  # type: ignore[index]


def test_restored_asset_layout_maps_only_bundled_roots(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    managed_root = bundle_root / "managed"
    source_root = bundle_root / "sources" / "baseline"
    managed_root.mkdir(parents=True)
    source_root.mkdir(parents=True)
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": {
                    "managed_root": "managed",
                    "source_roots": {"baseline": "sources/baseline"},
                },
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )

    managed, sources = restore_verification._restored_asset_layout(  # type: ignore[attr-defined]
        manifest,
        bundle_root,
    )

    assert managed == managed_root
    assert sources == {"baseline": source_root}


def test_restore_report_completion_includes_database_and_http_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    current_time = started_at + timedelta(seconds=5)

    class TestClock:
        @classmethod
        def now(cls, timezone):
            return current_time.astimezone(timezone)

    def recompute_database(*_args, **kwargs):
        nonlocal current_time
        assert kwargs["source_roots"] == {"baseline": tmp_path}
        current_time += timedelta(seconds=7)
        return {"counts": {}, "integrity": {}, "physical_counts": {}}

    def verify_http(*_args, **_kwargs):
        nonlocal current_time
        current_time += timedelta(seconds=3)
        return {"ok": True, "checks": {}}

    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    monkeypatch.setattr(restore_verification, "datetime", TestClock)
    monkeypatch.setattr(
        restore_verification,
        "_safe_database_counts",
        recompute_database,
    )
    monkeypatch.setattr(restore_verification, "_verify_http_workflow", verify_http)

    report = restore_verification.verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=asset_root,
        source_roots={"baseline": tmp_path},
        database_url="postgresql+psycopg://drill",
        expected_aggregate={
            "schema_version": 1,
            "counts": {},
            "integrity_expectations": {},
        },
        base_url="https://drill.local",
        drill_username="reviewer",
        drill_password="password",
        backup_evidence={},
        started_at=started_at,
        rto_target_seconds=60,
    )

    assert report["completed_at"] == "2026-09-13T10:00:15Z"
    assert report["duration_seconds"] == 15


def test_restored_asset_layout_rejects_a_broad_source_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": {
                    "managed_root": "managed",
                    "source_roots": {"baseline": "/"},
                },
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside the restored bundle"):
        restore_verification._restored_asset_layout(  # type: ignore[attr-defined]
            manifest,
            bundle_root,
        )


def test_restore_report_requires_complete_scientific_baseline_and_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    content = b"verified asset"
    (asset_root / "one.bin").write_bytes(content)
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "asset_root_name": "assets",
                "file_count": 1,
                "total_bytes": len(content),
                "files": [
                    {
                        "path": "one.bin",
                        "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    expected = {
        "schema_version": 1,
        "counts": {"corpus_papers": 672, "lineages": 193},
        "integrity_expectations": {"self_loops": 0, "invalid_pair_endpoints": 0},
    }
    monkeypatch.setattr(
        "leadtrace.ops.restore.verify_restored_system._safe_database_counts",
        lambda _, **__: {
            "counts": expected["counts"],
            "integrity": expected["integrity_expectations"],
            "physical_counts": {"papers": 672, "releases": 1, "audit_events": 10},
        },
    )
    monkeypatch.setattr(
        "leadtrace.ops.restore.verify_restored_system._verify_http_workflow",
        lambda *args, **kwargs: {"ok": True, "checks": {"login": True}},
    )
    completed_at = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    started_at = completed_at - timedelta(minutes=4)
    backup_evidence = {
        "database": {
            "backup_id": "database-1",
            "metadata_sha256": "a" * 64,
            "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
        },
        "assets": {
            "backup_id": "assets-2",
            "metadata_sha256": "b" * 64,
            "chain_backup_ids": ["assets-1", "assets-2"],
            "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
        },
    }

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=asset_root,
        database_url="postgresql://restore.invalid/drill",
        expected_aggregate=expected,
        base_url="https://restore-drill.lan",
        drill_username="drill",
        drill_password="protected",
        backup_evidence=backup_evidence,
        started_at=started_at,
        completed_at=completed_at,
        rto_target_seconds=300,
    )

    assert report["ok"] is True
    assert report["baseline"] == {
        "ok": True,
        "counts": expected["counts"],
        "integrity": expected["integrity_expectations"],
        "physical_counts": {"papers": 672, "releases": 1, "audit_events": 10},
    }
    assert report["backup_evidence"] == backup_evidence
    assert report["started_at"] == "2026-09-12T11:56:00Z"
    assert report["completed_at"] == "2026-09-12T12:00:00Z"
    assert report["duration_seconds"] == 240
    assert report["rto"] == {"target_seconds": 300, "met": True}


def test_restore_report_fails_when_any_integrity_expectation_differs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "asset_root_name": "assets",
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    expected = {
        "schema_version": 1,
        "counts": {"corpus_papers": 672},
        "integrity_expectations": {"self_loops": 0},
    }
    monkeypatch.setattr(
        "leadtrace.ops.restore.verify_restored_system._safe_database_counts",
        lambda _, **__: {
            "counts": expected["counts"],
            "integrity": {"self_loops": 1},
            "physical_counts": {"papers": 672, "releases": 1, "audit_events": 1},
        },
    )
    monkeypatch.setattr(
        "leadtrace.ops.restore.verify_restored_system._verify_http_workflow",
        lambda *args, **kwargs: {"ok": True},
    )

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=asset_root,
        database_url="postgresql://restore.invalid/drill",
        expected_aggregate=expected,
        base_url="https://restore-drill.lan",
        drill_username="drill",
        drill_password="protected",
        backup_evidence={"database": {}, "assets": {}},
        started_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 9, 12, 12, 1, tzinfo=UTC),
        rto_target_seconds=300,
    )

    assert report["ok"] is False
    assert "database_baseline_mismatch" in report["errors"]


def test_restore_report_can_verify_the_backup_metadata_before_extracting(
    tmp_path: Path,
) -> None:
    artifacts = {
        "assets.manifest.json": b'{"files": []}\n',
        "assets.tar.age": b"encrypted archive",
        "tar.snapshot": b"snapshot state",
    }
    for name, content in artifacts.items():
        (tmp_path / name).write_bytes(content)
    metadata = {
        "schema_version": 1,
        "backup_id": "assets-1",
        "backup_scope": "assets",
        "started_at": "2026-09-12T10:00:00Z",
        "completed_at": "2026-09-12T10:01:00Z",
        "outcome": "success",
        "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:key",
            "payloads_encrypted": True,
        },
        "destination": {"kind": "separate_disk", "identity": "disk-a"},
        "artifacts": {
            (
                "asset_manifest"
                if name.endswith(".manifest.json")
                else "asset_snapshot"
                if name.endswith(".snapshot")
                else "asset_archive"
            ): {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for name, content in artifacts.items()
        },
        "asset_chain": {
            "mode": "full",
            "parent_backup_id": None,
            "position": 0,
        },
    }
    metadata_path = tmp_path / "backup-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    report = verify_backup(metadata_path)

    assert report.ok is True
    assert report.backup_scope == "assets"


def test_restore_evidence_is_derived_from_verified_backup_metadata(
    tmp_path: Path,
) -> None:
    def write_backup(backup_id: str, scope: str) -> Path:
        root = tmp_path / backup_id
        root.mkdir()
        names = {
            "database": {"database_dump": "database.dump.age"},
            "assets": {
                "asset_manifest": "assets.manifest.json",
                "asset_archive": "assets.tar.age",
                "asset_snapshot": "tar.snapshot",
            },
        }[scope]
        artifacts: dict[str, dict[str, object]] = {}
        for artifact_name, filename in names.items():
            content = f"{backup_id}:{artifact_name}".encode()
            (root / filename).write_bytes(content)
            artifacts[artifact_name] = {
                "path": filename,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        metadata = {
            "schema_version": 1,
            "backup_id": backup_id,
            "backup_scope": scope,
            "started_at": "2026-09-12T10:00:00Z",
            "completed_at": "2026-09-12T10:01:00Z",
            "outcome": "success",
            "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
            "encryption": {
                "algorithm": "age-x25519",
                "recipient_fingerprint": "SHA256:key",
                "payloads_encrypted": True,
            },
            "destination": {"kind": "separate_disk", "identity": "disk-a"},
            "artifacts": artifacts,
        }
        if scope == "assets":
            metadata["asset_chain"] = {
                "mode": "full",
                "parent_backup_id": None,
                "position": 0,
            }
        metadata_path = root / "backup-metadata.json"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata_path

    database_metadata = write_backup("database-1", "database")
    asset_metadata = write_backup("assets-1", "assets")
    module = importlib.import_module("leadtrace.ops.restore.verify_restored_system")
    build_backup_evidence = getattr(module, "build_backup_evidence")

    evidence = build_backup_evidence(database_metadata, asset_metadata)

    assert evidence["database"]["backup_id"] == "database-1"
    assert evidence["assets"]["backup_id"] == "assets-1"
    assert evidence["assets"]["chain_backup_ids"] == ["assets-1"]
    assert str(tmp_path) not in json.dumps(evidence)


def test_restore_drill_refuses_to_use_an_existing_restore_root(tmp_path: Path) -> None:
    restore_root = tmp_path / "already-used"
    restore_root.mkdir()
    (restore_root / "keep.txt").write_text("keep", encoding="utf-8")
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    environment = {
        **os.environ,
        "LEADTRACE_RESTORE_ROOT": str(restore_root),
        "LEADTRACE_DATABASE_METADATA": str(tmp_path / "db.json"),
        "LEADTRACE_ASSET_METADATA": str(tmp_path / "assets.json"),
        "LEADTRACE_RESTORE_DATABASE_URL": "postgresql://example.invalid/restore",
        "LEADTRACE_PRODUCTION_DATABASE_URL": "postgresql://example.invalid/production",
        "LEADTRACE_RESTORE_DATABASE_ALLOWLIST": "restore",
        "LEADTRACE_AGE_IDENTITY_FILE": str(tmp_path / "identity.txt"),
        "LEADTRACE_DRILL_BASE_URL": "https://leadtrace.invalid",
        "LEADTRACE_DRILL_USERNAME": "drill",
        "LEADTRACE_DRILL_PASSWORD": "not-used",
        "LEADTRACE_EXPECTED_AGGREGATE": str(tmp_path / "expected.json"),
        "LEADTRACE_RESTORE_RTO_SECONDS": "3600",
    }

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "restore root" in (result.stderr + result.stdout).casefold()
    assert (restore_root / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_drill_rejects_the_production_database_before_restore(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    restore_root = tmp_path / "restore"
    marker = tmp_path / "pg-restore-was-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\n"
        "while (($#)); do case \"$1\" in --output) out=$2; shift 2;; *) shift;; esac; done\n"
        "printf 'decrypted' > \"$out\"\n",
        encoding="utf-8",
    )
    (fake_bin / "pg_restore").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\ntouch {marker!s}\n",
        encoding="utf-8",
    )
    (fake_bin / "tar").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n",
        encoding="utf-8",
    )
    for command in ("age", "pg_restore", "tar"):
        (fake_bin / command).chmod(0o755)

    database_url = "postgresql://database.internal/leadtrace_production"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_RESTORE_ROOT": str(restore_root),
        "LEADTRACE_DATABASE_METADATA": str(tmp_path / "db.json"),
        "LEADTRACE_ASSET_METADATA": str(tmp_path / "assets.json"),
        "LEADTRACE_RESTORE_DATABASE_URL": database_url,
        "LEADTRACE_PRODUCTION_DATABASE_URL": database_url,
        "LEADTRACE_RESTORE_DATABASE_ALLOWLIST": "leadtrace_restore_drill_20260912",
        "LEADTRACE_AGE_IDENTITY_FILE": str(tmp_path / "identity.txt"),
        "LEADTRACE_DRILL_BASE_URL": "https://leadtrace.invalid",
        "LEADTRACE_DRILL_USERNAME": "drill",
        "LEADTRACE_DRILL_PASSWORD": "not-used",
        "LEADTRACE_EXPECTED_AGGREGATE": str(tmp_path / "expected.json"),
        "LEADTRACE_RESTORE_RTO_SECONDS": "3600",
    }

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "production database" in (result.stderr + result.stdout).casefold()
    assert not marker.exists()


def test_restore_drill_uses_atomic_fail_fast_pg_restore() -> None:
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "--single-transaction" in script
    assert "--exit-on-error" in script


def test_restore_drill_protects_plaintext_and_replays_the_verified_asset_chain() -> None:
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "umask 077" in script
    assert "trap cleanup_restore_plaintext EXIT" in script
    assert "asset_chain.py" in script
    assert "--listed-incremental=/dev/null" in script
    assert "require_value LEADTRACE_EXPECTED_AGGREGATE" in script
    assert "require_value LEADTRACE_RESTORE_RTO_SECONDS" in script


def test_restore_target_validator_rejects_a_database_with_user_relations(
    tmp_path: Path,
) -> None:
    helper_path = (
        Path(__file__).parents[3]
        / "ops"
        / "restore"
        / "validate_restore_target.py"
    )
    fake_module = tmp_path / "fake-python"
    fake_module.mkdir()
    (fake_module / "psycopg.py").write_text(
        "class Cursor:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *args): return None\n"
        "    def execute(self, query): self.query = query\n"
        "    def fetchone(self):\n"
        "        return ('leadtrace_restore_drill_20260912',) if 'current_database' in self.query else (1,)\n"
        "class Connection:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *args): return None\n"
        "    def cursor(self): return Cursor()\n"
        "def connect(*args, **kwargs): return Connection()\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(fake_module),
        "LEADTRACE_RESTORE_DATABASE_URL": (
            "postgresql://database.internal/leadtrace_restore_drill_20260912"
        ),
        "LEADTRACE_PRODUCTION_DATABASE_URL": (
            "postgresql://database.internal/leadtrace_production"
        ),
        "LEADTRACE_RESTORE_DATABASE_ALLOWLIST": "leadtrace_restore_drill_20260912",
    }

    result = subprocess.run(
        [os.environ.get("PYTHON", "python"), str(helper_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not empty" in (result.stderr + result.stdout).casefold()


def test_restore_http_workflow_reads_paper_pdf_release_and_audit(monkeypatch) -> None:
    requested: list[tuple[str, str]] = []

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def post(self, path: str, **_: object) -> Response:
            requested.append(("POST", path))
            return Response(200, {"csrf_token": "drill-csrf"})

        def get(self, path: str, **_: object) -> Response:
            requested.append(("GET", path))
            if path == "/api/v1/papers?page=1&page_size=1":
                return Response(200, {"items": [{"id": "paper-1"}]})
            return Response(206 if path.endswith("/source-pdf") else 200, {})

    import httpx

    monkeypatch.setattr(httpx, "Client", Client)

    report = _verify_http_workflow(
        "https://restore-drill.lan",
        username="drill",
        password="protected-password",
    )

    assert report["ok"] is True
    assert requested == [
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/papers?page=1&page_size=1"),
        ("GET", "/api/v1/papers/paper-1"),
        ("GET", "/api/v1/papers/paper-1/source-pdf"),
        ("GET", "/api/v1/published/overview"),
        ("GET", "/api/v1/audit/events?limit=1"),
    ]
