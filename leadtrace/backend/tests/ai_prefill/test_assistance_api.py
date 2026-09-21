from pathlib import Path

from app.ai_prefill.assistance_router import create_assistance_router
from app.ai_prefill.assistance_schemas import AssistanceContractResponse
from app.config import Settings


def test_assistance_router_is_preview_only() -> None:
    preview = create_assistance_router(
        Settings(
            environment="preview",
            preview_artifact_root=Path("/tmp/leadtrace-preview-artifacts"),
        )
    )
    production = create_assistance_router(
        Settings(environment="development"),
    )

    assert any(route.path == "/api/v2/admin/ai-prefill/contracts" for route in preview.routes)
    assert production.routes == []


def test_contract_response_declares_candidate_v1_capabilities() -> None:
    response = AssistanceContractResponse(
        envelope_schema={"title": "CandidateEnvelope"},
        profile_version="core-v1",
        validator_version="assistance-validation-v1",
        capabilities=["candidate-import", "candidate-validate", "preview-apply"],
    )

    assert response.profile_version == "core-v1"
    assert "preview-apply" in response.capabilities


def test_candidate_object_limit_counts_structures_and_nested_lineage_items():
    import pytest
    from pydantic import ValidationError
    from app.ai_prefill.assistance_schemas import CandidateCreateRequest
    from app.ai_prefill.contracts import AiPrefillPayload
    from .test_preview_application import make_candidate
    compounds = [{"ref": f"c{index}", "compound_label": str(index), "structure": {"smiles": "CCO"}}
                 for index in range(2500)]
    exact = make_candidate(AiPrefillPayload.model_validate({"schema_version": 1, "compounds": compounds}))
    assert CandidateCreateRequest(candidate=exact).candidate == exact
    payload = {"schema_version": 1, "compounds": compounds,
               "lineages": [{"ref": "lineage:1", "lineage_label": "Series", "members": [{"compound_ref": "c0", "role": "root"}]}]}
    excessive = make_candidate(AiPrefillPayload.model_validate(payload))
    with pytest.raises(ValidationError, match="5000 scientific objects"):
        CandidateCreateRequest(candidate=excessive)


def test_candidate_object_limit_includes_every_lineage_member_and_edge():
    import pytest
    from pydantic import ValidationError
    from app.ai_prefill.assistance_schemas import CandidateCreateRequest
    from app.ai_prefill.contracts import AiPrefillPayload
    from .test_preview_application import make_candidate
    compounds = [{"ref": f"c{index}", "compound_label": str(index), "structure": {"smiles": "CCO"}}
                 for index in range(1666)]
    lineage = {"ref": "lineage:1", "lineage_label": "Series",
               "members": [{"compound_ref": item["ref"], "role": "unspecified"} for item in compounds],
               "edges": [{"ref": "edge:1", "parent_compound_ref": "c0", "child_compound_ref": "c1", "relation_type": "lead_optimization"}]}
    payload = {"schema_version": 1, "compounds": compounds, "lineages": [lineage]}
    exact = make_candidate(AiPrefillPayload.model_validate(payload))
    assert CandidateCreateRequest(candidate=exact).candidate == exact  # 3332 + 1 + 1666 + 1.
    lineage["edges"].append({"ref": "edge:2", "parent_compound_ref": "c1", "child_compound_ref": "c2", "relation_type": "lead_optimization"})
    excessive = make_candidate(AiPrefillPayload.model_validate(payload))
    with pytest.raises(ValidationError, match="5000 scientific objects"):
        CandidateCreateRequest(candidate=excessive)
