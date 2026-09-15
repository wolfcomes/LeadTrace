from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import ApprovalDecision
from app.releases.manifest import validate_changeset_binding_delta
from app.releases.models import ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.reviews.models import Changeset, ChangesetSubmission
from app.reviews.attestations import (
    AttestationValidationError,
    validate_frozen_attestation,
)
from app.reviews.service import ReviewNotFound, ReviewService
from app.security.policies import WorkflowState
from app.users.models import User, UserRole

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
                f"Changeset version changed: expected {expected_version}, current {changeset.version}"
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
        }
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
        for release_item in release_items:
            revision = session.get(ObjectRevision, release_item.revision_id)
            if revision is None:
                raise ApprovalConflict("Base release evidence revision is missing")
            before_by_id[release_item.object_id] = dict(revision.snapshot)

        structures = [
            {
                "object_id": str(object_id),
                "before": before_by_id.get(object_id, {}),
                "after": after,
            }
            for object_id, after in after_by_kind[ObjectKind.STRUCTURE.value]
        ]
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
                    "before": before or {},
                    "after": after,
                }
            )
        return {
            "changeset_id": str(changeset.id),
            "base_release_id": str(changeset.base_release_id),
            "submission_version": submission_version,
            "snapshot_hash": snapshot_hash,
            "structures": structures,
            "regions": regions,
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
