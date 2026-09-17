from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus


AiPrefillRunDispatcher = Callable[[UUID, UUID], None]


@dataclass(frozen=True, slots=True)
class AiPrefillReconcileReport:
    dispatched: int = 0
    recovered: int = 0
    dispatch_failures: int = 0


class AiPrefillRunReconciler:
    """Recover queued AI runs whose broker dispatch lease expired."""

    def __init__(
        self,
        *,
        dispatch_timeout: timedelta = timedelta(seconds=60),
        worker_timeout: timedelta = timedelta(minutes=5),
        batch_size: int = 100,
    ) -> None:
        if dispatch_timeout <= timedelta(0) or worker_timeout <= timedelta(0):
            raise ValueError("Recovery timeouts must be positive")
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        self.dispatch_timeout = dispatch_timeout
        self.worker_timeout = worker_timeout
        self.batch_size = batch_size

    def reconcile(
        self,
        factory: sessionmaker[Session],
        dispatcher: AiPrefillRunDispatcher,
        *,
        now: datetime | None = None,
    ) -> AiPrefillReconcileReport:
        checked_at = self._now(now)
        prepared: list[tuple[UUID, UUID]] = []
        recovered = 0
        with factory.begin() as session:
            stale_runs = list(
                session.scalars(
                    select(AiExtractionRun)
                    .where(
                        AiExtractionRun.status == AiExtractionRunStatus.RUNNING,
                        func.coalesce(
                            AiExtractionRun.heartbeat_at,
                            AiExtractionRun.started_at,
                            AiExtractionRun.dispatched_at,
                            AiExtractionRun.queued_at,
                        )
                        <= checked_at - self.worker_timeout,
                    )
                    .order_by(
                        func.coalesce(
                            AiExtractionRun.heartbeat_at,
                            AiExtractionRun.started_at,
                            AiExtractionRun.dispatched_at,
                            AiExtractionRun.queued_at,
                        ),
                        AiExtractionRun.id,
                    )
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for run in stale_runs:
                run.status = AiExtractionRunStatus.QUEUED
                run.error_summary = "Worker lease expired; queued for retry"
                run.started_at = None
                run.heartbeat_at = None
                run.completed_at = None
                run.dispatch_token = uuid4()
                run.dispatched_at = checked_at
                prepared.append((run.id, run.dispatch_token))
                recovered += 1

            remaining = max(0, self.batch_size - len(prepared))
            queued_runs = list(
                session.scalars(
                    select(AiExtractionRun)
                    .where(
                        AiExtractionRun.status == AiExtractionRunStatus.QUEUED,
                        (
                            AiExtractionRun.dispatched_at.is_(None)
                            | (
                                AiExtractionRun.dispatched_at
                                <= checked_at - self.dispatch_timeout
                            )
                        ),
                    )
                    .order_by(AiExtractionRun.queued_at, AiExtractionRun.id)
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            ) if remaining else []
            for run in queued_runs:
                run.dispatch_token = uuid4()
                run.dispatched_at = checked_at
                prepared.append((run.id, run.dispatch_token))
            session.flush()

        dispatch_failures = 0
        for run_id, token in prepared:
            try:
                dispatcher(run_id, token)
            except Exception:
                dispatch_failures += 1
                with factory.begin() as session:
                    run = session.scalar(
                        select(AiExtractionRun)
                        .where(AiExtractionRun.id == run_id)
                        .with_for_update()
                    )
                    if (
                        run is not None
                        and run.status is AiExtractionRunStatus.QUEUED
                        and run.dispatch_token == token
                    ):
                        run.dispatched_at = None

        return AiPrefillReconcileReport(
            dispatched=len(prepared) - dispatch_failures,
            recovered=recovered,
            dispatch_failures=dispatch_failures,
        )

    def claim_delivery(
        self,
        session: Session,
        *,
        run_id: UUID,
        delivery_token: UUID,
        now: datetime | None = None,
    ) -> AiExtractionRun | None:
        checked_at = self._now(now)
        run = session.scalar(
            select(AiExtractionRun)
            .where(AiExtractionRun.id == run_id)
            .with_for_update()
        )
        if (
            run is None
            or run.status is not AiExtractionRunStatus.QUEUED
            or run.dispatch_token != delivery_token
        ):
            return None
        run.status = AiExtractionRunStatus.RUNNING
        run.started_at = checked_at
        run.heartbeat_at = checked_at
        run.completed_at = None
        run.error_summary = None
        session.flush()
        return run

    def heartbeat_delivery(
        self,
        session: Session,
        *,
        run_id: UUID,
        delivery_token: UUID,
        now: datetime | None = None,
    ) -> bool:
        run = session.scalar(
            select(AiExtractionRun)
            .where(AiExtractionRun.id == run_id)
            .with_for_update()
        )
        if not self._is_current_delivery(run, delivery_token):
            return False
        run.heartbeat_at = self._now(now)
        session.flush()
        return True

    def fail_delivery(
        self,
        session: Session,
        *,
        run_id: UUID,
        delivery_token: UUID,
        error_summary: str,
        now: datetime | None = None,
    ) -> bool:
        run = session.scalar(
            select(AiExtractionRun)
            .where(AiExtractionRun.id == run_id)
            .with_for_update()
        )
        if not self._is_current_delivery(run, delivery_token):
            return False
        completed_at = self._now(now)
        run.status = AiExtractionRunStatus.FAILED
        run.error_summary = error_summary.strip()[:512] or "AI prefill failed"
        run.heartbeat_at = completed_at
        run.completed_at = completed_at
        session.flush()
        return True

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        checked_at = value or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return checked_at.astimezone(UTC)

    @staticmethod
    def _is_current_delivery(
        run: AiExtractionRun | None,
        delivery_token: UUID,
    ) -> bool:
        return bool(
            run is not None
            and run.status is AiExtractionRunStatus.RUNNING
            and run.dispatch_token == delivery_token
        )


__all__ = [
    "AiPrefillReconcileReport",
    "AiPrefillRunDispatcher",
    "AiPrefillRunReconciler",
]
