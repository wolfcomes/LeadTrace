from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthSession
from app.config import Settings
from app.database import DatabaseResources
from app.jobs.models import (
    CropJob,
    CropJobAttempt,
    CropJobAttemptStatus,
    CropJobStatus,
)
from app.jobs.reconciler import JobReconciler
from app.jobs.service import CropRequest, CropService, CropValidationError
from app.main import create_app
from app.maintenance.models import MaintenanceWindow
from app.maintenance.service import MaintenanceModeActive
from app.maintenance.service import MaintenanceService
from app.releases.models import Release
from app.users.models import UserRole
from app.users.service import UserService
from app.worker import celery_app


PASSWORD = "Task 23 recovery password!"
NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)


def _job(*, status: CropJobStatus = CropJobStatus.PENDING) -> CropJob:
    return CropJob(
        input_hash="a" * 64,
        source_pdf_sha256="b" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.9,
        y1=0.9,
        rotation=0,
        padding=0,
        dpi=200,
        renderer_version="task-23-test",
        status=status,
    )


def _persist_job(factory: sessionmaker[Session], job: CropJob) -> UUID:
    with factory.begin() as session:
        session.add(job)
        session.flush()
        return job.id


def _request() -> CropRequest:
    return CropRequest(
        source_pdf_sha256="b" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.9,
        y1=0.9,
        rotation=0,
        padding=0,
        dpi=200,
        renderer_version="task-23-test",
    )


def _job_for_request(request: CropRequest) -> CropJob:
    job = _job()
    job.input_hash = request.input_hash()
    return job


def test_queued_job_is_dispatched_from_postgresql(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job_id = _persist_job(auth_session_factory, _job())
    deliveries: list[tuple[UUID, UUID]] = []

    report = JobReconciler().reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )

    assert report.dispatched == 1
    assert report.recovered == 0
    assert deliveries[0][0] == job_id
    with auth_session_factory.begin() as session:
        persisted = session.get(CropJob, job_id)
        assert persisted is not None
        assert persisted.dispatch_token == deliveries[0][1]
        assert persisted.dispatched_at == NOW


def test_stale_dispatch_is_redelivered_with_same_token_after_redis_restart(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job = _job()
    job_id = _persist_job(auth_session_factory, job)
    first_delivery: list[tuple[UUID, UUID]] = []
    reconciler = JobReconciler(dispatch_timeout=timedelta(seconds=30))
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: first_delivery.append((queued_job_id, token)),
        now=NOW,
    )

    restarted_delivery: list[tuple[UUID, UUID]] = []
    report = reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: restarted_delivery.append(
            (queued_job_id, token)
        ),
        now=NOW + timedelta(seconds=31),
    )

    assert report.dispatched == 1
    assert restarted_delivery == first_delivery
    assert restarted_delivery[0][0] == job_id


def test_failed_broker_delivery_is_immediately_recoverable(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job_id = _persist_job(auth_session_factory, _job())
    reconciler = JobReconciler(dispatch_timeout=timedelta(minutes=5))

    def unavailable_broker(_: UUID, __: UUID) -> None:
        raise ConnectionError("Redis is restarting")

    failed = reconciler.reconcile(
        auth_session_factory,
        unavailable_broker,
        now=NOW,
    )
    recovered_deliveries: list[tuple[UUID, UUID]] = []
    recovered = reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: recovered_deliveries.append(
            (queued_job_id, token)
        ),
        now=NOW + timedelta(seconds=1),
    )

    assert failed.dispatch_failures == 1
    assert failed.dispatched == 0
    assert recovered.dispatched == 1
    assert recovered_deliveries[0][0] == job_id


def test_legacy_running_job_without_heartbeat_recovers_from_started_at(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job = _job(status=CropJobStatus.RUNNING)
    job.started_at = NOW - timedelta(minutes=3)
    job_id = _persist_job(auth_session_factory, job)
    deliveries: list[tuple[UUID, UUID]] = []

    report = JobReconciler(worker_timeout=timedelta(minutes=2)).reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )

    assert report.recovered == 1
    assert deliveries[0][0] == job_id


