from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.audit.models import AuditEvent
from app.config import Settings
from app.database import DatabaseResources
from app.imports.models import ImportBatch, ImportReleaseCandidate
from app.jobs.models import CropJob, CropJobStatus
from app.main import create_app
from app.users.models import User, UserRole
from app.users.service import UserService


PASSWORD = "Admin API password 2026!"


def _client(
    tmp_path: Path,
    database_url: str,
    factory: sessionmaker[Session],
) -> TestClient:
    with factory.begin() as session:
        admin = session.scalar(
            select(User).where(User.normalized_username == "admin.console")
        )
        if admin is None:
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


def _seed_import_candidate(session) -> ImportReleaseCandidate:
    fingerprint = uuid4().hex + uuid4().hex
    counts = {"corpus_papers": 1}
    integrity = {"missing": 0}
    asset_linkage = {"resolved": 1}
    batch = ImportBatch(
        source_fingerprint=fingerprint,
        status="completed",
        counts=counts,
        integrity=integrity,
        asset_linkage=asset_linkage,
        completed_at=datetime.now(UTC),
    )
    session.add(batch)
    session.flush()
    candidate = ImportReleaseCandidate(
        import_batch_id=batch.id,
        status="imported_baseline",
        manifest={
            "schema_version": 1,
            "source_fingerprint": fingerprint,
            "status": "imported_baseline",
            "is_current": False,
            "counts": counts,
            "integrity": integrity,
            "asset_linkage": asset_linkage,
            "revision_count": 1,
            "source_file": "/private/baseline/source.csv",
            "raw_values": {"password": "must-not-appear"},
        },
        is_current=False,
    )
    session.add(candidate)
    session.flush()
    return candidate


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
            attempt_count=3,
            max_attempts=3,
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with _client(tmp_path, empty_postgresql_database_url, auth_session_factory) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "retry-001"}
        first = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
        second = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)

    with _client(
        tmp_path, empty_postgresql_database_url, auth_session_factory
    ) as restarted_client:
        csrf = _login(restarted_client)
        after_restart = restarted_client.post(
            f"/api/v1/admin/jobs/{job_id}/retry",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "retry-001"},
        )

    assert first.status_code == second.status_code == after_restart.status_code == 200
    assert first.json()["id"] == second.json()["id"] == after_restart.json()["id"] == str(job_id)
    assert first.json()["status"] == "pending"
    assert first.json()["attempt_count"] == 3
    assert first.json()["max_attempts"] == 6
    assert first.json()["dispatched_at"] is None
    assert first.json()["heartbeat_at"] is None
    assert after_restart.json()["max_attempts"] == 6


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


def test_admin_lists_safe_import_candidates_and_records_one_audited_decision(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        candidate = _seed_import_candidate(session)
        candidate_id = candidate.id

    with _client(
        tmp_path,
        empty_postgresql_database_url,
        auth_session_factory,
    ) as client:
        csrf = _login(client)
        listing = client.get("/api/v1/admin/import-candidates")
        missing_csrf = client.post(
            f"/api/v1/admin/import-candidates/{candidate_id}/decision",
            json={"action": "approve", "reason": "Reviewed baseline"},
        )
        first = client.post(
            f"/api/v1/admin/import-candidates/{candidate_id}/decision",
            headers={"X-CSRF-Token": csrf},
            json={
                "action": "approve",
                "reason": (
                    "Reviewed baseline manifest and integrity report "
                    "password=decision-secret"
                ),
            },
        )
        retry = client.post(
            f"/api/v1/admin/import-candidates/{candidate_id}/decision",
            headers={"X-CSRF-Token": csrf},
            json={
                "action": "approve",
                "reason": (
                    "Reviewed baseline manifest and integrity report "
                    "password=decision-secret"
                ),
            },
        )
        conflict = client.post(
            f"/api/v1/admin/import-candidates/{candidate_id}/decision",
            headers={"X-CSRF-Token": csrf},
            json={"action": "approve", "reason": "Changed retry reason"},
        )
        decided_listing = client.get("/api/v1/admin/import-candidates")

    assert listing.status_code == 200
    assert len(listing.json()) == 1
    safe_candidate = listing.json()[0]
    assert safe_candidate["id"] == str(candidate_id)
    assert safe_candidate["status"] == "imported_baseline"
    assert safe_candidate["decision"] is None
    assert "source_file" not in safe_candidate["manifest"]
    assert "raw_values" not in safe_candidate["manifest"]
    assert "/private/" not in listing.text
    assert "must-not-appear" not in listing.text
    assert missing_csrf.status_code == 403
    assert first.status_code == 200
    assert first.json()["status"] == "approved"
    assert first.json()["decision"]["decision"] == "approve"
    assert "decision-secret" not in first.text
    assert "[REDACTED]" in first.json()["decision"]["reason"]
    assert first.json()["idempotent"] is False
    assert retry.status_code == 200
    assert retry.json()["decision"]["id"] == first.json()["decision"]["id"]
    assert retry.json()["idempotent"] is True
    assert conflict.status_code == 409
    assert decided_listing.json()[0]["status"] == "approved"
    assert "decision-secret" not in decided_listing.text
    assert "[REDACTED]" in decided_listing.json()[0]["decision"]["reason"]

    with auth_session_factory() as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "import_candidate.approved"
                )
            )
        )
        assert len(events) == 1
        assert events[0].paper_id is None
        assert events[0].target_id == candidate_id
        assert "decision-secret" not in events[0].reason
        assert "source_file" not in str(events[0].details)


def test_import_candidate_admin_endpoints_reject_reviewer(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        candidate = _seed_import_candidate(session)
        candidate_id = candidate.id
        reviewer = UserService().create_user(
            session,
            username="candidate.reviewer",
            display_name="Candidate Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        reviewer.must_change_password = False

    with _client(
        tmp_path,
        empty_postgresql_database_url,
        auth_session_factory,
    ) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "candidate.reviewer", "password": PASSWORD},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        listing = client.get("/api/v1/admin/import-candidates")
        decision = client.post(
            f"/api/v1/admin/import-candidates/{candidate_id}/decision",
            headers={"X-CSRF-Token": csrf},
            json={"action": "reject", "reason": "Must not be authorized"},
        )

    assert listing.status_code == 403
    assert decision.status_code == 403
