from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.users.models import UserRole
from app.users.service import UserService
import leadtrace.ops.restore.verify_restored_system as restore_verification
from leadtrace.ops.restore.verify_restored_system import (
    _safe_database_counts,
    _verify_http_workflow,
    verify_asset_restore,
    verify_restored_system,
)


COUNT_KEYS = {
    "papers",
    "paper_sources",
    "review_tasks",
    "paper_workspaces",
    "paper_section_reviews",
    "change_events",
    "paper_submissions",
    "admin_decisions",
    "published_paper_versions",
    "current_published_papers",
    "ai_extraction_runs",
    "compounds",
    "structures",
    "structure_source_images",
    "lineages",
    "lineage_members",
    "lineage_edges",
    "evidence",
    "edge_evidence_links",
    "activities",
    "assets",
    "crop_jobs",
    "crop_job_attempts",
    "crop_job_retry_operations",
    "maintenance_windows",
    "users",
    "admin_users",
}

ZERO_INTEGRITY = {
    "paper_source_asset_mismatches": 0,
    "current_publication_pointer_mismatches": 0,
    "publication_hash_mismatches": 0,
    "snapshot_hash_mismatches": 0,
    "missing_or_corrupt_assets": 0,
    "audit_chain_invalid": 0,
}


def _write_empty_manifest(root: Path) -> Path:
    (root / "managed").mkdir(parents=True)
    (root / "sources" / "source_pdfs").mkdir(parents=True)
    manifest = root.parent / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "asset_root_name": "asset-snapshot",
                "layout": {
                    "managed_root": "managed",
                    "source_roots": {"source_pdfs": "sources/source_pdfs"},
                },
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _paper_centric_expected_aggregate() -> dict[str, object]:
    return {
        "schema_version": 2,
        "counts": {key: 0 for key in COUNT_KEYS},
        "integrity_expectations": ZERO_INTEGRITY,
    }