def test_worker_death_marks_attempt_stale_and_redelivers_job(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job_id = _persist_job(auth_session_factory, _job())
    deliveries: list[tuple[UUID, UUID]] = []
    reconciler = JobReconciler(worker_timeout=timedelta(minutes=2))
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )
    first_token = deliveries[0][1]
    with auth_session_factory.begin() as session:
        claimed = reconciler.claim_delivery(
            session,
            job_id=job_id,
            delivery_token=first_token,
            now=NOW,
        )
        assert claimed is not None

    deliveries.clear()
    report = reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW + timedelta(minutes=2, seconds=1),
    )

    assert report.recovered == 1
    assert report.dispatched == 1
    assert deliveries[0][1] != first_token
    with auth_session_factory.begin() as session:
        attempt = session.scalar(
            select(CropJobAttempt).where(
                CropJobAttempt.job_id == job_id,
                CropJobAttempt.attempt_number == 1,
            )
        )
        persisted = session.get(CropJob, job_id)
        assert attempt is not None
        assert attempt.status is CropJobAttemptStatus.STALE
        assert attempt.completed_at == NOW + timedelta(minutes=2, seconds=1)
        assert persisted is not None
        assert persisted.status is CropJobStatus.PENDING
        assert persisted.attempt_count == 1


def test_old_delivery_cannot_heartbeat_after_worker_recovery(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job_id = _persist_job(auth_session_factory, _job())
    deliveries: list[tuple[UUID, UUID]] = []
    reconciler = JobReconciler(worker_timeout=timedelta(minutes=2))
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )
    old_token = deliveries[0][1]
    with auth_session_factory.begin() as session:
        assert (
            reconciler.claim_delivery(
                session,
                job_id=job_id,
                delivery_token=old_token,
                now=NOW,
            )
            is not None
        )
    deliveries.clear()
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW + timedelta(minutes=3),
    )

    with auth_session_factory.begin() as session:
        assert (
            reconciler.heartbeat_delivery(
                session,
                job_id=job_id,
                delivery_token=old_token,
                now=NOW + timedelta(minutes=3, seconds=1),
            )
            is False
        )
        persisted = session.get(CropJob, job_id)
        assert persisted is not None
        assert persisted.dispatch_token == deliveries[0][1]
        assert persisted.heartbeat_at is None


def test_duplicate_delivery_can_be_claimed_only_once(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job_id = _persist_job(auth_session_factory, _job())
    deliveries: list[tuple[UUID, UUID]] = []
    reconciler = JobReconciler()
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )
    token = deliveries[0][1]

    with auth_session_factory.begin() as session:
        first = reconciler.claim_delivery(
            session,
            job_id=job_id,
            delivery_token=token,
            now=NOW,
        )
    with auth_session_factory.begin() as session:
        duplicate = reconciler.claim_delivery(
            session,
            job_id=job_id,
            delivery_token=token,
            now=NOW,
        )

    assert first is not None
    assert duplicate is None
    with auth_session_factory.begin() as session:
        attempts = list(
            session.scalars(
                select(CropJobAttempt).where(CropJobAttempt.job_id == job_id)
            )
        )
        assert len(attempts) == 1


def test_stale_attempt_stops_at_retry_limit(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job = _job(status=CropJobStatus.RUNNING)
    job.attempt_count = 3
    job.max_attempts = 3
    job.dispatch_token = UUID("00000000-0000-0000-0000-000000000123")
    job.dispatched_at = NOW - timedelta(minutes=4)
    job.started_at = NOW - timedelta(minutes=3)
    job.heartbeat_at = NOW - timedelta(minutes=3)
    job_id = _persist_job(auth_session_factory, job)
    with auth_session_factory.begin() as session:
        session.add(
            CropJobAttempt(
                job_id=job_id,
                attempt_number=3,
                delivery_token=job.dispatch_token,
                status=CropJobAttemptStatus.RUNNING,
                started_at=job.started_at,
                heartbeat_at=job.heartbeat_at,
            )
        )

    deliveries: list[tuple[UUID, UUID]] = []
    report = JobReconciler(worker_timeout=timedelta(minutes=2)).reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )

    assert report.exhausted == 1
    assert report.dispatched == 0
    assert deliveries == []
    with auth_session_factory.begin() as session:
        persisted = session.get(CropJob, job_id)
        attempt = session.scalar(
            select(CropJobAttempt).where(CropJobAttempt.job_id == job_id)
        )
        assert persisted is not None
        assert persisted.status is CropJobStatus.FAILED
        assert persisted.error_message == "Worker lease expired; retry limit reached"
        assert attempt is not None
        assert attempt.status is CropJobAttemptStatus.STALE


