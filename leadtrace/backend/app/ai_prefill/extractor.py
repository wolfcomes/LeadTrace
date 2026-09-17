from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.ai_prefill.contracts import AiPrefillPayload


@dataclass(frozen=True, slots=True)
class ProtectedPdfReference:
    """Logical Source PDF identity without a storage or physical path."""

    paper_id: UUID
    source_root_key: str
    source_key: str
    sha256: str
    page_count: int


class AiExtractor(Protocol):
    engine: str
    engine_version: str

    def extract(self, source: ProtectedPdfReference) -> AiPrefillPayload: ...


__all__ = ["AiExtractor", "ProtectedPdfReference"]
