from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from leadtrace.ops.cutover.preflight import (
    CheckResult,
    PreflightProbes,
    _services_probe,
    run_preflight,
)
from leadtrace.ops.cutover.smoke_test import run_smoke_test
from leadtrace.ops.restore.verify_restored_system import build_backup_evidence


def _write_backup(
    root: Path,
    *,
    backup_id: str,
    scope: str,
    now: datetime,
) -> Path:
    if scope == "assets":
        root = root.parent / backup_id
    root.mkdir()
    names = {
        "database": {"database_dump": "database.dump.age"},
        "assets": {
            "asset_manifest": "assets.manifest.json",
            "asset_archive": "assets.tar.age",
            "asset_snapshot": "tar.snapshot",
        },
    }[scope]
    artifacts: dict[str, dict[str, object]] = {}
    for artifact_name, filename in names.items():
        content = f"{backup_id}:{artifact_name}".encode()
        (root / filename).write_bytes(content)
        artifacts[artifact_name] = {
            "path": filename,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    payload = {
        "schema_version": 1,
        "backup_id": backup_id,
        "backup_scope": scope,
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "completed_at": now.isoformat(),
        "outcome": "success",
        "versions": {"application": "0.1.0", "schema": "0015", "release": "r1"},
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:key",
            "payloads_encrypted": True,
        },
        "destination": {"kind": "separate_disk", "identity": "disk-a"},
        "artifacts": artifacts,
    }
    if scope == "assets":
        payload["asset_chain"] = {
            "mode": "full",
            "parent_backup_id": None,
            "position": 0,
        }
    metadata = root / "backup-metadata.json"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    return metadata


def _restore_evidence(database_metadata: Path, asset_metadata: Path) -> dict[str, object]:
    return build_backup_evidence(database_metadata, asset_metadata)


def _complete_restore_report(
    *,
    now: datetime,
    database_metadata: Path,
    asset_metadata: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": True,
        "assets": {"ok": True, "file_count": 1, "errors": []},
        "baseline": {"ok": True, "counts": {}, "integrity": {}},
        "http": {"ok": True, "checks": {}},
        "started_at": (now - timedelta(minutes=5)).isoformat(),
        "completed_at": now.isoformat(),
        "duration_seconds": 300,
        "rto": {"target_seconds": 3600, "met": True},
        "errors": [],
        "backup_evidence": _restore_evidence(database_metadata, asset_metadata),
    }


def test_preflight_aggregates_required_evidence_into_machine_readable_report(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-1", scope="database", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets", backup_id="assets-1", scope="assets", now=now
    )
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_text(
        json.dumps(
            _complete_restore_report(
                now=now,
                database_metadata=database_backup,
                asset_metadata=asset_backup,
            )
        ),
        encoding="utf-8",
    )
    config = {
        "schema_version": 1,
        "application_version": "0.1.0",
        "schema_revision": "0015",
        "release_key": "r1",
        "database_backup_metadata": str(database_backup),
        "asset_backup_metadata": str(asset_backup),
        "restore_report": str(restore_report),
        "max_backup_age_hours": 4,
        "max_restore_age_days": 31,
    }
    probes = PreflightProbes(
        database=lambda _: CheckResult.passed("database", "database evidence matches"),
        services=lambda _: CheckResult.passed("services", "services ready"),
        permissions=lambda _: CheckResult.passed("permissions", "role matrix passed"),
        source_manifest=lambda _: CheckResult.passed(
            "source_manifest", "source unchanged"
        ),
    )

    report = run_preflight(config, probes=probes, now=now)

    assert report.ok is True
    assert report.as_dict()["status"] == "PASS"
    assert {check.name for check in report.checks} == {
        "asset_backup",
        "database",
        "database_backup",
        "permissions",
        "restore_drill",
        "services",
        "source_manifest",
    }


