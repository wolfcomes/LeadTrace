"""Operator transition from technical supplement to the existing Reviewer draft."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService, canonical_content_hash
from app.papers.metadata import ARTICLE_METADATA_DEFAULTS
from app.publications.models import AdminDecision, AdminDecisionAction
from app.publications.reviewer_rounds import RoundHistory
from app.publications.service import PublicationService, DecisionResult
from app.users.models import User, UserRole
from app.workspaces.history import lock_workspace
from app.workspaces.models import PaperSubmission
from app.workspaces.snapshot import build_paper_snapshot


def return_supplement_for_review(session: Session, *, submission_id: UUID,
        content_hash: str, expected_workspace_version: int, actor: User,
        reason: str, request_id: str) -> DecisionResult:
    if actor.role is not UserRole.ADMIN or not actor.is_enabled:
        raise PermissionError('An enabled Admin is required')
    reason = reason.strip()
    if not reason:
        raise ValueError('Explain which additions need Reviewer verification')
    submission = session.get(PaperSubmission, submission_id)
    if submission is None:
        raise ValueError('Submission not found')
    context = lock_workspace(session, submission.workspace_id)
    if context is None:
        raise ValueError('Active workspace not found')
    key = 'supplement-review:' + canonical_content_hash({
        'submission': str(submission_id), 'hash': content_hash,
        'version': expected_workspace_version, 'actor': str(actor.id), 'reason': reason})
    service = PublicationService()
    replay = session.scalar(select(AdminDecision).where(
        AdminDecision.decided_by_id == actor.id, AdminDecision.idempotency_key == key))
    if replay is not None:
        return service.decide(session, submission_id=submission_id, content_hash=content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES, reason=reason, idempotency_key=key, actor=actor)
    session.refresh(context.workspace)
    if context.workspace.version != expected_workspace_version or submission.content_hash != content_hash:
        raise RuntimeError('Supplement or workspace changed; inspect a fresh baseline')
    history = RoundHistory(session, submission.workspace_id)
    if submission.id not in history.origins or history.submissions[-1].id != submission.id:
        raise RuntimeError('Only a verified latest metadata supplement can be returned by this operation')
    current = build_paper_snapshot(session, submission.workspace_id)
    excluded = {'sections', 'review_progress', 'paper'}
    if ({k: v for k, v in current.items() if k not in excluded}
            != {k: v for k, v in submission.snapshot.items() if k not in excluded}
            or (ARTICLE_METADATA_DEFAULTS | current['paper']) != (ARTICLE_METADATA_DEFAULTS | submission.snapshot['paper'])):
        raise RuntimeError('Workspace no longer matches the supplemented snapshot')
    result = service.decide(session, submission_id=submission_id, content_hash=content_hash,
        action=AdminDecisionAction.REQUEST_CHANGES, reason=reason, idempotency_key=key, actor=actor)
    AuditService().append_event(session, actor_id=actor.id, action='submission.supplement_review_requested',
        target_type='paper_submission', target_id=submission_id, paper_id=submission.paper_id,
        changeset_id=None, release_id=None, ip_address='127.0.0.1', request_id=request_id,
        result='success', reason=reason, before_hash=content_hash, after_hash=content_hash,
        details={'reviewer_submission_id': str(history.origins[submission_id].id),
            'decision_id': str(result.decision.id), 'scientific_content_changed': False,
            'existing_confirmations_preserved': True})
    return result
