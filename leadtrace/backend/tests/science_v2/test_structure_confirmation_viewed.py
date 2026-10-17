import pytest
from tests.science_v2.test_edit_history_dependencies import _graph


@pytest.mark.parametrize('input_method', ['manual_smiles', 'ai_prefill', 'structure_editor'])
def test_confirmation_preserves_current_compound_and_lineage_views(science_api_context, input_method):
    c = science_api_context
    headers = {'X-CSRF-Token': c.login('science.api.reviewer')}
    cid, _, _ = _graph(c)
    base = f'/api/v2/workspaces/{c.first.workspace_id}'
    structure_url = f'/api/v2/compounds/{cid}/structure'
    payload = {'input_method': input_method, 'smiles': 'CCO', 'molfile': None}
    if input_method == 'structure_editor':
        from rdkit import Chem
        payload.update(smiles=None, molfile=Chem.MolToMolBlock(Chem.MolFromSmiles('CCO')))
    response = c.client.put(structure_url, headers=headers, json={**payload, 'expected_workspace_version': 1, 'status': 'draft'})
    assert response.status_code == 200, response.text
    before = c.client.get(base+'/review-progress').json()
    for item in before['items']:
        assert c.client.post(base+'/views', headers=headers, json={k:item[k] for k in ('kind','entity_id','signature')}|{'viewed':True}).status_code == 200
    if input_method == 'ai_prefill':
        payload['input_method'] = 'manual_smiles'  # The actual confirm button sends this.
    response = c.client.put(structure_url, headers=headers, json={**payload, 'expected_workspace_version': 2, 'status': 'reviewer_confirmed'})
    assert response.status_code == 200, response.text
    assert response.json()['structure']['status'] == 'reviewer_confirmed'
    after = c.client.get(base+'/review-progress').json()
    assert after['workspace_version'] == 3
    assert all(item['viewed'] for item in after['items'])
    # Real structural edits still invalidate both the Compound and its Lineages.
    response = c.client.put(structure_url, headers=headers, json={'input_method':'manual_smiles', 'smiles':'CCN', 'molfile':None, 'expected_workspace_version':3, 'status':'reviewer_confirmed'})
    assert response.status_code == 200, response.text
    assert not any(item['viewed'] for item in c.client.get(base+'/review-progress').json()['items'])


@pytest.mark.parametrize('receipt_state', ['absent', 'stale', 'unviewed'])
def test_confirmation_does_not_promote_invalid_view_receipts(science_api_context, receipt_state):
    c = science_api_context
    headers = {'X-CSRF-Token': c.login('science.api.reviewer')}
    cid, _, _ = _graph(c)
    base = f'/api/v2/workspaces/{c.first.workspace_id}'
    url = f'/api/v2/compounds/{cid}/structure'
    payload = {'input_method':'manual_smiles', 'smiles':'CCO', 'molfile':None}
    assert c.client.put(url, headers=headers, json={**payload,'expected_workspace_version':1,'status':'draft'}).status_code == 200
    if receipt_state != 'absent':
        for item in c.client.get(base+'/review-progress').json()['items']:
            assert c.client.post(base+'/views', headers=headers, json={k:item[k] for k in ('kind','entity_id','signature')}|{'viewed':receipt_state=='stale'}).status_code == 200
    version = 2
    if receipt_state == 'stale':
        assert c.client.patch(f'/api/v2/compounds/{cid}',headers=headers,json={'expected_workspace_version':version,'description':'Changed since viewing'}).status_code == 200
        version += 1
    assert c.client.put(url, headers=headers, json={**payload,'expected_workspace_version':version,'status':'reviewer_confirmed'}).status_code == 200
    assert not any(item['viewed'] for item in c.client.get(base+'/review-progress').json()['items'])
