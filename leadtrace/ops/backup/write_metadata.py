from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_artifact(raw_value: str) -> tuple[str, Path]:
    try:
        name, raw_path = raw_value.split("=", 1)
    except ValueError as error:
        raise ValueError("artifact must use NAME=PATH syntax") from error
    if not name or not raw_path:
        raise ValueError("artifact name and path are required")
    path = Path(raw_path).resolve(strict=True)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact is not a regular file: {name}")
    return name, path


def write_metadata(
    output: Path,
    *,
    backup_id: str,
    backup_scope: str,
    started_at: str,
    destination_id: str,
    destination_kind: str,
    encryption_recipient: str,
    application_version: str,
    schema_version: str,
    release_version: str,
    artifacts: Sequence[str],
) -> None:
    parsed_artifacts = dict(_parse_artifact(value) for value in artifacts)
    if not parsed_artifacts:
        raise ValueError("at least one backup artifact is required")
    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": 1,
        "backup_id": backup_id,
        "backup_scope": backup_scope,
        "started_at": started_at,
        "completed_at": completed_at,
        "outcome": "success",
        "versions": {
            "application": application_version,
            "schema": schema_version,
            "release": release_version,
        },
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": encryption_recipient,
            "payloads_encrypted": True,
        },
        "destination": {
            "kind": destination_kind,
            "identity": destination_id,
        },
        "artifacts": {
            name: {
                "path": path.name,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for name, path in sorted(parsed_artifacts.items())
        },
    }
    destination = Path(output).resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a LeadTrace backup metadata record.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--backup-scope", choices=("database", "assets", "full"), required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--destination-kind", default="separate_disk")
    parser.add_argument("--encryption-recipient", required=True)
    parser.add_argument("--application-version", required=True)
    parser.add_argument("--schema-version", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--artifact", action="append", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    write_metadata(
        args.output,
        backup_id=args.backup_id,
        backup_scope=args.backup_scope,
        started_at=args.started_at,
        destination_id=args.destination_id,
        destination_kind=args.destination_kind,
        encryption_recipient=args.encryption_recipient,
        application_version=args.application_version,
        schema_version=args.schema_version,
        release_version=args.release_version,
        artifacts=args.artifact,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
