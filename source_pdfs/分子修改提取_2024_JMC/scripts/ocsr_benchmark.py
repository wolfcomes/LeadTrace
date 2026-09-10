"""Validation helpers for the auditable OCSR structure-crop manifest."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pymupdf as fitz


CROP_FIELDS = (
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "08_ocsr_benchmark" / "structure_crop_manifest.csv"
DEFAULT_CROPS_DIR = PROJECT_ROOT / "08_ocsr_benchmark" / "crops"
DEFAULT_DECIMER_CACHE_DIR = PROJECT_ROOT / "08_ocsr_benchmark" / "decimer_model"
OUTPUT_IDENTITY_FIELDS = ("crop_id", "compound_role", "compound_id")
GPU_PROBE_REEXECUTED = "OCSR_GPU_PROBE_REEXECUTED"
MODEL_PROBE_REEXECUTED = "OCSR_MODEL_PROBE_REEXECUTED"
INFER_REEXECUTED = "OCSR_INFER_REEXECUTED"
DECIMER_MODEL_URL = "https://zenodo.org/record/8300489/files/models.zip"
DECIMER_HANDDRAWN_MODEL_URL = (
    "https://zenodo.org/records/10781330/files/DECIMER_HandDrawn_model.zip"
)
DECIMER_MODEL_MEMBERS = (
    "DECIMER_model/saved_model.pb",
    "DECIMER_model/assets/tokenizer_SMILES.pkl",
)
DECIMER_HANDDRAWN_MODEL_MEMBERS = (
    "DECIMER_HandDrawn_model/saved_model.pb",
    "DECIMER_HandDrawn_model/assets/tokenizer_pubchem.pkl",
)
DECIMER_CACHE_MEMBERS = (
    "DECIMER_model/saved_model.pb",
    "DECIMER_model/assets/tokenizer_SMILES.pkl",
    "DECIMER_HandDrawn_model/saved_model.pb",
    "DECIMER_HandDrawn_model/assets/tokenizer_pubchem.pkl",
)
PROPOSAL_FIELDS = (
    "crop_id",
    "visual_review_id",
    "doi",
    "source_pdf",
    "page",
    "compound_role",
    "compound_id",
    "crop_path",
    "raw_smiles",
    "token_confidences",
    "mean_token_confidence",
    "min_token_confidence",
    "inference_status",
    "inference_error",
    "rdkit_status",
    "canonical_smiles",
    "model_version",
    "review_status",
)


class ManifestError(ValueError):
    """Raised when a crop manifest cannot be read or validated."""


def validate_decimer_archive(archive: Path) -> str | None:
    """Return a validation error unless an archive has both DECIMER models."""
    try:
        with ZipFile(archive) as handle:
            members = set(handle.namelist())
    except (BadZipFile, OSError):
        return "archive is not a readable ZIP file"

    for member in DECIMER_MODEL_MEMBERS:
        if member not in members:
            return f"archive is missing {member}"
    return None


def validate_handdrawn_archive(archive: Path) -> str | None:
    """Return a validation error unless an archive has the hand-drawn model."""
    try:
        with ZipFile(archive) as handle:
            members = set(handle.namelist())
    except (BadZipFile, OSError):
        return "archive is not a readable ZIP file"

    for member in DECIMER_HANDDRAWN_MODEL_MEMBERS:
        if member not in members:
            return f"archive is missing {member}"
    return None


def validate_decimer_cache(cache: Path) -> str | None:
    """Return an error unless both DECIMER runtime model trees are complete."""
    cache = Path(cache)
    for member in DECIMER_CACHE_MEMBERS:
        if not (cache / member).is_file():
            return f"cache is missing {member}"
    return None


def configure_decimer_cache(cache: Path) -> str:
    """Point DECIMER's pystow namespace at the project-owned model cache."""
    value = str(Path(cache).resolve())
    os.environ["DECIMER-V2_HOME"] = value
    return value


def _download_decimer_archive(
    url: str,
    archive: Path,
    validator: object,
) -> Path:
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    validation_error = validator(archive)
    if archive.is_file() and validation_error is None:
        return archive

    command = [
        "curl",
        "--fail",
        "--location",
        "--continue-at",
        "-",
        "--output",
        str(archive),
        url,
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"could not download DECIMER archive {url}") from error

    validation_error = validator(archive)
    if validation_error:
        raise ValueError(f"downloaded archive {archive}: {validation_error}")
    return archive


