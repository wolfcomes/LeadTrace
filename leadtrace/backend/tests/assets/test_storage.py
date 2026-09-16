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
    namespaced = store.put_bytes(
        content,
        suffix=".png",
        namespace="rdkit-structure/drawing-key",
    )

    assert first.storage_key == second.storage_key
    assert first.sha256 == second.sha256
    assert first.path == second.path
    assert first.path.read_bytes() == content
    assert namespaced.storage_key != first.storage_key
    assert namespaced.storage_key.startswith(
        "managed/rdkit-structure/drawing-key/objects/"
    )
    assert namespaced.path.read_bytes() == content
    with pytest.raises(AssetPathError):
        store.put_bytes(content, suffix=".png", namespace="../escape")

    replacement = _png_bytes((19, 11))
    assert replacement != content
    first.path.write_bytes(replacement)
    repaired = store.put_bytes(content, suffix=".png")

    assert repaired.path == first.path
    assert repaired.path.read_bytes() == content

    same_size_replacement = bytearray(content)
    same_size_replacement[-1] ^= 1
    assert len(same_size_replacement) == len(content)
    first.path.write_bytes(same_size_replacement)
    repaired = store.put_bytes(content, suffix=".png")

    assert repaired.path.read_bytes() == content
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


def test_snapshot_rejects_invalid_image_content_after_a_valid_signature(
    tmp_path: Path,
) -> None:
    store = LocalAssetStore(tmp_path / "managed")
    invalid_png = _png_bytes()[:-8]
    stored = store.put_bytes(invalid_png, suffix=".png")

    with pytest.raises(AssetMimeMismatchError, match="Image content is invalid"):
        store.read_snapshot(stored.storage_key)


def test_open_snapshot_spools_large_content_and_uses_bounded_source_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = LocalAssetStore(tmp_path / "managed")
    content = b"%PDF-1.4\n" + (b"x" * (2 * 1024 * 1024))
    stored = store.put_bytes(content, suffix=".pdf")
    real_open = Path.open
    read_sizes: list[int] = []

    class TrackingReader:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self.handle.read(size)

    def tracked_open(file_path: Path, *args, **kwargs):
        handle = real_open(file_path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if file_path == stored.path and "r" in mode:
            return TrackingReader(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracked_open)
    inspected, snapshot = store.open_snapshot(stored.storage_key)
    try:
        assert inspected.sha256 == stored.sha256
        assert inspected.byte_size == len(content)
        assert getattr(snapshot, "_rolled") is True
        assert snapshot.read() == content
    finally:
        snapshot.close()

    assert read_sizes
    assert all(size > 0 for size in read_sizes)
