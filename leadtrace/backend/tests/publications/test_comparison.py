from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from app.publications.comparison import reconstruct_reviewer_baseline
from app.workspaces.models import ChangeActorKind


def event(kind, before, after, *, actor=ChangeActorKind.REVIEWER, action=None):
    value = after or before or {}
    return SimpleNamespace(entity_type=kind, entity_id=value.get('id', str(uuid4())),
        action=action or f'{kind}.update', before_value=before, after_value=after,
        actor_kind=actor)


def compound(**updates):
    return dict(id='c1', paper_id='p1', workspace_id='w1', compound_label='12',
        display_name=None, description=None, sort_order=0, created_by_kind='ai', **updates)


def test_baseline_reverses_all_actors_after_first_reviewer_and_preserves_frozen_input():
    initial = compound()
    middle = {**initial, 'description': 'Reviewer change'}
    final = {**middle, 'display_name': 'Admin correction'}
    snapshot = {'schema_version': 1, 'compounds': [final]}
    original = deepcopy(snapshot)
    baseline, warnings = reconstruct_reviewer_baseline(snapshot, [
        event('compound', None, initial, actor=ChangeActorKind.AI, action='compound.create'),
        event('compound', initial, middle),
        event('compound', middle, final, actor=ChangeActorKind.ADMIN),
    ])
    assert baseline['compounds'] == [initial]
    assert warnings == []
    assert snapshot == original


def test_evidence_bbox_is_normalized_and_decimal_formats_match():
    row = dict(id='e1', paper_id='p1', workspace_id='w1', kind='table',
        source_sha256='a'*64, page_number=1, quoted_text='12 nM', caption=None,
        crop_asset_id=None, reviewer_note=None, created_by_kind='ai',
        bbox={'x0': 0.1, 'y0': 0.2, 'x1': 0.3, 'y1': 0.4})
    after = {**row, 'page_number': 2}
    frozen = {k:v for k,v in after.items() if k not in {'bbox', 'created_by_kind'}}
    frozen.update(dict(x0='0.100000', y0='0.200000', x1='0.300000', y1='0.400000'))
    baseline, warnings = reconstruct_reviewer_baseline(
        {'schema_version': 1, 'evidence': [frozen]}, [event('evidence', row, after)])
    assert warnings == []
    assert baseline['evidence'][0]['page_number'] == 1
    assert baseline['evidence'][0]['x0'] == '0.1'
    assert 'bbox' not in baseline['evidence'][0]


def test_missing_or_inconsistent_history_is_not_claimed_as_empty_diff():
    row = compound()
    for events in ([], [event('compound', row, {**row, 'description': 'not frozen'})],
                   [event('mystery', None, {'id':'m1'})],
                   [event('compound_order', {'compound_ids':['c1']}, {'compound_ids':['c1']}, action='compound.reorder')]):
        baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1, 'compounds':[row]}, events)
        assert baseline is None
        assert warnings


def test_delete_restores_complete_compound_bundle_and_create_reverses_to_absence():
    row = compound()
    deleted = event('compound', {'compound':row, 'structure':None, 'structure_source_images':[]}, None, action='compound.delete')
    deleted.entity_id = 'c1'
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1, 'compounds':[]}, [deleted])
    assert baseline['compounds'] == [row]
    assert not warnings
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1, 'compounds':[row]}, [event('compound',None,row,action='compound.create')])
    assert baseline['compounds'] == []
    assert not warnings


def test_partial_delete_bundle_fails_closed():
    deletion = event('lineage_edge', {'edge': {'id':'e1'}}, None, action='lineage_edge.delete')
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1, 'lineage_edges':[]}, [deletion])
    assert baseline is None
    assert warnings


def test_section_changes_are_reconstructed_including_not_reported():
    before = dict(section_key='activities',state='pending',note='Needs check')
    after = dict(section_key='activities',state='not_reported',note=None)
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1,'sections':[after]}, [event('paper_section_review',before,after,action='section.update')])
    assert baseline['sections'] == [before]
    assert not warnings


def test_confirmation_restores_unresolved_status_instead_of_hiding_issue_resolution():
    before = dict(id='s1', paper_id='p1', workspace_id='w1', compound_id='c1',
        smiles='CC', canonical_smiles='CC', molfile=None, inchi=None, inchikey=None,
        depiction_asset_id=None, status='unresolved', input_method='ai_prefill', created_by_kind='ai')
    after = {**before, 'status':'reviewer_confirmed'}
    frozen = {k:v for k,v in after.items() if k != 'created_by_kind'}
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1,'structures':[frozen]}, [event('structure',before,after)])
    assert baseline['structures'][0]['status'] == 'unresolved'
    assert not warnings


def test_unlogged_cross_entity_scientific_change_is_not_inferred_from_repair_action():
    before = compound()
    after = {**before, 'description':'AI repair'}
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1,'compounds':[after]}, [
        event('compound',before,before),
        event('compound',before,after,actor=ChangeActorKind.AI,action='ai_repair.compound.update'),
    ])
    assert baseline is None
    assert warnings


def test_unknown_lifecycle_action_is_not_silently_treated_as_workflow_only():
    baseline, warnings = reconstruct_reviewer_baseline({'schema_version':1}, [
        event('article_lifecycle', {'id':'w1'}, {'id':'w1'}, action='workspace.replace_content')])
    assert baseline is None
    assert warnings


def test_bibliography_defaults_omitted_from_snapshot_do_not_break_first_round_baseline():
    snapshot={'schema_version':1,'paper':{'id':'p','pmid':'123'}}
    before={'pmid':None,'abstract_status':'not_checked','research_profile':{},'pdb_references':[]}
    after={**before,'pmid':'123'}
    original=deepcopy(snapshot)
    baseline,warnings=reconstruct_reviewer_baseline(snapshot,[event('paper',before,after,action='bibliography.update')])
    assert warnings==[]
    assert baseline['paper']=={'id':'p'}
    assert snapshot==original


def test_bibliography_reset_reconstructs_previous_source_backed_values():
    before={'abstract_status':'extracted','abstract':'Source abstract','abstract_source':'Page 1',
            'research_profile':{'mechanisms':[{'label':'Inhibitor','source':'Page 1'}]}}
    after={'abstract_status':'not_checked','abstract':None,'abstract_source':None,'research_profile':{}}
    baseline,warnings=reconstruct_reviewer_baseline({'schema_version':1,'paper':{'id':'p'}},[event('paper',before,after,action='bibliography.update')])
    assert warnings==[]
    assert baseline['paper']=={'id':'p',**before}
    bad={'schema_version':1,'paper':{'id':'p','abstract_status':'needs_review'}}
    assert reconstruct_reviewer_baseline(bad,[event('paper',before,after,action='bibliography.update')])[0] is None
