"""Source-backed structure availability, separate from reviewer disposition."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_serializer

AVAILABILITY_FIELDS = ('availability', 'availability_note', 'identity_source', 'checked_sources')
UNAVAILABLE = {'not_reported', 'not_checked', 'unresolved'}

class AvailabilityFields(BaseModel):
    availability: Literal['available', 'not_reported', 'not_checked', 'unresolved'] | None = None
    availability_note: str | None = Field(default=None, max_length=10000)
    identity_source: str | None = Field(default=None, max_length=10000)
    checked_sources: str | None = Field(default=None, max_length=10000)

    @model_serializer(mode='wrap')
    def omit_absent_availability(self, handler):
        data = handler(self)
        for key in AVAILABILITY_FIELDS:
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @field_validator('availability_note', 'identity_source', 'checked_sources')
    @classmethod
    def clean_availability_text(cls, value):
        return value.strip() or None if value is not None else None

def availability_values(value):
    return {key: getattr(value, key, None) for key in AVAILABILITY_FIELDS if getattr(value, key, None) is not None}

def validate_availability(value, smiles, molfile):
    if value.availability in UNAVAILABLE:
        if smiles or molfile:
            raise ValueError('Unavailable structure cannot contain SMILES or Molfile')
        if any(not getattr(value, key, None) for key in AVAILABILITY_FIELDS[1:]):
            raise ValueError('Unavailable structure requires availability_note, identity_source and checked_sources')
    elif value.availability == 'available' and not (smiles or molfile):
        raise ValueError('Available structure requires SMILES or Molfile')


def structure_counts(compounds, structures):
    """Partition article entries by usable chemistry; count human review separately."""
    counts = dict(total=len(compounds), available=0, not_reported=0, not_checked=0, unresolved=0, confirmed=0)
    by_compound = {row.compound_id: row for row in structures}
    for compound in compounds:
        row = by_compound.get(compound.id)
        if row is None:
            kind = 'not_checked'
        elif row.canonical_smiles and row.canonical_smiles.strip() and row.availability not in UNAVAILABLE:
            kind = 'available'
        elif row.availability in UNAVAILABLE:
            kind = row.availability
        elif str(row.status) in {'not_reported', 'unresolved'}:
            kind = str(row.status)
        else:
            kind = 'unresolved' if row.smiles or row.molfile else 'not_checked'
        counts[kind] += 1
        if row is not None and str(row.status) == 'reviewer_confirmed':
            counts['confirmed'] += 1
    return counts


def valid_unavailable(value):
    return (value.availability in UNAVAILABLE and not (value.smiles or value.molfile)
            and all(isinstance(getattr(value, key, None), str) and getattr(value, key).strip()
                    for key in AVAILABILITY_FIELDS[1:]))


def snapshot_requires_preservation(row):
    """Compatibility for frozen legacy gaps and raw, unparseable human drafts."""
    if row is None:
        return True
    if row.get('availability') in UNAVAILABLE:
        return False
    if row.get('status') in {'unresolved', 'not_reported'}:
        return True
    from app.structures.service import _parse_smiles, _parse_molfile
    if row.get('input_method') == 'structure_editor' or not row.get('smiles'):
        return not row.get('molfile') or not _parse_molfile(row['molfile']).parseable
    return not _parse_smiles(row['smiles']).parseable
