"""Bind Preview operations to their registry, directories and connected DB."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import stat
from typing import Literal
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.ai_prefill.preview_models import PreviewMarker
from app.config import Settings


class PreviewIdentityError(RuntimeError):
    """The process cannot establish the identity of its Preview instance."""


@dataclass(frozen=True, slots=True)
class PreviewMarkerData:
    instance_id: UUID
    baseline_sha256: str
    schema_revision: str


@dataclass(frozen=True, slots=True)
class PreviewRegistryData:
    instance_id: UUID
    database_name: str
    database_host: str
    database_port: int
    schema_revision: str
    baseline_sha256: str
    asset_root: Path
    source_root: Path
    artifact_root: Path | None = None


class _ReadyRegistry(BaseModel):
    model_config = ConfigDict(strict=True)
    schema_version: Literal[1]
    state: Literal["ready"]
    instance_id: UUID
    database_name: str = Field(min_length=1)
    database_host: str = Field(min_length=1)
    database_port: int = Field(ge=1, le=65535)
    schema_revision: str = Field(min_length=1)
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_root: Path
    source_root: Path
    artifact_root: Path
    commit: str = Field(min_length=1)
    lockfile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _safe_path(path: Path, label: str) -> None:
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise PreviewIdentityError(f"Preview {label} must be a dedicated absolute path")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise PreviewIdentityError(f"Preview {label} must not contain symlinks")


def _database_target(settings: Settings) -> tuple[str, str, int]:
    try:
        url = make_url(settings.database_url)
        host = url.query.get("host", url.host)
        port = int(url.query.get("port", url.port or 5432))
        if url.get_backend_name() != "postgresql" or not isinstance(host, str) or not host:
            raise ValueError
        if not url.database or not url.database.endswith("_preview"):
            raise ValueError
        if not 1 <= port <= 65535:
            raise ValueError
        return url.database, host, port
    except (ValueError, TypeError, SQLAlchemyError) as error:
        raise PreviewIdentityError("Preview requires an explicit PostgreSQL endpoint and _preview database") from error


def require_preview_settings(settings: Settings) -> None:
    if settings.environment != "preview":
        raise PreviewIdentityError("Preview operations require the preview environment")
    missing = [name for name in (
        "preview_instance_id", "preview_baseline_sha256", "preview_artifact_root", "preview_registry_path",
    ) if getattr(settings, name) is None]
    if missing:
        raise PreviewIdentityError("Preview settings are incomplete: " + ", ".join(missing))
    if set(settings.source_roots) != {"source_pdfs"}:
        raise PreviewIdentityError("Preview v1 requires exactly the registered source_pdfs root")
    paths = {
        "asset_root": settings.asset_root,
        "source_root": settings.source_roots["source_pdfs"],
        "artifact_root": settings.preview_artifact_root,
    }
    for label, path in paths.items():
        _safe_path(path, label)
    _safe_path(settings.preview_registry_path, "registry path")
    values = list(paths.values())
    for i, first in enumerate(values):
        for second in values[i + 1:]:
            if first.is_relative_to(second) or second.is_relative_to(first):
                raise PreviewIdentityError("Preview source, asset and artifact roots must not overlap")
    if any(settings.preview_registry_path.is_relative_to(path) for path in values):
        raise PreviewIdentityError("Preview registry must be outside source, asset and artifact roots")
    _database_target(settings)


def read_preview_registry(settings: Settings) -> PreviewRegistryData:
    """Read a bounded regular file, without creating or modifying directories."""
    require_preview_settings(settings)
    try:
        fd = os.open(settings.preview_registry_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise PreviewIdentityError("Preview registry is not a regular file")
            data = stream.read(65_537)
        if len(data) > 65_536:
            raise PreviewIdentityError("Preview registry exceeds size limit")
        value = _ReadyRegistry.model_validate_json(data)
    except (OSError, ValidationError) as error:
        raise PreviewIdentityError("Preview registry is missing, invalid or not ready") from error
    return PreviewRegistryData(**{
        name: getattr(value, name) for name in PreviewRegistryData.__dataclass_fields__
    })


def verify_preview_identity(
    settings: Settings, *, registry: PreviewRegistryData, marker: PreviewMarkerData,
    database_name: str, schema_revision: str, asset_root: Path,
) -> None:
    require_preview_settings(settings)
    configured_database, host, port = _database_target(settings)
    checks = (
        (registry.instance_id == settings.preview_instance_id, "registry instance id"),
        (marker.instance_id == settings.preview_instance_id, "marker instance id"),
        (registry.baseline_sha256 == settings.preview_baseline_sha256, "registry baseline"),
        (marker.baseline_sha256 == settings.preview_baseline_sha256, "marker baseline"),
        (registry.database_name == database_name == configured_database, "database name"),
        (registry.database_host == host, "database host"),
        (registry.database_port == port, "database port"),
        (registry.schema_revision == schema_revision, "registry schema revision"),
        (marker.schema_revision == schema_revision, "marker schema revision"),
        (registry.asset_root == asset_root == settings.asset_root, "asset root"),
        (registry.source_root == settings.source_roots["source_pdfs"], "source root"),
        (registry.artifact_root == settings.preview_artifact_root, "artifact root"),
    )
    for matches, label in checks:
        if not matches:
            raise PreviewIdentityError(f"Preview identity mismatch: {label}")


@lru_cache(maxsize=1)
def _schema_head() -> str:
    from app.database import DEFAULT_ALEMBIC_CONFIG_PATH
    head = ScriptDirectory.from_config(Config(str(DEFAULT_ALEMBIC_CONFIG_PATH))).get_current_head()
    if head is None:
        raise PreviewIdentityError("Preview code has no schema head")
    return head


def verify_preview_connection(settings: Settings, connection: Connection, *, lock: bool = False) -> None:
    """Read identity on the same DB connection used by the upcoming operation."""
    registry = read_preview_registry(settings)
    for label, path in (
        ("asset", settings.asset_root), ("artifact", settings.preview_artifact_root),
        ("source", settings.source_roots["source_pdfs"]),
    ):
        if not path.is_dir():
            raise PreviewIdentityError(f"Preview {label} directory is unavailable")
    try:
        database_name = connection.scalar(text("SELECT current_database()"))
        schema_revisions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
        statement = select(PreviewMarker.instance_id, PreviewMarker.baseline_sha256, PreviewMarker.schema_revision)
        if lock:
            statement = statement.with_for_update()
        markers = connection.execute(statement).all()
        info = connection.connection.driver_connection.info
        _, host, port = _database_target(settings)
        if info.host != host or info.port != port:
            raise PreviewIdentityError("Preview connected endpoint differs from configuration")
    except SQLAlchemyError as error:
        raise PreviewIdentityError("Preview database identity is unavailable") from error
    if len(markers) != 1:
        raise PreviewIdentityError("Preview database must contain exactly one instance marker")
    if schema_revisions != [_schema_head()]:
        raise PreviewIdentityError("Preview database schema does not match code")
    verify_preview_identity(
        settings, registry=registry, marker=PreviewMarkerData(*markers[0]),
        database_name=database_name, schema_revision=schema_revisions[0], asset_root=settings.asset_root,
    )