def test_manual_retry_restores_exhausted_attempt_budget(
    auth_session_factory: sessionmaker[Session],
) -> None:
    job = _job(status=CropJobStatus.FAILED)
    job.attempt_count = 3
    job.max_attempts = 3
    job.error_message = "retry limit reached"
    job.completed_at = NOW
    job_id = _persist_job(auth_session_factory, job)
    with auth_session_factory.begin() as session:
        for attempt_number in range(1, 4):
            session.add(
                CropJobAttempt(
                    job_id=job_id,
                    attempt_number=attempt_number,
                    delivery_token=UUID(
                        f"00000000-0000-0000-0000-{attempt_number:012d}"
                    ),
                    status=CropJobAttemptStatus.FAILED,
                    started_at=NOW - timedelta(minutes=attempt_number),
                    heartbeat_at=NOW - timedelta(minutes=attempt_number),
                    completed_at=NOW - timedelta(minutes=attempt_number - 1),
                    error_message="worker failed",
                )
            )
    reconciler = JobReconciler()

    with auth_session_factory.begin() as session:
        retried = reconciler.retry_failed(session, job_id=job_id)

    assert retried.status is CropJobStatus.PENDING
    assert retried.attempt_count == 3
    assert retried.max_attempts == 6
    assert retried.error_message is None
    assert retried.completed_at is None

    deliveries: list[tuple[UUID, UUID]] = []
    report = reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW + timedelta(minutes=1),
    )
    assert report.dispatched == 1
    assert deliveries[0][0] == job_id
    with auth_session_factory.begin() as session:
        attempt = reconciler.claim_delivery(
            session,
            job_id=job_id,
            delivery_token=deliveries[0][1],
            now=NOW + timedelta(minutes=1),
        )
        assert attempt is not None
        assert attempt.attempt_number == 4


def test_superseded_job_is_never_dispatched_or_claimed(
    auth_session_factory: sessionmaker[Session],
) -> None:
    old_job = _job()
    old_job.input_hash = "c" * 64
    new_job = _job()
    new_job.input_hash = "d" * 64
    with auth_session_factory.begin() as session:
        session.add_all([old_job, new_job])
        session.flush()
        old_id = old_job.id
        new_id = new_job.id

    reconciler = JobReconciler()
    with auth_session_factory.begin() as session:
        reconciler.supersede(
            session,
            job_id=old_id,
            superseded_by_id=new_id,
            now=NOW,
        )

    deliveries: list[tuple[UUID, UUID]] = []
    reconciler.reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW,
    )
    assert [delivery[0] for delivery in deliveries] == [new_id]

    with auth_session_factory.begin() as session:
        old = session.get(CropJob, old_id)
        assert old is not None
        assert old.status is CropJobStatus.SUPERSEDED
        assert old.superseded_by_id == new_id
        assert old.dispatch_token is None
        assert (
            reconciler.claim_delivery(
                session,
                job_id=old_id,
                delivery_token=UUID("00000000-0000-0000-0000-000000000456"),
                now=NOW,
            )
            is None
        )


