from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.chemistry.validation import SourceComparison, validate_structure
from app.compounds.models import Compound
from app.molecule_proposals.models import MoleculeProposal, MoleculeProposalDisposition
from app.revisions.models import ObjectRevision, RevisionedObject
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ChangesetItem
from app.reviews.service import ReviewForbidden, ReviewNotFound, ReviewService, RevisionConflict
from app.reviews.state_machine import content_mutable
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.visual_objects.models import VisualObject, VisualRegion


class MoleculeProposalValidationError(ValueError):
    """Raised when a proposal decision is scientifically or structurally invalid."""


class MoleculeProposalVersionConflict(RevisionConflict):
    """Raised when the containing review changeset is stale."""


def _snapshot_hash(session: Session, snapshot: Mapping[str, object]) -> str:
    value = session.scalar(select(func.leadtrace_jsonb_sha256(cast(dict(snapshot), JSONB))))
    return str(value)


def _text(value: str | None, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise MoleculeProposalValidationError(f"{field} is required")
        return None
    clean = value.strip()
    if required and not clean:
        raise MoleculeProposalValidationError(f"{field} is required")
    return clean or None


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


class MoleculeProposalReviewService:
    """Typed read/write facade for immutable OCSR proposal evidence."""

    def _editable_changeset(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        expected_version: int,
        paper_id: UUID,
        actor_id: UUID,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None or changeset.paper_id != paper_id:
            raise ReviewNotFound("Changeset not found")
        try:
            ReviewService()._authorize_owner_or_admin(session, changeset, actor_id)
        except ReviewForbidden:
            raise
        if changeset.version != expected_version:
            raise MoleculeProposalVersionConflict(expected_version, changeset.version)
        if not content_mutable(changeset.workflow_state):
            raise MoleculeProposalValidationError(
                "Only editable draft changesets can contain proposal decisions"
            )
        return changeset

    @staticmethod
    def _latest_revision(session: Session, proposal_id: UUID, *, lock: bool = False) -> ObjectRevision:
        statement = (
            select(ObjectRevision)
            .where(ObjectRevision.object_id == proposal_id)
            .order_by(ObjectRevision.revision_number.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        revision = session.scalar(statement)
        if revision is None:
            raise MoleculeProposalValidationError("Molecule proposal has no revision")
        return revision

    @staticmethod
    def _ensure_same_paper_references(
        session: Session,
        *,
        paper_id: UUID,
        compound_id: UUID | None,
        resulting_structure_id: UUID | None,
    ) -> tuple[Compound | None, Structure | None]:
        compound = session.get(Compound, compound_id) if compound_id else None
        if compound_id is not None and (compound is None or compound.paper_id != paper_id):
            raise MoleculeProposalValidationError("Compound does not belong to this Paper")
        structure = session.get(Structure, resulting_structure_id) if resulting_structure_id else None
        if resulting_structure_id is not None and (
            structure is None or structure.paper_id != paper_id
        ):
            raise MoleculeProposalValidationError(
                "Resulting structure does not belong to this Paper"
            )
        if structure is not None and compound is not None and structure.compound_id != compound.id:
            raise MoleculeProposalValidationError(
                "Resulting structure does not belong to the selected Compound"
            )
        return compound, structure

    @staticmethod
    def _review_values(
        revision: ObjectRevision,
    ) -> dict[str, object]:
        normalized = _mapping(revision.snapshot.get("normalized_values"))
        review = _mapping(revision.snapshot.get("review"))
        values: dict[str, object] = {}
        for key in (
            "reviewed_smiles",
            "selected_component_smiles",
            "compound_id",
            "resulting_structure_id",
            "rationale",
            "source_comparison",
            "source_verified",
        ):
            if key in review:
                values[key] = review[key]
            elif key in normalized:
                values[key] = normalized[key]
        values.setdefault("disposition", revision.proposal_disposition or MoleculeProposalDisposition.PENDING.value)
        return values

    @staticmethod
    def _merge_snapshot(
        base: ObjectRevision,
        *,
        disposition: MoleculeProposalDisposition,
        reviewed_smiles: str | None,
        selected_component_smiles: str | None,
        compound_id: UUID | None,
        resulting_structure_id: UUID | None,
        rationale: str | None,
        source_comparison: SourceComparison,
        source_verified: bool,
    ) -> dict[str, object]:
        snapshot = dict(base.snapshot)
        normalized = _mapping(snapshot.get("normalized_values"))
        review = _mapping(snapshot.get("review"))
        review.update(
            {
                "disposition": disposition.value,
                "reviewed_smiles": reviewed_smiles,
                "selected_component_smiles": selected_component_smiles,
                "compound_id": str(compound_id) if compound_id else None,
                "resulting_structure_id": str(resulting_structure_id)
                if resulting_structure_id
                else None,
                "rationale": rationale,
                "source_comparison": source_comparison.value,
                "source_verified": source_verified,
            }
        )
        # Keep a flat normalized projection for exports and existing diff/UI
        # consumers, while preserving raw machine fields byte-for-byte.
        normalized.update(review)
        snapshot["normalized_values"] = normalized
        snapshot["review"] = review
        return snapshot

    def validate_update(
        self,
        session: Session,
        *,
        paper_id: UUID,
        disposition: MoleculeProposalDisposition,
        reviewed_smiles: str | None,
        selected_component_smiles: str | None,
        compound_id: UUID | None,
        resulting_structure_id: UUID | None,
        rationale: str | None,
        source_comparison: SourceComparison,
        source_verified: bool,
        machine_snapshot: Mapping[str, object],
    ) -> tuple[dict[str, object], object | None, Compound | None, Structure | None]:
        reviewed_smiles = _text(reviewed_smiles, "reviewed_smiles")
        selected_component_smiles = _text(
            selected_component_smiles, "selected_component_smiles"
        )
        rationale = _text(rationale, "rationale")
        if disposition in {
            MoleculeProposalDisposition.REJECTED,
            MoleculeProposalDisposition.NOT_APPLICABLE,
        } and not rationale:
            raise MoleculeProposalValidationError(
                "rationale is required when a proposal is rejected or not applicable"
            )
        compound, structure = self._ensure_same_paper_references(
            session,
            paper_id=paper_id,
            compound_id=compound_id,
            resulting_structure_id=resulting_structure_id,
        )
        validation = None
        if disposition in {
            MoleculeProposalDisposition.ACCEPTED,
            MoleculeProposalDisposition.CORRECTED,
        }:
            if not reviewed_smiles:
                raise MoleculeProposalValidationError(
                    "reviewed_smiles is required when a proposal is accepted or corrected"
                )
            if compound is None and structure is None:
                raise MoleculeProposalValidationError(
                    "accepted or corrected proposals must reference a Compound or Structure"
                )
            validation = validate_structure(
                reviewed_smiles,
                selected_component_smiles=selected_component_smiles,
                source_comparison=source_comparison,
                source_verified=source_verified,
                human_confirmed=False,
            )
            if not validation.parseable:
                raise MoleculeProposalValidationError(
                    "reviewed_smiles must be a parseable structure"
                )
        return {
            "reviewed_smiles": reviewed_smiles,
            "selected_component_smiles": selected_component_smiles,
            "rationale": rationale,
            "source_comparison": source_comparison.value,
            "source_verified": source_verified,
        }, validation, compound, structure

    def update(
        self,
        session: Session,
        *,
        paper_id: UUID,
        proposal_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        disposition: MoleculeProposalDisposition,
        reviewed_smiles: str | None = None,
        selected_component_smiles: str | None = None,
        compound_id: UUID | None = None,
        resulting_structure_id: UUID | None = None,
        rationale: str | None = None,
        source_comparison: SourceComparison = SourceComparison.NOT_COMPARED,
        source_verified: bool = False,
    ) -> tuple[MoleculeProposal, ObjectRevision, Changeset]:
        proposal = session.scalar(
            select(MoleculeProposal)
            .where(MoleculeProposal.id == proposal_id, MoleculeProposal.paper_id == paper_id)
            .with_for_update()
        )
        if proposal is None:
            raise ReviewNotFound("Molecule proposal not found")
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=paper_id,
            actor_id=actor_id,
        )
        predecessor = self._latest_revision(session, proposal.id, lock=True)
        self.validate_update(
            session,
            paper_id=paper_id,
            disposition=disposition,
            reviewed_smiles=reviewed_smiles,
            selected_component_smiles=selected_component_smiles,
            compound_id=compound_id,
            resulting_structure_id=resulting_structure_id,
            rationale=rationale,
            source_comparison=source_comparison,
            source_verified=source_verified,
            machine_snapshot=predecessor.snapshot,
        )
        snapshot = self._merge_snapshot(
            predecessor,
            disposition=disposition,
            reviewed_smiles=_text(reviewed_smiles, "reviewed_smiles"),
            selected_component_smiles=_text(selected_component_smiles, "selected_component_smiles"),
            compound_id=compound_id,
            resulting_structure_id=resulting_structure_id,
            rationale=_text(rationale, "rationale"),
            source_comparison=source_comparison,
            source_verified=source_verified,
        )
        item = session.scalar(
            select(ChangesetItem)
            .where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == proposal.id,
            )
            .with_for_update()
        )
        if item is None:
            latest_sequence = session.scalar(
                select(func.max(ChangesetItem.sequence)).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
            item = ChangesetItem(
                changeset_id=changeset.id,
                paper_id=paper_id,
                object_id=proposal.id,
                object_kind="molecule_proposal",
                base_revision_id=predecessor.id,
                proposed_snapshot=snapshot,
                content_hash=_snapshot_hash(session, snapshot),
                sequence=int(latest_sequence or 0) + 1,
            )
            session.add(item)
            session.flush()
        revision = RevisionService().create_revision(
            session,
            object_identity=proposal,
            actor_id=actor_id,
            reason=_text(rationale, "rationale") or "Review molecule proposal",
            snapshot=snapshot,
            predecessor=predecessor,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
            canonical_smiles=(
                validate_structure(
                    _text(reviewed_smiles, "reviewed_smiles") or "",
                    selected_component_smiles=_text(
                        selected_component_smiles, "selected_component_smiles"
                    ),
                    source_comparison=source_comparison,
                    source_verified=source_verified,
                ).canonical_isomeric_smiles
                if disposition
                in {
                    MoleculeProposalDisposition.ACCEPTED,
                    MoleculeProposalDisposition.CORRECTED,
                }
                else None
            ),
            proposal_disposition=disposition.value,
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        changeset.version += 1
        session.flush()
        return proposal, revision, changeset


# Short alias retained for callers that prefer the domain name.
ProposalReviewService = MoleculeProposalReviewService

