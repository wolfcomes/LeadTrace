"""Compare a candidate with an independently reviewed source inventory, offline."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope, SourceIdentity, canonical_json_bytes, computed_hashes,
)


class InventoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    required: bool = True
    role: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def check_entry(self):
        if any(not alias for alias in self.aliases):
            raise ValueError("inventory aliases must be nonblank")
        if not self.required and not self.exclusion_reason:
            raise ValueError("excluded inventory entry requires an exclusion_reason")
        return self


class CompoundInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inventory_version: Literal[1] = 1
    source: SourceIdentity
    scope: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    entries: list[InventoryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_identities(self):
        identities: set[str] = set()
        for entry in self.entries:
            for label in [entry.label, *entry.aliases]:
                if label in identities:
                    raise ValueError(f"duplicate/ambiguous inventory label or alias: {label}")
                identities.add(label)
        if not any(entry.required for entry in self.entries):
            raise ValueError("inventory must require at least one compound")
        return self


def check_compound_coverage(candidate: CandidateEnvelope, inventory: CompoundInventory) -> dict:
    for field in ("paper_key", "source_sha256", "byte_size", "page_count"):
        if getattr(candidate.source, field) != getattr(inventory.source, field):
            raise ValueError(f"inventory and candidate must have the same source: {field}")
    if (candidate.source.doi and inventory.source.doi
            and candidate.source.doi.casefold() != inventory.source.doi.casefold()):
        raise ValueError("inventory and candidate must have the same source DOI")
    by_label: dict[str, list[str]] = {}
    for compound in candidate.payload.compounds:
        by_label.setdefault(compound.compound_label.strip(), []).append(compound.ref)
    matched, missing, ambiguous, excluded = [], [], [], []
    known_labels = set()
    for entry in inventory.entries:
        labels = [entry.label, *entry.aliases]
        known_labels.update(labels)
        if not entry.required:
            excluded.append(entry.model_dump(mode="json"))
            continue
        refs = [ref for label in labels for ref in by_label.get(label, [])]
        if not refs:
            missing.append(entry.label)
        elif len(refs) != 1:
            ambiguous.append({"label": entry.label, "candidate_refs": refs})
        else:
            matched.append({"label": entry.label, "candidate_ref": refs[0]})
    return {
        "status": "incomplete" if missing or ambiguous else "complete_for_declared_scope",
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": computed_hashes(candidate).candidate_sha256,
        "inventory_sha256": hashlib.sha256(canonical_json_bytes(inventory.model_dump(mode="json"))).hexdigest(),
        "scope": inventory.scope,
        "reviewed_by": inventory.reviewed_by,
        "inventory_count": len(inventory.entries),
        "required_count": sum(entry.required for entry in inventory.entries),
        "covered_count": len(matched),
        "matched": matched,
        "missing_labels": missing,
        "ambiguous_matches": ambiguous,
        "excluded_entries": excluded,
        "extra_candidate_labels": sorted(set(by_label) - known_labels),
        "scientific_identity_verified": False,
        "note": "Label coverage only; inventory provenance, structures, activities and crops need independent review. Omissions never satisfy required entries.",
    }