def test_preflight_fails_closed_when_restore_drill_is_stale(tmp_path: Path) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-1", scope="database", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets", backup_id="assets-1", scope="assets", now=now
    )
    restore_report = tmp_path / "restore-report.json"
    payload = _complete_restore_report(
        now=now - timedelta(days=32),
        database_metadata=database_backup,
        asset_metadata=asset_backup,
    )
    restore_report.write_text(json.dumps(payload), encoding="utf-8")
    config = {
        "schema_version": 1,
        "application_version": "0.1.0",
        "schema_revision": "0015",
        "release_key": "r1",
        "database_backup_metadata": str(database_backup),
        "asset_backup_metadata": str(asset_backup),
        "restore_report": str(restore_report),
        "max_backup_age_hours": 4,
        "max_restore_age_days": 31,
    }

    def passed(name: str) -> CheckResult:
        return CheckResult.passed(name, "ok")

    probes = PreflightProbes(
        database=lambda _: passed("database"),
        services=lambda _: passed("services"),
        permissions=lambda _: passed("permissions"),
        source_manifest=lambda _: passed("source_manifest"),
    )

    report = run_preflight(config, probes=probes, now=now)

    assert report.ok is False
    stale = next(check for check in report.checks if check.name == "restore_drill")
    assert stale.status == "FAIL"
    assert "stale" in stale.summary.casefold()


@pytest.mark.parametrize(
    ("section", "replacement"),
    [
        ("assets", None),
        ("assets", {"ok": False, "errors": ["asset_hash_mismatch"]}),
        ("baseline", None),
        ("baseline", {"ok": False, "error": "database_baseline_mismatch"}),
        ("http", None),
        ("http", {"ok": False, "error": "http_smoke_failed"}),
    ],
)
def test_preflight_rejects_incomplete_or_failed_restore_child_checks(
    tmp_path: Path,
    section: str,
    replacement: dict[str, object] | None,
) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-1", scope="database", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets", backup_id="assets-1", scope="assets", now=now
    )
    payload = _complete_restore_report(
        now=now,
        database_metadata=database_backup,
        asset_metadata=asset_backup,
    )
    if replacement is None:
        payload.pop(section)
    else:
        payload[section] = replacement
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_text(json.dumps(payload), encoding="utf-8")

    report = run_preflight(
        {
            "schema_version": 1,
            "application_version": "0.1.0",
            "schema_revision": "0015",
            "release_key": "r1",
            "database_backup_metadata": str(database_backup),
            "asset_backup_metadata": str(asset_backup),
            "restore_report": str(restore_report),
            "max_backup_age_hours": 4,
            "max_restore_age_days": 31,
        },
        probes=PreflightProbes(
            database=lambda _: CheckResult.passed("database", "ok"),
            services=lambda _: CheckResult.passed("services", "ok"),
            permissions=lambda _: CheckResult.passed("permissions", "ok"),
            source_manifest=lambda _: CheckResult.passed("source_manifest", "ok"),
        ),
        now=now,
    )

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "FAIL"


@pytest.mark.parametrize(
    ("updates", "label"),
    [
        ({"duration_seconds": 299}, "duration"),
        ({"started_at": "2026-09-12T12:01:00Z"}, "timestamp order"),
        ({"rto": {"target_seconds": 299, "met": True}}, "RTO result"),
    ],
)
def test_preflight_rejects_internally_inconsistent_restore_timing(
    tmp_path: Path,
    updates: dict[str, object],
    label: str,
) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-1", scope="database", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets", backup_id="assets-1", scope="assets", now=now
    )
    payload = _complete_restore_report(
        now=now,
        database_metadata=database_backup,
        asset_metadata=asset_backup,
    )
    payload.update(updates)
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_text(json.dumps(payload), encoding="utf-8")

    report = run_preflight(
        {
            "schema_version": 1,
            "application_version": "0.1.0",
            "schema_revision": "0015",
            "release_key": "r1",
            "database_backup_metadata": str(database_backup),
            "asset_backup_metadata": str(asset_backup),
            "restore_report": str(restore_report),
            "max_backup_age_hours": 4,
            "max_restore_age_days": 31,
        },
        probes=PreflightProbes(
            database=lambda _: CheckResult.passed("database", "ok"),
            services=lambda _: CheckResult.passed("services", "ok"),
            permissions=lambda _: CheckResult.passed("permissions", "ok"),
            source_manifest=lambda _: CheckResult.passed("source_manifest", "ok"),
        ),
        now=now,
    )

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "FAIL", label


