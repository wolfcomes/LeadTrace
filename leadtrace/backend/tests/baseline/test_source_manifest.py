from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from leadtrace.ops.baseline.build_manifest import build_manifest
from leadtrace.ops.baseline.verify_manifest import verify_manifest


def _set_mtime(path: Path, nanoseconds: int) -> None:
    os.utime(path, ns=(nanoseconds, nanoseconds))


def test_manifest_is_deterministic_and_read_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = source / "paper.pdf"
    original.write_bytes(b"%PDF-test")
    _set_mtime(original, 1_700_000_000_123_456_789)
    output = tmp_path / "manifest.json"

    build_manifest([source], output, workspace_root=tmp_path)
    first = output.read_bytes()
    before = original.stat()
    build_manifest([source], output, workspace_root=tmp_path)

    assert output.read_bytes() == first
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    assert original.read_bytes() == b"%PDF-test"


def test_manifest_records_stable_metadata_in_relative_path_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "中文 folder"
    nested.mkdir(parents=True)
    (source / "z.csv").write_text("id\n1\n", encoding="utf-8")
    (nested / "a.pdf").write_bytes(b"%PDF-a")
    output = tmp_path / "manifest.json"

    build_manifest([source], output, workspace_root=tmp_path)

    payload = json.loads(output.read_text(encoding="utf-8"))
    files = payload["files"]
    assert [row["path"] for row in files] == [
        "source/z.csv",
        "source/中文 folder/a.pdf",
    ]
    assert files[0]["byte_size"] == 5
    assert len(files[0]["sha256"]) == 64
    assert files[0]["category"] == "structured_data"
    assert files[1]["category"] == "pdf"


@pytest.mark.parametrize(
    "relative_path",
    [
        ".pytest_cache/cache.json",
        ".venv-test/lib/tool.py",
        "node_modules/pkg/index.js",
        "__pycache__/module.pyc",
        "service.log",
        "temporary.tmp",
    ],
)
def test_manifest_excludes_runtime_and_temporary_files(
    tmp_path: Path,
    relative_path: str,
) -> None:
    source = tmp_path / "source"
    excluded = source / relative_path
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_bytes(b"runtime")
    retained = source / "paper.pdf"
    retained.write_bytes(b"%PDF")
    output = tmp_path / "manifest.json"

    build_manifest([source], output, workspace_root=tmp_path)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [row["path"] for row in payload["files"]] == ["source/paper.pdf"]


def test_manifest_rejects_output_below_a_source_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="outside every source root"):
        build_manifest(
            [source],
            source / "manifest.json",
            workspace_root=tmp_path,
        )


def test_verifier_reports_changed_missing_and_unexpected_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    changed = source / "changed.csv"
    changed.write_text("before", encoding="utf-8")
    missing = source / "missing.pdf"
    missing.write_bytes(b"missing-later")
    manifest = tmp_path / "manifest.json"
    build_manifest([source], manifest, workspace_root=tmp_path)

    changed.write_text("after", encoding="utf-8")
    missing.unlink()
    (source / "unexpected.json").write_text("{}", encoding="utf-8")

    result = verify_manifest(manifest)

    assert result.counts == {"changed": 1, "missing": 1, "unexpected": 1}
    assert result.ok is False


def test_verifier_can_run_as_the_documented_script(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "paper.pdf").write_bytes(b"%PDF")
    manifest = tmp_path / "manifest.json"
    build_manifest([source], manifest, workspace_root=tmp_path)
    repository_root = Path(__file__).resolve().parents[4]

    completed = subprocess.run(
        [
            sys.executable,
            str(repository_root / "leadtrace/ops/baseline/verify_manifest.py"),
            str(manifest),
        ],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "changed=0 missing=0 unexpected=0"
