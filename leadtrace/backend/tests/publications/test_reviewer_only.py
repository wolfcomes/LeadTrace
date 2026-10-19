from copy import deepcopy

from app.publications.reviewer_projection import reviewer_only_baseline
from app.workspaces.models import ChangeActorKind
from tests.publications.test_comparison import compound, event


def repair(before, after, action='update'):
    metadata = {'repair_job_id': 'job', 'delivery_mode': 'automatic_revision', 'requested_by_id': 'admin'}
    result = event('compound', {**before, '_repair': metadata} if before else None,
                 {**after, '_repair': metadata} if after else None,
                 actor=ChangeActorKind.AI, action=f'compound.repair_{action}')
    result.id = id(result)
    result.actor_id = None
    return result


def project(final, events):
    snapshot = {'schema_version': 1, 'compounds': final}
    original = deepcopy(snapshot)
    baseline, warnings = reviewer_only_baseline(snapshot, events, verified_repair_ids={e.id for e in events if hasattr(e, 'id')})
    assert not warnings
    assert snapshot == original
    return baseline['compounds']


def test_ai_only_additions_updates_deletions_are_not_human_changes():
    a = compound(); b = {**a, 'description': 'AI'}
    assert project([b], [repair(a, b)]) == [b]
    assert project([b], [repair(None, b, 'create')]) == [b]
    assert project([], [repair(b, None, 'delete')]) == []


def test_human_changes_survive_ai_changes_to_other_fields_in_same_row():
    a = compound(); b = {**a, 'description': 'Human'}
    c = {**b, 'display_name': 'AI name'}
    assert project([c], [event('compound', a, b), repair(b, c)]) == [{**a, 'display_name': 'AI name'}]


def test_ai_override_is_baseline_for_next_human_change():
    a = compound(); b = {**a, 'description': 'Human first'}
    c = {**b, 'description': 'AI'}; d = {**c, 'description': 'Human last'}
    assert project([d], [event('compound', a, b), repair(b, c), event('compound', c, d)]) == [c]
    assert project([c], [event('compound', a, b), repair(b, c)]) == [c]


def test_human_edit_or_delete_of_ai_created_row_is_visible():
    a = compound(); b = {**a, 'description': 'Human'}
    assert project([b], [repair(None, a, 'create'), event('compound', a, b)]) == [a]
    deletion = event('compound', {'compound': a, 'structure': None, 'structure_source_images': []}, None, action='compound.delete')
    deletion.entity_id = 'c1'
    assert project([], [repair(None, a, 'create'), deletion]) == [a]


def test_unsupported_history_does_not_silently_hide_changes():
    a = compound()
    baseline, warnings = reviewer_only_baseline({'schema_version': 1, 'compounds': [a]},
        [event('compound', a, a, actor=ChangeActorKind.AI, action='unknown.repair')])
    assert baseline is None and warnings

def test_human_creation_remains_visible_after_ai_updates_it():
    a = compound(); b = {**a, 'description': 'AI'}
    assert project([b], [event('compound', None, a, action='compound.create'), repair(a, b)]) == []


def test_unverified_repair_and_inconsistent_chain_are_unavailable():
    a = compound(); b = {**a, 'description': 'AI'}
    change = repair(a, b)
    baseline, warnings = reviewer_only_baseline({'schema_version': 1, 'compounds': [b]}, [change])
    assert baseline is None and warnings
    baseline, warnings = reviewer_only_baseline({'schema_version': 1, 'compounds': [a]}, [change], verified_repair_ids={change.id})
    assert baseline is None and warnings


def test_snapshot_undo_keeps_ai_state_and_removes_human_net_change():
    from tests.publications.test_clipboard_comparison import state, event as snapshot_event
    a = compound(); b = {**a, 'display_name': 'AI'}; c = {**b, 'description': 'Human'}
    middle = state(); middle['compounds'] = [b]
    changed = deepcopy(middle); changed['compounds'] = [c]
    ai = repair(a, b)
    result, warnings = reviewer_only_baseline(middle, [ai, event('compound', b, c),
        snapshot_event('workspace.undo', changed, middle)], verified_repair_ids={ai.id})
    assert not warnings
    assert result['compounds'] == [b]

