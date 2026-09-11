from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tomllib

from PIL import Image
import pytest

from app.assets.storage import (
    AssetMimeMismatchError,
    AssetPathError,
    LocalAssetStore,
)


def test_image_inspection_dependency_is_installed_in_production() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    )

    assert any(
        dependency.casefold().startswith("pillow")
        for dependency in project["project"]["dependencies"]
    )


def _png_bytes(size: tuple[int, int] = (12, 7)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_storage_keys_reject_absolute_traversal_and_symlink_escape(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    managed.mkdir()
    source.mkdir()
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4\n")
    (source / "escape.pdf").symlink_to(outside / "secret.pdf")
    store = LocalAssetStore(managed, source_roots={"baseline": source})

    for storage_key in (
        "/etc/passwd",
        "managed/../../etc/passwd",
        "source/baseline/../outside/secret.pdf",
        "source/baseline/escape.pdf",
        r"managed\..\secret",
    ):
        with pytest.raises(AssetPathError):
            store.path_for(storage_key)


def test_managed_content_is_atomically_addressed_and_deduplicated(
    tmp_path: Path,
) -> None:
    store = LocalAssetStore(tmp_path / "managed")
    content = _png_bytes()

    first = store.put_bytes(content, suffix=".png")
    second = store.put_bytes(content, suffix=".png")

    assert first.storage_key == second.storage_key
    assert first.sha256 == second.sha256
    assert first.path == second.path
    assert first.path.read_bytes() == content
    assert not list((tmp_path / "managed").rglob("*.tmp"))


def test_inspection_uses_content_signatures_and_records_image_dimensions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    image = source / "结构 图 (26a′).png"
    image.write_bytes(_png_bytes((31, 19)))
    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"baseline": source},
    )

    inspected = store.inspect("source/baseline/结构 图 (26a′).png")

    assert inspected.mime_type == "image/png"
    assert inspected.width == 31
    assert inspected.height == 19
    assert inspected.byte_size == image.stat().st_size
    assert len(inspected.sha256) == 64


def test_extension_and_content_mismatch_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "spoofed.pdf").write_bytes(_png_bytes())
    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"baseline": source},
    )

    with pytest.raises(AssetMimeMismatchError, match="PDF"):
        store.inspect("source/baseline/spoofed.pdf")
