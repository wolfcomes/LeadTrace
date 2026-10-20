from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.activities.models import Activity
from app.compounds.models import Compound
from app.workspaces.snapshot import build_paper_snapshot
from app.activity_tables.schemas import TableWrite


def payload(ids, version=1):
    return dict(expected_workspace_version=version, name='Table 1', kind='source', source_label='Table 1',
                columns=[dict(id='potency', label='Human IC50', assay='Human', metric='IC50', unit='nM', activity_ids=[str(x) for x in ids])])


def seed(f):
    with f.session_factory.begin() as s:
        c = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_label='1', sort_order=0, created_by_kind='reviewer')
        s.add(c); s.flush()
        rows = [Activity(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_id=c.id,
                         assay_name='Human', metric='IC50', unit='nM', operator='=', value=v, sort_order=i)
                for i, v in enumerate([1, 2])]
        s.add_all(rows); s.flush()
        return [r.id for r in rows]


def test_table_shape_rejects_ambiguous_source_and_duplicate_ids():
    data = payload([uuid4()])
    TableWrite.model_validate(data)
    with pytest.raises(ValidationError):
        TableWrite.model_validate(data | {'source_label': None})
    with pytest.raises(ValidationError):
        TableWrite.model_validate(data | {'columns': data['columns'] * 2})
    data['columns'][0]['activity_ids'] *= 2
    with pytest.raises(ValidationError):
        TableWrite.model_validate(data)


