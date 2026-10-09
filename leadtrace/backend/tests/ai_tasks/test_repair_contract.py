import pytest
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_tasks.repair import require_explicit_collections
from tests.ai_prefill.test_contract import complete_payload


def test_omitted_populated_collection_cannot_become_implicit_deletion():
    raw=complete_payload();before=AiPrefillPayload.model_validate(raw)
    del raw['lineages']
    with pytest.raises(ValueError,match='omitted'):
        require_explicit_collections(before,raw)


def test_omitted_nested_edges_cannot_become_implicit_deletion():
    raw=complete_payload();before=AiPrefillPayload.model_validate(raw)
    del raw['lineages'][0]['edges']
    with pytest.raises(ValueError,match='omitted'):
        require_explicit_collections(before,raw)


def test_explicit_removal_still_produces_reviewable_change():
    raw=complete_payload();before=AiPrefillPayload.model_validate(raw)
    raw['lineages']=[];raw['edge_evidence_links']=[]
    require_explicit_collections(before,raw)
