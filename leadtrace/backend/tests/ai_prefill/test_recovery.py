from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus

from .test_apply import AiContext, _queue, ai_context  # noqa: F401


NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


def test_committed_queued_run_is_redispatched_after_dispatch_lease_expires(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.dispatch_token is not None
        assert run.dispatched_at is not None
        dispatch_token = run.dispatch_token
        initial_dispatched_at = run.dispatched_at

    from app.ai_prefill.reconciler import AiPrefillRunReconciler

    deliveries: list[tuple[UUID, UUID]] = []
    report = AiPrefillRunReconciler(
        dispatch_timeout=timedelta(seconds=30)
    ).reconcile(
        ai_context.session_factory,
        lambda queued_run_id, token: deliveries.append((queued_run_id, token)),
        now=initial_dispatched_at + timedelta(seconds=31),
    )

    assert report.dispatched == 1
    assert report.dispatch_failures == 0
    assert deliveries[0][0] == run_id
    assert deliveries[0][1] != dispatch_token
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.status is AiExtractionRunStatus.QUEUED
        assert run.dispatch_token == deliveries[0][1]
        assert run.dispatched_at == initial_dispatched_at + timedelta(seconds=31)


def test_reconciler_releases_failed_broker_dispatch_for_immediate_retry(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None and run.dispatched_at is not None
        initial_dispatched_at = run.dispatched_at

    from app.ai_prefill.reconciler import AiPrefillRunReconciler

    reconciler = AiPrefillRunReconciler(dispatch_timeout=timedelta(seconds=30))

    def unavailable_broker(_: UUID, __: UUID) -> None:
        raise ConnectionError("Redis unavailable")

    failed = reconciler.reconcile(
        ai_context.session_factory,
        unavailable_broker,
        now=initial_dispatched_at + timedelta(seconds=31),
    )
    deliveries: list[tuple[UUID, UUID]] = []
    recovered = reconciler.reconcile(
        ai_context.session_factory,
        lambda queued_run_id, token: deliveries.append((queued_run_id, token)),
        now=initial_dispatched_at + timedelta(seconds=32),
    )

    assert failed.dispatch_failures == 1
    assert failed.dispatched == 0
    assert recovered.dispatched == 1
    assert deliveries[0][0] == run_id


def test_expired_running_run_is_fenced_and_redispatched(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None and run.dispatch_token is not None
        stale_token = run.dispatch_token
        run.status = AiExtractionRunStatus.RUNNING
        run.started_at = NOW - timedelta(minutes=6)
        run.heartbeat_at = NOW - timedelta(minutes=6)

    from app.ai_prefill.contracts import AiPrefillPayload
    from app.ai_prefill.reconciler import AiPrefillRunReconciler
    from app.ai_prefill.service import AiPrefillService
    from .test_contract import complete_payload

    deliveries: list[tuple[UUID, UUID]] = []
    report = AiPrefillRunReconciler(
        worker_timeout=timedelta(minutes=5)
    ).reconcile(
        ai_context.session_factory,
        lambda queued_run_id, token: deliveries.append((queued_run_id, token)),
        now=NOW,
    )

    assert report.recovered == 1
    assert report.dispatched == 1
    assert deliveries[0][0] == run_id
    assert deliveries[0][1] != stale_token
    with ai_context.session_factory.begin() as session:
        stale_apply = AiPrefillService().apply(
            session,
            run_id=run_id,
            dispatch_token=stale_token,
            payload=AiPrefillPayload.model_validate(complete_payload()),
        )
        assert stale_apply.applied is False
        assert stale_apply.idempotent is True
        assert stale_apply.run.status is AiExtractionRunStatus.QUEUED


def test_recent_running_heartbeat_prevents_recovery(
    ai_context: AiContext,
) -> None:
    run_id = _queue(ai_context)
    with ai_context.session_factory.begin() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        run.status = AiExtractionRunStatus.RUNNING
        run.started_at = NOW - timedelta(minutes=6)
        run.heartbeat_at = NOW - timedelta(seconds=10)

    from app.ai_prefill.reconciler import AiPrefillRunReconciler

    deliveries: list[tuple[UUID, UUID]] = []
    report = AiPrefillRunReconciler(
        worker_timeout=timedelta(minutes=5)
    ).reconcile(
        ai_context.session_factory,
        lambda queued_run_id, token: deliveries.append((queued_run_id, token)),
        now=NOW,
    )

    assert report.recovered == 0
    assert report.dispatched == 0
    assert deliveries == []
