from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError, request_id_for
from app.assets.storage import LocalAssetStore
from app.audit.service import AuditService, canonical_content_hash
from app.auth.router import resolve_remote_address
from app.database import get_db_session
from app.releases.export import export_release
from app.releases.models import Release, ReleaseItem
from app.releases.service import (
    PublishedRelease,
    ReleaseConflict,
    get_current_release,
    preview_approved_changeset,
    publish_approved_changeset,
    rollback_release,
)
from app.releases.validation import validate_release
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_published_data,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.models import UserRole


class PublishRequest(BaseModel):
    changeset_id: UUID
    title: str | None = Field(default=None, max_length=255)
    notes: str = ""


class RollbackRequest(BaseModel):
    target_release_id: UUID
    reason: str = Field(min_length=1, max_length=4000)


def create_releases_router() -> APIRouter:
    router = APIRouter()
    published_router = APIRouter(prefix="/api/v1/published", tags=["published data"])

    @published_router.get("/overview")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def published_overview(
        request: Request,
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> dict[str, object]:
        with session.begin():
            release = get_current_release(session)
            metadata = PublishedRelease.from_model(release)
        return {
            "request_id": request_id_for(request),
            "release": {
                "id": str(metadata.id),
                "key": metadata.key,
                "title": metadata.title,
                "published_at": metadata.published_at.isoformat(),
            },
            "metrics": metadata.metrics,
        }

    admin_router = APIRouter(prefix="/api/v1/releases", tags=["releases"])

    def require_admin(principal: Principal) -> None:
        if principal.role is not UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permission denied")

    def asset_store(request: Request) -> LocalAssetStore:
        settings = request.app.state.settings
        return LocalAssetStore(settings.asset_root, source_roots=settings.source_roots)

    def require_idempotency_key(value: str | None) -> str:
        key = (value or "").strip()
        if not key or len(key) > 200:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key must contain 1 to 200 characters",
            )
        return key

    @admin_router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_releases(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, object]]:
        require_admin(principal)
        with session.begin():
            rows = list(
                session.scalars(
                    select(Release).order_by(Release.created_at.desc(), Release.id)
                )
            )
        return [
            {
                "id": str(row.id),
                "release_key": row.release_key,
                "title": row.title,
                "notes": row.notes,
                "published_at": row.published_at.isoformat(),
                "is_current": row.is_current,
                "manifest_finalized": row.manifest_finalized,
                "metrics": row.metrics,
            }
            for row in rows
        ]

    @admin_router.get("/{release_id}/validation")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def release_validation(
        release_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> dict[str, object]:
        require_admin(principal)
        with session.begin():
            result = validate_release(
                session, release_id, asset_store=asset_store(request)
            )
        return result.as_dict()

    @admin_router.get("/preview/{changeset_id}")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def release_preview(
        changeset_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> dict[str, object]:
        require_admin(principal)
        try:
            with session.begin():
                return preview_approved_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=principal.user_id,
                    asset_store=asset_store(request),
                )
        except ReleaseConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @admin_router.get("/{release_id}/export")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def release_export(
        release_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> dict[str, object]:
        require_admin(principal)
        with session.begin():
            try:
                return export_release(
                    session, release_id, asset_store=asset_store(request)
                )
            except ValueError as error:
                raise APIError(
                    422,
                    "RELEASE_VALIDATION_FAILED",
                    "Release validation failed",
                ) from error

    @admin_router.post("/publish")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def publish(
        payload: PublishRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        require_admin(principal)
        require_request_csrf(
            principal,
            csrf_token,
            request.app.state.settings.session_secret.get_secret_value(),
        )
        operation_key = require_idempotency_key(idempotency_key)
        try:
            with session.begin():
                result = publish_approved_changeset(
                    session,
                    changeset_id=payload.changeset_id,
                    actor_id=principal.user_id,
                    title=payload.title,
                    notes=payload.notes,
                    idempotency_key=operation_key,
                    asset_store=asset_store(request),
                )
                if not result.idempotent:
                    from app.reviews.models import Changeset

                    changeset = session.get(Changeset, payload.changeset_id)
                    if changeset is not None:
                        after = {
                            "release_id": str(result.release.id),
                            "release_key": result.release.release_key,
                        }
                        AuditService().append_event(
                            session,
                            actor_id=principal.user_id,
                            action="release.published",
                            target_type="release",
                            target_id=result.release.id,
                            paper_id=changeset.paper_id,
                            changeset_id=changeset.id,
                            release_id=result.release.id,
                            ip_address=resolve_remote_address(
                                request, request.app.state.settings
                            ),
                            request_id=request_id_for(request),
                            result="success",
                            reason=payload.notes or "Published approved changeset",
                            before_hash=canonical_content_hash(
                                {"release_id": str(changeset.base_release_id)}
                            ),
                            after_hash=canonical_content_hash(after),
                            details={"after": after},
                        )
        except ReleaseConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise APIError(
                422,
                "RELEASE_VALIDATION_FAILED",
                "Release validation failed",
            ) from error
        return {
            "release_id": str(result.release.id),
            "release_key": result.release.release_key,
            "validation": result.validation.as_dict(),
            "idempotent": result.idempotent,
            "operation_id": str(result.operation_id) if result.operation_id else None,
            "request_id": request_id_for(request),
        }

    @admin_router.post("/rollback")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def rollback(
        payload: RollbackRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        require_admin(principal)
        require_request_csrf(
            principal,
            csrf_token,
            request.app.state.settings.session_secret.get_secret_value(),
        )
        operation_key = require_idempotency_key(idempotency_key)
        try:
            with session.begin():
                result = rollback_release(
                    session,
                    target_release_id=payload.target_release_id,
                    actor_id=principal.user_id,
                    reason=payload.reason,
                    idempotency_key=operation_key,
                    asset_store=asset_store(request),
                )
                first_item = session.scalar(
                    select(ReleaseItem)
                    .where(ReleaseItem.release_id == result.release.id)
                    .order_by(ReleaseItem.manifest_order)
                )
                if first_item is not None and not result.idempotent:
                    after = {
                        "release_id": str(result.release.id),
                        "rollback_of": str(payload.target_release_id),
                        "replaced_release_id": str(result.replaced_release_id),
                    }
                    AuditService().append_event(
                        session,
                        actor_id=principal.user_id,
                        action="release.rolled_back",
                        target_type="release",
                        target_id=result.release.id,
                        paper_id=first_item.paper_id,
                        changeset_id=None,
                        release_id=result.release.id,
                        ip_address=resolve_remote_address(
                            request, request.app.state.settings
                        ),
                        request_id=request_id_for(request),
                        result="success",
                        reason=payload.reason,
                        before_hash=canonical_content_hash(
                            {"release_id": str(result.replaced_release_id)}
                        ),
                        after_hash=canonical_content_hash(after),
                        details={"after": after},
                    )
        except ReleaseConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise APIError(
                422,
                "RELEASE_VALIDATION_FAILED",
                "Release validation failed",
            ) from error
        return {
            "release_id": str(result.release.id),
            "release_key": result.release.release_key,
            "validation": result.validation.as_dict(),
            "idempotent": result.idempotent,
            "operation_id": str(result.operation_id) if result.operation_id else None,
            "request_id": request_id_for(request),
        }

    router.include_router(published_router)
    router.include_router(admin_router)

    return router