def test_persisted_crop_service_does_not_revive_superseded_work(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    request = _request()
    old_job = _job_for_request(request)
    new_job = _job()
    new_job.input_hash = "e" * 64
    with auth_session_factory.begin() as session:
        session.add_all([old_job, new_job])
        session.flush()
        old_id = old_job.id
        JobReconciler().supersede(
            session,
            job_id=old_job.id,
            superseded_by_id=new_job.id,
            now=NOW,
        )

    rendered: list[bool] = []
    with pytest.raises(CropValidationError, match="superseded"):
        with auth_session_factory.begin() as session:
            CropService(tmp_path).run_persisted(
                session,
                request,
                renderer=lambda _: rendered.append(True) or b"PNG",
            )

    assert rendered == []
    with auth_session_factory.begin() as session:
        persisted = session.get(CropJob, old_id)
        assert persisted is not None
        assert persisted.status is CropJobStatus.SUPERSEDED


def test_persisted_crop_service_stops_before_rendering_during_maintenance(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    request = _request()
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="maintenance.crop",
            display_name="Maintenance Crop",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        session.flush()
        session.add(_job_for_request(request))
        session.add(
            MaintenanceWindow(
                reason="Freeze renderer writes",
                started_at=NOW,
                expected_end_at=NOW + timedelta(hours=1),
                started_by_id=admin.id,
            )
        )

    rendered: list[bool] = []
    with pytest.raises(MaintenanceModeActive):
        with auth_session_factory.begin() as session:
            CropService(tmp_path).run_persisted(
                session,
                request,
                renderer=lambda _: rendered.append(True) or b"PNG",
            )

    assert rendered == []


def test_maintenance_mode_pauses_job_dispatch(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="maintenance.owner",
            display_name="Maintenance Owner",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        session.flush()
        session.add(
            MaintenanceWindow(
                reason="Database integrity check",
                started_at=NOW,
                expected_end_at=NOW + timedelta(hours=1),
                started_by_id=admin.id,
            )
        )
        session.add(_job())

    deliveries: list[tuple[UUID, UUID]] = []
    report = JobReconciler().reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
        now=NOW + timedelta(minutes=1),
    )

    assert report.maintenance_active is True
    assert report.dispatched == 0
    assert deliveries == []


def test_maintenance_activation_waits_for_inflight_write_guard(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="maintenance.fence",
            display_name="Maintenance Fence",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        session.flush()
        admin_id = admin.id

    guard_ready = Event()
    release_guard = Event()
    activated = Event()

    def hold_write_guard() -> None:
        with auth_session_factory.begin() as session:
            MaintenanceService().require_writes_enabled(session)
            guard_ready.set()
            assert release_guard.wait(timeout=5)

    def activate_maintenance() -> None:
        with auth_session_factory.begin() as session:
            MaintenanceService().activate(
                session,
                actor_id=admin_id,
                reason="Wait for active writes",
                expected_end_at=NOW + timedelta(hours=1),
                now=NOW,
            )
        activated.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        guarded = executor.submit(hold_write_guard)
        assert guard_ready.wait(timeout=5)
        enabling = executor.submit(activate_maintenance)
        activated_while_guarded = activated.wait(timeout=0.2)
        release_guard.set()
        guarded.result(timeout=5)
        enabling.result(timeout=5)

    assert activated_while_guarded is False
    assert activated.is_set()


def test_maintenance_mode_rejects_worker_heartbeat(
    auth_session_factory: sessionmaker[Session],
) -> None:
    token = UUID("00000000-0000-0000-0000-000000000789")
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="maintenance.heartbeat",
            display_name="Maintenance Heartbeat",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        session.flush()
        job = _job(status=CropJobStatus.RUNNING)
        job.dispatch_token = token
        job.dispatched_at = NOW - timedelta(minutes=1)
        job.started_at = NOW - timedelta(minutes=1)
        job.heartbeat_at = NOW - timedelta(minutes=1)
        job.attempt_count = 1
        session.add(job)
        session.flush()
        job_id = job.id
        session.add(
            CropJobAttempt(
                job_id=job_id,
                attempt_number=1,
                delivery_token=token,
                status=CropJobAttemptStatus.RUNNING,
                started_at=job.started_at,
                heartbeat_at=job.heartbeat_at,
            )
        )
        session.add(
            MaintenanceWindow(
                reason="Freeze background writes",
                started_at=NOW,
                expected_end_at=NOW + timedelta(hours=1),
                started_by_id=admin.id,
            )
        )

    with auth_session_factory.begin() as session:
        updated = JobReconciler().heartbeat_delivery(
            session,
            job_id=job_id,
            delivery_token=token,
            now=NOW + timedelta(minutes=1),
        )
        persisted = session.get(CropJob, job_id)
        assert persisted is not None
        assert updated is False
        assert persisted.heartbeat_at == NOW - timedelta(minutes=1)


def _maintenance_client(
    tmp_path: Path,
    database_url: str,
    factory: sessionmaker[Session],
) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="maintenance-test-secret-more-than-thirty-two-characters",
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


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_maintenance_api_keeps_published_reads_and_blocks_reviewer_writes(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        users: dict[UserRole, UUID] = {}
        for role in (UserRole.ADMIN, UserRole.REVIEWER, UserRole.VISITOR):
            user = UserService().create_user(
                session,
                username=f"maintenance.{role.value}",
                display_name=f"Maintenance {role.value}",
                role=role,
                initial_password=PASSWORD,
            )
            user.must_change_password = False
            session.flush()
            users[role] = user.id
        session.add(
            Release(
                release_key="maintenance-current",
                title="Current scientific release",
                notes="",
                metrics={"paper_count": 1},
                published_by_id=users[UserRole.ADMIN],
                published_at=NOW,
                is_current=True,
                manifest_finalized=True,
            )
        )

    with _maintenance_client(
        tmp_path,
        empty_postgresql_database_url,
        auth_session_factory,
    ) as client:
        admin_csrf = _login(client, "maintenance.admin")
        expected_end = datetime.now(UTC) + timedelta(hours=2)
        invalid = client.put(
            "/api/v1/admin/maintenance",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "active": True,
                "reason": "Invalid expired window",
                "expected_end": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            },
        )
        assert invalid.status_code == 422

        enabled = client.put(
            "/api/v1/admin/maintenance",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "active": True,
                "reason": "Apply a verified schema migration",
                "expected_end": expected_end.isoformat(),
            },
        )
        assert enabled.status_code == 200
        assert enabled.json() == {
            "active": True,
            "reason": "Apply a verified schema migration",
            "started_at": enabled.json()["started_at"],
            "expected_end": expected_end.isoformat().replace("+00:00", "Z"),
            "started_by_id": str(users[UserRole.ADMIN]),
            "allowed_operations": [
                "read_published_data",
                "inspect_system_health",
                "disable_maintenance_mode",
            ],
        }

        client.cookies.clear()
        unauthenticated = client.post(
            "/api/v1/review/changesets",
            json={},
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["code"] == "AUTHENTICATION_REQUIRED"

        _login(client, "maintenance.visitor")
        published = client.get("/api/v1/published/overview")
        assert published.status_code == 200
        assert published.json()["release"]["key"] == "maintenance-current"

        client.cookies.clear()
        reviewer_csrf = _login(client, "maintenance.reviewer")
        with auth_session_factory.begin() as session:
            before_last_seen = session.scalar(
                select(AuthSession.last_seen_at)
                .where(AuthSession.user_id == users[UserRole.REVIEWER])
                .order_by(AuthSession.created_at.desc())
                .limit(1)
            )
        blocked = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={},
        )
        assert blocked.status_code == 503
        assert blocked.json()["code"] == "MAINTENANCE_MODE"
        assert blocked.json()["message"] == "LeadTrace is temporarily read-only"
        assert blocked.json()["details"] == {
            "reason": "Apply a verified schema migration",
            "started_at": enabled.json()["started_at"],
            "expected_end": expected_end.isoformat().replace("+00:00", "Z"),
        }
        with auth_session_factory.begin() as session:
            after_last_seen = session.scalar(
                select(AuthSession.last_seen_at)
                .where(AuthSession.user_id == users[UserRole.REVIEWER])
                .order_by(AuthSession.created_at.desc())
                .limit(1)
            )
        assert after_last_seen == before_last_seen

        client.cookies.clear()
        admin_csrf = _login(client, "maintenance.admin")
        disabled = client.put(
            "/api/v1/admin/maintenance",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "active": False,
                "reason": "Migration and integrity checks completed",
            },
        )
        assert disabled.status_code == 200
        assert disabled.json()["active"] is False

    with auth_session_factory.begin() as session:
        windows = list(session.scalars(select(MaintenanceWindow)))
        assert len(windows) == 1
        assert windows[0].active_slot is None
        assert windows[0].ended_by_id == users[UserRole.ADMIN]
        assert windows[0].ended_reason == "Migration and integrity checks completed"


def test_celery_worker_uses_recoverable_delivery_settings() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_cancel_long_running_tasks_on_connection_loss is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_compose_persists_redis_delivery_and_stops_worker_gracefully() -> None:
    compose_path = Path(__file__).parents[3] / "deploy" / "compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    worker = compose["services"]["worker"]
    redis = compose["services"]["redis"]

    assert worker["init"] is True
    assert worker["stop_grace_period"] == "30s"
    assert "--prefetch-multiplier=1" in worker["command"]
    assert redis["command"] == [
        "redis-server",
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
    ]