def test_tables_persist_other_confirm_invalidate_and_undo(workspace_fixture):
    f = workspace_fixture; ids = seed(f)
    csrf = f.login('workspace.reviewer'); headers = {'X-CSRF-Token': csrf}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    progress_url = f'/api/v2/workspaces/{f.workspace_id}/review-progress'
    empty_progress = f.client.get(progress_url).json()
    activity_group = next(x for x in empty_progress['sections'] if x['section_key'] == 'activities')
    assert (activity_group['total'], activity_group['viewed'], activity_group['complete']) == (0, 0, False)
    with f.session_factory() as s:
        assert 'activity_tables' not in build_paper_snapshot(s, f.workspace_id)
    result = f.client.put(url, json=payload(ids[:1]) | {'evidence_ids': [seed_table_evidence(f)]}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['table']['review_status'] == 'draft'
    draft_group = next(x for x in f.client.get(progress_url).json()['sections'] if x['section_key'] == 'activities')
    assert (draft_group['total'], draft_group['viewed'], draft_group['complete']) == (1, 0, False)
    listing = f.client.get(base).json()
    assert listing['other_activity_ids'] == [str(ids[1])]
    assert listing['workspace_version'] == 2
    from app.workspaces.validation import validate_submission
    with f.session_factory() as s:
        assert any(b.code == 'ACTIVITY_TABLE_NOT_REVIEWED' for b in validate_submission(s, f.workspace_id).blockers)
    result = f.client.post(url + '/confirm', json={'expected_workspace_version': 2}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['table']['review_status'] == 'reviewer_confirmed'
    confirmed_group = next(x for x in f.client.get(progress_url).json()['sections'] if x['section_key'] == 'activities')
    assert (confirmed_group['total'], confirmed_group['viewed'], confirmed_group['complete']) == (1, 1, True)
    from app.workspaces.validation import validate_submission
    with f.session_factory() as s:
        assert not any(b.code == 'SECTION_PENDING' and b.section_key.value == 'activities'
                       for b in validate_submission(s, f.workspace_id).blockers)
    result = f.client.patch(f'/api/v2/activities/{ids[0]}', json={'expected_workspace_version': 3, 'value': '7.00'}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['review_status'] == 'draft'
    invalidated_group = next(x for x in f.client.get(progress_url).json()['sections'] if x['section_key'] == 'activities')
    assert not invalidated_group['complete']
    result = f.client.request('DELETE', f'/api/v2/activities/{ids[0]}', json={'expected_workspace_version': 4}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['columns'][0]['activity_ids'] == []
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/edit-history/undo', json={'expected_workspace_version': 5}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['columns'][0]['activity_ids'] == [str(ids[0])]
    with f.session_factory() as s:
        assert build_paper_snapshot(s, f.workspace_id)['activity_tables'][0]['columns'][0]['activity_ids'] == [str(ids[0])]


def test_tables_versions_permissions_invalid_identity_and_delete(workspace_fixture):
    f = workspace_fixture; ids = seed(f)
    csrf = f.login('workspace.reviewer'); headers = {'X-CSRF-Token': csrf}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    bad = payload(ids); bad['columns'][0]['metric'] = 'EC50'
    assert f.client.put(url, json=bad, headers=headers).status_code == 422
    assert f.client.put(url, json=payload([uuid4()]), headers=headers).status_code == 422
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 409
    csrf = f.login('workspace.admin')
    assert f.client.get(base).status_code == 200
    assert f.client.put(url, json=payload(ids, 2), headers={'X-CSRF-Token': csrf}).status_code == 403
    f.login('workspace.other')
    assert f.client.get(base).status_code == 404
    csrf = f.login('workspace.reviewer')
    result = f.client.request('DELETE', url, json={'expected_workspace_version': 2}, headers={'X-CSRF-Token': csrf})
    assert result.status_code == 200, result.text
    assert set(f.client.get(base).json()['other_activity_ids']) == set(map(str, ids))


def test_table_links_are_removed_on_measurement_identity_change_and_audited(workspace_fixture):
    from sqlalchemy import select
    from app.workspaces.models import ChangeEvent
    from app.publications.comparison import reconstruct_reviewer_baseline
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    result = f.client.patch(f'/api/v2/activities/{ids[0]}', json={'expected_workspace_version': 2, 'metric': 'EC50'}, headers=headers)
    assert result.status_code == 200, result.text
    listing = f.client.get(base).json()
    assert listing['tables'][0]['columns'][0]['activity_ids'] == [str(ids[1])]
    assert listing['other_activity_ids'] == [str(ids[0])]
    with f.session_factory() as s:
        events = list(s.scalars(select(ChangeEvent).where(ChangeEvent.workspace_id == f.workspace_id)))
        baseline, warnings = reconstruct_reviewer_baseline(build_paper_snapshot(s, f.workspace_id), events)
        assert not warnings, warnings
        assert not baseline.get('activity_tables')
        assert all(row['metric'] == 'IC50' for row in baseline['activities'])


def test_table_content_affects_view_signatures_but_confirm_does_not(workspace_fixture):
    from app.workspaces.review_progress import review_items
    from app.publications.schemas import PublishedPaperSnapshotResponse
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    def signature():
        with f.session_factory() as s:
            return review_items(build_paper_snapshot(s, f.workspace_id))[0]['signature']
    eid = seed_table_evidence(f)
    before = signature()
    assert f.client.put(url, json=payload(ids) | {'evidence_ids': [eid]}, headers=headers).status_code == 200
    after = signature()
    assert before != after
    assert f.client.post(url + '/confirm', json={'expected_workspace_version': 2}, headers=headers).status_code == 200
    assert signature() == after
    with f.session_factory() as s:
        frozen = build_paper_snapshot(s, f.workspace_id)
    published = PublishedPaperSnapshotResponse.model_validate(frozen).model_dump(mode='json')
    assert published['activity_tables'][0]['name'] == 'Table 1'
    data = payload(ids, 3) | {'name': 'Human activity', 'evidence_ids': [eid]}
    assert f.client.put(url, json=data, headers=headers).status_code == 200
    assert signature() != after
    assert frozen['activity_tables'][0]['name'] == 'Table 1'


def test_table_readonly_noop_page_and_unresolved(workspace_fixture):
    from app.workspaces.models import PaperWorkspace, WorkspaceState
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    assert f.client.put(url, json=payload(ids) | {'page_number': 999}, headers=headers).status_code == 422
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    response = f.client.post(url + '/confirm', json={'expected_workspace_version': 2, 'review_status': 'unresolved'}, headers=headers)
    assert response.status_code == 200
    response = f.client.put(url, json=payload(ids, 3), headers=headers)
    assert response.json()['workspace_version'] == 3
    assert response.json()['table']['review_status'] == 'unresolved'
    with f.session_factory.begin() as s:
        s.get(PaperWorkspace, f.workspace_id).state = WorkspaceState.SUBMITTED
    assert f.client.get(base).status_code == 200
    assert f.client.put(url, json=payload(ids, 3) | {'name': 'Changed'}, headers=headers).status_code == 409


def seed_table_evidence(f, *, bbox=True, kind='table'):
    from app.evidence.models import Evidence
    with f.session_factory.begin() as s:
        row = Evidence(paper_id=f.paper_id, workspace_id=f.workspace_id, kind=kind,
                       source_sha256='a' * 64, page_number=1, caption='Table 1',
                       x0=0.1 if bbox else None, y0=0.1 if bbox else None,
                       x1=0.9 if bbox else None, y1=0.9 if bbox else None)
        s.add(row); s.flush()
        return str(row.id)


def test_explicit_rows_and_evidence_shape_preserves_legacy_defaults():
    ids = [uuid4(), uuid4()]
    data = TableWrite.model_validate(payload([]) | {'compound_ids': ids, 'evidence_ids': ids})
    assert data.compound_ids == ids
    assert data.evidence_ids == ids
    for key in ('compound_ids', 'evidence_ids'):
        with pytest.raises(ValidationError):
            TableWrite.model_validate(payload([]) | {key: ids * 2})


def test_explicit_rows_order_removal_other_and_undo(workspace_fixture):
    f = workspace_fixture; ids = seed(f)
    with f.session_factory.begin() as s:
        first = str(s.get(Activity, ids[0]).compound_id)
        second = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_label='2', sort_order=1, created_by_kind='reviewer')
        s.add(second); s.flush(); second = str(second.id)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    data = payload(ids) | {'compound_ids': [second, first], 'sort': 'default'}
    result = f.client.put(url, json=data, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['table']['compound_ids'] == [second, first]
    assert f.client.put(url, json=data | {'expected_workspace_version': 2, 'compound_ids': [second]}, headers=headers).status_code == 422
    assert f.client.put(url, json=data | {'expected_workspace_version': 2, 'compound_ids': [str(uuid4())]}, headers=headers).status_code == 422
    result = f.client.put(url, json=payload([], 2) | {'compound_ids': [second]}, headers=headers)
    assert result.status_code == 200, result.text
    assert set(f.client.get(base).json()['other_activity_ids']) == set(map(str, ids))
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/edit-history/undo', json={'expected_workspace_version': 3}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['compound_ids'] == [second, first]
    result = f.client.request('DELETE', f'/api/v2/compounds/{second}', json={'expected_workspace_version': 4}, headers=headers)
    assert result.status_code == 409, result.text
    assert result.json()['details']['table_references'] == 1


def test_source_confirmation_requires_valid_table_crop(workspace_fixture):
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    url = f'/api/v2/workspaces/{f.workspace_id}/activity-tables/{uuid4()}'
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    response = f.client.post(url + '/confirm', json={'expected_workspace_version': 2}, headers=headers)
    assert response.status_code == 422, response.text
    assert f.client.post(url + '/confirm', json={'expected_workspace_version': 2, 'review_status': 'unresolved'}, headers=headers).status_code == 200
    for eid in (str(uuid4()), seed_table_evidence(f, bbox=False), seed_table_evidence(f, kind='text')):
        assert f.client.put(url, json=payload(ids, 3) | {'evidence_ids': [eid]}, headers=headers).status_code == 422
    eid = seed_table_evidence(f)
    response = f.client.put(url, json=payload(ids, 3) | {'evidence_ids': [eid]}, headers=headers)
    assert response.status_code == 200, response.text
    response = f.client.post(url + '/confirm', json={'expected_workspace_version': 4}, headers=headers)
    assert response.status_code == 200, response.text


def test_linked_evidence_edit_invalidates_table_and_view_and_is_reversible(workspace_fixture):
    from sqlalchemy import select
    from app.workspaces.models import ChangeEvent
    from app.workspaces.review_progress import review_items
    from app.publications.comparison import reconstruct_reviewer_baseline
    f = workspace_fixture; ids = seed(f); eid = seed_table_evidence(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    assert f.client.put(url, json=payload(ids) | {'evidence_ids': [eid]}, headers=headers).status_code == 200
    assert f.client.post(url + '/confirm', json={'expected_workspace_version': 2}, headers=headers).status_code == 200
    with f.session_factory() as s:
        before = review_items(build_paper_snapshot(s, f.workspace_id))[0]['signature']
    result = f.client.patch(f'/api/v2/evidence/{eid}', json={'expected_workspace_version': 3, 'caption': 'Corrected table caption'}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['review_status'] == 'draft'
    with f.session_factory() as s:
        frozen = build_paper_snapshot(s, f.workspace_id)
        assert review_items(frozen)[0]['signature'] != before
        events = list(s.scalars(select(ChangeEvent).where(ChangeEvent.workspace_id == f.workspace_id)))
        baseline, warnings = reconstruct_reviewer_baseline(frozen, events)
        assert not warnings, warnings
        assert baseline['evidence'][0]['caption'] == 'Table 1'
    result = f.client.request('DELETE', f'/api/v2/evidence/{eid}', json={'expected_workspace_version': 4}, headers=headers)
    assert result.status_code == 409, result.text
    assert result.json()['details']['table_references'] == 1
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/edit-history/undo', json={'expected_workspace_version': 4}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['review_status'] == 'reviewer_confirmed'


def test_problem_submit_allows_draft_table_but_preserves_missing_review_issue(workspace_fixture):
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    url = f'/api/v2/workspaces/{f.workspace_id}/activity-tables/{uuid4()}'
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    response = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/submit-problem',
        json={'expected_workspace_version': 2, 'reason': 'Original table is inconsistent'},
        headers=headers | {'Idempotency-Key': 'table-problem'})
    assert response.status_code == 200, response.text
    assert any(b['code'] == 'ACTIVITY_TABLE_NOT_REVIEWED' for b in response.json()['submission']['snapshot']['problem_report']['blockers'])


def test_legacy_table_history_and_snapshot_optional_fields(workspace_fixture):
    from copy import deepcopy
    from sqlalchemy import select
    from app.workspaces.models import WorkspaceEdit
    from app.publications.schemas import PublishedPaperSnapshotResponse
    f = workspace_fixture; ids = seed(f)
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    base = f'/api/v2/workspaces/{f.workspace_id}/activity-tables'; url = f'{base}/{uuid4()}'
    assert f.client.put(url, json=payload(ids), headers=headers).status_code == 200
    with f.session_factory.begin() as s:
        snapshot = build_paper_snapshot(s, f.workspace_id)
        table = snapshot['activity_tables'][0]
        assert 'compound_ids' not in table and 'evidence_ids' not in table
        published = PublishedPaperSnapshotResponse.model_validate(snapshot).model_dump(mode='json')
        assert 'compound_ids' not in published['activity_tables'][0]
        assert 'evidence_ids' not in published['activity_tables'][0]
        for edit in s.scalars(select(WorkspaceEdit).where(WorkspaceEdit.workspace_id == f.workspace_id)):
            for key in ('before_state', 'after_state'):
                state = deepcopy(getattr(edit, key))
                for row in state.get('activity_tables', []):
                    row.pop('compound_ids', None); row.pop('evidence_ids', None)
                setattr(edit, key, state)
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/edit-history/undo', json={'expected_workspace_version': 2}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'] == []
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/edit-history/redo', json={'expected_workspace_version': 3}, headers=headers)
    assert result.status_code == 200, result.text
    assert f.client.get(base).json()['tables'][0]['compound_ids'] is None
