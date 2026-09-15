from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.config import Settings
from app.database import DatabaseResources
from app.imports.approval import ImportCandidateApprovalService
from app.imports.reconcile import DEFAULT_EXPECTED_AGGREGATE
from app.imports.service import BaselineImporter
from app.main import create_app
from app.releases import router as releases_router
from app.releases.models import Release
from app.users.models import User
from app.users.models import UserRole
from app.users.service import UserService
PASSWORD = "Release route password 2026!"
pytest_plugins = ("tests.imports.conftest",)




@pytest.fixture
def release_api_client(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    workspace = baseline_fixture["workspace"]
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    assert isinstance(workspace, Path)
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    with auth_session_factory.begin() as session:
        for role in UserRole:
            user = UserService().create_user(
                session,
                username=f"release.{role.value}",
                display_name=f"Release {role.value}",
                role=role,
                initial_password=PASSWORD,
            )
            user.must_change_password = False
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="release-route-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "managed",
        source_roots={"baseline": workspace},
        baseline_import_root=source_root,
        baseline_source_manifest=manifest_path,
        baseline_expected_aggregate=DEFAULT_EXPECTED_AGGREGATE,
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        yield client


def _login(client: TestClient, role: UserRole) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"release.{role.value}", "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (None, 401),
        (UserRole.VISITOR, 403),
        (UserRole.REVIEWER, 403),
        (UserRole.ADMIN, 409),
    ],
)
def test_release_routes_enforce_admin_role_over_http(
    release_api_client: TestClient,
    role: UserRole | None,
    expected: int,
) -> None:
    client = release_api_client
    client.cookies.clear()
    csrf = _login(client, role) if role is not None else None
    headers = {
        "X-CSRF-Token": csrf or "anonymous",
        "Idempotency-Key": f"route-{role or 'anonymous'}",
    }
    target_id = uuid4()

    listing = client.get("/api/v1/releases")
    scientific_evidence = client.get(
        f"/api/v1/approvals/{target_id}/scientific-evidence"
    )
    preview = client.get(f"/api/v1/releases/preview/{target_id}")
    publish = client.post(
        "/api/v1/releases/publish",
        headers=headers,
        json={"changeset_id": str(target_id), "notes": "Route test"},
    )
    publish_baseline = client.post(
        "/api/v1/releases/publish-baseline",
        headers=headers,
        json={"candidate_id": str(target_id), "notes": "Route test"},
    )
    rollback = client.post(
        "/api/v1/releases/rollback",
        headers=headers,
        json={
            "target_release_id": str(target_id),
            "reason": "Route test rollback",
        },
    )
    backfill = client.post(
        "/api/v1/releases/backfill-machine-evidence",
        headers=headers,
        json={"source_fingerprint": "f" * 64, "notes": "Route test"},
    )

    if role is UserRole.ADMIN:
        assert listing.status_code == 200
    else:
        assert listing.status_code == expected
    assert preview.status_code == expected
    assert scientific_evidence.status_code == (404 if role is UserRole.ADMIN else expected)
    assert publish.status_code == expected
    assert publish_baseline.status_code == expected
    assert rollback.status_code == expected
    assert backfill.status_code == (404 if role is UserRole.ADMIN else expected)


