from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BibliographyCorrection(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=1024)
    journal: str | None = Field(default=None, min_length=1, max_length=255)
    publication_year: int | None = Field(default=None, ge=1000, le=9999)
    volume: str | None = Field(default=None, min_length=1, max_length=64)
    issue: str | None = Field(default=None, min_length=1, max_length=64)
    doi: str | None = Field(default=None, min_length=1, max_length=255)


class NormalizedBBox(StrictModel):
    x0: Decimal = Field(ge=0, le=1)
    y0: Decimal = Field(ge=0, le=1)
    x1: Decimal = Field(ge=0, le=1)
    y1: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def positive_area(self) -> "NormalizedBBox":
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("Bounding box must have positive normalized area")
        return self


class AiStructure(StrictModel):
    smiles: str | None = Field(default=None, min_length=1)
    molfile: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def has_one_representation(self) -> "AiStructure":
        if not self.smiles and not self.molfile:
            raise ValueError("Structure requires SMILES or Molfile")
        return self


class AiCompound(StrictModel):
    ref: str = Field(min_length=1, max_length=255)
    compound_label: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=10_000)
    structure: AiStructure


class AiStructureLocator(StrictModel):
    ref: str = Field(min_length=1, max_length=255)
    compound_ref: str = Field(min_length=1, max_length=255)
    page_number: int = Field(gt=0)
    bbox: NormalizedBBox
    source_context: str | None = Field(default=None, max_length=10_000)
    label: str | None = Field(default=None, max_length=512)


class AiLineageMember(StrictModel):
    compound_ref: str = Field(min_length=1, max_length=255)
    role: Literal["root", "intermediate", "terminal", "unspecified"]


class AiLineageEdge(StrictModel):
    ref: str = Field(min_length=1, max_length=255)
    parent_compound_ref: str = Field(min_length=1, max_length=255)
    child_compound_ref: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(min_length=1, max_length=128)
    modification_summary: str | None = Field(default=None, max_length=10_000)


class AiLineage(StrictModel):
    ref: str = Field(min_length=1, max_length=255)
    lineage_label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    members: list[AiLineageMember] = Field(default_factory=list)
    edges: list[AiLineageEdge] = Field(default_factory=list)


class AiEvidence(StrictModel):
    ref: str = Field(min_length=1, max_length=255)
    kind: Literal["text", "table", "scheme", "image"]
    page_number: int = Field(gt=0)
    bbox: NormalizedBBox | None = None
    quoted_text: str | None = Field(default=None, max_length=20_000)
    caption: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def has_content(self) -> "AiEvidence":
        if self.bbox is None and not self.quoted_text and not self.caption:
            raise ValueError("Evidence requires a locator, quote, or caption")
        return self


class AiEdgeEvidenceLink(StrictModel):
    edge_ref: str = Field(min_length=1, max_length=255)
    evidence_ref: str = Field(min_length=1, max_length=255)
    role: Literal["supports", "contradicts", "contextual"]


class AiActivity(StrictModel):
    compound_ref: str = Field(min_length=1, max_length=255)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=255)
    assay_name: str = Field(min_length=1, max_length=512)
    metric: str = Field(min_length=1, max_length=128)
    operator: Literal["=", "<", "<=", ">", ">=", "~"]
    value: Decimal
    unit: str | None = Field(default=None, max_length=128)
    context: str | None = Field(default=None, max_length=10_000)


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")


class AiPrefillPayload(StrictModel):
    schema_version: Literal[1]
    bibliography: BibliographyCorrection = Field(
        default_factory=BibliographyCorrection
    )
    compounds: list[AiCompound] = Field(default_factory=list)
    structure_locators: list[AiStructureLocator] = Field(default_factory=list)
    lineages: list[AiLineage] = Field(default_factory=list)
    evidence: list[AiEvidence] = Field(default_factory=list)
    edge_evidence_links: list[AiEdgeEvidenceLink] = Field(default_factory=list)
    activities: list[AiActivity] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "AiPrefillPayload":
        compound_refs = [item.ref for item in self.compounds]
        _require_unique(compound_refs, "Compound ref")
        _require_unique(
            [item.compound_label for item in self.compounds],
            "Compound label",
        )
        compounds = set(compound_refs)

        _require_unique(
            [item.ref for item in self.structure_locators],
            "Structure locator ref",
        )
        for locator in self.structure_locators:
            if locator.compound_ref not in compounds:
                raise ValueError(
                    f"Structure locator references unknown Compound: "
                    f"{locator.compound_ref}"
                )

        _require_unique([item.ref for item in self.lineages], "Lineage ref")
        edge_refs: list[str] = []
        for lineage in self.lineages:
            member_refs = [member.compound_ref for member in lineage.members]
            _require_unique(member_refs, f"member in Lineage {lineage.ref}")
            for member_ref in member_refs:
                if member_ref not in compounds:
                    raise ValueError(
                        f"Lineage member references unknown Compound: {member_ref}"
                    )
            members = set(member_refs)
            for edge in lineage.edges:
                edge_refs.append(edge.ref)
                if edge.parent_compound_ref == edge.child_compound_ref:
                    raise ValueError("Lineage Edge cannot be a self-edge")
                for endpoint in (
                    edge.parent_compound_ref,
                    edge.child_compound_ref,
                ):
                    if endpoint not in compounds:
                        raise ValueError(
                            f"Lineage Edge references unknown Compound: {endpoint}"
                        )
                    if endpoint not in members:
                        raise ValueError(
                            f"Lineage Edge endpoint is not a Lineage member: {endpoint}"
                        )
        _require_unique(edge_refs, "Edge ref")
        edges = set(edge_refs)

        evidence_refs = [item.ref for item in self.evidence]
        _require_unique(evidence_refs, "Evidence ref")
        evidence = set(evidence_refs)
        for link in self.edge_evidence_links:
            if link.edge_ref not in edges:
                raise ValueError(f"Link references unknown Edge: {link.edge_ref}")
            if link.evidence_ref not in evidence:
                raise ValueError(
                    f"Link references unknown Evidence: {link.evidence_ref}"
                )
        for activity in self.activities:
            if activity.compound_ref not in compounds:
                raise ValueError(
                    f"Activity references unknown Compound: {activity.compound_ref}"
                )
            if (
                activity.evidence_ref is not None
                and activity.evidence_ref not in evidence
            ):
                raise ValueError(
                    f"Activity references unknown Evidence: {activity.evidence_ref}"
                )
        return self


__all__ = [
    "AiActivity",
    "AiCompound",
    "AiEdgeEvidenceLink",
    "AiEvidence",
    "AiLineage",
    "AiLineageEdge",
    "AiLineageMember",
    "AiPrefillPayload",
    "AiStructure",
    "AiStructureLocator",
    "BibliographyCorrection",
    "NormalizedBBox",
]
