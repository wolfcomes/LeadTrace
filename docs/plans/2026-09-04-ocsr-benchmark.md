# OCSR Benchmark Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an auditable DECIMER and RDKit benchmark from manually localized structure crops for the 16 text-confirmed JMC optimization paths.

**Architecture:** A project-local CSV declares original-PDF coordinates for one compound structure per row. One Python module validates and renders deterministic PNG crops, configures TensorFlow's NVIDIA library paths, fetches a resumable project-owned DECIMER cache, and records raw DECIMER proposals plus RDKit validation in a separate table. Existing confirmed-path tables remain read-only inputs.

**Tech Stack:** Python 3.12, PyMuPDF, DECIMER 2.8.0, TensorFlow 2.16.1, CUDA, RDKit, Pillow, pytest, curl.

**Repository Note:** This workspace is not a Git repository. Do not run the listed commit commands unless Git is initialized; record relevant command output in the benchmark summary instead.

---

### Task 1: Create An Auditable Crop-Manifest API

**Files:**

- Create: `source_pdfs/分子修改提取_2024_JMC/tests/conftest.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/tests/test_ocsr_benchmark.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/ocsr_benchmark.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/structure_crop_manifest.csv`

**Step 1: Write the failing test**

```python
# tests/conftest.py
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# tests/test_ocsr_benchmark.py
from ocsr_benchmark import CROP_FIELDS, validate_crop_row


def test_crop_manifest_declares_all_auditable_fields(tmp_path):
    row = {
        "crop_id": "CROP-0001", "visual_review_id": "VIS-0001",
        "doi": "10.1000/example", "source_pdf": str(tmp_path / "paper.pdf"),
        "page": "1", "compound_role": "parent", "compound_id": "12d",
        "x0": "10", "y0": "20", "x1": "150", "y1": "180",
        "review_status": "human_localized",
    }
    assert set(CROP_FIELDS) == set(row)
    assert validate_crop_row(row, page_count=1) == []
```

**Step 2: Run the test and verify RED**

```bash
cd /data/home/zhangzhiyong/lead_optimization_collection/source_pdfs/分子修改提取_2024_JMC
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
```

Expected: FAIL because `ocsr_benchmark` does not exist.

**Step 3: Implement the minimal API**

```python
# scripts/ocsr_benchmark.py
CROP_FIELDS = (
    "crop_id", "visual_review_id", "doi", "source_pdf", "page", "compound_role",
    "compound_id", "x0", "y0", "x1", "y1", "review_status",
)


def validate_crop_row(row: dict[str, str], page_count: int) -> list[str]:
    missing = [field for field in CROP_FIELDS if not row.get(field, "").strip()]
    if missing:
        return [f"missing fields: {', '.join(missing)}"]
    if row["compound_role"] not in {"parent", "derived"}:
        return ["compound_role must be parent or derived"]
    page = int(row["page"])
    if not 1 <= page <= page_count:
        return ["page is outside source PDF"]
    x0, y0, x1, y1 = (float(row[key]) for key in ("x0", "y0", "x1", "y1"))
    if x1 <= x0 or y1 <= y0:
        return ["crop rectangle has no positive area"]
    return []
```

Create the manifest with no inferred rows:

```csv
crop_id,visual_review_id,doi,source_pdf,page,compound_role,compound_id,x0,y0,x1,y1,review_status
```

**Step 4: Verify GREEN**

Run the Task 1 command again. Expected: PASS.

**Step 5: Commit when Git exists**

```bash
git add tests/conftest.py tests/test_ocsr_benchmark.py scripts/ocsr_benchmark.py 08_ocsr_benchmark/structure_crop_manifest.csv
git commit -m "feat: add OCSR crop-manifest validation"
```

### Task 2: Render Validated Crops From Original PDFs

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_ocsr_benchmark.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/ocsr_benchmark.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/crops/.gitkeep`

**Step 1: Write the failing test**

```python
import fitz
from ocsr_benchmark import render_crop


def test_render_crop_preserves_manifest_identity(tmp_path):
    source = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 30, 120, 130), color=(0, 0, 0))
    document.save(source)
    document.close()
    row = {
        "crop_id": "CROP-0001", "visual_review_id": "VIS-0001", "doi": "10.1000/example",
        "source_pdf": str(source), "page": "1", "compound_role": "parent", "compound_id": "12d",
        "x0": "20", "y0": "30", "x1": "120", "y1": "130", "review_status": "human_localized",
    }
    output = render_crop(row, tmp_path / "crops", dpi=300)
    assert output.name == "CROP-0001_parent_12d.png"
    assert output.is_file() and output.stat().st_size > 0
