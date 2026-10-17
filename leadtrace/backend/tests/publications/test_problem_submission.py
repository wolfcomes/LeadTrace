import pytest

from app.publications.metadata_supplement import supplement_metadata
from app.publications.models import AdminDecisionAction
from app.publications.service import PublicationService, DecisionStateConflictError
from app.users.models import User
from app.workspaces.submission import SubmissionService


def _problem(f):
    with f.session_factory.begin() as session:
        return SubmissionService().submit(session, workspace_id=f.workspace_id,
            reviewer_id=f.reviewer_id, expected_workspace_version=1,
            idempotency_key='report-issue', reviewer_note=None,
            problem_reason='The reported structures are internally inconsistent.')


def test_admin_sees_problem_reason_and_cannot_publish_but_can_return(publication_fixture):
    f = publication_fixture
    submission = _problem(f)
    f.login('publication.admin')
    listing = f.client.get('/api/v2/admin/submissions?reviewer_rounds=true')
    assert listing.status_code == 200
    assert listing.json()['items'][0]['submission_kind'] == 'problem_report'
    detail = f.client.get(f'/api/v2/admin/submissions/{submission.id}?reviewer_rounds=true')
    assert detail.status_code == 200
    assert detail.json()['submission']['snapshot']['problem_report']['reason']
    with f.session_factory.begin() as session:
        admin = session.get(User, f.admin_id)
        with pytest.raises(DecisionStateConflictError, match='Problem reports cannot be published'):
            PublicationService().decide(session, submission_id=submission.id,
                content_hash=submission.content_hash, action=AdminDecisionAction.APPROVE,
                reason='Approve', idempotency_key='no-publish', actor=admin)
        result = PublicationService().decide(session, submission_id=submission.id,
            content_hash=submission.content_hash, action=AdminDecisionAction.REQUEST_CHANGES,
            reason='Please resolve the article issue', idempotency_key='return', actor=admin)
        assert result.published_version is None


def test_metadata_supplement_cannot_turn_problem_report_into_publishable_submission(publication_fixture):
    f = publication_fixture
    submission = _problem(f)
    with f.session_factory.begin() as session:
        with pytest.raises(ValueError, match='Problem reports must be returned'):
            supplement_metadata(session, submission_id=submission.id,
                content_hash=submission.content_hash, expected_workspace_version=2,
                updates={'abstract': 'Added metadata'}, reason='Fill abstract',
                actor=session.get(User, f.admin_id), request_id='problem-supplement')


def test_problem_return_requires_normal_review_before_publish(publication_fixture):
    from sqlalchemy import select
    from app.workspaces.models import PaperSectionReview, PaperSectionState, PaperWorkspace
    from app.workspaces.submission import SubmissionValidationError
    f = publication_fixture
    report = _problem(f)
    with f.session_factory.begin() as session:
        admin = session.get(User, f.admin_id)
        PublicationService().decide(session, submission_id=report.id, content_hash=report.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES, reason='Resolve and review',
            idempotency_key='return-report', actor=admin)
        version = session.get(PaperWorkspace, f.workspace_id).version
        with pytest.raises(SubmissionValidationError):
            SubmissionService().submit(session, workspace_id=f.workspace_id, reviewer_id=f.reviewer_id,
                expected_workspace_version=version, idempotency_key='not-ready', reviewer_note=None)
        for section in session.scalars(select(PaperSectionReview).where(PaperSectionReview.workspace_id == f.workspace_id)):
            section.state = PaperSectionState.NOT_REPORTED
        normal = SubmissionService().submit(session, workspace_id=f.workspace_id, reviewer_id=f.reviewer_id,
            expected_workspace_version=version, idempotency_key='review-complete', reviewer_note='Reviewed after issue resolution')
        assert 'problem_report' not in normal.snapshot
        result = PublicationService().decide(session, submission_id=normal.id, content_hash=normal.content_hash,
            action=AdminDecisionAction.APPROVE, reason='Issue resolved and review complete',
            idempotency_key='approve-normal', actor=admin)
        assert result.published_version is not None
