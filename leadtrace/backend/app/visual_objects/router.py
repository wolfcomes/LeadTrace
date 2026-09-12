from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.reviews.models import ReviewTask
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.models import UserRole
from app.visual_objects.regions import (
    RegionBounds,
    RegionService,
    RegionValidationError,
    RegionVersionConflict,
    normalize_bounds,
)


class RegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_key: str | None = Field(default=None, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    bounds: dict[str, float] | None = None
    rotation: int = Field(default=0)
    changeset_id: UUID
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "RegionRequest":
        values = self.bounds or {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}
        if all(values.get(key) is None for key in ("x0", "y0", "x1", "y1")):
            return self
        if any(values.get(key) is None for key in ("x0", "y0", "x1", "y1")):
            raise ValueError("bounds or x0/y0/x1/y1 are required")
        return self

    def parsed_bounds(self) -> RegionBounds:
        values = self.bounds or {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}
        if any(values.get(key) is None for key in ("x0", "y0", "x1", "y1")):
            raise RegionValidationError("bounds or x0/y0/x1/y1 are required")
        return normalize_bounds(float(values["x0"]), float(values["y0"]), float(values["x1"]), float(values["y1"]))


class RegionUpdateRequest(RegionRequest):
    region_key: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    rotation: int | None = None


class DuplicateRequest(BaseModel):
    region_key: str = Field(min_length=1, max_length=255)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class SplitRequest(BaseModel):
    first_key: str = Field(min_length=1, max_length=255)
    second_key: str = Field(min_length=1, max_length=255)
    first_bounds: dict[str, float]
    second_bounds: dict[str, float]
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class TombstoneRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)


def _authorize(session: Session, principal: Principal, paper_id: UUID) -> None:
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    if principal.role is UserRole.ADMIN:
        return
    assigned = session.scalar(
        select(ReviewTask.id).where(
            ReviewTask.paper_id == paper_id,
            ReviewTask.assigned_reviewer_id == principal.user_id,
        )
    )
    if assigned is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    # Permission lookup starts SQLAlchemy's implicit transaction. End it before
    # the mutation's explicit transaction so the dependency can commit changes.
    session.rollback()


def require_region_edit_permission(
    principal: Principal = Depends(get_authenticated_principal),
) -> Principal:
    """Dependency marker used by the route-policy matrix and API docs."""
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    return principal


setattr(require_region_edit_permission, "__leadtrace_action__", Action.EDIT_DRAFT)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, RegionVersionConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": "REVISION_CONFLICT",
                "message": str(error),
                "expected_version": error.expected_version,
                "current_version": error.current_version,
            },
        )
    if isinstance(error, RegionValidationError):
        message = str(error)
        if "not found" in message.lower():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=message)
    return HTTPException(status_code=400, detail="The request could not be completed")


def create_visual_regions_router(session_secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers/{paper_id}/regions", tags=["visual regions"])
    service = RegionService()

    @router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_regions(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, Any]]:
        _authorize(session, principal, paper_id)
        return service.list_regions(session, paper_id)

    @router.get("/{region_id}/revisions")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_revisions(
        paper_id: UUID,
        region_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, Any]]:
        _authorize(session, principal, paper_id)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            revisions = service.revisions(session, region_id)
            if not revisions:
                raise RegionValidationError("Region not found")
            return [
                {
                    "id": str(revision.id),
                    "object_id": str(revision.object_id),
                    "revision_number": revision.revision_number,
                    "predecessor_id": str(revision.predecessor_id) if revision.predecessor_id else None,
                    "changeset_id": str(revision.changeset_id) if revision.changeset_id else None,
                    "snapshot": revision.snapshot,
                    "is_tombstone": revision.is_tombstone,
                    "workflow_state": revision.workflow_state.value,
                    "created_at": revision.created_at,
                }
                for revision in revisions
            ]
        except Exception as error:
            raise _error(error) from error

    @router.post("")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_region(
        paper_id: UUID,
        payload: RegionRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                region = service.create_region(
                    session,
                    paper_id=paper_id,
                    actor_id=principal.user_id,
                    region_key=payload.region_key or "",
                    page_number=payload.page_number or 1,
                    bounds=payload.parsed_bounds(),
                    rotation=payload.rotation,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"id": str(region.id), "region_key": region.region_key}
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{region_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_region(
        paper_id: UUID,
        region_id: UUID,
        payload: RegionUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            session.rollback()
            with session.begin():
                revision = service.update_region(
                    session,
                    region_id=region_id,
                    actor_id=principal.user_id,
                    bounds=payload.parsed_bounds() if any(value is not None for value in (payload.x0, payload.y0, payload.x1, payload.y1)) or payload.bounds else None,
                    page_number=payload.page_number,
                    rotation=payload.rotation,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"revision_id": str(revision.id), "revision_number": revision.revision_number}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{region_id}/duplicate")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def duplicate_region(
        paper_id: UUID,
        region_id: UUID,
        payload: DuplicateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            session.rollback()
            with session.begin():
                region = service.duplicate_region(
                    session,
                    region_id=region_id,
                    actor_id=principal.user_id,
                    region_key=payload.region_key,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"id": str(region.id), "region_key": region.region_key}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{region_id}/split")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def split_region(
        paper_id: UUID,
        region_id: UUID,
        payload: SplitRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            session.rollback()
            first_bounds = normalize_bounds(**payload.first_bounds)
            second_bounds = normalize_bounds(**payload.second_bounds)
            with session.begin():
                first, second = service.split_region(
                    session,
                    region_id=region_id,
                    actor_id=principal.user_id,
                    first_key=payload.first_key,
                    second_key=payload.second_key,
                    first_bounds=first_bounds,
                    second_bounds=second_bounds,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"regions": [{"id": str(first.id), "region_key": first.region_key}, {"id": str(second.id), "region_key": second.region_key}]}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{region_id}/tombstone")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def tombstone_region(
        paper_id: UUID,
        region_id: UUID,
        payload: TombstoneRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            session.rollback()
            with session.begin():
                revision = service.tombstone_region(
                    session,
                    region_id=region_id,
                    actor_id=principal.user_id,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"revision_id": str(revision.id), "is_tombstone": True}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{region_id}/restore")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def restore_region(
        paper_id: UUID,
        region_id: UUID,
        payload: TombstoneRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_region_edit_permission),
    ) -> dict[str, Any]:
        _authorize(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            service.ensure_region_belongs_to_paper(session, region_id=region_id, paper_id=paper_id)
            session.rollback()
            with session.begin():
                revision = service.restore_region(
                    session,
                    region_id=region_id,
                    actor_id=principal.user_id,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                return {"revision_id": str(revision.id), "is_tombstone": False}
        except Exception as error:
            raise _error(error) from error

    return router
