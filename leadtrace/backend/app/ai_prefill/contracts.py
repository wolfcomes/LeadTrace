from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewHintModel(StrictModel):
    review_hint: str | None = Field(default=None, max_length=1000)

    @field_validator("review_hint")
    @classmethod
    def clean_review_hint(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        # Absent hints must not change hashes of frozen v1 candidates.
        data = handler(self)
        if self.review_hint is None:
            data.pop("review_hint", None)
        return data


from app.papers.metadata import ArticleMetadata


class BibliographyCorrection(ArticleMetadata, StrictModel):
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


from app.structures.availability import AvailabilityFields, AVAILABILITY_FIELDS, UNAVAILABLE, validate_availability


class AiStructure(AvailabilityFields, StrictModel):
    # Revision-only context for an existing incomplete/uncertain structure.
    preserve_unresolved: Literal[True] | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        data = handler(self)
        if self.preserve_unresolved is None:
            data.pop("preserve_unresolved", None)
        for key in AVAILABILITY_FIELDS:
            if data.get(key) is None: data.pop(key, None)
        return data

    smiles: str | None = Field(default=None, min_length=1)
    molfile: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def has_one_representation(self) -> "AiStructure":
        validate_availability(self, self.smiles, self.molfile)
        if not self.smiles and not self.molfile and not self.preserve_unresolved and self.availability not in UNAVAILABLE:
            raise ValueError("Structure requires SMILES or Molfile")
        return self


class AiCompound(ReviewHintModel):
    ref: str = Field(min_length=1, max_length=255)
    compound_label: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=10_000)
    structure: AiStructure


class AiCompoundHighlight(ReviewHintModel):
    ref: str = Field(min_length=1, max_length=255)
    compound_ref: str = Field(min_length=1, max_length=255)
    evidence_ref: str = Field(min_length=1, max_length=255)
    role: Literal["study_start", "paper_selected", "optimization_start"]
    scope: str = Field(min_length=1, max_length=512)
    rationale: str = Field(min_length=1, max_length=10_000)

    @field_validator("scope", "rationale")
    @classmethod
    def required_text(cls, value):
        if not value.strip():
            raise ValueError("Nonblank text is required")
        return value.strip()


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


class AiLineageEdge(ReviewHintModel):
    preserve_unresolved: Literal[True] | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        data = super().preserve_legacy_serialization(handler)
        if self.preserve_unresolved is None:
            data.pop("preserve_unresolved", None)
        for key in AVAILABILITY_FIELDS:
            if data.get(key) is None: data.pop(key, None)
        return data

    ref: str = Field(min_length=1, max_length=255)
    parent_compound_ref: str = Field(min_length=1, max_length=255)
    child_compound_ref: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(min_length=1, max_length=128)
    modification_summary: str | None = Field(default=None, max_length=10_000)


class AiLineage(StrictModel):
    lineage_type: Literal["sar", "synthesis", "unspecified"] = "unspecified"
    ref: str = Field(min_length=1, max_length=255)
    lineage_label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    members: list[AiLineageMember] = Field(default_factory=list)
    edges: list[AiLineageEdge] = Field(default_factory=list)


    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        # Existing signed candidates and receipts predate classification.
        data = handler(self)
        if self.lineage_type == "unspecified":
            data.pop("lineage_type", None)
        return data


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


class AiActivity(ReviewHintModel):
    ref: str | None = Field(default=None, min_length=1, max_length=255)
    compound_ref: str = Field(min_length=1, max_length=255)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=255)
    assay_name: str = Field(min_length=1, max_length=512)
    metric: str = Field(min_length=1, max_length=128)
    operator: Literal["=", "<", "<=", ">", ">=", "~"]
    value: Decimal
    unit: str | None = Field(default=None, max_length=128)
    context: str | None = Field(default=None, max_length=10_000)


    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        data = handler(self)
        if self.ref is None:
            data.pop("ref", None)
        if self.review_hint is None:
            data.pop("review_hint", None)
        return data


