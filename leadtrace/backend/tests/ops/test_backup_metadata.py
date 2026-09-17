from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import time

import pytest

from leadtrace.ops.backup.prune_backups import expired_backup_directories
from leadtrace.ops.backup.verify_backup import verify_backup
from leadtrace.ops.restore.verify_restored_system import verify_asset_restore


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


def test_asset_backup_metadata_requires_a_restorable_chain_identity(
    tmp_path: Path,
) -> None:
    metadata_path, metadata = _write_complete_backup(tmp_path)
    metadata["backup_scope"] = "assets"
    metadata["artifacts"].pop("database_dump")
    snapshot = tmp_path / "tar.snapshot"
    snapshot.write_bytes(b"snapshot state")
    metadata["artifacts"]["asset_snapshot"] = {
        "path": snapshot.name,
        "sha256": _sha256(snapshot.read_bytes()),
        "size_bytes": snapshot.stat().st_size,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="chain"):
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
        "LEADTRACE_BACKUP_ALLOWED_PARENT": "/tmp",
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


def test_default_backup_ids_include_scope_to_avoid_gate_collisions(
    tmp_path: Path,
) -> None:
    common = Path(__file__).parents[3] / "ops" / "backup" / "common.sh"
    script = """
source "$1"
BACKUP_DESTINATION="$2"
date() { printf '%s\n' '20260912T100000Z'; }
new_staging_directory database
database_id="$BACKUP_ID"
cleanup_staging_directory
unset BACKUP_ID
new_staging_directory assets
assets_id="$BACKUP_ID"
cleanup_staging_directory
printf '%s\n%s\n' "$database_id" "$assets_id"
"""

    result = subprocess.run(
        ["bash", "-c", script, "leadtrace-test", str(common), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "20260912T100000Z-database",
        "20260912T100000Z-assets",
    ]


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
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
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


def test_same_id_postgres_backups_are_serialized_without_nested_finalize(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    (fake_bin / "pg_dump").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "out=''\n"
        "for arg in \"$@\"; do case \"$arg\" in --file=*) out=\"${arg#--file=}\";; esac; done\n"
        "touch \"$LEADTRACE_TEST_BARRIER/entered.$$\"\n"
        "while [[ ! -e \"$LEADTRACE_TEST_BARRIER/release\" ]]; do sleep 0.01; done\n"
        "printf 'database bytes' > \"$out\"\n",
        encoding="utf-8",
    )
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\ninput=''\n"
        "while (($#)); do case \"$1\" in -o) out=$2; shift 2;; -r) shift 2;; *) input=$1; shift;; esac; done\n"
        "cp -- \"$input\" \"$out\"\n",
        encoding="utf-8",
    )
    for command in ("pg_dump", "age"):
        (fake_bin / command).chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_DATABASE_URL": "postgresql://example.invalid/leadtrace",
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "same-id",
        "LEADTRACE_TEST_BARRIER": str(barrier),
    }
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_postgres.sh"
    processes = [
        subprocess.Popen(
            ["bash", str(script_path)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        deadline = time.monotonic() + 3
        while not list(barrier.glob("entered.*")) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(barrier.glob("entered.*"))) == 1
        time.sleep(0.15)
        assert len(list(barrier.glob("entered.*"))) == 1
    finally:
        (barrier / "release").touch()
        results = [process.communicate(timeout=5) for process in processes]

    assert sorted(process.returncode for process in processes) == [0, 2]
    final_directory = destination / "same-id"
    assert (final_directory / "backup-metadata.json").is_file()
    assert not list(final_directory.glob(".leadtrace-*.staging.*"))
    assert not list(destination.glob(".leadtrace-*.staging.*"))
    assert any("already exists" in stderr for _, stderr in results)


def test_asset_backup_finalizes_manifest_and_encrypted_archive(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "objects").mkdir()
    (asset_root / "objects" / "one.txt").write_text("one", encoding="utf-8")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\ninput=''\nwhile (($#)); do case \"$1\" in -o) out=$2; shift 2;; -r) shift 2;; *) input=$1; shift;; esac; done\ncp -- \"$input\" \"$out\"\n",
        encoding="utf-8",
    )
    for command in ("age",):
        (fake_bin / command).chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_SOURCE_ROOTS": json.dumps({"source_pdfs": str(source_root)}),
        "LEADTRACE_SOURCE_ALLOWED_PARENTS": json.dumps(
            {"source_pdfs": str(tmp_path)}
        ),
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
    assert report.verified_artifacts == (
        "asset_archive",
        "asset_manifest",
        "asset_snapshot",
    )
    metadata = json.loads(
        (final_directory / "backup-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["asset_chain"] == {
        "mode": "full",
        "parent_backup_id": None,
        "position": 0,
    }
    manifest = json.loads(
        (final_directory / "assets.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["layout"] == {
        "managed_root": "managed",
        "source_roots": {"source_pdfs": "sources/source_pdfs"},
    }
    assert {row["path"] for row in manifest["files"]} == {
        "managed/objects/one.txt",
        "sources/source_pdfs/paper.pdf",
    }


def test_asset_backup_requires_explicit_source_root_configuration(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"
    environment = {
        **os.environ,
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "missing-source-config",
    }
    environment.pop("LEADTRACE_SOURCE_ROOTS", None)
    environment.pop("LEADTRACE_SOURCE_ALLOWED_PARENTS", None)

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "LEADTRACE_SOURCE_ROOTS is required" in result.stderr
    assert not (destination / "missing-source-config").exists()


def test_asset_backup_requires_the_source_pdfs_namespace(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    (fake_bin / "age").chmod(0o755)
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_SOURCE_ROOTS": "{}",
        "LEADTRACE_SOURCE_ALLOWED_PARENTS": "{}",
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "missing-source-pdfs",
    }

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "source_pdfs" in (result.stderr + result.stdout).casefold()
    assert not (destination / "missing-source-pdfs").exists()


def test_asset_backup_rejects_source_root_outside_its_allowed_parent(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    source_root = tmp_path / "source"
    source_root.mkdir()
    approved_parent = tmp_path / "approved"
    approved_parent.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    (fake_bin / "age").chmod(0o755)
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_SOURCE_ROOTS": json.dumps({"source_pdfs": str(source_root)}),
        "LEADTRACE_SOURCE_ALLOWED_PARENTS": json.dumps(
            {"source_pdfs": str(approved_parent)}
        ),
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
        "LEADTRACE_BACKUP_ID": "source-outside-parent",
    }

    result = subprocess.run(
        ["bash", str(script_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "allowed parent" in (result.stderr + result.stdout).casefold()
    assert not (destination / "source-outside-parent").exists()


def test_asset_backup_rejects_source_and_destination_overlap(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = destination / "assets"
    asset_root.mkdir()
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"
    environment = {
        **os.environ,
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(destination),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
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
    assert "overlap" in (result.stderr + result.stdout).casefold()


def test_full_and_incremental_asset_chain_restores_with_real_tar(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    first = asset_root / "first.txt"
    first.write_text("first revision", encoding="utf-8")
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "paper.txt"
    source_file.write_text("source revision one", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "age").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nout=''\ninput=''\n"
        "while (($#)); do case \"$1\" in -o) out=$2; shift 2;; -r) shift 2;; *) input=$1; shift;; esac; done\n"
        "cp -- \"$input\" \"$out\"\n",
        encoding="utf-8",
    )
    (fake_bin / "age").chmod(0o755)
    script_path = Path(__file__).parents[3] / "ops" / "backup" / "backup_assets.sh"
    common_environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEADTRACE_BACKUP_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_BACKUP_DESTINATION": str(destination),
        "LEADTRACE_ASSET_ALLOWED_PARENT": str(tmp_path),
        "LEADTRACE_ASSET_ROOT": str(asset_root),
        "LEADTRACE_SOURCE_ROOTS": json.dumps({"source_pdfs": str(source_root)}),
        "LEADTRACE_SOURCE_ALLOWED_PARENTS": json.dumps(
            {"source_pdfs": str(tmp_path)}
        ),
        "LEADTRACE_ENCRYPTION_RECIPIENT": "age1example",
        "LEADTRACE_ENCRYPTION_FINGERPRINT": "SHA256:test-key",
        "LEADTRACE_DESTINATION_ID": "test-destination",
        "LEADTRACE_APPLICATION_VERSION": "0.1.0",
        "LEADTRACE_SCHEMA_VERSION": "0015",
        "LEADTRACE_RELEASE_VERSION": "release-test",
    }

    full = subprocess.run(
        ["bash", str(script_path)],
        env={
            **common_environment,
            "LEADTRACE_BACKUP_ID": "assets-full",
            "LEADTRACE_ASSET_BACKUP_MODE": "full",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert full.returncode == 0, full.stderr
    first.unlink()
    (asset_root / "second.txt").write_text("second revision", encoding="utf-8")
    source_file.write_text("source revision two", encoding="utf-8")
    incremental = subprocess.run(
        ["bash", str(script_path)],
        env={
            **common_environment,
            "LEADTRACE_BACKUP_ID": "assets-incremental",
            "LEADTRACE_ASSET_BACKUP_MODE": "incremental",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert incremental.returncode == 0, incremental.stderr
    assert (destination / ".leadtrace-latest-assets").resolve() == (
        destination / "assets-incremental"
    )

    terminal_metadata = destination / "assets-incremental" / "backup-metadata.json"
    chain_helper = Path(__file__).parents[3] / "ops" / "backup" / "asset_chain.py"
    chain = subprocess.run(
        ["python", str(chain_helper), "--metadata", str(terminal_metadata)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert chain.returncode == 0, chain.stderr
    metadata_paths = [Path(value) for value in chain.stdout.splitlines()]
    assert [path.parent.name for path in metadata_paths] == [
        "assets-full",
        "assets-incremental",
    ]
    for metadata_path in metadata_paths:
        directory_skeleton = metadata_path.parent / "asset-snapshot"
        assert directory_skeleton.is_dir()
        assert not any(path.is_file() for path in directory_skeleton.rglob("*"))

    restored = tmp_path / "restored"
    restored.mkdir()
    for metadata_path in metadata_paths:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        archive = metadata_path.parent / payload["artifacts"]["asset_archive"]["path"]
        extraction = subprocess.run(
            [
                "tar",
                "--extract",
                "--listed-incremental=/dev/null",
                f"--file={archive}",
                f"--directory={restored}",
                "--no-same-owner",
                "--no-same-permissions",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert extraction.returncode == 0, extraction.stderr
    terminal = json.loads(terminal_metadata.read_text(encoding="utf-8"))
    manifest = terminal_metadata.parent / terminal["artifacts"]["asset_manifest"]["path"]
    report = verify_asset_restore(manifest, restored)
    assert report.ok is True
    assert not (restored / "managed" / first.name).exists()
    assert (restored / "managed" / "second.txt").read_text(encoding="utf-8") == (
        "second revision"
    )
    assert (restored / "sources" / "source_pdfs" / source_file.name).read_text(
        encoding="utf-8"
    ) == "source revision two"


def test_retention_prunes_only_verified_expired_direct_children(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()

    def write_database_backup(backup_id: str, completed_at: str) -> Path:
        root = destination / backup_id
        root.mkdir()
        artifact = root / "database.dump.age"
        artifact.write_bytes(backup_id.encode())
        metadata = {
            "schema_version": 1,
            "backup_id": backup_id,
            "backup_scope": "database",
            "started_at": completed_at,
            "completed_at": completed_at,
            "outcome": "success",
            "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
            "encryption": {
                "algorithm": "age-x25519",
                "recipient_fingerprint": "SHA256:key",
                "payloads_encrypted": True,
            },
            "destination": {"kind": "separate_disk", "identity": "disk-a"},
            "artifacts": {
                "database_dump": {
                    "path": artifact.name,
                    "sha256": _sha256(artifact.read_bytes()),
                    "size_bytes": artifact.stat().st_size,
                }
            },
        }
        (root / "backup-metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return root

    expired = write_database_backup("database-expired", "2026-07-01T00:00:00Z")
    current = write_database_backup("database-current", "2026-09-10T00:00:00Z")
    unmanaged = destination / "operator-notes"
    unmanaged.mkdir()
    tool = Path(__file__).parents[3] / "ops" / "backup" / "prune_backups.py"
    command = [
        "python",
        str(tool),
        "--destination",
        str(destination),
        "--allowed-parent",
        str(tmp_path),
        "--retention-days",
        "30",
        "--now",
        "2026-09-12T00:00:00Z",
    ]

    preview = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    assert preview.returncode == 0, preview.stderr
    assert "database-expired" in preview.stdout
    assert expired.exists() and current.exists() and unmanaged.exists()

    applied = subprocess.run(
        [*command, "--apply"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert applied.returncode == 0, applied.stderr
    assert not expired.exists()
    assert current.exists()
    assert unmanaged.exists()


def test_retention_preserves_expired_parents_of_retained_asset_backups(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()

    def write_asset_backup(
        backup_id: str,
        completed_at: str,
        *,
        mode: str,
        parent_backup_id: str | None,
        position: int,
    ) -> Path:
        root = destination / backup_id
        root.mkdir()
        artifacts: dict[str, dict[str, object]] = {}
        for artifact_name, filename in {
            "asset_manifest": "assets.manifest.json",
            "asset_archive": "assets.tar.age",
            "asset_snapshot": "tar.snapshot",
        }.items():
            artifact = root / filename
            artifact.write_bytes(f"{backup_id}:{artifact_name}".encode())
            artifacts[artifact_name] = {
                "path": filename,
                "sha256": _sha256(artifact.read_bytes()),
                "size_bytes": artifact.stat().st_size,
            }
        metadata = {
            "schema_version": 1,
            "backup_id": backup_id,
            "backup_scope": "assets",
            "started_at": completed_at,
            "completed_at": completed_at,
            "outcome": "success",
            "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
            "encryption": {
                "algorithm": "age-x25519",
                "recipient_fingerprint": "SHA256:key",
                "payloads_encrypted": True,
            },
            "destination": {"kind": "separate_disk", "identity": "disk-a"},
            "asset_chain": {
                "mode": mode,
                "parent_backup_id": parent_backup_id,
                "position": position,
            },
            "artifacts": artifacts,
        }
        (root / "backup-metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return root

    full = write_asset_backup(
        "assets-full",
        "2026-08-12T00:00:00Z",
        mode="full",
        parent_backup_id=None,
        position=0,
    )
    write_asset_backup(
        "assets-incremental",
        "2026-08-14T00:00:00Z",
        mode="incremental",
        parent_backup_id="assets-full",
        position=1,
    )

    candidates = expired_backup_directories(
        destination,
        allowed_parent=tmp_path,
        cutoff=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert full not in candidates


def test_retention_cli_waits_for_the_shared_destination_lock(tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    root = destination / "database-expired"
    root.mkdir()
    artifact = root / "database.dump.age"
    artifact.write_bytes(b"expired")
    metadata = {
        "schema_version": 1,
        "backup_id": root.name,
        "backup_scope": "database",
        "started_at": "2026-07-01T00:00:00Z",
        "completed_at": "2026-07-01T00:00:00Z",
        "outcome": "success",
        "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:key",
            "payloads_encrypted": True,
        },
        "destination": {"kind": "separate_disk", "identity": "disk-a"},
        "artifacts": {
            "database_dump": {
                "path": artifact.name,
                "sha256": _sha256(artifact.read_bytes()),
                "size_bytes": artifact.stat().st_size,
            }
        },
    }
    (root / "backup-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    common = Path(__file__).parents[3] / "ops" / "backup" / "common.sh"
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            'source "$1"; BACKUP_DESTINATION="$2"; acquire_backup_lock; echo locked; read -r',
            "leadtrace-lock-holder",
            str(common),
            str(destination),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    tool = Path(__file__).parents[3] / "ops" / "backup" / "prune_backups.py"
    prune = subprocess.Popen(
        [
            "python",
            str(tool),
            "--destination",
            str(destination),
            "--allowed-parent",
            str(tmp_path),
            "--retention-days",
            "30",
            "--now",
            "2026-09-12T00:00:00Z",
            "--apply",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.15)
        assert prune.poll() is None
        assert root.exists()
    finally:
        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        holder.communicate(timeout=5)
        prune_stdout, prune_stderr = prune.communicate(timeout=5)

    assert holder.returncode == 0
    assert prune.returncode == 0, prune_stderr
    assert "database-expired" in prune_stdout
    assert not root.exists()


def _write_asset_chain(destination: Path, *, length: int) -> Path:
    parent_backup_id: str | None = None
    terminal = destination
    for position in range(length):
        backup_id = f"assets-{position:03d}"
        root = destination / backup_id
        root.mkdir()
        artifacts: dict[str, dict[str, object]] = {}
        for artifact_name, filename in {
            "asset_manifest": "assets.manifest.json",
            "asset_archive": "assets.tar.age",
            "asset_snapshot": "tar.snapshot",
        }.items():
            artifact = root / filename
            artifact.write_bytes(f"{backup_id}:{artifact_name}".encode())
            artifacts[artifact_name] = {
                "path": filename,
                "sha256": _sha256(artifact.read_bytes()),
                "size_bytes": artifact.stat().st_size,
            }
        (root / "backup-metadata.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "backup_id": backup_id,
                    "backup_scope": "assets",
                    "started_at": "2026-09-12T00:00:00Z",
                    "completed_at": "2026-09-12T00:01:00Z",
                    "outcome": "success",
                    "versions": {
                        "application": "0.1.0",
                        "schema": "0015",
                        "release": "r1",
                    },
                    "encryption": {
                        "algorithm": "age-x25519",
                        "recipient_fingerprint": "SHA256:key",
                        "payloads_encrypted": True,
                    },
                    "destination": {
                        "kind": "separate_disk",
                        "identity": "disk-a",
                    },
                    "asset_chain": {
                        "mode": "full" if position == 0 else "incremental",
                        "parent_backup_id": parent_backup_id,
                        "position": position,
                    },
                    "artifacts": artifacts,
                }
            ),
            encoding="utf-8",
        )
        parent_backup_id = backup_id
        terminal = root / "backup-metadata.json"
    return terminal


def test_asset_chain_next_allows_the_128th_node(tmp_path: Path) -> None:
    terminal = _write_asset_chain(tmp_path, length=127)
    tool = Path(__file__).parents[3] / "ops" / "backup" / "asset_chain.py"

    result = subprocess.run(
        ["python", str(tool), "--metadata", str(terminal), "--next"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split("|")[1] == "127"


def test_asset_chain_next_requires_a_new_full_backup_after_128_nodes(
    tmp_path: Path,
) -> None:
    terminal = _write_asset_chain(tmp_path, length=128)
    tool = Path(__file__).parents[3] / "ops" / "backup" / "asset_chain.py"

    result = subprocess.run(
        ["python", str(tool), "--metadata", str(terminal), "--next"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "full backup" in result.stderr.casefold()


def test_systemd_units_define_backup_retention_and_restore_schedules() -> None:
    systemd_root = Path(__file__).parents[3] / "ops" / "systemd"
    expected = {
        "leadtrace-backup-postgres.timer": "OnCalendar=*-*-* 00/4:00:00",
        "leadtrace-backup-assets-incremental.timer": "OnCalendar=*-*-* 01:15:00",
        "leadtrace-backup-assets-full.timer": "OnCalendar=Sun *-*-* 02:30:00",
        "leadtrace-backup-retention.timer": "OnCalendar=*-*-* 03:30:00",
        "leadtrace-restore-drill.timer": "OnCalendar=monthly",
        "leadtrace-backup-gate.service": "LEADTRACE_ASSET_BACKUP_MODE=full",
    }

    for filename, required in expected.items():
        content = (systemd_root / filename).read_text(encoding="utf-8")
        assert required in content
        assert "Persistent=true" in content if filename.endswith(".timer") else True

    restore_service = (systemd_root / "leadtrace-restore-drill.service").read_text(
        encoding="utf-8"
    )
    assert (
        "Environment=LEADTRACE_PYTHON_BIN=/opt/leadtrace/.venv/bin/python"
        in restore_service
    )
    restore_script = (
        Path(__file__).parents[3] / "ops" / "restore" / "restore_drill.sh"
    ).read_text(encoding="utf-8")
    assert 'PYTHON_BIN="${LEADTRACE_PYTHON_BIN:-python}"' in restore_script
    assert '"${PYTHON_BIN}" "${SCRIPT_DIRECTORY}/validate_restore_target.py"' in restore_script
