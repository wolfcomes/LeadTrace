"""Input-package helpers for cold-start AI-prefill processes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    SourceIdentity,
    canonical_json_bytes,
)


class AuthorizedSourceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha256: str = Field(min_length=64, max_length=64)
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    access: str = Field(default="read-only", min_length=1, max_length=64)

    @field_validator("source_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if any(char not in "0123456789abcdef" for char in value):
            raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
        return value


class PrefillInputPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: Literal[1] = 1
    experiment_id: str = Field(min_length=1, max_length=128)
    target: SourceIdentity
    source_locator: AuthorizedSourceLocator
    schema_version: str = Field(default="CandidateEnvelope.v1", min_length=1)
    guide_version: str = Field(min_length=1, max_length=255)
    recipe: dict[str, Any] = Field(default_factory=dict)
    parent_candidate_id: str | None = None
    input_evaluation_ids: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def locator_matches_target(self) -> "PrefillInputPackage":
        if self.source_locator.source_sha256 != self.target.source_sha256:
            raise ValueError("source locator hash must match target source identity")
        return self


def prepare_input_package(
    *,
    experiment_id: str,
    source: SourceIdentity,
    guide_version: str,
    source_path: Path | None = None,
    parent_candidate_id: str | None = None,
    input_evaluation_ids: list[str] | None = None,
    recipe: dict[str, Any] | None = None,
) -> PrefillInputPackage:
    """Create a package whose public identity contains no local path."""

    locator = AuthorizedSourceLocator(
        source_sha256=source.source_sha256,
        path=str(source_path.resolve()) if source_path is not None else None,
    )
    return PrefillInputPackage(
        experiment_id=experiment_id,
        target=source,
        source_locator=locator,
        guide_version=guide_version,
        recipe=recipe or {},
        parent_candidate_id=parent_candidate_id,
        input_evaluation_ids=input_evaluation_ids or [],
        instructions=[
            "Read the source through the authorized read-only locator.",
            "Return CandidateEnvelope.v1 and record omissions instead of guessing.",
            "Follow docs/ai-prefill/START_HERE.md and the actual frozen guide bundle; this input package does not bundle guides or verify the PDF.",
            "Survey a source-derived compound inventory and verify representative cores before family expansion; producer self-check is not independent audit.",
            "Run candidate validate, candidate coverage, and candidate self-check with the final source self-review before independent audit.",
            "Use DeepSeek-led routine mode or Codex-observed evaluation mode from the current guide; only the trusted delivery coordinator may apply an authorized Preview draft.",
        ],
    )


def input_package_sha256(package: PrefillInputPackage) -> str:
    return hashlib.sha256(canonical_json_bytes(package.model_dump(mode="json"))).hexdigest()


def load_candidate(path: Path) -> CandidateEnvelope:
    return CandidateEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["AuthorizedSourceLocator", "PrefillInputPackage", "input_package_sha256", "load_candidate", "prepare_input_package"]
