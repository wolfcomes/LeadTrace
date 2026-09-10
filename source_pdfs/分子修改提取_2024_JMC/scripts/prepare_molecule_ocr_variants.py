#!/usr/bin/env python3
"""Create auditable, caption-free image variants for isolated molecule objects.

The source crop is retained as an explicit variant.  The derived variants only
remove a spatially separated lower caption; they never erase atom labels,
bonds, stereochemical marks, or any pixels within the selected structure band.
They are OCSR inputs, not structural evidence or confirmed SMILES.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping

from PIL import Image, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBJECTS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "molecule_ocr_variants"
DEFAULT_MANIFEST = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "molecule_ocr_variant_manifest.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "molecule_ocr_variant_summary.json"

ELIGIBLE_OBJECT_TYPES = {"complete_molecule", "molecule_series_member"}
ELIGIBLE_SMILES_SOURCES = {"isolated_object_pending_ocsr"}
MISSING = "--"
VARIANT_VERSION = "molecule_ocr_variants_v1_2026-09-05"

VARIANT_FIELDS = (
    "variant_id", "object_id", "paper_id", "paper_rank", "candidate_id", "page",
    "object_type", "compound_label", "variant_name", "parent_crop_path", "variant_path",
    "variant_filename", "parent_width", "parent_height", "structure_bbox_pixels",
    "caption_separation_status", "transform_steps", "ocrs_input_status", "review_status",
    "annotation_version", "updated_at",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=VARIANT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def select_molecule_objects(rows: Iterable[Mapping[str, object]]) -> list[dict[str, str]]:
    """Return only isolated, complete numbered-molecule crops suitable for OCSR."""
    selected: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("object_type", "")) not in ELIGIBLE_OBJECT_TYPES:
            continue
        if str(row.get("smiles_source", "")) not in ELIGIBLE_SMILES_SOURCES:
            continue
        crop_path = str(row.get("crop_path", "") or "").strip()
        if not crop_path or crop_path == MISSING:
            continue
        selected.append({key: str(value or "") for key, value in row.items()})
    return sorted(selected, key=lambda row: (
        int(row.get("paper_rank", "9999")) if row.get("paper_rank", "").isdigit() else 9999,
        row.get("object_id", ""),
    ))


def _ink_rows(image: Image.Image, *, threshold: int = 220) -> list[tuple[int, int]]:
    """Return dark-pixel spans per row, while preserving all pixels in the crop."""
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.load()
    rows: list[tuple[int, int]] = []
    for y in range(height):
        positions = [x for x in range(width) if pixels[x, y] < threshold]
        if positions:
            rows.append((y, len(positions)))
    return rows


def _row_blocks(rows: list[tuple[int, int]], *, bridge: int) -> list[tuple[int, int, int]]:
    if not rows:
        return []
    blocks: list[tuple[int, int, int]] = []
    start, previous, mass = rows[0][0], rows[0][0], rows[0][1]
    for y, count in rows[1:]:
        if y - previous <= bridge:
            previous = y
            mass += count
            continue
        blocks.append((start, previous, mass))
        start, previous, mass = y, y, count
    blocks.append((start, previous, mass))
    return blocks


def find_top_ink_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Locate a top structure band when it is separated from its caption.

    A full source image is returned when the visual separation is ambiguous.
    That conservative fallback avoids truncating a molecule simply to suppress
    explanatory text.
    """
    width, height = image.size
    rows = _ink_rows(image)
    bridge = max(5, round(height * 0.035))
    blocks = _row_blocks(rows, bridge=bridge)
    minimum_mass = max(24, round(width * 0.16))
    structure_block = next((block for block in blocks if block[2] >= minimum_mass), None)
    if structure_block is None:
        return (0, 0, width, height)

    top, bottom, _ = structure_block
    later_blocks = [block for block in blocks if block[0] > bottom]
    if not later_blocks:
        return (0, 0, width, height)

    next_top = later_blocks[0][0]
    blank_gap = next_top - bottom - 1
    if blank_gap < max(8, round(height * 0.05)):
        return (0, 0, width, height)

    gray = image.convert("L")
    pixels = gray.load()
    x_positions = [
        x for y in range(top, bottom + 1) for x in range(width)
        if pixels[x, y] < 220
    ]
    if not x_positions:
        return (0, 0, width, height)
    padding = max(8, round(min(width, height) * 0.05))
    return (
        max(0, min(x_positions) - padding),
        max(0, top - padding),
        min(width, max(x_positions) + padding + 1),
        min(height, bottom + padding + 1),
    )


