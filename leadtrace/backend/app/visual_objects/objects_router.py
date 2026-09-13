from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset, ReviewTask
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.models import UserRole
from app.visual_objects.bindings import BindingConflict, BindingService
from app.visual_objects.models import VisualObject
from app.visual_objects.objects import (
    MoleculeObjectService,
    ObjectVersionConflict,
    ObjectValidationError,
    normalize_object_type,
)
from app.visual_objects.relationships import RelationshipService


class ObjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: str = Field(min_length=1, max_length=255)
    object_type: str
    label: str | None = Field(default=None, max_length=255)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class ObjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    label: str | None = Field(default=None, max_length=255)
    changeset_id: UUID
    expected_version: int = Field(ge=1)


class RegionBindingRequest(BaseModel):
    region_id: UUID
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    role: str = Field(default="source", max_length=64)
    note: str | None = None


class AssetBindingRequest(BaseModel):
    asset_id: UUID
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    role: str = Field(default="image", max_length=64)
    is_primary: bool = False


class CompoundBindingRequest(BaseModel):
    compound_id: UUID
    label: str = Field(min_length=1, max_length=255)
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    label_bbox: dict[str, object] | None = None
    role: str = Field(default="label", max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = None
    is_primary: bool = False


class RelationRequest(BaseModel):
    target_object_id: UUID
    relation_type: str
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    note: str | None = None


class RegionBindingUpdateRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    role: str = Field(default="source", max_length=64)
    note: str | None = None


class AssetBindingUpdateRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    role: str = Field(default="image", max_length=64)
    is_primary: bool = False


class CompoundBindingUpdateRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=255)
    label_bbox: dict[str, object] | None = None
    role: str = Field(default="label", max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = None
    is_primary: bool = False


class RelationUpdateRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    note: str | None = None


class BindingDeleteRequest(BaseModel):
    changeset_id: UUID
    expected_version: int = Field(ge=1)


def _authorize_paper(session: Session, principal: Principal, paper_id: UUID) -> None:
    if principal.role is UserRole.VISITOR:
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
    session.rollback()


def _require_object_paper(session: Session, object_id: UUID, paper_id: UUID) -> VisualObject:
    object_identity = session.scalar(select(VisualObject).where(VisualObject.id == object_id))
    if object_identity is None or object_identity.paper_id != paper_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return object_identity


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ObjectVersionConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": "REVISION_CONFLICT",
                "message": str(error),
                "expected_version": error.expected_version,
                "current_version": error.current_version,
            },
        )
    if isinstance(error, (ObjectValidationError, BindingConflict)):
        message = str(error)
        if "not found" in message.casefold():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=message)
    return HTTPException(status_code=400, detail="The request could not be completed")


def _object_payload(object_identity: VisualObject) -> dict[str, object]:
    return {
        "id": str(object_identity.id),
        "paper_id": str(object_identity.paper_id),
        "object_key": object_identity.object_key,
        "object_type": str(object_identity.object_type),
    }


def _revision_payload(revision: ObjectRevision, *, changeset_version: int) -> dict[str, object]:
    return {
        "revision_id": str(revision.id),
        "revision_number": revision.revision_number,
        "changeset_id": str(revision.changeset_id) if revision.changeset_id else None,
        "changeset_version": changeset_version,
        "snapshot": revision.snapshot,
        "workflow_state": revision.workflow_state.value,
    }


