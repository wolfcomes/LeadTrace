from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.audit.service import AuditService, canonical_content_hash, persisted_json_value, redact_secrets
from app.database import get_db_session
from app.molecule_proposals.models import MoleculeProposal, MoleculeProposalDisposition
from app.molecule_proposals.schemas import MoleculeProposalResponse, MoleculeProposalUpdateRequest
from app.molecule_proposals.service import (
    MoleculeProposalReviewService,
    MoleculeProposalValidationError,
    MoleculeProposalVersionConflict,
)
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset, ReviewTask
from app.reviews.service import ReviewForbidden, ReviewNotFound, RevisionConflict
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Principal
from app.users.models import UserRole


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


def _safe_machine(snapshot: dict[str, object]) -> dict[str, object]:
    raw = dict(snapshot.get("raw_values", {})) if isinstance(snapshot.get("raw_values"), dict) else {}
    normalized = dict(snapshot.get("normalized_values", {})) if isinstance(snapshot.get("normalized_values"), dict) else {}
    for values in (raw, normalized):
        for key in list(values):
            normalized_key = str(key).casefold()
            if (
                normalized_key in {"crop_path", "source_pdf", "source_crop_path", "storage_key"}
                or normalized_key.endswith("_path")
                or normalized_key.endswith("_filepath")
            ):
                values.pop(key, None)
    return {"raw_values": raw, "normalized_values": normalized}


def _asset_payload(asset: Asset | None) -> dict[str, object] | None:
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "url": f"/api/v1/assets/{asset.id}/content",
        "original_filename": asset.original_filename,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "page_count": asset.page_count,
        "access_level": asset.access_level.value,
        "category": asset.category.value,
    }


def _response(
    session: Session,
    proposal: MoleculeProposal,
    revision: ObjectRevision,
    *,
    changeset_version: int | None,
) -> MoleculeProposalResponse:
    snapshot = revision.snapshot
    review = snapshot.get("review")
    if not isinstance(review, dict):
        review = {
            "disposition": revision.proposal_disposition or MoleculeProposalDisposition.PENDING.value
        }
    region = None
    if proposal.source_region_id is not None:
        region_revision = session.scalar(
            select(ObjectRevision)
            .where(ObjectRevision.object_id == proposal.source_region_id)
            .order_by(ObjectRevision.revision_number.desc())
            .limit(1)
        )
        if region_revision is not None:
            region = {
                "id": str(proposal.source_region_id),
                "revision_id": str(region_revision.id),
                "snapshot": region_revision.snapshot,
            }
    return MoleculeProposalResponse(
        id=proposal.id,
        paper_id=proposal.paper_id,
        visual_object_id=proposal.visual_object_id,
        proposal_key=proposal.proposal_key,
        model_run_key=proposal.model_run_key,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        changeset_id=revision.changeset_id,
        changeset_version=changeset_version,
        disposition=MoleculeProposalDisposition(revision.proposal_disposition or MoleculeProposalDisposition.PENDING.value),
        machine=_safe_machine(snapshot),
        review=dict(review),
        crop_asset=_asset_payload(session.get(Asset, proposal.crop_asset_id)) if proposal.crop_asset_id else None,
        source_region=region,
    )


def _error(error: Exception) -> HTTPException:
    if isinstance(error, (MoleculeProposalVersionConflict, RevisionConflict)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "REVISION_CONFLICT",
                "message": "Review resource changed concurrently",
                "expected_version": error.expected_version,
                "current_version": error.current_version,
            },
        )
    if isinstance(error, (ReviewNotFound,)):
        return HTTPException(status_code=404, detail="Resource not found")
    if isinstance(error, ReviewForbidden):
        return HTTPException(status_code=403, detail="Permission denied")
    if isinstance(error, MoleculeProposalValidationError):
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=400, detail="The request could not be completed")


def create_molecule_proposals_router(session_secret: str) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/papers/{paper_id}/molecule-proposals",
        tags=["molecule proposals"],
    )
    service = MoleculeProposalReviewService()
    audit_service = AuditService()

    @router.get("", response_model=list[MoleculeProposalResponse])
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def list_proposals(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> list[MoleculeProposalResponse]:
        _authorize_paper(session, principal, paper_id)
        proposals = session.scalars(
            select(MoleculeProposal)
            .where(MoleculeProposal.paper_id == paper_id)
            .order_by(MoleculeProposal.proposal_key, MoleculeProposal.model_run_key)
        )
        result: list[MoleculeProposalResponse] = []
        for proposal in proposals:
            revision = service._latest_revision(session, proposal.id)
            changeset_version = None
            if revision.changeset_id is not None:
                changeset = session.get(Changeset, revision.changeset_id)
                changeset_version = changeset.version if changeset is not None else None
            result.append(_response(session, proposal, revision, changeset_version=changeset_version))
        return result

    @router.patch("/{proposal_id}", response_model=MoleculeProposalResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def update_proposal(
        paper_id: UUID,
        proposal_id: UUID,
        payload: MoleculeProposalUpdateRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> MoleculeProposalResponse:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                predecessor = service._latest_revision(session, proposal_id)
                proposal, revision, changeset = service.update(
                    session,
                    paper_id=paper_id,
                    proposal_id=proposal_id,
                    actor_id=principal.user_id,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                    disposition=payload.disposition,
                    reviewed_smiles=payload.reviewed_smiles,
                    selected_component_smiles=payload.selected_component_smiles,
                    compound_id=payload.compound_id,
                    resulting_structure_id=payload.resulting_structure_id,
                    rationale=payload.rationale,
                    source_comparison=payload.source_comparison,
                    source_verified=payload.source_verified,
                )
                before = {
                    "proposal_id": str(proposal.id),
                    "revision_id": str(predecessor.id),
                    "snapshot": predecessor.snapshot,
                    "disposition": predecessor.proposal_disposition,
                }
                after = _response(
                    session,
                    proposal,
                    revision,
                    changeset_version=changeset.version,
                ).model_dump(mode="json")
                request_id = getattr(request.state, "request_id", "molecule-proposal")
                ip_address = request.client.host if request.client else "unknown"
                persisted_before = persisted_json_value(session, redact_secrets(before))
                persisted_after = persisted_json_value(session, redact_secrets(after))
                audit_service.append_event(
                    session,
                    actor_id=principal.user_id,
                    action="review.molecule_proposal.updated",
                    target_type="molecule_proposal",
                    target_id=proposal.id,
                    paper_id=paper_id,
                    changeset_id=changeset.id,
                    release_id=changeset.base_release_id,
                    ip_address=ip_address,
                    request_id=request_id,
                    result="success",
                    reason=str(after.get("review", {}).get("rationale") or "Updated molecule proposal"),
                    before_hash=canonical_content_hash(persisted_before),
                    after_hash=canonical_content_hash(persisted_after),
                    details={"before": persisted_before, "after": persisted_after},
                )
                return _response(session, proposal, revision, changeset_version=changeset.version)
        except Exception as error:
            raise _error(error) from error

    return router
