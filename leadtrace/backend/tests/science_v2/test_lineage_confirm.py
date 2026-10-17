from uuid import UUID

import pytest
from sqlalchemy import select

from app.compounds.models import Compound
from app.lineages.models import Lineage, LineageMember, LineageEdge, LineageEdgeReviewStatus
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState
from app.workspaces.snapshot import build_paper_snapshot
from app.publications.comparison import reconstruct_reviewer_baseline
from tests.science_v2.test_edit_history import move


def graph(c, statuses=('draft', 'draft', 'unresolved', 'reviewer_confirmed')):
    with c.session_factory.begin() as s:
        scope = dict(paper_id=c.first.paper_id, workspace_id=c.first.workspace_id)
        compounds = [Compound(**scope, compound_label=str(i), sort_order=i, created_by_kind='reviewer') for i in range(5)]
        lineages = [Lineage(**scope, lineage_label=str(i), sort_order=i) for i in range(2)]
        s.add_all(compounds + lineages)
        s.flush()
        for lineage in lineages:
            s.add_all([LineageMember(**scope, lineage_id=lineage.id, compound_id=row.id, role='root' if i == 0 else 'terminal', sort_order=i) for i, row in enumerate(compounds)])
        s.flush()
        edges = [LineageEdge(**scope, lineage_id=lineages[0].id, parent_compound_id=compounds[i].id, child_compound_id=compounds[i+1].id, relation_type='optimization', review_status=status, review_hint='Keep this hint', sort_order=i) for i, status in enumerate(statuses)]
        edges.append(LineageEdge(**scope, lineage_id=lineages[1].id, parent_compound_id=compounds[0].id, child_compound_id=compounds[1].id, relation_type='optimization', review_status='draft', sort_order=0))
        s.add_all(edges)
        s.flush()
        return str(lineages[0].id), str(lineages[1].id), [str(e.id) for e in edges]


def confirm(c, csrf, lid, version=1):
    return c.client.post(f'/api/v2/lineages/{lid}/confirm', headers={'X-CSRF-Token': csrf} if csrf else {}, json={'expected_workspace_version': version})


def test_confirm_drafts_atomic_history_viewing_and_undo(science_api_context):
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    lid, other, edges = graph(c)
    with c.session_factory() as s:
        original = build_paper_snapshot(s, c.first.workspace_id)
    result = confirm(c, csrf, lid)
    assert result.status_code == 200, result.text
    assert result.json()['workspace_version'] == 2
    assert [e['review_status'] for e in result.json()['lineage']['edges']] == ['reviewer_confirmed', 'reviewer_confirmed', 'unresolved', 'reviewer_confirmed']
    assert all(e['review_hint'] == 'Keep this hint' for e in result.json()['lineage']['edges'])
    base = f'/api/v2/workspaces/{c.first.workspace_id}'
    viewed = c.client.get(base+'/review-progress').json()['items']
    assert [i['entity_id'] for i in viewed if i['viewed']] == [lid]
    assert c.client.get(base+'/edit-history').json()['undo_action'] == 'lineage.confirm'
    with c.session_factory() as s:
        assert s.get(LineageEdge, UUID(edges[-1])).review_status.value == 'draft'
        events = list(s.scalars(select(ChangeEvent)))
        assert len(events) == 1
        baseline, warnings = reconstruct_reviewer_baseline(build_paper_snapshot(s, c.first.workspace_id), events)
        assert warnings == []
        assert baseline['lineage_edges'] == original['lineage_edges']
    # Repeating the operation is a scientific no-op.
    assert confirm(c, csrf, lid, 2).json()['workspace_version'] == 2
    assert move(c, csrf, 'undo', 2).status_code == 200
    current = c.client.get(base+'/lineages').json()['items']
    assert [e['review_status'] for l in current if l['id'] == lid for e in l['edges']] == ['draft', 'draft', 'unresolved', 'reviewer_confirmed']
    assert not any(i['viewed'] for i in c.client.get(base+'/review-progress').json()['items'])
    assert move(c, csrf, 'redo', 3).status_code == 200
    assert confirm(c, csrf, lid, 4).json()['workspace_version'] == 4


@pytest.mark.parametrize('statuses', [(), ('unresolved', 'reviewer_confirmed')])
def test_no_drafts_does_not_create_history_or_view_receipts(science_api_context, statuses):
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    lid, _, _ = graph(c, statuses)
    result = confirm(c, csrf, lid)
    assert result.status_code == 200, result.text
    assert result.json()['workspace_version'] == 1
    with c.session_factory() as s:
        assert not list(s.scalars(select(ChangeEvent)))
    assert not any(i['viewed'] for i in c.client.get(f'/api/v2/workspaces/{c.first.workspace_id}/review-progress').json()['items'])


def test_confirm_rejects_stale_version_csrf_ownership_and_readonly(science_api_context):
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    lid, _, _ = graph(c)
    assert confirm(c, csrf, lid, 2).status_code == 409
    assert confirm(c, None, lid).status_code == 403
    assert confirm(c, c.login('science.api.other'), lid).status_code == 404
    assert confirm(c, c.login('science.api.admin'), lid).status_code == 403
    csrf = c.login('science.api.reviewer')
    with c.session_factory.begin() as s:
        s.get(PaperWorkspace, c.first.workspace_id).state = WorkspaceState.SUBMITTED
    assert confirm(c, csrf, lid).status_code == 409
    with c.session_factory() as s:
        assert not list(s.scalars(select(ChangeEvent)))
        assert s.get(PaperWorkspace, c.first.workspace_id).version == 1


def test_failed_edge_validation_rolls_back_all_confirmations(science_api_context, monkeypatch):
    from app.lineages.service import LineageService, LineageValidationError
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    lid, _, edges = graph(c)
    original = LineageService._validate_edge
    calls = []
    def validate(*args, **kwargs):
        calls.append(kwargs['exclude_edge_id'])
        if len(calls) == 2:
            raise LineageValidationError('Invalid edge')
        return original(*args, **kwargs)
    monkeypatch.setattr(LineageService, '_validate_edge', staticmethod(validate))
    assert confirm(c, csrf, lid).status_code == 422
    with c.session_factory() as s:
        assert [s.get(LineageEdge, UUID(e)).review_status.value for e in edges[:2]] == ['draft', 'draft']
        assert s.get(PaperWorkspace, c.first.workspace_id).version == 1
        assert not list(s.scalars(select(ChangeEvent)))
