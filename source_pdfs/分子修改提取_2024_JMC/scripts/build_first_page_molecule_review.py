#!/usr/bin/env python3
"""Build a molecule-level, image-first review snapshot for the first 20 Papers.

Page crops are evidence regions, not molecules.  This builder creates smaller
objects for isolated compounds, shared scaffolds, replacement fragments, and
linkers, while dropping regions that are explicitly charts, text, protein
scenes, or 3D-only renderings.  It intentionally does not copy a page-level
OCSR proposal onto a child object: SMILES inference is only eligible after the
visual object has been isolated and its attachment semantics have been recorded.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_fragment_review.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_summary.json"
DEFAULT_CROPS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "molecule_review_crops"
MISSING = "--"
ANNOTATION_VERSION = "first_page_molecule_objects_v2_2026-09-07"
EXCLUDED_OBJECT_TYPES = {"non_structure_region", "three_d_structure_evidence"}

OBJECT_FIELDS = (
    "object_id", "paper_rank", "paper_id", "title_guess", "source_pdf", "page",
    "figure_id", "candidate_id", "object_index", "object_type", "object_role",
    "compound_label", "parent_object_id", "derived_object_id",
    "source_crop_path", "crop_path", "x0", "y0", "x1", "y1",
    "local_x0", "local_y0", "local_x1", "local_y1", "local_bbox_normalized",
    "structure_scope", "localization_status", "split_status", "visible_notation",
    "shared_scaffold", "visible_fragment", "attachment_points",
    "relationship_evidence", "inference_steps", "smiles_source", "raw_smiles",
    "canonical_smiles", "heuristic_primary_component_smiles", "rdkit_status", "smiles_accuracy_state", "review_status",
    "review_note", "annotation_version",
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
            writer = csv.DictWriter(handle, fieldnames=OBJECT_FIELDS, extrasaction="ignore")
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


def _text(row: Mapping[str, object], key: str, default: str = MISSING) -> str:
    value = str(row.get(key, "") or "").strip()
    return value or default


def _number(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalised_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    return tuple(max(0.0, min(1.0, value)) for value in (x0, y0, x1, y1))  # type: ignore[return-value]


def _box_text(box: tuple[float, float, float, float]) -> str:
    return ",".join(f"{value:.4f}" for value in _normalised_box(box))


def _first_compound_label(row: Mapping[str, object]) -> str:
    value = _text(row, "compound_ids")
    if value == MISSING:
        return MISSING
    return value.split("|")[0].strip() or MISSING


def classify_object_smiles_state(object_type: str, ready_for_ocsr: bool = False) -> str:
    if object_type == "non_structure_region":
        return "not_applicable_non_structure"
    if object_type == "three_d_structure_evidence":
        return "not_applicable_3d_structure"
    if object_type == "mixed_structure_evidence":
        return "mixed_region_requires_split"
    if object_type in {
        "shared_scaffold", "replacement_fragment", "linker_fragment", "variable_site",
    }:
        return "fragment_not_whole_molecule"
    if object_type == "mixed_region_molecule":
        return "isolated_molecule_awaiting_ocsr" if ready_for_ocsr else "mixed_region_requires_split"
    if object_type == "molecule_series_member":
        return "isolated_object_awaiting_ocsr" if ready_for_ocsr else "series_member_requires_local_split"
    return "isolated_object_awaiting_ocsr" if ready_for_ocsr else "object_boundary_requires_review"


def is_retained_structure_object(object_type: str) -> bool:
    """Keep chemical structures and fragments, not charts or 3D-only regions."""
    return object_type not in EXCLUDED_OBJECT_TYPES


def _common_fields(
    row: Mapping[str, object], object_type: str, box: tuple[float, float, float, float],
    *, ready_for_ocsr: bool = False,
) -> dict[str, str]:
    scope = _text(row, "visual_scope", "unknown")
    if object_type == "non_structure_region":
        localization = "classified_non_structure"
        split_status = "not_applicable"
        smiles_source = "excluded_non_structure_region"
        steps = "classify image region -> exclude charts/text/protein scene from molecular OCSR"
    elif object_type == "three_d_structure_evidence":
        localization = "3d_structure_region_identified"
        split_status = "not_eligible_for_2d_ocsr"
        smiles_source = "not_applicable_3d_rendering"
        steps = "locate 3D molecular rendering -> preserve as structural evidence -> do not apply 2D OCSR"
    elif object_type == "mixed_structure_evidence":
        localization = "mixed_region_not_yet_split"
        split_status = "requires_molecule_boundary_annotation"
        smiles_source = "excluded_until_local_split"
        steps = "locate molecular subregion -> separate it from chart/spectrum/assay imagery -> only then evaluate OCSR"
    elif object_type in {"shared_scaffold", "replacement_fragment", "linker_fragment", "variable_site"}:
        localization = "structure_object_localized"
        split_status = "isolated_fragment_requires_connectivity_review"
        smiles_source = "attachment_point_notation_only"
        steps = "locate labeled structure -> isolate scaffold/fragment -> preserve endpoint notation -> infer connectivity before SMILES"
    elif object_type == "mixed_region_molecule":
        localization = "molecule_located_inside_mixed_region"
        split_status = "local_split_completed_non_structure_removed"
        smiles_source = "isolated_object_pending_ocsr" if ready_for_ocsr else "local_boundary_requires_review"
        steps = "locate molecule subregion -> remove adjacent assay imagery -> inspect atom/bond correspondence -> run OCSR"
    else:
        localization = "isolated_2d_molecule_region"
        split_status = "isolated_object_ready_for_ocsr"
        smiles_source = "isolated_object_pending_ocsr" if ready_for_ocsr else "series_member_shared_region"
        steps = "locate one labeled 2D molecule -> confirm label boundary -> run OCSR -> visually verify atom and bond graph" if ready_for_ocsr else "locate numbered member -> separate it from neighboring members -> confirm label boundary -> run OCSR"
    return {
        "structure_scope": scope if scope != MISSING else "unknown",
        "localization_status": localization,
        "split_status": split_status,
        "visible_notation": _text(row, "visible_notation"),
        "shared_scaffold": MISSING,
        "visible_fragment": MISSING,
        "attachment_points": _text(row, "attachment_points"),
        "relationship_evidence": _text(row, "text_evidence"),
        "inference_steps": steps,
        "smiles_source": smiles_source,
        "raw_smiles": MISSING,
        "canonical_smiles": MISSING,
        "heuristic_primary_component_smiles": MISSING,
        "rdkit_status": "not_run",
        "smiles_accuracy_state": classify_object_smiles_state(object_type, ready_for_ocsr),
        "review_status": "object_requires_human_review",
        "review_note": MISSING,
        "local_bbox_normalized": _box_text(box),
        "local_x0": f"{box[0]:.4f}", "local_y0": f"{box[1]:.4f}",
        "local_x1": f"{box[2]:.4f}", "local_y1": f"{box[3]:.4f}",
    }


def _spec(
    object_type: str,
    label: str = MISSING,
    box: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    *,
    role: str = "molecule_or_fragment",
    notation: str | None = None,
    fragment: str | None = None,
    scaffold: str | None = None,
    attachment: str | None = None,
    note: str | None = None,
    parent_index: int | None = None,
    ready_for_ocsr: bool = False,
) -> dict[str, object]:
    return {
        "object_type": object_type, "compound_label": label, "box": _normalised_box(box),
        "object_role": role, "notation": notation, "fragment": fragment,
        "scaffold": scaffold, "attachment": attachment, "note": note,
        "parent_index": parent_index,
        "ready_for_ocsr": ready_for_ocsr,
    }


def _grid_boxes(columns: int, rows: int, y_margin: float = 0.0, y_gap: float = 0.0) -> list[tuple[float, float, float, float]]:
    width = 1.0 / columns
    height = (1.0 - y_margin * 2 - y_gap * (rows - 1)) / rows
    return [
        (column * width, y_margin + row * (height + y_gap), (column + 1) * width,
         y_margin + row * (height + y_gap) + height)
        for row in range(rows) for column in range(columns)
    ]


def _explicit_specs(candidate_id: str) -> list[dict[str, object]] | None:
    """Return manually reviewed layout hints for known first-page figures.

    These are localization annotations, not chemical structure claims.  A
    repeated box means several labels share one drawn scaffold and therefore
    remains a connectivity-review item.
    """
    if candidate_id == "PAGE-5d639341273b-CAND-001":
        labels = ["1", "2a", "2b", "2c", "2d", "2e", "2f", "2g", "2h", "2i", "2j", "2k", "2l", "2m", "2n", "2o"]
        return [_spec("molecule_series_member", label, box, role="numbered_series_member", scaffold="danuglipron-like common scaffold visible; exact graph pending OCSR", ready_for_ocsr=True) for label, box in zip(labels, _grid_boxes(4, 4))]

    if candidate_id == "PAGE-d79ad4b6d9ff-CAND-001":
        return [_spec("molecule_series_member", label, (index / 3, 0.0, (index + 1) / 3, 0.98), role="numbered_series_member", scaffold="common triazole-containing scaffold visible", ready_for_ocsr=True) for index, label in enumerate(("10", "11", "12"))]

    if candidate_id == "PAGE-b70cf253ca57-CAND-001":
        labels = ("34", "35", "36")
        boxes = ((0.10, 0.02, 0.71, 0.34), (0.10, 0.34, 0.71, 0.67), (0.10, 0.67, 0.71, 1.0))
        return [_spec("molecule_series_member", label, box, role="numbered_table_member", scaffold="common table scaffold visible", ready_for_ocsr=True) for label, box in zip(labels, boxes)]

    if candidate_id == "PAGE-8b83aebf4c53-CAND-002":
        labels = ("3", "4", "5", "6", "7", "25", "26", "27", "28", "29")
        boxes = [
            (index / 5, 0.0, (index + 1) / 5, 0.30) for index in range(5)
        ] + [
            (index / 5, 0.29, (index + 1) / 5, 0.59) for index in range(5)
        ]
        return [_spec("molecule_series_member", label, box, role="numbered_series_member", scaffold="common bicyclic heteroaromatic scaffold visible", ready_for_ocsr=True) for label, box in zip(labels, boxes)]

    if candidate_id == "PAGE-6f29995b606f-CAND-003":
        return [
            _spec("molecule_series_member", "3", (0.00, 0.00, 0.49, 0.39), role="numbered_series_member", scaffold="common scaffold with Site 3 substitution", ready_for_ocsr=True),
            _spec("molecule_series_member", "21", (0.43, 0.00, 0.76, 0.39), role="numbered_series_member", scaffold="common scaffold with Site 3 substitution", ready_for_ocsr=True),
            _spec("non_structure_region", MISSING, (0.0, 0.36, 1.0, 1.0), role="binding_scene_and_activity_chart"),
        ]

    if candidate_id == "PAGE-3d1249a64e3d-CAND-002":
        return [_spec("mixed_region_molecule", "L22", (0.02, 0.13, 0.43, 0.94), role="molecule_in_mixed_figure", scaffold="isolated 2D molecule at left of assay images", ready_for_ocsr=True)]

    if candidate_id == "PAGE-884593225a2c-CAND-001":
        return [_spec("complete_molecule", _first_compound_label({"compound_ids": "--"}), (0.10, 0.0, 0.92, 1.0), role="isolated_2d_molecule", scaffold="single complete 2D molecule; formula shown", ready_for_ocsr=True)]

    if candidate_id == "PAGE-2389b5da8795-CAND-001":
        return [_spec("three_d_structure_evidence", MISSING, (0.0, 0.0, 1.0, 1.0), role="3d_molecular_rendering")]

    if candidate_id == "PAGE-889b08022bee-CAND-001":
        return [
            _spec("shared_scaffold", MISSING, (0.02, 0.02, 0.94, 0.98), role="parent_scaffold", notation="B", scaffold="parent scaffold with unresolved B attachment site", attachment="B", note="B is an attachment point, not an atom label"),
            _spec("variable_site", "B", (0.74, 0.70, 1.0, 1.0), role="variable_site_marker", notation="B", fragment="B substituent not drawn in this figure", attachment="B", parent_index=0),
        ]

    if candidate_id == "PAGE-889b08022bee-CAND-003":
        labels = ("11", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24")
        boxes = [(0.18, 0.09 + index * 0.069, 0.43, 0.16 + index * 0.069) for index in range(len(labels))]
        return [_spec("replacement_fragment", label, box, role="B_table_replacement_fragment", notation="B", fragment="B-column replacement drawing or group", attachment="B", note="Table cell is a fragment; do not expand into a full parent without the parent scaffold") for label, box in zip(labels, boxes)]

    if candidate_id == "PAGE-880042186935-CAND-001":
        return [
            _spec("shared_scaffold", "6-8", (0.01, 0.0, 0.50, 0.47), role="parent_scaffold", notation="Site 1", scaffold="parent scaffold with Site 1 attachment", attachment="Site 1"),
            _spec("replacement_fragment", "3", (0.04, 0.44, 0.28, 0.72), role="Site_1_replacement_fragment", notation="Site 1", fragment="piperidine-like replacement drawing", attachment="Site 1", parent_index=0),
            _spec("replacement_fragment", "5", (0.28, 0.44, 0.53, 0.72), role="Site_1_replacement_fragment", notation="Site 1", fragment="morpholine-like replacement drawing", attachment="Site 1", parent_index=0),
            _spec("replacement_fragment", "6", (0.04, 0.66, 0.28, 1.0), role="Site_1_replacement_fragment", notation="Site 1", fragment="amide replacement drawing", attachment="Site 1", parent_index=0),
            _spec("replacement_fragment", "7", (0.28, 0.66, 0.53, 1.0), role="Site_1_replacement_fragment", notation="Site 1", fragment="amide replacement drawing", attachment="Site 1", parent_index=0),
        ]

    if candidate_id == "PAGE-6f29995b606f-CAND-001":
        return [
            _spec("shared_scaffold", MISSING, (0.27, 0.13, 0.68, 0.88), role="annotated_parent_scaffold", notation="Site 1; Site 2; Site 3; R1; R2", scaffold="common scaffold is visible, but annotations overlap the figure", attachment="Site 1; Site 2; Site 3"),
            _spec("variable_site", "Site 3", (0.17, 0.22, 0.44, 0.59), role="variable_site_fragment", notation="Site 3; R1; R2", fragment="R1/R2 fragment shown in highlighted Site 3 region", attachment="Site 3", parent_index=0),
            _spec("variable_site", "Site 1", (0.47, 0.18, 0.70, 0.82), role="variable_site_marker", notation="Site 1", fragment="hydrophobic/linker region", attachment="Site 1", parent_index=0),
            _spec("variable_site", "Site 2", (0.67, 0.20, 0.98, 0.73), role="variable_site_marker", notation="Site 2", fragment="carboxylic-acid region", attachment="Site 2", parent_index=0),
        ]

    if candidate_id == "PAGE-d867a063e9f9-CAND-001":
        return [_spec("replacement_fragment", label, box, role="plot_substituent_fragment", notation=label, fragment="colored substituent fragment below selectivity plot", attachment=label) for label, box in zip(("R2", "R3", "R1", "R4"), ((0.17, 0.57, 0.29, 0.99), (0.42, 0.57, 0.55, 0.99), (0.67, 0.57, 0.79, 0.99), (0.91, 0.57, 1.0, 0.99)))]

    if candidate_id == "PAGE-d867a063e9f9-CAND-002":
        return [_spec("replacement_fragment", label, box, role="plot_substituent_fragment", notation=label, fragment="colored substituent fragment below selectivity plot", attachment=label) for label, box in zip(("R2", "R3", "R1", "R4"), ((0.16, 0.53, 0.30, 0.99), (0.40, 0.53, 0.55, 0.99), (0.65, 0.53, 0.80, 0.99), (0.89, 0.53, 1.0, 0.99)))]

    if candidate_id == "PAGE-621e2220dc85-CAND-001":
        specs: list[dict[str, object]] = []
        groups = [
            (("3",), (0.00, 0.03, 0.23, 0.48)),
            (("4", "5", "6"), (0.25, 0.05, 0.46, 0.48)),
            (("7", "8", "9"), (0.40, 0.03, 0.68, 0.48)),
            (("10a", "10b", "10c", "10d", "10e"), (0.68, 0.00, 1.00, 0.42)),
            (("13a", "13b", "13c", "13d", "13e", "14a", "15a", "15b", "15c", "15d", "15e"), (0.00, 0.43, 0.36, 0.79)),
            (("16a", "16b", "16c", "16d", "16e", "17a", "18a", "18b", "18c", "18d", "18e"), (0.36, 0.43, 0.69, 0.79)),
            (("19a", "19b", "19c", "19d", "19e", "20a", "21a", "21b", "21c", "21d", "21e"), (0.69, 0.43, 1.00, 0.79)),
        ]
        for labels, box in groups:
            for label in labels:
                specs.append(_spec("molecule_series_member", label, box, role="reaction_series_member", notation="R1; R2; Linker a-e", scaffold="common reaction-series scaffold; label-to-drawing binding requires review", attachment="R1; R2; Linker", note="numbered member shares a reaction-panel region; isolate its individual drawing before OCSR", ready_for_ocsr=False))
        linker_boxes = ((0.05, 0.78, 0.25, 1.0), (0.25, 0.78, 0.43, 1.0), (0.43, 0.78, 0.65, 1.0), (0.65, 0.78, 0.84, 1.0), (0.84, 0.78, 1.0, 1.0))
        for label, box in zip(("a", "b", "c", "d", "e"), linker_boxes):
            specs.append(_spec("linker_fragment", f"Linker {label}", box, role="linker_fragment", notation=f"Linker {label}", fragment="linker drawing with two attachment endpoints", attachment=f"Linker {label}"))
        return specs

    return None


def _fallback_specs(row: Mapping[str, object]) -> list[dict[str, object]]:
    scope = _text(row, "visual_scope", "unknown")
    if scope == "non_structure_region":
        return [_spec("non_structure_region", role="non_chemical_structure_region")]
    if scope == "mixed_structure_evidence":
        return [_spec("mixed_structure_evidence", role="mixed_region_requires_split", note="molecule boundary not yet localized")]
    if scope == "complete_molecule_candidate":
        return [_spec("complete_molecule", _first_compound_label(row), role="isolated_2d_molecule", ready_for_ocsr=True)]
    if scope == "complete_molecule_series":
        return [_spec("molecule_series_member", _first_compound_label(row), role="series_requires_label_split", note="candidate contains multiple numbered structures; split rule not yet assigned")]
    if scope == "fragment_or_series":
        return [_spec("shared_scaffold", role="fragment_or_series_requires_split", notation=_text(row, "visible_notation"), attachment=_text(row, "attachment_points"), note="candidate needs manual local boundary before fragment-specific OCSR")]
    return [_spec("mixed_structure_evidence", role="unknown_region_requires_review", note="visual scope is not yet determined")]


def _render_local_crop(source_path: str, output_path: Path, box: tuple[float, float, float, float]) -> str:
    if not source_path or source_path == MISSING or not Path(source_path).is_file():
        return MISSING
    try:
        from PIL import Image

        with Image.open(source_path) as image:
            width, height = image.size
            left = max(0, min(width - 1, math.floor(box[0] * width)))
            top = max(0, min(height - 1, math.floor(box[1] * height)))
            right = max(left + 1, min(width, math.ceil(box[2] * width)))
            bottom = max(top + 1, min(height, math.ceil(box[3] * height)))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.crop((left, top, right, bottom)).save(output_path)
        return str(output_path.resolve())
    except (OSError, ValueError, ImportError):
        return MISSING


def _build_object(row: Mapping[str, object], spec: Mapping[str, object], index: int, output_dir: Path | None, render_crops: bool) -> dict[str, str]:
    candidate_id = _text(row, "candidate_id")
    box = tuple(spec.get("box", (0.0, 0.0, 1.0, 1.0)))  # type: ignore[arg-type]
    object_type = str(spec.get("object_type", "mixed_structure_evidence"))
    object_id = f"OBJ-{candidate_id}-OBJ-{index:03d}"
    source_crop = _text(row, "crop_path")
    crop_path = MISSING
    if render_crops and output_dir is not None:
        crop_path = _render_local_crop(source_crop, output_dir / f"{object_id}.png", box)
    base = _common_fields(row, object_type, box, ready_for_ocsr=bool(spec.get("ready_for_ocsr", False)))
    parent_index = spec.get("parent_index")
    parent_id = f"OBJ-{candidate_id}-OBJ-{int(parent_index) + 1:03d}" if parent_index is not None else MISSING
    if spec.get("notation"):
        base["visible_notation"] = str(spec["notation"])
    if spec.get("attachment"):
        base["attachment_points"] = str(spec["attachment"])
    if spec.get("scaffold"):
        base["shared_scaffold"] = str(spec["scaffold"])
    if spec.get("fragment"):
        base["visible_fragment"] = str(spec["fragment"])
    if spec.get("note"):
        base["review_note"] = str(spec["note"])
    candidate_box = (_text(row, "x0"), _text(row, "y0"), _text(row, "x1"), _text(row, "y1"))
    values = {
        "object_id": object_id, "paper_rank": _text(row, "paper_rank"), "paper_id": _text(row, "paper_id"),
        "title_guess": _text(row, "title_guess"), "source_pdf": _text(row, "source_pdf"), "page": _text(row, "page"),
        "figure_id": candidate_id.rsplit("-CAND-", 1)[0], "candidate_id": candidate_id, "object_index": str(index),
        "object_type": object_type, "object_role": str(spec.get("object_role", "molecule_or_fragment")),
        "compound_label": str(spec.get("compound_label", MISSING)), "parent_object_id": parent_id,
        "derived_object_id": MISSING, "source_crop_path": source_crop, "crop_path": crop_path,
        "x0": candidate_box[0], "y0": candidate_box[1], "x1": candidate_box[2], "y1": candidate_box[3],
        **base, "annotation_version": ANNOTATION_VERSION,
    }
    return {field: str(values.get(field, MISSING) or MISSING) for field in OBJECT_FIELDS}


def build_molecule_objects(
    candidates: Iterable[Mapping[str, object]],
    *,
    crop_output_dir: Path | None = None,
    render_crops: bool = True,
) -> list[dict[str, str]]:
    rows = sorted(
        [dict(row) for row in candidates],
        key=lambda row: (_number(row.get("paper_rank"), 9999), _text(row, "candidate_id")),
    )
    output: list[dict[str, str]] = []
    for row in rows:
        candidate_id = _text(row, "candidate_id")
        specs = _explicit_specs(candidate_id) or _fallback_specs(row)
        for index, spec in enumerate(specs, 1):
            if not is_retained_structure_object(str(spec.get("object_type", "mixed_structure_evidence"))):
                continue
            output.append(_build_object(row, spec, index, crop_output_dir, render_crops))
    return output


def write_molecule_snapshot(
    candidates: Iterable[Mapping[str, object]],
    output_path: Path = DEFAULT_OUTPUT,
    summary_path: Path = DEFAULT_SUMMARY,
    *,
    crop_output_dir: Path | None = None,
    render_crops: bool = True,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    candidate_rows = [dict(row) for row in candidates]
    all_specs = [
        spec
        for row in candidate_rows
        for spec in (_explicit_specs(_text(row, "candidate_id")) or _fallback_specs(row))
    ]
    filtered_object_types = Counter(
        str(spec.get("object_type", "mixed_structure_evidence"))
        for spec in all_specs
        if not is_retained_structure_object(str(spec.get("object_type", "mixed_structure_evidence")))
    )
    rows = build_molecule_objects(candidate_rows, crop_output_dir=crop_output_dir, render_crops=render_crops)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": ANNOTATION_VERSION,
        "candidate_rows": len({str(row.get("candidate_id", "")) for row in candidate_rows if row.get("candidate_id")}),
        "object_rows": len(rows),
        "object_rows_before_filter": len(all_specs),
        "filtered_object_rows": sum(filtered_object_types.values()),
        "filtered_object_type_counts": dict(filtered_object_types),
        "object_type_counts": dict(Counter(row["object_type"] for row in rows)),
        "paper_counts": dict(Counter(row["paper_id"] for row in rows)),
        "smiles_state_counts": dict(Counter(row["smiles_accuracy_state"] for row in rows)),
        "rdkit_status_counts": dict(Counter(row["rdkit_status"] for row in rows)),
        "eligible_for_isolated_ocsr": sum(row["smiles_source"] == "isolated_object_pending_ocsr" for row in rows),
        "fragment_objects_preserving_endpoints": sum(row["smiles_source"] == "attachment_point_notation_only" for row in rows),
        "non_structure_objects_excluded": filtered_object_types.get("non_structure_region", 0),
        "source_path": str(DEFAULT_INPUT.resolve()),
    }
    _atomic_write_csv(output_path, rows)
    _atomic_write_json(summary_path, summary)
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--crops-dir", type=Path, default=DEFAULT_CROPS)
    parser.add_argument("--no-crops", action="store_true")
    args = parser.parse_args(argv)
    rows, summary = write_molecule_snapshot(
        read_csv(args.input), args.output, args.summary,
        crop_output_dir=args.crops_dir, render_crops=not args.no_crops,
    )
    print(json.dumps({**summary, "output": str(args.output.resolve()), "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
