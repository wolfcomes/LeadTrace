from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.config import Settings
from app.ai_tasks.models import AiTask, AiTaskSettings
from app.ai_tasks.service import claim_next, cancel_job, set_limit, invalidate_paper_jobs


def seed(session_factory, count=7):
    from tests.ai_prefill.test_apply import create_ai_context
    context=create_ai_context(session_factory)
    with session_factory.begin() as s:
        for i in range(count):
            # Independent logical papers are unnecessary for claim-capacity test;
            # enqueue owns the real same-paper exclusion.
            s.add(AiTask(id=uuid4(),paper_id=context.paper_id,workspace_id=context.workspace_id,
                requested_by_id=context.admin_id,idempotency_key=str(uuid4()),request_digest=str(i),
                action='prefill',preset_id='test',model='synthetic',reasoning_effort='high',adapter='codex',
                workspace_version=1,task_version=1,source_sha256='a'*64,timeout_seconds=60,state='queued',
                delivery_state='pending',stage='queued',config={},result_summary={}))
    return context


def test_global_capacity_is_atomic_and_cancel_keeps_running_slot(auth_session_factory):
    seed(auth_session_factory)
    def claim(_):
        with auth_session_factory.begin() as s:return claim_next(s,owner='test-worker')
    with ThreadPoolExecutor(max_workers=7) as pool:
        ids=list(pool.map(claim,range(7)))
    active=[i for i in ids if i]
    assert len(active)==4
    with auth_session_factory.begin() as s:
        job=s.get(AiTask,active[0]);cancel_job(s,job)
        assert job.state=='cancel_requested'
        assert claim_next(s,owner='other') is None
        set_limit(s,2)
    with auth_session_factory.begin() as s:
        assert claim_next(s,owner='other') is None


def test_queued_cancel_never_launches_and_invalidation_retains_active_capacity(auth_session_factory):
    c=seed(auth_session_factory,2)
    with auth_session_factory.begin() as s:
        claimed=claim_next(s,owner='test')
        invalidate_paper_jobs(s,c.paper_id,'assignment_recalled')
    with auth_session_factory.begin() as s:
        rows=list(s.scalars(select(AiTask)))
        assert {r.state for r in rows}=={'cancel_requested','superseded'}
        assert all(r.result_summary['invalidated'] for r in rows)
        assert claim_next(s,owner='test') is None
