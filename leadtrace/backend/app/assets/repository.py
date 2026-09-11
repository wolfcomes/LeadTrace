from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset


class AssetRepository:
    def get(self, session: Session, asset_id: UUID) -> Asset | None:
        return session.get(Asset, asset_id)

    def find_exact(
        self,
        session: Session,
        *,
        storage_key: str,
        sha256: str,
    ) -> Asset | None:
        return session.scalar(
            select(Asset).where(
                Asset.storage_key == storage_key,
                Asset.sha256 == sha256,
            )
        )
