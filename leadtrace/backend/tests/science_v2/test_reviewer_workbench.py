from uuid import UUID
from app.workspaces.models import PaperWorkspace, WorkspaceState
from app.workspaces.snapshot import build_paper_snapshot


def test_metadata_is_versioned_and_frozen_with_source_boundaries(science_api_context):
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    metadata = {'abstract': 'Original abstract.\nSecond paragraph.', 'abstract_source': 'Page 1, Abstract',
        'pdb_references': [{'pdb_id': '1abc', 'usage': 'cited_structure', 'source_page': 2,
                            'source_context': 'Previously reported structure', 'review_hint': 'Check ligand pairing'}]}
    response = ctx.client.patch(base+'/bibliography', headers=headers, json={'expected_workspace_version': 1, **metadata})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['bibliography']['abstract'] == metadata['abstract']
    assert data['bibliography']['pdb_references'][0]['pdb_id'] == '1ABC'
    with ctx.session_factory.begin() as session:
        snap = build_paper_snapshot(session, ctx.first.workspace_id)
        assert snap['paper']['abstract'] == metadata['abstract']
        assert snap['paper']['pdb_references'][0]['usage'] == 'cited_structure'
    invalid = ctx.client.patch(base+'/bibliography', headers=headers, json={'expected_workspace_version': 2,
        'pdb_references': [{'pdb_id': 'ATP', 'usage': 'unknown'}]})
    assert invalid.status_code == 422
    outside = ctx.client.patch(base+'/bibliography', headers=headers, json={'expected_workspace_version': 2,
        'pdb_references': [{'pdb_id': '1ABC', 'usage': 'unknown', 'source_page': 999}]})
    assert outside.status_code == 422
    stale = ctx.client.patch(base+'/bibliography', headers=headers, json={'expected_workspace_version': 1, 'abstract': 'stale'})
    assert stale.status_code == 409


def test_view_receipts_are_current_content_scoped_not_scientific_approval(science_api_context):
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    created = ctx.client.post(base+'/compounds', headers=headers, json={'expected_workspace_version': 1, 'compound_label': '1', 'review_hint': 'Verify core'})
    assert created.status_code == 201
    cid = created.json()['compound']['id']
    progress = ctx.client.get(base+'/review-progress')
    assert progress.status_code == 200, progress.text
    item = next(x for x in progress.json()['items'] if x['kind']=='compound' and x['entity_id']==cid)
    assert not item['viewed']
    assert {x['kind'] for x in progress.json()['items']} == {'compound'}
    assert {x['section_key'] for x in progress.json()['sections']} == {'compounds','lineages'}
    url = base+'/views'
    payload = {'kind': 'compound', 'entity_id': cid, 'signature': item['signature'], 'viewed': True}
    assert ctx.client.post(url, json=payload).status_code == 403
    assert ctx.client.post(url, headers=headers, json=payload).status_code == 200
    assert ctx.client.post(url, headers=headers, json=payload).status_code == 200
    assert ctx.client.get(base).json()['version'] == 2
    assert ctx.client.get(base+'/compounds').json()['items'][0]['review_hint'] == 'Verify core'
    updated = ctx.client.patch('/api/v2/compounds/'+cid, headers=headers, json={'expected_workspace_version': 2, 'description': 'Changed content'})
    assert updated.status_code == 200
    assert ctx.client.post(url, headers=headers, json=payload).status_code == 409
    current = next(x for x in ctx.client.get(base+'/review-progress').json()['items'] if x['kind']=='compound' and x['entity_id']==cid)
    assert not current['viewed']
    ctx.login('science.api.other')
    assert ctx.client.get(base+'/review-progress').status_code == 404


