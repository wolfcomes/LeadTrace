from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import APIError, request_id_for
from app.approvals.service import ApprovalConflict, ApprovalForbidden, ApprovalService
from app.audit.service import AuditService, canonical_content_hash
from app.auth.router import resolve_remote_address
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Principal
from app.users.models import UserRole
from app.reviews.service import ReviewNotFound


class ApprovalDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4000)


def _payload(decision: object) -> dict[str, object]:
    return {
        "id": str(decision.id),
        "changeset_id": str(decision.changeset_id),
        "submission_version": decision.submission_version,
        "decision": decision.decision,
        "actor_id": str(decision.actor_id),
        "reason": decision.reason,
        "snapshot": decision.snapshot,
        "snapshot_hash": decision.snapshot_hash,
        "created_at": decision.created_at.isoformat(),
    }


def create_approvals_router(session_secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
    service = ApprovalService()

    def admin(principal: Principal) -> None:
        if principal.role is not UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permission denied")

    @router.get("")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_approvals(
        changeset_id: UUID | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[dict[str, object]]:
        admin(principal)
        with session.begin():
            decisions = service.list_decisions(session, changeset_id=changeset_id)
        return [_payload(item) for item in decisions]

    @router.get("/{changeset_id}/scientific-evidence")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def scientific_evidence(
        changeset_id: UUID,
        changed_only: bool = Query(default=True),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> dict[str, object]:
        admin(principal)
        try:
            with session.begin():
                return service.scientific_evidence(
                    session,
                    changeset_id,
                    changed_only=changed_only,
                )
        except ReviewNotFound as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except ApprovalConflict as error:
            raise APIError(409, "APPROVAL_EVIDENCE_CONFLICT", str(error)) from error

    routes = {
        "approve": "approve",
        "request-changes": "request_changes",
        "reject": "reject",
    }
    for path, action in routes.items():

        def make_route(path: str, action: str):
            @router.post("/{changeset_id}/" + path)
            @declare_route_access(RouteAccess.AUTHENTICATED)
            def decision(
                changeset_id: UUID,
                payload: ApprovalDecisionRequest,
                request: Request,
                session: Session = Depends(get_db_session),
                principal: Principal = Depends(get_authenticated_principal),
                csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
            ) -> dict[str, object]:
                admin(principal)
                require_request_csrf(principal, csrf_token, session_secret)
                try:
                    with session.begin():
                        result = service.decide(
                            session,
                            changeset_id=changeset_id,
                            actor_id=principal.user_id,
                            action=action,  # type: ignore[arg-type]
                            reason=payload.reason,
                            expected_version=payload.expected_version,
                        )
                        if not result.idempotent:
                            from app.reviews.models import Changeset

                            changeset = session.get(Changeset, changeset_id)
                            if changeset is not None:
                                after = _payload(result.decision)
                                AuditService().append_event(
                                    session,
                                    actor_id=principal.user_id,
                                    action=f"review.changeset.{action}",
                                    target_type="approval_decision",
                                    target_id=result.decision.id,
                                    paper_id=changeset.paper_id,
                                    changeset_id=changeset.id,
                                    release_id=changeset.base_release_id,
                                    ip_address=resolve_remote_address(
                                        request, request.app.state.settings
                                    ),
                                    request_id=request_id_for(request),
                                    result="success",
                                    reason=payload.reason,
                                    before_hash=canonical_content_hash(None),
                                    after_hash=canonical_content_hash(after),
                                    details={"after": after},
                                )
                except ApprovalForbidden as error:
                    raise HTTPException(
                        status_code=403, detail="Permission denied"
                    ) from error
                except ApprovalConflict as error:
                    raise APIError(409, "APPROVAL_CONFLICT", str(error)) from error
                except ValueError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
                response = _payload(result.decision)
                response["idempotent"] = result.idempotent
                response["request_id"] = request_id_for(request)
                return response

            decision.__name__ = f"{action}_changeset"
            return decision

        make_route(path, action)
    return router
