from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from leadtrace.ops.cutover.preflight import (  # noqa: E402
    CheckResult,
    PreflightReport,
    write_report,
)


def _login(client: object, credentials: tuple[str, str]) -> bool:
    username, password = credentials
    if not username or not password:
        return False
    response = client.post(  # type: ignore[attr-defined]
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    return response.status_code == 200


def _check(name: str, passed: bool, success: str, failure: str) -> CheckResult:
    if passed:
        return CheckResult.passed(name, success)
    return CheckResult.failed(name, failure)


def run_smoke_test(
    config: Mapping[str, object],
    *,
    clients: Mapping[str | None, object] | None = None,
    credentials: Mapping[str, tuple[str, str]] | None = None,
) -> PreflightReport:
    if config.get("schema_version") != 2:
        raise ValueError("unsupported smoke-test configuration schema version")
    paper_id = str(config.get("representative_paper_id") or "").strip()
    if not paper_id:
        raise ValueError("representative_paper_id is required")

    owned_clients: list[object] = []
    active_clients = clients
    if active_clients is None:
        import httpx

        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url.startswith("https://"):
            raise ValueError("smoke-test base_url must use HTTPS")
        created = {
            role: httpx.Client(
                base_url=base_url,
                timeout=5.0,
                follow_redirects=False,
            )
            for role in (None, "visitor", "reviewer", "admin")
        }
        active_clients = created
        owned_clients.extend(created.values())
    active_credentials = credentials or {
        role: (
            os.environ.get(f"LEADTRACE_SMOKE_{role.upper()}_USERNAME", ""),
            os.environ.get(f"LEADTRACE_SMOKE_{role.upper()}_PASSWORD", ""),
        )
        for role in ("visitor", "reviewer", "admin")
    }

    anonymous = active_clients[None]
    visitor = active_clients["visitor"]
    reviewer = active_clients["reviewer"]
    admin = active_clients["admin"]
    checks: list[CheckResult] = []
    try:
        health_ok = (
            anonymous.get("/health/live").status_code == 200  # type: ignore[attr-defined]
            and anonymous.get("/health/ready").status_code == 200  # type: ignore[attr-defined]
        )
        checks.append(
            _check(
                "health",
                health_ok,
                "New LeadTrace route is ready",
                "New LeadTrace route is unavailable",
            )
        )
        fallback_read = anonymous.get("/legacy-dashboard/")  # type: ignore[attr-defined]
        fallback_write = anonymous.post("/legacy-dashboard/")  # type: ignore[attr-defined]
        checks.append(
            _check(
                "legacy_fallback",
                fallback_read.status_code == 200
                and fallback_write.status_code in {403, 405},
                "Old Dashboard fallback is available read-only",
                "Old Dashboard fallback is unavailable or writable",
            )
        )

        visitor_login = _login(visitor, active_credentials["visitor"])
        visitor_ok = (
            visitor_login
            and visitor.get("/api/v2/papers?page=1&page_size=1").status_code == 200  # type: ignore[attr-defined]
            and visitor.get(f"/api/v2/papers/{paper_id}").status_code == 200  # type: ignore[attr-defined]
            and visitor.get(f"/api/v2/papers/{paper_id}/source-pdf").status_code  # type: ignore[attr-defined]
            in {403, 404}
            and visitor.get("/api/v1/users").status_code == 403  # type: ignore[attr-defined]
        )
        checks.append(
            _check(
                "visitor",
                visitor_ok,
                "Visitor reads the published Paper without privileged access",
                "Visitor smoke test failed",
            )
        )

        reviewer_login = _login(reviewer, active_credentials["reviewer"])
        reviewer_ok = (
            reviewer_login
            and reviewer.get(f"/api/v2/papers/{paper_id}/source-pdf").status_code  # type: ignore[attr-defined]
            in {200, 206}
            and reviewer.get("/api/v1/users").status_code == 403  # type: ignore[attr-defined]
            and reviewer.get("/api/v2/admin/papers?page=1&page_size=1").status_code  # type: ignore[attr-defined]
            == 403
        )
        checks.append(
            _check(
                "reviewer",
                reviewer_ok,
                "Reviewer can read assigned source and cannot administer",
                "Reviewer smoke test failed",
            )
        )

        admin_login = _login(admin, active_credentials["admin"])
        audit = admin.get("/api/v1/audit/verify")  # type: ignore[attr-defined]
        admin_ok = (
            admin_login
            and admin.get("/api/v1/users").status_code == 200  # type: ignore[attr-defined]
            and admin.get("/api/v2/admin/papers?page=1&page_size=1").status_code  # type: ignore[attr-defined]
            == 200
            and admin.get("/api/v2/admin/submissions").status_code == 200  # type: ignore[attr-defined]
            and audit.status_code == 200
            and audit.json().get("valid") is True
        )
        checks.append(
            _check(
                "admin",
                admin_ok,
                "Admin routes and audit chain are readable",
                "Admin smoke test failed",
            )
        )
    except Exception:
        checks.append(
            CheckResult.failed("execution", "Smoke-test request failed safely")
        )
    finally:
        for client in owned_clients:
            client.close()  # type: ignore[attr-defined]
    return PreflightReport(datetime.now(UTC), tuple(checks))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LeadTrace post-cutover smoke tests."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = json.loads(args.config.resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit("smoke-test config must contain a JSON object")
    report = run_smoke_test(config)
    payload = report.as_dict()
    if args.report:
        write_report(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
