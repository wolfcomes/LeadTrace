from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.models import (
    CropJob,
    CropJobAttempt,
    CropJobAttemptStatus,
    CropJobStatus,
)
from app.maintenance.service import MaintenanceService


JobDispatcher = Callable[[UUID, UUID], None]


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    dispatched: int = 0
    recovered: int = 0
    exhausted: int = 0
    dispatch_failures: int = 0
    maintenance_active: bool = False


class JobReconciler:
    """Recover PostgreSQL-authoritative crop jobs using at-least-once delivery."""

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
        dispatcher: JobDispatcher,
        *,
        now: datetime | None = None,
    ) -> ReconcileReport:
        checked_at = self._now(now)
        prepared: list[tuple[UUID, UUID]] = []
        recovered = 0
        exhausted = 0
        with factory.begin() as session:
            maintenance = MaintenanceService()
            maintenance.acquire_write_guard(session)
            if maintenance.current(session) is not None:
                return ReconcileReport(maintenance_active=True)

            stale_jobs = list(
                session.scalars(
                    select(CropJob)
                    .where(
                        CropJob.status == CropJobStatus.RUNNING,
                        func.coalesce(
                            CropJob.heartbeat_at,
                            CropJob.started_at,
                            CropJob.updated_at,
                            CropJob.created_at,
                        )
                        <= checked_at - self.worker_timeout,
                    )
                    .order_by(
                        func.coalesce(
                            CropJob.heartbeat_at,
                            CropJob.started_at,
                            CropJob.updated_at,
                            CropJob.created_at,
                        ),
                        CropJob.id,
                    )
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for job in stale_jobs:
                self._mark_current_attempt_stale(session, job, checked_at)
                job.completed_at = None
                job.heartbeat_at = None
                job.started_at = None
                if job.attempt_count >= job.max_attempts:
                    job.status = CropJobStatus.FAILED
                    job.error_message = (
                        "Worker lease expired; retry limit reached"
                    )
                    job.completed_at = checked_at
                    job.dispatch_token = None
                    job.dispatched_at = None
                    exhausted += 1
                else:
                    job.status = CropJobStatus.PENDING
                    job.error_message = "Worker lease expired; queued for retry"
                    job.dispatch_token = uuid4()
                    job.dispatched_at = checked_at
                    prepared.append((job.id, job.dispatch_token))
                    recovered += 1

            remaining = max(0, self.batch_size - len(prepared))
            if remaining:
                pending_jobs = list(
                    session.scalars(
                        select(CropJob)
                        .where(
                            CropJob.status == CropJobStatus.PENDING,
                            CropJob.superseded_by_id.is_(None),
                            CropJob.attempt_count < CropJob.max_attempts,
                            (
                                CropJob.dispatched_at.is_(None)
                                | (
                                    CropJob.dispatched_at
                                    <= checked_at - self.dispatch_timeout
                                )
                            ),
                        )
                        .order_by(CropJob.created_at, CropJob.id)
                        .limit(remaining)
                        .with_for_update(skip_locked=True)
                    )
                )
                for job in pending_jobs:
                    if job.dispatch_token is None:
                        job.dispatch_token = uuid4()
                    job.dispatched_at = checked_at
                    prepared.append((job.id, job.dispatch_token))
            session.flush()

        dispatch_failures = 0
        for job_id, token in prepared:
            try:
                dispatcher(job_id, token)
            except Exception:
                dispatch_failures += 1
                with factory.begin() as session:
                    job = session.scalar(
                        select(CropJob)
                        .where(CropJob.id == job_id)
                        .with_for_update()
                    )
                    if (
                        job is not None
                        and job.status is CropJobStatus.PENDING
                        and job.dispatch_token == token
                    ):
                        job.dispatched_at = None

        return ReconcileReport(
            dispatched=len(prepared) - dispatch_failures,
            recovered=recovered,
            exhausted=exhausted,
            dispatch_failures=dispatch_failures,
        )

    def claim_delivery(
        self,
        session: Session,
        *,
        job_id: UUID,
        delivery_token: UUID,
        now: datetime | None = None,
    ) -> CropJobAttempt | None:
        checked_at = self._now(now)
        maintenance = MaintenanceService()
        maintenance.acquire_write_guard(session)
        if maintenance.current(session) is not None:
            return None
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if (
            job is None
            or job.status is not CropJobStatus.PENDING
            or job.superseded_by_id is not None
            or job.dispatch_token != delivery_token
            or job.attempt_count >= job.max_attempts
        ):
            return None
        job.attempt_count += 1
        job.status = CropJobStatus.RUNNING
        job.started_at = checked_at
        job.heartbeat_at = checked_at
        job.completed_at = None
        attempt = CropJobAttempt(
            job_id=job.id,
            attempt_number=job.attempt_count,
            delivery_token=delivery_token,
            status=CropJobAttemptStatus.RUNNING,
            started_at=checked_at,
            heartbeat_at=checked_at,
        )
        session.add(attempt)
        session.flush()
        return attempt

    def heartbeat_delivery(
        self,
        session: Session,
        *,
        job_id: UUID,
        delivery_token: UUID,
        now: datetime | None = None,
    ) -> bool:
        checked_at = self._now(now)
        maintenance = MaintenanceService()
        maintenance.acquire_write_guard(session)
        if maintenance.current(session) is not None:
            return False
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if not self._is_current_delivery(job, delivery_token):
            return False
        attempt = self._current_attempt(session, job)
        if attempt is None or attempt.status is not CropJobAttemptStatus.RUNNING:
            return False
        job.heartbeat_at = checked_at
        attempt.heartbeat_at = checked_at
        session.flush()
        return True

    def complete_delivery(
        self,
        session: Session,
        *,
        job_id: UUID,
        delivery_token: UUID,
        asset_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        checked_at = self._now(now)
        maintenance = MaintenanceService()
        maintenance.acquire_write_guard(session)
        if maintenance.current(session) is not None:
            return False
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if not self._is_current_delivery(job, delivery_token):
            return False
        attempt = self._current_attempt(session, job)
        if attempt is None or attempt.status is not CropJobAttemptStatus.RUNNING:
            return False
        job.status = CropJobStatus.COMPLETED
        job.asset_id = asset_id
        job.heartbeat_at = checked_at
        job.completed_at = checked_at
        job.error_message = None
        attempt.status = CropJobAttemptStatus.COMPLETED
        attempt.heartbeat_at = checked_at
        attempt.completed_at = checked_at
        session.flush()
        return True

    def fail_delivery(
        self,
        session: Session,
        *,
        job_id: UUID,
        delivery_token: UUID,
        error_message: str,
        now: datetime | None = None,
    ) -> bool:
        checked_at = self._now(now)
        maintenance = MaintenanceService()
        maintenance.acquire_write_guard(session)
        if maintenance.current(session) is not None:
            return False
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if not self._is_current_delivery(job, delivery_token):
            return False
        attempt = self._current_attempt(session, job)
        if attempt is None or attempt.status is not CropJobAttemptStatus.RUNNING:
            return False
        message = error_message.strip()[:2000] or "Background job failed"
        attempt.status = CropJobAttemptStatus.FAILED
        attempt.completed_at = checked_at
        attempt.error_message = message
        job.started_at = None
        job.heartbeat_at = None
        job.dispatched_at = None
        job.dispatch_token = None
        job.error_message = message
        if job.attempt_count >= job.max_attempts:
            job.status = CropJobStatus.FAILED
            job.completed_at = checked_at
        else:
            job.status = CropJobStatus.PENDING
            job.completed_at = None
        session.flush()
        return True

    def defer_delivery(
        self,
        session: Session,
        *,
        job_id: UUID,
        delivery_token: UUID,
        reason: str,
        now: datetime | None = None,
    ) -> bool:
        """Release a claimed delivery without consuming its retry budget."""

        checked_at = self._now(now)
        MaintenanceService().acquire_write_guard(session)
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if not self._is_current_delivery(job, delivery_token):
            return False
        attempt = self._current_attempt(session, job)
        if attempt is None or attempt.status is not CropJobAttemptStatus.RUNNING:
            return False
        message = reason.strip()[:2000] or "Background job delivery deferred"
        attempt.status = CropJobAttemptStatus.STALE
        attempt.completed_at = checked_at
        attempt.error_message = message
        job.status = CropJobStatus.PENDING
        job.max_attempts += 1
        job.dispatch_token = None
        job.dispatched_at = None
        job.started_at = None
        job.heartbeat_at = None
        job.completed_at = None
        job.error_message = message
        session.flush()
        return True

    def supersede(
        self,
        session: Session,
        *,
        job_id: UUID,
        superseded_by_id: UUID,
        now: datetime | None = None,
    ) -> CropJob:
        if job_id == superseded_by_id:
            raise ValueError("A job cannot supersede itself")
        replacement = session.get(CropJob, superseded_by_id)
        if replacement is None:
            raise LookupError("Replacement job not found")
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if job is None:
            raise LookupError("Job not found")
        if job.status is CropJobStatus.RUNNING:
            attempt = self._current_attempt(session, job)
            if attempt is not None and attempt.status is CropJobAttemptStatus.RUNNING:
                attempt.status = CropJobAttemptStatus.STALE
                attempt.completed_at = self._now(now)
                attempt.error_message = "Superseded by newer work"
        job.status = CropJobStatus.SUPERSEDED
        job.superseded_by_id = replacement.id
        job.dispatch_token = None
        job.dispatched_at = None
        job.heartbeat_at = None
        job.completed_at = self._now(now)
        job.error_message = "Superseded by newer work"
        session.flush()
        return job

    def retry_failed(
        self,
        session: Session,
        *,
        job_id: UUID,
        retry_attempts: int = 3,
    ) -> CropJob:
        if retry_attempts < 1 or retry_attempts > 10:
            raise ValueError("retry_attempts must be between 1 and 10")
        job = session.scalar(
            select(CropJob).where(CropJob.id == job_id).with_for_update()
        )
        if job is None:
            raise LookupError("Job not found")
        if job.status is not CropJobStatus.FAILED:
            raise ValueError("Only failed jobs can be retried")
        job.status = CropJobStatus.PENDING
        job.max_attempts = job.attempt_count + retry_attempts
        job.dispatch_token = None
        job.dispatched_at = None
        job.started_at = None
        job.heartbeat_at = None
        job.completed_at = None
        job.error_message = None
        session.flush()
        return job

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        checked_at = value or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return checked_at.astimezone(UTC)

    @staticmethod
    def _current_attempt(
        session: Session,
        job: CropJob,
    ) -> CropJobAttempt | None:
        return session.scalar(
            select(CropJobAttempt)
            .where(
                CropJobAttempt.job_id == job.id,
                CropJobAttempt.attempt_number == job.attempt_count,
            )
            .with_for_update()
        )

    def _mark_current_attempt_stale(
        self,
        session: Session,
        job: CropJob,
        checked_at: datetime,
    ) -> None:
        attempt = self._current_attempt(session, job)
        if attempt is None or attempt.status is not CropJobAttemptStatus.RUNNING:
            return
        attempt.status = CropJobAttemptStatus.STALE
        attempt.completed_at = checked_at
        attempt.error_message = "Worker lease expired"

    @staticmethod
    def _is_current_delivery(job: CropJob | None, token: UUID) -> bool:
        return bool(
            job is not None
            and job.status is CropJobStatus.RUNNING
            and job.superseded_by_id is None
            and job.dispatch_token == token
        )


__all__ = ["JobDispatcher", "JobReconciler", "ReconcileReport"]
