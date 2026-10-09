"""Transactional Preview application for portable AI-prefill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from copy import copy
from uuid import UUID, uuid4

import pymupdf

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    ValidationReport,
    canonical_json_bytes,
)
from app.ai_prefill.assistance_verification import (
    PreviewApplicationValidationError,
    verify_candidate_for_application,
)
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.preview_identity import PreviewIdentityError, verify_preview_connection
from app.config import Settings
from app.ai_prefill.preview_models import ApplicationReceipt, PreviewMarker
from app.ai_prefill.service import AiPrefillNotFoundError, AiPrefillService
from app.assets.models import Asset, AssetIntegrityState
from app.assets.storage import AssetMimeMismatchError, AssetPathError, LocalAssetStore
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper
from app.structure_images.service import StructureSourceImageService
from app.users.models import User, UserRole
from app.structures.service import StructureDrawingService
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    ChangeActorKind,
    ChangeEvent,
    WorkspaceState,
)


class PreviewApplicationError(RuntimeError):
    """Raised when a Preview application cannot be committed."""


class PreviewApplicationConflictError(PreviewApplicationError):
    """Raised when an idempotency key is reused for different input."""


@dataclass(frozen=True, slots=True)
class PreviewApplicationResult:
    receipt: ApplicationReceipt
    applied: bool
    idempotent: bool


def _identity(value: UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def application_request_digest(
    *,
    instance_id: UUID | str,
    idempotency_key: str,
    candidate: CandidateEnvelope,
    report: ValidationReport,
    actor_id: UUID | str,
    paper_id: UUID | str | None,
    workspace_id: UUID | str | None,
    run_id: UUID | str | None,
    reviewer_id: UUID | str | None = None,
    expected_workspace_version: int | None = None,
) -> str:
    """Return the stable digest used to arbitrate idempotent applications."""

    import hashlib

    request = {
        "instance_id": _identity(instance_id),
        "idempotency_key": idempotency_key,
        "actor_id": _identity(actor_id),
        "reviewer_id": _identity(reviewer_id),
        "paper_id": _identity(paper_id),
        "workspace_id": _identity(workspace_id),
        "run_id": _identity(run_id),
        "expected_workspace_version": expected_workspace_version,
        "candidate": candidate.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json_bytes(request)).hexdigest()


class PreviewApplicationService:
    def __init__(
        self,
        *,
        settings: Settings,
        ai_service: AiPrefillService | None = None,
        structure_image_service: StructureSourceImageService | None = None,
    ) -> None:
        self.settings = settings
        self.ai_service = ai_service or AiPrefillService(structure_image_service)
        self.structure_image_service = (
            structure_image_service or self.ai_service.structure_image_service
            or StructureSourceImageService(
                settings.asset_root, source_roots=settings.source_roots,
            )
        )

    def apply(
        self,
        session: Session,
        *,
        instance_id: UUID,
        idempotency_key: str,
        candidate: CandidateEnvelope,
        validation_report: ValidationReport,
        actor_id: UUID,
        reviewer_id: UUID | None = None,
        paper_id: UUID | None = None,
        workspace_id: UUID | None = None,
        run_id: UUID | None = None,
        expected_workspace_version: int | None = None,
    ) -> PreviewApplicationResult:
        if instance_id != self.settings.preview_instance_id:
            raise PreviewIdentityError("Preview requested instance differs from configuration")
        verify_preview_connection(self.settings, session.connection(), lock=True)
        if not idempotency_key.strip() or len(idempotency_key) > 255:
            raise PreviewApplicationValidationError("idempotency_key is required")

        # Detach mutable caller-owned models before computing identities or using
        # their nested payload; every subsequent step uses these exact values.
        candidate = CandidateEnvelope.model_validate_json(candidate.model_dump_json())
        validation_report = ValidationReport.model_validate_json(validation_report.model_dump_json())
        if (workspace_id is not None or run_id is not None) and expected_workspace_version is None:
            raise PreviewApplicationValidationError(
                "expected_workspace_version is required for an existing workspace"
            )

        marker = session.scalar(
            select(PreviewMarker)
            .where(PreviewMarker.instance_id == instance_id)
            .with_for_update()
        )
        if marker is None:
            raise PreviewApplicationError("Preview instance is not registered")

        paper = self._lock_paper(session, candidate, paper_id)
        source = session.get(PaperSource, paper.source_id)
        if source is None:
            raise PreviewApplicationError("Paper Source is unavailable")
        if source.integrity_state is not PaperSourceIntegrityState.VERIFIED:
            raise PreviewApplicationValidationError("Paper Source is not verified")
        if source.byte_size != candidate.source.byte_size:
            raise PreviewApplicationValidationError("candidate source byte size mismatch")
        if source.page_count != candidate.source.page_count:
            raise PreviewApplicationValidationError("candidate source page count mismatch")
        if source.sha256 != candidate.source.source_sha256:
            raise PreviewApplicationValidationError("candidate source hash mismatch")
        if candidate.source.doi is not None and (
            paper.doi is None or candidate.source.doi.casefold() != paper.doi.casefold()
        ):
            raise PreviewApplicationValidationError("candidate source DOI mismatch")

        request_digest = application_request_digest(
            instance_id=instance_id,
            idempotency_key=idempotency_key,
            candidate=candidate,
            report=validation_report,
            actor_id=actor_id,
            reviewer_id=reviewer_id,
            paper_id=paper.id,
            workspace_id=workspace_id,
            run_id=run_id,
            expected_workspace_version=expected_workspace_version,
        )
        previous = session.scalar(
            select(ApplicationReceipt)
            .where(
                ApplicationReceipt.instance_id == instance_id,
                ApplicationReceipt.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if previous is not None:
            if previous.request_digest != request_digest:
                raise PreviewApplicationConflictError(
                    "idempotency key was already used for a different request"
                )
            return PreviewApplicationResult(previous, applied=False, idempotent=True)

        source_asset, source_bytes = self._pin_source(session, source)
        verification = verify_candidate_for_application(
            candidate,
            validation_report,
            expected_source_sha256=source.sha256,
            expected_page_count=source.page_count,
            expected_doi=paper.doi,
        )
        workspace, run = self._resolve_workspace_and_run(
            session,
            paper=paper,
            actor_id=actor_id,
            reviewer_id=reviewer_id,
            workspace_id=workspace_id,
            run_id=run_id,
            expected_workspace_version=expected_workspace_version,
        )
        initial_snapshot = {
            "paper": {
                "id": str(paper.id),
                "paper_key": paper.paper_key,
                "title": paper.title,
                "doi": paper.doi,
                "journal": paper.journal,
                "publication_year": paper.publication_year,
                "volume": paper.volume,
                "issue": paper.issue,
            },
            "workspace": {
                "id": str(workspace.id),
                "version": workspace.version,
                "state": workspace.state.value,
            },
            "run_id": str(run.id),
        }
        initial_workspace_version = workspace.version

        # Clone services per call so concurrent applications cannot replace each
        # other's pinned input. Crops use the already verified immutable bytes.
        ai_service = copy(self.ai_service)
        ai_service.drawing_service = StructureDrawingService(self.settings.asset_root)
        ai_service.structure_image_service = self.structure_image_service.with_source_snapshot(
            paper_id=paper.id, asset=source_asset, content=source_bytes,
        )
        result = ai_service.apply(
            session,
            run_id=run.id,
            payload=verification.candidate.payload,
        )
        if not result.applied:
            raise PreviewApplicationError(
                "AI apply did not commit; the Preview transaction was rolled back"
            )
        if (
            result.run.status is not AiExtractionRunStatus.SUCCEEDED
            or workspace.version != initial_workspace_version + 1
        ):
            raise PreviewApplicationError(
                "Preview apply did not produce the expected run and workspace state"
            )
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(
                ChangeEvent.ai_run_id == run.id,
                ChangeEvent.workspace_id == workspace.id,
                ChangeEvent.paper_id == paper.id,
                ChangeEvent.actor_kind == ChangeActorKind.AI,
            )
        )
        if not event_count:
            raise PreviewApplicationError(
                "Preview apply produced no AI ChangeEvent history"
            )
        pending_sections = session.scalar(
            select(func.count())
            .select_from(PaperSectionReview)
            .where(
                PaperSectionReview.workspace_id == workspace.id,
                PaperSectionReview.state == "pending",
            )
        )
        initial_snapshot["after_apply"] = {
            "workspace_version": workspace.version,
            "run_status": result.run.status.value,
            "ai_event_count": int(event_count),
            "entity_count": len(result.entity_map or {}),
            "pending_section_count": int(pending_sections or 0),
            "delivery_notes": result.delivery_notes,
        }

        receipt = ApplicationReceipt(
            instance_id=instance_id,
            application_id=uuid4(),
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            candidate_sha256=verification.hashes.candidate_sha256,
            payload_sha256=verification.hashes.payload_sha256,
            source_sha256=source.sha256,
            paper_id=paper.id,
            workspace_id=workspace.id,
            run_id=run.id,
            actor_id=actor_id,
            entity_map=result.entity_map or {},
            initial_snapshot=initial_snapshot,
        )
        session.add(receipt)
        session.flush()
        return PreviewApplicationResult(receipt, applied=True, idempotent=False)

    def _pin_source(self, session: Session, source: PaperSource) -> tuple[Asset, bytes]:
        asset = session.get(Asset, source.asset_id)
        if (
            asset is None or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.mime_type != "application/pdf"
            or (asset.sha256, asset.byte_size, asset.page_count)
            != (source.sha256, source.byte_size, source.page_count)
            or asset.storage_key != f"source/{source.source_root_key}/{source.source_key}"
        ):
            raise PreviewApplicationValidationError("Paper Source asset identity mismatch")
        try:
            inspected, content = LocalAssetStore(
                self.settings.asset_root, source_roots=self.settings.source_roots,
            ).read_snapshot(asset.storage_key)
        except (AssetPathError, AssetMimeMismatchError, OSError, ValueError) as error:
            raise PreviewApplicationValidationError("Paper Source is unavailable or invalid") from error
        if (
            inspected.mime_type != "application/pdf"
            or (inspected.sha256, inspected.byte_size, inspected.page_count)
            != (source.sha256, source.byte_size, source.page_count)
        ):
            raise PreviewApplicationValidationError("Paper Source failed byte integrity verification")
        try:
            with pymupdf.open(stream=content, filetype="pdf") as document:
                if document.needs_pass or document.page_count != source.page_count:
                    raise PreviewApplicationValidationError("Paper Source PDF is encrypted or has unexpected pages")
        except (RuntimeError, ValueError) as error:
            raise PreviewApplicationValidationError("Paper Source PDF cannot be opened") from error
        return asset, content

    @staticmethod
    def _lock_paper(
        session: Session,
        candidate: CandidateEnvelope,
        paper_id: UUID | None,
    ) -> Paper:
        statement = select(Paper).where(Paper.paper_key == candidate.source.paper_key)
        if paper_id is not None:
            statement = statement.where(Paper.id == paper_id)
        paper = session.scalar(statement.with_for_update())
        if paper is None:
            raise AiPrefillNotFoundError("Paper not found")
        return paper

    @staticmethod
    def _resolve_workspace_and_run(
        session: Session,
        *,
        paper: Paper,
        actor_id: UUID,
        reviewer_id: UUID | None,
        workspace_id: UUID | None,
        run_id: UUID | None,
        expected_workspace_version: int | None,
    ) -> tuple[PaperWorkspace, AiExtractionRun]:
        if run_id is not None:
            requested_workspace_id = workspace_id
            run = session.scalar(
                select(AiExtractionRun)
                .where(AiExtractionRun.id == run_id)
                .with_for_update()
            )
            if run is None or run.paper_id != paper.id:
                raise AiPrefillNotFoundError("AI extraction run not found")
            if (
                requested_workspace_id is not None
                and requested_workspace_id != run.workspace_id
            ):
                raise PreviewApplicationConflictError(
                    "run and workspace do not belong to the same application"
                )
            workspace_id = run.workspace_id
        workspace = None
        if workspace_id is not None:
            workspace = session.scalar(
                select(PaperWorkspace)
                .where(
                    PaperWorkspace.id == workspace_id,
                    PaperWorkspace.paper_id == paper.id,
                )
                .with_for_update()
            )
            if workspace is None:
                raise AiPrefillNotFoundError("Workspace not found")
        else:
            active_task = session.scalar(select(ReviewTask.id).where(
                ReviewTask.paper_id == paper.id,
                ReviewTask.status.notin_([ReviewTaskState.APPROVED, ReviewTaskState.ARCHIVED]),
            ).limit(1))
            if active_task is not None:
                raise PreviewApplicationConflictError(
                    "an existing assignment requires explicit workspace ID and version"
                )
            if reviewer_id is not None:
                reviewer = session.get(User, reviewer_id)
                if reviewer is None or reviewer.role is not UserRole.REVIEWER:
                    raise PreviewApplicationValidationError(
                        "reviewer_id must identify a Reviewer"
                    )
            selected_reviewer_id = session.scalar(
                select(User.id)
                .where(User.role == UserRole.REVIEWER)
                .order_by(User.id)
                .limit(1)
            )
            assigned_reviewer_id = reviewer_id or selected_reviewer_id
            if assigned_reviewer_id is None:
                raise PreviewApplicationError("Preview assignment requires a Reviewer")
            task = ReviewTask(
                paper_id=paper.id,
                assigned_reviewer_id=assigned_reviewer_id,
                created_by_id=actor_id,
            )
            session.add(task)
            session.flush()
            workspace = PaperWorkspace(
                paper_id=paper.id,
                review_task_id=task.id,
                state=WorkspaceState.EDITING,
                version=1,
            )
            session.add(workspace)
            session.flush()
            session.add_all(
                PaperSectionReview(
                    paper_id=paper.id,
                    workspace_id=workspace.id,
                    section_key=section,
                )
                for section in PaperSection
            )
            session.flush()
        if expected_workspace_version is not None and workspace.version != expected_workspace_version:
            raise PreviewApplicationConflictError("workspace version does not match request")
        if run_id is None:
            run = AiPrefillService().queue(
                session,
                workspace_id=workspace.id,
                requested_by_id=actor_id,
                engine="ai-prefill-preview",
                engine_version="candidate-envelope-v1",
            ).run
        return workspace, run


__all__ = [
    "PreviewApplicationConflictError",
    "PreviewApplicationError",
    "PreviewApplicationResult",
    "PreviewApplicationService",
    "application_request_digest",
]
