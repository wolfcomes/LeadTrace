#!/usr/bin/env python3
"""Run proposal-only OCSR on already isolated first-page molecule objects.

This is deliberately a second step after ``build_first_page_molecule_review``.
It never sends fragment-only or non-structure objects to DECIMER and never
promotes an OCSR result to a confirmed chemical structure.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping, Callable

from rdkit import Chem
from rdkit import RDLogger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBJECTS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_PROPOSALS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_proposals.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_ocr_summary.json"
DEFAULT_CACHE = PROJECT_ROOT / "08_ocsr_benchmark" / "decimer_model"

PROPOSAL_FIELDS = (
    "object_id", "paper_id", "paper_rank", "candidate_id", "page", "object_type",
    "compound_label", "crop_path", "raw_smiles", "token_confidences",
    "mean_token_confidence", "min_token_confidence", "inference_status",
    "inference_error", "rdkit_status", "canonical_smiles", "heuristic_primary_component_smiles", "model_version",
    "proposal_quality", "review_status", "updated_at",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: Iterable[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
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


def select_ocr_objects(
    objects: Iterable[Mapping[str, object]], *, offset: int = 0, limit: int | None = None,
) -> list[dict[str, str]]:
    selected = []
    for row in objects:
        if str(row.get("smiles_source", "")).strip() != "isolated_object_pending_ocsr":
            continue
        crop_path = str(row.get("crop_path", "") or "").strip()
        if not crop_path or crop_path == "--":
            continue
        selected.append({field: str(row.get(field, "") or "") for field in row.keys()})
    selected.sort(key=lambda row: (
        int(row.get("paper_rank", "9999") or "9999") if row.get("paper_rank", "").isdigit() else 9999,
        row.get("object_id", ""),
    ))
    return selected[offset: offset + limit if limit is not None else None]


def validate_proposal_smiles(raw_smiles: str) -> dict[str, str]:
    """Return RDKit syntax information without claiming visual correctness."""
    raw_smiles = str(raw_smiles or "").strip()
    if not raw_smiles:
        return {"rdkit_status": "invalid", "canonical_smiles": "", "heuristic_primary_component_smiles": "", "proposal_quality": "empty_smiles_needs_review"}
    RDLogger.DisableLog("rdApp.error")
    try:
        molecule = Chem.MolFromSmiles(raw_smiles)
    finally:
        RDLogger.EnableLog("rdApp.error")
    if molecule is None:
        return {"rdkit_status": "invalid", "canonical_smiles": "", "heuristic_primary_component_smiles": "", "proposal_quality": "invalid_smiles_needs_review"}
    canonical = Chem.MolToSmiles(molecule, isomericSmiles=True)
    components = []
    for component in raw_smiles.split("."):
        component_molecule = Chem.MolFromSmiles(component)
        if component_molecule is not None:
            components.append(component_molecule)
    primary = max(components, key=lambda item: (item.GetNumHeavyAtoms(), item.GetNumAtoms()), default=molecule)
    common_atoms = {"B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I", "Si", "Se"}
    suspicious = (
        raw_smiles.count(".") > 0
        or len(raw_smiles) > 180
        or any(atom.GetSymbol() not in common_atoms for atom in molecule.GetAtoms())
    )
    return {
        "rdkit_status": "valid",
        "canonical_smiles": canonical,
        "heuristic_primary_component_smiles": Chem.MolToSmiles(primary, isomericSmiles=True),
        "proposal_quality": "valid_but_suspicious_needs_review" if suspicious else "valid_but_needs_review",
    }


def _serialise_confidence(values: Iterable[object] | None) -> tuple[str, str, str]:
    records: list[dict[str, object]] = []
    for value in values or []:
        if isinstance(value, Mapping):
            token, score = value.get("token", ""), value.get("confidence", "")
        else:
            token, score = value  # type: ignore[misc]
        records.append({"token": str(token), "confidence": float(score)})
    scores = [float(item["confidence"]) for item in records]
    encoded = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
    return (
        encoded,
        str(sum(scores) / len(scores)) if scores else "",
        str(min(scores)) if scores else "",
    )


def _load_predictor(cache: Path) -> tuple[Callable[..., object], str]:
    """Load DECIMER after pointing pystow at the validated project cache.

    The project does not require a GPU for this review batch; TensorFlow may
    use CPU when no compatible GPU libraries are available.
    """
    os.environ["DECIMER-V2_HOME"] = str(Path(cache).resolve())
    import DECIMER

    predictor = getattr(DECIMER, "predict_SMILES", None)
    if predictor is None:
        raise RuntimeError("DECIMER does not expose predict_SMILES")
    return predictor, str(getattr(DECIMER, "__version__", "unknown"))


def _error_proposal(row: Mapping[str, object], error: Exception, model_version: str = "unknown") -> dict[str, str]:
    return {
        "object_id": str(row.get("object_id", "")), "paper_id": str(row.get("paper_id", "")),
        "paper_rank": str(row.get("paper_rank", "")), "candidate_id": str(row.get("candidate_id", "")),
        "page": str(row.get("page", "")), "object_type": str(row.get("object_type", "")),
        "compound_label": str(row.get("compound_label", "")), "crop_path": str(row.get("crop_path", "")),
        "raw_smiles": "", "token_confidences": "[]", "mean_token_confidence": "",
        "min_token_confidence": "", "inference_status": "error",
        "inference_error": f"{type(error).__name__}: {error}", "rdkit_status": "not_run",
        "canonical_smiles": "", "heuristic_primary_component_smiles": "", "model_version": model_version,
        "proposal_quality": "inference_error_needs_review",
        "review_status": "proposal_requires_human_review",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def infer_objects(
    objects: Iterable[Mapping[str, object]], cache: Path = DEFAULT_CACHE,
    *, predictor: Callable[..., object] | None = None, model_version: str | None = None,
) -> list[dict[str, str]]:
    selected = list(objects)
    if predictor is None:
        try:
            predictor, model_version = _load_predictor(cache)
        except Exception as error:
            return [_error_proposal(row, error) for row in selected]
    model_version = model_version or "unknown"
    output: list[dict[str, str]] = []
    for row in selected:
        try:
            raw_smiles, confidence_values = predictor(str(row["crop_path"]), confidence=True)  # type: ignore[misc]
            token_json, mean_confidence, min_confidence = _serialise_confidence(confidence_values)
            raw_smiles = str(raw_smiles or "")
            validated = validate_proposal_smiles(raw_smiles)
            output.append({
                **_error_proposal(row, RuntimeError("placeholder"), model_version),
                "raw_smiles": raw_smiles, "token_confidences": token_json,
                "mean_token_confidence": mean_confidence, "min_token_confidence": min_confidence,
                "inference_status": "ok", "inference_error": "", **validated,
            })
        except Exception as error:
            output.append(_error_proposal(row, error, model_version))
    return output


def merge_proposals_into_objects(
    objects: Iterable[Mapping[str, object]], proposals: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Overlay proposal fields while retaining the object review boundary."""
    by_id = {
        str(row.get("object_id", "")): {key: str(value or "") for key, value in row.items()}
        for row in objects if str(row.get("object_id", "")).strip()
    }
    for proposal in proposals:
        object_id = str(proposal.get("object_id", "")).strip()
        row = by_id.get(object_id)
        if row is None or row.get("review_status") in {"confirmed", "human_confirmed"}:
            continue
        row["raw_smiles"] = str(proposal.get("raw_smiles", "") or "") or "--"
        row["canonical_smiles"] = str(proposal.get("canonical_smiles", "") or "") or "--"
        row["heuristic_primary_component_smiles"] = str(proposal.get("heuristic_primary_component_smiles", "") or "") or "--"
        row["rdkit_status"] = str(proposal.get("rdkit_status", "not_run") or "not_run")
        quality = str(proposal.get("proposal_quality", "") or "")
        if row["rdkit_status"] == "valid":
            row["smiles_accuracy_state"] = (
                "isolated_object_syntax_valid_but_suspicious"
                if "suspicious" in quality else "isolated_object_syntax_valid_needs_visual_review"
            )
        elif row["rdkit_status"] == "invalid":
            row["smiles_accuracy_state"] = "isolated_object_smiles_invalid_needs_review"
        row["review_status"] = row.get("review_status") or "object_requires_human_review"
    return list(by_id.values())


