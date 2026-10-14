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
