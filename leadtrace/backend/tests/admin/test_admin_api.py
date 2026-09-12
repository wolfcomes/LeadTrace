from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.config import Settings
from app.database import DatabaseResources
from app.jobs.models import CropJob, CropJobStatus
from app.main import create_app
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Admin API password 2026!"


def _client(
    tmp_path: Path,
    database_url: str,
    factory: sessionmaker[Session],
) -> TestClient:
    with factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="admin.console",
            display_name="Admin Console",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="admin-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "assets",
    )
    resources = DatabaseResources(
        engine=factory.kw["bind"],
        session_factory=factory,
    )
    return TestClient(
        create_app(
            settings=settings,
            database_probe=lambda _: True,
            database_bootstrap=lambda _: resources,
        )
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.console", "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_admin_system_endpoint_returns_structured_checks_without_secrets(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with _client(tmp_path, empty_postgresql_database_url, auth_session_factory) as client:
        _login(client)
        response = client.get("/api/v1/admin/system")

    assert response.status_code == 200
    payload = response.json()
    assert {"status", "checks", "request_id"} <= payload.keys()
    assert {"database", "storage", "worker", "disk", "backup", "schema", "release"} <= payload["checks"].keys()
    assert "postgresql://" not in response.text
    assert str(tmp_path) not in response.text
    assert "secret" not in response.text.casefold()


def test_admin_asset_reverse_references_include_integrity_and_no_absolute_paths(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        asset = Asset(
            storage_key="imports/article.pdf",
            original_filename="article.pdf",
            sha256="a" * 64,
            byte_size=12,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(asset)
        session.flush()
        asset_id = asset.id

    with _client(tmp_path, empty_postgresql_database_url, auth_session_factory) as client:
        _login(client)
        response = client.get(f"/api/v1/admin/files/{asset_id}/references")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["id"] == str(asset_id)
    assert payload["asset"]["integrity"] == "verified"
    assert "storage_key" not in payload["asset"]
    assert "references" in payload
    assert str(tmp_path) not in response.text


def test_admin_failed_job_retry_reuses_idempotency_key(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        job = CropJob(
            input_hash="b" * 64,
            source_pdf_sha256="c" * 64,
            page_number=1,
            x0=0.1,
            y0=0.1,
            x1=0.9,
            y1=0.9,
            rotation=0,
            padding=0,
            dpi=200,
            renderer_version="test",
            status=CropJobStatus.FAILED,
            error_message="render failed",
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with _client(tmp_path, empty_postgresql_database_url, auth_session_factory) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "retry-001"}
        first = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
        second = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"] == str(job_id)
    assert first.json()["status"] == "pending"


def test_admin_audit_endpoint_supports_action_and_actor_filters(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with _client(tmp_path, empty_postgresql_database_url, auth_session_factory) as client:
        _login(client)
        response = client.get(
            "/api/v1/admin/audit",
            params={"action": "publish", "actor_id": str(uuid4())},
        )

    assert response.status_code == 200
    assert response.json() == []
