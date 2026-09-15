from __future__ import annotations

from typing import Literal
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.assets.models import Asset
from app.audit.service import canonical_content_hash
from app.molecule_proposals.models import MoleculeProposal
from app.releases.manifest import (
    draft_binding_delta_for_changeset,
    get_release_artifact_manifest,
    merge_binding_snapshots,
)
from app.releases.models import ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision, RevisionedObject
from app.revisions.service import RevisionService
from app.reviews.completeness import ObjectCompleteness, QueueState, assess_object
from app.reviews.models import Changeset, ChangesetItem, PaperReviewAttestation, PaperReviewScope
from app.reviews.service import (
    InvalidReview,
    ReviewForbidden,
    ReviewNotFound,
    RevisionConflict,
    ReviewService,
)
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import User, UserRole
from app.visual_objects.models import VisualObject, VisualRegion


class PaperAttestationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    scope_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    statement: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]

    @field_validator("statement")
    @classmethod
    def normalize_statement(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("statement is required")
        return value


class PaperAttestationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    changeset_id: UUID
    paper_id: UUID
    changeset_version: int
    scope_hash: str
    item_count: int
    resolved_count: int
    blocker_count: int
    statement: str
    stale: bool = False


@dataclass(frozen=True, slots=True)
class ReviewProgress:
    item_count: int
    resolved_count: int
    blocker_count: int
    states: tuple[ObjectCompleteness, ...]


class AttestationValidationError(ValueError):
    """Raised when a Paper cannot be attested at the requested version."""


def _snapshot_hash(session: Session, snapshot: Mapping[str, object]) -> str:
    value = session.scalar(select(func.leadtrace_jsonb_sha256(cast(dict(snapshot), JSONB))))
    return str(value or canonical_content_hash(snapshot))


def _uuid(value: object, *, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise AttestationValidationError(
            f"Frozen Paper attestation {field} is invalid"
        ) from error


def validate_frozen_attestation(
    session: Session,
    *,
    changeset: Changeset,
) -> PaperReviewAttestation | None:
    """Return the attestation bound to the exact frozen submission, if scoped."""

    scope = session.scalar(
        select(PaperReviewScope).where(
            PaperReviewScope.changeset_id == changeset.id
        )
    )
    if scope is None:
        return None
    submitted = changeset.submitted_snapshot
    if not isinstance(submitted, Mapping):
        raise AttestationValidationError(
            "Frozen Paper attestation submission is missing"
        )
    validation_results = submitted.get("validation_results")
    summary = (
        validation_results.get("paper_attestation")
        if isinstance(validation_results, Mapping)
        else None
    )
    if not isinstance(summary, Mapping):
        raise AttestationValidationError(
            "Frozen Paper attestation summary is missing"
        )
    attestation = session.get(
        PaperReviewAttestation,
        _uuid(summary.get("id"), field="id"),
    )
    if attestation is None:
        raise AttestationValidationError("Frozen Paper attestation is missing")

    paper_items = [
        row
        for row in submitted.get("items", [])
        if isinstance(row, Mapping)
        and row.get("object_kind") == ObjectKind.PAPER.value
        and row.get("object_id") == str(changeset.paper_id)
    ]
    if len(paper_items) != 1:
        raise AttestationValidationError(
            "Frozen Paper attestation does not identify one Paper revision"
        )
    paper_item = paper_items[0]
    proposed_snapshot = paper_item.get("proposed_snapshot")
    normalized = (
        proposed_snapshot.get("normalized_values")
        if isinstance(proposed_snapshot, Mapping)
        else None
    )
    if not isinstance(normalized, Mapping) or normalized.get("review_status") != "reviewed":
        raise AttestationValidationError(
            "Frozen Paper attestation revision is not marked reviewed"
        )

    reviewer = session.get(User, attestation.reviewer_id)
    expected = {
        "changeset_id": attestation.changeset_id == changeset.id,
        "paper_id": attestation.paper_id == changeset.paper_id,
        "scope_id": attestation.scope_id == scope.id,
        "scope_hash": attestation.scope_hash == scope.scope_hash,
        "reviewer_id": attestation.reviewer_id == changeset.owner_id,
        "paper_revision_id": str(attestation.paper_revision_id)
        == paper_item.get("proposed_revision_id"),
        "item_count": attestation.item_count == scope.item_count,
        "resolved_count": attestation.resolved_count == attestation.item_count,
        "blocker_count": attestation.blocker_count == 0,
        "summary_scope_id": summary.get("scope_id") == str(scope.id),
        "summary_scope_hash": summary.get("scope_hash") == scope.scope_hash,
        "summary_version": summary.get("changeset_version")
        == attestation.changeset_version,
        "summary_item_count": summary.get("item_count") == attestation.item_count,
        "summary_resolved_count": summary.get("resolved_count")
        == attestation.resolved_count,
        "summary_blocker_count": summary.get("blocker_count")
        == attestation.blocker_count,
        "summary_statement": summary.get("statement") == attestation.statement,
        "reviewer_enabled": reviewer is not None and reviewer.is_enabled,
        "reviewer_role": reviewer is not None
        and reviewer.role is UserRole.REVIEWER,
    }
    invalid = [name for name, valid in expected.items() if not valid]
    if invalid:
        raise AttestationValidationError(
            "Frozen Paper attestation is inconsistent: " + ", ".join(invalid)
        )
    return attestation


class PaperReviewScopeService:
    """Create immutable review scope snapshots and Paper attestations."""

    @staticmethod
    def ensure_scope(
        session: Session,
        *,
        changeset: Changeset,
        actor_id: UUID,
    ) -> PaperReviewScope:
        existing = session.scalar(
            select(PaperReviewScope).where(PaperReviewScope.changeset_id == changeset.id)
        )
        if existing is not None:
            if existing.base_release_id != changeset.base_release_id:
                raise AttestationValidationError("Review scope base Release changed")
            return existing
        paper_revision = session.scalar(
            select(ReleaseItem.revision_id)
            .where(
                ReleaseItem.release_id == changeset.base_release_id,
                ReleaseItem.paper_id == changeset.paper_id,
                ReleaseItem.object_id == changeset.paper_id,
                ReleaseItem.object_kind == ObjectKind.PAPER,
            )
            .limit(1)
        )
        if paper_revision is None:
            raise AttestationValidationError("Base release Paper revision is missing")
        release_items = list(
            session.scalars(
                select(ReleaseItem)
                .where(
                    ReleaseItem.release_id == changeset.base_release_id,
                    ReleaseItem.paper_id == changeset.paper_id,
                )
                .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
            )
        )
        rows: list[dict[str, object]] = []
        for item in release_items:
            rows.append(
                {
                    "object_id": str(item.object_id),
                    "revision_id": str(item.revision_id),
                    "object_kind": item.object_kind.value,
                    "required": True,
                    "reason": "base_release_item",
                }
            )
        snapshot: dict[str, object] = {
            "changeset_id": str(changeset.id),
            "paper_id": str(changeset.paper_id),
            "base_release_id": str(changeset.base_release_id),
            "items": rows,
        }
        scope = PaperReviewScope(
            id=uuid4(),
            changeset_id=changeset.id,
            paper_id=changeset.paper_id,
            base_release_id=changeset.base_release_id,
            base_paper_revision_id=paper_revision,
            snapshot=snapshot,
            scope_hash=canonical_content_hash(snapshot),
            item_count=len(rows),
            created_by_id=actor_id,
        )
        session.add(scope)
        session.flush()
        return scope

    @staticmethod
    def _item_revision(
        session: Session,
        *,
        changeset: Changeset,
        object_id: UUID,
        base_revision_id: UUID,
    ) -> ObjectRevision | None:
        item = session.scalar(
            select(ChangesetItem).where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == object_id,
            )
        )
        if item is not None:
            revision_id = item.proposed_revision_id or item.base_revision_id
            if revision_id is not None:
                return session.get(ObjectRevision, revision_id)
        return session.get(ObjectRevision, base_revision_id)

    @classmethod
    def progress(
        cls,
        session: Session,
        *,
        changeset: Changeset,
        scope: PaperReviewScope,
    ) -> ReviewProgress:
        states: list[ObjectCompleteness] = []
        scope_items = scope.snapshot.get("items")
        if not isinstance(scope_items, list):
            raise AttestationValidationError("Review scope items are invalid")
        scope_object_ids: set[UUID] = set()
        for row in scope_items:
            if not isinstance(row, Mapping):
                continue
            try:
                scope_object_ids.add(UUID(str(row["object_id"])))
            except (KeyError, TypeError, ValueError) as error:
                raise AttestationValidationError(
                    "Review scope object reference is invalid"
                ) from error

        manifest = get_release_artifact_manifest(session, changeset.base_release_id)
        frozen_bindings = (
            manifest.snapshot.get("bindings") if manifest is not None else None
        )
        try:
            bindings = merge_binding_snapshots(
                frozen_bindings if isinstance(frozen_bindings, Mapping) else {},
                draft_binding_delta_for_changeset(session, changeset.id),
            )
        except ValueError as error:
            raise AttestationValidationError(
                f"Review scope binding delta is invalid: {error}"
            ) from error

        bound_region_ids: dict[UUID, set[UUID]] = {}
        for binding in bindings.get("visual_object_regions", []):
            if not isinstance(binding, Mapping):
                continue
            try:
                visual_object_id = UUID(str(binding["visual_object_id"]))
                region_id = UUID(str(binding["region_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise AttestationValidationError(
                    "Review scope Region binding is invalid"
                ) from error
            visual = session.get(VisualObject, visual_object_id)
            region = session.get(VisualRegion, region_id)
            if (
                visual is None
                or region is None
                or visual.paper_id != changeset.paper_id
                or region.paper_id != changeset.paper_id
            ):
                raise AttestationValidationError(
                    "Review scope Region binding crosses Paper scope"
                )
            bound_region_ids.setdefault(visual_object_id, set()).add(region_id)

        for row in scope_items:
            if not isinstance(row, Mapping):
                continue
            try:
                object_id = UUID(str(row["object_id"]))
                revision_id = UUID(str(row["revision_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise AttestationValidationError(
                    "Review scope object reference is invalid"
                ) from error
            revision = cls._item_revision(
                session,
                changeset=changeset,
                object_id=object_id,
                base_revision_id=revision_id,
            )
            snapshot = revision.snapshot if revision is not None else {}
            normalized = snapshot.get("normalized_values") if isinstance(snapshot, Mapping) else {}
            normalized = normalized if isinstance(normalized, Mapping) else {}
            blockers = snapshot.get("review_blockers", []) if isinstance(snapshot, Mapping) else []
            if not isinstance(blockers, list):
                blockers = []
            kind = str(row.get("object_kind") or "")
            disposition = revision.proposal_disposition if revision is not None else None
            if kind == ObjectKind.MOLECULE_PROPOSAL.value:
                proposal = session.get(MoleculeProposal, object_id)
                review = snapshot.get("review") if isinstance(snapshot, Mapping) else {}
                review = review if isinstance(review, Mapping) else {}
                resulting_structure_id = review.get("resulting_structure_id") or normalized.get(
                    "resulting_structure_id"
                )
                structure = None
                if resulting_structure_id:
                    try:
                        structure = session.get(
                            Structure,
                            UUID(str(resulting_structure_id)),
                        )
                    except (TypeError, ValueError):
                        structure = None
                visual = (
                    session.get(VisualObject, proposal.visual_object_id)
                    if proposal is not None
                    else None
                )
                source_region = (
                    session.get(VisualRegion, proposal.source_region_id)
                    if proposal is not None and proposal.source_region_id is not None
                    else None
                )
                crop_asset = (
                    session.get(Asset, proposal.crop_asset_id)
                    if proposal is not None and proposal.crop_asset_id is not None
                    else None
                )
                source_asset = (
                    session.get(Asset, source_region.asset_id)
                    if source_region is not None and source_region.asset_id is not None
                    else None
                )
                source_ready = bool(
                    proposal is not None
                    and proposal.paper_id == changeset.paper_id
                    and visual is not None
                    and visual.paper_id == changeset.paper_id
                    and source_region is not None
                    and source_region.paper_id == changeset.paper_id
                    and crop_asset is not None
                    and source_asset is not None
                    and proposal.source_region_id
                    in bound_region_ids.get(proposal.visual_object_id, set())
                )
                structure_ready = bool(
                    disposition in {"rejected", "not_applicable"}
                    or (
                        structure is not None
                        and structure.paper_id == changeset.paper_id
                        and structure.id in scope_object_ids
                    )
                )
                state = assess_object(
                    object_kind=kind,
                    review_blockers=blockers,
                    requires_ocsr=True,
                    proposal_dispositions=[disposition or "pending"],
                    source_ready=source_ready,
                    structure_ready=structure_ready,
                )
            elif kind == ObjectKind.VISUAL_OBJECT.value:
                visual = session.get(VisualObject, object_id)
                localization_blockers = list(blockers)
                if (
                    visual is None
                    or visual.paper_id != changeset.paper_id
                    or not bound_region_ids.get(object_id)
                ):
                    localization_blockers.append("region_binding_missing")
                state = assess_object(
                    object_kind=kind,
                    review_blockers=localization_blockers,
                    requires_ocsr=False,
                    proposal_dispositions=[],
                    source_ready=True,
                    structure_ready=True,
                )
            elif kind == ObjectKind.VISUAL_REGION.value:
                region = session.get(VisualRegion, object_id)
                source_asset = (
                    session.get(Asset, region.asset_id)
                    if region is not None and region.asset_id is not None
                    else None
                )
                state = assess_object(
                    object_kind=kind,
                    review_blockers=blockers,
                    requires_ocsr=False,
                    proposal_dispositions=[],
                    source_ready=bool(
                        region is not None
                        and region.paper_id == changeset.paper_id
                        and source_asset is not None
                        and revision is not None
                        and revision.region_x0 is not None
                        and revision.region_y0 is not None
                        and revision.region_x1 is not None
                        and revision.region_y1 is not None
                    ),
                    structure_ready=True,
                )
            else:
                state = assess_object(
                    object_kind=kind,
                    review_blockers=blockers,
                    requires_ocsr=False,
                    proposal_dispositions=[],
                    source_ready=True,
                    structure_ready=True,
                )
            states.append(state)
        return ReviewProgress(
            item_count=len(states),
            resolved_count=sum(1 for state in states if state.resolved),
            blocker_count=sum(1 for state in states if state.blocking),
            states=tuple(states),
        )

    @classmethod
    def attest(
        cls,
        session: Session,
        *,
        changeset: Changeset,
        actor_id: UUID,
        expected_version: int,
        scope_hash: str,
        statement: str,
    ) -> tuple[PaperReviewScope, PaperReviewAttestation, ReviewProgress]:
        if changeset.version != expected_version:
            raise RevisionConflict(expected_version, changeset.version)
        actor = session.get(User, actor_id)
        if (
            actor_id != changeset.owner_id
            or actor is None
            or not actor.is_enabled
            or actor.role is not UserRole.REVIEWER
        ):
            raise ReviewForbidden(
                "Only the assigned Reviewer with an enabled account can attest this Paper"
            )
        scope = cls.ensure_scope(session, changeset=changeset, actor_id=actor_id)
        if scope.scope_hash.casefold() != scope_hash.casefold():
            raise AttestationValidationError("scope_hash does not match the frozen Paper scope")
        progress = cls.progress(session, changeset=changeset, scope=scope)
        if progress.blocker_count or progress.resolved_count < progress.item_count:
            raise AttestationValidationError(
                "Paper review is incomplete; resolve all required blockers before attesting"
            )
        # Ensure the Paper item is explicitly represented in this changeset and
        # carry a server-owned review_status marker into a new immutable revision.
        paper_item = session.scalar(
            select(ChangesetItem).where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == changeset.paper_id,
            ).with_for_update()
        )
        base_paper = session.get(ObjectRevision, scope.base_paper_revision_id)
        if base_paper is None:
            raise AttestationValidationError("Base Paper revision is missing")
        if paper_item is None:
            latest_sequence = session.scalar(
                select(func.max(ChangesetItem.sequence)).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
            paper_item = ChangesetItem(
                changeset_id=changeset.id,
                paper_id=changeset.paper_id,
                object_id=changeset.paper_id,
                object_kind=ObjectKind.PAPER.value,
                base_revision_id=base_paper.id,
                proposed_snapshot=dict(base_paper.snapshot),
                content_hash=_snapshot_hash(session, base_paper.snapshot),
                sequence=int(latest_sequence or 0) + 1,
            )
            session.add(paper_item)
            session.flush()
        attestation_id = uuid4()
        paper_snapshot = dict(paper_item.proposed_snapshot)
        existing_normalized = paper_snapshot.get("normalized_values")
        paper_normalized = (
            dict(existing_normalized)
            if isinstance(existing_normalized, Mapping)
            else {}
        )
        paper_normalized["review_status"] = "reviewed"
        paper_snapshot["normalized_values"] = paper_normalized
        predecessor = (
            session.get(
                ObjectRevision,
                paper_item.proposed_revision_id or paper_item.base_revision_id,
            )
            or base_paper
        )
        paper_revision = RevisionService().create_revision(
            session,
            object_identity=session.get(RevisionedObject, changeset.paper_id),
            actor_id=actor_id,
            reason="Paper-level review attestation",
            snapshot=paper_snapshot,
            predecessor=predecessor,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
        )
        paper_item.proposed_snapshot = paper_snapshot
        paper_item.proposed_revision_id = paper_revision.id
        paper_item.content_hash = paper_revision.content_hash
        changeset.version += 1
        validation_results = dict(changeset.validation_results or {})
        validation_results["paper_attestation"] = {
            "id": str(attestation_id),
            "scope_id": str(scope.id),
            "scope_hash": scope.scope_hash,
            "changeset_version": changeset.version,
            "item_count": progress.item_count,
            "resolved_count": progress.resolved_count,
            "blocker_count": progress.blocker_count,
            "statement": statement.strip(),
        }
        changeset.validation_results = validation_results
        attestation = PaperReviewAttestation(
            id=attestation_id,
            changeset_id=changeset.id,
            scope_id=scope.id,
            paper_id=changeset.paper_id,
            paper_revision_id=paper_revision.id,
            changeset_version=changeset.version,
            scope_hash=scope.scope_hash,
            reviewer_id=actor_id,
            item_count=progress.item_count,
            resolved_count=progress.resolved_count,
            blocker_count=progress.blocker_count,
            statement=statement.strip(),
        )
        session.add(attestation)
        session.flush()
        return scope, attestation, progress
