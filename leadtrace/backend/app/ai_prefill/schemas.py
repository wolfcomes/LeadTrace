from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus


class AiPrefillProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AiExtractionRunResponse(AiPrefillProjection):
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    starting_workspace_version: int
    status: AiExtractionRunStatus
    engine: str
    engine_version: str
    error_summary: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_model(cls, run: AiExtractionRun) -> "AiExtractionRunResponse":
        return cls(
            id=run.id,
            paper_id=run.paper_id,
            workspace_id=run.workspace_id,
            starting_workspace_version=run.starting_workspace_version,
            status=run.status,
            engine=run.engine,
            engine_version=run.engine_version,
            error_summary=run.error_summary,
            queued_at=run.queued_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )


class AiPrefillStatusResponse(AiPrefillProjection):
    run: AiExtractionRunResponse | None
    can_start: bool
    blocked_reason: str | None


__all__ = ["AiExtractionRunResponse", "AiPrefillStatusResponse"]
