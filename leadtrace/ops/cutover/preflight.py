from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse


LEADTRACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = LEADTRACE_ROOT / "backend"
REPOSITORY_ROOT = LEADTRACE_ROOT.parent
for module_root in (REPOSITORY_ROOT, BACKEND_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from leadtrace.ops.backup.asset_chain import resolve_asset_chain  # noqa: E402
from leadtrace.ops.backup.verify_backup import verify_backup  # noqa: E402


Status = Literal["PASS", "FAIL"]
RESTORE_COUNT_KEYS = frozenset(
    {
        "corpus_papers",
        "lineage_papers",
        "lineages",
        "compound_entities",
        "lineage_edges",
        "activity_rows",
        "complete_structures",
        "structure_confirmed",
        "missing_or_non_unique",
        "pair_ready_edges",
        "papers_with_pair_ready",
    }
)
RESTORE_INTEGRITY_KEYS = frozenset(
    {
        "self_loops",
        "duplicate_directed_edges",
        "unresolved_pair_ready_edges",
        "dangling_entity_references",
        "dangling_evidence_references",
        "invalid_pair_endpoints",
        "published_missing_or_corrupt_assets",
    }
)
RESTORE_HTTP_CHECKS = frozenset(
    {"papers", "paper_detail", "authorized_pdf", "release", "audit"}
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    summary: str
    evidence: dict[str, object]

    @property
    def ok(self) -> bool:
        return self.status == "PASS"

    @classmethod
    def passed(
        cls,
        name: str,
        summary: str,
        **evidence: object,
    ) -> "CheckResult":
        return cls(name, "PASS", summary, evidence)

    @classmethod
    def failed(
        cls,
        name: str,
        summary: str,
        **evidence: object,
    ) -> "CheckResult":
        return cls(name, "FAIL", summary, evidence)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
        }


Probe = Callable[[Mapping[str, object]], CheckResult]


@dataclass(frozen=True, slots=True)
class PreflightProbes:
    database: Probe
    services: Probe
    permissions: Probe
    source_manifest: Probe


@dataclass(frozen=True, slots=True)
class PreflightReport:
    generated_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "status": "PASS" if self.ok else "FAIL",
            "checks": [check.as_dict() for check in self.checks],
        }


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} timestamp has no UTC offset")
    return parsed.astimezone(UTC)


def _required_config(
    config: Mapping[str, object],
    key: str,
    expected: type | tuple[type, ...],
) -> object:
    value = config.get(key)
    if not isinstance(value, expected) or (
        isinstance(value, str) and not value.strip()
    ):
        raise ValueError(f"preflight configuration field is required: {key}")
    return value


def _backup_check(
    name: str,
    config: Mapping[str, object],
    *,
    metadata_key: str,
    expected_scope: str,
    now: datetime,
) -> CheckResult:
    try:
        metadata_path = Path(str(_required_config(config, metadata_key, str))).resolve(
            strict=True
        )
        report = verify_backup(metadata_path)
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        completed_at = _timestamp(payload.get("completed_at"), label=name)
        maximum_age = timedelta(
            hours=float(_required_config(config, "max_backup_age_hours", (int, float)))
        )
        destination = payload.get("destination")
        destination_kind = (
            destination.get("kind") if isinstance(destination, dict) else None
        )
        if report.backup_scope != expected_scope:
            raise ValueError("backup scope does not match cutover requirement")
        if (
            completed_at > now + timedelta(minutes=5)
            or now - completed_at > maximum_age
        ):
            raise ValueError("backup is stale or has an invalid completion time")
        if destination_kind not in {"separate_disk", "controlled_network"}:
            raise ValueError("backup destination is not physically independent")
        versions = payload.get("versions", {})
        expected_versions = {
            "application": config.get("application_version"),
            "schema": config.get("schema_revision"),
            "release": config.get("release_key"),
        }
        if versions != expected_versions:
            raise ValueError("backup versions do not match the cutover target")
        return CheckResult.passed(
            name,
            "Verified recent encrypted backup",
            backup_id=report.backup_id,
            destination_identity=destination.get("identity"),
            completed_at=completed_at.isoformat().replace("+00:00", "Z"),
        )
    except Exception:
        return CheckResult.failed(name, "Backup evidence is missing, invalid, or stale")


