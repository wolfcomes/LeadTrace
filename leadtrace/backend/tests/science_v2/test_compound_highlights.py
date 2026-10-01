from uuid import UUID
from sqlalchemy import select
from app.compounds.models import CompoundHighlight
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState
from app.workspaces.snapshot import build_paper_snapshot
from app.workspaces.validation import validate_submission
from app.publications.schemas import PublishedPaperSnapshotResponse


def seed(ctx):
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    compound = ctx.client.post(base+'/compounds', headers=headers, json={'expected_workspace_version':1,'compound_label':'1'}).json()['compound']
    ws = ctx.client.get(base).json()
    response = ctx.client.post(base+'/evidence', headers=headers, json={'expected_workspace_version':2, 'kind':'text', 'source_sha256':ws['source']['sha256'], 'page_number':1, 'quoted_text':'Synthetic author selection statement'})
    assert response.status_code == 201, response.text
    data = {'expected_workspace_version':3,'compound_id':compound['id'], 'evidence_id':response.json()['evidence']['id'], 'role':'study_start','scope':'Series A','rationale':'Source-backed starting lead'}
    return headers,base,data


def test_highlight_boundaries_versions_evidence_history_and_frozen_projection(science_api_context):
    ctx=science_api_context
    headers,base,data=seed(ctx)
    assert ctx.client.post(base+'/compound-highlights',json=data).status_code==403
    response=ctx.client.post(base+'/compound-highlights',headers=headers,json=data)
    assert response.status_code==201,response.text
    item=response.json()['highlight'];hid=item['id']
    assert item['review_status']=='draft'
    assert response.json()['workspace_version']==4
    assert ctx.client.get(base+'/compound-highlights').json()['items']==[item]
    with ctx.session_factory.begin() as session:
        snap=build_paper_snapshot(session,ctx.first.workspace_id)
        assert snap['compound_highlights'][0]['id']==hid
        public=PublishedPaperSnapshotResponse.model_validate(snap).model_dump(mode='json')
        assert public['compound_highlights'][0]['rationale']==data['rationale']
        assert 'workspace_id' not in public['compound_highlights'][0]
        assert any(b.code=='COMPOUND_HIGHLIGHT_NOT_REVIEWED' for b in validate_submission(session,ctx.first.workspace_id).blockers)
        event=session.scalar(select(ChangeEvent).where(ChangeEvent.entity_id==UUID(hid)))
        assert event.after_value['evidence_id']==data['evidence_id']
    assert ctx.client.post(base+'/compound-highlights',headers=headers,json={**data,'expected_workspace_version':4}).status_code==409
    assert ctx.client.post(base+'/compound-highlights',headers=headers,json={**data,'expected_workspace_version':4,'evidence_id':str(ctx.second.paper_id)}).status_code==422
    assert ctx.client.patch('/api/v2/compound-highlights/'+hid,headers=headers,json={'expected_workspace_version':3,'rationale':'stale'}).status_code==409
    for endpoint,key in [('compounds','compound_id'),('evidence','evidence_id')]:
        blocked=ctx.client.request('DELETE',f'/api/v2/{endpoint}/{data[key]}',headers=headers,json={'expected_workspace_version':4})
        assert blocked.status_code==409,blocked.text
    updated=ctx.client.patch('/api/v2/compound-highlights/'+hid,headers=headers,json={'expected_workspace_version':4,'review_status':'reviewer_confirmed'})
    assert updated.status_code==200,updated.text
    with ctx.session_factory.begin() as session:
        assert not any(b.code=='COMPOUND_HIGHLIGHT_NOT_REVIEWED' for b in validate_submission(session,ctx.first.workspace_id).blockers)
        assert snap['compound_highlights'][0]['review_status']=='draft'
    updated=ctx.client.patch('/api/v2/compound-highlights/'+hid,headers=headers,json={'expected_workspace_version':5,'rationale':'Changed source interpretation'})
    assert updated.json()['highlight']['review_status']=='draft'
    ctx.login('science.api.other')
    assert ctx.client.get(base+'/compound-highlights').status_code==404
    headers={'X-CSRF-Token':ctx.login('science.api.reviewer')}
    result=ctx.client.request('DELETE','/api/v2/compound-highlights/'+hid,headers=headers,json={'expected_workspace_version':6})
    assert result.status_code==200,result.text
    with ctx.session_factory.begin() as session:
        assert 'compound_highlights' not in build_paper_snapshot(session,ctx.first.workspace_id)


def test_highlight_invalidates_group_viewing_and_allows_multiple_roles(science_api_context):
    ctx=science_api_context;headers,base,data=seed(ctx)
    before=ctx.client.get(base+'/review-progress').json()['items'][0]
    view={key:before[key] for key in ('kind','entity_id','signature')}|{'viewed':True}
    assert ctx.client.post(base+'/views',headers=headers,json=view).status_code==200
    created=ctx.client.post(base+'/compound-highlights',headers=headers,json=data)
    assert created.status_code==201,created.text
    after=ctx.client.get(base+'/review-progress').json()['items'][0]
    assert not after['viewed'] and before['signature']!=after['signature']
    response=ctx.client.post(base+'/compound-highlights',headers=headers,json={**data,'expected_workspace_version':4,'role':'paper_selected','review_status':'unresolved','review_hint':'Choice ambiguous'})
    assert response.status_code==201,response.text
    assert ctx.client.get(base+'/compound-highlights').json()['total']==2
    with ctx.session_factory.begin() as session:
        session.get(PaperWorkspace,ctx.first.workspace_id).state=WorkspaceState.SUBMITTED
    blocked=ctx.client.patch('/api/v2/compound-highlights/'+response.json()['highlight']['id'],headers=headers,json={'expected_workspace_version':5,'scope':'Other'})
    assert blocked.status_code==409,blocked.text