def create_visual_objects_router(session_secret: str) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/papers/{paper_id}/visual-objects",
        tags=["visual objects"],
    )
    object_service = MoleculeObjectService()
    binding_service = BindingService()
    relationship_service = RelationshipService()

    def require_edit(principal: Principal = Depends(get_authenticated_principal)) -> Principal:
        if principal.role is UserRole.VISITOR:
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal

    setattr(require_edit, "__leadtrace_action__", Action.EDIT_DRAFT)

    @router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_objects(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        objects = session.scalars(
            select(VisualObject)
            .where(VisualObject.paper_id == paper_id)
            .order_by(VisualObject.object_key)
        )
        return [_object_payload(item) for item in objects]

    @router.post("")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_object(
        paper_id: UUID,
        payload: ObjectRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                return _object_payload(
                    object_service.create_object(
                        session,
                        paper_id=paper_id,
                        actor_id=principal.user_id,
                        object_key=payload.object_key,
                        object_type=normalize_object_type(payload.object_type),
                        label=payload.label,
                        changeset_id=payload.changeset_id,
                        expected_version=payload.expected_version,
                    )
                )
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{object_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_object(
        paper_id: UUID,
        object_id: UUID,
        payload: ObjectUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                revision = object_service.update_object(
                    session,
                    object_id=object_id,
                    actor_id=principal.user_id,
                    object_type=normalize_object_type(payload.object_type),
                    label=payload.label,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                )
                object_identity = session.get(VisualObject, object_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if object_identity is None or changeset is None:
                    raise ObjectValidationError("Molecule object not found")
                return {
                    **_object_payload(object_identity),
                    **_revision_payload(revision, changeset_version=changeset.version),
                }
        except Exception as error:
            raise _error(error) from error

    @router.post("/{object_id}/regions")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def bind_region(
        paper_id: UUID,
        object_id: UUID,
        payload: RegionBindingRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.bind_region(
                    session,
                    object_id=object_id,
                    region_id=payload.region_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    role=payload.role,
                    note=payload.note,
                )
                return {"id": str(binding.id), "region_id": str(binding.region_id)}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{object_id}/assets")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def bind_asset(
        paper_id: UUID,
        object_id: UUID,
        payload: AssetBindingRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.bind_asset(
                    session,
                    object_id=object_id,
                    asset_id=payload.asset_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    role=payload.role,
                    is_primary=payload.is_primary,
                )
                return {"id": str(binding.id), "asset_id": str(binding.asset_id)}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{object_id}/compounds")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def bind_compound(
        paper_id: UUID,
        object_id: UUID,
        payload: CompoundBindingRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.bind_compound(
                    session,
                    object_id=object_id,
                    compound_id=payload.compound_id,
                    label=payload.label,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    label_bbox=payload.label_bbox,
                    role=payload.role,
                    confidence=payload.confidence,
                    note=payload.note,
                    is_primary=payload.is_primary,
                )
                return {"id": str(binding.id), "compound_id": str(binding.compound_id), "label": binding.label}
        except Exception as error:
            raise _error(error) from error

    @router.post("/{object_id}/relations")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_relation(
        paper_id: UUID,
        object_id: UUID,
        payload: RelationRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                relation = relationship_service.create_relation(
                    session,
                    source_object_id=object_id,
                    target_object_id=payload.target_object_id,
                    relation_type=payload.relation_type,
                    note=payload.note,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                return {"id": str(relation.id), "relation_type": relation.relation_type}
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{object_id}/regions/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_region_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: RegionBindingUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.update_region(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    role=payload.role,
                    note=payload.note,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.delete("/{object_id}/regions/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def remove_region_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: BindingDeleteRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.remove_region(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{object_id}/assets/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_asset_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: AssetBindingUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.update_asset(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    role=payload.role,
                    is_primary=payload.is_primary,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.delete("/{object_id}/assets/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def remove_asset_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: BindingDeleteRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.remove_asset(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{object_id}/compounds/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_compound_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: CompoundBindingUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.update_compound(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    label=payload.label,
                    label_bbox=payload.label_bbox,
                    role=payload.role,
                    confidence=payload.confidence,
                    note=payload.note,
                    is_primary=payload.is_primary,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.delete("/{object_id}/compounds/{binding_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def remove_compound_binding(
        paper_id: UUID,
        object_id: UUID,
        binding_id: UUID,
        payload: BindingDeleteRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                binding = binding_service.remove_compound(
                    session,
                    binding_id=binding_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                if binding.visual_object_id != object_id:
                    raise BindingConflict("Binding does not belong to this object")
                return {"id": str(binding.id), "operation": binding.operation}
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{object_id}/relations/{relation_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_visual_relation(
        paper_id: UUID,
        object_id: UUID,
        relation_id: UUID,
        payload: RelationUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                relation = relationship_service.update_relation(
                    session,
                    relation_id=relation_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                    note=payload.note,
                )
                if relation.source_object_id != object_id:
                    raise BindingConflict("Relation does not belong to this object")
                return {"id": str(relation.id), "operation": relation.operation}
        except Exception as error:
            raise _error(error) from error

    @router.delete("/{object_id}/relations/{relation_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def remove_visual_relation(
        paper_id: UUID,
        object_id: UUID,
        relation_id: UUID,
        payload: BindingDeleteRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_edit),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            _require_object_paper(session, object_id, paper_id)
            session.rollback()
            with session.begin():
                relation = relationship_service.remove_relation(
                    session,
                    relation_id=relation_id,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    expected_version=payload.expected_version,
                )
                if relation.source_object_id != object_id:
                    raise BindingConflict("Relation does not belong to this object")
                return {"id": str(relation.id), "operation": relation.operation}
        except Exception as error:
            raise _error(error) from error

    return router
