from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from leadtrace.ops.backup.asset_chain import resolve_asset_chain  # noqa: E402
from leadtrace.ops.backup.verify_backup import verify_backup  # noqa: E402


CHUNK_SIZE = 1024 * 1024
PAPER_CENTRIC_COUNT_KEYS = {
    "papers",
    "paper_sources",
    "review_tasks",
    "paper_workspaces",
    "paper_section_reviews",
    "change_events",
    "paper_submissions",
    "admin_decisions",
    "published_paper_versions",
    "current_published_papers",
    "ai_extraction_runs",
    "compounds",
    "structures",
    "structure_source_images",
    "lineages",
    "lineage_members",
    "lineage_edges",
    "evidence",
    "edge_evidence_links",
    "activities",
    "assets",
    "crop_jobs",
    "crop_job_attempts",
    "crop_job_retry_operations",
    "maintenance_windows",
    "users",
    "admin_users",
}
PAPER_CENTRIC_INTEGRITY_KEYS = {
    "paper_source_asset_mismatches",
    "current_publication_pointer_mismatches",
    "publication_hash_mismatches",
    "snapshot_hash_mismatches",
    "missing_or_corrupt_assets",
    "audit_chain_invalid",
}


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


class InvalidDrillAccountError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_backup_evidence(
    database_metadata: Path,
    asset_metadata: Path,
) -> dict[str, object]:
    database_path = Path(database_metadata).resolve(strict=True)
    asset_path = Path(asset_metadata).resolve(strict=True)
    database_report = verify_backup(database_path)
    asset_report = verify_backup(asset_path)
    if database_report.backup_scope != "database":
        raise ValueError("database backup evidence has the wrong scope")
    if asset_report.backup_scope != "assets":
        raise ValueError("asset backup evidence has the wrong scope")
    chain = resolve_asset_chain(asset_path)
    database_payload = json.loads(database_path.read_text(encoding="utf-8"))
    asset_payload = json.loads(asset_path.read_text(encoding="utf-8"))
    versions = database_payload.get("versions")
    if versions != asset_payload.get("versions"):
        raise ValueError("database and asset backup versions do not match")
    chain_rows: list[dict[str, object]] = []
    for node in chain:
        payload = json.loads(node.metadata_path.read_text(encoding="utf-8"))
        archive = payload["artifacts"]["asset_archive"]
        chain_rows.append(
            {
                "backup_id": node.backup_id,
                "metadata_sha256": _sha256(node.metadata_path),
                "archive_sha256": archive["sha256"],
            }
        )
    return {
        "database": {
            "backup_id": database_report.backup_id,
            "metadata_sha256": _sha256(database_path),
            "artifact_sha256": database_payload["artifacts"]["database_dump"][
                "sha256"
            ],
            "versions": versions,
        },
        "assets": {
            "backup_id": asset_report.backup_id,
            "metadata_sha256": _sha256(asset_path),
            "manifest_sha256": asset_payload["artifacts"]["asset_manifest"][
                "sha256"
            ],
            "chain_backup_ids": [node.backup_id for node in chain],
            "chain": chain_rows,
            "versions": versions,
        },
    }


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


def _restored_asset_layout(
    manifest_path: Path,
    restored_root: Path,
) -> tuple[Path, dict[str, Path]]:
    manifest = json.loads(Path(manifest_path).resolve(strict=True).read_text(encoding="utf-8"))
    root = Path(restored_root).resolve(strict=True)
    layout = manifest.get("layout")
    if layout is None:
        return root, {}
    if not isinstance(layout, dict):
        raise ValueError("asset manifest layout is invalid")
    managed_value = layout.get("managed_root")
    source_values = layout.get("source_roots")
    if not isinstance(managed_value, str) or not isinstance(source_values, dict):
        raise ValueError("asset manifest layout is incomplete")

    def bundled_directory(value: object) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("asset layout path must be inside the restored bundle")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ValueError("asset layout path must be inside the restored bundle")
        resolved = root.joinpath(*relative.parts).resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "asset layout path must be inside the restored bundle"
            ) from error
        if not resolved.is_dir():
            raise ValueError("asset layout path must be a restored directory")
        return resolved

    source_roots: dict[str, Path] = {}
    for key, value in source_values.items():
        if not isinstance(key, str) or not key:
            raise ValueError("asset source root key is invalid")
        source_roots[key] = bundled_directory(value)
    return bundled_directory(managed_value), source_roots