def _write_backup_metadata(root: Path, backup_id: str, scope: str) -> Path:
    backup_root = root / backup_id
    backup_root.mkdir()
    filenames = {
        "database": {"database_dump": "database.dump.age"},
        "assets": {
            "asset_manifest": "assets.manifest.json",
            "asset_archive": "assets.tar.age",
            "asset_snapshot": "tar.snapshot",
        },
    }[scope]
    artifacts: dict[str, dict[str, object]] = {}
    for artifact_name, filename in filenames.items():
        content = f"{backup_id}:{artifact_name}".encode()
        (backup_root / filename).write_bytes(content)
        artifacts[artifact_name] = {
            "path": filename,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    metadata: dict[str, object] = {
        "schema_version": 1,
        "backup_id": backup_id,
        "backup_scope": scope,
        "started_at": "2026-09-17T10:00:00Z",
        "completed_at": "2026-09-17T10:01:00Z",
        "outcome": "success",
        "versions": {
            "application": "0.1.0",
            "schema": "0025_ai_prefill_runs",
            "release": "paper-centric",
        },
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:test-key",
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
    metadata_path = backup_root / "backup-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path


def test_asset_restore_checks_hash_and_size_without_leaking_paths(tmp_path: Path) -> None:
    restored = tmp_path / "restored"
    restored.mkdir()
    content = b"restored asset"
    (restored / "asset.bin").write_bytes(content)
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "file_count": 1,
                "total_bytes": len(content),
                "files": [
                    {
                        "path": "asset.bin",
                        "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    valid = verify_asset_restore(manifest, restored)
    (restored / "asset.bin").write_bytes(b"tampered asset")
    invalid = verify_asset_restore(manifest, restored)

    assert valid.ok is True
    assert invalid.ok is False
    assert invalid.errors == ("asset_hash_mismatch",)
    assert str(tmp_path) not in json.dumps(invalid.as_dict())


def test_restored_asset_layout_rejects_manifest_path_escape(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    (bundle_root / "sources" / "source_pdfs").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    manifest = tmp_path / "assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": {
                    "managed_root": "../outside",
                    "source_roots": {"source_pdfs": "sources/source_pdfs"},
                },
                "file_count": 0,
                "total_bytes": 0,
                "files": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside the restored bundle"):
        restore_verification._restored_asset_layout(manifest, bundle_root)


def test_backup_evidence_contains_verified_hashes_without_storage_paths(
    tmp_path: Path,
) -> None:
    database_metadata = _write_backup_metadata(
        tmp_path,
        "database-paper-centric",
        "database",
    )
    asset_metadata = _write_backup_metadata(
        tmp_path,
        "assets-paper-centric",
        "assets",
    )

    evidence = restore_verification.build_backup_evidence(
        database_metadata,
        asset_metadata,
    )

    assert evidence["database"]["metadata_sha256"] == hashlib.sha256(
        database_metadata.read_bytes()
    ).hexdigest()
    assert evidence["assets"]["metadata_sha256"] == hashlib.sha256(
        asset_metadata.read_bytes()
    ).hexdigest()
    assert evidence["assets"]["chain_backup_ids"] == ["assets-paper-centric"]
    assert str(tmp_path) not in json.dumps(evidence)


def test_safe_database_counts_uses_paper_centric_schema(
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del auth_session_factory

    aggregate = _safe_database_counts(empty_postgresql_database_url)

    assert aggregate["schema_version"] == 2
    assert set(aggregate["counts"]) == COUNT_KEYS
    assert set(aggregate["counts"].values()) == {0}
    assert aggregate["integrity"] == ZERO_INTEGRITY


def test_safe_database_counts_excludes_only_the_temporary_reviewer(
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="restore-admin",
            display_name="Restore Admin",
            role=UserRole.ADMIN,
            initial_password="Restore test admin password 2026!",
        )
        UserService().create_user(
            session,
            username="restore-drill",
            display_name="Restore Drill Reviewer",
            role=UserRole.REVIEWER,
            initial_password="Restore test reviewer password 2026!",
        )

    aggregate = _safe_database_counts(
        empty_postgresql_database_url,
        excluded_username="restore-drill",
    )

    assert aggregate["counts"]["users"] == 1
    assert aggregate["counts"]["admin_users"] == 1


def test_safe_database_counts_rejects_an_admin_drill_account(
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="restore-drill",
            display_name="Incorrect Restore Drill Admin",
            role=UserRole.ADMIN,
            initial_password="Restore test admin password 2026!",
        )

    with pytest.raises(ValueError, match="Reviewer"):
        _safe_database_counts(
            empty_postgresql_database_url,
            excluded_username="restore-drill",
        )


def test_safe_database_counts_rejects_a_missing_drill_account(
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del auth_session_factory

    with pytest.raises(ValueError, match="Reviewer"):
        _safe_database_counts(
            empty_postgresql_database_url,
            excluded_username="restore-drill",
        )


def test_restore_system_reports_an_invalid_admin_drill_account(
    tmp_path: Path,
    monkeypatch,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="restore-drill",
            display_name="Incorrect Restore Drill Admin",
            role=UserRole.ADMIN,
            initial_password="Restore test admin password 2026!",
        )
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    monkeypatch.setattr(
        restore_verification,
        "_verify_http_workflow",
        lambda *_args, **_kwargs: {"ok": True, "checks": {}},
    )

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=restored,
        database_url=empty_postgresql_database_url,
        expected_aggregate=_paper_centric_expected_aggregate(),
        base_url="https://restore.invalid",
        drill_username="restore-drill",
        drill_password="protected",
        backup_evidence={},
        started_at=datetime(2026, 9, 17, tzinfo=UTC),
        completed_at=datetime(2026, 9, 17, 0, 1, tzinfo=UTC),
        rto_target_seconds=3600,
    )

    assert report["ok"] is False
    assert report["baseline"] == {
        "ok": False,
        "error": "drill_account_invalid",
    }
    assert report["errors"] == ["drill_account_invalid"]


def test_safe_database_counts_validates_paper_source_and_restored_bytes(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    managed_root = tmp_path / "managed"
    source_root = tmp_path / "source_pdfs"
    managed_root.mkdir()
    source_root.mkdir()
    content = b"%PDF-1.4\n/Type /Page\n%%EOF\n"
    source_file = source_root / "paper.pdf"
    source_file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    with auth_session_factory.begin() as session:
        asset = Asset(
            storage_key="source/source_pdfs/paper.pdf",
            original_filename="paper.pdf",
            sha256=digest,
            byte_size=len(content),
            mime_type="application/pdf",
            page_count=1,
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={"source_root_key": "source_pdfs"},
        )
        session.add(asset)
        session.flush()
        source = PaperSource(
            asset_id=asset.id,
            source_root_key="source_pdfs",
            source_key="paper.pdf",
            sha256=digest,
            byte_size=len(content),
            page_count=1,
            integrity_state=PaperSourceIntegrityState.VERIFIED,
        )
        session.add(source)
        session.flush()
        session.add(
            Paper(
                paper_key="restore-paper",
                source_id=source.id,
                title="Restore verification paper",
                journal="Journal of Medicinal Chemistry",
                publication_year=2026,
                volume="69",
                issue="1",
                doi=None,
                catalog_state=PaperCatalogState.VERIFIED,
            )
        )

    aggregate = _safe_database_counts(
        empty_postgresql_database_url,
        asset_root=managed_root,
        source_roots={"source_pdfs": source_root},
    )
    source_file.write_bytes(b"tampered")
    tampered = _safe_database_counts(
        empty_postgresql_database_url,
        asset_root=managed_root,
        source_roots={"source_pdfs": source_root},
    )

    assert aggregate["counts"]["papers"] == 1
    assert aggregate["counts"]["paper_sources"] == 1
    assert aggregate["counts"]["assets"] == 1
    assert aggregate["integrity"] == ZERO_INTEGRITY
    assert tampered["integrity"]["missing_or_corrupt_assets"] == 1


def test_current_publication_pointer_must_select_latest_version() -> None:
    pointer_mismatches = getattr(
        restore_verification,
        "_current_publication_pointer_mismatches",
        None,
    )
    assert pointer_mismatches is not None
    paper_id = "paper-1"
    version_one = SimpleNamespace(id="version-1", paper_id=paper_id, version_number=1)
    version_two = SimpleNamespace(id="version-2", paper_id=paper_id, version_number=2)

    stale = pointer_mismatches(
        [SimpleNamespace(id=paper_id, current_published_version_id="version-1")],
        [version_one, version_two],
    )
    current = pointer_mismatches(
        [SimpleNamespace(id=paper_id, current_published_version_id="version-2")],
        [version_one, version_two],
    )
    missing = pointer_mismatches(
        [SimpleNamespace(id=paper_id, current_published_version_id=None)],
        [version_one, version_two],
    )

    assert stale == 1
    assert current == 0
    assert missing == 1


def test_restore_system_accepts_paper_centric_expected_aggregate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    counts = {key: 0 for key in COUNT_KEYS}
    aggregate = {
        "schema_version": 2,
        "counts": counts,
        "integrity": ZERO_INTEGRITY,
    }
    monkeypatch.setattr(
        restore_verification,
        "_safe_database_counts",
        lambda *_args, **_kwargs: aggregate,
    )
    monkeypatch.setattr(
        restore_verification,
        "_verify_http_workflow",
        lambda *_args, **_kwargs: {"ok": True, "checks": {}},
    )

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=restored,
        database_url="postgresql+psycopg://restore.invalid/leadtrace_restore_test",
        expected_aggregate={
            "schema_version": 2,
            "counts": counts,
            "integrity_expectations": ZERO_INTEGRITY,
        },
        base_url="https://restore.invalid",
        drill_username="drill",
        drill_password="protected",
        backup_evidence={},
        started_at=datetime(2026, 9, 17, tzinfo=UTC),
        completed_at=datetime(2026, 9, 17, 0, 1, tzinfo=UTC),
        rto_target_seconds=3600,
    )

    assert report["ok"] is True
    assert report["schema_version"] == 2
    assert report["baseline"]["ok"] is True


def test_restore_system_rejects_nonzero_integrity_expectations(
    tmp_path: Path,
) -> None:
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    nonzero_integrity = {**ZERO_INTEGRITY, "audit_chain_invalid": 1}

    with pytest.raises(
        ValueError,
        match="paper-centric expected aggregate",
    ):
        verify_restored_system(
            asset_manifest=manifest,
            restored_asset_root=restored,
            database_url=None,
            expected_aggregate={
                "schema_version": 2,
                "counts": {
                    key: 0
                    for key in restore_verification.PAPER_CENTRIC_COUNT_KEYS
                },
                "integrity_expectations": nonzero_integrity,
            },
            base_url=None,
            backup_evidence={},
            started_at=datetime(2026, 9, 17, tzinfo=UTC),
            completed_at=datetime(2026, 9, 17, 0, 1, tzinfo=UTC),
            rto_target_seconds=3600,
        )


def test_restore_system_reports_aggregate_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    actual_counts = {key: 0 for key in COUNT_KEYS}
    actual_counts["papers"] = 1
    monkeypatch.setattr(
        restore_verification,
        "_safe_database_counts",
        lambda *_args, **_kwargs: {
            "schema_version": 2,
            "counts": actual_counts,
            "integrity": ZERO_INTEGRITY,
        },
    )
    monkeypatch.setattr(
        restore_verification,
        "_verify_http_workflow",
        lambda *_args, **_kwargs: {"ok": True, "checks": {}},
    )

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=restored,
        database_url="postgresql+psycopg://restore.invalid/leadtrace_restore_test",
        expected_aggregate=_paper_centric_expected_aggregate(),
        base_url="https://restore.invalid",
        drill_username="drill",
        drill_password="protected",
        backup_evidence={},
        started_at=datetime(2026, 9, 17, tzinfo=UTC),
        completed_at=datetime(2026, 9, 17, 0, 1, tzinfo=UTC),
        rto_target_seconds=3600,
    )

    assert report["ok"] is False
    assert report["baseline"]["ok"] is False
    assert report["errors"] == ["database_baseline_mismatch"]


def test_restore_system_reports_nonzero_actual_integrity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    monkeypatch.setattr(
        restore_verification,
        "_safe_database_counts",
        lambda *_args, **_kwargs: {
            "schema_version": 2,
            "counts": {key: 0 for key in COUNT_KEYS},
            "integrity": {**ZERO_INTEGRITY, "audit_chain_invalid": 1},
        },
    )
    monkeypatch.setattr(
        restore_verification,
        "_verify_http_workflow",
        lambda *_args, **_kwargs: {"ok": True, "checks": {}},
    )

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=restored,
        database_url="postgresql+psycopg://restore.invalid/leadtrace_restore_test",
        expected_aggregate=_paper_centric_expected_aggregate(),
        base_url="https://restore.invalid",
        drill_username="drill",
        drill_password="protected",
        backup_evidence={},
        started_at=datetime(2026, 9, 17, tzinfo=UTC),
        completed_at=datetime(2026, 9, 17, 0, 1, tzinfo=UTC),
        rto_target_seconds=3600,
    )

    assert report["ok"] is False
    assert report["baseline"]["integrity_ok"] is False
    assert report["errors"] == [
        "database_baseline_mismatch",
        "database_integrity_failed",
    ]


def test_restore_system_reports_rto_target_exceeded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    restored = tmp_path / "restored"
    manifest = _write_empty_manifest(restored)
    monkeypatch.setattr(
        restore_verification,
        "_safe_database_counts",
        lambda *_args, **_kwargs: {
            "schema_version": 2,
            "counts": {key: 0 for key in COUNT_KEYS},
            "integrity": ZERO_INTEGRITY,
        },
    )
    monkeypatch.setattr(
        restore_verification,
        "_verify_http_workflow",
        lambda *_args, **_kwargs: {"ok": True, "checks": {}},
    )
    started_at = datetime(2026, 9, 17, tzinfo=UTC)

    report = verify_restored_system(
        asset_manifest=manifest,
        restored_asset_root=restored,
        database_url="postgresql+psycopg://restore.invalid/leadtrace_restore_test",
        expected_aggregate=_paper_centric_expected_aggregate(),
        base_url="https://restore.invalid",
        drill_username="drill",
        drill_password="protected",
        backup_evidence={},
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=61),
        rto_target_seconds=60,
    )

    assert report["ok"] is False
    assert report["duration_seconds"] == 61
    assert report["rto"] == {"target_seconds": 60, "met": False}
    assert report["errors"] == ["rto_target_exceeded"]


def test_restore_http_workflow_reads_v2_paper_pdf_and_audit(monkeypatch) -> None:
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
            if path == "/api/v2/papers":
                return Response(200, {"items": [{"paper_id": "paper-1"}]})
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
        ("GET", "/api/v2/papers"),
        ("GET", "/api/v2/papers/paper-1"),
        ("GET", "/api/v2/papers/paper-1/source-pdf"),
        ("GET", "/api/v1/audit/events?limit=1"),
    ]


def test_restore_drill_refuses_existing_root_and_protects_plaintext(
    tmp_path: Path,
) -> None:
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
    script = script_path.read_text(encoding="utf-8")

    assert result.returncode != 0
    assert "restore root" in (result.stderr + result.stdout).casefold()
    assert (restore_root / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert "umask 077" in script
    assert "trap cleanup_restore_plaintext EXIT" in script
    assert "--single-transaction" in script
    assert "--exit-on-error" in script
    assert "asset_chain.py" in script
    assert "--listed-incremental=/dev/null" in script


def test_restore_drill_converts_sqlalchemy_url_for_pg_restore() -> None:
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    script = script_path.read_text(encoding="utf-8")

    assert (
        'PG_RESTORE_DATABASE_URL="${LEADTRACE_RESTORE_DATABASE_URL/'
        'postgresql+psycopg:/postgresql:}"'
    ) in script
    assert '--dbname="${PG_RESTORE_DATABASE_URL}"' in script


def test_restore_drill_rejects_production_database_before_pg_restore(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    restore_root = tmp_path / "restore"
    marker = tmp_path / "pg-restore-was-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "pg_restore").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\ntouch {marker!s}\n",
        encoding="utf-8",
    )
    (fake_bin / "pg_restore").chmod(0o755)
    database_url = "postgresql://database.internal/leadtrace_production"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_RESTORE_ROOT": str(restore_root),
        "LEADTRACE_DATABASE_METADATA": str(tmp_path / "db.json"),
        "LEADTRACE_ASSET_METADATA": str(tmp_path / "assets.json"),
        "LEADTRACE_RESTORE_DATABASE_URL": database_url,
        "LEADTRACE_PRODUCTION_DATABASE_URL": database_url,
        "LEADTRACE_RESTORE_DATABASE_ALLOWLIST": "leadtrace_restore_drill_20260917",
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


def test_restore_target_validator_rejects_nonempty_database(tmp_path: Path) -> None:
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
        "        return ('leadtrace_restore_drill_20260917',) "
        "if 'current_database' in self.query else (1,)\n"
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
            "postgresql://database.internal/leadtrace_restore_drill_20260917"
        ),
        "LEADTRACE_PRODUCTION_DATABASE_URL": (
            "postgresql://database.internal/leadtrace_production"
        ),
        "LEADTRACE_RESTORE_DATABASE_ALLOWLIST": "leadtrace_restore_drill_20260917",
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
