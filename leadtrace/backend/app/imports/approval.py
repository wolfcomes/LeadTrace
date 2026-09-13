from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import canonical_content_hash, persisted_json_value
from app.imports.models import (
    ImportBatch,
    ImportCandidateDecision,
    ImportReleaseCandidate,
)
from app.users.models import User, UserRole


CandidateDecisionAction = Literal["approve", "reject"]


class CandidateDecisionNotFound(LookupError):
    """The requested imported baseline candidate does not exist."""


class CandidateDecisionConflict(RuntimeError):
    """A candidate cannot be decided from its current persisted state."""


class CandidateDecisionForbidden(PermissionError):
    """The actor is not allowed to decide imported baseline candidates."""


@dataclass(frozen=True, slots=True)
class CandidateDecisionResult:
    decision: ImportCandidateDecision
    idempotent: bool = False


def _clean_reason(reason: str) -> str:
    value = reason.strip()
    if not value:
        raise ValueError("reason is required")
    if len(value) > 4000:
        raise ValueError("reason exceeds 4000 characters")
    return value


class ImportCandidateApprovalService:
    """Record one immutable Admin decision for an imported baseline."""

    def decide(
        self,
        session: Session,
        *,
        candidate_id: UUID,
        actor_id: UUID,
        action: CandidateDecisionAction,
        reason: str,
    ) -> CandidateDecisionResult:
        actor = session.get(User, actor_id)
        if actor is None or not actor.is_enabled or actor.role is not UserRole.ADMIN:
            raise CandidateDecisionForbidden(
                "Only an enabled Admin can decide import candidates"
            )
        if action not in ("approve", "reject"):
            raise ValueError("action must be approve or reject")
        clean_reason = _clean_reason(reason)

        candidate = session.scalar(
            select(ImportReleaseCandidate)
            .where(ImportReleaseCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate is None:
            raise CandidateDecisionNotFound("Import candidate not found")

        persisted_manifest = persisted_json_value(session, candidate.manifest)
        if not isinstance(persisted_manifest, dict):
            raise CandidateDecisionConflict("Candidate manifest is invalid")
        manifest_hash = canonical_content_hash(persisted_manifest)
        existing = session.scalar(
            select(ImportCandidateDecision).where(
                ImportCandidateDecision.candidate_id == candidate.id
            )
        )
        if existing is not None:
            exact_retry = (
                existing.actor_id == actor_id
                and existing.decision == action
                and existing.reason == clean_reason
                and existing.manifest_hash == manifest_hash
                and existing.manifest == persisted_manifest
            )
            if exact_retry:
                return CandidateDecisionResult(existing, True)
            raise CandidateDecisionConflict("Candidate decision retry conflict")

        batch = session.get(ImportBatch, candidate.import_batch_id)
        if (
            candidate.status != "imported_baseline"
            or batch is None
            or batch.status != "completed"
            or batch.completed_at is None
        ):
            raise CandidateDecisionConflict(
                "Candidate must belong to a completed pending import"
            )

        decision = ImportCandidateDecision(
            candidate_id=candidate.id,
            decision=action,
            actor_id=actor.id,
            reason=clean_reason,
            manifest=persisted_manifest,
            manifest_hash=manifest_hash,
        )
        candidate.status = "approved" if action == "approve" else "rejected"
        session.add(decision)
        session.flush()
        return CandidateDecisionResult(decision, False)


__all__ = [
    "CandidateDecisionAction",
    "CandidateDecisionConflict",
    "CandidateDecisionForbidden",
    "CandidateDecisionNotFound",
    "CandidateDecisionResult",
    "ImportCandidateApprovalService",
]
