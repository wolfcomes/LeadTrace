"""Optional source-backed article metadata, shared by manual and AI inputs."""
import re
from typing import Literal
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


class ArticleMetadata(BaseModel):
    abstract: str | None = Field(default=None, max_length=30000)
    abstract_source: str | None = Field(default=None, max_length=2000)
    pdb_references: list[PdbReference] = Field(default_factory=list, max_length=100)

    @field_validator('abstract', 'abstract_source')
    @classmethod
    def clean(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode='after')
    def unique_mentions(self):
        keys = [(x.pdb_id, x.source_page, x.source_context, x.compound_label) for x in self.pdb_references]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate PDB mention')
        return self

    @model_serializer(mode='wrap')
    def preserve_old_payload(self, handler):
        result = handler(self)
        for key in ('abstract', 'abstract_source', 'pdb_references'):
            if key not in self.model_fields_set and not result.get(key):
                result.pop(key, None)
        return result
