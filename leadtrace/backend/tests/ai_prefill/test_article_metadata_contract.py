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
