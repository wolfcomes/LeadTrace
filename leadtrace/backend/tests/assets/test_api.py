from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Initial asset admin password 2026!"


def test_asset_metadata_is_admin_only_and_never_exposes_storage_paths(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="asset.admin",
            display_name="Asset Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        visitor = UserService().create_user(
            session,
            username="asset.visitor",
            display_name="Asset Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        visitor.must_change_password = False
        asset = Asset(
            storage_key="source/baseline/private/article.pdf",
            original_filename="article.pdf",
            sha256="a" * 64,
            byte_size=100,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(asset)
        session.flush()
        asset_id = asset.id

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="asset-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "managed",
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(application) as client:
        anonymous = client.get(f"/api/v1/assets/{asset_id}")
        client.post(
            "/api/v1/auth/login",
            json={"username": "asset.visitor", "password": PASSWORD},
        )
        forbidden = client.get(f"/api/v1/assets/{asset_id}")
        client.cookies.clear()
        client.post(
            "/api/v1/auth/login",
            json={"username": "asset.admin", "password": PASSWORD},
        )
        allowed = client.get(f"/api/v1/assets/{asset_id}")

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["id"] == str(asset_id)
    assert "storage_key" not in allowed.json()
    assert "/private/" not in allowed.text
    assert str(tmp_path) not in allowed.text
