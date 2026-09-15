from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import (
    AuditService,
    canonical_content_hash,
    persisted_json_value,
    redact_secrets,
)
from app.approvals.service import ApprovalConflict, ApprovalForbidden, ApprovalService
from app.api.errors import APIError, request_id_for
from app.auth.router import resolve_remote_address
from app.database import get_db_session
from app.reviews.schemas import (
    ChangesetCreateRequest,
    ChangesetDecisionRequest,
    ChangesetItemCreateRequest,
    ChangesetItemDeleteRequest,
    ChangesetItemFromBaseRequest,
    ChangesetItemResponse,
    ChangesetItemUpdateRequest,
    ChangesetMutationResponse,
    ChangesetResponse,
    ChangesetSubmitRequest,
    ChangesetTransitionRequest,
    ChangesetUpdateRequest,
    ReviewTaskCreateRequest,
    ReviewTaskReassignRequest,
    ReviewTaskResponse,
)
from app.reviews.comments import (
    CommentAction,
    CommentCreateRequest,
    CommentEventResponse,
    CommentForbidden,
    CommentNotFound,
    CommentResponse,
    CommentService,
    CommentStateConflict,
    CommentTransitionRequest,
    InvalidComment,
)
from app.reviews.service import (
    BaseReleaseConflict,
    ChangesetItemHasComments,
    ChangesetItemHasRevisions,
    InvalidReview,
    RevisionConflict,
    ReviewForbidden,
    ReviewNotFound,
    ReviewService,
    ReviewStateConflict,
)
from app.releases.models import ReleaseItem
from app.reviews.models import ChangesetItem, ReviewTask
from app.revisions.diff import build_revision_diff
from app.revisions.models import ObjectKind, ObjectRevision
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Principal, WorkflowState
from app.users.models import UserRole


def _region_fields_for_revision(
    revision: ObjectRevision | None,
) -> dict[str, object] | None:
    if revision is None:
        return None
    return {
        "x0": revision.region_x0,
        "y0": revision.region_y0,
        "x1": revision.region_x1,
        "y1": revision.region_y1,
        "rotation": revision.region_rotation,
    }


def _dedicated_fields_for_revision(
    revision: ObjectRevision | None,
) -> dict[str, object] | None:
    if revision is None:
        return None
    return {
        "activity_metric": revision.activity_metric,
        "activity_unit": revision.activity_unit,
        "activity_value": revision.activity_value,
        "canonical_smiles": revision.canonical_smiles,
        "evidence_text": revision.evidence_text,
        "relation_status": revision.relation_status,
        "relation_type": revision.relation_type,
        "proposal_disposition": revision.proposal_disposition,
    }


_MISSING = object()
_DEDICATED_FIELD_NAMES = (
    "activity_metric",
    "activity_unit",
    "activity_value",
    "canonical_smiles",
    "evidence_text",
    "relation_status",
    "relation_type",
    "proposal_disposition",
)


def _draft_dedicated_fields(
    base: ObjectRevision | None,
    snapshot: Mapping[str, object],
) -> dict[str, object] | None:
    fields = _dedicated_fields_for_revision(base) or {}
    normalized = snapshot.get("normalized_values")
    for field in _DEDICATED_FIELD_NAMES:
        candidate = snapshot.get(field, _MISSING)
        if candidate is _MISSING and isinstance(normalized, Mapping):
            candidate = normalized.get(field, _MISSING)
        if candidate is not _MISSING:
            fields[field] = candidate
    return fields or None


