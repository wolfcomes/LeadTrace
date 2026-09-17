from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
import logging
from threading import Event, Thread
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai_prefill.extractor import AiExtractor, ProtectedPdfReference
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.reconciler import AiPrefillRunReconciler
from app.ai_prefill.service import AiPrefillNotFoundError, AiPrefillService
from app.catalog.models import PaperSource
from app.papers.models import Paper
from app.structure_images.service import StructureSourceImageService


logger = logging.getLogger(__name__)


def _report(
    run_id: UUID,
    status: AiExtractionRunStatus,
    *,
    applied: bool,
    idempotent: bool,
) -> dict[str, object]:
    return {
        "run_id": str(run_id),
        "status": status.value,
        "applied": applied,
        "idempotent": idempotent,
    }


def _terminate_current_delivery(
    session_factory: sessionmaker[Session],
    *,
    run_id: UUID,
    dispatch_token: UUID,
    error_summary: str,
) -> tuple[AiExtractionRunStatus, bool]:
    with session_factory.begin() as session:
        failed = AiPrefillRunReconciler().fail_delivery(
            session,
            run_id=run_id,
            delivery_token=dispatch_token,
            error_summary=error_summary,
        )
        run = session.get(AiExtractionRun, run_id)
        if run is None:
            raise AiPrefillNotFoundError("AI extraction run not found")
        return run.status, failed


@contextmanager
def _heartbeat_current_delivery(
    session_factory: sessionmaker[Session],
    *,
    run_id: UUID,
    dispatch_token: UUID,
    interval: timedelta,
) -> Iterator[None]:
    if interval <= timedelta(0):
        raise ValueError("heartbeat_interval must be positive")
    stopped = Event()

    def heartbeat() -> None:
        while not stopped.wait(interval.total_seconds()):
            try:
                with session_factory.begin() as session:
                    current = AiPrefillRunReconciler().heartbeat_delivery(
                        session,
                        run_id=run_id,
                        delivery_token=dispatch_token,
                    )
                if not current:
                    return
            except Exception:
                logger.exception(
                    "AI prefill heartbeat failed",
                    extra={"ai_run_id": str(run_id)},
                )

    thread = Thread(
        target=heartbeat,
        name=f"ai-prefill-heartbeat-{run_id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


def execute_ai_prefill_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: UUID,
    dispatch_token: UUID | None = None,
    extractor: AiExtractor,
    structure_image_service: StructureSourceImageService | None = None,
    heartbeat_interval: timedelta = timedelta(seconds=30),
) -> dict[str, object]:
    if heartbeat_interval <= timedelta(0):
        raise ValueError("heartbeat_interval must be positive")
    reconciler = AiPrefillRunReconciler()
    with session_factory.begin() as session:
        row = session.execute(
            select(AiExtractionRun, Paper, PaperSource)
            .join(Paper, Paper.id == AiExtractionRun.paper_id)
            .join(PaperSource, PaperSource.id == Paper.source_id)
            .where(AiExtractionRun.id == run_id)
            .with_for_update(of=AiExtractionRun)
        ).one_or_none()
        if row is None:
            raise AiPrefillNotFoundError("AI extraction run not found")
        run, paper, source = row
        if dispatch_token is not None and run.dispatch_token != dispatch_token:
            return _report(
                run.id,
                run.status,
                applied=False,
                idempotent=True,
            )
        if run.status is AiExtractionRunStatus.RUNNING:
            return _report(
                run.id,
                run.status,
                applied=False,
                idempotent=True,
            )
        if run.status is AiExtractionRunStatus.SUCCEEDED:
            return _report(
                run.id,
                run.status,
                applied=False,
                idempotent=True,
            )
        if run.status in {
            AiExtractionRunStatus.FAILED,
            AiExtractionRunStatus.SUPERSEDED,
        }:
            return _report(
                run.id,
                run.status,
                applied=False,
                idempotent=True,
            )
        current_token = dispatch_token or run.dispatch_token
        if current_token is None:
            raise RuntimeError("Queued AI extraction run has no dispatch token")
        claimed = reconciler.claim_delivery(
            session,
            run_id=run.id,
            delivery_token=current_token,
        )
        if claimed is None:
            return _report(
                run.id,
                run.status,
                applied=False,
                idempotent=True,
            )
        reference = ProtectedPdfReference(
            paper_id=paper.id,
            source_root_key=source.source_root_key,
            source_key=source.source_key,
            sha256=source.sha256,
            page_count=source.page_count,
        )

    with _heartbeat_current_delivery(
        session_factory,
        run_id=run_id,
        dispatch_token=current_token,
        interval=heartbeat_interval,
    ):
        try:
            if run.engine != extractor.engine:
                raise ValueError("AI extractor engine does not match queued run")
            payload = extractor.extract(reference)
        except Exception:
            status, failed = _terminate_current_delivery(
                session_factory,
                run_id=run_id,
                dispatch_token=current_token,
                error_summary="AI extraction failed",
            )
            return _report(
                run_id,
                status,
                applied=False,
                idempotent=not failed,
            )

        try:
            with session_factory.begin() as session:
                result = AiPrefillService(structure_image_service).apply(
                    session,
                    run_id=run_id,
                    dispatch_token=current_token,
                    payload=payload,
                )
                report = _report(
                    run_id,
                    result.run.status,
                    applied=result.applied,
                    idempotent=result.idempotent,
                )
        except Exception:
            status, failed = _terminate_current_delivery(
                session_factory,
                run_id=run_id,
                dispatch_token=current_token,
                error_summary="AI prefill execution failed",
            )
            return _report(
                run_id,
                status,
                applied=False,
                idempotent=not failed,
            )
        return report


__all__ = ["execute_ai_prefill_run"]
