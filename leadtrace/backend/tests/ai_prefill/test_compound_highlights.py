import pytest
from pydantic import ValidationError
from app.ai_prefill.contracts import AiPrefillPayload


def payload():
    return {'schema_version': 1, 'compounds': [{'ref': 'c1', 'compound_label': '1', 'structure': {'smiles': 'CC'}}],
            'evidence': [{'ref': 'e1', 'kind': 'text', 'page_number': 1, 'quoted_text': 'Synthetic test evidence'}]}


def test_legacy_payload_omits_highlights():
    assert 'compound_highlights' not in AiPrefillPayload.model_validate(payload()).model_dump(mode='json')


def test_highlights_require_source_and_cannot_claim_review():
    data = payload()
    highlight = {'ref': 'h1', 'compound_ref': 'c1', 'evidence_ref': 'e1', 'role': 'study_start', 'scope': 'whole paper', 'rationale': 'Starting lead'}
    data['compound_highlights'] = [highlight]
    parsed = AiPrefillPayload.model_validate(data)
    assert parsed.compound_highlights[0].role == 'study_start'
    for key, value in [('evidence_ref', 'missing'), ('compound_ref', 'missing'), ('scope', '  '), ('review_status', 'reviewer_confirmed')]:
        data['compound_highlights'] = [{**highlight, key: value}]
        with pytest.raises(ValidationError):
            AiPrefillPayload.model_validate(data)
    data['compound_highlights'] = [highlight, {**highlight, 'ref': 'h2'}]
    with pytest.raises(ValidationError):
        AiPrefillPayload.model_validate(data)


def test_empty_published_highlights_keep_legacy_response_shape():
    from app.publications.schemas import PublishedPaperSnapshotResponse
    # Isolate the optional-field serializer from unrelated projection fields.
    projected = PublishedPaperSnapshotResponse.model_construct(compound_highlights=[])
    assert 'compound_highlights' not in projected.model_dump(mode='json')
