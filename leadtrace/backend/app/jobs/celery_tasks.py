from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from uuid import UUID

from celery.signals import worker_process_shutdown

from app.config import get_settings
from app.database import DatabaseResources, bootstrap_database
from app.db.model_registry import load_model_registry
from app.jobs.execution import execute_crop_delivery
from app.jobs.reconciler import JobReconciler
from app.worker import celery_app


EXECUTE_CROP_TASK_NAME = "leadtrace.jobs.execute_crop"
RECONCILE_CROP_TASK_NAME = "leadtrace.jobs.reconcile_crops"


@lru_cache(maxsize=1)
def _worker_resources() -> DatabaseResources:
    load_model_registry()
    return bootstrap_database(get_settings())


def dispatch_crop_job(job_id: UUID, delivery_token: UUID) -> None:
    execute_crop_job.apply_async(args=[str(job_id), str(delivery_token)])


@celery_app.task(name=EXECUTE_CROP_TASK_NAME)
def execute_crop_job(job_id: str, delivery_token: str) -> dict[str, object]:
    report = execute_crop_delivery(
        _worker_resources().session_factory,
        get_settings(),
        job_id=UUID(job_id),
        delivery_token=UUID(delivery_token),
    )
    payload = asdict(report)
    payload["job_id"] = str(report.job_id)
    payload["status"] = report.status.value
    payload["attempt_id"] = str(report.attempt_id) if report.attempt_id else None
    payload["asset_id"] = str(report.asset_id) if report.asset_id else None
    return payload


@celery_app.task(name=RECONCILE_CROP_TASK_NAME)
def reconcile_crop_jobs() -> dict[str, object]:
    report = JobReconciler().reconcile(
        _worker_resources().session_factory,
        dispatch_crop_job,
    )
    return asdict(report)


@worker_process_shutdown.connect
def _close_worker_resources(**_: object) -> None:
    if _worker_resources.cache_info().currsize:
        _worker_resources().close()
        _worker_resources.cache_clear()


__all__ = [
    "EXECUTE_CROP_TASK_NAME",
    "RECONCILE_CROP_TASK_NAME",
    "dispatch_crop_job",
    "execute_crop_job",
    "reconcile_crop_jobs",
]