def test_layout_has_separate_revision_and_does_not_change_graph(science_api_context):
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    compound = ctx.client.post(base+'/compounds', headers=headers, json={'expected_workspace_version': 1, 'compound_label': '1'}).json()['compound']
    lineage = ctx.client.post(base+'/lineages', headers=headers, json={'expected_workspace_version': 2, 'lineage_label': 'Synthetic series'}).json()['lineage']
    lid = lineage['id']
    ctx.client.post(f'/api/v2/lineages/{lid}/members', headers=headers, json={'expected_workspace_version': 3, 'compound_id': compound['id'], 'role': 'root'})
    path = f'/api/v2/lineages/{lid}/layouts/points'
    assert ctx.client.get(path).status_code == 200
    payload = {'expected_revision': 0, 'positions': {compound['id']: {'x': 25, 'y': -40}}, 'edge_controls': {}}
    response = ctx.client.put(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 1
    assert ctx.client.get(base).json()['version'] == 4
    assert ctx.client.put(path, headers=headers, json=payload).status_code == 409
    assert ctx.client.get(path).json()['positions'][compound['id']]['y'] == -40
    invalid = {**payload, 'expected_revision': 1, 'positions': {str(ctx.second.paper_id): {'x': 0, 'y': 0}}}
    assert ctx.client.put(path, headers=headers, json=invalid).status_code == 422
    with ctx.session_factory.begin() as session:
        session.get(PaperWorkspace, ctx.first.workspace_id).state = WorkspaceState.SUBMITTED
    assert ctx.client.put(path, headers=headers, json={**payload, 'expected_revision': 1}).status_code == 409


def test_viewing_auto_completes_reading_but_keeps_science_blockers(science_api_context):
    from app.workspaces.validation import validate_submission
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    created = ctx.client.post(base+'/compounds',headers=headers,json={'expected_workspace_version':1,'compound_label':'1'})
    cid = created.json()['compound']['id']
    # Viewing all records does not create a Structure or waive its disposition.
    progress = ctx.client.get(base+'/review-progress').json()
    for item in progress['items']:
        response = ctx.client.post(base+'/views',headers=headers,json={k:item[k] for k in ('kind','entity_id','signature')}|{'viewed':True})
        assert response.status_code == 200
    with ctx.session_factory.begin() as session:
        blockers = validate_submission(session,ctx.first.workspace_id).blockers
        assert any(x.code == 'STRUCTURE_NOT_CONFIRMED' for x in blockers)
        assert not any(x.code == 'SECTION_PENDING' and x.section_key.value in ('compounds','structures','activities') for x in blockers)
        assert not any(x.code == 'RECORD_NOT_VIEWED' for x in blockers)
    item = next(x for x in progress['items'] if x['kind']=='compound')
    assert ctx.client.post(base+'/views',headers=headers,json={k:item[k] for k in ('kind','entity_id','signature')}|{'viewed':False}).status_code == 200
    with ctx.session_factory.begin() as session:
        assert any(x.code == 'RECORD_NOT_VIEWED' and str(x.entity_id)==cid for x in validate_submission(session,ctx.first.workspace_id).blockers)


def test_metadata_clearing_is_explicit_and_legacy_candidate_shape_is_unchanged():
    from app.ai_prefill.contracts import BibliographyCorrection
    baseline = BibliographyCorrection().model_dump(mode='json')
    assert not {'abstract','abstract_source','pdb_references'} & baseline.keys()
    cleared = BibliographyCorrection(abstract=None,pdb_references=[]).model_dump(mode='json')
    assert cleared['abstract'] is None
    assert cleared['pdb_references'] == []


def test_structure_revision_invalidates_lineage_view_dependencies():
    from copy import deepcopy
    from app.workspaces.review_progress import review_items
    snapshot={'source':{'sha256':'a'*64},'paper':{'id':'p','title':'Test'},'compounds':[{'id':'c','compound_label':'1'}],
        'structures':[{'compound_id':'c','smiles':'CCO'}], 'structure_source_images':[],
        'lineages':[{'id':'l','lineage_label':'Series'}], 'lineage_members':[{'lineage_id':'l','compound_id':'c','role':'root'}],
        'lineage_edges':[], 'evidence':[], 'edge_evidence_links':[], 'activities':[]}
    before={x['kind']:x['signature'] for x in review_items(snapshot)}
    edited=deepcopy(snapshot);edited['structures'][0]['smiles']='CCN'
    after={x['kind']:x['signature'] for x in review_items(edited)}
    assert before['lineage']!=after['lineage']
    assert before['compound']!=after['compound']


def test_historical_child_receipts_are_retained_without_becoming_group_views(science_api_context):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.workspaces.models import WorkspaceViewReceipt
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    with ctx.session_factory.begin() as session:
        session.add(WorkspaceViewReceipt(workspace_id=ctx.first.workspace_id,
            reviewer_id=ctx.reviewer_id,kind='bibliography',entity_id=ctx.first.paper_id,
            signature='a'*64,viewed_at=datetime.now(timezone.utc)))
    progress = ctx.client.get(base+'/review-progress').json()
    assert not progress['tracking_started']
    assert progress['items'] == []
    rejected = ctx.client.post(base+'/views',headers=headers,json={
        'kind':'bibliography','entity_id':str(ctx.first.paper_id),'signature':'a'*64,'viewed':True})
    assert rejected.status_code == 422
    with ctx.session_factory.begin() as session:
        assert session.scalar(select(WorkspaceViewReceipt).where(
            WorkspaceViewReceipt.workspace_id==ctx.first.workspace_id)).viewed_at is not None
