"""Build auditable, SMILES-derived structures for the explicit path pilot."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPLICIT_PATHS = PROJECT_ROOT / "06_text_confirmed_paths" / "explicit_text_confirmed_paths.csv"
REFERENCE_PATH = PROJECT_ROOT / "09_structure_confirmation" / "compound_smiles_reference.csv"
OUTPUT_DIR = PROJECT_ROOT / "09_structure_confirmation"
GENERATED_STRUCTURES_DIR = OUTPUT_DIR / "generated_structures"
OUTPUT_PATH = OUTPUT_DIR / "confirmed_path_structures.csv"

OUTPUT_FIELDS = (
    "visual_review_id",
    "doi",
    "page",
    "page_references",
    "parent_compound",
    "derived_compound",
    "reported_from_group",
    "reported_to_group",
    "atom_level_change",
    "reported_activity_mentions",
    "evidence_text",
    "parent_smiles",
    "derived_smiles",
    "parent_canonical_smiles",
    "derived_canonical_smiles",
    "parent_rdkit_status",
    "derived_rdkit_status",
    "structure_source",
    "parent_source_locator",
    "derived_source_locator",
    "structure_image_parent",
    "structure_image_derived",
    "path_panel_image",
    "confirmation_status",
    "path_status",
    "review_status",
    "notes",
)

CHANGE_NOTES = {
    "VIS-0001": "phenyl ring -> thiophene",
    "VIS-0002": "phenyl ring -> pyridine",
    "VIS-0003": "phenyl ring -> pyridine",
    "VIS-0004": "meta-methyl -> chlorine",
    "VIS-0005": "rac-Ala -> glycine",
    "VIS-0006": "carboxamide -> methyl ester",
    "VIS-0007": "ethyl substituent at ammonium nitrogen -> methyl",
    "VIS-0008": "carboxyl group -> cyano",
    "VIS-0009": "methylimidazole -> isomeric pyrazole",
    "VIS-0010": "11H-indolo[3,2-c]isoquinoline -> 6,11-dihydro-5H-indolo[3,2-c]isoquinolin-5-one",
    "VIS-0011": "nicotinamide core -> pyrazinamide core",
    "VIS-0012": "benzothiazole H -> 5-fluoro substitution",
    "VIS-0013": "phenyl H -> meta-fluoro substitution",
    "VIS-0014": "phenoxy side chain -> 6-fluoroindazolyl side chain",
    "VIS-0015": "R3 substituent -> -CH2COOH",
    "VIS-0016": "N-capping benzyl -> methyl",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_smiles_reference(
    source: Path | Iterable[Mapping[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Load SI-derived compound SMILES keyed by DOI and compound label."""
    rows = _read_csv(source) if isinstance(source, Path) else [dict(row) for row in source]
    reference: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        doi = str(row.get("doi", "")).strip()
        compound_id = str(row.get("compound_id", "")).strip()
        smiles = str(row.get("smiles", "")).strip()
        if not doi or not compound_id or not smiles:
            raise ValueError("SMILES reference rows require doi, compound_id, and smiles")
        key = (doi, compound_id)
        if key in reference:
            raise ValueError(f"duplicate compound reference: {doi} / {compound_id}")
        reference[key] = {
            "doi": doi,
            "compound_id": compound_id,
            "smiles": smiles,
            "source_type": str(row.get("source_type", "")).strip(),
            "source_file": str(row.get("source_file", "")).strip(),
            "source_locator": str(row.get("source_locator", "")).strip(),
        }
    return reference


def canonicalize_smiles(smiles: str) -> tuple[str, str, str]:
    """Return RDKit status, canonical SMILES, and a human-readable note."""
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return "invalid", "", "RDKit could not parse the supplied SMILES"
    return "valid", Chem.MolToSmiles(molecule, canonical=True), ""


