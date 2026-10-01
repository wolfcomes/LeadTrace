from uuid import UUID
from app.workspaces.models import PaperWorkspace, WorkspaceState


def test_review_hints_use_existing_crud_permissions_versions_and_explicit_clear(science_api_context):
    ctx = science_api_context
    csrf = ctx.login('science.api.reviewer')
    headers = {'X-CSRF-Token': csrf}
    version = 1

    def create(path, **fields):
        nonlocal version
        response = ctx.client.post(path, headers=headers, json={'expected_workspace_version': version, **fields})
        assert response.status_code == 201, response.text
        version = response.json()['workspace_version']
        return response.json()

    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    root = create(base+'/compounds', compound_label='A', review_hint='  Shared core; check closure  ')['compound']
    assert root['review_hint'] == 'Shared core; check closure'
    child = create(base+'/compounds', compound_label='B')['compound']
    lineage = create(base+'/lineages', lineage_label='Series A')['lineage']
    for compound, role in [(root, 'root'), (child, 'terminal')]:
        create(f'/api/v2/lineages/{lineage["id"]}/members', compound_id=compound['id'], role=role)
    edge = create(f'/api/v2/lineages/{lineage["id"]}/edges', parent_compound_id=root['id'],
        child_compound_id=child['id'], relation_type='lead_optimization', review_status='draft',
        review_hint='Family reaction supports pairing; verify order')['edge']
    activity = create(f'/api/v2/compounds/{root["id"]}/activities', assay_name='Synthetic test assay',
        metric='IC50', operator='=', value='12', unit='nM', review_hint='Table and text differ')['activity']
    assert ctx.client.get(base+'/compounds').json()['items'][0]['review_hint'] == root['review_hint']
    assert ctx.client.get(f'/api/v2/lineages/{lineage["id"]}/edges').json()['items'][0]['review_hint'] == edge['review_hint']
    assert ctx.client.get(f'/api/v2/compounds/{root["id"]}/activities').json()['items'][0]['review_hint'] == activity['review_hint']
    confirmed = ctx.client.patch(f'/api/v2/lineage-edges/{edge["id"]}', headers=headers,
        json={'expected_workspace_version': version, 'review_status': 'reviewer_confirmed'})
    assert confirmed.status_code == 200
    assert confirmed.json()['edge']['review_hint'] == edge['review_hint']
    version = confirmed.json()['workspace_version']
    for collection, key, row in [('compounds','compound',root), ('activities','activity',activity), ('lineage-edges','edge',edge)]:
        path = f'/api/v2/{collection}/{row["id"]}'
        stale = ctx.client.patch(path, headers=headers, json={'expected_workspace_version': version-1, 'review_hint': None})
        assert stale.status_code == 409
        invalid = ctx.client.patch(path, headers=headers, json={'expected_workspace_version': version, 'review_hint': 'x'*1001})
        assert invalid.status_code == 422
        missing_csrf = ctx.client.patch(path, json={'expected_workspace_version': version, 'review_hint': None})
        assert missing_csrf.status_code == 403
        cleared = ctx.client.patch(path, headers=headers, json={'expected_workspace_version': version, 'review_hint': '   '})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()[key]['review_hint'] is None
        version = cleared.json()['workspace_version']
    with ctx.session_factory.begin() as session:
        session.get(PaperWorkspace, ctx.first.workspace_id).state = WorkspaceState.SUBMITTED
    for collection,row in [('compounds',root),('activities',activity),('lineage-edges',edge)]:
        denied = ctx.client.patch(f'/api/v2/{collection}/{row["id"]}', headers=headers,
            json={'expected_workspace_version': version, 'review_hint': 'New doubt'})
        assert denied.status_code == 409
        assert denied.json()['code'] == 'WORKSPACE_READ_ONLY'