```

**Step 2: Run the test and verify RED**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py::test_render_crop_preserves_manifest_identity -v
```

Expected: FAIL because `render_crop` does not exist.

**Step 3: Implement deterministic rendering**

```python
from pathlib import Path
import fitz


def render_crop(row: dict[str, str], output_dir: Path, dpi: int = 300) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(row["source_pdf"])
    try:
        page = document[int(row["page"]) - 1]
        rectangle = fitz.Rect(*(float(row[key]) for key in ("x0", "y0", "x1", "y1")))
        output = output_dir / f"{row['crop_id']}_{row['compound_role']}_{row['compound_id']}.png"
        page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rectangle, alpha=False).save(output)
        return output
    finally:
        document.close()
```

Add `render` and `validate-manifest` CLI subcommands. They must refuse to render if any manifest row is invalid and must not replace an existing crop unless `--replace` is supplied.

**Step 4: Verify GREEN and empty-manifest behavior**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py validate-manifest
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py render
```

Expected: tests PASS; zero rows and zero crops are reported without error.

### Task 3: Configure And Test The DECIMER GPU Runtime

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_ocsr_benchmark.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/ocsr_benchmark.py`

**Step 1: Write the failing test**

```python
from ocsr_benchmark import compose_library_path


def test_compose_library_path_deduplicates_and_keeps_system_path(tmp_path):
    first = tmp_path / "nvidia" / "cublas" / "lib"
    second = tmp_path / "nvidia" / "cudnn" / "lib"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert compose_library_path([first, second, first], "/system/lib").split(":") == [
        str(first), str(second), "/system/lib"
    ]
```

**Step 2: Run the test and verify RED**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py::test_compose_library_path_deduplicates_and_keeps_system_path -v
```

Expected: FAIL because `compose_library_path` does not exist.

**Step 3: Implement runtime setup before TensorFlow import**

```python
import os


def compose_library_path(library_dirs: list[Path], existing: str) -> str:
    entries = [str(path) for path in library_dirs] + [value for value in existing.split(":") if value]
    return ":".join(dict.fromkeys(entries))


def configure_nvidia_library_path() -> str:
    import nvidia
    library_dirs = sorted(
        path for package_root in nvidia.__path__
        for path in Path(package_root).glob("*/lib") if path.is_dir()
    )
    value = compose_library_path(library_dirs, os.environ.get("LD_LIBRARY_PATH", ""))
    os.environ["LD_LIBRARY_PATH"] = value
    return value
```

Add `gpu-probe`. It must call `configure_nvidia_library_path()` before importing TensorFlow or DECIMER, require one logical GPU, run a matrix multiplication on `/GPU:0`, and return nonzero on CPU fallback.

**Step 4: Verify GREEN and actual GPU execution**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py gpu-probe
```

Expected: all tests PASS and the probe names `NVIDIA GeForce RTX 2080 Ti` with a finite matrix-sum result.

### Task 4: Fetch And Validate The DECIMER Model Cache

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_ocsr_benchmark.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/ocsr_benchmark.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/decimer_model/.gitignore`

**Step 1: Write the failing test**

```python
from zipfile import ZipFile
from ocsr_benchmark import validate_decimer_archive


def test_validate_decimer_archive_requires_readable_expected_zip(tmp_path):
    archive = tmp_path / "models.zip"
    archive.write_bytes(b"not a zip")
    assert validate_decimer_archive(archive) == "archive is not a readable ZIP file"
    with ZipFile(archive, "w") as handle:
        handle.writestr("DECIMER_model/saved_model.pb", "placeholder")
        handle.writestr("DECIMER_HandDrawn_model/saved_model.pb", "placeholder")
    assert validate_decimer_archive(archive) is None
```

**Step 2: Run the test and verify RED**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py::test_validate_decimer_archive_requires_readable_expected_zip -v
```

Expected: FAIL because `validate_decimer_archive` does not exist.

**Step 3: Implement a resumable project-owned download**

Implement `download-model` using `subprocess.run` with exactly:

```python
[
    "curl", "--fail", "--location", "--continue-at", "-",
    "--output", str(archive),
    "https://zenodo.org/records/8300489/files/models.zip",
]
```

Validate with `zipfile.ZipFile` before extraction. Extract only under `08_ocsr_benchmark/decimer_model`, reject the cache unless both `DECIMER_model/saved_model.pb` and `DECIMER_HandDrawn_model/saved_model.pb` exist, and retain a partial archive for a later continuation. Set `PYSTOW_HOME` to that directory before importing DECIMER.

