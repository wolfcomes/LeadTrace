from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AssetRestoreReport:
    ok: bool
    file_count: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "file_count": self.file_count,
            "errors": list(self.errors),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_restore(
    manifest_path: Path,
    asset_root: Path,
) -> AssetRestoreReport:
    manifest_file = Path(manifest_path).resolve(strict=True)
    root = Path(asset_root).resolve(strict=True)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    files = payload.get("files")
    if payload.get("schema_version") != 1 or not isinstance(files, list):
        return AssetRestoreReport(False, 0, ("asset_manifest_invalid",))

    errors: list[str] = []
    expected_paths: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            errors.append("asset_manifest_invalid")
            continue
        raw_path = row.get("path")
        if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute():
            errors.append("asset_manifest_invalid")
            continue
        relative = Path(raw_path)
        if ".." in relative.parts:
            errors.append("asset_manifest_invalid")
            continue
        expected_paths.add(relative.as_posix())
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            errors.append("asset_missing")
            continue
        if candidate.stat().st_size != row.get("size_bytes"):
            errors.append("asset_size_mismatch")
            continue
        if _sha256(candidate) != row.get("sha256"):
            errors.append("asset_hash_mismatch")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths - expected_paths:
        errors.append("unexpected_asset")
    if len(files) != payload.get("file_count"):
        errors.append("asset_count_mismatch")
    if sum(int(row.get("size_bytes", -1)) for row in files if isinstance(row, dict)) != payload.get("total_bytes"):
        errors.append("asset_total_size_mismatch")
    unique_errors = tuple(dict.fromkeys(errors))
    return AssetRestoreReport(not unique_errors, len(files), unique_errors)


def _safe_database_counts(database_url: str) -> dict[str, int]:
    import psycopg

    connection_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            counts: dict[str, int] = {}
            for table in ("papers", "releases", "audit_events"):
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                counts[table] = int(cursor.fetchone()[0])
            return counts


def verify_restored_system(
    *,
    asset_manifest: Path,
    restored_asset_root: Path,
    database_url: str | None = None,
    expected_counts: dict[str, int] | None = None,
    base_url: str | None = None,
    drill_username: str | None = None,
    drill_password: str | None = None,
) -> dict[str, object]:
    asset_report = verify_asset_restore(asset_manifest, restored_asset_root)
    checks: dict[str, object] = {"assets": asset_report.as_dict()}
    errors = list(asset_report.errors)
    if database_url:
        try:
            counts = _safe_database_counts(database_url)
            checks["database"] = {"ok": True, "counts": counts}
            if expected_counts and counts != expected_counts:
                checks["database"] = {"ok": False, "counts": counts}
                errors.append("database_baseline_mismatch")
        except Exception:
            checks["database"] = {"ok": False, "error": "database_unavailable"}
            errors.append("database_unavailable")
    else:
        checks["database"] = {"ok": False, "error": "database_not_configured"}
        errors.append("database_not_configured")

    if base_url:
        checks["http"] = _verify_http_workflow(
            base_url,
            username=drill_username,
            password=drill_password,
        )
        if not checks["http"]["ok"]:  # type: ignore[index]
            errors.append("http_smoke_failed")
    else:
        checks["http"] = {"ok": False, "error": "http_not_configured"}
        errors.append("http_not_configured")
    checks["errors"] = list(dict.fromkeys(errors))
    checks["ok"] = not errors
    return checks


def _verify_http_workflow(
    base_url: str,
    *,
    username: str | None,
    password: str | None,
) -> dict[str, object]:
    if not username or not password:
        return {"ok": False, "error": "drill_account_not_configured"}
    try:
        import httpx

        with httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            if login.status_code != 200:
                return {"ok": False, "error": "login_failed"}
            csrf_token = login.json().get("csrf_token", "")
            headers = {"X-CSRF-Token": csrf_token}
            checks = {
                "papers": client.get("/api/v1/papers").status_code == 200,
                "release": client.get("/api/v1/published/overview").status_code == 200,
                "audit": client.get("/api/v1/audit/events").status_code in {200, 403},
            }
            return {"ok": all(checks.values()), "checks": checks}
    except Exception:
        return {"ok": False, "error": "http_unavailable"}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an isolated LeadTrace restore drill.")
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--restored-asset-root", type=Path, required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--expected-counts", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    expected_counts = None
    if args.expected_counts:
        expected_counts = json.loads(args.expected_counts.read_text(encoding="utf-8"))
    report = verify_restored_system(
        asset_manifest=args.asset_manifest,
        restored_asset_root=args.restored_asset_root,
        database_url=args.database_url,
        expected_counts=expected_counts,
        base_url=args.base_url,
        drill_username=os.environ.get("LEADTRACE_DRILL_USERNAME"),
        drill_password=os.environ.get("LEADTRACE_DRILL_PASSWORD"),
    )
    destination = args.report.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
