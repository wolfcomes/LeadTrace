"""Optional source-backed article metadata, shared by manual and AI inputs."""
import re
from collections import Counter
from typing import ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator


class PdbReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pdb_id: str = Field(max_length=12)
    usage: Literal['this_work', 'cited_structure', 'unknown'] = 'unknown'
    source_page: int | None = Field(default=None, ge=1)
    source_context: str | None = Field(default=None, max_length=2000)
    compound_label: str | None = Field(default=None, max_length=255)
    review_hint: str | None = Field(default=None, max_length=1000)

    @field_validator('pdb_id')
    @classmethod
    def accession(cls, value):
        value = value.strip()
        if re.fullmatch(r'[1-9][A-Za-z0-9]{3}', value):
            return value.upper()
        if re.fullmatch(r'pdb_[a-zA-Z0-9]{8}', value, flags=re.I):
            return 'pdb_' + value[4:].lower()
        raise ValueError('Use a PDB accession (e.g. 1ABC or pdb_00001abc), not a ligand code')

    @field_validator('source_context', 'compound_label', 'review_hint')
    @classmethod
    def clean(cls, value):
        return value.strip() or None if value is not None else None


ARTICLE_METADATA_DEFAULTS = {
    'abstract': None, 'abstract_source': None, 'pdb_references': [],
    'pmid': None, 'pmcid': None, 'identifiers_source': None,
    'abstract_status': 'not_checked', 'abstract_note': None, 'research_profile': {},
}
ARTICLE_METADATA_FIELDS = tuple(ARTICLE_METADATA_DEFAULTS)

# New selections use this vocabulary. Historical snapshots remain readable.
MODALITY_LABELS = ('直接靶点调节', 'PROTAC', '分子胶', '前药', '其他', '待明确')


def validate_modality_update(before: dict, after: dict) -> None:
    """Restrict new manual labels without invalidating historical science."""
    existing = before.get('modalities', [])
    legacy_counts = Counter(term['label'] for term in existing if term['label'] not in MODALITY_LABELS)
    unexplained_counts = Counter((term['label'], term.get('source')) for term in existing
                                 if term['label'] in ('其他', '待明确') and not (term.get('review_hint') or '').strip())
    for term in after.get('modalities', []):
        label = term['label']
        if label not in MODALITY_LABELS:
            if legacy_counts[label] < 1:
                raise ValueError('Choose a modality from the fixed vocabulary')
            legacy_counts[label] -= 1
        elif label in ('其他', '待明确') and not (term.get('review_hint') or '').strip():
            key = (label, term.get('source'))
            if unexplained_counts[key] < 1:
                raise ValueError('Other or unresolved modalities require an explanation')
            unexplained_counts[key] -= 1


def metadata_values(paper):
    return {key: getattr(paper, key) for key in ARTICLE_METADATA_FIELDS}


class SourceBackedLabel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=2000)
    review_hint: str | None = Field(default=None, max_length=1000)


class ResearchTarget(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=500)
    role: Literal['primary', 'co_primary', 'selectivity', 'off_target', 'mechanistic', 'biomarker', 'unknown'] = 'unknown'
    organism: str | None = Field(default=None, max_length=255)
    gene_symbol: str | None = Field(default=None, max_length=255)
    uniprot_id: str | None = Field(default=None, max_length=20)
    ncbi_gene_id: str | None = Field(default=None, pattern=r'^[1-9][0-9]*$', max_length=20)
    source: str = Field(min_length=1, max_length=2000)
    review_hint: str | None = Field(default=None, max_length=1000)

    @field_validator('organism', 'gene_symbol', 'uniprot_id', 'ncbi_gene_id', 'review_hint', mode='before')
    @classmethod
    def optional_text(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator('uniprot_id')
    @classmethod
    def accession(cls, value):
        if value is None:
            return None
        value = value.upper()
        if not re.fullmatch(r'(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[1-9][0-9]*)?', value):
            raise ValueError('Use a UniProt accession')
        return value


class ResearchProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    molecular_forms: list[SourceBackedLabel] = Field(default_factory=list, max_length=100)
    modalities: list[SourceBackedLabel] = Field(default_factory=list, max_length=100)
    mechanisms: list[SourceBackedLabel] = Field(default_factory=list, max_length=100)
    diseases: list[SourceBackedLabel] = Field(default_factory=list, max_length=100)
    optimization_goals: list[SourceBackedLabel] = Field(default_factory=list, max_length=100)
    targets: list[ResearchTarget] = Field(default_factory=list, max_length=200)

    @model_serializer(mode='wrap')
    def compact(self, handler):
        return {key: value for key, value in handler(self).items() if value or key in self.model_fields_set}


class ArticleMetadata(BaseModel):
    partial_metadata: ClassVar[bool] = False
    abstract: str | None = Field(default=None, max_length=30000)
    abstract_source: str | None = Field(default=None, max_length=2000)
    pdb_references: list[PdbReference] = Field(default_factory=list, max_length=100)
    pmid: str | None = Field(default=None, pattern=r'^[1-9][0-9]*$', max_length=20)
    pmcid: str | None = Field(default=None, pattern=r'^PMC[1-9][0-9]*$', max_length=23)
    identifiers_source: str | None = Field(default=None, max_length=2000)
    abstract_status: Literal['not_checked', 'extracted', 'not_found', 'needs_review'] = 'not_checked'
    abstract_note: str | None = Field(default=None, max_length=2000)
    research_profile: ResearchProfile = Field(default_factory=ResearchProfile)

    @field_validator('pmid', 'pmcid', mode='before')
    @classmethod
    def identifier(cls, value):
        return value.strip().upper() or None if isinstance(value, str) else value

    @field_validator('abstract', 'abstract_source', 'abstract_note', 'identifiers_source')
    @classmethod
    def clean(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode='after')
    def complete_abstract(self):
        if not self.partial_metadata:
            if self.abstract_status == 'extracted' and not (self.abstract and self.abstract_source):
                raise ValueError('Extracted abstract requires text and source')
            if self.abstract_status in ('not_found', 'needs_review') and not self.abstract_note:
                raise ValueError('Abstract status requires an explanatory note')
        return self

    @model_validator(mode='after')
    def unique_mentions(self):
        keys = [(x.pdb_id, x.source_page, x.source_context, x.compound_label) for x in self.pdb_references]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate PDB mention')
        return self

    @model_serializer(mode='wrap')
    def preserve_old_payload(self, handler):
        result = handler(self)
        for key, default in ARTICLE_METADATA_DEFAULTS.items():
            if key not in self.model_fields_set and result.get(key) == default:
                result.pop(key, None)
        return result