**Step 4: Verify GREEN and download the model**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py download-model
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py model-probe
```

Expected: tests PASS; a valid local model cache is created without a subsequent network download during `model-probe`.

### Task 5: Curate And Render Only Reviewed Compound Structures

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/structure_crop_manifest.csv`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/curation_notes.md`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/crops/*.png`

**Step 1: Record the review rules**

Write `curation_notes.md` with these rules:

```markdown
- One complete target compound structure per crop; do not use an R-group cell alone.
- Include the compound label only if it does not obscure the structure.
- Exclude reaction arrows, neighboring compounds, protein images, prose, and assay values.
- Record source coordinates in original PDF points, not rendered-image pixels.
- Use `human_localized` only after visually checking the crop and its compound label.
```

**Step 2: Populate reviewed rows only**

For every parent and derived compound in `06_text_confirmed_paths/explicit_text_confirmed_paths.csv`, locate the complete labeled structure in the original PDF. Enter a manifest row only where the association is direct. Record unresolved cases in `curation_notes.md`; do not replace them with generic synthetic intermediates.

**Step 3: Validate, render, and inspect**

```bash
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py validate-manifest
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py render
```

Expected: every declared crop validates and is rendered once. Inspect every PNG; fix only the source rectangle and re-render, never edit a PNG manually.

### Task 6: Run DECIMER And Record RDKit-Validated Proposals

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_ocsr_benchmark.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/ocsr_benchmark.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/ocsr_proposals.csv`
- Create: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/benchmark_summary.json`

**Step 1: Write the failing test**

```python
from ocsr_benchmark import validate_smiles


def test_validate_smiles_retains_raw_value_and_canonicalizes_valid_proposal():
    assert validate_smiles("C(C)O") == {"rdkit_status": "valid", "canonical_smiles": "CCO"}
    assert validate_smiles("not-smiles") == {"rdkit_status": "invalid", "canonical_smiles": ""}
```

**Step 2: Run the test and verify RED**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py::test_validate_smiles_retains_raw_value_and_canonicalizes_valid_proposal -v
```

Expected: FAIL because `validate_smiles` does not exist.

**Step 3: Implement the proposal-only inference path**

```python
from rdkit import Chem


def validate_smiles(raw_smiles: str) -> dict[str, str]:
    molecule = Chem.MolFromSmiles(raw_smiles)
    if molecule is None:
        return {"rdkit_status": "invalid", "canonical_smiles": ""}
    return {"rdkit_status": "valid", "canonical_smiles": Chem.MolToSmiles(molecule, isomericSmiles=True)}
```

Add `infer`. It must require a successful GPU probe in the same process, call `predict_SMILES(crop_path, confidence=True)` once per rendered crop, preserve raw SMILES and token confidence values, add mean/min confidence, RDKit status, canonical SMILES, model version, and set every row to `proposal_requires_human_review`. Write CSV and JSON summary atomically.

**Step 4: Verify GREEN and non-mutation**

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
sha256sum 06_text_confirmed_paths/explicit_text_confirmed_paths.csv > 08_ocsr_benchmark/text_paths_before.sha256
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py infer
sha256sum --check 08_ocsr_benchmark/text_paths_before.sha256
```

Expected: all tests PASS; one proposal row per crop, all marked for human review; `explicit_text_confirmed_paths.csv: OK`.

### Task 7: Manually Evaluate And Document The Pilot

**Files:**

- Modify: `source_pdfs/分子修改提取_2024_JMC/08_ocsr_benchmark/curation_notes.md`
- Modify: `source_pdfs/分子修改提取_2024_JMC/README.md`

**Step 1: Review each proposal against its source crop**

For every row, assess full connectivity, stereochemistry when depicted, charge state, and compound-label agreement. Record invalid-SMILES causes such as a partial structure, multiple structures, prose/arrows, or model failure.

**Step 2: Record results without promoting structures**

Add a review table to `curation_notes.md` with `crop_id`, RDKit status, visual-match status, and correction effort. Do not insert DECIMER or manually corrected SMILES into `06_text_confirmed_paths` during this pilot.

**Step 3: Document the new stage and run final verification**

Add `08_ocsr_benchmark` to README as a proposal-only stage, then run:

```bash
../../../.venv-jmc-ocr/bin/python -m pytest tests/test_ocsr_benchmark.py -v
../../../.venv-jmc-ocr/bin/python scripts/ocsr_benchmark.py gpu-probe
sha256sum --check 08_ocsr_benchmark/text_paths_before.sha256
```

Expected: tests pass, actual GPU execution succeeds, and the input text-confirmed table remains unchanged.

**Step 4: Commit when Git exists**

```bash
git add tests scripts 08_ocsr_benchmark README.md
git commit -m "feat: add auditable DECIMER OCSR benchmark"
```