def download_decimer_models(
    cache: Path = DEFAULT_DECIMER_CACHE_DIR,
    *,
    standard_archive: Path | None = None,
    handdrawn_archive: Path | None = None,
) -> Path:
    """Download, validate, and install both DECIMER model archives."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    standard_archive = standard_archive or cache / "models.zip"
    handdrawn_archive = handdrawn_archive or cache / "DECIMER_HandDrawn_model.zip"
    _download_decimer_archive(
        DECIMER_MODEL_URL,
        standard_archive,
        validate_decimer_archive,
    )
    _download_decimer_archive(
        DECIMER_HANDDRAWN_MODEL_URL,
        handdrawn_archive,
        validate_handdrawn_archive,
    )
    return extract_decimer_archives(standard_archive, handdrawn_archive, cache)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = Path(destination).resolve()
    with ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as error:
                raise ManifestError(f"archive member escapes extraction directory: {member.filename}") from error
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def extract_decimer_archives(
    standard_archive: Path,
    handdrawn_archive: Path,
    cache: Path,
) -> Path:
    """Install validated DECIMER archives into a complete project cache."""
    standard_archive = Path(standard_archive)
    handdrawn_archive = Path(handdrawn_archive)
    cache = Path(cache)
    standard_error = validate_decimer_archive(standard_archive)
    if standard_error:
        raise ValueError(f"standard DECIMER archive: {standard_error}")
    handdrawn_error = validate_handdrawn_archive(handdrawn_archive)
    if handdrawn_error:
        raise ValueError(f"hand-drawn DECIMER archive: {handdrawn_error}")

    cache.mkdir(parents=True, exist_ok=True)
    targets = (
        (standard_archive, "DECIMER_model", DECIMER_MODEL_URL),
        (handdrawn_archive, "DECIMER_HandDrawn_model", DECIMER_HANDDRAWN_MODEL_URL),
    )
    try:
        for archive, model_name, model_url in targets:
            with tempfile.TemporaryDirectory(prefix=f".{model_name}-", dir=cache) as temporary:
                staging = Path(temporary)
                _safe_extract(archive, staging)
                extracted = staging / model_name
                if not extracted.is_dir():
                    raise ValueError(f"archive did not extract {model_name}")
                target = cache / model_name
                if target.exists():
                    shutil.rmtree(target)
                os.replace(extracted, target)
                (target / ".model_url").write_text(model_url, encoding="utf-8")
    except (BadZipFile, OSError) as error:
        raise ValueError(f"could not install DECIMER archives: {error}") from error

    cache_error = validate_decimer_cache(cache)
    if cache_error:
        raise ValueError(cache_error)
    return cache


def compose_library_path(library_dirs: Iterable[Path], existing: str) -> str:
    """Prepend unique library directories while retaining existing entries."""
    entries = [str(path) for path in library_dirs]
    entries.extend(entry for entry in existing.split(os.pathsep) if entry)
    return os.pathsep.join(dict.fromkeys(entries))


def configure_nvidia_library_path() -> str:
    """Prepend installed NVIDIA package library directories to the loader path."""
    import nvidia

    library_dirs = sorted(
        (
            path
            for package_root in nvidia.__path__
            for path in Path(package_root).glob("*/lib")
            if path.is_dir()
        ),
        key=str,
    )
    value = compose_library_path(library_dirs, os.environ.get("LD_LIBRARY_PATH", ""))
    os.environ["LD_LIBRARY_PATH"] = value
    return value


def probe_gpu() -> tuple[str, float]:
    """Run a small TensorFlow matrix multiplication on the first logical GPU."""
    configure_nvidia_library_path()
    import tensorflow as tf

    logical_gpus = tf.config.list_logical_devices("GPU")
    if not logical_gpus:
        raise RuntimeError("no logical GPU available")

    with tf.device("/GPU:0"):
        left = tf.constant([[1.0, 2.0], [3.0, 4.0]])
        right = tf.constant([[5.0, 6.0], [7.0, 8.0]])
        product = tf.linalg.matmul(left, right)
        matrix_sum = float(tf.reduce_sum(product).numpy())

    if "GPU:0" not in product.device.upper():
        raise RuntimeError(f"matrix multiplication fell back to CPU: {product.device}")
    if not math.isfinite(matrix_sum):
        raise RuntimeError(f"GPU matrix result is not finite: {matrix_sum}")

    identity = logical_gpus[0].name
    physical_gpus = tf.config.list_physical_devices("GPU")
    if physical_gpus:
        details = tf.config.experimental.get_device_details(physical_gpus[0])
        identity = details.get("device_name", identity)
    return identity, matrix_sum


def run_gpu_probe() -> int:
    """Run the probe in a process that starts with NVIDIA libraries configured."""
    library_path = configure_nvidia_library_path()
    if os.environ.get(GPU_PROBE_REEXECUTED) != "1":
        environment = os.environ.copy()
        environment["LD_LIBRARY_PATH"] = library_path
        environment[GPU_PROBE_REEXECUTED] = "1"
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "gpu-probe"],
            env=environment,
            check=False,
        )
        return completed.returncode

    gpu_identity, matrix_sum = probe_gpu()
    print(f"GPU: {gpu_identity}")
    print(f"Matrix sum: {matrix_sum}")
    return 0


def probe_decimer_models(cache: Path = DEFAULT_DECIMER_CACHE_DIR) -> dict[str, str | float]:
    """Verify GPU execution and load both DECIMER SavedModel objects."""
    configure_nvidia_library_path()
    configured_cache = configure_decimer_cache(cache)
    cache_error = validate_decimer_cache(Path(configured_cache))
    if cache_error:
        raise ValueError(cache_error)

    package = importlib.import_module("DECIMER")
    runtime = importlib.import_module("DECIMER.decimer")
    for model_name in ("DECIMER_V2", "DECIMER_Hand_drawn"):
        if getattr(runtime, model_name, None) is None:
            raise RuntimeError(f"DECIMER model was not loaded: {model_name}")
    gpu_identity, matrix_sum = probe_gpu()

    return {
        "cache": configured_cache,
        "version": str(getattr(package, "__version__", "unknown")),
        "gpu": gpu_identity,
        "matrix_sum": matrix_sum,
    }


def run_model_probe(cache: Path = DEFAULT_DECIMER_CACHE_DIR) -> int:
    """Run the DECIMER probe after starting with NVIDIA libraries configured."""
    cache = Path(cache)
    library_path = configure_nvidia_library_path()
    if os.environ.get(MODEL_PROBE_REEXECUTED) != "1":
        environment = os.environ.copy()
        environment["LD_LIBRARY_PATH"] = library_path
        environment[MODEL_PROBE_REEXECUTED] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "model-probe",
                "--cache-dir",
                str(cache),
            ],
            env=environment,
            check=False,
        )
        return completed.returncode

    evidence = probe_decimer_models(cache)
    print(f"DECIMER cache: {evidence['cache']}")
    print(f"DECIMER version: {evidence['version']}")
    print(f"GPU: {evidence['gpu']}")
    print(f"Matrix sum: {evidence['matrix_sum']}")
    return 0


def run_infer(
    manifest: Path = DEFAULT_MANIFEST_PATH,
    crops_dir: Path = DEFAULT_CROPS_DIR,
    cache: Path = DEFAULT_DECIMER_CACHE_DIR,
    output_csv: Path = PROJECT_ROOT / "08_ocsr_benchmark" / "ocsr_proposals.csv",
    summary_json: Path = PROJECT_ROOT / "08_ocsr_benchmark" / "benchmark_summary.json",
) -> int:
    """Run inference in a fresh process whose loader path is preconfigured."""
    arguments = (
        "infer",
        "--manifest",
        str(Path(manifest)),
        "--crops-dir",
        str(Path(crops_dir)),
        "--cache-dir",
        str(Path(cache)),
        "--output",
        str(Path(output_csv)),
        "--summary",
        str(Path(summary_json)),
    )
    library_path = configure_nvidia_library_path()
    if os.environ.get(INFER_REEXECUTED) != "1":
        environment = os.environ.copy()
        environment["LD_LIBRARY_PATH"] = library_path
        environment[INFER_REEXECUTED] = "1"
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *arguments],
            env=environment,
            check=False,
        )
        return completed.returncode

    summary = infer_proposals(
        Path(manifest),
        Path(crops_dir),
        Path(cache),
        Path(output_csv),
        Path(summary_json),
    )
    print(
        f"Inferred {summary['proposal_count']} proposals; "
        f"{summary['valid_rdkit_count']} valid RDKit parses."
    )
    return 0


def validate_smiles(raw_smiles: str) -> dict[str, str]:
    """Parse a DECIMER proposal and return its RDKit-normalized form."""
    from rdkit import Chem

    molecule = Chem.MolFromSmiles(raw_smiles or "")
    if molecule is None:
        return {"rdkit_status": "invalid", "canonical_smiles": ""}
    return {
        "rdkit_status": "valid",
        "canonical_smiles": Chem.MolToSmiles(molecule, isomericSmiles=True),
    }


def _serialize_token_confidences(
    confidence_values: Iterable[object] | None,
) -> tuple[str, str, str]:
    """Convert DECIMER's token/confidence pairs to stable CSV values."""
    records: list[dict[str, str | float]] = []
    if confidence_values is not None:
        for item in confidence_values:
            if isinstance(item, Mapping):
                token = item["token"]
                confidence = item["confidence"]
            else:
                token, confidence = item  # type: ignore[misc]
            score = float(confidence)
            if not math.isfinite(score):
                raise ValueError("DECIMER token confidence is not finite")
            records.append({"token": str(token), "confidence": score})

    scores = [float(record["confidence"]) for record in records]
    encoded = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
    if not scores:
        return encoded, "", ""
    return encoded, str(sum(scores) / len(scores)), str(min(scores))


