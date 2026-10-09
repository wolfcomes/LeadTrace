from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_prefill.artifact_store import ArtifactConflictError, ArtifactStore
from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_inputs import load_candidate
from app.ai_prefill.assistance_schemas import (
    AssistanceContractResponse,
    CandidateCreateRequest,
    CandidateCreateResponse,
    PreviewApplicationRequest,
    PreviewApplicationResponse,
    ValidationCreateRequest,
    ValidationCreateResponse,
)
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.assistance_verification import PreviewApplicationValidationError
from app.ai_prefill.service import AiPrefillNotFoundError, AiPrefillUnavailableError
from app.ai_prefill.preview_application import (
    PreviewApplicationConflictError,
    PreviewApplicationError,
    PreviewApplicationService,
)
from app.ai_prefill.preview_models import ApplicationReceipt
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal


_BODY_LIMIT_RESPONSE = {
    413: {"description": "Request body exceeds 2 MiB; error code PREVIEW_REQUEST_TOO_LARGE"},
}


def _artifact_id(value: str, label: str) -> str:
    if (
        not value
        or len(value) > 128
        or value in {".", ".."}
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in value)
    ):
        raise HTTPException(status_code=422, detail=f"invalid {label}")
    return value


def create_assistance_router(settings: Settings) -> APIRouter:
    if settings.environment != "preview":
        return APIRouter()
    router = APIRouter(prefix="/api/v2/admin/ai-prefill", tags=["AI prefilling assistance"])
    require_catalog_management = require_permission(Action.MANAGE_PAPER_CATALOG)
    artifact_root = settings.preview_artifact_root or Path("/var/lib/leadtrace/preview-artifacts")
    # Construct the store only after request identity checks have passed.
    def artifact_store() -> ArtifactStore:
        return ArtifactStore(artifact_root)

    @router.get("/contracts", response_model=AssistanceContractResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def contracts(
        principal: Principal = Depends(require_catalog_management),
    ) -> AssistanceContractResponse:
        del principal
        return AssistanceContractResponse(
            envelope_schema=CandidateEnvelope.model_json_schema(),
            profile_version="core-v1",
            validator_version="assistance-validation-v1",
            capabilities=["candidate-import", "candidate-validate", "preview-apply"],
        )

    @router.post("/candidates", response_model=CandidateCreateResponse, status_code=201, responses=_BODY_LIMIT_RESPONSE)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def create_candidate(
        request: CandidateCreateRequest,
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> CandidateCreateResponse:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        existing_path = (
            artifact_root
            / "experiments"
            / request.candidate.experiment_id
            / "candidates"
            / request.candidate.candidate_id
            / "candidate.json"
        )
        replayed = existing_path.is_file()
        try:
            stored = artifact_store().put_candidate(request.candidate)
        except ArtifactConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return CandidateCreateResponse(candidate=stored, replayed=replayed)

    @router.get("/candidates/{candidate_id}", response_model=CandidateCreateResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def get_candidate(
        candidate_id: str,
        experiment_id: str,
        principal: Principal = Depends(require_catalog_management),
    ) -> CandidateCreateResponse:
        del principal
        experiment_id = _artifact_id(experiment_id, "experiment_id")
        candidate_id = _artifact_id(candidate_id, "candidate_id")
        path = artifact_root / "experiments" / experiment_id / "candidates" / candidate_id / "candidate.json"
        try:
            candidate = load_candidate(path)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail="Candidate not found") from error
        return CandidateCreateResponse(candidate=candidate)

    @router.post("/candidates/{candidate_id}/validations", response_model=ValidationCreateResponse, responses=_BODY_LIMIT_RESPONSE)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def validate_candidate_endpoint(
        candidate_id: str,
        experiment_id: str,
        request: ValidationCreateRequest,
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> ValidationCreateResponse:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        experiment_id = _artifact_id(experiment_id, "experiment_id")
        candidate_id = _artifact_id(candidate_id, "candidate_id")
        path = artifact_root / "experiments" / experiment_id / "candidates" / candidate_id / "candidate.json"
        try:
            candidate = load_candidate(path)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail="Candidate not found") from error
        report = validate_candidate(candidate, page_texts=request.page_texts)
        artifact_store().put_validation(report)
        return ValidationCreateResponse(report=report)

    @router.post("/candidates/{candidate_id}/preview-applications", response_model=PreviewApplicationResponse, responses=_BODY_LIMIT_RESPONSE)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def apply_candidate(
        candidate_id: str,
        experiment_id: str,
        request: PreviewApplicationRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> PreviewApplicationResponse:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        experiment_id = _artifact_id(experiment_id, "experiment_id")
        candidate_id = _artifact_id(candidate_id, "candidate_id")
        path = artifact_root / "experiments" / experiment_id / "candidates" / candidate_id / "candidate.json"
        try:
            candidate = load_candidate(path)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail="Candidate not found") from error
        if settings.preview_instance_id is None:
            raise HTTPException(status_code=503, detail="Preview instance is not configured")
        try:
            with session.begin():
                result = PreviewApplicationService(settings=settings).apply(
                    session,
                    instance_id=settings.preview_instance_id,
                    idempotency_key=request.idempotency_key,
                    candidate=candidate,
                    validation_report=request.validation_report,
                    actor_id=principal.user_id,
                    reviewer_id=request.reviewer_id,
                    paper_id=request.paper_id,
                    workspace_id=request.workspace_id,
                    run_id=request.run_id,
                    expected_workspace_version=request.expected_workspace_version,
                )
                if result.applied:
                    import hashlib
                    from app.ai_prefill.provenance import ProvenanceInput, append_provenance
                    from app.workspaces.models import PaperWorkspace
                    workspace = session.get(PaperWorkspace, result.receipt.workspace_id)
                    append_provenance(session, workspace=workspace, source_sha256=candidate.source.source_sha256,
                        actor_id=principal.user_id, record=ProvenanceInput(
                            run_key='apply:' + str(result.receipt.application_id), stage='prefill',
                            source_sha256=candidate.source.source_sha256,
                            candidate_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            verification='unknown', guide_version=candidate.recipe.guide_version,
                            completed_at=candidate.producer.generated_at, outcome='completed',
                            applied_workspace_version=workspace.version))

        except AiPrefillNotFoundError as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except (PreviewApplicationConflictError, AiPrefillUnavailableError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (PreviewApplicationError, PreviewApplicationValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PreviewApplicationResponse(
            reviewer_url=f"/review/papers/{result.receipt.paper_id}?workspace={result.receipt.workspace_id}",
            application_id=result.receipt.application_id,
            idempotent=result.idempotent,
            receipt={
                "idempotency_key": result.receipt.idempotency_key,
                "candidate_sha256": result.receipt.candidate_sha256,
                "entity_map": result.receipt.entity_map,
                "initial_snapshot": result.receipt.initial_snapshot,
            },
        )

    @router.get("/applications/{application_id}", response_model=PreviewApplicationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def get_application(
        application_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> PreviewApplicationResponse:
        del principal
        with session.begin():
            receipt = session.scalar(
                select(ApplicationReceipt).where(
                    ApplicationReceipt.application_id == application_id,
                    ApplicationReceipt.instance_id == settings.preview_instance_id,
                )
            )
        if receipt is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return PreviewApplicationResponse(
            reviewer_url=f"/review/papers/{receipt.paper_id}?workspace={receipt.workspace_id}",
            application_id=receipt.application_id,
            idempotent=True,
            receipt={
                "idempotency_key": receipt.idempotency_key,
                "candidate_sha256": receipt.candidate_sha256,
                "entity_map": receipt.entity_map,
                "initial_snapshot": receipt.initial_snapshot,
            },
        )

    return router


__all__ = ["create_assistance_router"]