def _expected_restore_baseline(
    config: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    expected_path = Path(
        str(_required_config(config, "expected_aggregate", str))
    ).resolve(strict=True)
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or expected.get("schema_version") != 1:
        raise ValueError("approved expected aggregate is invalid")
    counts = expected.get("counts")
    integrity = expected.get("integrity_expectations")
    for values, required_keys, label in (
        (counts, RESTORE_COUNT_KEYS, "counts"),
        (integrity, RESTORE_INTEGRITY_KEYS, "integrity"),
    ):
        if (
            not isinstance(values, dict)
            or set(values) != required_keys
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in values.values()
            )
        ):
            raise ValueError(f"approved expected aggregate {label} is invalid")
    assert isinstance(counts, dict)
    assert isinstance(integrity, dict)
    return counts, integrity


def _restore_rto_seconds(config: Mapping[str, object]) -> int:
    value = config.get("restore_rto_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("preflight configuration field is required: restore_rto_seconds")
    return value


def _validate_restore_report(
    payload: Mapping[str, object],
    *,
    expected_counts: Mapping[str, object],
    expected_integrity: Mapping[str, object],
    expected_rto_seconds: int,
) -> datetime:
    if payload.get("schema_version") != 1:
        raise ValueError("restore report schema is unsupported")
    if payload.get("ok") is not True or payload.get("errors") != []:
        raise ValueError("restore drill did not pass")
    for section_name in ("assets", "baseline", "http"):
        section = payload.get(section_name)
        if not isinstance(section, dict) or section.get("ok") is not True:
            raise ValueError(f"restore report {section_name} check did not pass")

    assets = payload["assets"]
    baseline = payload["baseline"]
    http = payload["http"]
    assert isinstance(assets, dict)
    assert isinstance(baseline, dict)
    assert isinstance(http, dict)
    file_count = assets.get("file_count")
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 0
        or assets.get("errors") != []
    ):
        raise ValueError("restore report asset evidence is incomplete")
    counts = baseline.get("counts")
    integrity = baseline.get("integrity")
    for values, required_keys, label in (
        (counts, RESTORE_COUNT_KEYS, "counts"),
        (integrity, RESTORE_INTEGRITY_KEYS, "integrity"),
    ):
        if (
            not isinstance(values, dict)
            or set(values) != required_keys
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in values.values()
            )
        ):
            raise ValueError(f"restore report baseline {label} is incomplete")
    if counts != expected_counts or integrity != expected_integrity:
        raise ValueError("restore report baseline differs from the approved aggregate")
    release_validation = baseline.get("release_validation")
    if (
        not isinstance(release_validation, dict)
        or release_validation.get("valid") is not True
        or release_validation.get("issues") != []
    ):
        raise ValueError("restore report release validation did not pass")
    http_checks = http.get("checks")
    if not isinstance(http_checks, dict) or any(
        http_checks.get(name) is not True for name in RESTORE_HTTP_CHECKS
    ):
        raise ValueError("restore report HTTP evidence is incomplete")

    started_at = _timestamp(payload.get("started_at"), label="restore drill start")
    completed_at = _timestamp(
        payload.get("completed_at"), label="restore drill completion"
    )
    if completed_at < started_at:
        raise ValueError("restore drill completion precedes its start")
    duration = payload.get("duration_seconds")
    measured_duration = int((completed_at - started_at).total_seconds())
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
        raise ValueError("restore drill duration is invalid")
    if duration != measured_duration:
        raise ValueError("restore drill duration does not match its timestamps")

    rto = payload.get("rto")
    if not isinstance(rto, dict):
        raise ValueError("restore drill RTO evidence is missing")
    target = rto.get("target_seconds")
    met = rto.get("met")
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError("restore drill RTO target is invalid")
    if target != expected_rto_seconds:
        raise ValueError("restore drill RTO target differs from the cutover target")
    if not isinstance(met, bool) or met != (duration <= target):
        raise ValueError("restore drill RTO result is inconsistent")
    if not met:
        raise ValueError("restore drill exceeded its RTO")
    return completed_at