def _normalised_coordinate(row: Mapping[str, object], name: str) -> float | None:
    try:
        value = float(str(row.get(name, "")))
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value <= 1.0 else None


def expanded_source_box(
    row: Mapping[str, object], source_size: tuple[int, int], *,
    expand_left: bool = True, expand_right: bool = True,
) -> tuple[int, int, int, int] | None:
    """Add a bounded horizontal margin around a small, gridded source region.

    A grid division can land directly across a terminal group such as a
    carboxylic acid.  This is limited to small two-dimensional cells and never
    expands vertically, so wide tables and reaction schemes remain untouched.
    """
    coordinates = [_normalised_coordinate(row, name) for name in ("local_x0", "local_y0", "local_x1", "local_y1")]
    if any(value is None for value in coordinates):
        return None
    x0, y0, x1, y1 = coordinates  # type: ignore[misc]
    if x1 <= x0 or y1 <= y0 or x1 - x0 > 0.34 or y1 - y0 > 0.34 or not (expand_left or expand_right):
        return None
    width, height = source_size
    left, top = round(x0 * width), round(y0 * height)
    right, bottom = round(x1 * width), round(y1 * height)
    cell_width = right - left
    horizontal_margin = min(round(width * 0.04), round(cell_width * 0.15))
    if horizontal_margin < 1:
        return None
    return (
        max(0, left - horizontal_margin) if expand_left else left, top,
        min(width, right + horizontal_margin) if expand_right else right, bottom,
    )


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "molecule"


