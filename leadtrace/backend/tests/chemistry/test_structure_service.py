from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.jobs.tasks.structures import run_structure_drawing_job
from app.structures.service import StructureDrawingService
from app.users.models import UserRole
from app.users.service import UserService


def test_drawing_service_reuses_one_verified_immutable_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        reviewer = UserService().create_user(
            session,
            username=f"structure-drawing-{uuid4().hex[:8]}",
            display_name="Structure drawing reviewer",
            role=UserRole.REVIEWER,
            initial_password="Structure drawing password 2026!",
        )
        service = StructureDrawingService(tmp_path)

        first = service.draw(
            session,
            smiles="c1ccccc1",
            created_by_id=reviewer.id,
        )
        second = service.draw(
            session,
            smiles="c1ccccc1",
            created_by_id=reviewer.id,
        )

        assert first.asset.id == second.asset.id
        assert first.reused is False
        assert second.reused is True
        asset = session.get(Asset, first.asset.id)
        assert asset is not None
        assert asset.category is AssetCategory.RDKIT_STRUCTURE
        assert asset.integrity_state is AssetIntegrityState.VERIFIED
        assert asset.mime_type == "image/png"
        assert asset.derivation_metadata["drawing_key"]
        assert (tmp_path / asset.storage_key.removeprefix("managed/")).read_bytes().startswith(
            b"\x89PNG"
        )


def test_background_drawing_job_keeps_the_shared_drawing_contract(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        result = run_structure_drawing_job(
            session,
            managed_root=tmp_path,
            smiles="C1=CC=CC=C1",
        )

        assert result.asset.category is AssetCategory.RDKIT_STRUCTURE
        assert result.path.read_bytes().startswith(b"\x89PNG")
        assert result.drawing_key
        assert result.reused is False
