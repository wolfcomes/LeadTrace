"""Runtime Preview identity must bind settings, files and the connected DB."""
from dataclasses import replace
from pathlib import Path

import pytest

from app.ai_prefill.preview_identity import PreviewIdentityError, verify_preview_identity
from app.config import Settings
from .test_preview_identity import BASELINE, INSTANCE_ID, marker, registry


def settings() -> Settings:
    return Settings(
        _env_file=None, environment="preview",
        database_url="postgresql+psycopg://preview:secret@preview-postgres/leadtrace_ap_example_preview",
        asset_root="/var/lib/leadtrace/preview/example/assets",
        source_roots={"source_pdfs": "/srv/leadtrace/source-pdfs"},
        preview_artifact_root="/var/lib/leadtrace/preview/example/artifacts",
        preview_registry_path="/var/lib/leadtrace/registry/registry.json",
        preview_instance_id=INSTANCE_ID, preview_baseline_sha256=BASELINE,
    )


@pytest.mark.parametrize(("field", "value"), [
    ("database_host", "other-postgres"),
    ("database_port", 6432),
    ("source_root", Path("/srv/other-pdfs")),
])
def test_runtime_rejects_registry_endpoint_or_source_drift(field, value):
    with pytest.raises(PreviewIdentityError):
        verify_preview_identity(
            settings(), registry=replace(registry(), **{field: value}), marker=marker(),
            database_name="leadtrace_ap_example_preview",
            schema_revision="0026_ai_prefill_preview_receipts", asset_root=registry().asset_root,
        )


def test_runtime_rejects_connected_database_different_from_configuration():
    with pytest.raises(PreviewIdentityError):
        verify_preview_identity(
            settings(), registry=replace(registry(), database_name="different_preview"),
            marker=marker(), database_name="different_preview",
            schema_revision="0026_ai_prefill_preview_receipts", asset_root=registry().asset_root,
        )


@pytest.mark.parametrize("problem", ["missing", "relative", "symlink", "parent_symlink", "source_overlap", "unknown_source"])
def test_preview_settings_reject_unsafe_paths(tmp_path, problem):
    from app.ai_prefill.preview_identity import require_preview_settings
    value = settings()
    if problem == "missing":
        value.preview_registry_path = None
    elif problem == "relative":
        value.preview_registry_path = Path("registry.json")
    elif problem in {"symlink", "parent_symlink"}:
        real = tmp_path / "real"
        real.mkdir()
        (real / "registry.json").write_text("{}")
        if problem == "symlink":
            link = tmp_path / "link.json"
            link.symlink_to(real / "registry.json")
            value.preview_registry_path = link
        else:
            link = tmp_path / "link"
            link.symlink_to(real, target_is_directory=True)
            value.preview_registry_path = link / "registry.json"
    elif problem == "source_overlap":
        value.asset_root = value.source_roots["source_pdfs"] / "assets"
    else:
        value.source_roots["other"] = tmp_path / "other"
    with pytest.raises(PreviewIdentityError):
        require_preview_settings(value)


@pytest.mark.parametrize("content", [b"{", b"x" * 65537, b'{"schema_version":1,"state":"initializing"}'])
def test_invalid_registry_is_rejected_without_filesystem_writes(tmp_path, content):
    from app.ai_prefill.preview_identity import read_preview_registry
    value = settings()
    value.preview_registry_path = tmp_path / "registry.json"
    value.preview_registry_path.write_bytes(content)
    before = list(tmp_path.iterdir())
    with pytest.raises(PreviewIdentityError):
        read_preview_registry(value)
    assert list(tmp_path.iterdir()) == before
    assert value.preview_registry_path.read_bytes() == content


def test_router_registration_does_not_create_artifact_directory(tmp_path):
    from app.ai_prefill.assistance_router import create_assistance_router
    value = settings()
    value.preview_artifact_root = tmp_path / "must-not-be-created"
    assert create_assistance_router(value).routes
    assert not value.preview_artifact_root.exists()
