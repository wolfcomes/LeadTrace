from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess

from leadtrace.ops.backup.verify_backup import verify_backup
from leadtrace.ops.restore.verify_restored_system import (
    _verify_http_workflow,
    verify_asset_restore,
    verify_restored_system,
)


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
        lambda _: {
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
        lambda _: {
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
