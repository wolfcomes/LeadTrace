from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.admin.papers import (
    AdminPaperCatalog,
    AdminPaperNotFound,
    AdminPaperSourceIntegrityError,
    AdminPaperSourceNotFound,
    AdminPaperWorkflowState,
    PublicationStatus,
)
from app.assets.models import Asset
from app.api.errors import request_id_for
from app.audit.service import (
    AuditService,
    canonical_content_hash,
    redact_sensitive_text,
)
from app.auth.router import resolve_remote_address
from app.compounds.models import Compound
from app.config import Settings
from app.database import get_db_session
from app.evidence.models import Evidence
from app.health.service import HealthService
from app.imports.approval import (
    CandidateDecisionConflict,
    CandidateDecisionForbidden,
    CandidateDecisionNotFound,
    ImportCandidateApprovalService,
)
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportCandidateDecision,
    ImportReleaseCandidate,
)
from app.imports.service import BaselineImporter, ImportValidationError
from app.jobs.models import CropJob
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.revisions.models import ObjectRevision
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.structures.models import Structure
from app.users.models import User
from app.users.schemas import EnabledUpdateRequest, UserResponse
from app.users.service import UserService
from app.visual_objects.models import (
    VisualObject,
    VisualObjectAssetBinding,
    VisualRegion,
)


class ImportRequest(BaseModel):
    source_root: str = Field(min_length=1, max_length=120)


class ImportCandidateDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=4000)


_SAFE_CANDIDATE_MANIFEST_FIELDS = (
    "schema_version",
    "source_fingerprint",
    "status",
    "is_current",
    "counts",
    "integrity",
    "asset_linkage",
    "revision_count",
)


def _safe_candidate_manifest(manifest: dict[str, object]) -> dict[str, object]:
    return {
        field: manifest[field]
        for field in _SAFE_CANDIDATE_MANIFEST_FIELDS
        if field in manifest
    }


def _safe_candidate_decision(
    decision: ImportCandidateDecision | None,
) -> dict[str, object] | None:
    if decision is None:
        return None
    return {
        "id": str(decision.id),
        "decision": decision.decision,
        "actor_id": str(decision.actor_id),
        "reason": redact_sensitive_text(decision.reason),
        "manifest_hash": decision.manifest_hash,
        "created_at": decision.created_at.isoformat(),
    }


def _safe_import_candidate(
    candidate: ImportReleaseCandidate,
    decision: ImportCandidateDecision | None,
) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "import_batch_id": str(candidate.import_batch_id),
        "status": candidate.status,
        "is_current": candidate.is_current,
        "manifest": _safe_candidate_manifest(candidate.manifest),
        "decision": _safe_candidate_decision(decision),
        "created_at": candidate.created_at.isoformat(),
    }


def _safe_asset(asset: Asset) -> dict[str, object]:
    source_root_key = asset.source_metadata.get("source_root_key") if isinstance(asset.source_metadata, dict) else None
    if isinstance(source_root_key, str) and (source_root_key.startswith("/") or "://" in source_root_key):
        source_root_key = Path(source_root_key).name
    return {
        "id": str(asset.id),
        "filename": asset.original_filename,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "category": asset.category.value,
        "access_level": asset.access_level.value,
        "access_class": asset.access_level.value,
        "integrity": asset.integrity_state.value,
        "integrity_state": asset.integrity_state.value,
        "import_batch_id": str(asset.import_batch_id) if asset.import_batch_id else None,
        "source_asset_id": str(asset.source_asset_id) if asset.source_asset_id else None,
        # Metadata may contain source paths; expose only the non-sensitive key.
        "has_derivation": bool(asset.derivation_metadata),
        "source_root_key": source_root_key,
    }


def _contains_asset(value: Any, asset_id: UUID) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"asset_id", "source_asset_id", "drawing_asset_id"} and str(nested) == str(asset_id):
                return True
            if _contains_asset(nested, asset_id):
                return True
    elif isinstance(value, list):
        return any(_contains_asset(item, asset_id) for item in value)
    return False


def _safe_source_reference(value: str) -> str:
    candidate = value.replace("\\", "/")
    if candidate.startswith("/") or "://" in candidate or ":\\" in value:
        return Path(candidate).name
    return candidate


