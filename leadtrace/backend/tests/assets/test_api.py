from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest
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


def _png_bytes(color: str, size: tuple[int, int] = (12, 7)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _asset_application(
    *,
    asset_root: Path,
    database_url: str,
    session_factory: sessionmaker[Session],
):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="asset-content-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=asset_root,
    )
    resources = DatabaseResources(
        engine=session_factory.kw["bind"],
        session_factory=session_factory,
    )
    return create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )


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


def test_asset_content_is_protected_and_streams_registered_bytes(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    content = _png_bytes("white", (1, 1))
    from app.assets.storage import LocalAssetStore

    store = LocalAssetStore(tmp_path / "managed")
    stored = store.put_bytes(content, suffix=".png")
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="asset.content.admin",
            display_name="Asset Content Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        reviewer = UserService().create_user(
            session,
            username="asset.content.reviewer",
            display_name="Asset Content Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        reviewer.must_change_password = False
        asset = Asset(
            storage_key=stored.storage_key,
            original_filename="content.png",
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            mime_type="image/png",
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.ADMIN,
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
        session_secret="asset-content-session-secret-more-than-thirty-two-characters",
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
        client.post(
            "/api/v1/auth/login",
            json={"username": "asset.content.reviewer", "password": PASSWORD},
        )
        reviewer_response = client.get(f"/api/v1/assets/{asset_id}/content")
        client.cookies.clear()
        client.post(
            "/api/v1/auth/login",
            json={"username": "asset.content.admin", "password": PASSWORD},
        )
        response = client.get(f"/api/v1/assets/{asset_id}/content")

    assert reviewer_response.status_code == 404
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("image/png")


def test_asset_content_returns_the_same_snapshot_that_passed_integrity_check(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    from app.assets.storage import LocalAssetStore

    original_content = _png_bytes("white")
    replacement_content = _png_bytes("black")
    store = LocalAssetStore(tmp_path / "managed")
    stored = store.put_bytes(original_content, suffix=".png")
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="asset.snapshot.admin",
            display_name="Asset Snapshot Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        asset = Asset(
            storage_key=stored.storage_key,
            original_filename="snapshot.png",
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            mime_type="image/png",
            category=AssetCategory.RENDER_CACHE,
            access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(asset)
        session.flush()
        asset_id = asset.id

    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(replacement_content)
    real_open = Path.open
    replaced = False

    def replace_after_open(file_path: Path, *args, **kwargs):
        nonlocal replaced
        handle = real_open(file_path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if file_path == stored.path and not replaced and "r" in mode:
            replaced = True
            os.replace(replacement, stored.path)
        return handle

    monkeypatch.setattr(Path, "open", replace_after_open)
    application = _asset_application(
        asset_root=tmp_path / "managed",
        database_url=empty_postgresql_database_url,
        session_factory=auth_session_factory,
    )
    with TestClient(application) as client:
        client.post(
            "/api/v1/auth/login",
            json={"username": "asset.snapshot.admin", "password": PASSWORD},
        )
        response = client.get(f"/api/v1/assets/{asset_id}/content")

    assert replaced is True
    assert response.status_code == 200
    assert response.content == original_content
    assert response.content != replacement_content


@pytest.mark.parametrize(
    ("tamper", "expected_state"),
    [
        ("missing", AssetIntegrityState.MISSING),
        ("corrupt", AssetIntegrityState.CORRUPT),
    ],
)
def test_asset_content_persists_failed_integrity_state_before_404(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
    tamper: str,
    expected_state: AssetIntegrityState,
) -> None:
    from app.assets.storage import LocalAssetStore

    original_content = _png_bytes("white")
    store = LocalAssetStore(tmp_path / "managed")
    stored = store.put_bytes(original_content, suffix=".png")
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username=f"asset.integrity.{tamper}",
            display_name="Asset Integrity Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        asset = Asset(
            storage_key=stored.storage_key,
            original_filename="integrity.png",
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            mime_type="image/png",
            category=AssetCategory.RENDER_CACHE,
            access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add(asset)
        session.flush()
        asset_id = asset.id

    if tamper == "missing":
        stored.path.unlink()
    else:
        replacement_content = _png_bytes("black", (19, 11))
        assert replacement_content != original_content
        stored.path.write_bytes(replacement_content)

    application = _asset_application(
        asset_root=tmp_path / "managed",
        database_url=empty_postgresql_database_url,
        session_factory=auth_session_factory,
    )
    with TestClient(application) as client:
        client.post(
            "/api/v1/auth/login",
            json={"username": f"asset.integrity.{tamper}", "password": PASSWORD},
        )
        response = client.get(f"/api/v1/assets/{asset_id}/content")

    assert response.status_code == 404
    with auth_session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.integrity_state is expected_state
