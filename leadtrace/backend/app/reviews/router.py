from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.database import get_db_session
from app.reviews.schemas import (
    ChangesetCreateRequest,
    ChangesetItemCreateRequest,
    ChangesetItemDeleteRequest,
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
from app.reviews.service import (
    BaseReleaseConflict,
    ChangesetItemHasRevisions,
    InvalidReview,
    RevisionConflict,
    ReviewForbidden,
    ReviewNotFound,
    ReviewService,
    ReviewStateConflict,
)
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Principal, WorkflowState
from app.users.models import UserRole


def create_reviews_router(session_secret: str) -> APIRouter:
    """Build the review router with the application CSRF secret."""

    router = APIRouter(prefix="/api/v1/review", tags=["review workflow"])
    service = ReviewService()

    def require_reviewer_or_admin(principal: Principal) -> None:
        if principal.must_change_password:
            raise HTTPException(status_code=403, detail="Password change required")
        if principal.role is UserRole.VISITOR:
            raise HTTPException(status_code=403, detail="Permission denied")

    def verify_csrf(principal: Principal, token: str | None) -> None:
        require_request_csrf(principal, token, session_secret)

    def as_error(error: Exception) -> HTTPException:
        if isinstance(error, ReviewNotFound):
            return HTTPException(status_code=404, detail="Resource not found")
        if isinstance(error, ReviewForbidden):
            return HTTPException(status_code=403, detail="Permission denied")
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
                task = service.reassign_task(
                    session,
                    task_id=task_id,
                    actor_id=principal.user_id,
                    assignee_id=payload.assigned_reviewer_id,
                    expected_version=payload.expected_version,
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

    @router.post(
        "/changesets/{changeset_id}/items",
        response_model=ChangesetItemResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def create_changeset_item(
        changeset_id: UUID,
        payload: ChangesetItemCreateRequest,
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
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetItemResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset, item = service.update_changeset_item(
                    session,
                    changeset_id=changeset_id,
                    item_id=item_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    proposed_snapshot=payload.proposed_snapshot,
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
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetMutationResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.delete_changeset_item(
                    session,
                    changeset_id=changeset_id,
                    item_id=item_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
        except ChangesetItemHasRevisions as error:
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
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.update_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    title=payload.title,
                    reason=payload.reason,
                    validation_results=payload.validation_results,
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
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.submit_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
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
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ChangesetResponse:
        require_reviewer_or_admin(principal)
        verify_csrf(principal, csrf_token)
        try:
            with session.begin():
                changeset = service.revise_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
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
        "publish": WorkflowState.PUBLISHED,
        "supersede": WorkflowState.SUPERSEDED,
    }
    for path, target_state in transition_routes.items():

        def make_transition(target_state: WorkflowState, path: str):
            @declare_route_access(RouteAccess.AUTHENTICATED)
            def transition(
                changeset_id: UUID,
                payload: ChangesetTransitionRequest,
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
                        changeset = service.transition_changeset(
                            session,
                            changeset_id=changeset_id,
                            actor_id=principal.user_id,
                            expected_version=payload.expected_version,
                            next_state=target_state,
                        )
                except (
                    ReviewNotFound,
                    ReviewForbidden,
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
