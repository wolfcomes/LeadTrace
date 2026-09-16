from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.audit.service import AuditService, canonical_content_hash
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.users.models import User, UserRole
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)


class PaperNotFoundError(LookupError):
    pass


class ReviewerNotFoundError(LookupError):
    pass


class InvalidReviewerError(ValueError):
    pass


class ActiveAssignmentError(RuntimeError):
    pass


class PaperSourceUnverifiedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    task: ReviewTask
    workspace: PaperWorkspace
    sections: list[PaperSectionReview]


class AssignmentService:
    def __init__(self, audit_service: AuditService | None = None) -> None:
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def _verified_source(
        session: Session,
        paper: Paper,
    ) -> tuple[PaperSource, Asset]:
        source = session.scalar(
            select(PaperSource)
            .where(PaperSource.id == paper.source_id)
            .with_for_update()
        )
        if source is None:
            raise PaperSourceUnverifiedError("Paper source is not verified")
        asset = session.scalar(
            select(Asset).where(Asset.id == source.asset_id).with_for_update()
        )
        expected_storage_key = (
            f"source/{source.source_root_key}/{source.source_key}"
        )
        if (
            paper.catalog_state is PaperCatalogState.SOURCE_ERROR
            or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or asset is None
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.category is not AssetCategory.ARTICLE_PDF
            or asset.access_level is not AssetAccessLevel.REVIEWER
            or asset.mime_type != "application/pdf"
            or asset.storage_key != expected_storage_key
            or asset.sha256 != source.sha256
            or asset.byte_size != source.byte_size
            or asset.page_count != source.page_count
        ):
            raise PaperSourceUnverifiedError("Paper source is not verified")
        return source, asset

    def assign(
        self,
        session: Session,
        *,
        paper_id: UUID,
        reviewer_id: UUID,
        admin_id: UUID,
        request_id: str,
        ip_address: str,
    ) -> AssignmentResult:
        paper = session.scalar(
            select(Paper).where(Paper.id == paper_id).with_for_update()
        )
        if paper is None:
            raise PaperNotFoundError("Paper not found")

        reviewer = session.scalar(
            select(User).where(User.id == reviewer_id).with_for_update()
        )
        if reviewer is None:
            raise ReviewerNotFoundError("Reviewer not found")
        if reviewer.role is not UserRole.REVIEWER or not reviewer.is_enabled:
            raise InvalidReviewerError("An enabled Reviewer is required")

        self._verified_source(session, paper)
        existing = session.scalar(
            select(ReviewTask.id).where(
                ReviewTask.paper_id == paper.id,
                ReviewTask.status != ReviewTaskState.APPROVED,
            )
        )
        if existing is not None:
            raise ActiveAssignmentError("Paper already has an active assignment")

        task = ReviewTask(
            paper_id=paper.id,
            assigned_reviewer_id=reviewer.id,
            created_by_id=admin_id,
            status=ReviewTaskState.ASSIGNED,
            version=1,
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
        sections = [
            PaperSectionReview(
                paper_id=paper.id,
                workspace_id=workspace.id,
                section_key=section_key,
                state=PaperSectionState.PENDING,
                note=None,
            )
            for section_key in PaperSection
        ]
        session.add_all(sections)
        session.flush()

        before = {"paper_id": str(paper.id), "active_assignment": None}
        after = {
            "paper_id": str(paper.id),
            "review_task_id": str(task.id),
            "workspace_id": str(workspace.id),
            "assigned_reviewer_id": str(reviewer.id),
            "task_status": task.status.value,
            "workspace_state": workspace.state.value,
        }
        self.audit_service.append_event(
            session,
            actor_id=admin_id,
            action="paper.review_assigned",
            target_type="review_task",
            target_id=task.id,
            paper_id=paper.id,
            changeset_id=None,
            release_id=None,
            ip_address=ip_address,
            request_id=request_id,
            result="success",
            reason="Admin assigned a Paper to an enabled Reviewer",
            before_hash=canonical_content_hash(before),
            after_hash=canonical_content_hash(after),
            details={
                "assigned_reviewer_id": str(reviewer.id),
                "workspace_id": str(workspace.id),
            },
        )
        return AssignmentResult(task=task, workspace=workspace, sections=sections)


__all__ = [
    "ActiveAssignmentError",
    "AssignmentResult",
    "AssignmentService",
    "InvalidReviewerError",
    "PaperNotFoundError",
    "PaperSourceUnverifiedError",
    "ReviewerNotFoundError",
]
