"""Portable contracts and deterministic identity helpers for AI-prefill work.

The existing :class:`AiPrefillPayload` remains the scientific write contract.  The
envelope in this module adds provenance and experiment identity without binding a
candidate to UUIDs that only exist in one database.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai_prefill.contracts import AiPrefillPayload


class AssistanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SourceIdentity(AssistanceModel):
    paper_key: str = Field(min_length=1, max_length=255)
    source_sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(gt=0)
    page_count: int = Field(gt=0)
    doi: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("source_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
        return value


class ProducerProvenance(AssistanceModel):
    kind: Literal["local", "remote", "human-assisted", "legacy-adapter"]
    engine: str = Field(min_length=1, max_length=255)
    engine_version: str = Field(min_length=1, max_length=255)
    generated_at: datetime


class CandidateRecipe(AssistanceModel):
    guide_version: str = Field(min_length=1, max_length=255)
    prompt_digest: str | None = Field(default=None, min_length=64, max_length=64)
    config_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("prompt_digest", "config_digest")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is not None and not _HEX64.fullmatch(value):
            raise ValueError("recipe digests must be lowercase SHA-256 hex")
        return value


class CandidateOmission(AssistanceModel):
    path: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2_000)
    source_locator: str | None = Field(default=None, max_length=512)


class CandidateHashes(AssistanceModel):
    payload_sha256: str
    candidate_sha256: str

    @field_validator("payload_sha256", "candidate_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError("hash must be a lowercase SHA-256 hex digest")
        return value


class CandidateEnvelope(AssistanceModel):
    envelope_version: Literal[1]
    candidate_id: str = Field(min_length=1, max_length=128)
    experiment_id: str = Field(min_length=1, max_length=128)
    source: SourceIdentity
    producer: ProducerProvenance
    recipe: CandidateRecipe
    parent_candidate_id: str | None = Field(default=None, max_length=128)
    input_evaluation_ids: list[str] = Field(default_factory=list)
    omissions: list[CandidateOmission] = Field(default_factory=list)
    payload: AiPrefillPayload
    hashes: CandidateHashes | None = None

    @field_validator("candidate_id", "experiment_id", "parent_candidate_id")
    @classmethod
    def validate_ids(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_ID.fullmatch(value):
            raise ValueError("identifier contains unsupported path characters")
        return value

    @field_validator("input_evaluation_ids")
    @classmethod
    def validate_evaluation_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("input_evaluation_ids must be unique")
        for item in value:
            if not _SAFE_ID.fullmatch(item):
                raise ValueError("evaluation identifier contains unsupported characters")
        return value


class ValidationIssue(AssistanceModel):
    code: str = Field(min_length=1, max_length=128)
    severity: Literal["error", "needs_review", "warning"]
    path: str = Field(min_length=1, max_length=512)
    message: str = Field(min_length=1, max_length=2_000)
    entity_ref: str | None = Field(default=None, max_length=255)
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(AssistanceModel):
    report_id: str = Field(min_length=1, max_length=128)
    experiment_id: str = Field(min_length=1, max_length=128)
    candidate_id: str
    candidate_sha256: str
    payload_sha256: str
    profile_version: str = Field(min_length=1, max_length=128)
    validator_version: str = Field(min_length=1, max_length=255)
    status: Literal["valid", "needs_review", "invalid"]
    issues: list[ValidationIssue] = Field(default_factory=list)
    created_at: datetime

    @property
    def can_apply(self) -> bool:
        return self.status != "invalid" and not any(
            issue.severity == "error" for issue in self.issues
        )


class Evaluation(AssistanceModel):
    evaluation_id: str = Field(min_length=1, max_length=128)
    experiment_id: str
    candidate_id: str
    reviewer: str = Field(min_length=1, max_length=255)
    created_at: datetime
    decision: Literal["accepted", "needs_revision", "rejected"]
    issue_codes: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=20_000)
    workspace_snapshot_id: str | None = Field(default=None, max_length=128)
    # Optional for legacy artifacts. New database evaluations always populate
    # all binding fields; absent values never imply that a review was complete.
    candidate_sha256: str | None = None
    payload_sha256: str | None = None
    source_sha256: str | None = None
    validation_report_id: str | None = Field(default=None, max_length=128)
    application_id: UUID | None = None
    workspace_version: int | None = Field(default=None, gt=0)
    applied_workspace_version: int | None = Field(default=None, gt=0)
    workspace_snapshot_sha256: str | None = None
    section_coverage: dict[str, Literal[
        "reviewed", "partial", "not_reviewed", "not_applicable"
    ]] | None = None

    @field_validator(
        "candidate_sha256", "payload_sha256", "source_sha256",
        "workspace_snapshot_sha256",
    )
    @classmethod
    def validate_binding_hash(cls, value: str | None) -> str | None:
        if value is not None and not _HEX64.fullmatch(value):
            raise ValueError("evaluation binding hashes must be lowercase SHA-256 hex")
        return value


class ExperimentRegistry(AssistanceModel):
    experiment_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    created_at: datetime
    baseline_version: str = Field(min_length=1, max_length=255)
    target_paper_keys: list[str] = Field(min_length=1)
    current_candidate_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON using the same rules as the production prefill script."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_payload_bytes(payload: AiPrefillPayload) -> bytes:
    return canonical_json_bytes(payload.model_dump(mode="json"))


def payload_sha256(payload: AiPrefillPayload) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def candidate_digest_input(candidate: CandidateEnvelope) -> dict[str, Any]:
    value = candidate.model_dump(mode="json", exclude={"hashes"})
    return value


def candidate_sha256(candidate: CandidateEnvelope) -> str:
    return hashlib.sha256(canonical_json_bytes(candidate_digest_input(candidate))).hexdigest()


def computed_hashes(candidate: CandidateEnvelope) -> CandidateHashes:
    return CandidateHashes(
        payload_sha256=payload_sha256(candidate.payload),
        candidate_sha256=candidate_sha256(candidate),
    )


def with_computed_hashes(candidate: CandidateEnvelope) -> CandidateEnvelope:
    return candidate.model_copy(update={"hashes": computed_hashes(candidate)})


def validate_declared_hashes(candidate: CandidateEnvelope) -> None:
    expected = computed_hashes(candidate)
    if candidate.hashes is not None and candidate.hashes != expected:
        raise ValueError("declared candidate hashes do not match canonical content")


__all__ = [
    "CandidateEnvelope",
    "CandidateHashes",
    "CandidateOmission",
    "CandidateRecipe",
    "Evaluation",
    "ExperimentRegistry",
    "ProducerProvenance",
    "SourceIdentity",
    "ValidationIssue",
    "ValidationReport",
    "canonical_json_bytes",
    "canonical_payload_bytes",
    "candidate_sha256",
    "computed_hashes",
    "payload_sha256",
    "validate_declared_hashes",
    "with_computed_hashes",
]