def create_admin_router(settings: Settings, *, database_probe: Any | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
    require_admin = require_permission(Action.MANAGE_ACCOUNTS)
    user_service = UserService()
    paper_catalog = AdminPaperCatalog()

    @router.get("/users", response_model=list[UserResponse])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_admin_users(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[UserResponse]:
        with session.begin():
            return [UserResponse.from_user(user) for user in user_service.list_users(session)]

    @router.patch("/users/{user_id}/enabled", response_model=UserResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def update_admin_user_enabled(
        user_id: UUID,
        payload: EnabledUpdateRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        require_request_csrf(principal, csrf_token, settings.session_secret.get_secret_value())
        with session.begin():
            try:
                user = user_service.set_enabled(session, user_id, payload.is_enabled)
            except LookupError as error:
                raise HTTPException(status_code=404, detail="User not found") from error
        return UserResponse.from_user(user)

    @router.post("/users/{user_id}/sessions/revoke", status_code=204, response_model=None)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def revoke_admin_user_sessions(
        user_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        require_request_csrf(principal, csrf_token, settings.session_secret.get_secret_value())
        with session.begin():
            if session.get(User, user_id) is None:
                raise HTTPException(status_code=404, detail="User not found")
            user_service.revoke_sessions(session, user_id)

    @router.get("/papers", response_model=dict[str, object])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_admin_papers(
        request: Request,
        candidate_id: UUID | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        search: str | None = Query(default=None, max_length=255),
        doi: str | None = Query(default=None, max_length=255),
        workflow_state: AdminPaperWorkflowState | None = None,
        publication_status: PublicationStatus | None = None,
        assignee_id: UUID | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            with session.begin():
                payload = paper_catalog.list(
                    session,
                    candidate_id=candidate_id,
                    page=page,
                    page_size=page_size,
                    search=search,
                    doi=doi,
                    workflow_state=workflow_state,
                    publication_status=publication_status,
                    assignee_id=assignee_id,
                )
        except AdminPaperSourceNotFound as error:
            raise HTTPException(status_code=404, detail="Import candidate not found") from error
        except AdminPaperSourceIntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="Import candidate Paper manifest is inconsistent",
            ) from error
        return {"request_id": request_id_for(request), **payload}

    @router.get("/papers/{paper_id}", response_model=dict[str, object])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def get_admin_paper(
        paper_id: UUID,
        request: Request,
        candidate_id: UUID | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            with session.begin():
                payload = paper_catalog.detail(
                    session,
                    paper_id=paper_id,
                    candidate_id=candidate_id,
                )
        except (AdminPaperNotFound, AdminPaperSourceNotFound) as error:
            raise HTTPException(status_code=404, detail="Paper not found") from error
        except AdminPaperSourceIntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="Import candidate Paper manifest is inconsistent",
            ) from error
        return {"request_id": request_id_for(request), **payload}

    @router.get("/files", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_files(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        category: str | None = None,
        integrity: str | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        with session.begin():
            statement = select(Asset).order_by(Asset.created_at.desc()).limit(limit).offset(offset)
            if category:
                statement = statement.where(Asset.category == category)
            if integrity:
                statement = statement.where(Asset.integrity_state == integrity)
            return [_safe_asset(asset) for asset in session.scalars(statement)]

    @router.get("/files/{asset_id}/references")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def file_references(
        asset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        with session.begin():
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="Asset not found")
            references: list[dict[str, object]] = []
            for link in session.scalars(select(ImportAssetLink).where(ImportAssetLink.asset_id == asset_id)):
                references.append({"kind": link.record_type, "id": link.original_id, "role": link.link_role, "source": _safe_source_reference(link.source_reference)})
            for region in session.scalars(select(VisualRegion).where(VisualRegion.asset_id == asset_id)):
                references.append({"kind": "visual_region", "id": str(region.id), "paper_id": str(region.paper_id), "role": "region"})
            for binding in session.scalars(select(VisualObjectAssetBinding).where(VisualObjectAssetBinding.asset_id == asset_id)):
                references.append({"kind": "visual_object", "id": str(binding.visual_object_id), "role": binding.role})
            for job in session.scalars(select(CropJob).where((CropJob.asset_id == asset_id) | (CropJob.source_asset_id == asset_id))):
                references.append({"kind": "crop_job", "id": str(job.id), "role": "output" if job.asset_id == asset_id else "source"})
            for derivative in session.scalars(select(Asset).where(Asset.source_asset_id == asset_id)):
                references.append({"kind": "asset", "id": str(derivative.id), "role": "derivative", "filename": derivative.original_filename})
            for model, kind in ((Structure, "structure"), (Evidence, "evidence"), (Activity, "activity"), (Lineage, "lineage"), (LineageEdge, "lineage_edge"), (Compound, "compound"), (Paper, "paper"), (VisualObject, "visual_object")):
                for obj in session.scalars(select(model)):
                    revisions = session.scalars(select(ObjectRevision).where(ObjectRevision.object_id == obj.id))
                    if any(_contains_asset(revision.snapshot, asset_id) for revision in revisions):
                        references.append({"kind": kind, "id": str(obj.id), "role": "revision_snapshot"})
            return {"asset": _safe_asset(asset), "references": references}

    @router.get("/imports", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_imports(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        with session.begin():
            return [
                {"id": str(batch.id), "status": batch.status, "source_fingerprint": batch.source_fingerprint, "counts": batch.counts, "integrity": batch.integrity, "asset_linkage": batch.asset_linkage, "started_at": batch.started_at.isoformat(), "completed_at": batch.completed_at.isoformat() if batch.completed_at else None}
                for batch in session.scalars(select(ImportBatch).order_by(ImportBatch.started_at.desc()))
            ]

    @router.get("/import-candidates", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_import_candidates(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        del principal
        with session.begin():
            candidates = list(
                session.scalars(
                    select(ImportReleaseCandidate).order_by(
                        ImportReleaseCandidate.created_at.desc(),
                        ImportReleaseCandidate.id,
                    )
                )
            )
            candidate_ids = [candidate.id for candidate in candidates]
            decisions = {
                decision.candidate_id: decision
                for decision in session.scalars(
                    select(ImportCandidateDecision).where(
                        ImportCandidateDecision.candidate_id.in_(candidate_ids)
                    )
                )
            } if candidate_ids else {}
            return [
                _safe_import_candidate(candidate, decisions.get(candidate.id))
                for candidate in candidates
            ]

    @router.post("/import-candidates/{candidate_id}/decision")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def decide_import_candidate(
        candidate_id: UUID,
        payload: ImportCandidateDecisionRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, object]:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        try:
            with session.begin():
                result = ImportCandidateApprovalService().decide(
                    session,
                    candidate_id=candidate_id,
                    actor_id=principal.user_id,
                    action=payload.action,
                    reason=payload.reason,
                )
                candidate = session.get(ImportReleaseCandidate, candidate_id)
                if candidate is None:
                    raise CandidateDecisionNotFound("Import candidate not found")
                if not result.idempotent:
                    after = {
                        "candidate_id": str(candidate.id),
                        "status": candidate.status,
                        "decision_id": str(result.decision.id),
                        "manifest_hash": result.decision.manifest_hash,
                    }
                    AuditService().append_event(
                        session,
                        actor_id=principal.user_id,
                        action=f"import_candidate.{candidate.status}",
                        target_type="import_release_candidate",
                        target_id=candidate.id,
                        paper_id=None,
                        changeset_id=None,
                        release_id=None,
                        ip_address=resolve_remote_address(request, settings),
                        request_id=request_id_for(request),
                        result="success",
                        reason=result.decision.reason,
                        before_hash=canonical_content_hash(
                            {
                                "candidate_id": str(candidate.id),
                                "status": "imported_baseline",
                            }
                        ),
                        after_hash=canonical_content_hash(after),
                        details={"after": after},
                    )
                response = _safe_import_candidate(candidate, result.decision)
                response["idempotent"] = result.idempotent
                response["request_id"] = request_id_for(request)
                return response
        except CandidateDecisionNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CandidateDecisionForbidden as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except CandidateDecisionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def _source_root(key: str) -> Path:
        root = settings.source_roots.get(key)
        if root is None:
            raise HTTPException(status_code=422, detail="Unknown source root")
        return root.resolve()

    @router.post("/imports/dry-run")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def import_dry_run(
        payload: ImportRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del session
        report = BaselineImporter(_source_root(payload.source_root), managed_asset_root=settings.asset_root).reconcile()
        return report.as_dict()

    @router.post("/imports/apply")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def import_apply(
        payload: ImportRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, object]:
        require_request_csrf(principal, csrf_token, settings.session_secret.get_secret_value())
        try:
            with session.begin():
                result = BaselineImporter(_source_root(payload.source_root), managed_asset_root=settings.asset_root).apply(session)
        except ImportValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"batch_id": str(result.batch_id), "release_candidate_id": str(result.release_candidate_id), "created": result.created}

    @router.get("/audit", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_audit(
        action: str | None = None,
        actor_id: UUID | None = None,
        target_type: str | None = None,
        result: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        with session.begin():
            events = AuditService().list_events(session, limit=500, offset=0)
            filtered = [event for event in events if (action is None or event.action == action) and (actor_id is None or event.actor_id == actor_id) and (target_type is None or event.target_type == target_type) and (result is None or event.result == result)]
            return [
                {"id": str(event.id), "sequence_number": event.sequence_number, "actor_id": str(event.actor_id), "action": event.action, "target_type": event.target_type, "target_id": str(event.target_id), "paper_id": str(event.paper_id) if event.paper_id else None, "changeset_id": str(event.changeset_id) if event.changeset_id else None, "release_id": str(event.release_id) if event.release_id else None, "occurred_at": event.occurred_at.isoformat(), "request_id": event.request_id, "result": event.result, "reason": event.reason, "details": event.details}
                for event in filtered[offset : offset + limit]
            ]

    @router.get("/system")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def system(
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        report = HealthService(settings, database_probe=database_probe or _database_probe).collect(session)
        request_id = getattr(request.state, "request_id", None) or "admin-system"
        return {**report.as_dict(), "request_id": request_id}

    return router


def _database_probe(database_url: str) -> bool:
    from app.health.router import probe_database

    return probe_database(database_url)


__all__ = ["create_admin_router"]
