from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.compounds.models import Compound
from app.compounds.service import CompoundDraft, CompoundReviewService, CompoundValidationError, CompoundVersionConflict
from app.database import get_db_session
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset, ReviewTask
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.users.models import UserRole


class CompoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_identity: str = Field(min_length=1, max_length=255)
    display_label: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


def _authorize_paper(session: Session, principal: Principal, paper_id: UUID) -> None:
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    if principal.role is not UserRole.ADMIN:
        assigned = session.scalar(select(ReviewTask.id).where(ReviewTask.paper_id == paper_id, ReviewTask.assigned_reviewer_id == principal.user_id))
        if assigned is None:
            raise HTTPException(status_code=404, detail="Resource not found")
    session.rollback()


def _require_editor(principal: Principal = Depends(get_authenticated_principal)) -> Principal:
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    return principal


setattr(_require_editor, "__leadtrace_action__", Action.EDIT_DRAFT)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, CompoundVersionConflict):
        return APIError(409, "REVISION_CONFLICT", "Compound draft changed concurrently", details={"expected_version": error.expected_version, "current_version": error.current_version})
    if isinstance(error, CompoundValidationError):
        if "not found" in str(error).casefold():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, IntegrityError):
        return APIError(409, "SCIENCE_CONFLICT", "Compound conflicts with an existing record")
    return HTTPException(status_code=400, detail="The request could not be completed")


def _payload(compound: Compound, revision: ObjectRevision, changeset_version: int = 0) -> dict[str, object]:
    return {
        "id": str(compound.id),
        "paper_id": str(compound.paper_id),
        "local_identity": compound.local_identity,
        "display_label": compound.display_label,
        "revision_id": str(revision.id),
        "revision_number": revision.revision_number,
        "changeset_version": changeset_version,
        "snapshot": revision.snapshot,
        "workflow_state": revision.workflow_state.value,
        "is_tombstone": revision.is_tombstone,
    }


def create_compounds_router(session_secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers/{paper_id}/compounds", tags=["compounds"])
    service = CompoundReviewService()

    @router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_compounds(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        compounds = session.scalars(select(Compound).where(Compound.paper_id == paper_id).order_by(Compound.local_identity))
        result = []
        for compound in compounds:
            revision = session.scalar(select(ObjectRevision).where(ObjectRevision.object_id == compound.id).order_by(ObjectRevision.revision_number.desc()).limit(1))
            if revision is not None:
                result.append(_payload(compound, revision))
        return result

    @router.post("", status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_compound(
        paper_id: UUID,
        payload: CompoundRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(_require_editor),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                compound, revision = service.create_compound(session, paper_id=paper_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, draft=CompoundDraft(payload.local_identity, payload.display_label, payload.reason))
                changeset = session.get(Changeset, payload.changeset_id)
                if changeset is None:
                    raise CompoundValidationError("Changeset not found")
                return _payload(compound, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{compound_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_compound(
        paper_id: UUID,
        compound_id: UUID,
        payload: CompoundRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(_require_editor),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            compound = session.get(Compound, compound_id)
            if compound is None or compound.paper_id != paper_id:
                raise CompoundValidationError("Compound not found")
            session.rollback()
            with session.begin():
                revision = service.update_compound(session, compound_id=compound_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, draft=CompoundDraft(payload.local_identity, payload.display_label, payload.reason))
                compound = session.get(Compound, compound_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if compound is None or changeset is None:
                    raise CompoundValidationError("Compound not found")
                return _payload(compound, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    return router
