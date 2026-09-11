from __future__ import annotations

from pathlib import Path

from app.assets.storage import AssetPathError, LocalAssetStore


def test_document_storage_namespaces_never_resolve_outside_configured_roots(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    managed.mkdir()
    source.mkdir()
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.7\nsecret\n")
    (source / "escape.pdf").symlink_to(outside / "secret.pdf")
    store = LocalAssetStore(managed, source_roots={"baseline": source})

    for storage_key in (
        "/etc/passwd",
        "managed/../../etc/passwd",
        "source/baseline/../outside/secret.pdf",
        "source/baseline/escape.pdf",
        r"managed\..\secret",
    ):
        try:
            store.path_for(storage_key)
        except AssetPathError:
            continue
        raise AssertionError(f"unsafe storage key was accepted: {storage_key}")