def _restore_check(
    config: Mapping[str, object],
    *,
    now: datetime,
) -> CheckResult:
    try:
        report_path = Path(
            str(_required_config(config, "restore_report", str))
        ).resolve(strict=True)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("restore report must contain an object")
        expected_counts, expected_integrity = _expected_restore_baseline(config)
        completed_at = _validate_restore_report(
            payload,
            expected_counts=expected_counts,
            expected_integrity=expected_integrity,
            expected_rto_seconds=_restore_rto_seconds(config),
        )
        maximum_age = timedelta(
            days=float(_required_config(config, "max_restore_age_days", (int, float)))
        )
        if (
            completed_at > now + timedelta(minutes=5)
            or now - completed_at > maximum_age
        ):
            return CheckResult.failed(
                "restore_drill", "Restore drill evidence is stale"
            )
        evidence = payload.get("backup_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("restore backup evidence is missing")
        expected_versions = {
            "application": config["application_version"],
            "schema": config["schema_revision"],
            "release": config["release_key"],
        }
        selected = {
            "database": Path(
                str(_required_config(config, "database_backup_metadata", str))
            ).resolve(strict=True),
            "assets": Path(
                str(_required_config(config, "asset_backup_metadata", str))
            ).resolve(strict=True),
        }
        for key, metadata_path in selected.items():
            verification = verify_backup(metadata_path)
            actual = evidence.get(key)
            if not isinstance(actual, dict):
                raise ValueError("restore backup evidence is incomplete")
            metadata_hash = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            if (
                actual.get("backup_id") != verification.backup_id
                or actual.get("metadata_sha256") != metadata_hash
                or actual.get("versions") != expected_versions
            ):
                raise ValueError("restore evidence references different backups")
        asset_evidence = evidence["assets"]
        assert isinstance(asset_evidence, dict)
        resolved_chain = resolve_asset_chain(selected["assets"])
        expected_chain = []
        for node in resolved_chain:
            node_payload = json.loads(node.metadata_path.read_text(encoding="utf-8"))
            expected_chain.append(
                {
                    "backup_id": node.backup_id,
                    "metadata_sha256": hashlib.sha256(
                        node.metadata_path.read_bytes()
                    ).hexdigest(),
                    "archive_sha256": node_payload["artifacts"]["asset_archive"][
                        "sha256"
                    ],
                }
            )
        if (
            asset_evidence.get("chain_backup_ids")
            != [node.backup_id for node in resolved_chain]
            or asset_evidence.get("chain") != expected_chain
        ):
            raise ValueError("restore asset chain evidence is invalid")
        return CheckResult.passed(
            "restore_drill",
            "Recent isolated restore drill passed for the selected backups",
            completed_at=completed_at.isoformat().replace("+00:00", "Z"),
        )
    except Exception:
        return CheckResult.failed(
            "restore_drill",
            "Restore drill backup evidence is missing, mismatched, or invalid",
        )


def run_preflight(
    config: Mapping[str, object],
    *,
    probes: PreflightProbes | None = None,
    now: datetime | None = None,
) -> PreflightReport:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    if config.get("schema_version") != 1:
        raise ValueError("unsupported preflight configuration schema version")
    for key in ("application_version", "schema_revision", "release_key"):
        _required_config(config, key, str)
    active_probes = probes or DEFAULT_PROBES
    checks = (
        _backup_check(
            "database_backup",
            config,
            metadata_key="database_backup_metadata",
            expected_scope="database",
            now=checked_at,
        ),
        _backup_check(
            "asset_backup",
            config,
            metadata_key="asset_backup_metadata",
            expected_scope="assets",
            now=checked_at,
        ),
        _restore_check(config, now=checked_at),
        active_probes.database(config),
        active_probes.services(config),
        active_probes.permissions(config),
        active_probes.source_manifest(config),
    )
    return PreflightReport(checked_at, checks)


def _database_probe(config: Mapping[str, object]) -> CheckResult:
    database_url = os.environ.get("LEADTRACE_DATABASE_URL", "").strip()
    try:
        if not database_url:
            raise ValueError("database URL is not configured")
        from sqlalchemy import select

        from app.assets.storage import LocalAssetStore
        from app.audit.service import AuditService
        from app.database import create_database_engine, validate_schema_version
        from app.releases.aggregate import recompute_release_aggregate
        from app.releases.models import Release
        from app.releases.validation import validate_release

        expected_path = Path(
            str(_required_config(config, "expected_aggregate", str))
        ).resolve(strict=True)
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        managed_root = Path(str(_required_config(config, "asset_root", str))).resolve(
            strict=True
        )
        if not managed_root.is_dir():
            raise ValueError("asset root is unavailable")
        raw_source_roots = config.get("source_roots", {})
        if not isinstance(raw_source_roots, dict):
            raise ValueError("source_roots must be an object")
        source_roots = {
            str(key): Path(str(value)).resolve(strict=True)
            for key, value in raw_source_roots.items()
        }
        engine = create_database_engine(database_url)
        try:
            validate_schema_version(engine)
            with engine.connect() as connection:
                actual_schema = connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar_one()
            from sqlalchemy.orm import Session

            with Session(engine) as session:
                release = session.scalar(
                    select(Release).where(Release.is_current).limit(1)
                )
                if release is None or not release.manifest_finalized:
                    raise ValueError("current finalized release is missing")
                if release.release_key != config["release_key"]:
                    raise ValueError("current release does not match cutover target")
                validation = validate_release(
                    session,
                    release.id,
                    asset_store=LocalAssetStore(
                        managed_root,
                        source_roots=source_roots,
                    ),
                )
                aggregate = recompute_release_aggregate(
                    session,
                    release,
                    asset_store=LocalAssetStore(
                        managed_root,
                        source_roots=source_roots,
                    ),
                    validation=validation,
                )
                if aggregate.counts != expected.get("counts"):
                    raise ValueError("current release counts do not match the baseline")
                if aggregate.integrity != expected.get("integrity_expectations"):
                    raise ValueError("current release integrity defects are present")
                audit = AuditService().verify_chain(session)
                if not validation.valid or not audit.valid:
                    raise ValueError("release assets or audit chain are invalid")
                paper_count = aggregate.counts["corpus_papers"]
        finally:
            engine.dispose()
        if actual_schema != config["schema_revision"]:
            raise ValueError("database schema does not match configured target")
        if version("leadtrace-backend") != config["application_version"]:
            raise ValueError("application version does not match configured target")
        return CheckResult.passed(
            "database",
            "Schema, import, release, assets, and audit chain validated",
            schema_revision=actual_schema,
            release_key=config["release_key"],
            paper_count=paper_count,
        )
    except Exception:
        return CheckResult.failed(
            "database",
            "Database, import, release, asset, or audit validation failed",
        )


def _services_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        import httpx
        import redis

        from app.worker import celery_app

        asset_root = Path(str(_required_config(config, "asset_root", str))).resolve(
            strict=True
        )
        if not asset_root.is_dir() or not os.access(
            asset_root, os.R_OK | os.W_OK | os.X_OK
        ):
            raise ValueError("asset storage is unavailable")
        redis_url = os.environ.get("LEADTRACE_REDIS_URL", "").strip()
        if not redis_url or not redis.Redis.from_url(redis_url).ping():
            raise ValueError("Redis is unavailable")
        worker_replies = celery_app.control.inspect(timeout=5.0).ping() or {}
        if not any(
            isinstance(reply, dict) and reply.get("ok") == "pong"
            for reply in worker_replies.values()
        ):
            raise ValueError("Celery worker is unavailable")
        base_url = str(_required_config(config, "base_url", str)).rstrip("/")
        if urlparse(base_url).scheme != "https":
            raise ValueError("LeadTrace URL must use HTTPS")
        old_dashboard_url = str(
            _required_config(config, "old_dashboard_url", str)
        ).rstrip("/")
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            live = client.get(f"{base_url}/health/live")
            ready = client.get(f"{base_url}/health/ready")
            fallback = client.get(f"{old_dashboard_url}/")
        if live.status_code != 200 or ready.status_code != 200:
            raise ValueError("LeadTrace health checks failed")
        if fallback.status_code != 200:
            raise ValueError("old Dashboard fallback is unavailable")
        return CheckResult.passed(
            "services",
            "HTTPS, database-adjacent services, storage, and fallback are ready",
        )
    except Exception:
        return CheckResult.failed(
            "services",
            "HTTPS, Redis, storage, readiness, or fallback check failed",
        )


def _login(client: object, username: str, password: str) -> tuple[bool, str]:
    response = client.post(  # type: ignore[attr-defined]
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        return False, ""
    return True, str(response.json().get("csrf_token", ""))


def _permissions_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        import httpx

        base_url = str(_required_config(config, "base_url", str)).rstrip("/")
        paper_id = str(_required_config(config, "representative_paper_id", str))
        credentials = {
            role: (
                os.environ.get(f"LEADTRACE_PREFLIGHT_{role.upper()}_USERNAME", ""),
                os.environ.get(f"LEADTRACE_PREFLIGHT_{role.upper()}_PASSWORD", ""),
            )
            for role in ("visitor", "reviewer", "admin")
        }
        if any(
            not username or not password for username, password in credentials.values()
        ):
            raise ValueError("preflight role credentials are incomplete")
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as visitor:
            visitor_ok, _ = _login(visitor, *credentials["visitor"])
            visitor_checks = (
                visitor.get("/api/v1/papers?page=1&page_size=1").status_code == 200,
                visitor.get(f"/api/v1/papers/{paper_id}/source-pdf").status_code
                in {403, 404},
                visitor.get("/api/v1/users").status_code == 403,
            )
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as reviewer:
            reviewer_ok, _ = _login(reviewer, *credentials["reviewer"])
            reviewer_checks = (
                reviewer.get(f"/api/v1/papers/{paper_id}/source-pdf").status_code
                in {200, 206},
                reviewer.get("/api/v1/users").status_code == 403,
                reviewer.get("/api/v1/releases").status_code == 403,
            )
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as admin:
            admin_ok, _ = _login(admin, *credentials["admin"])
            admin_checks = (
                admin.get("/api/v1/users").status_code == 200,
                admin.get("/api/v1/releases").status_code == 200,
                admin.get("/api/v1/audit/verify").status_code == 200,
            )
        if not all(
            (
                visitor_ok,
                reviewer_ok,
                admin_ok,
                *visitor_checks,
                *reviewer_checks,
                *admin_checks,
            )
        ):
            raise ValueError("permission matrix smoke test failed")
        return CheckResult.passed(
            "permissions",
            "Visitor, Reviewer, and Admin permission smoke tests passed",
        )
    except Exception:
        return CheckResult.failed(
            "permissions",
            "Role login or permission matrix smoke test failed",
        )


def _source_manifest_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        from leadtrace.ops.baseline.verify_manifest import verify_manifest

        manifest = Path(str(_required_config(config, "source_manifest", str))).resolve(
            strict=True
        )
        result = verify_manifest(manifest)
        if not result.ok:
            raise ValueError("source manifest changed")
        return CheckResult.passed(
            "source_manifest",
            "Approved production source manifest is unchanged",
            file_differences=0,
        )
    except Exception:
        return CheckResult.failed(
            "source_manifest",
            "Approved production source manifest is missing or changed",
        )


DEFAULT_PROBES = PreflightProbes(
    database=_database_probe,
    services=_services_probe,
    permissions=_permissions_probe,
    source_manifest=_source_manifest_probe,
)


def write_report(path: Path, payload: dict[str, object]) -> None:
    destination = path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
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
    parser = argparse.ArgumentParser(
        description="Run the LeadTrace production cutover preflight."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = json.loads(args.config.resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit("preflight config must contain a JSON object")
    report = run_preflight(config)
    payload = report.as_dict()
    if args.report:
        write_report(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
