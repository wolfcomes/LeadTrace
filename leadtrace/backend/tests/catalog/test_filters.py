from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai_prefill.models import AiExtractionRun
from app.ai_tasks.models import AiTask
from app.assets.models import Asset
from app.catalog.models import PaperSource
from app.papers.models import Paper
from app.users.models import UserRole
from app.workspaces.models import PaperWorkspace, ReviewTask, WorkspaceState, ReviewTaskState
from tests.catalog.test_api import catalog_client, _login


def _workspace(fixture, paper_id, *, reviewer=True, archived=False):
    with fixture.session_factory.begin() as session:
        task = ReviewTask(paper_id=paper_id, created_by_id=fixture.admin_id,
            assigned_reviewer_id=fixture.reviewer_id if reviewer else None,
            status=ReviewTaskState.ARCHIVED if archived else ReviewTaskState.ASSIGNED if reviewer else ReviewTaskState.UNASSIGNED)
        session.add(task); session.flush()
        workspace = PaperWorkspace(paper_id=paper_id, review_task_id=task.id,
            state=WorkspaceState.ARCHIVED if archived else WorkspaceState.EDITING, version=1)
        session.add(workspace); session.flush()
        return workspace.id


def _job(fixture, paper_id, workspace_id, *, state='queued', action='prefill', delivery='pending', age=0):
    with fixture.session_factory.begin() as session:
        job = AiTask(paper_id=paper_id,workspace_id=workspace_id,requested_by_id=fixture.admin_id,
            idempotency_key=str(uuid4()),request_digest='test',action=action,preset_id='test',model='synthetic',
            reasoning_effort='high',adapter='codex',workspace_version=1,task_version=1,source_sha256='a'*64,
            timeout_seconds=60,state=state,delivery_state=delivery,stage=state,
            created_at=datetime.now(timezone.utc)-timedelta(days=age),config={},result_summary={})
        session.add(job); session.flush()
        return job.id


def test_metadata_filters_apply_before_pagination_and_options_hide_removed(catalog_client):
    f = catalog_client
    _login(f.client, UserRole.ADMIN)
    with f.session_factory.begin() as s:
        paper = s.get(Paper, f.paper_ids[-1]); paper.journal='Other Journal'; paper.publication_year=2025; paper.volume='S1'; paper.issue='2-3'
        removed = s.get(Paper, f.paper_ids[-2]); removed.journal='Removed Journal'; removed.removed_at=datetime.now(timezone.utc); removed.removed_by_id=f.admin_id; removed.removal_reason='test'
    params=dict(journal='Other Journal',year_from=2025,year_to=2025,volume='S1',issue='2-3',limit=1)
    result=f.client.get('/api/v2/admin/papers',params=params)
    assert result.status_code==200
    assert result.json()['total']==1
    assert result.json()['items'][0]['id']==str(f.paper_ids[-1])
    assert f.client.get('/api/v2/admin/papers',params={**params,'search':'no match'}).json()['total']==0
    options=f.client.get('/api/v2/admin/papers/filter-options')
    assert options.status_code==200
    assert options.json()=={'journals':['Journal of Medicinal Chemistry','Other Journal'],'years':[2025,2024],'volumes':['67','S1'],'issues':['2-3','5']}
    assert f.client.get('/api/v2/admin/papers',params={'year_from':2026,'year_to':2024}).status_code==422
    assert f.client.get('/api/v2/admin/papers',params={'assignment_status':'bad'}).status_code==422
    assert f.client.get('/api/v2/admin/papers',params={'prefill_status':'bad'}).status_code==422


def test_assignment_and_prefill_follow_current_workspace_not_review_jobs(catalog_client):
    f=catalog_client; _login(f.client,UserRole.ADMIN)
    p0,p1,p2,p3,p4=f.paper_ids[:5]
    w0=_workspace(f,p0); w1=_workspace(f,p1); old=_workspace(f,p2,archived=True); w2=_workspace(f,p2,reviewer=False)
    w3=_workspace(f,p3); w4=_workspace(f,p4)
    _job(f,p0,w0,state='running'); _job(f,p1,w1,state='needs_revision',delivery='applied',age=2)
    _job(f,p1,w1,state='failed',action='revise'); _job(f,p2,old,state='completed',delivery='applied')
    _job(f,p3,w3,state='cancelled'); _job(f,p4,w4,state='failed',age=2)
    with f.session_factory.begin() as s:
        s.add(AiExtractionRun(paper_id=p4,workspace_id=w4,requested_by_id=f.admin_id,
            starting_workspace_version=1,status='succeeded',engine='legacy',engine_version='1'))
    for status,ids in [('running',[p0]),('succeeded',[p1,p4]),('superseded',[p3]),('failed',[])]:
        response=f.client.get('/api/v2/admin/papers',params={'prefill_status':status})
        assert response.status_code==200
        assert {i['id'] for i in response.json()['items']}=={str(i) for i in ids}
        assert all(i['ai_prefill']['effective_status']==status for i in response.json()['items'])
    assigned=f.client.get('/api/v2/admin/papers',params={'assignment_status':'assigned'}).json()
    assert assigned['total']==4
    assert f.client.get('/api/v2/admin/papers',params={'assignment_status':'unassigned','prefill_status':'not_started'}).json()['total']==16