def _current_publication_pointer_mismatches(
    papers: Sequence[object],
    published_versions: Sequence[object],
) -> int:
    latest_by_paper: dict[object, object] = {}
    for version in published_versions:
        paper_id = getattr(version, "paper_id")
        latest = latest_by_paper.get(paper_id)
        if latest is None or getattr(version, "version_number") > getattr(
            latest, "version_number"
        ):
            latest_by_paper[paper_id] = version

    paper_ids = {getattr(paper, "id") for paper in papers}
    mismatches = sum(
        1
        for paper in papers
        if getattr(paper, "current_published_version_id")
        != (
            getattr(latest, "id")
            if (latest := latest_by_paper.get(getattr(paper, "id"))) is not None
            else None
        )
    )
    return mismatches + len(set(latest_by_paper) - paper_ids)


def _zero_error_integrity(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == PAPER_CENTRIC_INTEGRITY_KEYS
        and all(type(item) is int and item == 0 for item in value.values())
    )


def _safe_database_counts(
    database_url: str,
    *,
    asset_root: Path | None = None,
    source_roots: dict[str, Path] | None = None,
    excluded_username: str | None = None,
) -> dict[str, object]:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.activities.models import Activity
    from app.assets.models import (
        Asset,
        AssetAccessLevel,
        AssetCategory,
        AssetIntegrityState,
    )
    from app.assets.storage import LocalAssetStore
    from app.ai_prefill.models import AiExtractionRun
    from app.audit.service import AuditService
    from app.catalog.models import PaperSource, PaperSourceIntegrityState
    from app.compounds.models import Compound
    from app.database import create_database_engine
    from app.evidence.models import EdgeEvidenceLink, Evidence
    from app.jobs.models import CropJob, CropJobAttempt, CropJobRetryOperation
    from app.lineages.models import Lineage, LineageEdge, LineageMember
    from app.maintenance.models import MaintenanceWindow
    from app.papers.models import Paper
    from app.publications.models import AdminDecision, PublishedPaperVersion
    from app.structure_images.models import StructureSourceImage
    from app.structures.models import Structure
    from app.users.models import User, UserRole
    from app.users.service import normalize_username
    from app.workspaces.models import (
        ChangeEvent,
        PaperSectionReview,
        PaperSubmission,
        PaperWorkspace,
        ReviewTask,
    )
    from app.workspaces.snapshot import canonical_snapshot_hash

    def count_rows(session: Session, model: type[object]) -> int:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)

    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            user_filters = []
            if excluded_username is not None:
                try:
                    normalized_excluded_username = normalize_username(
                        excluded_username
                    )
                except ValueError as error:
                    raise InvalidDrillAccountError(
                        "restore drill account must be an existing Reviewer"
                    ) from error
                drill_user = session.scalar(
                    select(User).where(
                        User.normalized_username == normalized_excluded_username
                    )
                )
                if drill_user is None or drill_user.role is not UserRole.REVIEWER:
                    raise InvalidDrillAccountError(
                        "restore drill account must be an existing Reviewer"
                    )
                user_filters.append(
                    User.normalized_username != normalized_excluded_username
                )
            users_query = select(func.count()).select_from(User).where(*user_filters)
            admin_users_query = (
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN)
            )
            model_counts = {
                "papers": count_rows(session, Paper),
                "paper_sources": count_rows(session, PaperSource),
                "review_tasks": count_rows(session, ReviewTask),
                "paper_workspaces": count_rows(session, PaperWorkspace),
                "paper_section_reviews": count_rows(session, PaperSectionReview),
                "change_events": count_rows(session, ChangeEvent),
                "paper_submissions": count_rows(session, PaperSubmission),
                "admin_decisions": count_rows(session, AdminDecision),
                "published_paper_versions": count_rows(
                    session, PublishedPaperVersion
                ),
                "current_published_papers": int(
                    session.scalar(
                        select(func.count())
                        .select_from(Paper)
                        .where(Paper.current_published_version_id.is_not(None))
                    )
                    or 0
                ),
                "ai_extraction_runs": count_rows(session, AiExtractionRun),
                "compounds": count_rows(session, Compound),
                "structures": count_rows(session, Structure),
                "structure_source_images": count_rows(
                    session, StructureSourceImage
                ),
                "lineages": count_rows(session, Lineage),
                "lineage_members": count_rows(session, LineageMember),
                "lineage_edges": count_rows(session, LineageEdge),
                "evidence": count_rows(session, Evidence),
                "edge_evidence_links": count_rows(session, EdgeEvidenceLink),
                "activities": count_rows(session, Activity),
                "assets": count_rows(session, Asset),
                "crop_jobs": count_rows(session, CropJob),
                "crop_job_attempts": count_rows(session, CropJobAttempt),
                "crop_job_retry_operations": count_rows(
                    session, CropJobRetryOperation
                ),
                "maintenance_windows": count_rows(session, MaintenanceWindow),
                "users": int(session.scalar(users_query) or 0),
                "admin_users": int(session.scalar(admin_users_query) or 0),
            }

            source_asset_mismatches = 0
            source_rows = session.execute(
                select(PaperSource, Asset)
                .outerjoin(Asset, Asset.id == PaperSource.asset_id)
                .order_by(PaperSource.id)
            ).all()
            for source, asset in source_rows:
                expected_storage_key = (
                    PurePosixPath(
                        "source", source.source_root_key, source.source_key
                    ).as_posix()
                )
                if (
                    asset is None
                    or source.sha256 != asset.sha256
                    or source.byte_size != asset.byte_size
                    or source.page_count != asset.page_count
                    or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
                    or asset.integrity_state is not AssetIntegrityState.VERIFIED
                    or asset.category is not AssetCategory.ARTICLE_PDF
                    or asset.access_level is not AssetAccessLevel.REVIEWER
                    or asset.storage_key != expected_storage_key
                ):
                    source_asset_mismatches += 1

            papers = list(session.scalars(select(Paper)))
            published_versions = list(session.scalars(select(PublishedPaperVersion)))
            pointer_mismatches = _current_publication_pointer_mismatches(
                papers,
                published_versions,
            )

            submissions = list(session.scalars(select(PaperSubmission)))
            submissions_by_id = {
                submission.id: submission for submission in submissions
            }
            decisions = list(session.scalars(select(AdminDecision)))
            decisions_by_id = {decision.id: decision for decision in decisions}
            publication_hash_mismatches = 0
            for decision in decisions:
                submission = submissions_by_id.get(decision.submission_id)
                if (
                    submission is None
                    or decision.paper_id != submission.paper_id
                    or decision.content_hash != submission.content_hash
                ):
                    publication_hash_mismatches += 1
            for version in published_versions:
                submission = submissions_by_id.get(version.submission_id)
                decision = decisions_by_id.get(version.admin_decision_id)
                if (
                    submission is None
                    or decision is None
                    or version.paper_id != submission.paper_id
                    or version.paper_id != decision.paper_id
                    or version.submission_id != decision.submission_id
                    or version.content_hash != submission.content_hash
                    or version.content_hash != decision.content_hash
                ):
                    publication_hash_mismatches += 1

            snapshot_hash_mismatches = 0
            for frozen in [*submissions, *published_versions]:
                snapshot = frozen.snapshot
                if (
                    not isinstance(snapshot, dict)
                    or canonical_snapshot_hash(snapshot) != frozen.content_hash
                ):
                    snapshot_hash_mismatches += 1

            assets = list(session.scalars(select(Asset).order_by(Asset.id)))
            store = (
                LocalAssetStore(asset_root, source_roots=source_roots)
                if asset_root is not None
                else None
            )
            missing_or_corrupt_assets = 0
            for asset in assets:
                if store is None:
                    missing_or_corrupt_assets += 1
                    continue
                try:
                    inspected = store.inspect(asset.storage_key)
                except (OSError, ValueError):
                    missing_or_corrupt_assets += 1
                    continue
                if (
                    inspected.sha256 != asset.sha256
                    or inspected.byte_size != asset.byte_size
                    or inspected.mime_type != asset.mime_type
                    or (
                        asset.page_count is not None
                        and inspected.page_count != asset.page_count
                    )
                    or (asset.width is not None and inspected.width != asset.width)
                    or (asset.height is not None and inspected.height != asset.height)
                ):
                    missing_or_corrupt_assets += 1

            audit_valid = AuditService().verify_chain(session).valid
            return {
                "schema_version": 2,
                "counts": model_counts,
                "integrity": {
                    "paper_source_asset_mismatches": source_asset_mismatches,
                    "current_publication_pointer_mismatches": pointer_mismatches,
                    "publication_hash_mismatches": publication_hash_mismatches,
                    "snapshot_hash_mismatches": snapshot_hash_mismatches,
                    "missing_or_corrupt_assets": missing_or_corrupt_assets,
                    "audit_chain_invalid": 0 if audit_valid else 1,
                },
            }
    finally:
        engine.dispose()


