from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.audit.models import (
    AuditChainHead,
    AuditEvent,
    AuditImmutableError,
)


GENESIS_HASH = "0" * 64
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_REASON_PATTERN = re.compile(
    r"(?P<prefix>\b(?:password|passwd|secret|token|"
    r"api(?:[_ -]?key)|authorization(?:[_ -]?header)?|credential|cookie|"
    r"private(?:[_ -]?key)|csrf(?:[_ -]?(?:token|value|secret))?|"
    r"session(?:[_ -]?(?:id|token|secret))?)"
    r"\b\s*(?:=|:|\bis\b)\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AuditVerification:
    valid: bool
    event_count: int
    first_invalid_sequence: int | None


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def persisted_json_value(session: Session, value: object) -> object:
    """Return the value after PostgreSQL JSONB applies its storage semantics."""

    return session.scalar(select(cast(value, JSONB)))


def persisted_content_hash(session: Session, value: object) -> str:
    return canonical_content_hash(persisted_json_value(session, value))


def redact_sensitive_text(value: str) -> str:
    """Remove inline credential values from free-form audit text."""

    return _SENSITIVE_REASON_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        value,
    )


def _sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return (
        "password" in normalized
        or "passwd" in normalized
        or "secret" in normalized
        or "session" in normalized
        or "token" in normalized
        or "credential" in normalized
        or "authorization" in normalized
        or "cookie" in normalized
        or "accesskey" in normalized
        or "apikey" in normalized
        or "privatekey" in normalized
        or normalized == "csrf"
        or normalized == "setcookie"
    )


def _safe_aggregate(key: object, value: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return normalized == "sessionsrevoked" and type(value) is int and value >= 0


def redact_secrets(value: Any) -> Any:
    """Return a JSON-safe copy with credential-bearing values removed."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _sensitive_key(key) and not _safe_aggregate(key, item)
                else redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def _required_text(value: str, field: str, maximum: int | None = None) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field} is required")
    if maximum is not None and len(clean) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return clean


def _required_hash(value: str, field: str) -> str:
    normalized = value.casefold()
    if not _HEX_SHA256.fullmatch(normalized):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return normalized


def _event_payload(event: AuditEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "sequence_number": event.sequence_number,
        "actor_id": str(event.actor_id),
        "action": event.action,
        "target_type": event.target_type,
        "target_id": str(event.target_id),
        "paper_id": str(event.paper_id) if event.paper_id else None,
        "changeset_id": str(event.changeset_id) if event.changeset_id else None,
        "release_id": str(event.release_id) if event.release_id else None,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "ip_address": event.ip_address,
        "request_id": event.request_id,
        "result": event.result,
        "reason": event.reason,
        "before_hash": event.before_hash,
        "after_hash": event.after_hash,
        "details": event.details,
    }


def _event_hash(previous_hash: str, event: AuditEvent) -> str:
    material = f"{previous_hash}\n{_canonical_json(_event_payload(event))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditService:
    """Append and verify a single globally ordered audit hash chain."""

    def append_event(
        self,
        session: Session,
        *,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: UUID,
        paper_id: UUID | None,
        changeset_id: UUID | None,
        release_id: UUID | None,
        ip_address: str,
        request_id: str,
        result: str,
        reason: str,
        before_hash: str,
        after_hash: str,
        details: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        head = session.scalar(
            select(AuditChainHead)
            .where(AuditChainHead.id == 1)
            .with_for_update()
        )
        if head is None:
            raise RuntimeError("Audit chain head is not initialized")
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        persisted_details = session.scalar(
            select(cast(redact_secrets(dict(details or {})), JSONB))
        )
        if not isinstance(persisted_details, dict):
            raise ValueError("details must be a JSON object")
        event = AuditEvent(
            id=uuid4(),
            sequence_number=head.last_sequence_number + 1,
            actor_id=actor_id,
            action=_required_text(action, "action", 120),
            target_type=_required_text(target_type, "target_type", 64),
            target_id=target_id,
            paper_id=paper_id,
            changeset_id=changeset_id,
            release_id=release_id,
            occurred_at=timestamp.astimezone(UTC),
            ip_address=_required_text(ip_address, "ip_address", 64),
            request_id=_required_text(request_id, "request_id", 128),
            result=_required_text(result, "result", 32),
            reason=_required_text(redact_sensitive_text(reason), "reason"),
            before_hash=_required_hash(before_hash, "before_hash"),
            after_hash=_required_hash(after_hash, "after_hash"),
            details=persisted_details,
            previous_event_hash=head.last_event_hash,
            event_hash="",
        )
        event.event_hash = _event_hash(event.previous_event_hash, event)
        session.add(event)
        head.last_sequence_number = event.sequence_number
        head.last_event_hash = event.event_hash
        head.updated_at = event.occurred_at
        session.flush()
        return event

    def list_events(
        self,
        session: Session,
        *,
        actor_id: UUID | None = None,
        action: str | None = None,
        target_type: str | None = None,
        result: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        if limit < 1 or limit > 500 or offset < 0:
            raise ValueError("Invalid audit pagination")
        statement = select(AuditEvent).order_by(AuditEvent.sequence_number.desc())
        if actor_id is not None:
            statement = statement.where(AuditEvent.actor_id == actor_id)
        if action is not None:
            statement = statement.where(AuditEvent.action == action)
        if target_type is not None:
            statement = statement.where(AuditEvent.target_type == target_type)
        if result is not None:
            statement = statement.where(AuditEvent.result == result)
        return list(session.scalars(statement.limit(limit).offset(offset)))

    def verify_chain(self, session: Session) -> AuditVerification:
        head = session.scalar(
            select(AuditChainHead)
            .where(AuditChainHead.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        events = list(
            session.scalars(select(AuditEvent).order_by(AuditEvent.sequence_number))
        )
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for event in events:
            valid = (
                event.sequence_number == expected_sequence
                and event.previous_event_hash == previous_hash
                and event.event_hash == _event_hash(previous_hash, event)
            )
            if not valid:
                return AuditVerification(False, len(events), event.sequence_number)
            previous_hash = event.event_hash
            expected_sequence += 1
        expected_head_hash = previous_hash
        if (
            head is None
            or head.last_sequence_number != len(events)
            or head.last_event_hash != expected_head_hash
        ):
            return AuditVerification(False, len(events), expected_sequence)
        return AuditVerification(True, len(events), None)


__all__ = [
    "AuditImmutableError",
    "AuditService",
    "AuditVerification",
    "canonical_content_hash",
    "persisted_content_hash",
    "persisted_json_value",
    "redact_secrets",
    "redact_sensitive_text",
]
