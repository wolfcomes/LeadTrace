from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.releases.models import Release


@dataclass(frozen=True, slots=True)
class PublishedRelease:
    id: UUID
    key: str
    title: str
    published_at: datetime
    metrics: dict[str, object]

    @classmethod
    def from_model(cls, release: Release) -> "PublishedRelease":
        return cls(
            id=release.id,
            key=release.release_key,
            title=release.title,
            published_at=release.published_at,
            metrics=release.metrics,
        )


def get_current_release(session: Session) -> Release:
    release = session.scalar(
        select(Release).where(
            Release.is_current.is_(True),
            Release.manifest_finalized.is_(True),
        )
    )
    if release is None:
        raise APIError(
            404,
            "CURRENT_RELEASE_NOT_FOUND",
            "No published release is currently available",
        )
    return release
