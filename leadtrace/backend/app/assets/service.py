from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.repository import AssetRepository
from app.assets.storage import InspectedFile, LocalAssetStore


def _now() -> datetime:
    return datetime.now(UTC)


class AssetService:
    def __init__(self, repository: AssetRepository | None = None) -> None:
        self.repository = repository or AssetRepository()

    def register_inspected(
        self,
        session: Session,
        *,
        storage_key: str,
        inspected: InspectedFile,
        category: AssetCategory,
        access_level: AssetAccessLevel,
        integrity_state: AssetIntegrityState = AssetIntegrityState.VERIFIED,
        source_metadata: dict[str, object] | None = None,
        derivation_metadata: dict[str, object] | None = None,
        import_batch_id: UUID | None = None,
        source_asset_id: UUID | None = None,
        created_by_id: UUID | None = None,
    ) -> tuple[Asset, bool]:
        existing = self.repository.find_exact(
            session,
            storage_key=storage_key,
            sha256=inspected.sha256,
        )
        if existing is not None:
            return existing, False
        prior_assets = session.scalars(
            select(Asset).where(
                Asset.storage_key == storage_key,
                Asset.integrity_state.in_(
                    [
                        AssetIntegrityState.REGISTERED,
                        AssetIntegrityState.VERIFIED,
                    ]
                ),
            )
        )
        for prior_asset in prior_assets:
            prior_asset.integrity_state = AssetIntegrityState.SUPERSEDED
        asset = Asset(
            storage_key=storage_key,
            original_filename=PurePosixPath(storage_key).name,
            sha256=inspected.sha256,
            byte_size=inspected.byte_size,
            mime_type=inspected.mime_type,
            width=inspected.width,
            height=inspected.height,
            page_count=inspected.page_count,
            category=category,
            access_level=access_level,
            integrity_state=integrity_state,
            import_batch_id=import_batch_id,
            source_asset_id=source_asset_id,
            derivation_metadata=derivation_metadata or {},
            source_metadata=source_metadata or {},
            verified_at=_now()
            if integrity_state is AssetIntegrityState.VERIFIED
            else None,
            created_by_id=created_by_id,
        )
        session.add(asset)
        session.flush()
        return asset, True

    def verify_integrity(
        self,
        session: Session,
        asset_id: UUID | None,
        store: LocalAssetStore,
    ) -> bool:
        if asset_id is None:
            return False
        asset = self.repository.get(session, asset_id)
        if asset is None:
            return False
        try:
            inspected = store.inspect(asset.storage_key)
        except FileNotFoundError:
            asset.integrity_state = AssetIntegrityState.MISSING
            return False
        except (OSError, ValueError):
            asset.integrity_state = AssetIntegrityState.CORRUPT
            return False
        valid = (
            inspected.sha256 == asset.sha256
            and inspected.byte_size == asset.byte_size
            and inspected.mime_type == asset.mime_type
        )
        asset.integrity_state = (
            AssetIntegrityState.VERIFIED if valid else AssetIntegrityState.CORRUPT
        )
        if valid:
            asset.verified_at = _now()
        return valid
