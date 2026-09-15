from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import ApprovalDecision
from app.assets.models import Asset
from app.molecule_proposals.models import MoleculeProposal
from app.releases.manifest import validate_changeset_binding_delta
from app.releases.models import ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.reviews.attestations import (
    AttestationValidationError,
    validate_frozen_attestation,
)
from app.reviews.models import Changeset, ChangesetSubmission, PaperReviewScope
from app.reviews.service import ReviewNotFound, ReviewService
from app.security.policies import WorkflowState
from app.users.models import User, UserRole
from app.visual_objects.models import VisualObject, VisualRegion

ApprovalAction = Literal["approve", "request_changes", "reject"]


class ApprovalConflict(RuntimeError):
    """An approval cannot be applied to the requested changeset state."""


class ApprovalForbidden(PermissionError):
    """The actor is not an enabled Admin or is the changeset owner."""


def _clean_reason(reason: str) -> str:
    value = reason.strip()
    if not value:
        raise ValueError("reason is required")
    return value[:4000]


def _safe_asset(asset: Asset | None) -> dict[str, object] | None:
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
        "category": asset.category.value,
        "access_level": asset.access_level.value,
    }


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            name = str(key)
            normalized = name.casefold()
            if (
                normalized
                in {"storage_key", "source_pdf", "crop_path", "source_crop_path"}
                or normalized.endswith("_path")
                or normalized.endswith("_filepath")
            ):
                continue
            result[name] = _safe_value(nested)
        return result
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_safe_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _proposal_disposition(
    revision: ObjectRevision | None,
    snapshot: Mapping[str, object],
) -> str:
    if revision is not None and revision.proposal_disposition:
        return str(revision.proposal_disposition)
    review = snapshot.get("review")
    if isinstance(review, Mapping) and review.get("disposition"):
        return str(review["disposition"])
    normalized = snapshot.get("normalized_values")
    if isinstance(normalized, Mapping) and normalized.get("disposition"):
        return str(normalized["disposition"])
    return "pending"


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    decision: ApprovalDecision
    idempotent: bool = False


