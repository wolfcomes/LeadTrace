from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.audit.service import AuditService, canonical_content_hash
from app.config import Settings
from app.database import DatabaseResources
from app.jobs.models import CropJob, CropJobStatus
from app.main import create_app
from app.maintenance.models import MaintenanceWindow
from app.users.models import User, UserRole
from app.users.service import UserService


PASSWORD = "Operations API password 2026!"


@pytest.fixture
def operations_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[tuple[TestClient, sessionmaker[Session], UUID]]:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="operations.admin",
            display_name="Operations Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        session.flush()
        admin_id = admin.id
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="operations-api-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "assets",
    )
    settings.asset_root.mkdir()
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    with TestClient(
        create_app(
            settings=settings,
            database_probe=lambda _: True,
            database_bootstrap=lambda _: resources,
        )
    ) as client:
        yield client, auth_session_factory, admin_id


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "operations.admin", "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_admin_can_inspect_current_assets_jobs_audit_and_system(
    operations_client: tuple[TestClient, sessionmaker[Session], UUID],
) -> None:
    client, factory, admin_id = operations_client
    csrf = _login(client)
    with factory.begin() as session:
        source = Asset(
            storage_key="managed/source.pdf",
            original_filename="source.pdf",
            sha256="a" * 64,
            byte_size=100,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(source)
        session.flush()
        derivative = Asset(
            storage_key="managed/crop.png",
            original_filename="crop.png",
            sha256="b" * 64,
            byte_size=50,
            mime_type="image/png",
            category=AssetCategory.EVIDENCE_CROP,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            source_asset_id=source.id,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(derivative)
        job = CropJob(
            input_hash="c" * 64,
            source_pdf_sha256=source.sha256,
            source_asset_id=source.id,
            page_number=1,
            x0=0.1,
            y0=0.1,
            x1=0.9,
            y1=0.9,
            rotation=0,
            padding=0,
            dpi=144,
            renderer_version="operations-test",
            status=CropJobStatus.FAILED,
            error_message="render failed",
            attempt_count=3,
            max_attempts=3,
            created_by_id=admin_id,
        )
        session.add(job)
        AuditService().append_event(
            session,
            actor_id=admin_id,
            action="operations.tested",
            target_type="asset",
            target_id=source.id,
            paper_id=None,
            changeset_id=None,
            release_id=None,
            ip_address="127.0.0.1",
            request_id="operations-test",
            result="success",
            reason="Verified operations surface",
            before_hash=canonical_content_hash(None),
            after_hash=source.sha256,
            details={},
        )
        session.flush()
        source_id = source.id
        derivative_id = derivative.id
        job_id = job.id

    files = client.get("/api/v1/admin/files")
    references = client.get(f"/api/v1/admin/files/{source_id}/references")
    jobs = client.get("/api/v1/admin/jobs")
    audit = client.get(
        "/api/v1/admin/audit", params={"action": "operations.tested"}
    )
    system = client.get("/api/v1/admin/system")
    retry = client.post(
        f"/api/v1/admin/jobs/{job_id}/retry",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "operations-retry",
        },
    )

    assert files.status_code == 200
    assert {item["id"] for item in files.json()} == {
        str(source_id),
        str(derivative_id),
    }
    assert references.status_code == 200
    assert {item["kind"] for item in references.json()["references"]} == {
        "asset",
        "crop_job",
    }
    assert jobs.status_code == 200
    assert jobs.json()[0]["id"] == str(job_id)
    assert audit.status_code == 200
    assert [event["action"] for event in audit.json()] == ["operations.tested"]
    assert system.status_code == 200
    assert {"database", "storage", "worker", "schema", "publication"} <= set(
        system.json()["checks"]
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending"


def test_admin_can_toggle_maintenance_without_legacy_release_models(
    operations_client: tuple[TestClient, sessionmaker[Session], UUID],
) -> None:
    client, factory, _ = operations_client
    csrf = _login(client)
    expected_end = datetime.now(UTC) + timedelta(hours=1)

    enabled = client.put(
        "/api/v1/admin/maintenance",
        headers={"X-CSRF-Token": csrf},
        json={
            "active": True,
            "reason": "Verified database maintenance",
            "expected_end": expected_end.isoformat(),
        },
    )
    status = client.get("/api/v1/admin/maintenance")
    disabled = client.put(
        "/api/v1/admin/maintenance",
        headers={"X-CSRF-Token": csrf},
        json={
            "active": False,
            "reason": "Verified maintenance completed",
            "expected_end": None,
        },
    )

    assert enabled.status_code == 200
    assert enabled.json()["active"] is True
    assert status.status_code == 200
    assert status.json()["active"] is True
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
    with factory() as session:
        windows = list(session.scalars(select(MaintenanceWindow)))
    assert len(windows) == 1
    assert windows[0].ended_at is not None


def test_admin_audit_filters_and_paginates_beyond_first_500_events(
    operations_client: tuple[TestClient, sessionmaker[Session], UUID],
) -> None:
    client, factory, admin_id = operations_client
    _login(client)
    with factory.begin() as session:
        service = AuditService()
        oldest = service.append_event(
            session,
            actor_id=admin_id,
            action="operations.deep-match",
            target_type="paper",
            target_id=uuid4(),
            paper_id=None,
            changeset_id=None,
            release_id=None,
            ip_address="127.0.0.1",
            request_id="operations-deep-match",
            result="failure",
            reason="Deep pagination sentinel",
            before_hash=canonical_content_hash(None),
            after_hash=canonical_content_hash({"matched": True}),
            details={},
        )
        for index in range(500):
            service.append_event(
                session,
                actor_id=admin_id,
                action="operations.filler",
                target_type="asset",
                target_id=uuid4(),
                paper_id=None,
                changeset_id=None,
                release_id=None,
                ip_address="127.0.0.1",
                request_id=f"operations-filler-{index}",
                result="success",
                reason="Deep pagination filler",
                before_hash=canonical_content_hash(None),
                after_hash=canonical_content_hash({"index": index}),
                details={},
            )
        oldest_id = str(oldest.id)

    filtered = client.get(
        "/api/v1/admin/audit",
        params={
            "action": "operations.deep-match",
            "target_type": "paper",
            "result": "failure",
        },
    )
    paged = client.get(
        "/api/v1/admin/audit",
        params={"limit": 1, "offset": 500},
    )

    assert filtered.status_code == 200
    assert [event["id"] for event in filtered.json()] == [oldest_id]
    assert paged.status_code == 200
    assert [event["id"] for event in paged.json()] == [oldest_id]
