from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.database import get_db_session
from app.lineages.models import Lineage, LineageEdge
from app.lineages.service import LineageReviewService, LineageValidationError, LineageVersionConflict, PairReadinessService
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset, ReviewTask
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.users.models import UserRole


class LineageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lineage_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class EdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_key: str = Field(min_length=1, max_length=255)
    parent_compound_id: UUID | None = None
    derived_compound_id: UUID
    relation_type: str = Field(min_length=1, max_length=120)
    relation_status: str = Field(min_length=1, max_length=80)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class EdgeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_compound_id: UUID | None = None
    derived_compound_id: UUID
    relation_type: str = Field(min_length=1, max_length=120)
    relation_status: str = Field(min_length=1, max_length=80)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class DeleteRequest(BaseModel):
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
    if isinstance(error, LineageVersionConflict):
        return APIError(409, "REVISION_CONFLICT", "Lineage draft changed concurrently", details={"expected_version": error.expected_version, "current_version": error.current_version})
    if isinstance(error, LineageValidationError):
        if "not found" in str(error).casefold():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, IntegrityError):
        return APIError(409, "SCIENCE_CONFLICT", "Lineage conflicts with an existing record")
    return HTTPException(status_code=400, detail="The request could not be completed")


def _revision(session: Session, object_id: UUID) -> ObjectRevision | None:
    return session.scalar(select(ObjectRevision).where(ObjectRevision.object_id == object_id).order_by(ObjectRevision.revision_number.desc()).limit(1))


def _lineage_payload(lineage: Lineage, revision: ObjectRevision, changeset_version: int = 0) -> dict[str, object]:
    return {"id": str(lineage.id), "paper_id": str(lineage.paper_id), "lineage_key": lineage.lineage_key, "revision_id": str(revision.id), "revision_number": revision.revision_number, "changeset_version": changeset_version, "snapshot": revision.snapshot, "workflow_state": revision.workflow_state.value, "is_tombstone": revision.is_tombstone}


def _edge_payload(edge: LineageEdge, revision: ObjectRevision, changeset_version: int = 0) -> dict[str, object]:
    return {"id": str(edge.id), "paper_id": str(edge.paper_id), "lineage_id": str(edge.lineage_id), "edge_key": edge.edge_key, "parent_compound_id": str(edge.parent_compound_id) if edge.parent_compound_id else None, "derived_compound_id": str(edge.derived_compound_id), "revision_id": str(revision.id), "revision_number": revision.revision_number, "changeset_version": changeset_version, "snapshot": revision.snapshot, "relation_type": revision.relation_type, "relation_status": revision.relation_status, "workflow_state": revision.workflow_state.value, "is_tombstone": revision.is_tombstone}


def create_lineages_router(session_secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers/{paper_id}", tags=["lineages"])
    service = LineageReviewService()

    @router.get("/lineages")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_lineages(paper_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        lineages = session.scalars(select(Lineage).where(Lineage.paper_id == paper_id).order_by(Lineage.lineage_key))
        result = []
        for lineage in lineages:
            revision = _revision(session, lineage.id)
            if revision is not None:
                result.append(_lineage_payload(lineage, revision))
        return result

    @router.post("/lineages", status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_lineage(paper_id: UUID, payload: LineageRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                lineage, revision = service.create_lineage(session, paper_id=paper_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, lineage_key=payload.lineage_key, reason=payload.reason)
                changeset = session.get(Changeset, payload.changeset_id)
                if changeset is None:
                    raise LineageValidationError("Changeset not found")
                return _lineage_payload(lineage, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.get("/lineages/{lineage_id}/edges")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_edges(paper_id: UUID, lineage_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        lineage = session.get(Lineage, lineage_id)
        if lineage is None or lineage.paper_id != paper_id:
            raise HTTPException(status_code=404, detail="Resource not found")
        edges = session.scalars(select(LineageEdge).where(LineageEdge.paper_id == paper_id, LineageEdge.lineage_id == lineage_id).order_by(LineageEdge.edge_key))
        result = []
        for edge in edges:
            revision = _revision(session, edge.id)
            if revision is not None:
                result.append(_edge_payload(edge, revision))
        return result

    @router.post("/lineages/{lineage_id}/edges", status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_edge(paper_id: UUID, lineage_id: UUID, payload: EdgeRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                edge, revision = service.create_edge(session, paper_id=paper_id, lineage_id=lineage_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, edge_key=payload.edge_key, parent_compound_id=payload.parent_compound_id, derived_compound_id=payload.derived_compound_id, relation_type=payload.relation_type, relation_status=payload.relation_status, evidence_ids=tuple(payload.evidence_ids), reason=payload.reason)
                changeset = session.get(Changeset, payload.changeset_id)
                if changeset is None:
                    raise LineageValidationError("Changeset not found")
                return _edge_payload(edge, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.patch("/lineage-edges/{edge_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_edge(paper_id: UUID, edge_id: UUID, payload: EdgeUpdateRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            edge = session.get(LineageEdge, edge_id)
            if edge is None or edge.paper_id != paper_id:
                raise LineageValidationError("Lineage edge not found")
            session.rollback()
            with session.begin():
                revision = service.update_edge(session, edge_id=edge_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, parent_compound_id=payload.parent_compound_id, derived_compound_id=payload.derived_compound_id, relation_type=payload.relation_type, relation_status=payload.relation_status, evidence_ids=tuple(payload.evidence_ids), reason=payload.reason)
                edge = session.get(LineageEdge, edge_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if edge is None or changeset is None:
                    raise LineageValidationError("Lineage edge not found")
                return _edge_payload(edge, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.delete("/lineage-edges/{edge_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_edge(paper_id: UUID, edge_id: UUID, payload: DeleteRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), _permission: Principal = Depends(_require_editor)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            edge = session.get(LineageEdge, edge_id)
            if edge is None or edge.paper_id != paper_id:
                raise LineageValidationError("Lineage edge not found")
            session.rollback()
            with session.begin():
                revision = service.delete_edge(session, edge_id=edge_id, actor_id=principal.user_id, changeset_id=payload.changeset_id, expected_version=payload.expected_version, reason=payload.reason)
                edge = session.get(LineageEdge, edge_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if edge is None or changeset is None:
                    raise LineageValidationError("Lineage edge not found")
                return _edge_payload(edge, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.get("/lineage-edges/{edge_id}/pair-readiness")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def pair_readiness(paper_id: UUID, edge_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        edge = session.get(LineageEdge, edge_id)
        if edge is None or edge.paper_id != paper_id:
            raise HTTPException(status_code=404, detail="Resource not found")
        readiness = PairReadinessService.from_database(session, edge_id)
        return {"edge_id": str(edge_id), "eligible": readiness.eligible, "blocking_codes": list(readiness.blocking_codes)}

    return router
