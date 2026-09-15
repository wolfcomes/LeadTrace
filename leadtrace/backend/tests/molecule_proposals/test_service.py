from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.chemistry.validation import SourceComparison
from app.molecule_proposals.models import MoleculeProposalDisposition
from app.molecule_proposals.schemas import MoleculeProposalUpdateRequest


def test_proposal_update_schema_forbids_machine_fields() -> None:
    with pytest.raises(ValidationError):
        MoleculeProposalUpdateRequest(
            changeset_id=uuid4(),
            expected_version=1,
            disposition=MoleculeProposalDisposition.ACCEPTED,
            raw_smiles="CCO",
        )


def test_proposal_update_schema_accepts_typed_reviewer_fields() -> None:
    payload = MoleculeProposalUpdateRequest(
        changeset_id=uuid4(),
        expected_version=1,
        disposition=MoleculeProposalDisposition.CORRECTED,
        reviewed_smiles="CCO",
        compound_id=uuid4(),
        source_comparison=SourceComparison.MATCH,
        source_verified=True,
    )
    assert payload.reviewed_smiles == "CCO"
    assert payload.source_comparison is SourceComparison.MATCH
