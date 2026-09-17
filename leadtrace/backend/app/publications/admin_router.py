from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.publications.models import AdminDecision, PublishedPaperVersion
from app.publications.schemas import (
    AdminDecisionRequest,
    AdminDecisionResponse,
    AdminSubmissionDetailResponse,
    AdminSubmissionListItem,
    AdminSubmissionListResponse,
    ChangeEventResponse,
    DecisionMutationResponse,
    PublishedPaperVersionResponse,
)
from app.publications.service import (
    DecisionForbiddenError,
    DecisionHashMismatchError,
    DecisionIdempotencyConflictError,
    DecisionNotFoundError,
    DecisionReasonRequiredError,
    DecisionStateConflictError,
    PublicationService,
)
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.workspaces.models import ChangeEvent, PaperSubmission
from app.workspaces.schemas import BibliographyResponse, SubmissionResponse


def _submission_response(submission: PaperSubmission) -> SubmissionResponse:
    return SubmissionResponse(
        id=submission.id,
        paper_id=submission.paper_id,
        workspace_id=submission.workspace_id,
        review_task_id=submission.review_task_id,
        submission_number=submission.submission_number,
        idempotency_key=submission.idempotency_key,
        snapshot=submission.snapshot,
        content_hash=submission.content_hash,
        workspace_version=submission.workspace_version,
        submitted_by_id=submission.submitted_by_id,
        reviewer_note=submission.reviewer_note,
        submitted_at=submission.submitted_at,
    )


def _bibliography(snapshot: dict[str, object]) -> BibliographyResponse:
    paper = snapshot["paper"]
    if not isinstance(paper, dict):
        raise RuntimeError("Published snapshot bibliography is invalid")
    return BibliographyResponse.model_validate(
        {
            "paper_id": paper["id"],
            "paper_key": paper["paper_key"],
            "title": paper["title"],
            "journal": paper["journal"],
            "publication_year": paper["publication_year"],
            "volume": paper["volume"],
            "issue": paper["issue"],
            "doi": paper.get("doi"),
        }
    )


def _event_response(event: ChangeEvent) -> ChangeEventResponse:
    return ChangeEventResponse(
        id=event.id,
        paper_id=event.paper_id,
        workspace_id=event.workspace_id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        action=event.action,
        before_value=event.before_value,
        after_value=event.after_value,
        actor_kind=event.actor_kind,
        actor_id=event.actor_id,
        ai_run_id=event.ai_run_id,
        occurred_at=event.occurred_at,
    )


def _decision_response(decision: AdminDecision) -> AdminDecisionResponse:
    return AdminDecisionResponse(
        id=decision.id,
        submission_id=decision.submission_id,
        paper_id=decision.paper_id,
        content_hash=decision.content_hash,
        action=decision.action,
        reason=decision.reason,
        decided_by_id=decision.decided_by_id,
        idempotency_key=decision.idempotency_key,
        decided_at=decision.decided_at,
    )


def _published_response(
    version: PublishedPaperVersion | None,
) -> PublishedPaperVersionResponse | None:
    if version is None:
        return None
    return PublishedPaperVersionResponse(
        id=version.id,
        paper_id=version.paper_id,
        submission_id=version.submission_id,
        admin_decision_id=version.admin_decision_id,
        version_number=version.version_number,
        snapshot=version.snapshot,
        content_hash=version.content_hash,
        decision_action=version.decision_action,
        published_by_id=version.published_by_id,
        published_at=version.published_at,
    )


def _translate_decision_error(error: Exception) -> APIError | HTTPException:
    if isinstance(error, DecisionNotFoundError):
        return APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if isinstance(error, DecisionForbiddenError):
        return HTTPException(status_code=403, detail="Permission denied")
    if isinstance(error, DecisionHashMismatchError):
        return APIError(
            409,
            "SUBMISSION_HASH_MISMATCH",
            "Submission content hash does not match",
        )
    if isinstance(error, DecisionIdempotencyConflictError):
        return APIError(409, "IDEMPOTENCY_CONFLICT", str(error))
    if isinstance(error, DecisionStateConflictError):
        return APIError(409, "SUBMISSION_STATE_CONFLICT", str(error))
    if isinstance(error, (DecisionReasonRequiredError, ValueError)):
        return APIError(422, "INVALID_REQUEST", str(error))
    raise error


def create_admin_publications_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v2/admin/submissions", tags=["paper publications"])
    service = PublicationService()
    session_secret = settings.session_secret.get_secret_value()

    @router.get("", response_model=AdminSubmissionListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.APPROVE_CHANGESET)
    def list_pending_submissions(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> AdminSubmissionListResponse:
        try:
            with session.begin():
                pending = service.list_pending_submissions(session, actor=principal)
                items = []
                for item in pending:
                    bibliography = _bibliography(item.submission.snapshot)
                    items.append(
                        AdminSubmissionListItem(
                            submission_id=item.submission.id,
                            paper_id=item.submission.paper_id,
                            workspace_id=item.submission.workspace_id,
                            submission_number=item.submission.submission_number,
                            content_hash=item.submission.content_hash,
                            submitted_by_id=item.submission.submitted_by_id,
                            submitted_at=item.submission.submitted_at,
                            paper_key=bibliography.paper_key,
                            title=bibliography.title,
                        )
                    )
        except DecisionForbiddenError as error:
            raise _translate_decision_error(error) from error
        return AdminSubmissionListResponse(items=items, total=len(items))

    @router.get("/{submission_id}", response_model=AdminSubmissionDetailResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.APPROVE_CHANGESET)
    def get_submission(
        submission_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> AdminSubmissionDetailResponse:
        try:
            with session.begin():
                review = service.get_submission_review(
                    session,
                    submission_id=submission_id,
                    actor=principal,
                )
                return AdminSubmissionDetailResponse(
                    submission=_submission_response(review.submission),
                    bibliography=_bibliography(review.submission.snapshot),
                    change_events=[_event_response(event) for event in review.change_events],
                    reviewer_diff=[_event_response(event) for event in review.reviewer_diff],
                )
        except (
            DecisionForbiddenError,
            DecisionNotFoundError,
            DecisionStateConflictError,
        ) as error:
            raise _translate_decision_error(error) from error

    @router.post(
        "/{submission_id}/decisions",
        response_model=DecisionMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.APPROVE_CHANGESET)
    def decide_submission(
        submission_id: UUID,
        payload: AdminDecisionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        idempotency_key_header: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DecisionMutationResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        header_key = idempotency_key_header.strip() if idempotency_key_header else None
        idempotency_key = header_key or payload.idempotency_key
        if idempotency_key is None:
            raise APIError(422, "INVALID_REQUEST", "idempotency_key is required")
        try:
            with session.begin():
                result = service.decide(
                    session,
                    submission_id=submission_id,
                    content_hash=payload.content_hash,
                    action=payload.action,
                    reason=payload.reason,
                    idempotency_key=idempotency_key,
                    actor=principal,
                )
                return DecisionMutationResponse(
                    decision=_decision_response(result.decision),
                    published_version=_published_response(result.published_version),
                )
        except (
            DecisionForbiddenError,
            DecisionHashMismatchError,
            DecisionIdempotencyConflictError,
            DecisionNotFoundError,
            DecisionReasonRequiredError,
            DecisionStateConflictError,
            ValueError,
        ) as error:
            raise _translate_decision_error(error) from error

    return router


__all__ = ["create_admin_publications_router"]
