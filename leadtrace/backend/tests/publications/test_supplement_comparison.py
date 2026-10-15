from copy import deepcopy

import pytest
from sqlalchemy import select

from app.publications.metadata_supplement import supplement_metadata
from app.publications.service import PublicationService
from app.publications.models import AdminDecisionAction
from app.users.models import User
from app.workspaces.models import PaperSubmission, PaperWorkspace, ChangeEvent, ChangeActorKind


def reviewer_submission(f):
    csrf = f.login('publication.reviewer')
    response = f.client.patch(
        f'/api/v2/workspaces/{f.workspace_id}/bibliography',
        headers={'X-CSRF-Token': csrf},
        json={'expected_workspace_version': 1, 'title': 'Reviewer corrected title'},
    )
    assert response.status_code == 200
    return f.submit()


def supplement(f, original, patch):
    with f.session_factory.begin() as s:
        return supplement_metadata(
            s, submission_id=original.id, content_hash=original.content_hash,
            expected_workspace_version=original.workspace_version, updates=patch,
            reason='Authorized article metadata supplement',
            actor=s.get(User, f.admin_id), request_id='comparison-regression',
        )


def detail(f, submission):
    f.login('publication.admin')
    response = f.client.get(f'/api/v2/admin/submissions/{submission.id}?include_comparison=true')
    assert response.status_code == 200
    return response.json()


def test_consecutive_supplements_retain_reviewer_round_and_original_note(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    original = deepcopy(first.snapshot)
    before = detail(f, first)
    second = supplement(f, first, {'pmid': '12345678'})
    third = supplement(f, second, {'abstract': 'An abstract.', 'abstract_source': 'Page 1', 'abstract_status': 'extracted'})
    result = detail(f, third)
    comparison = result['comparison']
    assert comparison['kind'] == 'reviewer_start'
    assert comparison['baseline_snapshot'] == before['comparison']['baseline_snapshot']
    assert [e['id'] for e in result['reviewer_diff']] == [e['id'] for e in before['reviewer_diff']]
    assert {e['actor_kind'] for e in comparison['events']} == {'reviewer', 'admin'}
    assert comparison['reviewer_submission']['id'] == str(first.id)
    assert comparison['reviewer_submission']['reviewer_note'] == first.reviewer_note
    assert comparison['reviewer_submission']['content_hash'] == first.content_hash
    assert comparison['supplement_count'] == 2
    assert result['submission']['reviewer_note'] is None
    assert result['submission']['content_hash'] == third.content_hash
    assert result['submission']['snapshot']['paper']['pmid'] == '12345678'
    assert next(s for s in result['submission']['snapshot']['sections'] if s['section_key'] == 'bibliography')['state'] == 'pending'
    assert not comparison['warnings']
    with f.session_factory() as s:
        assert s.get(PaperSubmission, first.id).snapshot == original
        assert len(list(s.scalars(select(PaperSubmission)))) == 3


def test_true_reviewer_resubmission_starts_new_round_before_next_supplement(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678'})
    with f.session_factory.begin() as s:
        PublicationService().decide(
            s, submission_id=second.id, content_hash=second.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES, reason='Reviewer must revise title',
            idempotency_key='real-return', actor=s.get(User, f.admin_id),
        )
        version = s.get(PaperWorkspace, f.workspace_id).version
    csrf = f.login('publication.reviewer')
    response = f.client.patch(f'/api/v2/workspaces/{f.workspace_id}/bibliography',
        headers={'X-CSRF-Token': csrf},
        json={'expected_workspace_version': version, 'title': 'Second round title'})
    assert response.status_code == 200
    third = f.submit(key='real-second-round')
    third_detail = detail(f, third)
    assert third_detail['comparison']['baseline_snapshot'] == second.snapshot
    assert third_detail['comparison']['reviewer_submission'] is None
    fourth = supplement(f, third, {'pmcid': 'PMC12345678'})
    result = detail(f, fourth)
    assert result['comparison']['kind'] == 'previous_submission'
    assert result['comparison']['baseline_submission_number'] == 2
    assert result['comparison']['baseline_snapshot'] == second.snapshot
    assert result['comparison']['reviewer_submission']['id'] == str(third.id)
    assert result['comparison']['supplement_count'] == 1
    assert [x['id'] for x in result['reviewer_diff']] == [x['id'] for x in third_detail['reviewer_diff']]


@pytest.mark.parametrize('broken', ['parent_hash', 'current_hash', 'actor', 'parent_id', 'origin_actor'])
def test_invalid_supplement_links_warn_without_inventing_baseline(publication_fixture, broken):
    f = publication_fixture
    first = reviewer_submission(f)
    second = supplement(f, first, {'pmid': '12345678'})
    with f.session_factory() as s:
        boundary = s.scalar(select(ChangeEvent).where(
            ChangeEvent.entity_id == (first.id if broken == 'origin_actor' else second.id),
            ChangeEvent.action == 'workspace.submit'))
        if broken == 'parent_hash': boundary.before_value = {**boundary.before_value, 'content_hash': '0' * 64}
        if broken == 'current_hash': boundary.after_value = {**boundary.after_value, 'content_hash': '0' * 64}
        if broken in {'actor', 'origin_actor'}: boundary.actor_kind = ChangeActorKind.AI
        if broken == 'parent_id': boundary.before_value = {**boundary.before_value, 'submission_id': str(second.id)}
        # Fault injection remains in memory; historical database rows stay immutable.
        with s.no_autoflush:
            review = PublicationService().get_submission_review(s, submission_id=second.id, actor=s.get(User, f.admin_id))
        assert review.comparison_kind == 'unavailable'
        assert review.baseline_snapshot is None
        assert review.reviewer_submission is None
        assert review.comparison_warnings