class ApprovalService:
    """Persist one immutable decision per submitted snapshot and action."""

    def decide(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        action: ApprovalAction,
        reason: str,
        expected_version: int | None = None,
    ) -> ApprovalResult:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None:
            raise ReviewNotFound("Changeset not found")
        actor = session.get(User, actor_id)
        if actor is None or not actor.is_enabled or actor.role is not UserRole.ADMIN:
            raise ApprovalForbidden("Only an enabled Admin can approve changesets")
        if changeset.owner_id == actor_id:
            raise ApprovalForbidden("A Reviewer cannot approve their own changeset")
        clean_reason = _clean_reason(reason)
        target = {
            "approve": WorkflowState.APPROVED,
            "request_changes": WorkflowState.CHANGES_REQUESTED,
            "reject": WorkflowState.REJECTED,
        }[action]
        submission_version = (
            changeset.version - 1
            if changeset.workflow_state is target
            else changeset.version
        )
        # Retries arrive after the state/version transition, so identify the
        # immutable submission using the pre-transition version.
        existing = session.scalar(
            select(ApprovalDecision).where(
                ApprovalDecision.changeset_id == changeset_id,
                ApprovalDecision.submission_version == submission_version,
                ApprovalDecision.decision == action,
            )
        )
        if existing is not None:
            return ApprovalResult(existing, True)
        if expected_version is not None and expected_version != changeset.version:
            raise ApprovalConflict(
                "Changeset version changed: "
                f"expected {expected_version}, current {changeset.version}"
            )
        if changeset.workflow_state is not WorkflowState.SUBMITTED:
            # Idempotent retries after a state transition are safe only when the
            # matching decision was already persisted.
            raise ApprovalConflict(
                f"Changeset is {changeset.workflow_state.value}, expected submitted"
            )
        snapshot = dict(changeset.submitted_snapshot or {})
        snapshot_hash = changeset.submitted_content_hash or ""
        if action == "approve":
            try:
                validate_frozen_attestation(session, changeset=changeset)
            except AttestationValidationError as error:
                raise ApprovalConflict(
                    f"Paper attestation is invalid: {error}"
                ) from error
            binding_delta = snapshot.get("binding_delta")
            if not isinstance(binding_delta, Mapping):
                raise ApprovalConflict("Binding delta is absent from the submitted snapshot")
            try:
                validate_changeset_binding_delta(
                    session,
                    changeset,
                    delta=binding_delta,
                )
            except ValueError as error:
                raise ApprovalConflict(f"Binding delta is invalid: {error}") from error
        ReviewService().transition_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=actor_id,
            expected_version=changeset.version,
            next_state=target,
        )
        decision = ApprovalDecision(
            changeset_id=changeset.id,
            submission_version=submission_version,
            decision=action,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
        )
        session.add(decision)
        session.flush()
        return ApprovalResult(decision, False)

    def approve(self, session: Session, **kwargs: object) -> ApprovalResult:
        return self.decide(session, action="approve", **kwargs)  # type: ignore[arg-type]

    def request_changes(self, session: Session, **kwargs: object) -> ApprovalResult:
        return self.decide(session, action="request_changes", **kwargs)  # type: ignore[arg-type]

    def reject(self, session: Session, **kwargs: object) -> ApprovalResult:
        return self.decide(session, action="reject", **kwargs)  # type: ignore[arg-type]

    @staticmethod
    def scientific_evidence(
        session: Session,
        changeset_id: UUID,
        *,
        changed_only: bool = True,
    ) -> dict[str, object]:
        changeset = session.get(Changeset, changeset_id)
        if changeset is None:
            raise ReviewNotFound("Changeset not found")
        submitted = changeset.submitted_snapshot
        if not isinstance(submitted, Mapping):
            raise ApprovalConflict("Changeset does not have a frozen submission")
        snapshot_hash = changeset.submitted_content_hash
        if snapshot_hash is None:
            raise ApprovalConflict("Changeset submission hash is invalid")
        submission_version = session.scalar(
            select(ChangesetSubmission.changeset_version)
            .where(
                ChangesetSubmission.changeset_id == changeset.id,
                ChangesetSubmission.content_hash == snapshot_hash,
            )
            .order_by(ChangesetSubmission.submission_number.desc())
            .limit(1)
        )
        if submission_version is None:
            raise ApprovalConflict("Changeset submission record is missing")
        submitted_items = submitted.get("items")
        if not isinstance(submitted_items, list):
            raise ApprovalConflict("Changeset submission items are invalid")

        after_by_kind: dict[str, list[tuple[UUID, dict[str, object]]]] = {
            ObjectKind.STRUCTURE.value: [],
            ObjectKind.VISUAL_REGION.value: [],
            ObjectKind.VISUAL_OBJECT.value: [],
            ObjectKind.MOLECULE_PROPOSAL.value: [],
        }
        submitted_revision_ids: dict[UUID, UUID] = {}
        for item in submitted_items:
            if not isinstance(item, Mapping):
                continue
            object_kind = str(item.get("object_kind") or "")
            if object_kind not in after_by_kind:
                continue
            proposed = item.get("proposed_snapshot")
            if not isinstance(proposed, Mapping):
                raise ApprovalConflict("Scientific submission snapshot is invalid")
            try:
                object_id = UUID(str(item["object_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ApprovalConflict("Scientific submission object ID is invalid") from error
            after_by_kind[object_kind].append((object_id, dict(proposed)))
            proposed_revision_id = item.get("proposed_revision_id")
            if proposed_revision_id is not None:
                try:
                    submitted_revision_ids[object_id] = UUID(
                        str(proposed_revision_id)
                    )
                except (TypeError, ValueError) as error:
                    raise ApprovalConflict(
                        "Scientific submission revision ID is invalid"
                    ) from error

        region_ids = {
            object_id
            for object_id, _ in after_by_kind[ObjectKind.VISUAL_REGION.value]
        }
        binding_delta = submitted.get("binding_delta")
        region_bindings = (
            binding_delta.get("visual_object_regions")
            if isinstance(binding_delta, Mapping)
            else None
        )
        if isinstance(region_bindings, list):
            for row in region_bindings:
                if not isinstance(row, Mapping) or row.get("region_id") is None:
                    continue
                try:
                    region_ids.add(UUID(str(row["region_id"])))
                except (TypeError, ValueError) as error:
                    raise ApprovalConflict(
                        "Scientific Region binding is invalid"
                    ) from error

        target_ids = {
            object_id
            for entries in after_by_kind.values()
            for object_id, _ in entries
        } | region_ids
        release_items = list(
            session.scalars(
                select(ReleaseItem).where(
                    ReleaseItem.release_id == changeset.base_release_id,
                    ReleaseItem.object_id.in_(target_ids),
                )
            )
        ) if target_ids else []
        before_by_id: dict[UUID, dict[str, object]] = {}
        before_revision_by_id: dict[UUID, ObjectRevision] = {}
        for release_item in release_items:
            revision = session.get(ObjectRevision, release_item.revision_id)
            if revision is None:
                raise ApprovalConflict("Base release evidence revision is missing")
            before_by_id[release_item.object_id] = dict(revision.snapshot)
            before_revision_by_id[release_item.object_id] = revision

        after_revision_by_id: dict[UUID, ObjectRevision] = {}
        for object_id, revision_id in submitted_revision_ids.items():
            revision = session.get(ObjectRevision, revision_id)
            if revision is None or revision.object_id != object_id:
                raise ApprovalConflict("Frozen scientific revision is invalid")
            after_revision_by_id[object_id] = revision

        def evidence_rows(kind: ObjectKind) -> list[dict[str, object]]:
            rows: list[dict[str, object]] = []
            for object_id, after in after_by_kind[kind.value]:
                before = before_by_id.get(object_id, {})
                if changed_only and before == after:
                    continue
                rows.append(
                    {
                        "object_id": str(object_id),
                        "before": _safe_value(before),
                        "after": _safe_value(after),
                    }
                )
            return rows

        structures = evidence_rows(ObjectKind.STRUCTURE)
        visual_objects = evidence_rows(ObjectKind.VISUAL_OBJECT)
        molecule_proposals = evidence_rows(ObjectKind.MOLECULE_PROPOSAL)
        proposal_by_id = {
            object_id: after
            for object_id, after in after_by_kind[
                ObjectKind.MOLECULE_PROPOSAL.value
            ]
        }
        for row in molecule_proposals:
            object_id = UUID(str(row["object_id"]))
            row["before_disposition"] = _proposal_disposition(
                before_revision_by_id.get(object_id),
                row["before"],
            )
            row["after_disposition"] = _proposal_disposition(
                after_revision_by_id.get(object_id),
                row["after"],
            )
        submitted_regions = {
            object_id: after
            for object_id, after in after_by_kind[ObjectKind.VISUAL_REGION.value]
        }
        ordered_region_ids = list(submitted_regions)
        ordered_region_ids.extend(
            sorted(region_ids - submitted_regions.keys(), key=str)
        )
        regions: list[dict[str, object]] = []
        for object_id in ordered_region_ids:
            before = before_by_id.get(object_id)
            after = submitted_regions.get(object_id, before)
            if after is None:
                raise ApprovalConflict(
                    "Region evidence is absent from the frozen base release"
                )
            regions.append(
                {
                    "object_id": str(object_id),
                    "before": _safe_value(before or {}),
                    "after": _safe_value(after),
                }
            )

        source_context: list[dict[str, object]] = []
        visible_proposal_ids = {
            UUID(str(row["object_id"])) for row in molecule_proposals
        }
        if not changed_only:
            visible_proposal_ids.update(proposal_by_id)
        for proposal_id in sorted(visible_proposal_ids, key=str):
            proposal = session.get(MoleculeProposal, proposal_id)
            if proposal is None or proposal.paper_id != changeset.paper_id:
                raise ApprovalConflict("Molecule proposal crosses Paper scope")
            visual = session.get(VisualObject, proposal.visual_object_id)
            region = (
                session.get(VisualRegion, proposal.source_region_id)
                if proposal.source_region_id is not None
                else None
            )
            if (
                visual is None
                or visual.paper_id != changeset.paper_id
                or region is None
                or region.paper_id != changeset.paper_id
            ):
                raise ApprovalConflict("Proposal source context crosses Paper scope")
            region_revision = after_revision_by_id.get(region.id) or before_revision_by_id.get(
                region.id
            )
            if region_revision is None:
                region_item = session.scalar(
                    select(ReleaseItem).where(
                        ReleaseItem.release_id == changeset.base_release_id,
                        ReleaseItem.paper_id == changeset.paper_id,
                        ReleaseItem.object_id == region.id,
                    )
                )
                region_revision = (
                    session.get(ObjectRevision, region_item.revision_id)
                    if region_item is not None
                    else None
                )
            if region_revision is None:
                raise ApprovalConflict("Proposal source Region revision is missing")
            crop_asset = (
                session.get(Asset, proposal.crop_asset_id)
                if proposal.crop_asset_id is not None
                else None
            )
            source_asset = (
                session.get(Asset, region.asset_id)
                if region.asset_id is not None
                else None
            )
            source_context.append(
                {
                    "proposal_id": str(proposal.id),
                    "visual_object_id": str(visual.id),
                    "region": {
                        "id": str(region.id),
                        "page_number": region.page_number,
                        "bounds": {
                            "x0": region_revision.region_x0,
                            "y0": region_revision.region_y0,
                            "x1": region_revision.region_x1,
                            "y1": region_revision.region_y1,
                        },
                        "rotation": region_revision.region_rotation or 0,
                    },
                    "crop_asset": _safe_asset(crop_asset),
                    "source_asset": _safe_asset(source_asset),
                }
            )

        scope = session.scalar(
            select(PaperReviewScope).where(
                PaperReviewScope.changeset_id == changeset.id
            )
        )
        attestation = None
        progress = None
        scope_payload = None
        if scope is not None:
            try:
                attestation = validate_frozen_attestation(
                    session,
                    changeset=changeset,
                )
            except AttestationValidationError as error:
                raise ApprovalConflict(
                    f"Paper attestation is invalid: {error}"
                ) from error
            if attestation is None:
                raise ApprovalConflict("Frozen Paper attestation is missing")
            scope_payload = {
                "id": str(scope.id),
                "scope_hash": scope.scope_hash,
                "item_count": scope.item_count,
            }
            progress = {
                "scope_count": attestation.item_count,
                "resolved_count": attestation.resolved_count,
                "blocker_count": attestation.blocker_count,
            }
        return {
            "changeset_id": str(changeset.id),
            "base_release_id": str(changeset.base_release_id),
            "submission_version": submission_version,
            "snapshot_hash": snapshot_hash,
            "structures": structures,
            "regions": regions,
            "visual_objects": visual_objects,
            "molecule_proposals": molecule_proposals,
            "source_context": source_context,
            "scope": scope_payload,
            "attestation": (
                {
                    "id": str(attestation.id),
                    "paper_revision_id": str(attestation.paper_revision_id),
                    "reviewer_id": str(attestation.reviewer_id),
                    "changeset_version": attestation.changeset_version,
                    "scope_hash": attestation.scope_hash,
                    "item_count": attestation.item_count,
                    "resolved_count": attestation.resolved_count,
                    "blocker_count": attestation.blocker_count,
                    "statement": attestation.statement,
                }
                if attestation is not None
                else None
            ),
            "progress": progress,
        }

    @staticmethod
    def list_decisions(
        session: Session,
        *,
        changeset_id: UUID | None = None,
    ) -> list[ApprovalDecision]:
        statement = select(ApprovalDecision).order_by(
            ApprovalDecision.created_at.desc(), ApprovalDecision.id
        )
        if changeset_id is not None:
            statement = statement.where(ApprovalDecision.changeset_id == changeset_id)
        return list(session.scalars(statement))