def test_release_mutations_require_csrf_and_idempotency_key(
    release_api_client: TestClient,
) -> None:
    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)
    target_id = str(uuid4())
    payload = {
        "target_release_id": target_id,
        "reason": "Verify mutation protection",
    }

    missing_csrf = client.post(
        "/api/v1/releases/rollback",
        headers={"Idempotency-Key": "missing-csrf"},
        json=payload,
    )
    missing_idempotency = client.post(
        "/api/v1/releases/rollback",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    missing_baseline_csrf = client.post(
        "/api/v1/releases/publish-baseline",
        headers={"Idempotency-Key": "missing-baseline-csrf"},
        json={"candidate_id": target_id, "notes": "Protected baseline"},
    )
    missing_baseline_idempotency = client.post(
        "/api/v1/releases/publish-baseline",
        headers={"X-CSRF-Token": csrf},
        json={"candidate_id": target_id, "notes": "Protected baseline"},
    )
    missing_backfill_csrf = client.post(
        "/api/v1/releases/backfill-machine-evidence",
        headers={"Idempotency-Key": "missing-backfill-csrf"},
        json={"source_fingerprint": "f" * 64},
    )
    missing_backfill_idempotency = client.post(
        "/api/v1/releases/backfill-machine-evidence",
        headers={"X-CSRF-Token": csrf},
        json={"source_fingerprint": "f" * 64},
    )

    assert missing_csrf.status_code == 403
    assert missing_idempotency.status_code == 400
    assert missing_baseline_csrf.status_code == 403
    assert missing_baseline_idempotency.status_code == 400
    assert missing_backfill_csrf.status_code == 403
    assert missing_backfill_idempotency.status_code == 400


def test_machine_evidence_backfill_maps_source_failures_to_a_safe_422(
    release_api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "private-baseline-source"

    def fail_backfill(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(f"Cannot read {secret_path}")

    monkeypatch.setattr(releases_router, "backfill_machine_evidence", fail_backfill)
    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)

    response = client.post(
        "/api/v1/releases/backfill-machine-evidence",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "safe-backfill-source-error",
        },
        json={"source_fingerprint": "f" * 64},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MACHINE_EVIDENCE_BACKFILL_FAILED"
    assert str(tmp_path) not in response.text


def test_machine_evidence_backfill_uses_the_configured_import_root(
    release_api_client: TestClient,
    baseline_fixture: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = baseline_fixture["source_root"]
    assert isinstance(source_root, Path)
    received: dict[str, object] = {}

    def capture_backfill(*args: object, **kwargs: object) -> None:
        del args
        received.update(kwargs)
        raise ValueError("stop after capturing the configured source root")

    monkeypatch.setattr(releases_router, "backfill_machine_evidence", capture_backfill)
    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)

    response = client.post(
        "/api/v1/releases/backfill-machine-evidence",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "configured-backfill-import-root",
        },
        json={"source_fingerprint": "f" * 64},
    )

    assert response.status_code == 422
    assert received["source_root"] == source_root
    assert received["source_manifest_path"] == baseline_fixture["manifest_path"]
    assert received["expected_path"] == DEFAULT_EXPECTED_AGGREGATE


def test_publish_baseline_route_is_idempotent_and_writes_corpus_audit_once(
    release_api_client: TestClient,
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    with auth_session_factory.begin() as session:
        imported = BaselineImporter(
            source_root,
            managed_asset_root=tmp_path / "managed",
            expected=expected,
            source_manifest_path=manifest_path,
        ).apply(session)
        admin = session.scalar(
            select(User).where(User.normalized_username == "release.admin")
        )
        assert admin is not None
        ImportCandidateApprovalService().decide(
            session,
            candidate_id=imported.release_candidate_id,
            actor_id=admin.id,
            action="approve",
            reason="Approve candidate for route publication test",
        )
        candidate_id = imported.release_candidate_id

    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)
    headers = {
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "route-baseline-publish",
    }
    request = {
        "candidate_id": str(candidate_id),
        "title": "Route baseline",
        "notes": "Publish the reviewed initial corpus",
    }
    first = client.post(
        "/api/v1/releases/publish-baseline",
        headers=headers,
        json=request,
    )
    retry = client.post(
        "/api/v1/releases/publish-baseline",
        headers=headers,
        json=request,
    )
    conflict = client.post(
        "/api/v1/releases/publish-baseline",
        headers=headers,
        json={**request, "title": "Conflicting title"},
    )

    assert first.status_code == 200, first.text
    assert first.json()["idempotent"] is False
    assert first.json()["validation"]["valid"] is True
    assert retry.status_code == 200
    assert retry.json()["release_id"] == first.json()["release_id"]
    assert retry.json()["operation_id"] == first.json()["operation_id"]
    assert retry.json()["idempotent"] is True
    assert conflict.status_code == 409
    assert str(tmp_path) not in first.text
    assert "password" not in first.text.casefold()

    with auth_session_factory() as session:
        release = session.get(Release, first.json()["release_id"])
        assert release is not None
        assert release.is_current is True
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "release.baseline_published"
                )
            )
        )
        assert len(events) == 1
        assert events[0].paper_id is None
        assert events[0].release_id == release.id


def test_publish_baseline_route_maps_asset_validation_to_safe_422(
    release_api_client: TestClient,
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory: sessionmaker[Session],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    crop = baseline_fixture["crop"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    assert isinstance(crop, Path)
    with auth_session_factory.begin() as session:
        imported = BaselineImporter(
            source_root,
            managed_asset_root=tmp_path / "managed",
            expected=expected,
            source_manifest_path=manifest_path,
        ).apply(session)
        admin = session.scalar(
            select(User).where(User.normalized_username == "release.admin")
        )
        assert admin is not None
        ImportCandidateApprovalService().decide(
            session,
            candidate_id=imported.release_candidate_id,
            actor_id=admin.id,
            action="approve",
            reason="Approve candidate before asset failure",
        )
        candidate_id = imported.release_candidate_id
    crop.unlink()

    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)
    response = client.post(
        "/api/v1/releases/publish-baseline",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "route-invalid-baseline-asset",
        },
        json={"candidate_id": str(candidate_id), "notes": "Must fail safely"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "RELEASE_VALIDATION_FAILED"
    assert str(tmp_path) not in response.text
    with auth_session_factory() as session:
        assert session.scalar(select(Release)) is None
