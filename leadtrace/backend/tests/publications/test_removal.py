import pytest
from sqlalchemy import select
from app.audit.service import AuditService
from app.publications.models import PublishedPaperVersion
from app.workspaces.models import PaperSubmission


@pytest.mark.parametrize('approved', [False, True])
def test_removed_submission_and_publication_are_hidden_but_immutable(publication_fixture, approved):
    f = publication_fixture
    submission = f.submit()
    token = f.login('publication.admin')
    headers = {'X-CSRF-Token': token}
    url = f'/api/v2/admin/submissions/{submission.id}'
    decision = dict(content_hash=submission.content_hash, action='approve',
                    reason='Checked synthetic data', idempotency_key='removal-approval')
    if approved:
        assert f.client.post(url+'/decisions', json=decision, headers=headers).status_code == 200
        assert f.client.get(f'/api/v2/papers/{f.paper_id}').status_code == 200
    else:
        assert f.client.get('/api/v2/admin/submissions').json()['total'] == 1
    management = f.client.get(f'/api/v2/admin/papers/{f.paper_id}/management').json()
    response = f.client.request('DELETE', f'/api/v2/admin/papers/{f.paper_id}', headers=headers,
        json=dict(reason='Outside scope', confirm_paper_key=management['paper_key'],
                  expected_workspace_id=management['workspace_id'],
                  expected_workspace_version=management['workspace_version'],
                  expected_task_version=management['task_version']))
    assert response.status_code == 200, response.text
    assert f.client.get(url).status_code == 404
    assert f.client.get('/api/v2/admin/submissions').json()['total'] == 0
    assert f.client.get('/api/v2/papers').json()['total'] == 0
    assert f.client.get(f'/api/v2/papers/{f.paper_id}').status_code == 404
    # An idempotent approval replay must not expose the removed snapshot.
    response = f.client.post(url+'/decisions', json=decision, headers=headers)
    assert response.status_code == 404, response.text
    with f.session_factory() as session:
        saved = session.get(PaperSubmission, submission.id)
        assert saved.snapshot == submission.snapshot and saved.content_hash == submission.content_hash
        published = session.scalar(select(PublishedPaperVersion).where(PublishedPaperVersion.paper_id == f.paper_id))
        assert (published is not None) == approved
        assert AuditService().verify_chain(session).valid
