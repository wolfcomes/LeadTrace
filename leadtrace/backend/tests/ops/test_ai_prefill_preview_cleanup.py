import json
from pathlib import Path
from uuid import UUID

import pytest

from leadtrace.ops.ai_prefill.preview_cleanup import (
    PreviewCleanup,
    PreviewCleanupError,
)
from leadtrace.ops.ai_prefill.cli import main
from leadtrace.ops.ai_prefill.preview_runtime import PreviewRuntime


INSTANCE_ID = UUID("22222222-2222-4222-8222-222222222222")


def make_runtime(tmp_path: Path) -> tuple[PreviewRuntime, Path, Path]:
    runtime = PreviewRuntime(tmp_path / "registry")
    assets = tmp_path / "instances" / str(INSTANCE_ID) / "assets"
    assets.mkdir(parents=True)
    (assets / "crop.png").write_bytes(b"crop")
    runtime.create(
        instance_id=INSTANCE_ID,
        database_name="leadtrace_example_preview",
        database_host="postgres",
        database_port=5432,
        baseline_sha256="b" * 64,
        schema_revision="0026_ai_prefill_preview_receipts",
        asset_root=assets,
        source_root=tmp_path / "shared-source",
        origin="https://preview.example.test",
    )
    runtime.complete(INSTANCE_ID, commit="abc123", lockfile_sha256="c" * 64)
    return runtime, assets, tmp_path / "archive"


def test_cleanup_requires_archive_before_destroy(tmp_path: Path) -> None:
    runtime, assets, archive = make_runtime(tmp_path)
    cleanup = PreviewCleanup(runtime, archive)

    plan = cleanup.plan(INSTANCE_ID)
    assert plan.instance_id == str(INSTANCE_ID)
    assert plan.asset_root == str(assets)

    with pytest.raises(PreviewCleanupError, match="archive"):
        cleanup.destroy(INSTANCE_ID)
    assert assets.exists()


def test_cleanup_archives_then_deletes_only_exact_asset_root(tmp_path: Path) -> None:
    runtime, assets, archive = make_runtime(tmp_path)
    sibling = assets.parent / "other-instance"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    cleanup = PreviewCleanup(runtime, archive)

    artifact = cleanup.archive(INSTANCE_ID, receipts={"application": "receipt-1"})
    assert artifact.exists()
    assert json.loads(artifact.read_text(encoding="utf-8"))["instance_id"] == str(INSTANCE_ID)

    cleanup.destroy(INSTANCE_ID)

    assert not assets.exists()
    assert sibling.exists()
    assert (sibling / "keep.txt").exists()
    assert runtime.read(INSTANCE_ID)["state"] == "archived"


def test_cleanup_rejects_registry_asset_root_symlink(tmp_path: Path) -> None:
    runtime, assets, archive = make_runtime(tmp_path)
    registry_path = runtime._path(INSTANCE_ID)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["asset_root"] = str(tmp_path / "outside")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    cleanup = PreviewCleanup(runtime, archive)
    cleanup.archive(INSTANCE_ID, receipts={})

    with pytest.raises(PreviewCleanupError, match="managed asset"):
        cleanup.destroy(INSTANCE_ID)
    assert outside.exists()
    assert assets.exists()


def test_cleanup_cli_requires_exact_instance_confirmation(tmp_path: Path, capsys) -> None:
    runtime, _assets, archive = make_runtime(tmp_path)
    registry_root = tmp_path / "registry"

    assert main(
        [
            "preview",
            "destroy",
            "--registry-root",
            str(registry_root),
            "--archive-root",
            str(archive),
            "--instance-id",
            str(INSTANCE_ID),
            "--confirm-instance",
            "different",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INSTANCE_CONFIRMATION_REQUIRED"


def test_cleanup_rechecks_registry_against_archived_snapshot(tmp_path: Path) -> None:
    runtime, assets, archive = make_runtime(tmp_path)
    cleanup = PreviewCleanup(runtime, archive)
    cleanup.archive(INSTANCE_ID, receipts={})
    registry_path = runtime._path(INSTANCE_ID)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["asset_root"] = str(tmp_path / "other" / str(INSTANCE_ID) / "assets")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(PreviewCleanupError, match="registry changed"):
        cleanup.destroy(INSTANCE_ID)
    assert assets.exists()


def test_legacy_cleanup_refuses_database_backed_native_instance(tmp_path):
    runtime, assets, archive = make_runtime(tmp_path)
    registry = runtime.read(INSTANCE_ID)
    registry['management'] = 'native-v1'
    runtime._write(runtime._path(INSTANCE_ID), registry, create=False)
    cleanup = PreviewCleanup(runtime, archive)
    with pytest.raises(PreviewCleanupError, match='database-backed'):
        cleanup.archive(INSTANCE_ID, receipts={})
    assert runtime.read(INSTANCE_ID)['state'] == 'ready'
    assert assets.exists()
