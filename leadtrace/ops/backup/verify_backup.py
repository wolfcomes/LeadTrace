from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


CHUNK_SIZE = 1024 * 1024
REQUIRED_ARTIFACTS = frozenset(
    {"database_dump", "asset_manifest", "asset_archive"}
)
REQUIRED_ARTIFACTS_BY_SCOPE = {
    "database": frozenset({"database_dump"}),
    "assets": frozenset({"asset_manifest", "asset_archive"}),
    "full": REQUIRED_ARTIFACTS,
}
REQUIRED_VERSION_FIELDS = frozenset({"application", "schema", "release"})
SENSITIVE_FIELD_MARKERS = (
    "password",
    "secret",
    "token",
    "private_key",
    "private-key",
    "credential",
)


@dataclass(frozen=True, slots=True)
class BackupVerificationReport:
    backup_id: str
    backup_scope: str
    verified_artifacts: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_sensitive_fields(value: object, *, field_path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold().replace(" ", "_")
            if any(marker in normalized_key for marker in SENSITIVE_FIELD_MARKERS):
                raise ValueError(f"sensitive field is not allowed in backup metadata: {field_path}")
            _reject_sensitive_fields(child, field_path=f"{field_path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, field_path=f"{field_path}[{index}]")


def _required_nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"backup metadata field is required: {field_name}")
    return value.strip()


def _parse_utc_timestamp(value: object, field_name: str) -> datetime:
    raw = _required_nonempty_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"backup metadata field is required and must be an ISO timestamp: {field_name}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"backup metadata timestamp must include UTC offset: {field_name}")
    return parsed.astimezone(UTC)


def verify_backup(metadata_path: Path) -> BackupVerificationReport:
    metadata_file = Path(metadata_path).resolve(strict=True)
    payload = json.loads(metadata_file.read_text(encoding="utf-8"))
    _reject_sensitive_fields(payload)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported backup metadata schema version")
    if payload.get("outcome") != "success":
        raise ValueError("metadata does not describe a successful finalized backup")
    backup_id = _required_nonempty_string(payload.get("backup_id"), "backup_id")
    backup_scope = _required_nonempty_string(payload.get("backup_scope", "full"), "backup_scope")
    required_artifacts = REQUIRED_ARTIFACTS_BY_SCOPE.get(backup_scope)
    if required_artifacts is None:
        raise ValueError("backup metadata backup_scope is unsupported")
    started_at = _parse_utc_timestamp(payload.get("started_at"), "started_at")
    completed_at = _parse_utc_timestamp(payload.get("completed_at"), "completed_at")
    if completed_at < started_at:
        raise ValueError("backup completed_at must not precede started_at")
    versions = payload.get("versions")
    if not isinstance(versions, dict) or set(versions) != REQUIRED_VERSION_FIELDS:
        raise ValueError("backup metadata version fields are required")
    for field_name in REQUIRED_VERSION_FIELDS:
        _required_nonempty_string(versions.get(field_name), f"versions.{field_name}")
    destination = payload.get("destination")
    if not isinstance(destination, dict):
        raise ValueError("backup destination identity is required")
    _required_nonempty_string(destination.get("kind"), "destination.kind")
    _required_nonempty_string(destination.get("identity"), "destination.identity")
    encryption = payload.get("encryption")
    if not isinstance(encryption, dict) or (
        encryption.get("algorithm") != "age-x25519"
        or encryption.get("payloads_encrypted") is not True
    ):
        raise ValueError("backup payloads must be encrypted with age-x25519")
    fingerprint = encryption.get("recipient_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ValueError("backup encryption recipient fingerprint is required")
    artifacts = payload["artifacts"]
    if set(artifacts) != required_artifacts:
        raise ValueError("backup metadata must describe the complete artifact set for its scope")

    verified: list[str] = []
    for artifact_name in sorted(artifacts):
        artifact = artifacts[artifact_name]
        if not isinstance(artifact, dict):
            raise ValueError(f"backup artifact metadata is invalid: {artifact_name}")
        raw_path = _required_nonempty_string(artifact.get("path"), f"artifacts.{artifact_name}.path")
        relative_path = Path(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"backup artifact path must remain within backup directory: {artifact_name}")
        candidate = metadata_file.parent / relative_path
        if candidate.is_symlink():
            raise ValueError(f"backup artifact must not be a symbolic link: {artifact_name}")
        path = candidate.resolve(strict=False)
        try:
            path.relative_to(metadata_file.parent)
        except ValueError as error:
            raise ValueError(f"backup artifact path must remain within backup directory: {artifact_name}") from error
        if not path.is_file():
            raise ValueError(f"backup artifact is missing or not a regular file: {artifact_name}")
        expected_size = artifact.get("size_bytes")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError(f"backup artifact size is required: {artifact_name}")
        if path.stat().st_size != expected_size:
            raise ValueError(f"backup artifact size mismatch: {artifact_name}")
        expected_hash = _required_nonempty_string(artifact.get("sha256"), f"artifacts.{artifact_name}.sha256")
        if _sha256(path) != expected_hash:
            raise ValueError(f"backup artifact hash mismatch: {artifact_name}")
        verified.append(artifact_name)
    return BackupVerificationReport(
        backup_id=backup_id,
        backup_scope=backup_scope,
        verified_artifacts=tuple(verified),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a finalized LeadTrace backup set and its metadata."
    )
    parser.add_argument("metadata", type=Path, help="Path to backup-metadata.json")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = verify_backup(args.metadata)
    print(
        f"backup_id={report.backup_id} "
        f"verified_artifacts={len(report.verified_artifacts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
