from copy import deepcopy
import pytest
from app.workspaces.review_progress import review_items


def snapshot():
    return {'source': {'sha256': 'a'*64}, 'paper': {'id': 'p', 'title': 'Synthetic'},
        'compounds': [{'id': 'a', 'compound_label': '1'}, {'id': 'b', 'compound_label': '2'}],
        'structures': [{'compound_id': 'a', 'smiles': 'CCO'}],
        'structure_source_images': [{'compound_id': 'a', 'page_number': 1}],
        'activities': [{'id': 'activity', 'compound_id': 'a', 'evidence_id': 'ev', 'value': 10, 'metric': 'IC50'}],
        'lineages': [{'id': 'l', 'lineage_label': 'Series'}],
        'lineage_members': [{'lineage_id': 'l', 'compound_id': 'a', 'role': 'root'}],
        'lineage_edges': [{'id': 'edge', 'lineage_id': 'l', 'parent_compound_id': 'a', 'child_compound_id': 'a'}],
        'edge_evidence_links': [{'edge_id': 'edge', 'evidence_id': 'ev', 'role': 'supports'}],
        'evidence': [{'id': 'ev', 'page_number': 1, 'quoted_text': 'Synthetic evidence'}, {'id': 'orphan', 'page_number': 2}]}


def signatures(data):
    return {(x['kind'], x['entity_id']): x['signature'] for x in review_items(data)}


def test_compounds_lineages_and_edges_are_viewable_items():
    assert set(signatures(snapshot())) == {
        ('compound', 'a'), ('compound', 'b'), ('lineage', 'l'), ('edge', 'edge')}


@pytest.mark.parametrize('table,field,value', [
    ('structures','smiles','CCN'), ('structure_source_images','page_number',2),
    ('activities','value',20), ('evidence','quoted_text','Changed evidence'),
])
def test_compound_dependencies_invalidate_its_group_and_containing_lineage(table,field,value):
    original=snapshot();changed=deepcopy(original);changed[table][0][field]=value
    before,after=signatures(original),signatures(changed)
    assert before[('compound','a')] != after[('compound','a')]
    assert before[('lineage','l')] != after[('lineage','l')]
    assert before[('compound','b')] == after[('compound','b')]


def test_edge_and_link_changes_invalidate_edge_and_containing_lineage():
    original=snapshot();changed=deepcopy(original);changed['edge_evidence_links'][0]['role']='contextual'
    before,after=signatures(original),signatures(changed)
    assert before[('edge','edge')] != after[('edge','edge')]
    assert before[('lineage','l')] != after[('lineage','l')]
    assert before[('compound','a')] == after[('compound','a')]


def test_edge_content_changes_invalidate_edge_and_containing_lineage():
    original=snapshot();changed=deepcopy(original);changed['lineage_edges'][0]['relation_type']='potency_optimization'
    before,after=signatures(original),signatures(changed)
    assert before[('edge','edge')] != after[('edge','edge')]
    assert before[('lineage','l')] != after[('lineage','l')]


def test_orphan_evidence_and_bibliography_do_not_fabricate_group_receipts():
    original=snapshot();changed=deepcopy(original)
    changed['evidence'][1]['page_number']=3;changed['paper']['title']='Updated'
    assert signatures(original)==signatures(changed)


def test_lineage_progress_requires_each_edge_and_keeps_existing_graph_receipts(science_api_context):
    from tests.science_v2.test_lineage_confirm import graph
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    _, _, edge_ids = graph(ctx, statuses=('draft',))
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'

    def progress():
        return ctx.client.get(base + '/review-progress').json()

    def mark(item, viewed=True):
        result = ctx.client.post(base + '/views', headers=headers, json={
            key: item[key] for key in ('kind', 'entity_id', 'signature')
        } | {'viewed': viewed})
        assert result.status_code == 200, result.text
        return result.json()

    for item in progress()['items']:
        if item['kind'] == 'lineage':
            mark(item)
    current = progress()
    coverage = next(s for s in current['sections'] if s['section_key'] == 'lineages')
    assert (coverage['viewed'], coverage['total'], coverage['complete']) == (2, 4, False)
    edge_items = [i for i in current['items'] if i['kind'] == 'edge']
    assert {i['entity_id'] for i in edge_items} == set(edge_ids)
    for item in edge_items:
        current = mark(item)
    coverage = next(s for s in current['sections'] if s['section_key'] == 'lineages')
    assert (coverage['viewed'], coverage['total'], coverage['complete']) == (4, 4, True)
    current = mark(edge_items[0], False)
    assert not next(s for s in current['sections'] if s['section_key'] == 'lineages')['complete']
    assert all(i['viewed'] for i in current['items'] if i['kind'] == 'lineage')
    assert current['workspace_version'] == 1


def test_no_edges_does_not_block_viewed_lineage(science_api_context):
    from app.lineages.models import Lineage
    ctx = science_api_context
    headers = {'X-CSRF-Token': ctx.login('science.api.reviewer')}
    base = f'/api/v2/workspaces/{ctx.first.workspace_id}'
    empty = ctx.client.get(base + '/review-progress').json()
    assert not next(s for s in empty['sections'] if s['section_key'] == 'lineages')['complete']
    with ctx.session_factory.begin() as session:
        session.add(Lineage(paper_id=ctx.first.paper_id, workspace_id=ctx.first.workspace_id,
                            lineage_label='No edges', sort_order=0))
    item = ctx.client.get(base + '/review-progress').json()['items'][0]
    result = ctx.client.post(base + '/views', headers=headers, json={
        key: item[key] for key in ('kind', 'entity_id', 'signature')
    } | {'viewed': True})
    assert result.status_code == 200
    coverage = next(s for s in result.json()['sections'] if s['section_key'] == 'lineages')
    assert (coverage['total'], coverage['viewed'], coverage['complete']) == (1, 1, True)
