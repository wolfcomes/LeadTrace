from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.publications.comparison import reconstruct_reviewer_baseline
from app.workspaces.models import ChangeActorKind


def state(version=1):
    return {'schema_version': 1, 'workspace_version': version, 'paper': {'id': 'p', 'title': 'Initial'},
        'source': {'asset_id': 'a', 'sha256': 'x'}, 'sections': [{'section_key': 'compounds', 'state': 'pending', 'note': None}],
        **{key: [] for key in ('compounds', 'structures', 'structure_source_images', 'lineages', 'lineage_members', 'lineage_edges', 'edge_evidence_links', 'evidence', 'activities', 'compound_highlights')}}


def event(action, before, after):
    return SimpleNamespace(action=action, entity_type='workspace_edit' if action.startswith('workspace.') else action.split('.')[0], entity_id='new', actor_kind=ChangeActorKind.REVIEWER,
        before_value={'snapshot': before}, after_value={'snapshot': after})


def compound():
    return dict(id='new', paper_id='p', workspace_id='w', compound_label='New', display_name=None, description=None, sort_order=0, created_by_kind='reviewer')


@pytest.mark.parametrize('action', ['compound.paste', 'lineage.paste', 'workspace.undo', 'workspace.redo'])
def test_snapshot_events_restore_baseline_preserving_frozen_metadata(action):
    before = state()
    after = deepcopy(before)
    after['compounds'] = [compound()]
    after['paper']['title'] = 'Updated'
    after['sections'][0]['state'] = 'completed'
    after['workspace_version'] = 2
    frozen = {**deepcopy(after), 'workspace_version': 5, 'review_progress': {'tracking_started': True}, 'ai_provenance': [{'entity_id': 'new'}]}
    original = deepcopy(frozen)
    baseline, warnings = reconstruct_reviewer_baseline(frozen, [event(action, before, after)])
    assert not warnings
    assert baseline['compounds'] == []
    assert baseline['paper'] == before['paper']
    assert baseline['sections'] == before['sections']
    assert baseline['workspace_version'] == 5
    assert baseline['review_progress'] == frozen['review_progress']
    assert baseline['ai_provenance'] == frozen['ai_provenance']
    assert frozen == original


def test_paste_undo_redo_chain_reconstructs_original_and_accepts_presentation_siblings():
    original = state()
    pasted = deepcopy(original); pasted['compounds'] = [compound()]; pasted['workspace_version'] = 2
    undone = deepcopy(original); undone['workspace_version'] = 3
    redone = deepcopy(pasted); redone['workspace_version'] = 4
    events = [event('compound.paste', original, pasted), event('workspace.undo', pasted, undone), event('workspace.redo', undone, redone)]
    for item in events[1:]:
        item.before_value['lineage_presentations'] = []
        item.after_value['lineage_presentations'] = []
    baseline, warnings = reconstruct_reviewer_baseline(redone, events)
    assert not warnings
    assert baseline['compounds'] == []


@pytest.mark.parametrize('corruption', ['different_science', 'missing_collection', 'different_source', 'different_paper', 'unknown_collection'])
def test_snapshot_reversal_fails_closed_on_incomplete_or_disagreeing_history(corruption):
    before = state(); after = state(2); frozen = deepcopy(after)
    if corruption == 'different_science': frozen['paper']['title'] = 'Unlogged'
    if corruption == 'missing_collection': after.pop('activities')
    if corruption == 'different_source': before['source']['asset_id'] = 'foreign'
    if corruption == 'different_paper': before['paper']['id'] = 'foreign'
    if corruption == 'unknown_collection': after['unknown_science'] = []
    baseline, warnings = reconstruct_reviewer_baseline(frozen, [event('compound.paste', before, after)])
    assert baseline is None and warnings


def test_submission_section_projection_requires_matching_completed_progress_and_preserves_notes():
    before = state(); after = state(2); frozen = deepcopy(after)
    frozen['sections'][0]['state'] = 'completed'
    history = [event('workspace.redo', before, after)]
    assert reconstruct_reviewer_baseline(frozen, history)[0] is None
    frozen['review_progress'] = {'sections': [{'section_key': 'compounds', 'complete': True}]}
    baseline, warnings = reconstruct_reviewer_baseline(frozen, history)
    assert not warnings and baseline['sections'][0]['state'] == 'pending'
    frozen['sections'][0]['note'] = 'Unlogged note'
    assert reconstruct_reviewer_baseline(frozen, history)[0] is None


def test_snapshot_reversal_normalizes_row_order_and_chains_with_regular_row_edits():
    before = state(); before['compounds'] = [compound()]
    pasted = deepcopy(before)
    pasted['compounds'].append({**compound(), 'id': 'second', 'compound_label': 'Second'})
    final = deepcopy(pasted)
    final['compounds'][0]['description'] = 'Later edit'
    update = SimpleNamespace(action='compound.update', entity_type='compound', entity_id='new', actor_kind=ChangeActorKind.REVIEWER, before_value=compound(), after_value=final['compounds'][0])
    # Reversing the ordinary update appends its before-value at the list end.
    baseline, warnings = reconstruct_reviewer_baseline(final, [event('compound.paste', before, pasted), update])
    assert not warnings and baseline['compounds'] == before['compounds']


def test_snapshot_reversal_treats_absent_optional_highlights_as_empty():
    before = state(); before.pop('compound_highlights')
    after = deepcopy(before); frozen = deepcopy(after); frozen['compound_highlights'] = []
    baseline, warnings = reconstruct_reviewer_baseline(frozen, [event('workspace.undo', before, after)])
    assert not warnings and 'compound_highlights' not in baseline
