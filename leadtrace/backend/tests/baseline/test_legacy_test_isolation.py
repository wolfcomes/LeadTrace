from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
LEGACY_ROOT = REPOSITORY_ROOT / "source_pdfs" / "分子修改提取_2024_JMC"
AUTO_FILL = LEGACY_ROOT / "09_paper_review" / "auto_fill"
PROTECTED_OUTPUTS = (
    "compound_lineage_summary.json",
    "compound_entities.csv",
    "compound_lineage_edges.csv",
    "compound_lineage_evidence.csv",
    "compound_activities.csv",
    "confirmed_compound_structures.csv",
    "molecule_ocr_variant_summary.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_legacy_mirror(tmp_path: Path) -> Path:
    mirror = tmp_path / "legacy_project"
    scripts = mirror / "scripts"
    tests = mirror / "tests"
    auto_fill = mirror / "09_paper_review" / "auto_fill"
    scripts.mkdir(parents=True)
    tests.mkdir()
    auto_fill.mkdir(parents=True)
    shutil.copy2(
        LEGACY_ROOT / "scripts" / "prepare_molecule_ocr_variants.py",
        scripts,
    )
    shutil.copy2(
        LEGACY_ROOT / "tests" / "test_prepare_molecule_ocr_variants.py",
        tests,
    )
    shutil.copy2(LEGACY_ROOT / "tests" / "conftest.py", tests)
    for filename in PROTECTED_OUTPUTS:
        shutil.copy2(AUTO_FILL / filename, auto_fill)
    return mirror


def test_representative_legacy_test_does_not_modify_protected_outputs(
    tmp_path: Path,
) -> None:
    mirror = _prepare_legacy_mirror(tmp_path)
    protected = [mirror / "09_paper_review" / "auto_fill" / name for name in PROTECTED_OUTPUTS]
    before = {path.name: _sha256(path) for path in protected}
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(mirror / "scripts")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_prepare_molecule_ocr_variants.py::test_snapshot_writes_original_and_label_free_variants_with_parent_provenance",
        ],
        cwd=mirror,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    after = {path.name: _sha256(path) for path in protected}
    changed = sorted(name for name in before if before[name] != after[name])
    assert changed == []