def _atomic_write_csv(path: Path, rows: list[Mapping[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            writer = csv.DictWriter(temporary, fieldnames=PROPOSAL_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, ensure_ascii=True, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def infer_proposals(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    crops_dir: Path = DEFAULT_CROPS_DIR,
    cache: Path = DEFAULT_DECIMER_CACHE_DIR,
    output_csv: Path = PROJECT_ROOT / "08_ocsr_benchmark" / "ocsr_proposals.csv",
    summary_json: Path = PROJECT_ROOT / "08_ocsr_benchmark" / "benchmark_summary.json",
) -> dict[str, object]:
    """Run DECIMER on validated crops and write proposal-only benchmark outputs."""
    rows = validate_manifest(Path(manifest_path))
    crop_paths = [crop_output_path(row, Path(crops_dir)) for row in rows]
    missing_crop = next((path for path in crop_paths if not path.is_file()), None)
    if missing_crop is not None:
        raise FileNotFoundError(f"rendered crop does not exist: {missing_crop}")

    evidence = probe_decimer_models(Path(cache))
    decimer = importlib.import_module("DECIMER")
    predictor = getattr(decimer, "predict_SMILES", None)
    if predictor is None:
        raise RuntimeError("DECIMER does not expose predict_SMILES")

    proposals: list[dict[str, object]] = []
    for row, crop_path in zip(rows, crop_paths):
        proposal: dict[str, object] = {
            field: row[field] for field in CROP_FIELDS if field not in {"x0", "y0", "x1", "y1"}
        }
        proposal.update(
            {
                "crop_path": str(crop_path),
                "raw_smiles": "",
                "token_confidences": "[]",
                "mean_token_confidence": "",
                "min_token_confidence": "",
                "inference_status": "error",
                "inference_error": "",
                "rdkit_status": "not_run",
                "canonical_smiles": "",
                "model_version": evidence["version"],
                "review_status": "proposal_requires_human_review",
            }
        )
        try:
            prediction = predictor(str(crop_path), confidence=True)
            raw_smiles, confidence_values = prediction
            raw_smiles = str(raw_smiles or "")
            token_json, mean_confidence, min_confidence = _serialize_token_confidences(
                confidence_values
            )
            proposal.update(
                {
                    "raw_smiles": raw_smiles,
                    "token_confidences": token_json,
                    "mean_token_confidence": mean_confidence,
                    "min_token_confidence": min_confidence,
                    "inference_status": "ok",
                    **validate_smiles(raw_smiles),
                }
            )
        except Exception as error:
            proposal["inference_error"] = f"{type(error).__name__}: {error}"
        proposals.append(proposal)

    summary: dict[str, object] = {
        "manifest": str(Path(manifest_path).resolve()),
        "crops_dir": str(Path(crops_dir).resolve()),
        "cache": evidence["cache"],
        "model_version": evidence["version"],
        "gpu": evidence["gpu"],
        "matrix_sum": evidence["matrix_sum"],
        "crop_count": len(rows),
        "proposal_count": len(proposals),
        "valid_rdkit_count": sum(row["rdkit_status"] == "valid" for row in proposals),
        "invalid_rdkit_count": sum(row["rdkit_status"] == "invalid" for row in proposals),
        "inference_error_count": sum(row["inference_status"] == "error" for row in proposals),
        "review_status": "proposal_requires_human_review",
        "output_csv": str(Path(output_csv).resolve()),
        "summary_json": str(Path(summary_json).resolve()),
    }
    _atomic_write_csv(Path(output_csv), proposals)
    _atomic_write_json(Path(summary_json), summary)
    return summary


def validate_crop_row(row: Mapping[str, object], page_count: object) -> list[str]:
    """Return manifest-row validation errors without raising on bad values."""
    missing = [field for field in CROP_FIELDS if _is_empty(row.get(field))]
    if missing:
        return [f"missing fields: {', '.join(missing)}"]

    compound_role = str(row["compound_role"]).strip()
    if compound_role not in {"parent", "derived"}:
        return ["compound_role must be parent or derived"]

    parsed_page_count = _parse_integer(page_count)
    if parsed_page_count is None:
        return ["page_count must be an integer"]
    if parsed_page_count < 1:
        return ["page_count must be positive"]

    page = _parse_integer(row["page"])
    if page is None:
        return ["page must be an integer"]
    if not 1 <= page <= parsed_page_count:
        return ["page is outside source PDF"]

    coordinates: dict[str, float] = {}
    for field in ("x0", "y0", "x1", "y1"):
        try:
            value = float(row[field])
        except (TypeError, ValueError):
            return [f"{field} must be numeric"]
        if not math.isfinite(value):
            return [f"{field} must be finite"]
        coordinates[field] = value

    if coordinates["x1"] <= coordinates["x0"] or coordinates["y1"] <= coordinates["y0"]:
        return ["crop rectangle has no positive area"]
    return []


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric_value) or not numeric_value.is_integer():
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def crop_output_path(row: Mapping[str, object], output_dir: Path) -> Path:
    """Return the canonical crop destination for one manifest row."""
    identity: list[str] = []
    for field in OUTPUT_IDENTITY_FIELDS:
        value = str(row[field])
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ManifestError(
                f"{field} identity must not contain path separators or be '.' or '..'"
            )
        identity.append(value)

    resolved_output_dir = Path(output_dir).resolve()
    output = (resolved_output_dir / f"{'_'.join(identity)}.png").resolve()
    try:
        output.relative_to(resolved_output_dir)
    except ValueError as error:
        raise ManifestError(f"crop output escapes crops directory: {output}") from error
    return output


def render_crop(
    row: Mapping[str, object],
    output_dir: Path,
    dpi: int = 300,
    *,
    replace: bool = False,
) -> Path:
    """Render one manifest rectangle using its original PDF point coordinates."""
    output = crop_output_path(row, output_dir)
    if output.exists() and not replace:
        raise FileExistsError(f"crop already exists: {output}")

    document = fitz.open(str(row["source_pdf"]))
    try:
        page = document[int(str(row["page"])) - 1]
        rectangle = fitz.Rect(
            *(float(row[field]) for field in ("x0", "y0", "x1", "y1"))
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(
            matrix=fitz.Matrix(dpi / 72, dpi / 72),
            clip=rectangle,
            alpha=False,
        ).save(output)
        return output
    finally:
        document.close()


def validate_manifest(manifest_path: Path) -> list[dict[str, str | None]]:
    """Read and validate every manifest row against its source PDF."""
    rows = _read_manifest(Path(manifest_path))
    errors: list[str] = []

    for row_number, row in enumerate(rows, start=2):
        source_pdf = row.get("source_pdf")
        if _is_empty(source_pdf):
            row_errors = validate_crop_row(row, page_count=1)
        else:
            try:
                document = fitz.open(str(source_pdf))
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"row {row_number}: unable to open source PDF: {error}")
                continue
            try:
                row_errors = validate_crop_row(row, page_count=document.page_count)
            finally:
                document.close()
        errors.extend(f"row {row_number}: {error}" for error in row_errors)

    if errors:
        raise ManifestError("\n".join(errors))
    return rows


def render_manifest(
    rows: list[Mapping[str, object]],
    output_dir: Path,
    *,
    replace: bool = False,
) -> int:
    """Render already-validated rows after preflighting existing output files."""
    outputs = [crop_output_path(row, output_dir) for row in rows]
    seen_outputs: set[Path] = set()
    for output in outputs:
        if output in seen_outputs:
            raise ManifestError(f"duplicate crop output: {output}")
        seen_outputs.add(output)

    if not replace:
        existing = next((output for output in outputs if output.exists()), None)
        if existing is not None:
            raise FileExistsError(f"crop already exists: {existing}")

    for row in rows:
        render_crop(row, output_dir, replace=replace)
    return len(rows)


def _read_manifest(manifest_path: Path) -> list[dict[str, str | None]]:
    try:
        with manifest_path.open(newline="", encoding="utf-8") as manifest:
            reader = csv.DictReader(manifest, strict=True)
            if reader.fieldnames != list(CROP_FIELDS):
                expected_header = ",".join(CROP_FIELDS)
                raise ManifestError(f"manifest header must be: {expected_header}")

            rows: list[dict[str, str | None]] = []
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ManifestError(f"row {row_number}: has too many columns")
                rows.append(row)
            return rows
    except ManifestError:
        raise
    except (OSError, csv.Error) as error:
        raise ManifestError(f"cannot read manifest {manifest_path}: {error}") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validation = commands.add_parser("validate-manifest")
    validation.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)

    rendering = commands.add_parser("render")
    rendering.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    rendering.add_argument("--crops-dir", type=Path, default=DEFAULT_CROPS_DIR)
    rendering.add_argument("--replace", action="store_true")

    commands.add_parser("gpu-probe")

    model_probe = commands.add_parser("model-probe")
    model_probe.add_argument("--cache-dir", type=Path, default=DEFAULT_DECIMER_CACHE_DIR)

    inference = commands.add_parser("infer")
    inference.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    inference.add_argument("--crops-dir", type=Path, default=DEFAULT_CROPS_DIR)
    inference.add_argument("--cache-dir", type=Path, default=DEFAULT_DECIMER_CACHE_DIR)
    inference.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "08_ocsr_benchmark" / "ocsr_proposals.csv",
    )
    inference.add_argument(
        "--summary",
        type=Path,
        default=PROJECT_ROOT / "08_ocsr_benchmark" / "benchmark_summary.json",
    )

    download = commands.add_parser("download-model")
    download.add_argument("--cache-dir", type=Path, default=DEFAULT_DECIMER_CACHE_DIR)
    download.add_argument("--standard-archive", type=Path)
    download.add_argument("--handdrawn-archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the crop-manifest validation or rendering command."""
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "gpu-probe":
            return run_gpu_probe()
        if arguments.command == "model-probe":
            return run_model_probe(arguments.cache_dir)
        if arguments.command == "infer":
            return run_infer(
                arguments.manifest,
                arguments.crops_dir,
                arguments.cache_dir,
                arguments.output,
                arguments.summary,
            )
        if arguments.command == "download-model":
            download_options = {}
            if arguments.standard_archive is not None:
                download_options["standard_archive"] = arguments.standard_archive
            if arguments.handdrawn_archive is not None:
                download_options["handdrawn_archive"] = arguments.handdrawn_archive
            cache = download_decimer_models(arguments.cache_dir, **download_options)
            print(f"Installed DECIMER models in {cache}")
            return 0

        rows = validate_manifest(arguments.manifest)
        if arguments.command == "validate-manifest":
            print(f"Validated {len(rows)} rows.")
            return 0

        crop_count = render_manifest(
            rows,
            arguments.crops_dir,
            replace=arguments.replace,
        )
    except (
        ImportError,
        ManifestError,
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Rendered {crop_count} crops from {len(rows)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
