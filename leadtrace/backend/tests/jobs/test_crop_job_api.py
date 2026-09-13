from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse
from uuid import UUID

from celery import Celery
from fastapi.testclient import TestClient
import pymupdf
import pytest
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.config import Settings
from app.database import DatabaseResources
from app.imports.models import ImportAssetLink, ImportBatch
from app.jobs.celery_tasks import RECONCILE_CROP_TASK_NAME
from app.jobs.execution import CropExecutionStatus, execute_crop_delivery
from app.jobs.models import CropJob, CropJobStatus
from app.jobs.reconciler import JobReconciler
from app.main import create_app
from app.papers.models import Paper
from app.reviews.models import ReviewTask, ReviewTaskStatus
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.regions import RegionService, normalize_bounds


PASSWORD = "Crop job API password 2026!"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class CropApiFixture:
    client: TestClient
    settings: Settings
    session_factory: sessionmaker[Session]
    paper_id: UUID
    region_id: UUID
    reviewer_id: UUID
    reviewer_username: str
    second_reviewer_username: str
    unassigned_reviewer_username: str
    visitor_username: str


def _source_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.draw_rect(pymupdf.Rect(40, 20, 160, 80), color=(0, 0, 0))
    page.insert_text((65, 55), "LeadTrace", fontsize=12)
    payload = document.tobytes()
    document.close()
    return payload


@pytest.fixture
def crop_api_fixture(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[CropApiFixture]:
    asset_root = tmp_path / "assets"
    store = LocalAssetStore(asset_root)
    source = store.put_bytes(_source_pdf(), suffix=".pdf")

    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="crop.api.admin",
            display_name="Crop API Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = UserService().create_user(
            session,
            username="crop.api.reviewer",
            display_name="Crop API Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        second_reviewer = UserService().create_user(
            session,
            username="crop.api.second-reviewer",
            display_name="Second Crop API Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        unassigned_reviewer = UserService().create_user(
            session,
            username="crop.api.unassigned",
            display_name="Unassigned Crop API Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        visitor = UserService().create_user(
            session,
            username="crop.api.visitor",
            display_name="Crop API Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        reviewer.must_change_password = False
        second_reviewer.must_change_password = False
        unassigned_reviewer.must_change_password = False
        visitor.must_change_password = False
        paper = Paper(paper_key="crop-api-paper")
        session.add(paper)
        session.flush()
        batch = ImportBatch(
            source_fingerprint="c" * 64,
            status="applied",
            counts={},
            integrity={},
            asset_linkage={},
        )
        session.add(batch)
        session.flush()
        source_asset, _ = AssetService().register_inspected(
            session,
            storage_key=source.storage_key,
            inspected=store.inspect(source.storage_key),
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            import_batch_id=batch.id,
            created_by_id=admin.id,
        )
        session.add(
            ImportAssetLink(
                import_batch_id=batch.id,
                record_type="paper",
                original_id=paper.paper_key,
                asset_id=source_asset.id,
                link_role="article_pdf",
                source_reference="crop-api-paper.pdf",
            )
        )
        session.add(
            ReviewTask(
                paper_id=paper.id,
                assigned_reviewer_id=reviewer.id,
                created_by_id=admin.id,
            )
        )
        session.add(
            ReviewTask(
                paper_id=paper.id,
                assigned_reviewer_id=second_reviewer.id,
                created_by_id=admin.id,
            )
        )
        region = RegionService().create_region(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            region_key="figure-1",
            page_number=1,
            bounds=normalize_bounds(0.25, 0.2, 0.75, 0.8),
            rotation=0,
        )
        session.flush()
        paper_id = paper.id
        region_id = region.id

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url=os.environ.get(
            "LEADTRACE_TEST_REDIS_URL",
            "redis://127.0.0.1:6379/15",
        ),
        session_secret="crop-api-test-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=asset_root,
    )
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
        yield CropApiFixture(
            client=client,
            settings=settings,
            session_factory=auth_session_factory,
            paper_id=paper_id,
            region_id=region_id,
            reviewer_id=reviewer.id,
            reviewer_username=reviewer.username,
            second_reviewer_username=second_reviewer.username,
            unassigned_reviewer_username=unassigned_reviewer.username,
            visitor_username=visitor.username,
        )