def run_batch(
    objects_path: Path = DEFAULT_OBJECTS, proposals_path: Path = DEFAULT_PROPOSALS,
    summary_path: Path = DEFAULT_SUMMARY, cache: Path = DEFAULT_CACHE,
    *, offset: int = 0, limit: int | None = None, resume: bool = True,
    infer: bool = True,
) -> dict[str, object]:
    objects = read_csv(objects_path)
    selected = select_ocr_objects(objects, offset=offset, limit=limit)
    old_proposals = read_csv(proposals_path) if resume and proposals_path.is_file() else []
    for proposal in old_proposals:
        raw_smiles = str(proposal.get("raw_smiles", "") or "").strip()
        if raw_smiles:
            proposal.update(validate_proposal_smiles(raw_smiles))
    processed = {row.get("object_id") for row in old_proposals if row.get("object_id")}
    to_infer = [row for row in selected if row.get("object_id") not in processed]
    incoming = infer_objects(to_infer, cache) if infer and to_infer else []
    by_id = {row.get("object_id"): row for row in old_proposals if row.get("object_id")}
    for row in incoming:
        by_id[row["object_id"]] = row
    proposals = [by_id[key] for key in sorted(by_id)]
    merged_objects = merge_proposals_into_objects(objects, proposals)
    _atomic_write_csv(proposals_path, proposals, PROPOSAL_FIELDS)
    object_fields = tuple(dict.fromkeys([*(objects[0].keys() if objects else ()), "heuristic_primary_component_smiles"]))
    _atomic_write_csv(objects_path, merged_objects, object_fields)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "object_rows": len(objects), "eligible_object_rows": len(select_ocr_objects(objects)),
        "selected_object_rows": len(selected), "ocr_attempted": len(proposals),
        "inference_ok": sum(row.get("inference_status") == "ok" for row in proposals),
        "inference_errors": sum(row.get("inference_status") == "error" for row in proposals),
        "rdkit_valid": sum(row.get("rdkit_status") == "valid" for row in proposals),
        "rdkit_invalid": sum(row.get("rdkit_status") == "invalid" for row in proposals),
        "proposal_quality_counts": dict(Counter(row.get("proposal_quality", "") for row in proposals)),
        "review_status": "proposal_requires_human_review",
        "objects_path": str(objects_path.resolve()), "proposals_path": str(proposals_path.resolve()),
    }
    _atomic_write_json(summary_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-infer", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)
    result = run_batch(
        args.objects, args.proposals, args.summary, args.cache_dir,
        offset=args.offset, limit=args.limit, resume=not args.no_resume, infer=not args.no_infer,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
