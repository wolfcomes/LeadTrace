from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from leadtrace.ops.backup.verify_backup import verify_backup
from leadtrace.ops.restore.verify_restored_system import (
    _verify_http_workflow,
    verify_asset_restore,
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


def test_restore_report_can_verify_the_backup_metadata_before_extracting(
    tmp_path: Path,
) -> None:
    artifacts = {
        "assets.manifest.json": b'{"files": []}\n',
        "assets.tar.age": b"encrypted archive",
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
            ("asset_manifest" if name.endswith(".manifest.json") else "asset_archive"): {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for name, content in artifacts.items()
        },
    }
    metadata_path = tmp_path / "backup-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    report = verify_backup(metadata_path)

    assert report.ok is True
    assert report.backup_scope == "assets"


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
        "LEADTRACE_AGE_IDENTITY_FILE": str(tmp_path / "identity.txt"),
        "LEADTRACE_DRILL_BASE_URL": "https://leadtrace.invalid",
        "LEADTRACE_DRILL_USERNAME": "drill",
        "LEADTRACE_DRILL_PASSWORD": "not-used",
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