def test_preflight_rejects_restore_evidence_for_different_backups(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-current", scope="database", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets", backup_id="assets-current", scope="assets", now=now
    )
    payload = _complete_restore_report(
        now=now,
        database_metadata=database_backup,
        asset_metadata=asset_backup,
    )
    payload["backup_evidence"] = {
        "database": {
            "backup_id": "db-older",
            "metadata_sha256": "a" * 64,
            "versions": {
                "application": "0.1.0",
                "schema": "0015",
                "release": "r1",
            },
        },
        "assets": {
            "backup_id": "assets-older",
            "metadata_sha256": "b" * 64,
            "chain_backup_ids": ["assets-older"],
            "versions": {
                "application": "0.1.0",
                "schema": "0015",
                "release": "r1",
            },
        },
    }
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_text(json.dumps(payload), encoding="utf-8")
    config = {
        "schema_version": 1,
        "application_version": "0.1.0",
        "schema_revision": "0015",
        "release_key": "r1",
        "database_backup_metadata": str(database_backup),
        "asset_backup_metadata": str(asset_backup),
        "restore_report": str(restore_report),
        "max_backup_age_hours": 4,
        "max_restore_age_days": 31,
    }

    def passed(name: str) -> CheckResult:
        return CheckResult.passed(name, "ok")

    report = run_preflight(
        config,
        probes=PreflightProbes(
            database=lambda _: passed("database"),
            services=lambda _: passed("services"),
            permissions=lambda _: passed("permissions"),
            source_manifest=lambda _: passed("source_manifest"),
        ),
        now=now,
    )

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "FAIL"
    assert "backup" in restore.summary.casefold()


def test_preflight_rejects_restore_evidence_for_a_different_asset_chain(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    database_backup = _write_backup(
        tmp_path / "database", backup_id="db-current", scope="database", now=now
    )
    _write_backup(
        tmp_path / "assets-full", backup_id="assets-full", scope="assets", now=now
    )
    asset_backup = _write_backup(
        tmp_path / "assets-current",
        backup_id="assets-current",
        scope="assets",
        now=now,
    )
    incremental = json.loads(asset_backup.read_text(encoding="utf-8"))
    incremental["asset_chain"] = {
        "mode": "incremental",
        "parent_backup_id": "assets-full",
        "position": 1,
    }
    asset_backup.write_text(json.dumps(incremental), encoding="utf-8")

    evidence = build_backup_evidence(database_backup, asset_backup)
    asset_evidence = evidence["assets"]
    assert isinstance(asset_evidence, dict)
    asset_evidence["chain_backup_ids"] = ["forged-parent", "assets-current"]
    payload = _complete_restore_report(
        now=now,
        database_metadata=database_backup,
        asset_metadata=asset_backup,
    )
    payload["backup_evidence"] = evidence
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_text(json.dumps(payload), encoding="utf-8")
    config = {
        "schema_version": 1,
        "application_version": "0.1.0",
        "schema_revision": "0015",
        "release_key": "r1",
        "database_backup_metadata": str(database_backup),
        "asset_backup_metadata": str(asset_backup),
        "restore_report": str(restore_report),
        "max_backup_age_hours": 4,
        "max_restore_age_days": 31,
    }

    def passed(name: str) -> CheckResult:
        return CheckResult.passed(name, "ok")

    report = run_preflight(
        config,
        probes=PreflightProbes(
            database=lambda _: passed("database"),
            services=lambda _: passed("services"),
            permissions=lambda _: passed("permissions"),
            source_manifest=lambda _: passed("source_manifest"),
        ),
        now=now,
    )

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "FAIL"
    assert "backup" in restore.summary.casefold()


def test_cutover_smoke_report_requires_new_site_and_read_only_fallback() -> None:
    requested: list[tuple[str, str]] = []

    class Response:
        def __init__(
            self, status_code: int, payload: dict[str, object] | None = None
        ) -> None:
            self.status_code = status_code
            self._payload = payload or {}

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def __init__(self, *, role: str | None = None) -> None:
            self.role = role

        def get(self, path: str) -> Response:
            requested.append(("GET", path))
            if path == "/health/live" or path == "/health/ready":
                return Response(200)
            if path == "/api/v1/published/overview":
                return Response(200, {"release": {"key": "release-1"}})
            if path == "/legacy-dashboard/":
                return Response(200)
            if path.endswith("/source-pdf"):
                return Response(403 if self.role == "visitor" else 206)
            if path == "/api/v1/users":
                return Response(200 if self.role == "admin" else 403)
            if path == "/api/v1/releases":
                return Response(200 if self.role == "admin" else 403)
            if path == "/api/v1/audit/verify":
                return Response(200, {"valid": True})
            return Response(200)

        def post(self, path: str, **_: object) -> Response:
            requested.append(("POST", path))
            if path == "/legacy-dashboard/":
                return Response(405)
            return Response(200, {"csrf_token": "smoke-csrf"})

    clients = {
        None: Client(),
        "visitor": Client(role="visitor"),
        "reviewer": Client(role="reviewer"),
        "admin": Client(role="admin"),
    }

    report = run_smoke_test(
        {
            "schema_version": 1,
            "release_key": "release-1",
            "representative_paper_id": "paper-1",
        },
        clients=clients,
        credentials={
            "visitor": ("visitor", "password"),
            "reviewer": ("reviewer", "password"),
            "admin": ("admin", "password"),
        },
    )

    assert report.ok is True
    assert report.as_dict()["status"] == "PASS"
    assert ("GET", "/legacy-dashboard/") in requested
    assert ("POST", "/legacy-dashboard/") in requested


@pytest.mark.parametrize(
    ("worker_reply", "expected_status"),
    [({}, "FAIL"), ({"celery@leadtrace": {"ok": "pong"}}, "PASS")],
)
def test_services_probe_requires_a_responsive_celery_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    worker_reply: dict[str, dict[str, str]],
    expected_status: str,
) -> None:
    class Response:
        status_code = 200

    class Client:
        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, _: str) -> Response:
            return Response()

    class RedisClient:
        @staticmethod
        def from_url(_: str) -> SimpleNamespace:
            return SimpleNamespace(ping=lambda: True)

    inspector = SimpleNamespace(ping=lambda: worker_reply)
    celery_app = SimpleNamespace(
        control=SimpleNamespace(inspect=lambda **_: inspector),
    )
    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(Client=lambda **_: Client())
    )
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=RedisClient))
    monkeypatch.setitem(
        sys.modules, "app.worker", SimpleNamespace(celery_app=celery_app)
    )
    monkeypatch.setenv("LEADTRACE_REDIS_URL", "redis://127.0.0.1:6379/0")

    result = _services_probe(
        {
            "asset_root": str(tmp_path),
            "base_url": "https://leadtrace.lan:8876",
            "old_dashboard_url": "https://leadtrace.lan:8876/legacy-dashboard",
        }
    )

    assert result.status == expected_status


