import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from zipfile import ZipFile

import fitz
import pytest

import ocsr_benchmark
from ocsr_benchmark import (
    CROP_FIELDS,
    compose_library_path,
    configure_decimer_cache,
    configure_nvidia_library_path,
    download_decimer_models,
    extract_decimer_archives,
    infer_proposals,
    main,
    probe_decimer_models,
    render_crop,
    PROPOSAL_FIELDS,
    validate_decimer_cache,
    validate_decimer_archive,
    validate_handdrawn_archive,
    validate_crop_row,
    validate_manifest,
    validate_smiles,
)


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "08_ocsr_benchmark"
    / "structure_crop_manifest.csv"
)
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ocsr_benchmark.py"


def valid_crop_row(tmp_path: Path) -> dict[str, str]:
    return {
        "crop_id": "CROP-0001",
        "visual_review_id": "VIS-0001",
        "doi": "10.1000/example",
        "source_pdf": str(tmp_path / "paper.pdf"),
        "page": "1",
        "compound_role": "parent",
        "compound_id": "12d",
        "x0": "10",
        "y0": "20",
        "x1": "150",
        "y1": "180",
        "review_status": "human_localized",
    }


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as manifest:
        writer = csv.DictWriter(manifest, fieldnames=CROP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def create_source_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page(width=200, height=200)
    document.save(path)
    document.close()


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_compose_library_path_prepends_unique_nvidia_paths_without_mutating_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "nvidia" / "cublas" / "lib"
    second = tmp_path / "nvidia" / "cudnn" / "lib"
    monkeypatch.setenv("LD_LIBRARY_PATH", "/unchanged")

    value = compose_library_path(
        [first, second, first],
        f"{second}:/system/lib::{first}:/alternate/lib:/system/lib",
    )

    assert value.split(":") == [
        str(first),
        str(second),
        "/system/lib",
        "/alternate/lib",
    ]
    assert os.environ["LD_LIBRARY_PATH"] == "/unchanged"


def test_configure_nvidia_library_path_discovers_and_prepends_nested_lib_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root = tmp_path / "nvidia"
    cublas_lib = package_root / "cublas" / "lib"
    cudnn_lib = package_root / "cudnn" / "lib"
    cublas_lib.mkdir(parents=True)
    cudnn_lib.mkdir(parents=True)
    nvidia = types.ModuleType("nvidia")
    nvidia.__path__ = [str(package_root)]
    monkeypatch.setitem(sys.modules, "nvidia", nvidia)
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{cudnn_lib}:/system/lib")

    value = configure_nvidia_library_path()

    assert value.split(":") == [str(cublas_lib), str(cudnn_lib), "/system/lib"]
    assert os.environ["LD_LIBRARY_PATH"] == value


def test_gpu_probe_returns_nonzero_when_tensorflow_has_no_logical_gpu(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nvidia = types.ModuleType("nvidia")
    nvidia.__path__ = []
    tensorflow = types.ModuleType("tensorflow")
    tensorflow.config = types.SimpleNamespace(list_logical_devices=lambda _: [])
    monkeypatch.setitem(sys.modules, "nvidia", nvidia)
    monkeypatch.setitem(sys.modules, "tensorflow", tensorflow)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.setenv("OCSR_GPU_PROBE_REEXECUTED", "1")

    assert main(["gpu-probe"]) == 1

    captured = capsys.readouterr()
    assert "no logical GPU available" in captured.err


def test_gpu_probe_relaunches_before_tensorflow_import_with_configured_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root = tmp_path / "nvidia"
    library_dir = package_root / "cudnn" / "lib"
    library_dir.mkdir(parents=True)
    nvidia = types.ModuleType("nvidia")
    nvidia.__path__ = [str(package_root)]
    tensorflow = types.ModuleType("tensorflow")
    tensorflow.config = types.SimpleNamespace(
        list_logical_devices=lambda _: pytest.fail(
            "TensorFlow accessed before relaunch"
        )
    )
    calls: list[tuple[list[str], dict[str, str], bool]] = []

    def run(command: list[str], *, env: dict[str, str], check: bool) -> object:
        calls.append((command, env, check))
        return types.SimpleNamespace(returncode=23)

    monkeypatch.setitem(sys.modules, "nvidia", nvidia)
    monkeypatch.setitem(sys.modules, "tensorflow", tensorflow)
    monkeypatch.setattr(
        ocsr_benchmark, "subprocess", types.SimpleNamespace(run=run), raising=False
    )
    monkeypatch.setenv("LD_LIBRARY_PATH", "/system/lib")
    monkeypatch.delenv("OCSR_GPU_PROBE_REEXECUTED", raising=False)

    assert main(["gpu-probe"]) == 23
    assert calls == [
        (
            [sys.executable, str(SCRIPT_PATH), "gpu-probe"],
            {
                **os.environ,
                "LD_LIBRARY_PATH": f"{library_dir}:/system/lib",
                "OCSR_GPU_PROBE_REEXECUTED": "1",
            },
            False,
        )
    ]


def test_validate_decimer_archive_requires_standard_model_and_tokenizer(tmp_path: Path) -> None:
    archive = tmp_path / "models.zip"
    archive.write_bytes(b"not a zip")
    assert validate_decimer_archive(archive) == "archive is not a readable ZIP file"

    with ZipFile(archive, "w") as handle:
        handle.writestr("DECIMER_model/saved_model.pb", "placeholder")
    assert validate_decimer_archive(archive) == "archive is missing DECIMER_model/assets/tokenizer_SMILES.pkl"

    with ZipFile(archive, "w") as handle:
        handle.writestr("DECIMER_model/saved_model.pb", "placeholder")
        handle.writestr("DECIMER_model/assets/tokenizer_SMILES.pkl", "placeholder")
    assert validate_decimer_archive(archive) is None


def test_validate_decimer_cache_requires_both_decimer_runtime_models(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "decimer-model"
    (cache / "DECIMER_model" / "assets").mkdir(parents=True)
    (cache / "DECIMER_model" / "saved_model.pb").write_bytes(b"model")
    (cache / "DECIMER_model" / "assets" / "tokenizer_SMILES.pkl").write_bytes(
        b"tokenizer"
    )

    assert validate_decimer_cache(cache) == (
        "cache is missing DECIMER_HandDrawn_model/saved_model.pb"
    )

    (cache / "DECIMER_HandDrawn_model" / "assets").mkdir(parents=True)
    (cache / "DECIMER_HandDrawn_model" / "saved_model.pb").write_bytes(b"model")
    (cache / "DECIMER_HandDrawn_model" / "assets" / "tokenizer_pubchem.pkl").write_bytes(
        b"tokenizer"
    )
    assert validate_decimer_cache(cache) is None


def test_extract_decimer_archives_installs_both_model_trees(tmp_path: Path) -> None:
    standard_archive = tmp_path / "standard.zip"
    handdrawn_archive = tmp_path / "handdrawn.zip"
    with ZipFile(standard_archive, "w") as handle:
        handle.writestr("DECIMER_model/saved_model.pb", "standard model")
        handle.writestr("DECIMER_model/assets/tokenizer_SMILES.pkl", "standard tokenizer")
    with ZipFile(handdrawn_archive, "w") as handle:
        handle.writestr("DECIMER_HandDrawn_model/saved_model.pb", "hand model")
        handle.writestr(
            "DECIMER_HandDrawn_model/assets/tokenizer_pubchem.pkl", "hand tokenizer"
        )

    cache = tmp_path / "cache"
    extract_decimer_archives(standard_archive, handdrawn_archive, cache)

    assert validate_decimer_cache(cache) is None
    assert (cache / "DECIMER_model" / ".model_url").is_file()
    assert (cache / "DECIMER_HandDrawn_model" / ".model_url").is_file()


def test_configure_decimer_cache_sets_absolute_decimer_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "nested" / "decimer-model"
    monkeypatch.delenv("DECIMER-V2_HOME", raising=False)

    value = configure_decimer_cache(cache)

    assert value == str(cache.resolve())
    assert os.environ["DECIMER-V2_HOME"] == str(cache.resolve())


def test_download_decimer_models_fetches_missing_archives_and_extracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> object:
        calls.append(command)
        archive = Path(command[command.index("--output") + 1])
        with ZipFile(archive, "w") as handle:
            if archive.name == "models.zip":
                handle.writestr("DECIMER_model/saved_model.pb", "standard model")
                handle.writestr(
                    "DECIMER_model/assets/tokenizer_SMILES.pkl", "standard tokenizer"
                )
            else:
                handle.writestr(
                    "DECIMER_HandDrawn_model/saved_model.pb", "hand model"
                )
                handle.writestr(
                    "DECIMER_HandDrawn_model/assets/tokenizer_pubchem.pkl",
                    "hand tokenizer",
                )
        assert check is True
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(ocsr_benchmark.subprocess, "run", fake_run)
    cache = tmp_path / "cache"

    result = download_decimer_models(cache)

    assert result == cache
    assert len(calls) == 2
    assert calls[0] == [
        "curl",
        "--fail",
        "--location",
        "--continue-at",
        "-",
        "--output",
        str(cache / "models.zip"),
        ocsr_benchmark.DECIMER_MODEL_URL,
    ]
    assert calls[1][-1] == ocsr_benchmark.DECIMER_HANDDRAWN_MODEL_URL
    assert validate_decimer_cache(cache) is None


def test_download_decimer_models_reuses_valid_local_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    with ZipFile(cache / "models.zip", "w") as handle:
        handle.writestr("DECIMER_model/saved_model.pb", "standard model")
        handle.writestr(
            "DECIMER_model/assets/tokenizer_SMILES.pkl", "standard tokenizer"
        )
    with ZipFile(cache / "DECIMER_HandDrawn_model.zip", "w") as handle:
        handle.writestr("DECIMER_HandDrawn_model/saved_model.pb", "hand model")
        handle.writestr(
            "DECIMER_HandDrawn_model/assets/tokenizer_pubchem.pkl", "hand tokenizer"
        )

    def fail_if_downloaded(*args: object, **kwargs: object) -> object:
        raise AssertionError("valid local archive should not be downloaded")

    monkeypatch.setattr(ocsr_benchmark.subprocess, "run", fail_if_downloaded)

    download_decimer_models(cache)

    assert validate_decimer_cache(cache) is None


def test_download_model_cli_installs_into_requested_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"

    def fake_download(requested_cache: Path) -> Path:
        assert requested_cache == cache
        return cache

    monkeypatch.setattr(ocsr_benchmark, "download_decimer_models", fake_download)

    assert main(["download-model", "--cache-dir", str(cache)]) == 0
    assert f"Installed DECIMER models in {cache}" in capsys.readouterr().out


def test_probe_decimer_models_checks_gpu_cache_and_loaded_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    events: list[str] = []
    monkeypatch.setattr(ocsr_benchmark, "configure_nvidia_library_path", lambda: "gpu-libs")
    monkeypatch.setattr(
        ocsr_benchmark,
        "probe_gpu",
        lambda: (events.append("gpu") or "Test GPU", 134.0),
    )
    monkeypatch.setattr(ocsr_benchmark, "validate_decimer_cache", lambda _: None)
    runtime = types.ModuleType("DECIMER.decimer")
    runtime.DECIMER_V2 = object()
    runtime.DECIMER_Hand_drawn = object()
    package = types.ModuleType("DECIMER")
    package.__path__ = []
    package.__version__ = "2.7.2"
    package.decimer = runtime
    monkeypatch.setitem(sys.modules, "DECIMER", package)
    monkeypatch.setitem(sys.modules, "DECIMER.decimer", runtime)
    original_import = ocsr_benchmark.importlib.import_module

    def import_module(name: str) -> object:
        if name.startswith("DECIMER"):
            events.append("import")
        return original_import(name)

    monkeypatch.setattr(ocsr_benchmark.importlib, "import_module", import_module)

    result = probe_decimer_models(cache)

    assert result == {
        "cache": str(cache.resolve()),
        "version": "2.7.2",
        "gpu": "Test GPU",
        "matrix_sum": 134.0,
    }
    assert events == ["import", "import", "gpu"]
    assert os.environ["DECIMER-V2_HOME"] == str(cache.resolve())


def test_model_probe_cli_reports_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv(ocsr_benchmark.MODEL_PROBE_REEXECUTED, "1")
    monkeypatch.setattr(
        ocsr_benchmark,
        "probe_decimer_models",
        lambda requested_cache: {
            "cache": str(requested_cache),
            "version": "2.7.2",
            "gpu": "Test GPU",
            "matrix_sum": 134.0,
        },
    )

    assert main(["model-probe", "--cache-dir", str(cache)]) == 0
    output = capsys.readouterr().out
    assert f"DECIMER cache: {cache}" in output
    assert "DECIMER version: 2.7.2" in output
    assert "GPU: Test GPU" in output
    assert "Matrix sum: 134.0" in output


def test_model_probe_cli_relaunches_with_nvidia_libraries_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    calls: list[tuple[list[str], dict[str, str], bool]] = []
    monkeypatch.setattr(ocsr_benchmark, "configure_nvidia_library_path", lambda: "gpu-libs")
    monkeypatch.delenv(ocsr_benchmark.MODEL_PROBE_REEXECUTED, raising=False)

    def run(command: list[str], *, env: dict[str, str], check: bool) -> object:
        calls.append((command, env, check))
        return types.SimpleNamespace(returncode=41)

    monkeypatch.setattr(ocsr_benchmark.subprocess, "run", run)

    assert main(["model-probe", "--cache-dir", str(cache)]) == 41
    assert calls == [
        (
            [
                sys.executable,
                str(SCRIPT_PATH),
                "model-probe",
                "--cache-dir",
                str(cache),
            ],
            {
                **os.environ,
                "LD_LIBRARY_PATH": "gpu-libs",
                ocsr_benchmark.MODEL_PROBE_REEXECUTED: "1",
            },
            False,
        )
    ]


def test_validate_smiles_canonicalizes_valid_proposals_and_marks_invalid_ones() -> None:
    assert validate_smiles("C(C)O") == {
        "rdkit_status": "valid",
        "canonical_smiles": "CCO",
    }
    assert validate_smiles("not-smiles") == {
        "rdkit_status": "invalid",
        "canonical_smiles": "",
    }


def test_infer_proposals_records_decimer_and_rdkit_results_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    manifest_row = valid_crop_row(tmp_path)
    manifest_row["source_pdf"] = str(source_pdf)
    manifest = tmp_path / "manifest.csv"
    write_manifest(manifest, [manifest_row])
    crops_dir = tmp_path / "crops"
    crop_path = render_crop(manifest_row, crops_dir)
    output_csv = tmp_path / "ocsr_proposals.csv"
    summary_json = tmp_path / "benchmark_summary.json"
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        ocsr_benchmark,
        "probe_decimer_models",
        lambda cache: {
            "cache": str(cache.resolve()),
            "version": "2.7.2",
            "gpu": "Test GPU",
            "matrix_sum": 134.0,
        },
    )
    decimer = types.ModuleType("DECIMER")
    decimer.__version__ = "2.7.2"

    def predict_smiles(image_path: str, *, confidence: bool = False) -> tuple[str, list[tuple[str, float]]]:
        calls.append((image_path, confidence))
        return "C(C)O", [("C", 0.8), ("C", 0.9), ("O", 1.0)]

    decimer.predict_SMILES = predict_smiles
    monkeypatch.setitem(sys.modules, "DECIMER", decimer)

    summary = infer_proposals(
        manifest,
        crops_dir,
        tmp_path / "model-cache",
        output_csv,
        summary_json,
    )

    assert calls == [(str(crop_path), True)]
    assert summary["crop_count"] == 1
    assert summary["valid_rdkit_count"] == 1
    with output_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == list(PROPOSAL_FIELDS)
    assert rows[0]["raw_smiles"] == "C(C)O"
    assert json.loads(rows[0]["token_confidences"]) == [
        {"token": "C", "confidence": 0.8},
        {"token": "C", "confidence": 0.9},
        {"token": "O", "confidence": 1.0},
    ]
    assert rows[0]["mean_token_confidence"] == "0.9"
    assert rows[0]["min_token_confidence"] == "0.8"
    assert rows[0]["rdkit_status"] == "valid"
    assert rows[0]["canonical_smiles"] == "CCO"
    assert rows[0]["review_status"] == "proposal_requires_human_review"
    assert json.loads(summary_json.read_text(encoding="utf-8"))["crop_count"] == 1


def test_infer_cli_relaunches_with_nvidia_libraries_before_decimer_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocsr_benchmark, "configure_nvidia_library_path", lambda: "gpu-libs")
    monkeypatch.delenv(ocsr_benchmark.INFER_REEXECUTED, raising=False)
    calls: list[tuple[list[str], dict[str, str], bool]] = []

    def run(command: list[str], *, env: dict[str, str], check: bool) -> object:
        calls.append((command, env, check))
        return types.SimpleNamespace(returncode=43)

    monkeypatch.setattr(ocsr_benchmark.subprocess, "run", run)
    manifest = tmp_path / "manifest.csv"
    crops = tmp_path / "crops"
    cache = tmp_path / "cache"
    output = tmp_path / "proposals.csv"
    summary = tmp_path / "summary.json"

    assert main(
        [
            "infer",
            "--manifest",
            str(manifest),
            "--crops-dir",
            str(crops),
            "--cache-dir",
            str(cache),
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    ) == 43
    assert calls == [
        (
            [
                sys.executable,
                str(SCRIPT_PATH),
                "infer",
                "--manifest",
                str(manifest),
                "--crops-dir",
                str(crops),
                "--cache-dir",
                str(cache),
                "--output",
                str(output),
                "--summary",
                str(summary),
            ],
            {
                **os.environ,
                "LD_LIBRARY_PATH": "gpu-libs",
                ocsr_benchmark.INFER_REEXECUTED: "1",
            },
            False,
        )
    ]


def test_crop_manifest_declares_all_auditable_fields(tmp_path: Path) -> None:
    assert CROP_FIELDS == (
        "crop_id",
        "visual_review_id",
        "doi",
        "source_pdf",
        "page",
        "compound_role",
        "compound_id",
        "x0",
        "y0",
        "x1",
        "y1",
        "review_status",
    )
    assert validate_crop_row(valid_crop_row(tmp_path), page_count=1) == []


@pytest.mark.parametrize(
    "field",
    (
        "crop_id",
        "visual_review_id",
        "doi",
        "source_pdf",
        "page",
        "compound_role",
        "compound_id",
        "x0",
        "y0",
        "x1",
        "y1",
        "review_status",
    ),
)
def test_validate_crop_row_rejects_each_empty_required_field(
    tmp_path: Path, field: str
) -> None:
    row = valid_crop_row(tmp_path)
    row[field] = ""

    assert validate_crop_row(row, page_count=1) == [f"missing fields: {field}"]


def test_validate_crop_row_rejects_an_invalid_compound_role(tmp_path: Path) -> None:
    row = valid_crop_row(tmp_path)
    row["compound_role"] = "reference"

    assert validate_crop_row(row, page_count=1) == [
        "compound_role must be parent or derived"
    ]


@pytest.mark.parametrize("page", ("0", "2"))
def test_validate_crop_row_rejects_a_page_outside_the_source_pdf(
    tmp_path: Path, page: str
) -> None:
    row = valid_crop_row(tmp_path)
    row["page"] = page

    assert validate_crop_row(row, page_count=1) == ["page is outside source PDF"]


@pytest.mark.parametrize(
    ("coordinate", "value"),
    (("x1", "10"), ("y1", "20")),
)
def test_validate_crop_row_rejects_a_non_positive_rectangle(
    tmp_path: Path, coordinate: str, value: str
) -> None:
    row = valid_crop_row(tmp_path)
    row[coordinate] = value

    assert validate_crop_row(row, page_count=1) == [
        "crop rectangle has no positive area"
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    (
        ("page", "not-a-page", "page must be an integer"),
        ("x0", "not-a-coordinate", "x0 must be numeric"),
        ("y0", "nan", "y0 must be finite"),
    ),
)
def test_validate_crop_row_reports_invalid_numeric_values_without_raising(
    tmp_path: Path, field: str, value: str, expected_error: str
) -> None:
    row = valid_crop_row(tmp_path)
    row[field] = value

    assert validate_crop_row(row, page_count=1) == [expected_error]


@pytest.mark.parametrize(
    ("page", "page_count", "expected_error"),
    (
        ("inf", 1, "page must be an integer"),
        (1.5, 1, "page must be an integer"),
        ("1", float("inf"), "page_count must be an integer"),
        ("1", 1.5, "page_count must be an integer"),
    ),
)
def test_validate_crop_row_rejects_non_finite_or_fractional_page_values(
    tmp_path: Path, page: object, page_count: object, expected_error: str
) -> None:
    row = valid_crop_row(tmp_path)
    row["page"] = page

    assert validate_crop_row(row, page_count=page_count) == [expected_error]


def test_manifest_has_the_canonical_header() -> None:
    with MANIFEST_PATH.open(newline="") as manifest:
        rows = list(csv.reader(manifest))

    assert rows
    assert rows[0] == list(CROP_FIELDS)


def test_render_crop_preserves_manifest_identity_and_pdf_coordinates(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.draw_rect(
        fitz.Rect(20, 30, 120, 130), color=(0, 0, 0), fill=(0, 0, 0)
    )
    document.save(source_pdf)
    document.close()

    row = valid_crop_row(tmp_path)
    row.update({"source_pdf": str(source_pdf), "x0": "20", "y0": "30", "x1": "120", "y1": "130"})

    output = render_crop(row, tmp_path / "crops", dpi=300)

    assert output.name == "CROP-0001_parent_12d.png"
    assert output.is_file() and output.stat().st_size > 0
    image = fitz.Pixmap(output)
    assert (image.width, image.height, image.alpha) == (417, 417, 0)
    assert min(image.samples) < 250


def test_render_crop_refuses_to_replace_an_existing_crop(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=200, height=200)
    document.save(source_pdf)
    document.close()

    row = valid_crop_row(tmp_path)
    row["source_pdf"] = str(source_pdf)
    output_dir = tmp_path / "crops"
    render_crop(row, output_dir)

    with pytest.raises(FileExistsError, match="crop already exists"):
        render_crop(row, output_dir)


def test_validate_manifest_accepts_an_empty_canonical_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "structure_crop_manifest.csv"
    write_manifest(manifest, [])

    assert validate_manifest(manifest) == []


def test_empty_manifest_cli_reports_zero_rows_and_crops(tmp_path: Path) -> None:
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [])

    validation = run_cli("validate-manifest", "--manifest", str(manifest))
    rendering = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert validation.returncode == 0
    assert validation.stdout == "Validated 0 rows.\n"
    assert rendering.returncode == 0
    assert rendering.stdout == "Rendered 0 crops from 0 rows.\n"
    assert not crops_dir.exists()


def test_validate_manifest_cli_rejects_a_noncanonical_header(tmp_path: Path) -> None:
    manifest = tmp_path / "structure_crop_manifest.csv"
    manifest.write_text("unexpected\n", encoding="utf-8")

    result = run_cli("validate-manifest", "--manifest", str(manifest))

    assert result.returncode != 0
    assert "manifest header must be" in result.stderr


@pytest.mark.parametrize("extra_arguments", ((), ("--replace",)))
def test_render_cli_rejects_duplicate_manifest_output_names_before_writing(
    tmp_path: Path, extra_arguments: tuple[str, ...]
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    first_row = valid_crop_row(tmp_path)
    first_row["source_pdf"] = str(source_pdf)
    second_row = first_row | {"visual_review_id": "VIS-0002"}
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [first_row, second_row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
        *extra_arguments,
    )

    assert result.returncode != 0
    assert "duplicate crop output" in result.stderr
    assert not crops_dir.exists()


@pytest.mark.parametrize(
    ("field", "value", "outside_filename"),
    (
        ("crop_id", "../outside", "outside_parent_12d.png"),
        ("compound_id", "12d/../../outside", "outside.png"),
    ),
)
def test_render_cli_rejects_path_traversal_identity_values_before_writing(
    tmp_path: Path, field: str, value: str, outside_filename: str
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    row = valid_crop_row(tmp_path)
    row.update({"source_pdf": str(source_pdf), field: value})
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    outside_file = tmp_path / outside_filename
    write_manifest(manifest, [row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "identity" in result.stderr
    assert not crops_dir.exists()
    assert not outside_file.exists()


@pytest.mark.parametrize(("field", "value"), (("crop_id", "."), ("compound_id", "..")))
def test_render_cli_rejects_dot_identity_values_before_writing(
    tmp_path: Path, field: str, value: str
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    row = valid_crop_row(tmp_path)
    row.update({"source_pdf": str(source_pdf), field: value})
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "identity" in result.stderr
    assert not crops_dir.exists()


@pytest.mark.parametrize("extra_arguments", ((), ("--replace",)))
def test_render_cli_rejects_normalized_identity_aliases_before_writing(
    tmp_path: Path, extra_arguments: tuple[str, ...]
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    first_row = valid_crop_row(tmp_path)
    first_row["source_pdf"] = str(source_pdf)
    second_row = first_row | {
        "visual_review_id": "VIS-0002",
        "crop_id": "x/../CROP-0001",
    }
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [first_row, second_row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
        *extra_arguments,
    )

    assert result.returncode != 0
    assert "identity" in result.stderr
    assert not crops_dir.exists()


def test_render_cli_preflights_existing_second_output_before_first_writing(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    first_row = valid_crop_row(tmp_path)
    first_row["source_pdf"] = str(source_pdf)
    second_row = first_row | {
        "crop_id": "CROP-0002",
        "compound_id": "12e",
    }
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [first_row, second_row])
    existing_output = render_crop(second_row, crops_dir)

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "crop already exists" in result.stderr
    assert not (crops_dir / "CROP-0001_parent_12d.png").exists()
    assert existing_output.is_file()


def test_render_cli_reports_a_malformed_csv_without_creating_crops(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    manifest.write_text(
        ",".join(CROP_FIELDS) + '\n"unterminated', encoding="utf-8"
    )

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "cannot read manifest" in result.stderr
    assert not crops_dir.exists()


def test_render_cli_reports_an_unreadable_source_pdf_without_creating_crops(
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "not-a-pdf.pdf"
    source_pdf.write_bytes(b"These bytes are not a PDF.")
    row = valid_crop_row(tmp_path)
    row["source_pdf"] = str(source_pdf)
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "unable to open source PDF" in result.stderr
    assert not crops_dir.exists()


def test_render_cli_validates_all_rows_before_creating_any_crop(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    valid_row = valid_crop_row(tmp_path)
    valid_row["source_pdf"] = str(source_pdf)
    invalid_row = valid_row | {
        "crop_id": "CROP-0002",
        "compound_id": "12e",
        "x1": valid_row["x0"],
    }
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [valid_row, invalid_row])

    result = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )

    assert result.returncode != 0
    assert "row 3: crop rectangle has no positive area" in result.stderr
    assert not crops_dir.exists()


def test_render_cli_requires_replace_to_overwrite_a_crop(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    create_source_pdf(source_pdf)
    row = valid_crop_row(tmp_path)
    row["source_pdf"] = str(source_pdf)
    manifest = tmp_path / "structure_crop_manifest.csv"
    crops_dir = tmp_path / "crops"
    write_manifest(manifest, [row])
    render_crop(row, crops_dir)

    refused = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
    )
    replaced = run_cli(
        "render",
        "--manifest",
        str(manifest),
        "--crops-dir",
        str(crops_dir),
        "--replace",
    )

    assert refused.returncode != 0
    assert "crop already exists" in refused.stderr
    assert replaced.returncode == 0
    assert replaced.stdout == "Rendered 1 crops from 1 rows.\n"