class AiActivityTableColumn(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=512)
    assay: str = Field(min_length=1, max_length=512)
    metric: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=128)
    activity_refs: list[str] = Field(default_factory=list, max_length=10000)


    @field_validator("id", "label", "assay", "metric")
    @classmethod
    def required_text(cls, value):
        if not value.strip():
            raise ValueError("Nonblank text is required")
        return value.strip()


class AiActivityTable(ReviewHintModel):
    ref: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=512)
    kind: Literal["source", "custom"] = "source"
    source_label: str | None = Field(default=None, max_length=512)
    source_title: str | None = Field(default=None, max_length=10000)
    page_number: int | None = Field(default=None, gt=0)
    compound_refs: list[str] | None = Field(default=None, max_length=10000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=1000)
    columns: list[AiActivityTableColumn] = Field(max_length=200)
    mode: Literal["any", "all"] = "any"
    sort: Literal["label", "similarity", "default"] = "label"

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        data = handler(self)
        if self.review_hint is None:
            data.pop("review_hint", None)
        if self.compound_refs is None:
            data.pop("compound_refs", None)
        if not self.evidence_refs:
            data.pop("evidence_refs", None)
        return data

    @field_validator("name")
    @classmethod
    def required_name(cls, value):
        if not value.strip():
            raise ValueError("Nonblank table name is required")
        return value.strip()

    @field_validator("source_label", "source_title")
    @classmethod
    def optional_text(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_table(self):
        if self.kind == "source" and not (self.source_label or "").strip():
            raise ValueError("Source Activity table requires source_label")
        _require_unique(self.compound_refs or [], "Compound ref in table rows")
        _require_unique(self.evidence_refs, "Evidence ref in table")
        _require_unique([c.id for c in self.columns], "Activity table column id")
        for column in self.columns:
            _require_unique(column.activity_refs, "Activity ref in table column")
        return self


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
    compound_highlights: list[AiCompoundHighlight] = Field(default_factory=list)
    activity_tables: list[AiActivityTable] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        data = handler(self)
        if not self.compound_highlights:
            data.pop("compound_highlights", None)
        if not self.activity_tables:
            data.pop("activity_tables", None)
        return data

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
        _require_unique([h.ref for h in self.compound_highlights], "Compound highlight ref")
        identities = [(h.compound_ref, h.role, h.scope) for h in self.compound_highlights]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate Compound highlight identity")
        for highlight in self.compound_highlights:
            if highlight.compound_ref not in compounds or highlight.evidence_ref not in evidence:
                raise ValueError("Compound highlight references unknown Compound or Evidence")
        _require_unique([a.ref for a in self.activities if a.ref is not None], "Activity ref")
        _require_unique([t.ref for t in self.activity_tables], "Activity table ref")
        by_ref = {a.ref: a for a in self.activities if a.ref is not None}
        evidence_by_ref = {e.ref: e for e in self.evidence}
        for table in self.activity_tables:
            if table.compound_refs is not None and not set(table.compound_refs) <= compounds:
                raise ValueError("Activity table references unknown Compound")
            for ref in table.evidence_refs:
                item = evidence_by_ref.get(ref)
                if item is None:
                    raise ValueError("Activity table references unknown Evidence")
                if item.kind != "table" or item.bbox is None:
                    raise ValueError("Activity table Evidence requires table kind and screenshot bbox")
            for column in table.columns:
                for ref in column.activity_refs:
                    activity = by_ref.get(ref)
                    if activity is None:
                        raise ValueError(f"Activity table references unknown Activity: {ref}")
                    if table.compound_refs is not None and activity.compound_ref not in table.compound_refs:
                        raise ValueError("Activity table Activity is outside selected Compound rows")
                    if (activity.assay_name, activity.metric, activity.unit) != (column.assay, column.metric, column.unit):
                        raise ValueError("Activity table column measurement differs from Activity")
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
