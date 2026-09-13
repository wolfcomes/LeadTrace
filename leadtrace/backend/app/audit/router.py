from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.service import AuditService, AuditVerification
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
)
from app.security.policies import Principal
from app.users.models import UserRole


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence_number: int
    actor_id: UUID
    action: str
    target_type: str
    target_id: UUID
    paper_id: UUID | None
    changeset_id: UUID | None
    release_id: UUID | None
    occurred_at: datetime
    ip_address: str
    request_id: str
    result: str
    reason: str
    before_hash: str
    after_hash: str
    details: dict[str, object]
    previous_event_hash: str
    event_hash: str


class AuditVerificationResponse(BaseModel):
    valid: bool
    event_count: int
    first_invalid_sequence: int | None

    @classmethod
    def from_result(
        cls, result: AuditVerification
    ) -> "AuditVerificationResponse":
        return cls(
            valid=result.valid,
            event_count=result.event_count,
            first_invalid_sequence=result.first_invalid_sequence,
        )


def create_audit_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
    service = AuditService()

    def require_audit_reader(principal: Principal) -> None:
        if principal.role is UserRole.VISITOR:
            raise HTTPException(status_code=403, detail="Permission denied")

    @router.get("/events", response_model=list[AuditEventResponse])
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_events(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[AuditEvent]:
        require_audit_reader(principal)
        with session.begin():
            return service.list_events(
                session,
                actor_id=(
                    None
                    if principal.role is UserRole.ADMIN
                    else principal.user_id
                ),
                limit=limit,
                offset=offset,
            )

    @router.get("/verify", response_model=AuditVerificationResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def verify_chain(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> AuditVerificationResponse:
        require_audit_reader(principal)
        if principal.role is not UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permission denied")
        with session.begin():
            result = service.verify_chain(session)
        return AuditVerificationResponse.from_result(result)

    return router