def test_submission_derived_completion_does_not_break_ai_section_reversal():
    from types import SimpleNamespace
    before = dict(id='section', paper_id='p1', workspace_id='w1', section_key='lineages', state='completed', note=None)
    metadata = {'repair_job_id':'job', 'delivery_mode':'automatic_revision', 'requested_by_id':'admin'}
    change = SimpleNamespace(id='event', entity_type='paper_section_review', entity_id='section',
        action='paper_section_review.repair_invalidate', actor_kind=ChangeActorKind.AI, actor_id=None,
        before_value=before, after_value={**before, 'state':'pending', '_repair':metadata})
    snapshot = {'schema_version':1, 'sections':[{'section_key':'lineages','state':'completed','note':None}],
        'review_progress':{'sections':[{'section_key':'lineages','complete':True}]}}
    baseline, warnings = reviewer_only_baseline(snapshot, [change], verified_repair_ids={'event'})
    assert not warnings
    assert baseline['sections'] == snapshot['sections']

def test_ai_metadata_addition_preserves_human_added_profile_group():
    initial = {'schema_version':1, 'paper':{'id':'p1'}}
    human = {'research_profile':{'targets':[{'name':'human target'}]}}
    final = {'research_profile':{**human['research_profile'], 'modalities':[{'label':'AI type'}]}}
    changes = [event('paper', {'research_profile':{}}, human, action='bibliography.update'),
        event('paper', human, final, actor=ChangeActorKind.AI, action='bibliography.update')]
    baseline, warnings = reviewer_only_baseline({**initial, 'paper':{'id':'p1', **final}}, changes)
    assert not warnings
    assert baseline['paper']['research_profile'] == {'modalities':[{'label':'AI type'}]}


def test_overlapping_ordered_metadata_lists_fail_closed():
    before = {'pdb_references':[{'code':'AAAA','note':'original'}]}
    human = {'pdb_references':[{'code':'AAAA','note':'human'}]}
    final = {'pdb_references':[*human['pdb_references'], {'code':'BBBB','note':'AI'}]}
    changes = [event('paper', before, human, action='bibliography.update'),
        event('paper', human, final, actor=ChangeActorKind.AI, action='bibliography.update')]
    baseline, warnings = reviewer_only_baseline({'schema_version':1,'paper':{'id':'p1', **final}}, changes)
    assert baseline is None and warnings


def test_previous_snapshot_detects_missing_human_history():
    from tests.publications.test_clipboard_comparison import state
    previous = state(); previous['compounds'] = [compound()]
    final = deepcopy(previous); final['paper']['title'] = 'Unlogged edit'
    baseline, warnings = reviewer_only_baseline(final, [], expected_start=previous)
    assert baseline is None and warnings

def test_human_section_note_after_ai_invalidation_survives_derived_completion():
    from types import SimpleNamespace
    before = dict(id='section', paper_id='p1', workspace_id='w1', section_key='lineages', state='completed', note=None)
    metadata = {'repair_job_id':'job', 'delivery_mode':'automatic_revision', 'requested_by_id':'admin'}
    ai = SimpleNamespace(id='event', entity_type='paper_section_review', entity_id='section',
        action='paper_section_review.repair_invalidate', actor_kind=ChangeActorKind.AI, actor_id=None,
        before_value=before, after_value={**before, 'state':'pending', '_repair':metadata})
    human_before = {'section_key':'lineages','state':'pending','note':None}
    human_after = {**human_before,'note':'Reviewer note'}
    human = event('paper_section_review', human_before, human_after, action='section.update')
    snapshot = {'schema_version':1, 'sections':[{**human_after,'state':'completed'}],
        'review_progress':{'sections':[{'section_key':'lineages','complete':True}]}}
    baseline, warnings = reviewer_only_baseline(snapshot, [ai,human], verified_repair_ids={'event'})
    assert not warnings
    assert baseline['sections'][0]['note'] is None
    assert snapshot['sections'][0]['note'] == 'Reviewer note'


