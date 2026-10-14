from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.contracts import AiPrefillPayload
from .test_assistance_validation import make


def test_absent_abstract_is_a_reported_review_gap_but_old_candidates_still_apply():
    report = validate_candidate(make(AiPrefillPayload(schema_version=1)))
    assert any(x.code == 'ABSTRACT_NOT_CHECKED' for x in report.issues)
    assert report.can_apply


def test_original_abstract_with_source_does_not_have_missing_metadata_warning():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
        'abstract': 'Synthetic source abstract.', 'abstract_source': 'Page 1, Abstract', 'abstract_status': 'extracted'}})
    assert not any(x.code.startswith('ABSTRACT_') for x in validate_candidate(make(payload)).issues)


def test_checked_absence_retains_gap_and_reason_without_claiming_original_is_absent():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
        'abstract_status': 'not_found', 'abstract_note': 'Checked supplied source; no abstract located'}})
    report = validate_candidate(make(payload))
    assert any(x.code == 'ABSTRACT_UNAVAILABLE' for x in report.issues)
    assert report.can_apply


def test_recorded_legacy_abstract_without_explicit_state_is_reviewable_but_flagged():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
        'abstract': 'Synthetic source abstract.', 'abstract_source': 'Page 1'}})
    report = validate_candidate(make(payload))
    assert any(x.code == 'ABSTRACT_STATUS_NOT_CHECKED' for x in report.issues)
    assert report.can_apply


def test_noncanonical_modalities_and_retired_form_are_flagged_without_mutating_legacy_payload():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
        'research_profile': {
            'modalities': [{'label': 'Inhibitor', 'source': 'Page 1'}],
            'molecular_forms': [{'label': 'Macrocycle', 'source': 'Page 2'}],
        }}})
    original = payload.model_dump(mode='json')
    report = validate_candidate(make(payload))
    assert any(x.code == 'MODALITY_OUTSIDE_VOCABULARY' and x.severity == 'needs_review' for x in report.issues)
    assert any(x.code == 'MOLECULAR_FORMS_RETIRED' for x in report.issues)
    assert report.can_apply
    assert payload.model_dump(mode='json') == original


def test_fixed_modalities_are_accepted_and_other_unknown_require_explanation():
    for label in ['直接靶点调节', 'PROTAC', '分子胶', '前药', '其他', '待明确']:
        payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
            'research_profile': {'modalities': [{'label': label, 'source': 'Page 1', 'review_hint': 'Source supports an unusual intervention; classification pending' if label in ['其他', '待明确'] else None}]}}})
        assert not any(x.code.startswith('MODALITY_') for x in validate_candidate(make(payload)).issues)
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'bibliography': {
        'research_profile': {'modalities': [{'label': '其他', 'source': 'Page 1'}]}}})
    assert any(x.code == 'MODALITY_EXPLANATION_MISSING' for x in validate_candidate(make(payload)).issues)
