from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.revisions.models import EvidenceState, ObjectRevision
from app.science.common import (
    ScientificVersionConflict,
    create_draft_revision,
    editable_changeset,
    ensure_changeset_item,
    latest_revision,
)


class EvidenceValidationError(ValueError):
    """Raised when evidence cannot be safely represented."""


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    evidence_key: str
    original_text: str
    source_locator: str
    compound_ids: tuple[UUID, ...] = ()


def validate_evidence_draft(draft: EvidenceDraft) -> EvidenceDraft:
    key = draft.evidence_key.strip()
    text = draft.original_text.strip()
    locator = draft.source_locator.strip()
    if not key or not text or not locator:
        raise EvidenceValidationError("evidence_key, original_text, and source_locator are required")
    if len(set(draft.compound_ids)) != len(draft.compound_ids):
        raise EvidenceValidationError("Evidence compound references must be unique")
    return EvidenceDraft(key, text, locator, tuple(draft.compound_ids))


class EvidenceVersionConflict(ScientificVersionConflict):
    pass


class EvidenceReviewService:
    def create_evidence(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: EvidenceDraft,
        reason: str,
    ) -> tuple[Evidence, ObjectRevision]:
        clean = validate_evidence_draft(draft)
        reason = reason.strip()
        if not reason:
            raise EvidenceValidationError("reason is required")
        compounds = session.scalars(select(Compound).where(Compound.id.in_(clean.compound_ids))).all()
        if len(compounds) != len(clean.compound_ids) or any(item.paper_id != paper_id for item in compounds):
            raise EvidenceValidationError("Evidence compounds must belong to this Paper")
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=paper_id,
            conflict_type=EvidenceVersionConflict,
        )
        if session.scalar(
            select(Evidence.id).where(Evidence.paper_id == paper_id, Evidence.evidence_key == clean.evidence_key)
        ) is not None:
            raise EvidenceValidationError("evidence_key already exists for this Paper")
        evidence = Evidence(paper_id=paper_id, evidence_key=clean.evidence_key)
        session.add(evidence)
        session.flush()
        snapshot = {
            "evidence_key": clean.evidence_key,
            "original_text": clean.original_text,
            "source_locator": clean.source_locator,
            "compound_ids": [str(item) for item in clean.compound_ids],
        }
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=evidence.id,
            object_kind="evidence",
            snapshot=snapshot,
            base_revision_id=None,
        )
        revision = create_draft_revision(
            session,
            object_identity=evidence,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=None,
            evidence_state=EvidenceState.SOURCE_BOUND,
            evidence_text=clean.original_text,
            search_text=f"{clean.original_text} {clean.source_locator}",
        )
        item.proposed_revision_id = revision.id
        session.flush()
        return evidence, revision

    def update_evidence(
        self,
        session: Session,
        *,
        evidence_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: EvidenceDraft,
        reason: str,
    ) -> ObjectRevision:
        evidence = session.scalar(select(Evidence).where(Evidence.id == evidence_id).with_for_update())
        if evidence is None:
            raise EvidenceValidationError("Evidence not found")
        clean = validate_evidence_draft(draft)
        reason = reason.strip()
        if not reason:
            raise EvidenceValidationError("reason is required")
        if clean.evidence_key != evidence.evidence_key:
            raise EvidenceValidationError("evidence_key is immutable")
        compounds = session.scalars(select(Compound).where(Compound.id.in_(clean.compound_ids))).all()
        if len(compounds) != len(clean.compound_ids) or any(item.paper_id != evidence.paper_id for item in compounds):
            raise EvidenceValidationError("Evidence compounds must belong to this Paper")
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=evidence.paper_id,
            conflict_type=EvidenceVersionConflict,
        )
        previous = latest_revision(session, evidence.id, for_update=True)
        if previous is None:
            raise EvidenceValidationError("Evidence has no revision")
        if previous.is_tombstone:
            raise EvidenceValidationError("Evidence is deleted")
        snapshot = {
            "evidence_key": evidence.evidence_key,
            "original_text": clean.original_text,
            "source_locator": clean.source_locator,
            "compound_ids": [str(item) for item in clean.compound_ids],
        }
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=evidence.id,
            object_kind="evidence",
            snapshot=previous.snapshot,
            base_revision_id=previous.id,
        )
        revision = create_draft_revision(
            session,
            object_identity=evidence,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=previous,
            evidence_state=EvidenceState.SOURCE_BOUND,
            evidence_text=clean.original_text,
            search_text=f"{clean.original_text} {clean.source_locator}",
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision

    def delete_evidence(
        self,
        session: Session,
        *,
        evidence_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        reason: str,
    ) -> ObjectRevision:
        evidence = session.scalar(
            select(Evidence).where(Evidence.id == evidence_id).with_for_update()
        )
        if evidence is None:
            raise EvidenceValidationError("Evidence not found")
        clean_reason = reason.strip()
        if not clean_reason:
            raise EvidenceValidationError("reason is required")
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=evidence.paper_id,
            conflict_type=EvidenceVersionConflict,
        )
        previous = latest_revision(session, evidence.id, for_update=True)
        if previous is None:
            raise EvidenceValidationError("Evidence has no revision")
        if previous.is_tombstone:
            raise EvidenceValidationError("Evidence is already deleted")
        snapshot = dict(previous.snapshot)
        snapshot["deleted"] = True
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=evidence.id,
            object_kind="evidence",
            snapshot=previous.snapshot,
            base_revision_id=previous.id,
        )
        revision = create_draft_revision(
            session,
            object_identity=evidence,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=previous,
            evidence_state=EvidenceState.REJECTED,
            evidence_text=previous.evidence_text,
            search_text=previous.search_text,
            is_tombstone=True,
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision
