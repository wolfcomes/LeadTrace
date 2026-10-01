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


def test_only_compound_and_lineage_are_viewable_groups():
    assert set(signatures(snapshot())) == {('compound', 'a'), ('compound', 'b'), ('lineage', 'l')}


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


def test_edge_and_link_changes_only_invalidate_lineage():
    original=snapshot();changed=deepcopy(original);changed['edge_evidence_links'][0]['role']='contextual'
    before,after=signatures(original),signatures(changed)
    assert before[('lineage','l')] != after[('lineage','l')]
    assert before[('compound','a')] == after[('compound','a')]


def test_orphan_evidence_and_bibliography_do_not_fabricate_group_receipts():
    original=snapshot();changed=deepcopy(original)
    changed['evidence'][1]['page_number']=3;changed['paper']['title']='Updated'
    assert signatures(original)==signatures(changed)