def create_reviews_router(session_secret: str) -> APIRouter:
    """Build the review router with the application CSRF secret."""

    router = APIRouter(prefix="/api/v1/review", tags=["review workflow"])
    service = ReviewService()
    comment_service = CommentService()
    audit_service = AuditService()

    def require_reviewer_or_admin(principal: Principal) -> None:
        if principal.role is UserRole.VISITOR:
            raise HTTPException(status_code=403, detail="Permission denied")

    def verify_csrf(principal: Principal, token: str | None) -> None:
        require_request_csrf(principal, token, session_secret)

    def as_error(error: Exception) -> HTTPException:
        if isinstance(error, CommentNotFound):
            return HTTPException(status_code=404, detail="Resource not found")
        if isinstance(error, CommentForbidden):
            return HTTPException(status_code=403, detail="Permission denied")
        if isinstance(error, CommentStateConflict):
            return APIError(409, "COMMENT_STATE_CONFLICT", str(error))
        if isinstance(error, InvalidComment):
            return HTTPException(status_code=422, detail=str(error))
        if isinstance(error, ReviewNotFound):
            return HTTPException(status_code=404, detail="Resource not found")
        if isinstance(error, ReviewForbidden):
            return HTTPException(status_code=403, detail="Permission denied")
        if isinstance(error, ApprovalForbidden):
            return HTTPException(status_code=403, detail="Permission denied")
        if isinstance(error, ApprovalConflict):
            return APIError(409, "APPROVAL_CONFLICT", str(error))
        if isinstance(error, RevisionConflict):
            return APIError(
                409,
                "REVISION_CONFLICT",
                "Review resource changed concurrently",
                details={
                    "expected_version": error.expected_version,
                    "current_version": error.current_version,
                },
            )
        if isinstance(error, BaseReleaseConflict):
            return APIError(
                409,
                "BASE_RELEASE_CONFLICT",
                "Changeset base release is no longer current",
                details={
                    "base_release_id": str(error.base_release_id),
                    "current_release_id": str(error.current_release_id)
                    if error.current_release_id
                    else None,
                },
            )
        if isinstance(error, ReviewStateConflict):
            return APIError(
                409,
                "REVIEW_STATE_CONFLICT",
                str(error),
                details={"current_state": error.current_state},
            )
        if isinstance(error, ChangesetItemHasRevisions):
            return APIError(
                409,
                "CHANGESET_ITEM_HAS_REVISIONS",
                "Changeset item has linked revisions and cannot be deleted",
                details={"item_id": str(error.item_id)},
            )
        if isinstance(error, ChangesetItemHasComments):
            return APIError(
                409,
                "CHANGESET_ITEM_HAS_COMMENTS",
                "Changeset item has linked comments and cannot be deleted",
                details={"item_id": str(error.item_id)},
            )
        if isinstance(error, InvalidReview):
            return HTTPException(status_code=422, detail=str(error))
        if isinstance(error, IntegrityError):
            return APIError(
                409,
                "REVIEW_CONFLICT",
                "Review resource conflicts with an existing record",
            )
        return HTTPException(
            status_code=400, detail="The request could not be completed"
        )

    def request_context(request: Request) -> tuple[str, str]:
        ip_address = resolve_remote_address(request, request.app.state.settings)
        return ip_address, request_id_for(request)

    def append_review_audit(
        session: Session,
        *,
        request: Request,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: UUID,
        paper_id: UUID,
        changeset_id: UUID | None,
        release_id: UUID | None,
        reason: str,
        before: object,
        after: object,
    ) -> None:
        ip_address, request_id = request_context(request)
        persisted_before = persisted_json_value(session, redact_secrets(before))
        persisted_after = persisted_json_value(session, redact_secrets(after))
        audit_service.append_event(
            session,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            paper_id=paper_id,
            changeset_id=changeset_id,
            release_id=release_id,
            ip_address=ip_address,
            request_id=request_id,
            result="success",
            reason=reason,
            before_hash=canonical_content_hash(persisted_before),
            after_hash=canonical_content_hash(persisted_after),
            details={"before": persisted_before, "after": persisted_after},
        )

    @router.get(
        "/changesets/{changeset_id}/comments",
        response_model=list[CommentResponse],
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_comments(
        changeset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[CommentResponse]:
        require_reviewer_or_admin(principal)
        try:
            with session.begin():
                comments = comment_service.list_comments(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                )
        except (CommentNotFound, CommentForbidden) as error:
            raise as_error(error) from error
        return [
            CommentResponse.from_model(comment, state) for comment, state in comments
        ]

    @router.post(
        "/changesets/{changeset_id}/comments",
        response_model=CommentResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_comment(
        changeset_id: UUID,
        payload: CommentCreateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> CommentResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        ip_address, request_id = request_context(request)
        try:
            with session.begin():
                comment, state = comment_service.create_comment(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    target_type=payload.target_type,
                    target_id=payload.target_id,
                    changeset_item_id=payload.changeset_item_id,
                    field_path=payload.field_path,
                    body=payload.body,
                    ip_address=ip_address,
                    request_id=request_id,
                )
        except (
            CommentNotFound,
            CommentForbidden,
            InvalidComment,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return CommentResponse.from_model(comment, state)

    @router.get(
        "/comments/{comment_id}/history",
        response_model=list[CommentEventResponse],
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_comment_history(
        comment_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[CommentEventResponse]:
        require_reviewer_or_admin(principal)
        try:
            with session.begin():
                events = comment_service.list_history(
                    session,
                    comment_id=comment_id,
                    actor_id=principal.user_id,
                )
        except (CommentNotFound, CommentForbidden) as error:
            raise as_error(error) from error
        return [CommentEventResponse.model_validate(item) for item in events]

    def transition_comment(
        *,
        comment_id: UUID,
        payload: CommentTransitionRequest,
        request: Request,
        session: Session,
        principal: Principal,
        csrf_token: str | None,
        action: CommentAction,
    ) -> CommentResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        ip_address, request_id = request_context(request)
        try:
            with session.begin():
                comment, state = comment_service.transition(
                    session,
                    comment_id=comment_id,
                    actor_id=principal.user_id,
                    action=action,
                    reason=payload.reason,
                    ip_address=ip_address,
                    request_id=request_id,
                )
        except (
            CommentNotFound,
            CommentForbidden,
            InvalidComment,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return CommentResponse.from_model(comment, state)

    @router.post("/comments/{comment_id}/resolve", response_model=CommentResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def resolve_comment(
        comment_id: UUID,
        payload: CommentTransitionRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> CommentResponse:
        return transition_comment(
            comment_id=comment_id,
            payload=payload,
            request=request,
            session=session,
            principal=principal,
            csrf_token=csrf_token,
            action=CommentAction.RESOLVED,
        )

    @router.post("/comments/{comment_id}/reopen", response_model=CommentResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def reopen_comment(
        comment_id: UUID,
        payload: CommentTransitionRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> CommentResponse:
        return transition_comment(
            comment_id=comment_id,
            payload=payload,
            request=request,
            session=session,
            principal=principal,
            csrf_token=csrf_token,
            action=CommentAction.REOPENED,
        )

    @router.get("/tasks", response_model=list[ReviewTaskResponse])
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_tasks(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[ReviewTaskResponse]:
        require_reviewer_or_admin(principal)
        with session.begin():
            tasks = service.list_tasks(
                session,
                None if principal.role is UserRole.ADMIN else principal.user_id,
            )
        return [ReviewTaskResponse.from_model(task) for task in tasks]

    @router.post("/tasks", response_model=ReviewTaskResponse, status_code=201)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_task(
        payload: ReviewTaskCreateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ReviewTaskResponse:
        require_reviewer_or_admin(principal)
        if principal.role is not UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permission denied")
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                task = service.create_task(
                    session,
                    paper_id=payload.paper_id,
                    assignee_id=payload.assigned_reviewer_id,
                    created_by_id=principal.user_id,
                    priority=payload.priority,
                )
                task_snapshot = ReviewTaskResponse.from_model(task).model_dump(
                    mode="json"
                )
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.task.created",
                    target_type="review_task",
                    target_id=task.id,
                    paper_id=task.paper_id,
                    changeset_id=None,
                    release_id=None,
                    reason="Created review task",
                    before=None,
                    after=task_snapshot,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return ReviewTaskResponse.from_model(task)

    @router.patch("/tasks/{task_id}/assignee", response_model=ReviewTaskResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def reassign_task(
        task_id: UUID,
        payload: ReviewTaskReassignRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ReviewTaskResponse:
        require_reviewer_or_admin(principal)
        if principal.role is not UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permission denied")
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                existing_task = session.scalar(
                    select(ReviewTask)
                    .where(ReviewTask.id == task_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                before = (
                    ReviewTaskResponse.from_model(existing_task).model_dump(mode="json")
                    if existing_task is not None
                    else None
                )
                task = service.reassign_task(
                    session,
                    task_id=task_id,
                    actor_id=principal.user_id,
                    assignee_id=payload.assigned_reviewer_id,
                    expected_version=payload.expected_version,
                )
                after = ReviewTaskResponse.from_model(task).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.task.reassigned",
                    target_type="review_task",
                    target_id=task.id,
                    paper_id=task.paper_id,
                    changeset_id=None,
                    release_id=None,
                    reason="Reassigned review task",
                    before=before,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return ReviewTaskResponse.from_model(task)

    @router.post("/changesets", response_model=ChangesetResponse, status_code=201)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_changeset(
        payload: ChangesetCreateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.create_changeset(
                    session,
                    paper_id=payload.paper_id,
                    actor_id=principal.user_id,
                    review_task_id=payload.review_task_id,
                    base_release_id=payload.base_release_id,
                    title=payload.title,
                    reason=payload.reason,
                )
                created = ChangesetResponse.from_model(changeset).model_dump(
                    mode="json"
                )
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset.created",
                    target_type="changeset",
                    target_id=changeset.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason=changeset.reason,
                    before=None,
                    after=created,
                )
                if payload.initialize_from_base:
                    base_entries = list(
                        session.execute(
                            select(ReleaseItem, ObjectRevision)
                            .join(
                                ObjectRevision,
                                (ObjectRevision.id == ReleaseItem.revision_id)
                                & (ObjectRevision.object_id == ReleaseItem.object_id),
                            )
                            .where(
                                ReleaseItem.release_id == changeset.base_release_id,
                                ReleaseItem.paper_id == changeset.paper_id,
                                ReleaseItem.object_kind.in_(
                                    [ObjectKind.PAPER, ObjectKind.EVIDENCE]
                                ),
                            )
                            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
                        )
                    )
                    if not any(
                        release_item.object_kind is ObjectKind.PAPER
                        for release_item, _ in base_entries
                    ):
                        raise ReviewNotFound("Base release Paper item not found")
                    for sequence, (release_item, base_revision) in enumerate(
                        base_entries,
                        start=1,
                    ):
                        item = service.add_changeset_item(
                            session,
                            changeset_id=changeset.id,
                            actor_id=principal.user_id,
                            expected_version=changeset.version,
                            object_id=release_item.object_id,
                            object_kind=release_item.object_kind.value,
                            base_revision_id=base_revision.id,
                            proposed_snapshot=base_revision.snapshot,
                            sequence=sequence,
                        )
                        item_after = ChangesetItemResponse.from_model(
                            item,
                            changeset_version=changeset.version,
                        ).model_dump(mode="json")
                        append_review_audit(
                            session,
                            request=request,
                            actor_id=principal.user_id,
                            action="review.changeset_item.created_from_base",
                            target_type="changeset_item",
                            target_id=item.id,
                            paper_id=changeset.paper_id,
                            changeset_id=changeset.id,
                            release_id=changeset.base_release_id,
                            reason=("Copied release-pinned revision into review draft"),
                            before=None,
                            after=item_after,
                        )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            BaseReleaseConflict,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return ChangesetResponse.from_model(changeset)

    @router.get("/changesets", response_model=list[ChangesetResponse])
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_changesets(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[ChangesetResponse]:
        require_reviewer_or_admin(principal)
        with session.begin():
            changesets = service.list_changesets(
                session,
                owner_id=None
                if principal.role is UserRole.ADMIN
                else principal.user_id,
            )
        return [ChangesetResponse.from_model(changeset) for changeset in changesets]

    @router.get("/changesets/{changeset_id}", response_model=ChangesetResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def get_changeset(
        changeset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        try:
            with session.begin():
                changeset = service.get_changeset(session, changeset_id)
                if (
                    principal.role is not UserRole.ADMIN
                    and changeset.owner_id != principal.user_id
                ):
                    raise ReviewNotFound("Changeset not found")
        except (ReviewNotFound, ReviewForbidden) as error:
            raise as_error(error) from error
        return ChangesetResponse.from_model(changeset)

    @router.get(
        "/changesets/{changeset_id}/items",
        response_model=list[ChangesetItemResponse],
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_changeset_items(
        changeset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[ChangesetItemResponse]:
        require_reviewer_or_admin(principal)
        try:
            with session.begin():
                changeset, items = service.list_changeset_items(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                )
        except (ReviewNotFound, ReviewForbidden) as error:
            raise as_error(error) from error
        return [
            ChangesetItemResponse.from_model(
                item,
                changeset_version=changeset.version,
            )
            for item in items
        ]

    @router.get(
        "/changesets/{changeset_id}/diff",
        response_model=list[dict[str, object]],
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def get_changeset_diff(
        changeset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, object]]:
        require_reviewer_or_admin(principal)
        try:
            with session.begin():
                _, items = service.list_changeset_items(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                )
                result = []
                for item in items:
                    base = (
                        session.get(ObjectRevision, item.base_revision_id)
                        if item.base_revision_id is not None
                        else None
                    )
                    proposed = (
                        session.get(ObjectRevision, item.proposed_revision_id)
                        if item.proposed_revision_id is not None
                        else None
                    )
                    result.append(
                        build_revision_diff(
                            object_id=item.object_id,
                            object_kind=item.object_kind,
                            base_revision_id=item.base_revision_id,
                            proposed_revision_id=item.proposed_revision_id,
                            before_snapshot=base.snapshot if base is not None else None,
                            after_snapshot=(
                                proposed.snapshot
                                if proposed is not None
                                else item.proposed_snapshot
                            ),
                            before_dedicated_fields=_dedicated_fields_for_revision(
                                base
                            ),
                            after_dedicated_fields=(
                                _dedicated_fields_for_revision(proposed)
                                if proposed is not None
                                else _draft_dedicated_fields(
                                    base,
                                    item.proposed_snapshot,
                                )
                            ),
                            before_region_fields=_region_fields_for_revision(base),
                            after_region_fields=(
                                _region_fields_for_revision(proposed)
                                if proposed is not None
                                else _region_fields_for_revision(base)
                            ),
                            before_tombstone=(base.is_tombstone if base else False),
                            after_tombstone=(
                                proposed.is_tombstone if proposed else False
                            ),
                        )
                    )
        except (ReviewNotFound, ReviewForbidden) as error:
            raise as_error(error) from error
        return result

    @router.post(
        "/changesets/{changeset_id}/items",
        response_model=ChangesetItemResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_changeset_item(
        changeset_id: UUID,
        payload: ChangesetItemCreateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetItemResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                item = service.add_changeset_item(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    object_id=payload.object_id,
                    object_kind=payload.object_kind.value,
                    base_revision_id=payload.base_revision_id,
                    proposed_snapshot=payload.proposed_snapshot,
                    sequence=payload.sequence,
                )
                changeset = service.get_changeset(session, changeset_id)
                after = ChangesetItemResponse.from_model(
                    item, changeset_version=changeset.version
                ).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset_item.created",
                    target_type="changeset_item",
                    target_id=item.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason="Created changeset item",
                    before=None,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return ChangesetItemResponse.from_model(
            item,
            changeset_version=changeset.version,
        )

    @router.post(
        "/changesets/{changeset_id}/items/from-base",
        response_model=ChangesetItemResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_changeset_item_from_base(
        changeset_id: UUID,
        payload: ChangesetItemFromBaseRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetItemResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.get_changeset(
                    session,
                    changeset_id,
                    for_update=True,
                )
                release_entry = session.execute(
                    select(ReleaseItem, ObjectRevision)
                    .join(
                        ObjectRevision,
                        (ObjectRevision.id == ReleaseItem.revision_id)
                        & (ObjectRevision.object_id == ReleaseItem.object_id),
                    )
                    .where(
                        ReleaseItem.release_id == changeset.base_release_id,
                        ReleaseItem.paper_id == changeset.paper_id,
                        ReleaseItem.object_id == payload.object_id,
                        ReleaseItem.object_kind == payload.object_kind,
                    )
                ).one_or_none()
                if release_entry is None:
                    raise ReviewNotFound("Base release item not found")
                _, base_revision = release_entry
                item = service.add_changeset_item(
                    session,
                    changeset_id=changeset.id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    object_id=payload.object_id,
                    object_kind=payload.object_kind.value,
                    base_revision_id=base_revision.id,
                    proposed_snapshot=base_revision.snapshot,
                    sequence=payload.sequence,
                )
                after = ChangesetItemResponse.from_model(
                    item,
                    changeset_version=changeset.version,
                ).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset_item.created_from_base",
                    target_type="changeset_item",
                    target_id=item.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason="Copied release-pinned revision into review draft",
                    before=None,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
            IntegrityError,
        ) as error:
            raise as_error(error) from error
        return ChangesetItemResponse.from_model(
            item,
            changeset_version=changeset.version,
        )

    @router.patch(
        "/changesets/{changeset_id}/items/{item_id}",
        response_model=ChangesetItemResponse,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def update_changeset_item(
        changeset_id: UUID,
        item_id: UUID,
        payload: ChangesetItemUpdateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetItemResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                service.get_changeset(session, changeset_id, for_update=True)
                existing_item = session.get(ChangesetItem, item_id)
                before = (
                    ChangesetItemResponse.from_model(
                        existing_item, changeset_version=payload.expected_version
                    ).model_dump(mode="json")
                    if existing_item is not None
                    else None
                )
                changeset, item = service.update_changeset_item(
                    session,
                    changeset_id=changeset_id,
                    item_id=item_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    proposed_snapshot=payload.proposed_snapshot,
                )
                after = ChangesetItemResponse.from_model(
                    item, changeset_version=changeset.version
                ).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset_item.updated",
                    target_type="changeset_item",
                    target_id=item.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason="Updated changeset item",
                    before=before,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
        ) as error:
            raise as_error(error) from error
        return ChangesetItemResponse.from_model(
            item,
            changeset_version=changeset.version,
        )

    @router.delete(
        "/changesets/{changeset_id}/items/{item_id}",
        response_model=ChangesetMutationResponse,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def delete_changeset_item(
        changeset_id: UUID,
        item_id: UUID,
        payload: ChangesetItemDeleteRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetMutationResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                service.get_changeset(session, changeset_id, for_update=True)
                existing_item = session.get(ChangesetItem, item_id)
                before = (
                    ChangesetItemResponse.from_model(
                        existing_item, changeset_version=payload.expected_version
                    ).model_dump(mode="json")
                    if existing_item is not None
                    else None
                )
                changeset = service.delete_changeset_item(
                    session,
                    changeset_id=changeset_id,
                    item_id=item_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset_item.deleted",
                    target_type="changeset_item",
                    target_id=item_id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason="Deleted changeset item",
                    before=before,
                    after=None,
                )
        except (ChangesetItemHasRevisions, ChangesetItemHasComments) as error:
            raise as_error(error) from error
        except IntegrityError as error:
            raise APIError(
                409,
                "CHANGESET_ITEM_HAS_REVISIONS",
                "Changeset item has linked revisions and cannot be deleted",
                details={"item_id": str(item_id)},
            ) from error
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
        ) as error:
            raise as_error(error) from error
        return ChangesetMutationResponse(
            changeset_id=changeset.id,
            version=changeset.version,
        )

    @router.patch("/changesets/{changeset_id}", response_model=ChangesetResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def update_changeset(
        changeset_id: UUID,
        payload: ChangesetUpdateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                existing_changeset = service.get_changeset(
                    session, changeset_id, for_update=True
                )
                before = (
                    ChangesetResponse.from_model(existing_changeset).model_dump(
                        mode="json"
                    )
                    if existing_changeset is not None
                    else None
                )
                changeset = service.update_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    title=payload.title,
                    reason=payload.reason,
                    validation_results=payload.validation_results,
                )
                after = ChangesetResponse.from_model(changeset).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset.updated",
                    target_type="changeset",
                    target_id=changeset.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason=changeset.reason,
                    before=before,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
        ) as error:
            raise as_error(error) from error
        return ChangesetResponse.from_model(changeset)

    @router.post("/changesets/{changeset_id}/submit", response_model=ChangesetResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def submit_changeset(
        changeset_id: UUID,
        payload: ChangesetSubmitRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                existing_changeset = service.get_changeset(
                    session, changeset_id, for_update=True
                )
                before = (
                    ChangesetResponse.from_model(existing_changeset).model_dump(
                        mode="json"
                    )
                    if existing_changeset is not None
                    else None
                )
                changeset = service.submit_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                after = ChangesetResponse.from_model(changeset).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset.submitted",
                    target_type="changeset",
                    target_id=changeset.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason=changeset.reason,
                    before=before,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
            BaseReleaseConflict,
        ) as error:
            raise as_error(error) from error
        return ChangesetResponse.from_model(changeset)

    @router.post("/changesets/{changeset_id}/revise", response_model=ChangesetResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def revise_changeset(
        changeset_id: UUID,
        payload: ChangesetTransitionRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                existing_changeset = service.get_changeset(
                    session, changeset_id, for_update=True
                )
                before = (
                    ChangesetResponse.from_model(existing_changeset).model_dump(
                        mode="json"
                    )
                    if existing_changeset is not None
                    else None
                )
                changeset = service.revise_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                after = ChangesetResponse.from_model(changeset).model_dump(mode="json")
                append_review_audit(
                    session,
                    request=request,
                    actor_id=principal.user_id,
                    action="review.changeset.revised",
                    target_type="changeset",
                    target_id=changeset.id,
                    paper_id=changeset.paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    reason=changeset.reason,
                    before=before,
                    after=after,
                )
        except (
            ReviewNotFound,
            ReviewForbidden,
            InvalidReview,
            RevisionConflict,
        ) as error:
            raise as_error(error) from error
        return ChangesetResponse.from_model(changeset)

    transition_routes = {
        "request-changes": WorkflowState.CHANGES_REQUESTED,
        "reject": WorkflowState.REJECTED,
        "approve": WorkflowState.APPROVED,
    }
    for path, target_state in transition_routes.items():

        def make_transition(target_state: WorkflowState, path: str):
            @declare_route_access(RouteAccess.AUTHENTICATED)
            def transition(
                changeset_id: UUID,
                payload: ChangesetDecisionRequest,
                request: Request,
                session: Session = Depends(get_db_session),
                principal: Principal = Depends(get_authenticated_principal),
                csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
            ) -> ChangesetResponse:
                require_reviewer_or_admin(principal)
                if principal.role is not UserRole.ADMIN:
                    raise HTTPException(status_code=403, detail="Permission denied")
                verify_csrf(principal, csrf_token)
                try:
                    with session.begin():
                        existing_changeset = service.get_changeset(
                            session, changeset_id, for_update=True
                        )
                        before = (
                            ChangesetResponse.from_model(existing_changeset).model_dump(
                                mode="json"
                            )
                            if existing_changeset is not None
                            else None
                        )
                        decision_is_idempotent = False
                        if target_state in {
                            WorkflowState.APPROVED,
                            WorkflowState.CHANGES_REQUESTED,
                            WorkflowState.REJECTED,
                        }:
                            action = {
                                WorkflowState.APPROVED: "approve",
                                WorkflowState.CHANGES_REQUESTED: "request_changes",
                                WorkflowState.REJECTED: "reject",
                            }[target_state]
                            decision_result = ApprovalService().decide(
                                session,
                                changeset_id=changeset_id,
                                actor_id=principal.user_id,
                                action=action,
                                reason=payload.reason,
                                expected_version=payload.expected_version,
                            )
                            decision_is_idempotent = decision_result.idempotent
                            changeset = service.get_changeset(
                                session, changeset_id, for_update=True
                            )
                        else:
                            changeset = service.transition_changeset(
                                session,
                                changeset_id=changeset_id,
                                actor_id=principal.user_id,
                                expected_version=payload.expected_version,
                                next_state=target_state,
                            )
                        after = ChangesetResponse.from_model(changeset).model_dump(
                            mode="json"
                        )
                        if not decision_is_idempotent:
                            append_review_audit(
                                session,
                                request=request,
                                actor_id=principal.user_id,
                                action=f"review.changeset.{target_state.value}",
                                target_type="changeset",
                                target_id=changeset.id,
                                paper_id=changeset.paper_id,
                                changeset_id=changeset.id,
                                release_id=changeset.base_release_id,
                                reason=payload.reason,
                                before=before,
                                after=after,
                            )
                except (
                    ReviewNotFound,
                    ReviewForbidden,
                    ApprovalForbidden,
                    ApprovalConflict,
                    InvalidReview,
                    RevisionConflict,
                ) as error:
                    raise as_error(error) from error
                return ChangesetResponse.from_model(changeset)

            transition.__name__ = f"transition_{path.replace('-', '_')}"
            return transition

        transition = make_transition(target_state, path)
        router.add_api_route(
            f"/changesets/{{changeset_id}}/{path}",
            transition,
            methods=["POST"],
            response_model=ChangesetResponse,
            name=transition.__name__,
        )

    return router
