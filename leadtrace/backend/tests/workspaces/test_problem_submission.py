from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.workspaces.models import PaperSubmission, PaperWorkspace, WorkspaceState
from app.workspaces.snapshot import canonical_snapshot_hash
from app.workspaces.submission import SubmissionService


def test_problem_submission_freezes_incomplete_content_and_reason(workspace_fixture):
    f = workspace_fixture
    csrf = f.login('workspace.reviewer')
    payload = {'expected_workspace_version': 1, 'reason': '  Article structures contradict the reported series.  '}
    url = f'/api/v2/workspaces/{f.workspace_id}/submit-problem'
    headers = {'X-CSRF-Token': csrf, 'Idempotency-Key': 'problem-1'}
    result = f.client.post(url, json=payload, headers=headers)
    assert result.status_code == 200, result.text
    frozen = result.json()['submission']
    report = frozen['snapshot']['problem_report']
    assert report['reason'] == payload['reason'].strip()
    assert len(report['blockers']) == 6
    assert {b['code'] for b in report['blockers']} == {'SECTION_PENDING'}
    assert all(s['state'] == 'pending' for s in frozen['snapshot']['sections'])
    assert canonical_snapshot_hash(frozen['snapshot']) == frozen['content_hash']
    repeated = f.client.post(url, json=payload, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()['submission']['id'] == frozen['id']
    changed = f.client.post(url, json=payload | {'reason': 'Different issue'}, headers=headers)
    assert changed.status_code == 409
    normal_replay = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/submit',
        json={'expected_workspace_version': 1}, headers=headers)
    assert normal_replay.status_code == 409
    with f.session_factory() as session:
        assert session.get(PaperWorkspace, f.workspace_id).state is WorkspaceState.SUBMITTED
        assert session.scalar(select(func.count()).select_from(PaperSubmission)) == 1


@pytest.mark.parametrize('reason', ['', '   ', 'x' * 10001])
def test_problem_submission_requires_meaningful_bounded_reason(workspace_fixture, reason):
    f = workspace_fixture
    csrf = f.login('workspace.reviewer')
    result = f.client.post(f'/api/v2/workspaces/{f.workspace_id}/submit-problem',
        json={'expected_workspace_version': 1, 'reason': reason},
        headers={'X-CSRF-Token': csrf, 'Idempotency-Key': 'bad-reason'})
    assert result.status_code == 422


def test_problem_submission_preserves_csrf_ownership_and_version(workspace_fixture):
    f = workspace_fixture
    url = f'/api/v2/workspaces/{f.workspace_id}/submit-problem'
    body = {'expected_workspace_version': 1, 'reason': 'Major article issue'}
    csrf = f.login('workspace.reviewer')
    assert f.client.post(url, json=body).status_code == 403
    assert f.client.post(url, json=body | {'expected_workspace_version': 99},
        headers={'X-CSRF-Token': csrf, 'Idempotency-Key': 'stale'}).status_code == 409
    csrf = f.login('workspace.other')
    assert f.client.post(url, json=body, headers={'X-CSRF-Token': csrf, 'Idempotency-Key': 'other'}).status_code == 404
    csrf = f.login('workspace.admin')
    assert f.client.post(url, json=body, headers={'X-CSRF-Token': csrf, 'Idempotency-Key': 'admin'}).status_code == 403


def test_problem_submission_never_bypasses_boundary_validation(workspace_fixture, monkeypatch):
    from app.workspaces.validation import SubmissionBlocker, SubmissionValidation
    from app.workspaces.submission import SubmissionValidationError
    f = workspace_fixture
    monkeypatch.setattr('app.workspaces.submission.validate_submission', lambda *_: SubmissionValidation([
        SubmissionBlocker('BOUNDARY_VIOLATION', 'Cross-workspace content', 'compound', uuid4())]))
    with f.session_factory.begin() as session:
        with pytest.raises(SubmissionValidationError):
            SubmissionService().submit(session, workspace_id=f.workspace_id, reviewer_id=f.reviewer_id,
                expected_workspace_version=1, idempotency_key='boundary', reviewer_note=None,
                problem_reason='Article issue')
        assert session.get(PaperWorkspace, f.workspace_id).state is WorkspaceState.EDITING


def test_problem_submission_keeps_unconfirmed_unviewed_compound(workspace_fixture):
    from app.compounds.models import Compound
    f = workspace_fixture
    with f.session_factory.begin() as session:
        compound = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id,
            compound_label='Synthetic-1', sort_order=0, created_by_kind='reviewer')
        session.add(compound)
        session.flush()
        frozen = SubmissionService().submit(session, workspace_id=f.workspace_id,
            reviewer_id=f.reviewer_id, expected_workspace_version=1,
            idempotency_key='incomplete-compound', reviewer_note=None, problem_reason='Cannot resolve structures')
        assert frozen.snapshot['compounds'][0]['compound_label'] == 'Synthetic-1'
        assert frozen.snapshot['structures'] == []
        assert any(b['code'] == 'STRUCTURE_NOT_CONFIRMED' for b in frozen.snapshot['problem_report']['blockers'])
        assert frozen.snapshot['review_progress']['items'][0]['viewed'] is False
