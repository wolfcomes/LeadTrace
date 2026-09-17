import importlib

from celery import Celery

from app.config import get_settings


settings = get_settings()
celery_app = Celery(
    "leadtrace",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 600},
    beat_schedule={
        "reconcile-crop-jobs": {
            "task": "leadtrace.jobs.reconcile_crops",
            "schedule": 30.0,
        },
        "reconcile-ai-prefill-runs": {
            "task": "leadtrace.ai_prefill.reconcile",
            "schedule": 30.0,
        },
    },
)

importlib.import_module("app.jobs.celery_tasks")
importlib.import_module("app.ai_prefill.celery_tasks")
