from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse
from uuid import UUID

from celery import Celery
from PIL import Image
import pymupdf
import pytest
from redis import Redis
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
from app.jobs.celery_tasks import (
    EXECUTE_CROP_TASK_NAME,
    RECONCILE_CROP_TASK_NAME,
    dispatch_crop_job,
    execute_crop_job,
)
from app.jobs.execution import CropExecutionStatus, execute_crop_delivery
from app.jobs.models import CropJob, CropJobAttempt, CropJobAttemptStatus, CropJobStatus
from app.jobs.reconciler import JobReconciler
from app.jobs.service import CropRequest
from app.worker import celery_app


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _create_source_and_job(
    factory: sessionmaker[Session],
    *,
    asset_root: Path,
    source_root: Path,
) -> tuple[UUID, CropRequest]:
    source_root.mkdir(parents=True, exist_ok=True)
    source_path = source_root / "paper.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.draw_rect(pymupdf.Rect(50, 20, 150, 80), color=(0, 0, 0))
    page.insert_text((70, 55), "LeadTrace", fontsize=12)
    source_path.write_bytes(document.tobytes())
    document.close()

    store = LocalAssetStore(asset_root, source_roots={"test": source_root})
    source_key = store.source_storage_key("test", "paper.pdf")
    inspected = store.inspect(source_key)
    request = CropRequest(
        source_pdf_sha256=inspected.sha256,
        page_number=1,
        x0=0.25,
        y0=0.2,
        x1=0.75,
        y1=0.8,
        rotation=0,
        padding=0,
        dpi=72,
        renderer_version=f"pymupdf-{pymupdf.VersionBind}",
    )
    with factory.begin() as session:
        source_asset, _ = AssetService().register_inspected(
            session,
            storage_key=source_key,
            inspected=inspected,
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
        )
        job = CropJob(
            input_hash=request.input_hash(),
            source_pdf_sha256=request.source_pdf_sha256,
            source_asset_id=source_asset.id,
            page_number=request.page_number,
            x0=request.x0,
            y0=request.y0,
            x1=request.x1,
            y1=request.y1,
            rotation=request.rotation,
            padding=request.padding,
            dpi=request.dpi,
            renderer_version=request.renderer_version,
            status=CropJobStatus.PENDING,
        )
        session.add(job)
        session.flush()
        return job.id, request


def _settings(
    database_url: str,
    *,
    asset_root: Path,
    source_root: Path,
    redis_url: str = "redis://127.0.0.1:6379/15",
) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url=redis_url,
        session_secret="worker-test-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=asset_root,
        source_roots={"test": source_root},
    )


def test_celery_registers_crop_execution_and_periodic_reconciliation() -> None:
    assert EXECUTE_CROP_TASK_NAME in celery_app.tasks
    assert RECONCILE_CROP_TASK_NAME in celery_app.tasks
    assert celery_app.conf.beat_schedule["reconcile-crop-jobs"] == {
        "task": RECONCILE_CROP_TASK_NAME,
        "schedule": 30.0,
    }


def test_crop_dispatcher_sends_only_json_serializable_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery: dict[str, object] = {}

    def capture(*, args: list[str]) -> None:
        delivery["args"] = args

    monkeypatch.setattr(execute_crop_job, "apply_async", capture)
    job_id = UUID("00000000-0000-0000-0000-000000000123")
    delivery_token = UUID("00000000-0000-0000-0000-000000000456")

    dispatch_crop_job(job_id, delivery_token)

    assert delivery == {"args": [str(job_id), str(delivery_token)]}


def test_crop_worker_rebuilds_request_from_postgresql_and_renders_source_pdf(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    asset_root = tmp_path / "assets"
    source_root = tmp_path / "sources"
    job_id, request = _create_source_and_job(
        auth_session_factory,
        asset_root=asset_root,
        source_root=source_root,
    )
    deliveries: list[tuple[UUID, UUID]] = []
    JobReconciler().reconcile(
        auth_session_factory,
        lambda queued_job_id, token: deliveries.append((queued_job_id, token)),
    )

    report = execute_crop_delivery(
        auth_session_factory,
        _settings(
            empty_postgresql_database_url,
            asset_root=asset_root,
            source_root=source_root,
        ),
        job_id=job_id,
        delivery_token=deliveries[0][1],
    )

    assert report.status is CropExecutionStatus.COMPLETED
    assert report.asset_id is not None
    with auth_session_factory.begin() as session:
        job = session.get(CropJob, job_id)
        attempt = session.get(CropJobAttempt, report.attempt_id)
        assert job is not None
        assert job.status is CropJobStatus.COMPLETED
        assert job.asset_id == report.asset_id
        assert attempt is not None
        assert attempt.status is CropJobAttemptStatus.COMPLETED
        registered_asset = session.get(Asset, report.asset_id)
        assert registered_asset is not None
        crop_path = LocalAssetStore(asset_root).path_for(registered_asset.storage_key)
    with Image.open(crop_path) as image:
        assert image.format == "PNG"
        assert image.size == (100, 60)
    assert request.input_hash() == job.input_hash


@pytest.mark.skipif(
    not os.environ.get("LEADTRACE_TEST_REDIS_URL"),
    reason="LEADTRACE_TEST_REDIS_URL is required for the real broker test",
)
def test_real_redis_and_celery_worker_complete_reconciled_crop(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    redis_url = os.environ["LEADTRACE_TEST_REDIS_URL"]
    redis_database = urlparse(redis_url).path.lstrip("/")
    assert redis_database and int(redis_database) > 0
    broker = Redis.from_url(redis_url)
    broker.flushdb()
    asset_root = tmp_path / "assets"
    source_root = tmp_path / "sources"
    job_id, _ = _create_source_and_job(
        auth_session_factory,
        asset_root=asset_root,
        source_root=source_root,
    )
    environment = os.environ.copy()
    environment.update(
        {
            "LEADTRACE_ENVIRONMENT": "test",
            "LEADTRACE_DATABASE_URL": empty_postgresql_database_url,
            "LEADTRACE_REDIS_URL": redis_url,
            "LEADTRACE_ASSET_ROOT": str(asset_root),
            "LEADTRACE_SOURCE_ROOTS": json.dumps({"test": str(source_root)}),
        }
    )
    log_path = tmp_path / "celery-worker.log"
    client = Celery("leadtrace-integration", broker=redis_url)
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
            client.send_task(RECONCILE_CROP_TASK_NAME)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    pytest.fail(log_path.read_text(encoding="utf-8"))
                with auth_session_factory.begin() as session:
                    status = session.get(CropJob, job_id).status
                if status is CropJobStatus.COMPLETED:
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
            client.close()
            broker.flushdb()
            broker.close()

    with auth_session_factory.begin() as session:
        completed = session.get(CropJob, job_id)
        assert completed is not None
        assert completed.status is CropJobStatus.COMPLETED
        assert completed.asset_id is not None
