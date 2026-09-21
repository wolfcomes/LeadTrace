"""Archive and precisely destroy managed Preview resources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from uuid import UUID

from leadtrace.ops.ai_prefill.preview_runtime import PreviewRuntime, PreviewRuntimeError


class PreviewCleanupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    instance_id: str
    state: str
    database_name: str
    asset_root: str
    source_root: str
    archive_path: str


class PreviewCleanup:
    def __init__(self, runtime: PreviewRuntime, archive_root: Path) -> None:
        self.runtime = runtime
        if archive_root.exists() and archive_root.is_symlink():
            raise PreviewCleanupError("archive root must not be a symlink")
        self.archive_root = archive_root.resolve()
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def _archive_path(self, instance_id: UUID) -> Path:
        return self.archive_root / str(instance_id) / "preview-archive.json"

    def plan(self, instance_id: UUID) -> CleanupPlan:
        try:
            registry = self.runtime.read(instance_id)
        except PreviewRuntimeError as error:
            raise PreviewCleanupError(str(error)) from error
        return CleanupPlan(
            instance_id=str(instance_id),
            state=str(registry.get("state", "unknown")),
            database_name=str(registry.get("database_name", "")),
            asset_root=str(registry.get("asset_root", "")),
            source_root=str(registry.get("source_root", "")),
            archive_path=str(self._archive_path(instance_id)),
        )

    def archive(self, instance_id: UUID, *, receipts: dict[str, object]) -> Path:
        if self.runtime.read(instance_id).get("management") == "native-v1":
            raise PreviewCleanupError("database-backed native Preview archive is not implemented; preserve the instance")
        plan = self.plan(instance_id)
        if plan.state not in {"ready", "archived"}:
            raise PreviewCleanupError("Preview must be ready before archive")
        path = self._archive_path(instance_id)
        if path.exists():
            if path.is_symlink():
                raise PreviewCleanupError("archive path must not be a symlink")
            return path
        registry = self.runtime.read(instance_id)
        payload = {
            "schema_version": 1,
            "instance_id": str(instance_id),
            "registry": registry,
            "receipts": receipts,
        }
        content = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise PreviewCleanupError("archive temporary path already exists")
        temporary.write_bytes(content)
        temporary.replace(path)
        digest = hashlib.sha256(content).hexdigest()
        registry["archive_sha256"] = digest
        registry["archive_path"] = str(path)
        registry["state"] = "archived"
        self.runtime._write(self.runtime._path(instance_id), registry, create=False)
        return path

    def destroy(self, instance_id: UUID) -> CleanupPlan:
        if self.runtime.read(instance_id).get("management") == "native-v1":
            raise PreviewCleanupError("database-backed native Preview destroy is not implemented; preserve the instance")
        plan = self.plan(instance_id)
        archive = self._archive_path(instance_id)
        if plan.state != "archived" or not archive.is_file() or archive.is_symlink():
            raise PreviewCleanupError("Preview must be archived before destroy")
        registry = self.runtime.read(instance_id)
        archive_bytes = archive.read_bytes()
        expected_digest = registry.get("archive_sha256")
        if expected_digest != hashlib.sha256(archive_bytes).hexdigest():
            raise PreviewCleanupError("archive digest does not match registry")
        try:
            archived_registry = json.loads(archive_bytes.decode("utf-8"))["registry"]
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
            raise PreviewCleanupError("archive registry snapshot is invalid") from error
        for key in ("instance_id", "database_name", "asset_root", "source_root", "baseline_sha256", "schema_revision"):
            if archived_registry.get(key) != registry.get(key):
                raise PreviewCleanupError("registry changed after archive")
        asset_root = Path(plan.asset_root)
        if (
            not asset_root.is_absolute()
            or asset_root == Path("/")
            or asset_root.is_symlink()
            or str(instance_id) not in asset_root.parts
            or not asset_root.name
        ):
            raise PreviewCleanupError("refusing to delete unmanaged asset root")
        if asset_root.exists():
            shutil.rmtree(asset_root)
        return plan


__all__ = ["CleanupPlan", "PreviewCleanup", "PreviewCleanupError"]