def build_confirmation_rows(
    paths: Iterable[Mapping[str, str]],
    reference: Mapping[tuple[str, str], Mapping[str, str]],
) -> list[dict[str, str]]:
    """Join explicit text paths to sourced SMILES without inferring structures."""
    records: list[dict[str, str]] = []
    for path in paths:
        visual_review_id = str(path.get("visual_review_id", "")).strip()
        doi = str(path.get("doi", "")).strip()
        parent_id = str(path.get("parent_compound", "")).strip()
        derived_id = str(path.get("derived_compound", "")).strip()
        parent = reference.get((doi, parent_id), {})
        derived = reference.get((doi, derived_id), {})
        parent_smiles = str(parent.get("smiles", ""))
        derived_smiles = str(derived.get("smiles", ""))
        parent_status, parent_canonical, parent_note = canonicalize_smiles(parent_smiles) if parent_smiles else ("missing", "", "No sourced parent SMILES")
        derived_status, derived_canonical, derived_note = canonicalize_smiles(derived_smiles) if derived_smiles else ("missing", "", "No sourced derived SMILES")
        complete = parent_status == "valid" and derived_status == "valid"
        notes = "; ".join(note for note in (parent_note, derived_note) if note)
        records.append(
            {
                "visual_review_id": visual_review_id,
                "doi": doi,
                "page": str(path.get("page", "")),
                "page_references": str(path.get("page_references", "")),
                "parent_compound": parent_id,
                "derived_compound": derived_id,
                "reported_from_group": str(path.get("reported_from_group", "")),
                "reported_to_group": str(path.get("reported_to_group", "")),
                "atom_level_change": CHANGE_NOTES.get(visual_review_id, ""),
                "reported_activity_mentions": str(path.get("reported_activity_mentions", "")),
                "evidence_text": str(path.get("evidence_text", "")),
                "parent_smiles": parent_smiles,
                "derived_smiles": derived_smiles,
                "parent_canonical_smiles": parent_canonical,
                "derived_canonical_smiles": derived_canonical,
                "parent_rdkit_status": parent_status,
                "derived_rdkit_status": derived_status,
                "structure_source": "supporting_information_csv" if complete else "needs_manual_source_review",
                "parent_source_locator": str(parent.get("source_locator", "")),
                "derived_source_locator": str(derived.get("source_locator", "")),
                "structure_image_parent": "",
                "structure_image_derived": "",
                "path_panel_image": "",
                "confirmation_status": "confirmed_by_si_smiles" if complete else "needs_manual_structure_confirmation",
                "path_status": "structure_confirmed_pending_human_review" if complete else "needs_manual_structure_confirmation",
                "review_status": "unreviewed",
                "notes": notes,
            }
        )
    return records


def render_structure_images(rows: Iterable[Mapping[str, str]], output_dir: Path) -> list[dict[str, str]]:
    """Render all valid endpoint molecules and a two-panel path image via RDKit."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, str]] = []
    for row in rows:
        item = {key: str(value) for key, value in row.items()}
        if row.get("parent_rdkit_status") != "valid" or row.get("derived_rdkit_status") != "valid":
            rendered.append(item)
            continue
        parent = Chem.MolFromSmiles(str(row["parent_smiles"]))
        derived = Chem.MolFromSmiles(str(row["derived_smiles"]))
        if parent is None or derived is None:
            rendered.append(item)
            continue
        visual_review_id = str(row["visual_review_id"])
        parent_path = output_dir / f"{visual_review_id}_parent.png"
        derived_path = output_dir / f"{visual_review_id}_derived.png"
        panel_path = output_dir / f"{visual_review_id}_path.png"
        Draw.MolToFile(parent, str(parent_path), size=(720, 480), legend=f"{row['parent_compound']} / parent")
        Draw.MolToFile(derived, str(derived_path), size=(720, 480), legend=f"{row['derived_compound']} / derived")
        panel = Draw.MolsToGridImage(
            [parent, derived],
            molsPerRow=2,
            subImgSize=(520, 380),
            legends=[f"{row['parent_compound']} / parent", f"{row['derived_compound']} / derived"],
            useSVG=False,
        )
        panel.save(panel_path)
        item["structure_image_parent"] = str(parent_path)
        item["structure_image_derived"] = str(derived_path)
        item["path_panel_image"] = str(panel_path)
        rendered.append(item)
    return rendered


def _relative_image_path(value: str, output_dir: Path) -> str:
    if not value:
        return ""
    return str(Path(value).resolve().relative_to(output_dir.resolve().parent)).replace("\\", "/")


def write_confirmation_csv(rows: Iterable[Mapping[str, str]], path: Path, output_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            output = {field: str(row.get(field, "")) for field in OUTPUT_FIELDS}
            for field in ("structure_image_parent", "structure_image_derived", "path_panel_image"):
                output[field] = _relative_image_path(output[field], output_dir)
            writer.writerow(output)


def build_dataset(
    *,
    explicit_paths: Path = EXPLICIT_PATHS,
    reference_path: Path = REFERENCE_PATH,
    output_path: Path = OUTPUT_PATH,
    image_dir: Path = GENERATED_STRUCTURES_DIR,
) -> list[dict[str, str]]:
    paths = _read_csv(explicit_paths)
    reference = load_smiles_reference(reference_path)
    rows = build_confirmation_rows(paths, reference)
    rendered = render_structure_images(rows, image_dir)
    write_confirmation_csv(rendered, output_path, image_dir)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit-paths", type=Path, default=EXPLICIT_PATHS)
    parser.add_argument("--reference", type=Path, default=REFERENCE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--image-dir", type=Path, default=GENERATED_STRUCTURES_DIR)
    args = parser.parse_args()
    rows = build_dataset(
        explicit_paths=args.explicit_paths,
        reference_path=args.reference,
        output_path=args.output,
        image_dir=args.image_dir,
    )
    complete = sum(row["confirmation_status"] == "confirmed_by_si_smiles" for row in rows)
    print(f"wrote {len(rows)} path records; {complete} have two RDKit-valid SI SMILES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
