from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from leadtrace.ops.ai_prefill.preview_runtime import (
    PreviewRuntime,
    PreviewRuntimeError,
)


INSTANCE_ID = UUID("22222222-2222-4222-8222-222222222222")


def runtime(tmp_path: Path) -> PreviewRuntime:
    return PreviewRuntime(tmp_path / "previews")


def create(runtime: PreviewRuntime) -> Path:
    return runtime.create(
        instance_id=INSTANCE_ID,
        database_name="leadtrace_ap_example_preview",
        database_host="preview-postgres",
        database_port=5432,
        baseline_sha256="b" * 64,
        schema_revision="0026_ai_prefill_preview_receipts",
        asset_root=Path("/var/lib/leadtrace/preview/example/assets"),
        source_root=Path("/srv/leadtrace/source-pdfs"),
        origin="https://preview.example.test",
    )


def test_create_records_incomplete_registry_until_explicit_completion(tmp_path: Path) -> None:
    instance_runtime = runtime(tmp_path)
    path = create(instance_runtime)

    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "initializing"

    completed = instance_runtime.complete(
        INSTANCE_ID,
        commit="abc123",
        lockfile_sha256="c" * 64,
    )
    assert completed["state"] == "ready"
    assert completed["commit"] == "abc123"
    assert completed["lockfile_sha256"] == "c" * 64


def test_create_rejects_existing_or_non_preview_targets(tmp_path: Path) -> None:
    instance_runtime = runtime(tmp_path)
    create(instance_runtime)

    with pytest.raises(PreviewRuntimeError, match="already exists"):
        create(instance_runtime)

    with pytest.raises(PreviewRuntimeError, match="_preview"):
        instance_runtime.create(
            instance_id=UUID("33333333-3333-4333-8333-333333333333"),
            database_name="leadtrace",
            database_host="preview-postgres",
            database_port=5432,
            baseline_sha256="b" * 64,
            schema_revision="0026_ai_prefill_preview_receipts",
            asset_root=Path("/var/lib/leadtrace/preview/example/assets"),
            source_root=Path("/srv/leadtrace/source-pdfs"),
            origin="https://preview.example.test",
        )


def test_registry_never_serializes_runtime_secrets(tmp_path: Path) -> None:
    instance_runtime = runtime(tmp_path)
    path = create(instance_runtime)
    content = path.read_text(encoding="utf-8")

    assert "password" not in content.casefold()
    assert "secret" not in content.casefold()


def test_runtime_registry_can_be_verified_by_the_backend(tmp_path):
    from app.ai_prefill.preview_identity import read_preview_registry
    from app.config import Settings
    instance_runtime = runtime(tmp_path)
    assets, sources, artifacts = (tmp_path / name for name in ("assets", "sources", "artifacts"))
    path = instance_runtime.create(
        instance_id=INSTANCE_ID, database_name="runtime_preview",
        database_host="preview-postgres", database_port=5432,
        baseline_sha256="b" * 64, schema_revision="0026_ai_prefill_preview_receipts",
        asset_root=assets, source_root=sources, artifact_root=artifacts,
        origin="https://preview.example.test",
    )
    instance_runtime.complete(INSTANCE_ID, commit="abc123", lockfile_sha256="c" * 64)
    settings = Settings(
        _env_file=None, environment="preview",
        database_url="postgresql+psycopg://preview@preview-postgres/runtime_preview",
        asset_root=assets, source_roots={"source_pdfs": sources},
        preview_artifact_root=artifacts, preview_registry_path=path,
        preview_instance_id=INSTANCE_ID, preview_baseline_sha256="b" * 64,
    )
    registry = read_preview_registry(settings)
    assert registry.artifact_root == artifacts
    assert registry.instance_id == INSTANCE_ID