def test_ai_table_addition_is_excluded_but_later_reviewer_column_edit_is_visible():
    from types import SimpleNamespace
    row = dict(id='t1', paper_id='p1', workspace_id='w1', name='Table 1', kind='source', source_label='Table 1',
               source_title=None, page_number=2, review_hint=None, columns=[{'id':'col1','label':'IC50'}],
               mode='any', sort='label', review_status='draft', created_by_kind='ai')
    edited = {**row, 'columns':[{'id':'col1','label':'Human corrected IC50'}]}
    metadata = {'repair_job_id':'job','delivery_mode':'automatic_revision','requested_by_id':'admin'}
    ai = SimpleNamespace(id='ai1', entity_type='activity_table', entity_id='t1', action='activity_table.repair_create',
        actor_kind=ChangeActorKind.AI, actor_id=None, before_value=None, after_value={**row,'_repair':metadata})
    human = SimpleNamespace(id='h1',entity_type='activity_table',entity_id='t1',action='activity_table.update',
        actor_kind=ChangeActorKind.REVIEWER, before_value=row,after_value=edited)
    snapshot = {'schema_version':1,'activity_tables':[edited]}; frozen = deepcopy(snapshot)
    baseline,warnings=reviewer_only_baseline(snapshot,[ai,human],verified_repair_ids={'ai1'})
    assert not warnings
    assert baseline['activity_tables']==[row]
    assert snapshot==frozen


def table_edit_sequence(human_change, ai_change):
    from types import SimpleNamespace
    row = dict(id='t1', paper_id='p1', workspace_id='w1', name='Table 1', kind='source', source_label='Table 1',
               source_title=None, page_number=2, review_hint=None, columns=[{'id':'a','label':'IC50'}, {'id':'b','label':'EC50'}],
               mode='any', sort='label', review_status='draft', created_by_kind='ai')
    human = deepcopy(row); human_change(human)
    final = deepcopy(human); ai_change(final)
    metadata = {'repair_job_id':'job','delivery_mode':'automatic_revision','requested_by_id':'admin'}
    events = [SimpleNamespace(id='h', entity_type='activity_table',entity_id='t1',action='activity_table.update',
                  actor_kind=ChangeActorKind.REVIEWER,before_value=row,after_value=human),
              SimpleNamespace(id='ai',entity_type='activity_table',entity_id='t1',action='activity_table.repair_update',
                  actor_kind=ChangeActorKind.AI,actor_id=None,before_value={**human,'_repair':metadata},after_value={**final,'_repair':metadata})]
    baseline, warnings = reviewer_only_baseline({'schema_version':1,'activity_tables':[final]}, events, verified_repair_ids={'ai'})
    return baseline, warnings, final


def test_human_table_column_label_survives_later_ai_column_addition():
    baseline, warnings, final = table_edit_sequence(
        lambda t: t['columns'][0].update(label='Human IC50'),
        lambda t: t['columns'].append({'id':'c','label':'Selectivity'}))
    assert not warnings
    assert baseline['activity_tables'][0]['columns'] == [{'id':'a','label':'IC50'}, {'id':'b','label':'EC50'}, {'id':'c','label':'Selectivity'}]
    assert final['columns'][0]['label'] == 'Human IC50'


def test_ai_table_reorder_preserves_human_label_and_moves_baseline_columns():
    baseline, warnings, final = table_edit_sequence(
        lambda t: t['columns'][0].update(label='Human IC50'), lambda t: t['columns'].reverse())
    assert not warnings
    assert baseline['activity_tables'][0]['columns'] == [{'id':'b','label':'EC50'}, {'id':'a','label':'IC50'}]
    assert final['columns'][1]['label'] == 'Human IC50'


def test_ai_table_added_column_keeps_prior_human_reorder_visible():
    baseline, warnings, final = table_edit_sequence(
        lambda t: t['columns'].reverse(), lambda t: t['columns'].append({'id':'c','label':'Selectivity'}))
    assert not warnings
    assert [c['id'] for c in baseline['activity_tables'][0]['columns']] == ['a','c','b']
    assert [c['id'] for c in final['columns']] == ['b','a','c']


def test_overlapping_human_and_ai_column_reorders_report_warning():
    baseline, warnings, _ = table_edit_sequence(
        lambda t: t['columns'].reverse(), lambda t: t['columns'].reverse())
    assert baseline is None and warnings