def test_ai_jobs_filter_before_limit_and_return_true_total_and_offset(catalog_client):
    f=catalog_client; _login(f.client,UserRole.ADMIN)
    p0,p1=f.paper_ids[:2]; w0=_workspace(f,p0); w1=_workspace(f,p1)
    ids=[_job(f,p0,w0,state='completed',delivery='applied',age=i+1) for i in range(3)]
    _job(f,p1,w1,state='running')
    with f.session_factory.begin() as s:s.get(Paper,p0).journal='Selected'
    response=f.client.get('/api/v2/admin/ai-tasks',params={'journal':'Selected','limit':1,'offset':1})
    assert response.status_code==200
    body=response.json(); assert body['total']==3; assert len(body['items'])==1
    assert body['items'][0]['id']==str(ids[1]); assert body['offset']==1; assert body['limit']==1


def test_files_match_related_derived_assets_and_exclude_unattached_only_when_filtering(catalog_client):
    f=catalog_client; _login(f.client,UserRole.ADMIN)
    with f.session_factory.begin() as s:
        paper=s.get(Paper,f.paper_ids[-1]);paper.journal='Selected'
        source=s.get(PaperSource,paper.source_id)
        parent=s.get(Asset,source.asset_id)
        def asset(name,source_id=None):
            row=Asset(storage_key=name,original_filename=name,sha256=name.ljust(64,'0'),byte_size=1,
                mime_type='image/png',category='evidence_crop',access_level='reviewer',integrity_state='verified',
                source_asset_id=source_id,derivation_metadata={},source_metadata={})
            s.add(row);s.flush();return row.id
        child=asset('child',parent.id);grandchild=asset('grandchild',child);loose=asset('loose')
        expected={str(parent.id),str(child),str(grandchild)}
    response=f.client.get('/api/v1/admin/files',params={'journal':'Selected'})
    assert response.status_code==200
    assert {i['id'] for i in response.json()}==expected
    assert str(loose) in {i['id'] for i in f.client.get('/api/v1/admin/files').json()}


def test_files_include_historical_only_and_shared_assets_without_leaking_removed(catalog_client):
    from app.workspaces.models import ChangeEvent
    f=catalog_client;_login(f.client,UserRole.ADMIN)
    live,removed=f.paper_ids[:2];wl=_workspace(f,live);wr=_workspace(f,removed)
    with f.session_factory.begin() as s:
        s.get(Paper,live).journal='Selected'
        p=s.get(Paper,removed);p.journal='Removed';p.removed_at=datetime.now(timezone.utc);p.removed_by_id=f.admin_id;p.removal_reason='test'
        def asset(name):
            a=Asset(storage_key=name,original_filename=name,sha256=name.ljust(64,'0'),byte_size=1,
                mime_type='image/png',category='evidence_crop',access_level='reviewer',integrity_state='verified',
                derivation_metadata={},source_metadata={});s.add(a);s.flush();return a.id
        historical,shared,hidden=asset('historical'),asset('shared'),asset('hidden')
        for paper_id,w,ids in [(live,wl,[historical,shared]),(removed,wr,[shared,hidden])]:
            s.add(ChangeEvent(paper_id=paper_id,workspace_id=w,entity_type='evidence',entity_id=uuid4(),
                action='test',before_value={'old':[{'crop_asset_id':str(i)} for i in ids]},after_value={},actor_kind='system'))
    filtered=f.client.get('/api/v1/admin/files',params={'journal':'Selected'})
    assert filtered.status_code==200
    ids={i['id'] for i in filtered.json()}
    assert {str(historical),str(shared)} <= ids
    assert str(hidden) not in ids
    assert f.client.get('/api/v1/admin/files',params={'journal':'Removed'}).json()==[]
    assert str(hidden) not in {i['id'] for i in f.client.get('/api/v1/admin/files').json()}


@pytest.mark.parametrize('path',['/api/v2/admin/papers','/api/v2/admin/papers/filter-options','/api/v2/admin/submissions','/api/v1/admin/files','/api/v2/admin/ai-tasks'])
def test_filter_endpoints_keep_reviewer_permissions(catalog_client,path):
    f=catalog_client;_login(f.client,UserRole.REVIEWER)
    assert f.client.get(path,params={'journal':'Selected'}).status_code==403
