from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.database import get_db_session
from app.evidence.models import Evidence
from app.evidence.service import EvidenceDraft, EvidenceReviewService, EvidenceValidationError, EvidenceVersionConflict
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset, ReviewTask
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.users.models import UserRole


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1, max_length=255)
    original_text: str = Field(min_length=1, max_length=20000)
    source_locator: str = Field(min_length=1, max_length=2000)
    compound_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class EvidenceDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    if isinstance(error, EvidenceVersionConflict):
        return APIError(409, "REVISION_CONFLICT", "Evidence draft changed concurrently", details={"expected_version": error.expected_version, "current_version": error.current_version})
    if isinstance(error, EvidenceValidationError):
        if "not found" in str(error).casefold():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, IntegrityError):
        return APIError(409, "SCIENCE_CONFLICT", "Evidence conflicts with an existing record")
    return HTTPException(status_code=400, detail="The request could not be completed")


def _payload(evidence: Evidence, revision: ObjectRevision, changeset_version: int = 0) -> dict[str, object]:
    return {
        "id": str(evidence.id),
        "paper_id": str(evidence.paper_id),
        "evidence_key": evidence.evidence_key,
        "revision_id": str(revision.id),
        "revision_number": revision.revision_number,
        "changeset_version": changeset_version,
        "snapshot": revision.snapshot,
        "evidence_state": revision.evidence_state.value if revision.evidence_state else None,
        "workflow_state": revision.workflow_state.value,
        "is_tombstone": revision.is_tombstone,
    }


def _draft(payload: EvidenceRequest) -> EvidenceDraft:
    return EvidenceDraft(payload.evidence_key, payload.original_text, payload.source_locator, tuple(payload.compound_ids))


def create_evidence_router(session_secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers/{paper_id}/evidence", tags=["evidence"])
    service = EvidenceReviewService()

    @router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_evidence(paper_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        records = session.scalars(select(Evidence).where(Evidence.paper_id == paper_id).order_by(Evidence.evidence_key))
        result = []
        for evidence in records:
            revision = session.scalar(select(ObjectRevision).where(ObjectRevision.object_id == evidence.id).order_by(ObjectRevision.revision_number.desc()).limit(1))
            if revision is not None:
                result.append(_payload(evidence, revision))
        return result

    @router.post("", status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_evidence(paper_id: UUID, payload: EvidenceRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                evidence, revision = service.create_evidence(session, paper_id=paper_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, draft=_draft(payload), reason=payload.reason)
                changeset = session.get(Changeset, payload.changeset_id)
                if changeset is None:
                    raise EvidenceValidationError("Changeset not found")
                return _payload(evidence, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{evidence_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_evidence(paper_id: UUID, evidence_id: UUID, payload: EvidenceRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            evidence = session.get(Evidence, evidence_id)
            if evidence is None or evidence.paper_id != paper_id:
                raise EvidenceValidationError("Evidence not found")
            session.rollback()
            with session.begin():
                revision = service.update_evidence(session, evidence_id=evidence_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, draft=_draft(payload), reason=payload.reason)
                evidence = session.get(Evidence, evidence_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if evidence is None or changeset is None:
                    raise EvidenceValidationError("Evidence not found")
                return _payload(evidence, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.delete("/{evidence_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_evidence(paper_id: UUID, evidence_id: UUID, payload: EvidenceDeleteRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            evidence = session.get(Evidence, evidence_id)
            if evidence is None or evidence.paper_id != paper_id:
                raise EvidenceValidationError("Evidence not found")
            session.rollback()
            with session.begin():
                revision = service.delete_evidence(session, evidence_id=evidence_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, reason=payload.reason)
                evidence = session.get(Evidence, evidence_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if evidence is None or changeset is None:
                    raise EvidenceValidationError("Evidence not found")
                return _payload(evidence, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    return router
