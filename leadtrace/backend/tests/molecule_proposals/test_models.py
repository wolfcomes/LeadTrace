from __future__ import annotations

from sqlalchemy import event
from uuid import uuid4

from app.molecule_proposals.models import (
    MoleculeProposal,
    MoleculeProposalDisposition,
)
from app.revisions.models import ObjectKind, ObjectRevision
from app.reviews.models import PaperReviewAttestation, PaperReviewScope
from app.releases.aggregate import _MODEL_BY_KIND as AGGREGATE_MODELS
from app.releases.manifest import extract_asset_ids
from app.releases.service import _BASELINE_KIND_SPECS
from app.releases.validation import _MODEL_BY_KIND as VALIDATION_MODELS


def test_molecule_proposal_is_a_revisioned_object_kind() -> None:
    assert ObjectKind.MOLECULE_PROPOSAL.value == "molecule_proposal"
    assert MoleculeProposal.__mapper_args__["polymorphic_identity"] is (
        ObjectKind.MOLECULE_PROPOSAL
    )
    assert MoleculeProposalDisposition.PENDING.value == "pending"
    assert MoleculeProposalDisposition.NOT_APPLICABLE.value == "not_applicable"


def test_proposal_disposition_is_a_dedicated_revision_column() -> None:
    column = ObjectRevision.__table__.c.proposal_disposition

    assert column.nullable is True
    assert column.type.length == 24


def test_review_scope_and_attestation_are_orm_append_only() -> None:
    for model in (PaperReviewScope, PaperReviewAttestation):
        assert event.contains(model, "before_update", model.reject_mutation)
        assert event.contains(model, "before_delete", model.reject_mutation)


def test_release_services_recognize_molecule_proposals() -> None:
    assert AGGREGATE_MODELS[ObjectKind.MOLECULE_PROPOSAL] is MoleculeProposal
    assert VALIDATION_MODELS[ObjectKind.MOLECULE_PROPOSAL] is MoleculeProposal
    assert any(
        kind is ObjectKind.MOLECULE_PROPOSAL and model is MoleculeProposal
        for kind, model, _ in _BASELINE_KIND_SPECS
    )


def test_release_manifest_finds_proposal_crop_assets() -> None:
    asset_id = uuid4()

    assert extract_asset_ids({"crop_asset_id": str(asset_id)}) == {asset_id}