def _login(
    client: TestClient,
    username: str,
    password: str = PASSWORD,
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _enqueue_crop(fixture: CropApiFixture) -> tuple[UUID, UUID]:
    csrf = _login(fixture.client, fixture.reviewer_username)
    path = (
        f"/api/v1/papers/{fixture.paper_id}/regions/"
        f"{fixture.region_id}/crop-jobs"
    )
    response = fixture.client.post(
        path,
        headers={"X-CSRF-Token": csrf},
        json={"source_kind": "article", "padding": 0, "dpi": 72},
    )
    assert response.status_code == 202
    job_id = UUID(response.json()["id"])
    deliveries: list[tuple[UUID, UUID]] = []
    JobReconciler().reconcile(
        fixture.session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
    )
    assert deliveries[0][0] == job_id
    return job_id, deliveries[0][1]


def test_reviewer_enqueues_idempotent_crop_then_worker_completes_it(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    csrf = _login(fixture.client, fixture.reviewer_username)
    path = (
        f"/api/v1/papers/{fixture.paper_id}/regions/"
        f"{fixture.region_id}/crop-jobs"
    )

    created = fixture.client.post(
        path,
        headers={"X-CSRF-Token": csrf},
        json={"source_kind": "article", "padding": 0, "dpi": 72},
    )
    repeated = fixture.client.post(
        path,
        headers={"X-CSRF-Token": csrf},
        json={"source_kind": "article", "padding": 0, "dpi": 72},
    )

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["id"] == created.json()["id"]
    assert created.json()["status"] == "pending"
    job_id = UUID(created.json()["id"])
    with fixture.session_factory.begin() as session:
        job = session.get(CropJob, job_id)
        assert job is not None
        assert job.status is CropJobStatus.PENDING
        assert job.dispatch_token is None
        assert job.created_by_id is not None
        assert job.renderer_version.startswith("pymupdf-")
        assert session.scalar(select(func.count()).select_from(CropJob)) == 1

    deliveries: list[tuple[UUID, UUID]] = []
    JobReconciler().reconcile(
        fixture.session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
    )
    report = execute_crop_delivery(
        fixture.session_factory,
        fixture.settings,
        job_id=job_id,
        delivery_token=deliveries[0][1],
    )

    assert report.status is CropExecutionStatus.COMPLETED
    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")
    assert status.status_code == 200
    assert set(status.json()) == {
        "id",
        "status",
        "asset_id",
        "error_code",
        "error_message",
    }
    assert status.json()["id"] == str(job_id)
    assert status.json()["status"] == "completed"
    assert status.json()["asset_id"] == str(report.asset_id)


def test_crop_enqueue_requires_csrf_and_an_active_paper_assignment(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    path = (
        f"/api/v1/papers/{fixture.paper_id}/regions/"
        f"{fixture.region_id}/crop-jobs"
    )
    payload = {"source_kind": "article", "padding": 0, "dpi": 72}
    _login(fixture.client, fixture.reviewer_username)

    missing_csrf = fixture.client.post(path, json=payload)

    assert missing_csrf.status_code == 403
    fixture.client.cookies.clear()
    unassigned_csrf = _login(
        fixture.client,
        fixture.unassigned_reviewer_username,
    )
    unassigned = fixture.client.post(
        path,
        headers={"X-CSRF-Token": unassigned_csrf},
        json=payload,
    )
    assert unassigned.status_code == 403

    fixture.client.cookies.clear()
    visitor_csrf = _login(fixture.client, fixture.visitor_username)
    visitor = fixture.client.post(
        path,
        headers={"X-CSRF-Token": visitor_csrf},
        json=payload,
    )
    assert visitor.status_code == 403
    with fixture.session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(CropJob)) == 0


def test_each_authorized_reviewer_can_track_a_globally_reused_crop_job(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    path = (
        f"/api/v1/papers/{fixture.paper_id}/regions/"
        f"{fixture.region_id}/crop-jobs"
    )
    payload = {"source_kind": "article", "padding": 0, "dpi": 72}
    first_csrf = _login(fixture.client, fixture.reviewer_username)
    first = fixture.client.post(
        path,
        headers={"X-CSRF-Token": first_csrf},
        json=payload,
    )
    assert first.status_code == 202

    fixture.client.cookies.clear()
    second_csrf = _login(fixture.client, fixture.second_reviewer_username)
    second = fixture.client.post(
        path,
        headers={"X-CSRF-Token": second_csrf},
        json=payload,
    )

    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    status = fixture.client.get(f"/api/v1/crop-jobs/{second.json()['id']}")
    assert status.status_code == 200
    assert status.json()["id"] == second.json()["id"]
    with fixture.session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(CropJob)) == 1


def test_reviewer_cannot_track_a_job_after_their_assignment_is_completed(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    job_id, _ = _enqueue_crop(fixture)
    with fixture.session_factory.begin() as session:
        task = session.scalar(
            select(ReviewTask).where(
                ReviewTask.paper_id == fixture.paper_id,
                ReviewTask.assigned_reviewer_id == fixture.reviewer_id,
            )
        )
        assert task is not None
        task.status = ReviewTaskStatus.COMPLETED

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")
    assert status.status_code == 404


def test_demoted_reviewer_cannot_use_an_existing_crop_job_subscription(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    job_id, _ = _enqueue_crop(fixture)
    with fixture.session_factory.begin() as session:
        UserService().set_role(session, fixture.reviewer_id, UserRole.VISITOR)
    fixture.client.cookies.clear()
    _login(fixture.client, fixture.reviewer_username)

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")

    assert status.status_code == 403
    assert str(job_id) not in status.text
    assert "asset_id" not in status.text


def test_reviewer_can_track_crop_jobs_after_password_reset(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    job_id, _ = _enqueue_crop(fixture)
    replacement_password = "Replacement crop API password 2026!"
    with fixture.session_factory.begin() as session:
        UserService().reset_password(
            session,
            fixture.reviewer_id,
            replacement_password,
        )
    fixture.client.cookies.clear()
    _login(
        fixture.client,
        fixture.reviewer_username,
        replacement_password,
    )

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")

    assert status.status_code == 200
    assert status.json()["id"] == str(job_id)


def test_reviewer_job_status_hides_a_missing_source_absolute_path(
    crop_api_fixture: CropApiFixture,
) -> None:
    fixture = crop_api_fixture
    job_id, delivery_token = _enqueue_crop(fixture)
    with fixture.session_factory.begin() as session:
        job = session.get(CropJob, job_id)
        assert job is not None
        source_asset = session.get(Asset, job.source_asset_id)
        assert source_asset is not None
        source_path = LocalAssetStore(fixture.settings.asset_root).path_for(
            source_asset.storage_key
        )
    source_path.unlink()

    with pytest.raises(FileNotFoundError):
        execute_crop_delivery(
            fixture.session_factory,
            fixture.settings,
            job_id=job_id,
            delivery_token=delivery_token,
        )

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["error_code"] == "CROP_JOB_EXECUTION_FAILED"
    assert status.json()["error_message"] == "Crop job execution failed"
    assert str(source_path) not in status.text


def test_reviewer_job_status_hides_an_unexpected_renderer_error(
    crop_api_fixture: CropApiFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = crop_api_fixture
    job_id, delivery_token = _enqueue_crop(fixture)
    internal_path = "/srv/leadtrace/private/render-cache/secret.pdf"

    def fail_render(*_: object, **__: object) -> bytes:
        raise RuntimeError(f"renderer crashed while reading {internal_path}")

    monkeypatch.setattr("app.jobs.execution.render_pdf_crop", fail_render)
    with pytest.raises(RuntimeError):
        execute_crop_delivery(
            fixture.session_factory,
            fixture.settings,
            job_id=job_id,
            delivery_token=delivery_token,
        )

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["error_code"] == "CROP_JOB_EXECUTION_FAILED"
    assert status.json()["error_message"] == "Crop job execution failed"
    assert internal_path not in status.text


@pytest.mark.skipif(
    not os.environ.get("LEADTRACE_TEST_REDIS_URL"),
    reason="LEADTRACE_TEST_REDIS_URL is required for the real broker test",
)
def test_reviewer_api_job_survives_real_redis_and_celery_delivery(
    crop_api_fixture: CropApiFixture,
    empty_postgresql_database_url: str,
    tmp_path: Path,
) -> None:
    fixture = crop_api_fixture
    redis_url = os.environ["LEADTRACE_TEST_REDIS_URL"]
    redis_database = urlparse(redis_url).path.lstrip("/")
    assert redis_database and int(redis_database) > 0
    broker = Redis.from_url(redis_url)
    broker.flushdb()
    csrf = _login(fixture.client, fixture.reviewer_username)
    path = (
        f"/api/v1/papers/{fixture.paper_id}/regions/"
        f"{fixture.region_id}/crop-jobs"
    )
    created = fixture.client.post(
        path,
        headers={"X-CSRF-Token": csrf},
        json={"source_kind": "article", "padding": 0, "dpi": 72},
    )
    assert created.status_code == 202
    job_id = UUID(created.json()["id"])

    environment = os.environ.copy()
    environment.update(
        {
            "LEADTRACE_ENVIRONMENT": "test",
            "LEADTRACE_DATABASE_URL": empty_postgresql_database_url,
            "LEADTRACE_REDIS_URL": redis_url,
            "LEADTRACE_ASSET_ROOT": str(fixture.settings.asset_root),
            "LEADTRACE_SOURCE_ROOTS": json.dumps({}),
        }
    )
    log_path = tmp_path / "celery-api-worker.log"
    celery_client = Celery("leadtrace-api-integration", broker=redis_url)
    with log_path.open("w", encoding="utf-8") as worker_log:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "app.worker:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
                "--loglevel=WARNING",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            celery_client.send_task(RECONCILE_CROP_TASK_NAME)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    pytest.fail(log_path.read_text(encoding="utf-8"))
                with fixture.session_factory.begin() as session:
                    job = session.get(CropJob, job_id)
                    assert job is not None
                    current_status = job.status
                if current_status is CropJobStatus.COMPLETED:
                    break
                time.sleep(0.2)
            else:
                pytest.fail(log_path.read_text(encoding="utf-8"))
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            celery_client.close()
            broker.flushdb()
            broker.close()

    status = fixture.client.get(f"/api/v1/crop-jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["asset_id"] is not None
