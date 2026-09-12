from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compounds.models import Compound, normalize_local_label
from app.revisions.models import ObjectRevision
from app.science.common import (
    ScientificVersionConflict,
    create_draft_revision,
    editable_changeset,
    ensure_changeset_item,
    latest_revision,
)


class CompoundValidationError(ValueError):
    """Raised when a Paper-local compound label is invalid."""


@dataclass(frozen=True, slots=True)
class CompoundDraft:
    local_identity: str
    display_label: str
    reason: str


def validate_compound_draft(draft: CompoundDraft) -> CompoundDraft:
    try:
        local_identity = normalize_local_label(draft.local_identity)
    except ValueError as error:
        raise CompoundValidationError(str(error)) from error
    display_label = draft.display_label.strip()
    reason = draft.reason.strip()
    if not display_label or not reason:
        raise CompoundValidationError("display_label and reason are required")
    if len(local_identity) > 255 or len(display_label) > 255:
        raise CompoundValidationError("Compound labels must be at most 255 characters")
    return CompoundDraft(local_identity, display_label, reason)


class CompoundVersionConflict(ScientificVersionConflict):
    pass


class CompoundReviewService:
    """Persist Paper-local compound edits as immutable draft revisions."""

    @staticmethod
    def _snapshot(compound: Compound, draft: CompoundDraft) -> dict[str, object]:
        return {
            "local_identity": draft.local_identity,
            "display_label": draft.display_label,
            "normalized_label": draft.local_identity,
            "paper_id": str(compound.paper_id),
        }

    def create_compound(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: CompoundDraft,
    ) -> tuple[Compound, ObjectRevision]:
        clean = validate_compound_draft(draft)
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=paper_id,
            conflict_type=CompoundVersionConflict,
        )
        duplicate = session.scalar(
            select(Compound.id).where(
                Compound.paper_id == paper_id,
                Compound.local_identity == clean.local_identity,
            )
        )
        if duplicate is not None:
            raise CompoundValidationError("local_identity already exists for this Paper")
        compound = Compound(
            paper_id=paper_id,
            local_identity=clean.local_identity,
            display_label=clean.display_label,
            normalized_label=clean.local_identity,
        )
        session.add(compound)
        session.flush()
        snapshot = self._snapshot(compound, clean)
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=compound.id,
            object_kind="compound",
            snapshot=snapshot,
            base_revision_id=None,
        )
        revision = create_draft_revision(
            session,
            object_identity=compound,
            actor_id=actor_id,
            reason=clean.reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=None,
        )
        item.proposed_revision_id = revision.id
        session.flush()
        return compound, revision

    def update_compound(
        self,
        session: Session,
        *,
        compound_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: CompoundDraft,
    ) -> ObjectRevision:
        compound = session.scalar(
            select(Compound).where(Compound.id == compound_id).with_for_update()
        )
        if compound is None:
            raise CompoundValidationError("Compound not found")
        clean = validate_compound_draft(draft)
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=compound.paper_id,
            conflict_type=CompoundVersionConflict,
        )
        duplicate = session.scalar(
            select(Compound.id).where(
                Compound.paper_id == compound.paper_id,
                Compound.local_identity == clean.local_identity,
                Compound.id != compound.id,
            )
        )
        if duplicate is not None:
            raise CompoundValidationError("local_identity already exists for this Paper")
        previous = latest_revision(session, compound.id, for_update=True)
        if previous is None:
            raise CompoundValidationError("Compound has no revision")
        snapshot = self._snapshot(compound, clean)
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=compound.id,
            object_kind="compound",
            snapshot=previous.snapshot,
            base_revision_id=previous.id,
        )
        revision = create_draft_revision(
            session,
            object_identity=compound,
            actor_id=actor_id,
            reason=clean.reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=previous,
        )
        compound.local_identity = clean.local_identity
        compound.display_label = clean.display_label
        compound.normalized_label = clean.local_identity
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision
