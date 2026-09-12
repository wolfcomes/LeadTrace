from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from leadtrace.ops.backup.verify_backup import verify_backup


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_complete_backup(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    artifacts = {
        "database.dump.age": b"encrypted database dump",
        "assets.manifest.json": b'{"files": []}\n',
        "assets.tar.age": b"encrypted asset archive",
    }
    for relative_path, content in artifacts.items():
        (tmp_path / relative_path).write_bytes(content)

    metadata = {
        "schema_version": 1,
        "backup_id": "20260912T100000Z-release-17",
        "started_at": "2026-09-12T10:00:00Z",
        "completed_at": "2026-09-12T10:03:00Z",
        "outcome": "success",
        "versions": {
            "application": "0.1.0",
            "schema": "0015_crop_job_subscriptions",
            "release": "release-17",
        },
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:backup-key-2026-09",
            "payloads_encrypted": True,
        },
        "destination": {
            "kind": "separate_disk",
            "identity": "leadtrace-backup-disk-a",
        },
        "artifacts": {
            "database_dump": {
                "path": "database.dump.age",
                "sha256": _sha256(artifacts["database.dump.age"]),
                "size_bytes": len(artifacts["database.dump.age"]),
            },
            "asset_manifest": {
                "path": "assets.manifest.json",
                "sha256": _sha256(artifacts["assets.manifest.json"]),
                "size_bytes": len(artifacts["assets.manifest.json"]),
            },
            "asset_archive": {
                "path": "assets.tar.age",
                "sha256": _sha256(artifacts["assets.tar.age"]),
                "size_bytes": len(artifacts["assets.tar.age"]),
            },
        },
    }
    metadata_path = tmp_path / "backup-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path, metadata


def test_complete_encrypted_backup_metadata_verifies_artifacts(tmp_path: Path) -> None:
    metadata_path, _ = _write_complete_backup(tmp_path)

    report = verify_backup(metadata_path)

    assert report.ok is True
    assert report.backup_id == "20260912T100000Z-release-17"
    assert report.verified_artifacts == (
        "asset_archive",
        "asset_manifest",
        "database_dump",
    )


def test_backup_metadata_rejects_an_unsuccessful_outcome(tmp_path: Path) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    metadata["outcome"] = "failed"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="successful finalized backup"):
        verify_backup(metadata_path)


@pytest.mark.parametrize(
    ("encryption", "message"),
    [
        ({"algorithm": "none", "recipient_fingerprint": "key", "payloads_encrypted": False}, "encrypted"),
        ({"algorithm": "age-x25519", "recipient_fingerprint": "", "payloads_encrypted": True}, "fingerprint"),
    ],
)
def test_backup_metadata_requires_encrypted_payloads_and_key_identity(
    tmp_path: Path,
    encryption: dict[str, object],
    message: str,
) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    metadata["encryption"] = encryption
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_backup(metadata_path)


def test_backup_metadata_rejects_embedded_secrets_without_echoing_them(
    tmp_path: Path,
) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    marker = "do-not-leak-this-database-password"
    metadata["runtime"] = {"database_password": marker}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="sensitive field") as error:
        verify_backup(metadata_path)

    assert marker not in str(error.value)


def test_backup_metadata_rejects_artifact_path_escape(tmp_path: Path) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    metadata["artifacts"]["database_dump"]["path"] = "../outside.dump"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="within backup directory"):
        verify_backup(metadata_path)


@pytest.mark.parametrize(
    "field_path",
    [
        ("backup_id",),
        ("versions", "application"),
        ("versions", "schema"),
        ("versions", "release"),
        ("destination", "identity"),
        ("started_at",),
        ("completed_at",),
    ],
)
def test_backup_metadata_requires_operational_identity_fields(
    tmp_path: Path,
    field_path: tuple[str, ...],
) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    target: dict[str, object] = metadata
    for key in field_path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target.pop(field_path[-1])
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="required"):
        verify_backup(metadata_path)


@pytest.mark.parametrize(
    ("script", "destination"),
    [
        ("backup_postgres.sh", "relative/backups"),
        ("backup_assets.sh", "/"),
    ],
)
def test_backup_scripts_reject_unresolved_or_broad_destinations(
    script: str,
    destination: str,
) -> None:
    script_path = Path(__file__).parents[3] / "ops" / "backup" / script
    environment = {
        **os.environ,
        "LEADTRACE_BACKUP_DESTINATION": destination,
        "LEADTRACE_DATABASE_URL": "postgresql://example.invalid/leadtrace",
        "LEADTRACE_ASSET_ROOT": "/var/lib/leadtrace/assets",
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
    }
    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "destination" in (result.stderr + result.stdout).casefold()


def test_postgres_backup_finalizes_an_encrypted_verified_set(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "pg_dump").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\nfor arg in \"$@\"; do case \"$arg\" in --file=*) out=\"${arg#--file=}\";; esac; done\nprintf 'database bytes' > \"$out\"\n",
        encoding="utf-8",
    )
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\ninput=''\nwhile (($#)); do case \"$1\" in -o) out=$2; shift 2;; -r) shift 2;; *) input=$1; shift;; esac; done\ncp -- \"$input\" \"$out\"\n",
        encoding="utf-8",
    )
    for command in ("pg_dump", "age"):
        (fake_bin / command).chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_DATABASE_URL": "postgresql://example.invalid/leadtrace",
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "test-db-backup",
    }
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_postgres.sh"

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    final_directory = destination / "test-db-backup"
    report = verify_backup(final_directory / "backup-metadata.json")
    assert report.verified_artifacts == ("database_dump",)
    assert not list(destination.glob("*.staging.*"))


def test_asset_backup_finalizes_manifest_and_encrypted_archive(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "objects").mkdir()
    (asset_root / "objects" / "one.txt").write_text("one", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\ninput=''\nwhile (($#)); do case \"$1\" in -o) out=$2; shift 2;; -r) shift 2;; *) input=$1; shift;; esac; done\ncp -- \"$input\" \"$out\"\n",
        encoding="utf-8",
    )
    (fake_bin / "tar").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\nwhile (($#)); do case \"$1\" in -f) out=$2; shift 2;; --file=*) out=${1#--file=}; shift;; *) shift;; esac; done\nprintf 'archive bytes' > \"$out\"\n",
        encoding="utf-8",
    )
    for command in ("age", "tar"):
        (fake_bin / command).chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "test-assets-backup",
        "LEADTRACE_ASSET_BACKUP_MODE": "full",
    }
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    final_directory = destination / "test-assets-backup"
    report = verify_backup(final_directory / "backup-metadata.json")
    assert report.verified_artifacts == ("asset_archive", "asset_manifest")
