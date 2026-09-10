#!/usr/bin/env python3
"""Build conservative, auditable SMILES reconstruction candidates.

The input is the object-level first-page snapshot and the proposal-only OCSR
layer.  This module never edits the confirmed structure dataset.  It treats a
SMILES string as the last representation of a reconstructed graph, not as
evidence that the graph was read correctly from the image.
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
import re
import tempfile
from typing import Iterable, Mapping

from rdkit import Chem
from rdkit import RDLogger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBJECTS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_objects.csv"
DEFAULT_PROPOSALS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_proposals.csv"
DEFAULT_REFERENCES = PROJECT_ROOT / "09_structure_confirmation" / "compound_smiles_reference.csv"
DEFAULT_EXTERNAL_REFERENCES = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_external_references.csv"
DEFAULT_MODEL_VISUAL_REVIEWS = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_model_visual_reviews.csv"
DEFAULT_DOCUMENTS = PROJECT_ROOT / "02_text_extraction" / "full_document_text_index.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_reconstructions.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "first_page_molecule_reconstruction_summary.json"

MISSING = "--"
RECONSTRUCTION_VERSION = "first_page_molecule_reconstruction_v1_2026-09-05"

RECONSTRUCTION_FIELDS = (
    "object_id", "paper_rank", "paper_id", "doi", "candidate_id", "page",
    "object_type", "compound_label", "crop_path", "attachment_points",
    "smiles_source",
    "raw_model_smiles", "model_canonical_smiles", "model_primary_component_smiles",
    "cleaned_candidate_smiles", "removed_components", "removed_component_count",
    "selection_reason", "component_diagnostics", "reference_smiles",
    "reference_source_type", "reference_source_file", "reference_source_locator",
    "reconstructed_smiles", "reconstructed_canonical_smiles", "reconstruction_status",
    "reconstruction_confidence", "reconstruction_steps", "review_status",
    "annotation_version", "updated_at",
)

_METAL_SYMBOLS = {
    "Li", "Na", "K", "Rb", "Cs", "Fr", "Be", "Mg", "Ca", "Sr", "Ba", "Ra",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "Hf", "Ta", "W", "Re",
    "Os", "Ir", "Pt", "Au", "Hg", "Al", "Ga", "In", "Tl", "Sn", "Pb", "Bi",
    "Po", "At", "Rn", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
    "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Ac", "Th", "Pa", "U", "Np", "Pu",
}
_ISOTOPE = re.compile(r"\[(?:\d{1,3}[A-Z][a-z]?|[A-Z][a-z]?\d{1,3})")
_LABEL_NORMALIZER = re.compile(r"[^a-z0-9]+")


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
            writer = csv.DictWriter(handle, fieldnames=list(RECONSTRUCTION_FIELDS), extrasaction="ignore")
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


def _parse_component(component: str) -> Chem.Mol | None:
    if not component:
        return None
    RDLogger.DisableLog("rdApp.error")
    try:
        return Chem.MolFromSmiles(component)
    finally:
        RDLogger.EnableLog("rdApp.error")


def _atom_symbols(molecule: Chem.Mol) -> set[str]:
    return {atom.GetSymbol() for atom in molecule.GetAtoms()}


def _has_isotope(component: str, molecule: Chem.Mol) -> bool:
    return bool(_ISOTOPE.search(component)) or any(atom.GetIsotope() for atom in molecule.GetAtoms())


def _without_isotopes(molecule: Chem.Mol) -> Chem.Mol:
    """Remove isotope labels from a selected graph without changing its bonds."""
    result = Chem.Mol(molecule)
    for atom in result.GetAtoms():
        atom.SetIsotope(0)
    return result


def _diagnose_component(component: str, molecule: Chem.Mol | None) -> dict[str, object]:
    if molecule is None:
        return {
            "component": component, "parse_status": "invalid", "heavy_atoms": 0,
            "rings": 0, "symbols": [], "rejected": True, "reject_reasons": ["invalid_smiles"],
        }
    symbols = _atom_symbols(molecule)
    reasons: list[str] = []
    if symbols & _METAL_SYMBOLS:
        reasons.append("metal_or_counterion")
    has_isotope = _has_isotope(component, molecule)
    # DECIMER frequently emits a spurious isotope on a large organic graph
    # when a nearby label or activity value touches the crop.  Keep the graph
    # eligible, but strip the label in the cleaned candidate and record it in
    # diagnostics.  Small isolated isotope components remain rejected.
    normalizable_isotope = has_isotope and molecule.GetNumHeavyAtoms() >= 12 and molecule.GetRingInfo().NumRings() >= 1
    if has_isotope and not normalizable_isotope:
        reasons.append("isotope_or_radiolabel")
    if molecule.GetNumHeavyAtoms() == 0:
        reasons.append("no_heavy_atoms")
    if symbols <= {"C", "H"} and molecule.GetRingInfo().NumRings() == 0 and molecule.GetNumHeavyAtoms() >= 12:
        reasons.append("long_acyclic_carbon_noise")
    if component in {"[C-]#[O+]", "C#N", "[C-]#N", "[CH3-]", "C", "CC", "CCC", "CCCC"}:
        reasons.append("small_repeated_noise_component")
    return {
        "component": component,
        "parse_status": "valid",
        "heavy_atoms": molecule.GetNumHeavyAtoms(),
        "rings": molecule.GetRingInfo().NumRings(),
        "symbols": sorted(symbols),
        "normalizable_isotope": normalizable_isotope,
        "rejected": bool(reasons),
        "reject_reasons": reasons,
    }


def _component_score(diagnostic: Mapping[str, object]) -> float:
    """Score a plausible organic graph, not the longest decoded string."""
    if diagnostic.get("rejected"):
        return -math.inf
    heavy_atoms = int(diagnostic.get("heavy_atoms", 0))
    rings = int(diagnostic.get("rings", 0))
    symbols = set(diagnostic.get("symbols", []))
    score = float(heavy_atoms)
    score += rings * 8.0
    score += len(symbols & {"N", "O", "S", "P", "F", "Cl", "Br", "I"}) * 2.0
    if symbols <= {"C", "H"} and rings == 0:
        score -= 5.0
    return score


def choose_primary_component(raw_smiles: str) -> dict[str, str]:
    """Select a likely molecular graph and explain every discarded component.

    This is intentionally a candidate cleaner.  It does not assert that the
    selected graph is visually correct and never changes ``raw_smiles``.
    """
    raw_smiles = str(raw_smiles or "").strip()
    if not raw_smiles or raw_smiles == MISSING:
        return {
            "cleaned_candidate_smiles": MISSING, "removed_components": "[]",
            "removed_component_count": "0", "selection_reason": "no_model_smiles",
            "component_diagnostics": "[]",
        }
    diagnostics: list[dict[str, object]] = []
    for component in raw_smiles.split("."):
        diagnostics.append(_diagnose_component(component, _parse_component(component)))
    plausible = [item for item in diagnostics if not item["rejected"]]
    if not plausible:
        return {
            "cleaned_candidate_smiles": MISSING,
            "removed_components": json.dumps([item["component"] for item in diagnostics], ensure_ascii=True, separators=(",", ":")),
            "removed_component_count": str(len(diagnostics)),
            "selection_reason": "no_plausible_organic_component",
            "component_diagnostics": json.dumps(diagnostics, ensure_ascii=True, separators=(",", ":")),
        }
    selected = max(plausible, key=_component_score)
    selected_molecule = _parse_component(str(selected["component"]))
    assert selected_molecule is not None
    if selected.get("normalizable_isotope"):
        selected_molecule = _without_isotopes(selected_molecule)
    selected_smiles = Chem.MolToSmiles(selected_molecule, isomericSmiles=True)
    removed = [item["component"] for item in diagnostics if item is not selected]
    return {
        "cleaned_candidate_smiles": selected_smiles,
        "removed_components": json.dumps(removed, ensure_ascii=True, separators=(",", ":")),
        "removed_component_count": str(len(removed)),
        "selection_reason": "largest_plausible_organic_component",
        "component_diagnostics": json.dumps(diagnostics, ensure_ascii=True, separators=(",", ":")),
    }


def _canonical(smiles: str) -> str:
    molecule = _parse_component(smiles)
    return Chem.MolToSmiles(molecule, isomericSmiles=True) if molecule is not None else MISSING


def consensus_smiles(smiles_values: Iterable[str]) -> dict[str, str]:
    """Find normalized graph agreement across multiple crop/model proposals."""
    groups: dict[str, list[str]] = {}
    for value in smiles_values:
        value = str(value or "").strip()
        if not value or value == MISSING:
            continue
        canonical = _canonical(value)
        if canonical == MISSING:
            continue
        groups.setdefault(canonical, []).append(value)
    if not groups:
        return {"consensus_smiles": MISSING, "consensus_count": "0", "variant_count": "0", "consensus_state": "no_valid_graph"}
    selected, values = max(groups.items(), key=lambda item: (len(item[1]), item[0]))
    variant_count = sum(len(value) for value in groups.values())
    return {
        "consensus_smiles": selected if len(values) >= 2 else MISSING,
        "consensus_count": str(len(values)),
        "variant_count": str(variant_count),
        "consensus_state": "graph_consensus_found" if len(values) >= 2 else "single_graph_candidate",
    }


def _normalise_label(value: object) -> str:
    return _LABEL_NORMALIZER.sub("", str(value or "").casefold())


def _reference_index(references: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in references:
        doi = str(row.get("doi", "")).strip().casefold()
        label = _normalise_label(
            row.get("compound_id") or row.get("compound_label") or row.get("source_label", "")
        )
        smiles = str(row.get("smiles", "")).strip()
        if doi and label and smiles:
            key = (doi, label)
            candidate = {key: str(value or "") for key, value in row.items()}
            current = index.get(key)
            current_is_external = current and str(current.get("reference_status", "")).startswith("external_source_")
            candidate_is_external = str(candidate.get("reference_status", "")).startswith("external_source_")
            # The maintained reference table is the stronger source when the
            # same DOI/label is present in both it and the external snapshot.
            if current is None or (current_is_external and not candidate_is_external):
                index[key] = candidate
    return index


def _object_doi(row: Mapping[str, object], doi_by_paper: Mapping[str, object]) -> str:
    return str(row.get("doi") or doi_by_paper.get(str(row.get("paper_id", "")), "") or "").strip()


def classify_reconstruction(row: Mapping[str, object], candidate: Mapping[str, object]) -> dict[str, str]:
    object_type = str(row.get("object_type", ""))
    if object_type in {"shared_scaffold", "replacement_fragment", "linker_fragment", "variable_site"}:
        return {
            "reconstruction_status": "fragment_requires_attachment_review",
            "reconstructed_smiles": MISSING,
            "smiles_source": "attachment_point_notation_only",
        }
    if object_type in {"non_structure_region", "three_d_structure_evidence", "mixed_structure_evidence"}:
        return {
            "reconstruction_status": "not_applicable_or_not_isolated",
            "reconstructed_smiles": MISSING,
            "smiles_source": "excluded_non_structure_region",
        }
    if candidate.get("reference_smiles") and candidate["reference_smiles"] != MISSING:
        reference_smiles = _canonical(str(candidate["reference_smiles"]))
        if str(candidate.get("reference_status", "")) == "external_source_requires_visual_match":
            return {
                "reconstruction_status": "external_source_requires_visual_match",
                "reconstructed_smiles": reference_smiles,
                "smiles_source": str(candidate.get("reference_source_type") or "external_source"),
            }
        if str(candidate.get("reference_status", "")) == "external_source_visual_match_confirmed":
            return {
                "reconstruction_status": "external_source_visual_match_confirmed",
                "reconstructed_smiles": reference_smiles,
                "smiles_source": str(candidate.get("reference_source_type") or "external_source"),
            }
        return {
            "reconstruction_status": "exact_source_confirmed",
            "reconstructed_smiles": reference_smiles,
            "smiles_source": str(candidate.get("reference_source_type") or "exact_reference"),
        }
    cleaned = str(candidate.get("cleaned_candidate_smiles", ""))
    if cleaned and cleaned != MISSING:
        if str(candidate.get("model_review_status", "")) == "model_visual_match_confirmed":
            return {
                "reconstruction_status": "model_visual_match_confirmed",
                "reconstructed_smiles": cleaned,
                "smiles_source": "OCSR_visual_match_reviewed",
            }
        return {
            "reconstruction_status": "model_primary_component_requires_visual_review",
            "reconstructed_smiles": cleaned,
            "smiles_source": "OCSR_primary_component_candidate",
        }
    return {
        "reconstruction_status": "no_reconstructable_graph",
        "reconstructed_smiles": MISSING,
        "smiles_source": "no_valid_graph_candidate",
    }


def _base_row(row: Mapping[str, object], doi: str) -> dict[str, str]:
    return {
        "object_id": str(row.get("object_id", "")),
        "paper_rank": str(row.get("paper_rank", "")),
        "paper_id": str(row.get("paper_id", "")),
        "doi": doi or MISSING,
        "candidate_id": str(row.get("candidate_id", "")),
        "page": str(row.get("page", "")),
        "object_type": str(row.get("object_type", "")),
        "compound_label": str(row.get("compound_label", "")) or MISSING,
        "crop_path": str(row.get("crop_path", "")) or MISSING,
        "attachment_points": str(row.get("attachment_points", "")) or MISSING,
    }


def build_reconstruction_rows(
    objects: Iterable[Mapping[str, object]],
    proposals: Iterable[Mapping[str, object]],
    references: Iterable[Mapping[str, object]],
    *,
    doi_by_paper: Mapping[str, object] | None = None,
    model_visual_reviews: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, str]]:
    proposal_by_id = {str(row.get("object_id", "")): row for row in proposals if row.get("object_id")}
    reference_by_key = _reference_index(references)
    doi_by_paper = doi_by_paper or {}
    if isinstance(model_visual_reviews, Mapping):
        model_review_by_id = {str(key): dict(value) for key, value in model_visual_reviews.items()}
    else:
        model_review_by_id = {
            str(row.get("object_id", "")): row for row in (model_visual_reviews or [])
            if row.get("object_id")
        }
    output: list[dict[str, str]] = []
    for object_row in objects:
        object_id = str(object_row.get("object_id", ""))
        proposal = proposal_by_id.get(object_id, {})
        doi = _object_doi(object_row, doi_by_paper)
        raw_model = str(proposal.get("raw_smiles", "") or "").strip() or MISSING
        model_canonical = str(proposal.get("canonical_smiles", "") or "").strip() or MISSING
        model_primary = str(proposal.get("heuristic_primary_component_smiles", "") or "").strip() or MISSING
        cleaned = choose_primary_component(raw_model)
        label = str(object_row.get("compound_label", ""))
        reference = reference_by_key.get((doi.casefold(), _normalise_label(label)), {})
        candidate = {
            **cleaned,
            "reference_smiles": str(reference.get("smiles", "") or "").strip(),
            "reference_source_type": str(reference.get("source_type", "") or "").strip(),
            "reference_status": str(reference.get("reference_status", "") or "").strip(),
            "model_review_status": str(model_review_by_id.get(object_id, {}).get("review_status", "") or "").strip(),
        }
        decision = classify_reconstruction(object_row, candidate)
        reconstructed = decision["reconstructed_smiles"]
        canonical_reconstructed = _canonical(reconstructed) if reconstructed != MISSING else MISSING
        confidence = {
            "exact_source_confirmed": "high",
            "external_source_visual_match_confirmed": "high_pending_confirmation_layer",
            "external_source_requires_visual_match": "medium_pending_visual_match",
            "model_visual_match_confirmed": "medium_high_visual_review",
            "model_primary_component_requires_visual_review": "low",
        }.get(decision["reconstruction_status"], "not_evaluable")
        steps = (
            "classify image object -> split disconnected OCSR components -> reject metal/isotope/repeated noise -> "
            "select plausible organic graph -> compare exact source when available -> visually verify atom/bond graph"
        )
        if decision["reconstruction_status"] == "fragment_requires_attachment_review":
            steps = "classify fragment object -> preserve R/Site/Linker endpoint -> defer full graph assembly until attachment is confirmed"
        elif decision["reconstruction_status"] == "not_applicable_or_not_isolated":
            steps = "exclude non-2D or mixed object from whole-molecule reconstruction"
        elif decision["reconstruction_status"] in {
            "external_source_requires_visual_match", "external_source_visual_match_confirmed",
        }:
            steps = (
                "classify image object -> parse external SI structure record -> normalize source SMILES -> "
                "compare source graph with PDF image -> keep pending until atom/bond and stereochemistry are visually verified"
            )
        elif decision["reconstruction_status"] == "model_visual_match_confirmed":
            steps = (
                "classify complete image object -> split disconnected OCSR components -> reject noise -> "
                "compare normalized RDKit rendering with the PDF figure -> record model visual match -> retain for final approval"
            )
        values = {
            **_base_row(object_row, doi),
            "raw_model_smiles": raw_model,
            "model_canonical_smiles": model_canonical,
            "model_primary_component_smiles": model_primary,
            "cleaned_candidate_smiles": cleaned["cleaned_candidate_smiles"],
            "removed_components": cleaned["removed_components"],
            "removed_component_count": cleaned["removed_component_count"],
            "selection_reason": cleaned["selection_reason"],
            "component_diagnostics": cleaned["component_diagnostics"],
            "reference_smiles": str(reference.get("smiles", "") or MISSING),
            "reference_source_type": str(reference.get("source_type", "") or MISSING),
            "reference_source_file": str(reference.get("source_file", "") or MISSING),
            "reference_source_locator": str(reference.get("source_locator", "") or MISSING),
            "reconstructed_smiles": reconstructed,
            "reconstructed_canonical_smiles": canonical_reconstructed,
            "reconstruction_status": decision["reconstruction_status"],
            "smiles_source": decision["smiles_source"],
            "reconstruction_confidence": confidence,
            "reconstruction_steps": steps,
            "review_status": "object_requires_human_review",
            "annotation_version": RECONSTRUCTION_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        output.append({field: str(values.get(field, MISSING) or MISSING) for field in RECONSTRUCTION_FIELDS})
    return output


def write_reconstruction_snapshot(
    objects: Iterable[Mapping[str, object]],
    proposals: Iterable[Mapping[str, object]],
    references: Iterable[Mapping[str, object]],
    output_path: Path = DEFAULT_OUTPUT,
    summary_path: Path = DEFAULT_SUMMARY,
    *,
    doi_by_paper: Mapping[str, object] | None = None,
    model_visual_reviews: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    rows = build_reconstruction_rows(
        objects,
        proposals,
        references,
        doi_by_paper=doi_by_paper,
        model_visual_reviews=model_visual_reviews,
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_version": RECONSTRUCTION_VERSION,
        "object_rows": len(rows),
        "candidate_rows": sum(row["object_type"] not in {"non_structure_region", "three_d_structure_evidence"} for row in rows),
        "exact_source_confirmed": sum(row["reconstruction_status"] == "exact_source_confirmed" for row in rows),
        "external_source_visual_match_confirmed": sum(
            row["reconstruction_status"] == "external_source_visual_match_confirmed" for row in rows
        ),
        "external_source_requires_visual_match": sum(
            row["reconstruction_status"] == "external_source_requires_visual_match" for row in rows
        ),
        "model_visual_match_confirmed": sum(
            row["reconstruction_status"] == "model_visual_match_confirmed" for row in rows
        ),
        "model_candidates_needing_review": sum(row["reconstruction_status"] == "model_primary_component_requires_visual_review" for row in rows),
        "fragment_requires_attachment_review": sum(row["reconstruction_status"] == "fragment_requires_attachment_review" for row in rows),
        "not_applicable_or_not_isolated": sum(row["reconstruction_status"] == "not_applicable_or_not_isolated" for row in rows),
        "no_reconstructable_graph": sum(row["reconstruction_status"] == "no_reconstructable_graph" for row in rows),
        "removed_component_count": sum(int(row["removed_component_count"]) for row in rows),
        "status_counts": dict(Counter(row["reconstruction_status"] for row in rows)),
        "output_path": str(Path(output_path).resolve()),
    }
    _atomic_write_csv(output_path, rows)
    _atomic_write_json(summary_path, summary)
    return rows, summary


def _doi_index(path: Path) -> dict[str, str]:
    return {row.get("paper_id", ""): row.get("doi", "") for row in read_csv(path) if row.get("paper_id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--external-references", type=Path, default=DEFAULT_EXTERNAL_REFERENCES)
    parser.add_argument("--model-visual-reviews", type=Path, default=DEFAULT_MODEL_VISUAL_REVIEWS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    references = read_csv(args.references) if args.references.is_file() else []
    if args.external_references.is_file():
        references.extend(read_csv(args.external_references))
    model_visual_reviews = read_csv(args.model_visual_reviews) if args.model_visual_reviews.is_file() else []
    rows, summary = write_reconstruction_snapshot(
        read_csv(args.objects), read_csv(args.proposals) if args.proposals.is_file() else [],
        references,
        args.output, args.summary, doi_by_paper=_doi_index(args.documents) if args.documents.is_file() else {},
        model_visual_reviews=model_visual_reviews,
    )
    print(json.dumps({**summary, "rows_written": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
