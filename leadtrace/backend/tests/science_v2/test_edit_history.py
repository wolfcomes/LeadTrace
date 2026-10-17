from uuid import UUID
from sqlalchemy import select
from app.compounds.models import Compound
from app.workspaces.models import ChangeEvent, PaperWorkspace

def create(ctx, csrf, version=1, label='1'):
    r=ctx.client.post(f'/api/v2/workspaces/{ctx.first.workspace_id}/compounds',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':version,'compound_label':label,'display_name':'Example'})
    assert r.status_code == 201, r.text
    return r.json()['compound']['id']

def move(ctx,csrf,direction,version):
    return ctx.client.post(f'/api/v2/workspaces/{ctx.first.workspace_id}/edit-history/{direction}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':version})

def test_create_undo_redo_preserves_id_and_appends_history(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');cid=create(c,csrf)
    state=c.client.get(f'/api/v2/workspaces/{c.first.workspace_id}/edit-history')
    assert state.status_code == 200
    assert state.json()['undo_action'] == 'compound.create'
    r=move(c,csrf,'undo',2); assert r.status_code == 200,r.text
    assert r.json()['workspace_version']==3
    with c.session_factory() as s: assert s.get(Compound,UUID(cid)) is None
    r=move(c,csrf,'redo',3); assert r.status_code==200,r.text
    with c.session_factory() as s:
        assert s.get(Compound,UUID(cid)).compound_label=='1'
        assert s.get(PaperWorkspace,c.first.workspace_id).version==4
        assert [e.action for e in s.scalars(select(ChangeEvent).order_by(ChangeEvent.occurred_at))] == ['compound.create','workspace.undo','workspace.redo']

def test_new_edit_discards_redo_and_external_version_blocks_undo(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');create(c,csrf)
    assert move(c,csrf,'undo',2).status_code==200
    create(c,csrf,3,'2')
    assert move(c,csrf,'redo',4).status_code==409
    with c.session_factory.begin() as s: s.get(PaperWorkspace,c.first.workspace_id).version+=1
    assert move(c,csrf,'undo',5).status_code==409

def test_undo_rejects_stale_version_other_reviewer_and_readonly(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');create(c,csrf)
    assert move(c,csrf,'undo',1).status_code==409
    other=c.login('science.api.other')
    assert move(c,other,'undo',2).status_code==404
    csrf=c.login('science.api.reviewer')
    assert c.client.post(f'/api/v2/workspaces/{c.first.workspace_id}/edit-history/undo',json={'expected_workspace_version':2}).status_code==403
    from app.workspaces.models import WorkspaceState
    with c.session_factory.begin() as s:s.get(PaperWorkspace,c.first.workspace_id).state=WorkspaceState.SUBMITTED
    assert move(c,csrf,'undo',2).status_code==409

def test_update_delete_undo_restores_structure_dependency(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');cid=create(c,csrf)
    r=c.client.put(f'/api/v2/compounds/{cid}/structure',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':2,'status':'draft','input_method':'manual_smiles','smiles':'CCO','molfile':None})
    assert r.status_code==200,r.text
    r=c.client.request('DELETE',f'/api/v2/compounds/{cid}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':3})
    assert r.status_code==200,r.text
    assert move(c,csrf,'undo',4).status_code==200
    r=c.client.get(f'/api/v2/compounds/{cid}/structure');assert r.status_code==200
    assert r.json()['structure']['canonical_smiles']=='CCO'
    assert move(c,csrf,'undo',5).status_code==200
    assert c.client.get(f'/api/v2/compounds/{cid}/structure').json()['structure'] is None
    assert move(c,csrf,'redo',6).status_code==200
    assert c.client.get(f'/api/v2/compounds/{cid}/structure').json()['structure']['canonical_smiles']=='CCO'

def test_undo_does_not_resurrect_old_view_receipt(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');cid=create(c,csrf)
    url=f'/api/v2/workspaces/{c.first.workspace_id}'
    item=c.client.get(url+'/review-progress').json()['items'][0]
    assert c.client.post(url+'/views',headers={'X-CSRF-Token':csrf},json={k:item[k] for k in ('kind','entity_id','signature')}|{'viewed':True}).status_code==200
    assert c.client.patch(f'/api/v2/compounds/{cid}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':2,'description':'Changed'}).status_code==200
    assert move(c,csrf,'undo',3).status_code==200
    assert c.client.get(url+'/review-progress').json()['items'][0]['viewed'] is False

def test_undo_doi_conflict_rolls_back_without_exposing_database_details(science_api_context):
    from app.papers.models import Paper
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    with c.session_factory() as s:
        original_doi = s.get(Paper, c.first.paper_id).doi
    url = f'/api/v2/workspaces/{c.first.workspace_id}/bibliography'
    response = c.client.patch(url, headers={'X-CSRF-Token': csrf},
        json={'expected_workspace_version': 1, 'doi': None})
    assert response.status_code == 200, response.text
    with c.session_factory.begin() as s:
        s.get(Paper, c.second.paper_id).doi = original_doi
    response = move(c, csrf, 'undo', 2)
    assert response.status_code == 409, response.text
    assert response.json()['code'] == 'EDIT_HISTORY_CHANGED'
    assert 'uq_papers_doi' not in response.text
    with c.session_factory() as s:
        assert s.get(Paper, c.first.paper_id).doi is None
        assert s.get(PaperWorkspace, c.first.workspace_id).version == 2
        assert len(list(s.scalars(select(ChangeEvent)))) == 1