def test_services_probe_requires_writable_asset_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Response:
        status_code = 200

    class Client:
        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, _: str) -> Response:
            return Response()

    class RedisClient:
        @staticmethod
        def from_url(_: str) -> SimpleNamespace:
            return SimpleNamespace(ping=lambda: True)

    inspector = SimpleNamespace(ping=lambda: {"worker": {"ok": "pong"}})
    celery_app = SimpleNamespace(
        control=SimpleNamespace(inspect=lambda **_: inspector),
    )
    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(Client=lambda **_: Client())
    )
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=RedisClient))
    monkeypatch.setitem(
        sys.modules, "app.worker", SimpleNamespace(celery_app=celery_app)
    )
    monkeypatch.setenv("LEADTRACE_REDIS_URL", "redis://127.0.0.1:6379/0")
    read_execute = os.R_OK | os.X_OK
    monkeypatch.setattr(os, "access", lambda _path, mode: mode == read_execute)

    result = _services_probe(
        {
            "asset_root": str(tmp_path),
            "base_url": "https://127.0.0.1:8877",
            "old_dashboard_url": "http://127.0.0.1:8765",
        }
    )

    assert result.status == "FAIL"


@pytest.mark.parametrize(
    "script",
    [
        "leadtrace/ops/cutover/preflight.py",
        "leadtrace/ops/cutover/smoke_test.py",
    ],
)
def test_cutover_scripts_support_direct_command_line_execution(script: str) -> None:
    repository_root = Path(__file__).parents[4]

    result = subprocess.run(
        [sys.executable, str(repository_root / script), "--help"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_nginx_keeps_old_dashboard_on_a_read_only_fallback_route() -> None:
    deploy_root = Path(__file__).parents[3] / "deploy"
    nginx = (deploy_root / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    compose = (deploy_root / "compose.yaml").read_text(encoding="utf-8")

    assert "location /legacy-dashboard/" in nginx
    assert "limit_except GET" in nginx
    assert "proxy_pass http://host.docker.internal:8765/;" in nginx
    assert "host.docker.internal:host-gateway" in compose


def test_cutover_artifacts_require_explicit_evidence_and_native_fallback() -> None:
    repository_root = Path(__file__).parents[4]
    cutover = (repository_root / "leadtrace/ops/runbooks/cutover.md").read_text(
        encoding="utf-8"
    )
    rollback = (
        repository_root / "leadtrace/ops/runbooks/rollback-cutover.md"
    ).read_text(encoding="utf-8")
    acceptance = (repository_root / "docs/acceptance/leadtrace-release-1.md").read_text(
        encoding="utf-8"
    )
    native_nginx = (
        repository_root / "leadtrace/deploy/nginx/nginx.native.conf"
    ).read_text(encoding="utf-8")
    native_fallback_nginx = (
        repository_root / "leadtrace/deploy/nginx/nginx.native-fallback.conf"
    ).read_text(encoding="utf-8")
    native_preflight_nginx = (
        repository_root / "leadtrace/deploy/nginx/nginx.native-preflight.conf"
    ).read_text(encoding="utf-8")
    example = json.loads(
        (repository_root / "leadtrace/ops/cutover/preflight.example.json").read_text(
            encoding="utf-8"
        )
    )

    for required in (
        "maintenance",
        "/api/v1/admin/maintenance",
        "backup_postgres.sh",
        "backup_assets.sh",
        "preflight.py",
        "smoke_test.py",
        "nginx -t",
        "read-only",
        "--read-only",
        "rollback-cutover.md",
        "nginx.native-preflight.conf",
    ):
        assert required in cutover
    build = cutover.index("## Build and stage")
    loopback_listener = cutover.index("## Install the loopback TLS preflight listener")
    rollback_backup = cutover.index("## Enter maintenance and take rollback backups")
    final_import = cutover.index("## Apply the final import and validate")
    candidate_restore = cutover.index("## Back up and restore the cutover candidate")
    preflight = cutover.index("## Preflight the staged candidate")
    route_switch = cutover.index("## Switch the primary route")
    assert (
        build
        < loopback_listener
        < rollback_backup
        < final_import
        < candidate_restore
        < preflight
        < route_switch
    )
    assert "restore_drill.sh" in cutover[candidate_restore:preflight]
    assert "selected candidate backup IDs" in cutover[candidate_restore:preflight]
    for required in ("preserve", "new revisions", "read-only", "smoke_test.py"):
        assert required in rollback
    for required in (
        "Batch 01",
        "Batch 02",
        "Batch 03",
        "Batch 04",
        "Batch 05",
        "Batch 06",
        "multiple roots",
        "branches",
        "unresolved parent",
        "racemate",
        "multicomponent material",
        "source mismatch",
        "prime label",
        "one-image/many-label",
        "multiple sources",
        "no pair-ready edge",
        "rich activity",
        "Role-based UAT | NOT_RUN",
        "Backup and restore evidence | NOT_RUN",
        "Internal CA and LAN TLS | NOT_RUN",
        "Primary-route cutover | NOT_RUN",
        "Fallback exercise | NOT_RUN",
        "Return to LeadTrace and repeat smoke | NOT_RUN",
    ):
        assert required in acceptance
    assert example["application_version"] == "0.1.0"
    assert example["schema_revision"] == "0015_crop_job_subscriptions"
    assert example["base_url"] == "https://127.0.0.1:8877"
    assert example["old_dashboard_url"] == "http://127.0.0.1:8765"
    assert "listen 8876 ssl;" in native_nginx
    assert "proxy_pass http://127.0.0.1:8000;" in native_nginx
    assert "root /srv/leadtrace/current-frontend;" in native_nginx
    assert "127.0.0.1:5173" not in native_nginx
    assert "location /legacy-dashboard/" in native_nginx
    assert "limit_except GET" in native_nginx
    assert "proxy_pass http://127.0.0.1:8765;" in native_fallback_nginx
    assert "limit_except GET" in native_fallback_nginx
    assert "listen 127.0.0.1:8877 ssl;" in native_preflight_nginx
    assert "proxy_pass http://127.0.0.1:8000;" in native_preflight_nginx