def _save_variants(image: Image.Image, bounds: tuple[int, int, int, int], output_dir: Path, stem: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cropped = image.crop(bounds)
    variants = {
        "label_free": cropped.convert("RGB"),
        "label_free_grayscale": ImageOps.grayscale(cropped),
        "label_free_thresholded": ImageOps.grayscale(cropped).point(lambda value: 0 if value < 210 else 255, mode="1"),
    }
    filenames: dict[str, str] = {}
    for variant_name, variant_image in variants.items():
        filename = f"{stem}__{variant_name}.png"
        variant_image.save(output_dir / filename)
        filenames[variant_name] = filename
    return filenames


def _row_values(
    object_row: Mapping[str, object], *, variant_name: str, parent_path: Path,
    variant_path: Path, variant_filename: str, parent_size: tuple[int, int],
    bounds: tuple[int, int, int, int], caption_separation_status: str,
    transform_steps: str,
) -> dict[str, str]:
    object_id = str(object_row.get("object_id", ""))
    return {
        "variant_id": f"{object_id}::{variant_name}",
        "object_id": object_id,
        "paper_id": str(object_row.get("paper_id", "")),
        "paper_rank": str(object_row.get("paper_rank", "")),
        "candidate_id": str(object_row.get("candidate_id", "")),
        "page": str(object_row.get("page", "")),
        "object_type": str(object_row.get("object_type", "")),
        "compound_label": str(object_row.get("compound_label", "")) or MISSING,
        "variant_name": variant_name,
        "parent_crop_path": str(parent_path),
        "variant_path": str(variant_path),
        "variant_filename": variant_filename or MISSING,
        "parent_width": str(parent_size[0]),
        "parent_height": str(parent_size[1]),
        "structure_bbox_pixels": json.dumps(bounds, separators=(",", ":")),
        "caption_separation_status": caption_separation_status,
        "transform_steps": transform_steps,
        "ocrs_input_status": "proposal_only_pending_ensemble_ocr",
        "review_status": "image_variant_requires_graph_review",
        "annotation_version": VARIANT_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_variant_snapshot(
    objects: Iterable[Mapping[str, object]], output_dir: Path = DEFAULT_OUTPUT_DIR,
    manifest_path: Path = DEFAULT_MANIFEST, summary_path: Path = DEFAULT_SUMMARY,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Render derived OCSR image inputs and an auditable CSV manifest."""
    selected = select_molecule_objects(objects)
    output: list[dict[str, str]] = []
    processed = 0
    failures: list[dict[str, str]] = []
    for object_row in selected:
        parent_path = Path(str(object_row["crop_path"])).resolve()
        try:
            with Image.open(parent_path) as loaded:
                image = loaded.convert("RGB")
        except (FileNotFoundError, OSError) as error:
            failures.append({"object_id": str(object_row.get("object_id", "")), "error": str(error)})
            continue
        bounds = find_top_ink_bounds(image)
        caption_status = "caption_removed_by_blank_band" if bounds != (0, 0, *image.size) else "no_safe_caption_separation"
        stem = _safe_filename(str(object_row.get("object_id", "molecule")))
        filenames = _save_variants(image, bounds, Path(output_dir), stem)
        original = _row_values(
            object_row, variant_name="original_object_crop", parent_path=parent_path,
            variant_path=parent_path, variant_filename="", parent_size=image.size, bounds=bounds,
            caption_separation_status=caption_status, transform_steps="preserved parent object crop without pixel transformation",
        )
        output.append(original)
        for variant_name, filename in filenames.items():
            transform = "crop only to top ink band"
            if variant_name == "label_free_grayscale":
                transform += " -> grayscale"
            elif variant_name == "label_free_thresholded":
                transform += " -> grayscale -> threshold at 210"
            output.append(_row_values(
                object_row, variant_name=variant_name, parent_path=parent_path,
                variant_path=(Path(output_dir) / filename).resolve(), variant_filename=filename,
                parent_size=image.size, bounds=bounds, caption_separation_status=caption_status,
                transform_steps=transform,
            ))
        source_crop_text = str(object_row.get("source_crop_path", "") or "").strip()
        source_path = Path(source_crop_text).resolve() if source_crop_text and source_crop_text != MISSING else None
        if source_path and source_path != parent_path and source_path.is_file():
            try:
                with Image.open(source_path) as loaded_source:
                    source_image = loaded_source.convert("RGB")
            except OSError as error:
                failures.append({"object_id": str(object_row.get("object_id", "")), "error": f"source expansion skipped: {error}"})
            else:
                edge_threshold = max(2, round(min(image.size) * 0.015))
                source_box = expanded_source_box(
                    object_row, source_image.size,
                    expand_left=bounds[0] <= edge_threshold,
                    expand_right=bounds[2] >= image.width - edge_threshold,
                )
                if source_box is not None:
                    source_region = source_image.crop(source_box)
                    source_bounds = find_top_ink_bounds(source_region)
                    source_caption_status = "caption_removed_by_blank_band" if source_bounds != (0, 0, *source_region.size) else "no_safe_caption_separation"
                    source_filenames = _save_variants(source_region, source_bounds, Path(output_dir), f"{stem}__source_expanded")
                    source_structure_bounds = (
                        source_box[0] + source_bounds[0], source_box[1] + source_bounds[1],
                        source_box[0] + source_bounds[2], source_box[1] + source_bounds[3],
                    )
                    for base_name, filename in source_filenames.items():
                        variant_name = f"source_expanded_{base_name}"
                        transform = "re-crop candidate source with 15% horizontal cell margin -> crop only to top ink band"
                        if base_name == "label_free_grayscale":
                            transform += " -> grayscale"
                        elif base_name == "label_free_thresholded":
                            transform += " -> grayscale -> threshold at 210"
                        output.append(_row_values(
                            object_row, variant_name=variant_name, parent_path=source_path,
                            variant_path=(Path(output_dir) / filename).resolve(), variant_filename=filename,
                            parent_size=source_image.size, bounds=source_structure_bounds,
                            caption_separation_status=source_caption_status, transform_steps=transform,
                        ))
        processed += 1
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": VARIANT_VERSION,
        "objects_eligible": len(selected),
        "objects_processed": processed,
        "objects_failed": len(failures),
        "variant_rows": len(output),
        "caption_removed_objects": sum(row["caption_separation_status"] == "caption_removed_by_blank_band" and row["variant_name"] == "original_object_crop" for row in output),
        "failures": failures,
        "manifest_path": str(Path(manifest_path).resolve()),
    }
    _atomic_write_csv(manifest_path, output)
    _atomic_write_json(summary_path, summary)
    return output, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    rows, summary = write_variant_snapshot(
        read_csv(args.objects), args.output_dir, args.manifest, args.summary,
    )
    print(json.dumps({**summary, "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
