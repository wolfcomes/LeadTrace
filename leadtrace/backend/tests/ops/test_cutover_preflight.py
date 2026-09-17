from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from leadtrace.ops.cutover.preflight import _permissions_probe, _services_probe
from leadtrace.ops.cutover.smoke_test import run_smoke_test


def test_cutover_smoke_report_uses_paper_centric_routes_and_read_only_fallback() -> None:
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
            if path in {"/health/live", "/health/ready"}:
                return Response(200)
            if path == "/legacy-dashboard/":
                return Response(200)
            if path.endswith("/source-pdf"):
                return Response(403 if self.role == "visitor" else 206)
            if path == "/api/v1/users":
                return Response(200 if self.role == "admin" else 403)
            if path.startswith("/api/v2/admin/papers"):
                return Response(200 if self.role == "admin" else 403)
            if path == "/api/v2/admin/submissions":
                return Response(200 if self.role == "admin" else 403)
            if path == "/api/v1/audit/verify":
                return Response(200, {"valid": True})
            if path.startswith("/api/v2/papers"):
                return Response(200)
            return Response(404)

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
        {"schema_version": 2, "representative_paper_id": "paper-1"},
        clients=clients,
        credentials={
            "visitor": ("visitor", "password"),
            "reviewer": ("reviewer", "password"),
            "admin": ("admin", "password"),
        },
    )

    assert report.ok is True
    assert report.as_dict()["status"] == "PASS"
    assert ("GET", "/api/v2/papers?page=1&page_size=1") in requested
    assert ("GET", "/api/v2/admin/submissions") in requested
    assert all("releases" not in path for _, path in requested)
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


@pytest.mark.parametrize("visitor_draft_status", [403, 404])
def test_permissions_probe_checks_unassigned_pdf_and_draft_isolation(
    monkeypatch: pytest.MonkeyPatch,
    visitor_draft_status: int,
) -> None:
    requested: list[tuple[str, str]] = []

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object] | None = None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        role: str | None = None

        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, path: str, json: dict[str, str]) -> Response:
            del json
            requested.append(("POST", path))
            self.role = ["visitor", "reviewer", "admin"][
                sum(1 for method, route in requested if method == "POST") - 1
            ]
            return Response(200, {"csrf_token": "csrf"})

        def get(self, path: str) -> Response:
            requested.append(("GET", path))
            if path.endswith("/unassigned/source-pdf"):
                return Response(404)
            if self.role == "visitor" and path.endswith("/source-pdf"):
                return Response(403)
            if path.endswith("/draft-workspace"):
                return Response(
                    visitor_draft_status if self.role == "visitor" else 200
                )
            if path == "/api/v1/users":
                return Response(200 if self.role == "admin" else 403)
            if path.startswith("/api/v2/admin/"):
                return Response(200 if self.role == "admin" else 403)
            return Response(200)

    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(Client=lambda **kwargs: Client(**kwargs))
    )
    for role in ("VISITOR", "REVIEWER", "ADMIN"):
        monkeypatch.setenv(f"LEADTRACE_PREFLIGHT_{role}_USERNAME", role.casefold())
        monkeypatch.setenv(f"LEADTRACE_PREFLIGHT_{role}_PASSWORD", "protected")

    result = _permissions_probe(
        {
            "base_url": "https://leadtrace.invalid",
            "representative_paper_id": "published",
            "unassigned_paper_id": "unassigned",
            "draft_workspace_id": "draft-workspace",
        }
    )

    assert result.status == "PASS"
    assert ("GET", "/api/v2/papers/unassigned/source-pdf") in requested
    assert ("GET", "/api/v2/workspaces/draft-workspace") in requested


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


def test_preflight_example_uses_paper_centric_evidence() -> None:
    repository_root = Path(__file__).parents[4]
    example = json.loads(
        (repository_root / "leadtrace/ops/cutover/preflight.example.json").read_text(
            encoding="utf-8"
        )
    )

    assert example["schema_version"] == 2
    assert example["schema_revision"] == "0025_ai_prefill_runs"
    assert example["backup_version_marker"] == "paper-centric-pilot"
    assert "release_key" not in example
    assert example["pilot_manifest"].endswith("volume67-issue5-first20.json")
    assert example["acceptance_evidence"].endswith("acceptance-evidence.json")
    assert example["visual_acceptance_report"].endswith("visual-acceptance.json")
    assert example["unassigned_paper_id"] == "TO_BE_REPLACED_WITH_UNASSIGNED_PAPER_UUID"
    assert example["draft_workspace_id"] == "TO_BE_REPLACED_WITH_DRAFT_WORKSPACE_UUID"
    assert example["restore_expected_aggregate"].endswith(
        "restore-expected-aggregate.json"
    )
    assert set(example["source_roots"]) == {"source_pdfs"}


def test_cutover_runbook_gates_live_migration_after_preflight() -> None:
    repository_root = Path(__file__).parents[4]
    runbook = (
        repository_root / "leadtrace/ops/runbooks/cutover.md"
    ).read_text(encoding="utf-8")

    assert "import_baseline" not in runbook
    assert "current Release validation" not in runbook
    assert "Never run Alembic against the currently routed database" in runbook
    assert "LEADTRACE_CANDIDATE_DATABASE_URL" in runbook
    assert runbook.index("preflight.py") < runbook.index("## Switch the primary route")
    assert "explicitly approved maintenance window" in runbook
