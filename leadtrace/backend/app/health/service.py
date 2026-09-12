from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import check_database_connection, validate_schema_version
from app.releases.models import Release


CheckProbe = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: str
    checks: dict[str, dict[str, str]]

    def as_dict(self) -> dict[str, object]:
        return {"status": self.status, "checks": self.checks}


class HealthService:
    """Collect safe, actionable operational checks for the Admin console."""

    def __init__(
        self,
        settings: Settings,
        *,
        database_probe: CheckProbe = check_database_connection,
    ) -> None:
        self.settings = settings
        self.database_probe = database_probe

    def collect(self, session: Session | None = None) -> HealthReport:
        checks: dict[str, dict[str, str]] = {}
        storage_ok = self._storage_ready()
        checks["storage"] = {
            "status": "ok" if storage_ok else "unavailable",
            "summary": "Asset storage is accessible" if storage_ok else "Asset storage is unavailable",
        }
        try:
            database_ok = bool(self.database_probe(self.settings.database_url))
        except Exception:
            database_ok = False
        checks["database"] = {
            "status": "ok" if database_ok else "unavailable",
            "summary": "Database connection is healthy" if database_ok else "Database connection failed",
        }

        disk_ok = self._disk_ready()
        checks["disk"] = {
            "status": "ok" if disk_ok else "warning",
            "summary": "Sufficient asset volume capacity" if disk_ok else "Asset volume is low on free space",
        }
        checks["worker"] = {
            "status": "ok" if self.settings.redis_url.strip() else "unavailable",
            "summary": "Worker queue is configured" if self.settings.redis_url.strip() else "Worker queue is not configured",
        }
        backup_root = self._backup_root()
        checks["backup"] = {
            "status": "ok" if backup_root is not None and backup_root.is_dir() else "warning",
            "summary": "Backup location is available" if backup_root is not None and backup_root.is_dir() else "Backup location is not configured",
        }

        schema_ok = False
        if session is not None:
            try:
                validate_schema_version(session.get_bind())
                schema_ok = True
            except Exception:
                schema_ok = False
        checks["schema"] = {
            "status": "ok" if schema_ok else "unavailable",
            "summary": "Database schema matches the application" if schema_ok else "Database schema requires migration",
        }

        release_ok = False
        if session is not None:
            release_ok = session.scalar(select(Release.id).where(Release.is_current).limit(1)) is not None
        checks["release"] = {
            "status": "ok" if release_ok else "warning",
            "summary": "A current release is available" if release_ok else "No current release is published",
        }
        required = ("storage", "database", "worker", "schema")
        overall = "ok" if all(checks[name]["status"] == "ok" for name in required) else "degraded"
        return HealthReport(overall, checks)

    def _storage_ready(self) -> bool:
        root = self.settings.asset_root
        return root.is_dir() and root.exists()

    def _disk_ready(self) -> bool:
        try:
            return shutil.disk_usage(self.settings.asset_root).free >= 100 * 1024 * 1024
        except OSError:
            return False

    def _backup_root(self) -> Path | None:
        # Backup paths are intentionally read from configuration but never returned.
        configured = getattr(self.settings, "backup_root", None)
        return configured if isinstance(configured, Path) else None


__all__ = ["HealthReport", "HealthService"]
