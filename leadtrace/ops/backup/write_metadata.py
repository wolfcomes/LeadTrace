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
    asset_mode: str | None = None,
    parent_backup_id: str | None = None,
    chain_position: int | None = None,
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
    if backup_scope == "assets":
        if asset_mode not in {"full", "incremental"} or chain_position is None:
            raise ValueError("asset backup chain identity is required")
        if asset_mode == "full" and (parent_backup_id is not None or chain_position != 0):
            raise ValueError("full asset backup must start a new chain")
        if asset_mode == "incremental" and (
            not parent_backup_id or chain_position < 1
        ):
            raise ValueError("incremental asset backup must identify its parent")
        payload["asset_chain"] = {
            "mode": asset_mode,
            "parent_backup_id": parent_backup_id,
            "position": chain_position,
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
    parser.add_argument("--asset-mode", choices=("full", "incremental"))
    parser.add_argument("--parent-backup-id")
    parser.add_argument("--chain-position", type=int)
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
        asset_mode=args.asset_mode,
        parent_backup_id=args.parent_backup_id,
        chain_position=args.chain_position,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
