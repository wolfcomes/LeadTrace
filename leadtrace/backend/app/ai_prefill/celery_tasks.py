from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from celery.signals import worker_process_shutdown

from app.ai_prefill.extractor import ProtectedPdfReference
from app.ai_prefill.legacy_adapter import LegacyPipelineAdapter
from app.ai_prefill.models import AiExtractionRun
from app.ai_prefill.reconciler import AiPrefillRunReconciler
from app.ai_prefill.worker_service import execute_ai_prefill_run
from app.config import Settings, get_settings
from app.database import DatabaseResources, bootstrap_database
from app.db.model_registry import load_model_registry
from app.structure_images.service import StructureSourceImageService
from app.worker import celery_app


AI_PREFILL_TASK_NAME = "leadtrace.ai_prefill.execute"
AI_PREFILL_RECONCILE_TASK_NAME = "leadtrace.ai_prefill.reconcile"


@lru_cache(maxsize=1)
def _worker_resources() -> DatabaseResources:
    load_model_registry()
    return bootstrap_database(get_settings())


class _UnavailableExtractor:
    def __init__(self, engine: str, engine_version: str) -> None:
        self.engine = engine
        self.engine_version = engine_version

    def extract(self, source: ProtectedPdfReference):
        del source
        raise RuntimeError("AI extractor is not configured")


def _extractor(settings: Settings, engine: str, engine_version: str):
    if engine == "legacy_pipeline" and settings.ai_prefill_legacy_root is not None:
        adapter = LegacyPipelineAdapter(settings.ai_prefill_legacy_root)
        if adapter.engine_version != engine_version:
            return _UnavailableExtractor(engine, engine_version)
        return adapter
    return _UnavailableExtractor(engine, engine_version)


def dispatch_ai_prefill_run(run_id: UUID, dispatch_token: UUID) -> None:
    execute_ai_prefill.apply_async(args=[str(run_id), str(dispatch_token)])


@celery_app.task(name=AI_PREFILL_RECONCILE_TASK_NAME)
def reconcile_ai_prefill_runs() -> dict[str, int]:
    report = AiPrefillRunReconciler().reconcile(
        _worker_resources().session_factory,
        dispatch_ai_prefill_run,
    )
    return {
        "dispatched": report.dispatched,
        "recovered": report.recovered,
        "dispatch_failures": report.dispatch_failures,
    }


@celery_app.task(name=AI_PREFILL_TASK_NAME)
def execute_ai_prefill(
    run_id: str,
    dispatch_token: str,
) -> dict[str, object]:
    resources = _worker_resources()
    parsed_run_id = UUID(run_id)
    with resources.session_factory() as session:
        run = session.get(AiExtractionRun, parsed_run_id)
        if run is None:
            raise LookupError("AI extraction run not found")
        engine = run.engine
        engine_version = run.engine_version
    settings = get_settings()
    return execute_ai_prefill_run(
        resources.session_factory,
        run_id=parsed_run_id,
        dispatch_token=UUID(dispatch_token),
        extractor=_extractor(settings, engine, engine_version),
        structure_image_service=StructureSourceImageService(
            settings.asset_root,
            source_roots=settings.source_roots,
        ),
    )


@worker_process_shutdown.connect
def _close_ai_worker_resources(**_: object) -> None:
    if _worker_resources.cache_info().currsize:
        _worker_resources().close()
        _worker_resources.cache_clear()


__all__ = [
    "AI_PREFILL_RECONCILE_TASK_NAME",
    "AI_PREFILL_TASK_NAME",
    "dispatch_ai_prefill_run",
    "execute_ai_prefill",
    "reconcile_ai_prefill_runs",
]
