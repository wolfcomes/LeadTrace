from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.imports.models import ImportReleaseCandidate, ImportStagingRecord
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.revisions.models import ObjectKind, ObjectRevision, StructureState
from app.security.policies import WorkflowState
from app.users.models import User


AdminPaperWorkflowState = Literal[
    "initial",
    "ai_baseline_unassigned",
    "ai_baseline_in_review",
    "human_review_pending_approval",
    "admin_approved",
]
PublicationStatus = Literal["unpublished", "published"]

WORKFLOW_STATES: tuple[AdminPaperWorkflowState, ...] = (
    "initial",
    "ai_baseline_unassigned",
    "ai_baseline_in_review",
    "human_review_pending_approval",
    "admin_approved",
)


class AdminPaperSourceNotFound(LookupError):
    """The selected candidate does not exist."""


class AdminPaperNotFound(LookupError):
    """The selected Paper does not exist in the database catalog."""


@dataclass(frozen=True, slots=True)
class _SourceContext:
    candidate: ImportReleaseCandidate | None
    release: Release | None


def _normalized_values(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized = value.get("normalized_values")
    return normalized if isinstance(normalized, dict) else value


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _empty_quality() -> dict[str, int]:
    return {
        "compounds": 0,
        "structures": 0,
        "confirmed_structures": 0,
        "evidence": 0,
        "activities": 0,
        "lineages": 0,
        "lineage_edges": 0,
        "unresolved_relations": 0,
        "visual_objects": 0,
    }


def _task_payload(task: ReviewTask | None, users: dict[UUID, User]) -> dict[str, object] | None:
    if task is None:
        return None
    assignee = users.get(task.assigned_reviewer_id)
    return {
        "id": str(task.id),
        "status": task.status.value,
        "assignee_id": str(task.assigned_reviewer_id),
        "assignee_display_name": (
            assignee.display_name if assignee is not None else "未知用户"
        ),
        "priority": task.priority,
        "version": task.version,
        "updated_at": task.updated_at.isoformat(),
    }


def _changeset_payload(changeset: Changeset | None) -> dict[str, object] | None:
    if changeset is None:
        return None
    return {
        "id": str(changeset.id),
        "workflow_state": changeset.workflow_state.value,
        "version": changeset.version,
        "updated_at": changeset.updated_at.isoformat(),
    }


def _derive_workflow_state(
    *,
    has_ai_baseline: bool,
    task: ReviewTask | None,
    changeset: Changeset | None,
) -> AdminPaperWorkflowState:
    if changeset is not None and changeset.workflow_state in {
        WorkflowState.APPROVED,
        WorkflowState.PUBLISHED,
    }:
        return "admin_approved"
    if changeset is not None and changeset.workflow_state is WorkflowState.SUBMITTED:
        return "human_review_pending_approval"
    if changeset is not None and changeset.workflow_state in {
        WorkflowState.DRAFT,
        WorkflowState.REVISED_DRAFT,
        WorkflowState.CHANGES_REQUESTED,
    }:
        return "ai_baseline_in_review"
    if task is not None and task.status is not ReviewTaskStatus.COMPLETED:
        return "ai_baseline_in_review"
    if has_ai_baseline:
        return "ai_baseline_unassigned"
    return "initial"


class AdminPaperCatalog:
    """Read a safe Admin projection across imports, releases, and review state."""

    def _source_context(
        self,
        session: Session,
        candidate_id: UUID | None,
    ) -> _SourceContext:
        current_release = session.scalar(
            select(Release).where(Release.is_current.is_(True)).limit(1)
        )
        if candidate_id is not None:
            candidate = session.get(ImportReleaseCandidate, candidate_id)
            if candidate is None:
                raise AdminPaperSourceNotFound("Import candidate not found")
            return _SourceContext(candidate=candidate, release=current_release)
        if current_release is not None:
            return _SourceContext(candidate=None, release=current_release)
        candidate = session.scalar(
            select(ImportReleaseCandidate)
            .where(ImportReleaseCandidate.status != "rejected")
            .order_by(ImportReleaseCandidate.created_at.desc())
            .limit(1)
        )
        if candidate is None:
            candidate = session.scalar(
                select(ImportReleaseCandidate)
                .order_by(ImportReleaseCandidate.created_at.desc())
                .limit(1)
            )
        return _SourceContext(candidate=candidate, release=None)

    @staticmethod
    def _published_paper_ids(
        session: Session,
        release: Release | None,
    ) -> set[UUID]:
        if release is None:
            return set()
        return set(
            session.scalars(
                select(ReleaseItem.paper_id).where(
                    ReleaseItem.release_id == release.id,
                    ReleaseItem.object_kind == ObjectKind.PAPER,
                )
            )
        )

    @staticmethod
    def _candidate_projection(
        session: Session,
        candidate: ImportReleaseCandidate,
    ) -> tuple[
        set[str],
        dict[str, dict[str, object]],
        dict[str, dict[str, int]],
        dict[str, str],
        dict[str, str],
    ]:
        rows = session.execute(
            select(
                ImportStagingRecord.record_type,
                ImportStagingRecord.original_id,
                ImportStagingRecord.normalized_values,
            ).where(
                ImportStagingRecord.import_batch_id == candidate.import_batch_id
            )
        )
        baseline_keys: set[str] = set()
        metadata: dict[str, dict[str, object]] = {}
        quality: dict[str, dict[str, int]] = defaultdict(_empty_quality)
        targets: dict[str, str] = {}
        review_statuses: dict[str, str] = {}
        for record_type, original_id, normalized in rows:
            values = normalized if isinstance(normalized, dict) else {}
            paper_key = _text(values.get("paper_id"))
            if record_type == "paper":
                paper_key = paper_key or str(original_id)
                baseline_keys.add(paper_key)
                metadata[paper_key] = values
            if paper_key is None:
                continue
            counts = quality[paper_key]
            counter_name = {
                "compound": "compounds",
                "structure": "structures",
                "evidence": "evidence",
                "activity": "activities",
                "lineage": "lineages",
                "lineage_edge": "lineage_edges",
                "visual_object": "visual_objects",
            }.get(record_type)
            if counter_name is not None:
                counts[counter_name] += 1
            if (
                record_type == "structure"
                and values.get("confirmation_status") == "structure_confirmed"
            ):
                counts["confirmed_structures"] += 1
            if record_type == "lineage_edge" and values.get(
                "relation_status"
            ) in {None, "", "unresolved", "invalid"}:
                counts["unresolved_relations"] += 1
            if record_type == "activity" and paper_key not in targets:
                target = _text(values.get("target"))
                if target is not None:
                    targets[paper_key] = target
            if paper_key not in review_statuses:
                status = _text(values.get("review_status"))
                if status is not None:
                    review_statuses[paper_key] = status
        return baseline_keys, metadata, quality, targets, review_statuses

    @staticmethod
    def _release_projection(
        session: Session,
        release: Release,
    ) -> tuple[
        set[UUID],
        dict[UUID, ObjectRevision],
        dict[UUID, dict[str, int]],
    ]:
        rows = session.execute(
            select(ReleaseItem, ObjectRevision)
            .join(ObjectRevision, ObjectRevision.id == ReleaseItem.revision_id)
            .where(ReleaseItem.release_id == release.id)
        )
        baseline_ids: set[UUID] = set()
        metadata: dict[UUID, ObjectRevision] = {}
        quality: dict[UUID, dict[str, int]] = defaultdict(_empty_quality)
        for item, revision in rows:
            counts = quality[item.paper_id]
            if item.object_kind is ObjectKind.PAPER:
                baseline_ids.add(item.paper_id)
                metadata[item.paper_id] = revision
            counter_name = {
                ObjectKind.COMPOUND: "compounds",
                ObjectKind.STRUCTURE: "structures",
                ObjectKind.EVIDENCE: "evidence",
                ObjectKind.ACTIVITY: "activities",
                ObjectKind.LINEAGE: "lineages",
                ObjectKind.LINEAGE_EDGE: "lineage_edges",
                ObjectKind.VISUAL_OBJECT: "visual_objects",
            }.get(item.object_kind)
            if counter_name is not None:
                counts[counter_name] += 1
            if (
                item.object_kind is ObjectKind.STRUCTURE
                and revision.structure_state is StructureState.STRUCTURE_CONFIRMED
            ):
                counts["confirmed_structures"] += 1
            if item.object_kind is ObjectKind.LINEAGE_EDGE and revision.relation_status in {
                None,
                "",
                "unresolved",
                "invalid",
            }:
                counts["unresolved_relations"] += 1
        return baseline_ids, metadata, quality

    @staticmethod
    def _review_projection(
        session: Session,
        paper_ids: list[UUID],
    ) -> tuple[
        dict[UUID, ReviewTask],
        dict[UUID, Changeset],
        dict[UUID, User],
    ]:
        if not paper_ids:
            return {}, {}, {}
        tasks = list(
            session.scalars(
                select(ReviewTask)
                .where(ReviewTask.paper_id.in_(paper_ids))
                .order_by(ReviewTask.updated_at.desc(), ReviewTask.id.desc())
            )
        )
        changesets = list(
            session.scalars(
                select(Changeset)
                .where(Changeset.paper_id.in_(paper_ids))
                .order_by(Changeset.updated_at.desc(), Changeset.id.desc())
            )
        )
        task_by_paper: dict[UUID, ReviewTask] = {}
        for task in tasks:
            existing = task_by_paper.get(task.paper_id)
            if existing is None or (
                existing.status is ReviewTaskStatus.COMPLETED
                and task.status is not ReviewTaskStatus.COMPLETED
            ):
                task_by_paper[task.paper_id] = task
        changeset_by_paper: dict[UUID, Changeset] = {}
        for changeset in changesets:
            changeset_by_paper.setdefault(changeset.paper_id, changeset)
        user_ids = {task.assigned_reviewer_id for task in tasks}
        users = {
            user.id: user
            for user in session.scalars(select(User).where(User.id.in_(user_ids)))
        } if user_ids else {}
        return task_by_paper, changeset_by_paper, users

    @staticmethod
    def _source_payload(context: _SourceContext) -> dict[str, object]:
        if context.candidate is not None:
            candidate = context.candidate
            return {
                "kind": "candidate",
                "candidate_id": str(candidate.id),
                "release_id": None,
                "title": "AI 提取基线候选",
                "status": candidate.status,
                "dataset_class": "ai_extracted_baseline",
                "verification_status": "unverified",
                "publication_status": (
                    "published" if candidate.status == "published" else "unpublished"
                ),
            }
        if context.release is not None:
            release = context.release
            dataset = release.metrics.get("dataset")
            if not isinstance(dataset, dict):
                dataset = {}
            dataset_class = _text(dataset.get("dataset_class"))
            verification = _text(dataset.get("verification_status"))
            if dataset_class is None:
                dataset_class = (
                    "ai_extracted_baseline"
                    if release.source_candidate_id is not None
                    else "human_verified_dataset"
                )
            if verification is None:
                verification = (
                    "unverified"
                    if dataset_class == "ai_extracted_baseline"
                    else "human_verified"
                )
            return {
                "kind": "release",
                "candidate_id": (
                    str(release.source_candidate_id)
                    if release.source_candidate_id is not None
                    else None
                ),
                "release_id": str(release.id),
                "title": release.title,
                "status": "published",
                "dataset_class": dataset_class,
                "verification_status": verification,
                "publication_status": "published",
            }
        return {
            "kind": "database",
            "candidate_id": None,
            "release_id": None,
            "title": "数据库文章目录",
            "status": "initial",
            "dataset_class": "unclassified",
            "verification_status": "unverified",
            "publication_status": "unpublished",
        }

    def _items(
        self,
        session: Session,
        context: _SourceContext,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        papers = list(session.scalars(select(Paper).order_by(Paper.paper_key, Paper.id)))
        paper_ids = [paper.id for paper in papers]
        published_ids = self._published_paper_ids(session, context.release)

        candidate_keys: set[str] = set()
        candidate_metadata: dict[str, dict[str, object]] = {}
        candidate_quality: dict[str, dict[str, int]] = {}
        candidate_targets: dict[str, str] = {}
        candidate_review_statuses: dict[str, str] = {}
        release_ids: set[UUID] = set()
        release_metadata: dict[UUID, ObjectRevision] = {}
        release_quality: dict[UUID, dict[str, int]] = {}
        if context.candidate is not None:
            (
                candidate_keys,
                candidate_metadata,
                candidate_quality,
                candidate_targets,
                candidate_review_statuses,
            ) = self._candidate_projection(session, context.candidate)
        elif context.release is not None:
            release_ids, release_metadata, release_quality = self._release_projection(
                session, context.release
            )

        task_by_paper, changeset_by_paper, users = self._review_projection(
            session, paper_ids
        )
        source = self._source_payload(context)
        source_verification = str(source["verification_status"])
        items: list[dict[str, object]] = []
        for paper in papers:
            has_ai_baseline = (
                paper.paper_key in candidate_keys
                if context.candidate is not None
                else paper.id in release_ids
            )
            normalized: dict[str, object] = {}
            quality = _empty_quality()
            target = None
            review_status = None
            revision_id = None
            if context.candidate is not None:
                normalized = candidate_metadata.get(paper.paper_key, {})
                quality = candidate_quality.get(paper.paper_key, _empty_quality())
                target = candidate_targets.get(paper.paper_key)
                review_status = candidate_review_statuses.get(paper.paper_key)
            elif context.release is not None:
                revision = release_metadata.get(paper.id)
                if revision is not None:
                    normalized = _normalized_values(revision.snapshot)
                    revision_id = str(revision.id)
                quality = release_quality.get(paper.id, _empty_quality())

            task = task_by_paper.get(paper.id)
            changeset = changeset_by_paper.get(paper.id)
            workflow_state = _derive_workflow_state(
                has_ai_baseline=has_ai_baseline,
                task=task,
                changeset=changeset,
            )
            publication_status: PublicationStatus = (
                "published" if paper.id in published_ids else "unpublished"
            )
            active_task = task is not None and task.status is not ReviewTaskStatus.COMPLETED
            can_modify = publication_status == "published" and active_task and workflow_state not in {
                "human_review_pending_approval",
                "admin_approved",
            }
            if publication_status != "published":
                modification_blocker = "baseline_must_be_published"
            elif not active_task:
                modification_blocker = "review_task_required"
            elif workflow_state == "human_review_pending_approval":
                modification_blocker = "pending_admin_approval"
            elif workflow_state == "admin_approved":
                modification_blocker = "approved_changeset_locked"
            else:
                modification_blocker = None
            items.append(
                {
                    "id": str(paper.id),
                    "revision_id": revision_id,
                    "paper_key": paper.paper_key,
                    "doi": paper.doi,
                    "title": _text(normalized.get("title_guess"))
                    or _text(normalized.get("title"))
                    or paper.paper_key,
                    "year": _text(normalized.get("filename_year"))
                    or _text(normalized.get("year")),
                    "target": target or _text(normalized.get("target")),
                    "review_status": review_status
                    or _text(normalized.get("review_status")),
                    "workflow_state": workflow_state,
                    "publication_status": publication_status,
                    "verification_status": (
                        source_verification if has_ai_baseline else "unverified"
                    ),
                    "quality": dict(quality),
                    "task": _task_payload(task, users),
                    "changeset": _changeset_payload(changeset),
                    "can_modify": can_modify,
                    "modification_blocker": modification_blocker,
                }
            )
        return items, source

    def list(
        self,
        session: Session,
        *,
        candidate_id: UUID | None = None,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        doi: str | None = None,
        workflow_state: AdminPaperWorkflowState | None = None,
        publication_status: PublicationStatus | None = None,
        assignee_id: UUID | None = None,
    ) -> dict[str, object]:
        context = self._source_context(session, candidate_id)
        items, source = self._items(session, context)
        status_counts = Counter(str(item["workflow_state"]) for item in items)
        normalized_search = (search or "").strip().casefold()
        normalized_doi = (doi or "").strip().casefold()
        filtered = []
        for item in items:
            searchable = " ".join(
                str(item.get(field) or "")
                for field in ("paper_key", "title", "doi", "target")
            ).casefold()
            if normalized_search and normalized_search not in searchable:
                continue
            if normalized_doi and normalized_doi not in str(item.get("doi") or "").casefold():
                continue
            if workflow_state is not None and item["workflow_state"] != workflow_state:
                continue
            if (
                publication_status is not None
                and item["publication_status"] != publication_status
            ):
                continue
            if assignee_id is not None:
                task = item.get("task")
                if not isinstance(task, dict) or task.get("assignee_id") != str(assignee_id):
                    continue
            filtered.append(item)
        total_items = len(filtered)
        total_pages = math.ceil(total_items / page_size) if total_items else 0
        start = (page - 1) * page_size
        return {
            "source": source,
            "status_counts": {
                state: status_counts.get(state, 0) for state in WORKFLOW_STATES
            },
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
            },
            "filters": {
                "candidate_id": str(candidate_id) if candidate_id else None,
                "search": search,
                "doi": doi,
                "workflow_state": workflow_state,
                "publication_status": publication_status,
                "assignee_id": str(assignee_id) if assignee_id else None,
            },
            "items": filtered[start : start + page_size],
        }

    def detail(
        self,
        session: Session,
        *,
        paper_id: UUID,
        candidate_id: UUID | None = None,
    ) -> dict[str, object]:
        if session.get(Paper, paper_id) is None:
            raise AdminPaperNotFound("Paper not found")
        context = self._source_context(session, candidate_id)
        items, source = self._items(session, context)
        paper = next((item for item in items if item["id"] == str(paper_id)), None)
        if paper is None:
            raise AdminPaperNotFound("Paper not found")
        return {
            "source": source,
            "paper": paper,
            "source_pdf_url": f"/api/v1/papers/{paper_id}/source-pdf?kind=article",
            "review_entry": (
                f"/review/changesets/{paper['changeset']['id']}"
                if isinstance(paper.get("changeset"), dict)
                and paper["changeset"].get("id")
                else (
                    f"/review/changesets?task={paper['task']['id']}"
                    if isinstance(paper.get("task"), dict)
                    and paper["task"].get("id")
                    else None
                )
            ),
        }


__all__ = [
    "AdminPaperCatalog",
    "AdminPaperNotFound",
    "AdminPaperSourceNotFound",
    "AdminPaperWorkflowState",
    "PublicationStatus",
    "WORKFLOW_STATES",
]
