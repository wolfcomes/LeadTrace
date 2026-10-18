from copy import deepcopy
import pytest

from sqlalchemy import select

from app.publications.models import AdminDecisionAction
from app.publications.service import PublicationService
from app.users.models import User
from app.workspaces.models import ChangeActorKind, ChangeEvent, PaperSubmission, PaperWorkspace
from tests.publications.test_supplement_comparison import reviewer_submission, supplement


def round_detail(f, submission):
    f.login('publication.admin')
    response = f.client.get(f'/api/v2/admin/submissions/{submission.id}?include_comparison=true&reviewer_rounds=true')
    assert response.status_code == 200
    return response.json()


def return_submission(f, submission):
    with f.session_factory.begin() as s:
        PublicationService().decide(s, submission_id=submission.id, content_hash=submission.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES, reason='Please check added metadata only',
            idempotency_key=f'return-{submission.id}', actor=s.get(User, f.admin_id))
        return s.get(PaperWorkspace, f.workspace_id).version


def test_supplement_url_selects_original_reviewer_and_separates_additions(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    original = deepcopy(first.snapshot)
    second = supplement(f, first, {'pmid': '12345678'})
    third = supplement(f, second, {'abstract': 'Added abstract', 'abstract_source': 'Page 1', 'abstract_status': 'extracted'})
    data = round_detail(f, third)
    assert data['submission']['id'] == str(first.id)
    assert data['submission']['snapshot'] == original
    rounds = data['review_rounds']
    assert [x['id'] for x in rounds['versions']] == [str(first.id)]
    assert rounds['versions'][0]['round_number'] == 1
    assert rounds['versions'][0]['submitted_at'] == data['submission']['submitted_at']
    assert rounds['versions'][0]['submitted_by_name'] == 'Publication Reviewer'
    assert rounds['versions'][0]['status'] == 'awaiting_reviewer'
    assert rounds['versions'][0]['decision'] is None  # Supplement closure is not a human rejection.
    assert not rounds['can_decide']
    assert rounds['supplements'][0]['phase'] == 'after_submission'
    assert rounds['supplements'][0]['snapshot']['paper']['pmid'] == '12345678'
    assert rounds['supplements'][0]['count'] == 2
    assert all(e['actor_kind'] == 'reviewer' for e in data['comparison']['events'])
    with f.session_factory() as s:
        assert s.get(PaperSubmission, first.id).snapshot == original


def test_resubmission_uses_reviewer_round_and_keeps_human_correction(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678', 'abstract': 'AI text', 'abstract_source': 'Page 1', 'abstract_status': 'extracted'})
    version = return_submission(f, second)
    csrf = f.login('publication.reviewer')
    response = f.client.patch(f'/api/v2/workspaces/{f.workspace_id}/bibliography',
        headers={'X-CSRF-Token': csrf}, json={'expected_workspace_version': version, 'abstract': 'Human corrected text'})
    assert response.status_code == 200
    third = f.submit(key='reviewer-round-2')
    data = round_detail(f, third)
    assert [x['round_number'] for x in data['review_rounds']['versions']] == [1, 2]
    assert [x['id'] for x in data['review_rounds']['versions']] == [str(first.id), str(third.id)]
    assert data['review_rounds']['can_decide']
    assert data['comparison']['baseline_submission_number'] == 1
    assert data['comparison']['baseline_snapshot']['paper']['abstract'] == 'AI text'
    assert data['submission']['snapshot']['paper']['abstract'] == 'Human corrected text'
    assert data['comparison']['baseline_snapshot']['paper']['pmid'] == data['submission']['snapshot']['paper']['pmid']
    assert data['review_rounds']['supplements'][0]['phase'] == 'before_submission'
    assert not round_detail(f, first)['review_rounds']['can_decide']


def test_round_list_uses_reviewer_time_and_distinguishes_awaiting_recheck(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678'})
    return_submission(f, second)
    f.login('publication.admin')
    response = f.client.get('/api/v2/admin/submissions?reviewer_rounds=true')
    assert response.status_code == 200
    item = response.json()['items'][0]
    assert item['submission_id'] == str(first.id)
    assert item['reviewer_round_number'] == 1
    assert item['review_status'] == 'awaiting_reviewer'
    assert item['submitted_at'] == round_detail(f, first)['submission']['submitted_at']
    followup = round_detail(f, first)['review_rounds']['versions'][0]['followup_decision']
    assert followup['submission_id'] == str(second.id)
    assert followup['reason'] == 'Please check added metadata only'


def test_return_supplement_preserves_science_confirmations_and_replays(publication_fixture):
    from app.publications.supplement_review import return_supplement_for_review
    from app.audit.service import AuditService
    from app.workspaces.models import PaperSectionReview, ReviewTask
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678'})
    with f.session_factory.begin() as s:
        sections = [(r.id, r.state, r.note) for r in s.scalars(select(PaperSectionReview))]
        args = dict(submission_id=second.id, content_hash=second.content_hash,
            expected_workspace_version=second.workspace_version,
            actor=s.get(User, f.admin_id), reason='Check only additions', request_id='return-test')
        result = return_supplement_for_review(s, **args)
        assert return_supplement_for_review(s, **args).decision.id == result.decision.id
        assert s.get(PaperWorkspace, f.workspace_id).state.value == 'editing'
        assert s.get(ReviewTask, f.task_id).status.value == 'changes_requested'
        assert [(r.id, r.state, r.note) for r in s.scalars(select(PaperSectionReview))] == sections
        assert s.get(PaperSubmission, second.id).snapshot == second.snapshot
        assert s.get(PaperSubmission, first.id).snapshot == first.snapshot
        assert AuditService().verify_chain(s).valid


def test_technical_supplement_cannot_be_approved_even_with_correct_hash(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678'})
    csrf = f.login('publication.admin')
    response = f.client.post(f'/api/v2/admin/submissions/{second.id}/decisions',
        headers={'X-CSRF-Token': csrf, 'Idempotency-Key': 'no-technical-approval'},
        json={'content_hash': second.content_hash, 'action': 'approve', 'reason': 'Would approve unconfirmed additions'})
    assert response.status_code == 409
    assert round_detail(f, second)['review_rounds']['versions'][0]['status'] == 'awaiting_reviewer'


def test_genuine_return_remains_visible_and_previous_version_is_read_only(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    return_submission(f, first)
    third = f.submit(key='after-genuine-return')
    data = round_detail(f, first)
    assert data['review_rounds']['versions'][0]['status'] == 'request_changes'
    assert data['review_rounds']['versions'][0]['decision']['reason'] == 'Please check added metadata only'
    assert data['review_rounds']['versions'][1]['id'] == str(third.id)
    assert not data['review_rounds']['can_decide']
    assert round_detail(f, third)['review_rounds']['can_decide']


def test_projection_requires_admin(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    f.login('publication.reviewer')
    assert f.client.get(f'/api/v2/admin/submissions/{first.id}?reviewer_rounds=true').status_code == 403
    assert f.client.get('/api/v2/admin/submissions?reviewer_rounds=true').status_code == 403


@pytest.mark.parametrize('previous', [False, True])
def test_unverified_latest_submission_stays_visible_in_list(publication_fixture, monkeypatch, previous):
    import app.workspaces.submission as module
    f = publication_fixture
    if previous:
        first = reviewer_submission(f)
        return_submission(f, first)
    real = module.ChangeEvent
    def invalid_boundary(**kwargs):
        if kwargs.get('action') == 'workspace.submit':
            kwargs['action'] = 'legacy.missing_submit_boundary'
        return real(**kwargs)
    monkeypatch.setattr(module, 'ChangeEvent', invalid_boundary)
    last = f.submit(key='missing-boundary')
    f.login('publication.admin')
    data = f.client.get('/api/v2/admin/submissions?reviewer_rounds=true').json()
    assert data['total'] == 1
    assert data['items'][0]['submission_id'] == str(last.id)
    assert data['items'][0]['review_status'] == 'unavailable'
    assert data['items'][0]['reviewer_round_number'] is None
    assert data['items'][0]['review_warning']


def test_directory_opens_latest_record_for_full_supplement_validation(publication_fixture, monkeypatch):
    import app.publications.metadata_supplement as module
    f = publication_fixture
    first = reviewer_submission(f)
    canonical = module.canonical_snapshot_hash
    monkeypatch.setattr(module, 'canonical_snapshot_hash',
        lambda snapshot: '0' * 64 if snapshot['paper'].get('pmid') == '12345678' else canonical(snapshot))
    corrupt = supplement(f, first, {'pmid': '12345678'})
    f.login('publication.admin')
    listing = f.client.get('/api/v2/admin/submissions?reviewer_rounds=true').json()['items'][0]
    assert listing['submission_id'] == str(first.id)  # Directory identity stays the human submission.
    assert listing['review_entry_id'] == str(corrupt.id)  # Detail validates the full current chain.
    data = round_detail(f, corrupt)
    assert data['submission']['id'] == str(corrupt.id)
    assert data['review_rounds']['selected_round_number'] is None
    assert not data['review_rounds']['can_decide']
    assert data['comparison']['kind'] == 'unavailable'
    assert data['review_rounds']['warnings']


@pytest.mark.parametrize('later_round', [False, True])
@pytest.mark.parametrize('verified', [False, True])
def test_ai_revision_baseline_keeps_reviewer_changes(publication_fixture, later_round, verified):
    from uuid import uuid4
    from app.ai_tasks.models import AiTask
    from app.ai_tasks.repair_apply import _row_snapshot
    from app.papers.models import Paper
    from app.workspaces.snapshot import canonical_snapshot_hash
    f = publication_fixture
    if later_round:
        first = reviewer_submission(f)
        return_submission(f, first)
    with f.session_factory.begin() as s:
        paper = s.get(Paper, f.paper_id)
        workspace = s.get(PaperWorkspace, f.workspace_id)
        job = AiTask(paper_id=f.paper_id, workspace_id=f.workspace_id, requested_by_id=f.admin_id,
            idempotency_key='approval-repair', request_digest='a'*64, action='revise', preset_id='test',
            adapter='codex', model='test', reasoning_effort='high', workspace_version=workspace.version,
            task_version=1, source_sha256='a'*64, timeout_seconds=1800, state='completed',
            delivery_state='applied', result_summary={'applied_workspace_version':workspace.version+1})
        s.add(job); s.flush()
        before = _row_snapshot(paper)
        paper.abstract = 'AI addition'; paper.abstract_status = 'extracted'; paper.abstract_source = 'Page 1'
        after = _row_snapshot(paper)
        metadata = {'repair_job_id':str(job.id if verified else uuid4()), 'delivery_mode':'automatic_revision', 'requested_by_id':str(f.admin_id)}
        s.add(ChangeEvent(paper_id=f.paper_id, workspace_id=f.workspace_id, entity_type='paper',
            entity_id=f.paper_id, action='paper.repair_update', actor_kind=ChangeActorKind.AI,
            before_value={**before,'_repair':metadata}, after_value={**after,'_repair':metadata}))
        workspace.version += 1
        version = workspace.version
    csrf = f.login('publication.reviewer')
    response = f.client.patch(f'/api/v2/workspaces/{f.workspace_id}/bibliography',
        headers={'X-CSRF-Token':csrf}, json={'expected_workspace_version':version, 'title':'Human title after repair'})
    assert response.status_code == 200
    submission = f.submit(key='after-ai-repair')
    frozen = deepcopy(submission.snapshot)
    data = round_detail(f, submission)
    # A repair before the first human event is already part of the initial
    # baseline. Later rounds must additionally verify its task binding.
    if verified or not later_round:
        baseline = data['comparison']['baseline_snapshot']
        assert baseline['paper']['abstract'] == 'AI addition'
        assert baseline['paper']['title'] != frozen['paper']['title']
        assert not data['comparison']['warnings']
    else:
        assert data['comparison']['kind'] == 'unavailable'
        assert data['comparison']['warnings']
    assert data['submission']['snapshot'] == frozen
    assert canonical_snapshot_hash(frozen) == submission.content_hash
    assert all(e['actor_kind'] == 'reviewer' for e in data['comparison']['events'])
