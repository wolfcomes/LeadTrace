import pytest
from pydantic import ValidationError
from app.ai_prefill.contracts import BibliographyCorrection
from app.workspaces.schemas import BibliographyUpdateRequest


def test_article_metadata_source_backed_normalization_and_legacy_shape():
    old = BibliographyCorrection().model_dump(mode='json')
    assert not {'pmid', 'pmcid', 'research_profile', 'abstract_status'} & old.keys()
    data = BibliographyCorrection(pmid=' 123456 ', pmcid='pmc123456', identifiers_source=' PubMed ',
        abstract='Original abstract', abstract_source='PubMed', abstract_status='extracted',
        research_profile={'targets': [{'name': 'EGFR', 'source': 'Abstract', 'gene_symbol': 'EGFR'}],
                          'molecular_forms': [{'label': 'Small molecule', 'source': 'Abstract'}]}).model_dump(mode='json')
    assert data['pmid'] == '123456'
    assert data['pmcid'] == 'PMC123456'
    assert data['research_profile']['targets'][0]['role'] == 'unknown'
    assert data['abstract_status'] == 'extracted'


@pytest.mark.parametrize('fields', [
    {'pmid': 'doi:1'}, {'pmcid': '123'},
    {'abstract_status': 'extracted'}, {'abstract_status': 'not_found'},
    {'abstract_status': 'needs_review', 'abstract_note': ' '},
    {'research_profile': {'targets': [{'name': 'EGFR', 'source': ' '}]}},
    {'research_profile': {'mechanisms': [{'label': ' ', 'source': 'Abstract'}]}},
    {'research_profile': {'targets': [{'name': 'EGFR', 'source': 'Abstract', 'ncbi_gene_id': 'abc'}]}},
])
def test_article_metadata_rejects_invalid_or_unsupported_claims(fields):
    with pytest.raises(ValidationError):
        BibliographyCorrection(**fields)


def test_abstract_partial_patch_defers_cross_field_validation_until_current_state_is_merged():
    request = BibliographyUpdateRequest(expected_workspace_version=1, abstract_status='extracted')
    assert request.updates() == {'abstract_status': 'extracted'}
    assert BibliographyCorrection(abstract='Legacy abstract').abstract == 'Legacy abstract'


def test_target_optional_identifiers_can_be_cleared_and_numeric_ids_are_positive():
    from app.papers.metadata import ResearchTarget
    target = ResearchTarget(name='Target', source='Abstract', uniprot_id=' ', ncbi_gene_id='', organism='')
    assert target.uniprot_id is None
    assert target.ncbi_gene_id is None
    assert target.organism is None
    for fields in ({'pmid': '0'}, {'pmid': '0123'}, {'pmcid': 'PMC0'}, {'pmcid': 'PMC0123'}):
        with pytest.raises(ValidationError):
            BibliographyCorrection(**fields)


def test_manual_modality_edits_require_vocabulary_but_preserve_existing_legacy_rows():
    from app.papers.metadata import validate_modality_update
    old = {'modalities': [{'label': 'Legacy action', 'source': 'Page 1'}]}
    validate_modality_update(old, old)
    validate_modality_update(old, {'modalities': [{'label': 'Legacy action', 'source': 'Corrected page 2'}]})
    validate_modality_update(old, {'modalities': [{'label': '小分子抑制剂', 'source': 'Page 1'}]})
    for new in [
        {'modalities': [{'label': 'Another invented class', 'source': 'Page 1'}]},
        {'modalities': old['modalities'] * 2},
        {'modalities': [{'label': '其他', 'source': 'Page 1'}]},
    ]:
        with pytest.raises(ValueError):
            validate_modality_update(old, new)
    validate_modality_update(old, {'modalities': [{'label': '其他', 'source': 'Page 1', 'review_hint': 'Unusual intervention explicitly described'}]})


def test_unexplained_legacy_modality_does_not_allow_new_duplicate():
    from app.papers.metadata import validate_modality_update
    old = {'modalities': [{'label': '其他', 'source': 'Page 1'}]}
    validate_modality_update(old, old)
    with pytest.raises(ValueError):
        validate_modality_update(old, {'modalities': old['modalities'] * 2})


def test_article_evidence_preserves_legacy_shape_and_accepts_exact_quotes():
    from app.papers.metadata import SourceBackedLabel, ArticleEvidence, PdbReference
    legacy = SourceBackedLabel(label='Inhibitor', source='Page 1').model_dump(mode='json')
    assert 'evidence' not in legacy
    assert 'evidence' not in PdbReference(pdb_id='1ABC').model_dump(mode='json')
    quote = {'source_kind': 'main_pdf', 'quoted_text': 'Exact source words.', 'page_number': 1}
    term = SourceBackedLabel(label='Inhibitor', source='Page 1', evidence=[quote])
    assert term.model_dump(mode='json')['evidence'][0]['quoted_text'] == quote['quoted_text']
    assert ArticleEvidence.model_validate(quote).page_number == 1


@pytest.mark.parametrize('quote', [
    {'source_kind': 'main_pdf', 'quoted_text': 'Quote'},
    {'source_kind': 'main_pdf', 'quoted_text': ' ', 'page_number': 1},
    {'source_kind': 'external', 'quoted_text': 'Quote', 'source_url': 'javascript:alert(1)'},
    {'source_kind': 'external', 'quoted_text': 'Quote'},
    {'source_kind': 'supplement', 'quoted_text': 'Quote', 'page_number': 1},
    {'source_kind': 'main_pdf', 'quoted_text': 'Quote', 'page_number': 1, 'bbox': {'x': .9, 'y': 0, 'width': .2, 'height': .1}, 'source_sha256': 'a'*64},
    {'source_kind': 'main_pdf', 'quoted_text': 'Quote', 'page_number': 1, 'bbox': {'x': 0, 'y': 0, 'width': .2, 'height': .1}},
])
def test_article_evidence_rejects_untraceable_or_unsafe_sources(quote):
    from app.papers.metadata import ArticleEvidence
    with pytest.raises(ValidationError):
        ArticleEvidence.model_validate(quote)


def test_molecule_type_vocabulary_and_legacy_broad_label_remain_distinct():
    from app.papers.metadata import MODALITY_LABELS, validate_modality_update
    assert len(MODALITY_LABELS) == 15
    assert '直接靶点调节' not in MODALITY_LABELS
    old = {'modalities': [{'label': '直接靶点调节', 'source': 'Legacy page 1'}]}
    validate_modality_update(old, old)
    with pytest.raises(ValueError):
        validate_modality_update({}, old)


def test_manual_molecule_type_changes_require_main_type_and_unique_labels():
    from app.papers.metadata import validate_modality_update
    def term(label):
        return {'label': label, 'source': 'Page 1'}
    old = {'modalities': [term('直接靶点调节'), term('直接靶点调节')]}
    # Historical duplicates and broad labels remain editable without reclassification.
    validate_modality_update(old, {'modalities': [term('直接靶点调节') | {'source': 'Updated page'}, term('直接靶点调节')]})
    validate_modality_update(old, {'modalities': []})
    validate_modality_update(old, {'modalities': [term('小分子抑制剂'), term('大环类')]})
    for labels in [['大环类'], ['前药'], ['小分子抑制剂', '小分子抑制剂'], ['直接靶点调节']]:
        with pytest.raises(ValueError):
            validate_modality_update(old, {'modalities': [term(label) for label in labels]})
