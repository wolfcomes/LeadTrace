from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.activities.models import Activity
from app.compounds.models import Compound
from app.papers.models import Paper
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceViewReceipt
from app.workspaces.snapshot import build_paper_snapshot


def seed(c):
    with c.session_factory.begin() as s:
        scope = dict(paper_id=c.first.paper_id, workspace_id=c.first.workspace_id)
        first = Compound(**scope, compound_label='C10', display_name='Example', sort_order=0, created_by_kind='reviewer')
        blank = Compound(**scope, compound_label='C2', sort_order=1, created_by_kind='reviewer')
        foreign = Compound(paper_id=c.second.paper_id, workspace_id=c.second.workspace_id, compound_label='Private', sort_order=0, created_by_kind='reviewer')
        s.add_all([first, blank, foreign]); s.flush()
        for i in range(2):
            s.add(Activity(**scope, compound_id=first.id, assay_name='Assay A', metric='IC50', operator='<' if i else '=', value=Decimal('0.123456789012345678901'), unit='nM', context='Human enzyme', review_hint='Check conditions', sort_order=i))
        s.add(Activity(paper_id=c.second.paper_id, workspace_id=c.second.workspace_id, compound_id=foreign.id, assay_name='Private assay', metric='EC50', operator='=', value=1, sort_order=0))
        return str(first.id), str(blank.id)


def test_comparison_preserves_all_values_and_empty_compounds_without_writes(science_api_context):
    c = science_api_context
    cid, blank = seed(c)
    c.login('science.api.reviewer')
    with c.session_factory() as s:
        before = build_paper_snapshot(s, c.first.workspace_id)
    r = c.client.get(f'/api/v2/workspaces/{c.first.workspace_id}/activity-comparison')
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['workspace_version'] == 1
    assert data['workspace_id'] == str(c.first.workspace_id)
    assert [x['id'] for x in data['compounds']] == [cid, blank]
    assert len(data['activities']) == 2
    assert [x['operator'] for x in data['activities']] == ['=', '<']
    assert all(x['value'] == '0.123456789012345678901' for x in data['activities'])
    assert all(x['review_hint'] == 'Check conditions' and x['context'] == 'Human enzyme' for x in data['activities'])
    with c.session_factory() as s:
        assert build_paper_snapshot(s, c.first.workspace_id) == before
        assert not list(s.scalars(select(ChangeEvent)))
        assert not list(s.scalars(select(WorkspaceViewReceipt)))


def test_empty_comparison_and_latest_saved_version(science_api_context):
    c = science_api_context
    csrf = c.login('science.api.reviewer')
    base = f'/api/v2/workspaces/{c.first.workspace_id}'
    r = c.client.get(base+'/activity-comparison')
    assert r.status_code == 200, r.text
    assert r.json() == {'workspace_id': str(c.first.workspace_id), 'workspace_version': 1, 'compounds': [], 'activities': []}
    cid, _ = seed(c)
    r = c.client.post(f'/api/v2/compounds/{cid}/activities', headers={'X-CSRF-Token':csrf}, json={'expected_workspace_version':1,'assay_name':'New assay','metric':'Ki','operator':'>','value':'100','unit':'nM'})
    assert r.status_code == 201, r.text
    data = c.client.get(base+'/activity-comparison').json()
    assert data['workspace_version'] == 2
    assert len(data['activities']) == 3
    assert data['activities'][-1]['assay_name'] == 'New assay'


@pytest.mark.parametrize('role,status', [(None,401),('other',404),('visitor',403),('admin',200),('reviewer',200)])
def test_comparison_access_policy(science_api_context, role, status):
    c = science_api_context
    seed(c)
    if role: c.login('science.api.'+role)
    r = c.client.get(f'/api/v2/workspaces/{c.first.workspace_id}/activity-comparison')
    assert r.status_code == status, r.text


def test_comparison_hidden_for_removed_paper(science_api_context):
    c = science_api_context
    seed(c)
    c.login('science.api.admin')
    with c.session_factory.begin() as s:
        p = s.get(Paper, c.first.paper_id)
        p.removed_at = datetime.now(timezone.utc)
        p.removed_by_id = c.admin_id
        p.removal_reason = 'Synthetic removed paper'
    assert c.client.get(f'/api/v2/workspaces/{c.first.workspace_id}/activity-comparison').status_code == 404
