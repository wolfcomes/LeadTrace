"""Filesystem registry for explicitly managed Preview instances.

This module records lifecycle facts only. Database provisioning, migrations, and
process supervision remain explicit operator steps and are not inferred from a
registry file.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from secrets import token_hex
from uuid import UUID


class PreviewRuntimeError(RuntimeError):
    pass


def _digest(value: str, label: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PreviewRuntimeError(f"{label} must be a lowercase SHA-256 digest")
    return value


class PreviewRuntime:
    def __init__(self, root: Path) -> None:
        if root.exists() and root.is_symlink():
            raise PreviewRuntimeError("Preview registry root must not be a symlink")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, instance_id: UUID) -> Path:
        return self.root / str(instance_id) / "registry.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _assert_absolute(path: Path, label: str) -> None:
        if not path.is_absolute() or path == Path("/"):
            raise PreviewRuntimeError(f"{label} must be a dedicated absolute path")

    def _write(self, path: Path, value: dict[str, object], *, create: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            raise PreviewRuntimeError("Preview registry path must not be a symlink")
        content = (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode()
        temporary = path.with_name(f".{path.name}.{token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if create:
                try:
                    os.link(temporary, path)
                except FileExistsError as error:
                    raise PreviewRuntimeError("Preview registry already exists") from error
                temporary.unlink(missing_ok=True)
            else:
                os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def create(
        self,
        *,
        instance_id: UUID,
        database_name: str,
        database_host: str,
        database_port: int,
        baseline_sha256: str,
        schema_revision: str,
        asset_root: Path,
        source_root: Path,
        origin: str,
        artifact_root: Path | None = None,
    ) -> Path:
        if not database_name.endswith("_preview"):
            raise PreviewRuntimeError("Preview database name must end with _preview")
        if not database_host or not 1 <= database_port <= 65535:
            raise PreviewRuntimeError("Preview database host and port are required")
        _digest(baseline_sha256, "baseline_sha256")
        self._assert_absolute(asset_root, "asset_root")
        self._assert_absolute(source_root, "source_root")
        artifact_root = artifact_root or asset_root.parent / "artifacts"
        self._assert_absolute(artifact_root, "artifact_root")
        if not origin.startswith(("http://", "https://")):
            raise PreviewRuntimeError("Preview origin must be an HTTP(S) URL")
        path = self._path(instance_id)
        if path.exists() or path.is_symlink():
            raise PreviewRuntimeError("Preview registry already exists")
        registry = {
            "schema_version": 1,
            "instance_id": str(instance_id),
            "state": "initializing",
            "database_name": database_name,
            "database_host": database_host,
            "database_port": database_port,
            "baseline_sha256": baseline_sha256,
            "schema_revision": schema_revision,
            "asset_root": str(asset_root),
            "source_root": str(source_root),
            "artifact_root": str(artifact_root),
            "origin": origin,
            "created_at": self._now(),
        }
        self._write(path, registry, create=True)
        return path

    def read(self, instance_id: UUID) -> dict[str, object]:
        path = self._path(instance_id)
        if path.is_symlink() or self.root not in path.resolve().parents:
            raise PreviewRuntimeError("Preview registry path is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise PreviewRuntimeError("Preview registry does not exist") from error
        if not isinstance(value, dict):
            raise PreviewRuntimeError("Preview registry is not an object")
        return value

    def complete(self, instance_id: UUID, *, commit: str, lockfile_sha256: str) -> dict[str, object]:
        path = self._path(instance_id)
        registry = self.read(instance_id)
        if registry.get("state") != "initializing":
            raise PreviewRuntimeError("Preview registry is not initializing")
        if not commit.strip():
            raise PreviewRuntimeError("Preview commit is required")
        _digest(lockfile_sha256, "lockfile_sha256")
        registry.update(
            {
                "state": "ready",
                "phase": "ready",
                "commit": commit,
                "lockfile_sha256": lockfile_sha256,
                "completed_at": self._now(),
            }
        )
        self._write(path, registry, create=False)
        return registry


__all__ = ["PreviewRuntime", "PreviewRuntimeError"]