def verify_restored_system(
    *,
    asset_manifest: Path,
    restored_asset_root: Path,
    source_roots: dict[str, Path] | None = None,
    database_url: str | None = None,
    expected_aggregate: dict[str, object],
    base_url: str | None = None,
    drill_username: str | None = None,
    drill_password: str | None = None,
    backup_evidence: dict[str, object],
    started_at: datetime,
    completed_at: datetime | None = None,
    rto_target_seconds: int,
) -> dict[str, object]:
    began_at = started_at.astimezone(UTC)
    asset_report = verify_asset_restore(asset_manifest, restored_asset_root)
    managed_root, bundled_source_roots = _restored_asset_layout(
        asset_manifest,
        restored_asset_root,
    )
    active_source_roots = (
        source_roots if source_roots is not None else bundled_source_roots
    )
    checks: dict[str, object] = {
        "schema_version": 2,
        "assets": asset_report.as_dict(),
        "backup_evidence": backup_evidence,
    }
    errors = list(asset_report.errors)
    expected_counts = expected_aggregate.get("counts")
    expected_integrity = expected_aggregate.get("integrity_expectations")
    if (
        expected_aggregate.get("schema_version") != 2
        or not isinstance(expected_counts, dict)
        or set(expected_counts) != PAPER_CENTRIC_COUNT_KEYS
        or not _zero_error_integrity(expected_integrity)
    ):
        raise ValueError("approved paper-centric expected aggregate is invalid")
    if database_url:
        try:
            baseline = _safe_database_counts(
                database_url,
                asset_root=managed_root,
                source_roots=active_source_roots,
                excluded_username=drill_username,
            )
            integrity_clean = _zero_error_integrity(baseline.get("integrity"))
            baseline_matches = (
                baseline.get("schema_version") == 2
                and set(baseline.get("counts", {})) == PAPER_CENTRIC_COUNT_KEYS
                and baseline.get("counts") == expected_counts
                and baseline.get("integrity") == expected_integrity
                and integrity_clean
            )
            checks["baseline"] = {
                "ok": baseline_matches,
                "integrity_ok": integrity_clean,
                **baseline,
            }
            if not baseline_matches:
                errors.append("database_baseline_mismatch")
            if not integrity_clean:
                errors.append("database_integrity_failed")
        except InvalidDrillAccountError:
            checks["baseline"] = {"ok": False, "error": "drill_account_invalid"}
            errors.append("drill_account_invalid")
        except Exception:
            checks["baseline"] = {"ok": False, "error": "database_unavailable"}
            errors.append("database_unavailable")
    else:
        checks["baseline"] = {"ok": False, "error": "database_not_configured"}
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
    finished_at = (completed_at or datetime.now(UTC)).astimezone(UTC)
    duration_seconds = max(0, int((finished_at - began_at).total_seconds()))
    checks.update(
        started_at=began_at.isoformat().replace("+00:00", "Z"),
        completed_at=finished_at.isoformat().replace("+00:00", "Z"),
        duration_seconds=duration_seconds,
        rto={
            "target_seconds": rto_target_seconds,
            "met": duration_seconds <= rto_target_seconds,
        },
    )
    if duration_seconds > rto_target_seconds:
        errors.append("rto_target_exceeded")
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
            papers = client.get("/api/v2/papers")
            paper_id = None
            if papers.status_code == 200:
                items = papers.json().get("items", [])
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    paper_id = items[0].get("paper_id")
            checks = {
                "papers": papers.status_code == 200 and isinstance(paper_id, str),
                "paper_detail": (
                    isinstance(paper_id, str)
                    and client.get(f"/api/v2/papers/{paper_id}").status_code == 200
                ),
                "authorized_pdf": (
                    isinstance(paper_id, str)
                    and client.get(
                        f"/api/v2/papers/{paper_id}/source-pdf",
                        headers={"Range": "bytes=0-1023"},
                    ).status_code in {200, 206}
                ),
                "audit": client.get("/api/v1/audit/events?limit=1").status_code == 200,
            }
            return {"ok": all(checks.values()), "checks": checks}
    except Exception:
        return {"ok": False, "error": "http_unavailable"}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an isolated LeadTrace restore drill.")
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--restored-asset-root", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-aggregate", type=Path, required=True)
    parser.add_argument("--database-backup-metadata", type=Path, required=True)
    parser.add_argument("--asset-backup-metadata", type=Path, required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--rto-target-seconds", type=int, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    expected_aggregate = json.loads(
        args.expected_aggregate.resolve(strict=True).read_text(encoding="utf-8")
    )
    if not isinstance(expected_aggregate, dict):
        raise SystemExit("expected aggregate must contain a JSON object")
    try:
        started_at = datetime.fromisoformat(args.started_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise SystemExit("started-at must be an ISO timestamp") from error
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise SystemExit("started-at must include a UTC offset")
    if args.rto_target_seconds <= 0:
        raise SystemExit("rto-target-seconds must be positive")
    backup_evidence = build_backup_evidence(
        args.database_backup_metadata,
        args.asset_backup_metadata,
    )
    report = verify_restored_system(
        asset_manifest=args.asset_manifest,
        restored_asset_root=args.restored_asset_root,
        database_url=args.database_url,
        expected_aggregate=expected_aggregate,
        base_url=args.base_url,
        drill_username=os.environ.get("LEADTRACE_DRILL_USERNAME"),
        drill_password=os.environ.get("LEADTRACE_DRILL_PASSWORD"),
        backup_evidence=backup_evidence,
        started_at=started_at,
        rto_target_seconds=args.rto_target_seconds,
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
