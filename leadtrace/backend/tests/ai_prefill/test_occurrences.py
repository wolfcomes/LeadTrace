from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.occurrences import occurrence_context, occurrence_notes
from .test_contract import complete_payload


def test_long_annotations_remain_available_without_breaking_export_contract():
    raw = complete_payload()
    first = raw['structure_locators'][0]
    first['source_context'] = 'a' * 10000
    second = dict(first, ref='alternate', source_context='b' * 10000, label='Alternate')
    raw['structure_locators'].append(second)
    locators = AiPrefillPayload.model_validate(raw).structure_locators
    assert occurrence_context(locators) == first['source_context']
    notes = occurrence_notes(locators)
    assert notes[0]['annotations'] == [
        {'ref': x.ref, 'label': x.label, 'source_context': x.source_context} for x in locators
    ]
    assert notes[0]['extended_annotations'] is True
