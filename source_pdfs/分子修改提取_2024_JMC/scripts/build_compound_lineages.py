#!/usr/bin/env python3
"""Build evidence-backed medicinal-chemistry optimization lineages.

Image-object containment is deliberately excluded from this layer. A lineage
edge records a direct compound-to-compound optimization asserted by article
text/figures or retained as explicitly unresolved for later review.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping

from rdkit import Chem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTO_FILL_ROOT = PROJECT_ROOT / "09_paper_review" / "auto_fill"
DEFAULT_EVIDENCE = PROJECT_ROOT / "03_sar_candidates" / "full_evidence_candidates.csv"
DEFAULT_RECONSTRUCTIONS = AUTO_FILL_ROOT / "first_page_molecule_reconstructions.csv"
DEFAULT_SOURCE_MANIFEST = AUTO_FILL_ROOT / "external_sources" / "acs_si_source_manifest.csv"
DEFAULT_ENTITIES = AUTO_FILL_ROOT / "compound_entities.csv"
DEFAULT_EDGES = AUTO_FILL_ROOT / "compound_lineage_edges.csv"
DEFAULT_LINEAGE_EVIDENCE = AUTO_FILL_ROOT / "compound_lineage_evidence.csv"
DEFAULT_ACTIVITIES = AUTO_FILL_ROOT / "compound_activities.csv"
DEFAULT_SUMMARY = AUTO_FILL_ROOT / "compound_lineage_summary.json"
DEFAULT_ANNOTATIONS = AUTO_FILL_ROOT / "lineage_annotations"
DEFAULT_CONFIRMED_PATHS = PROJECT_ROOT / "09_structure_confirmation" / "confirmed_path_structures.csv"
DEFAULT_CONFIRMED_STRUCTURES = AUTO_FILL_ROOT / "confirmed_compound_structures.csv"
DEFAULT_DOCUMENT_INDEX = PROJECT_ROOT / "02_text_extraction" / "full_document_text_index.csv"
MISSING = "--"
ANNOTATION_VERSION = "compound_lineages_v1_2026-09-08"

CONFIRMED_STRUCTURE_REVIEW_STATES = frozenset({
    "structure_confirmed",
})

ENTITY_FIELDS = (
    "compound_entity_id", "paper_id", "doi", "lineage_ids", "display_label",
    "normalized_label", "preferred_name", "entity_origin", "entity_role",
    "compound_object_ids", "canonical_smiles", "structure_status",
    "structure_source_type", "structure_source_file", "structure_source_locator",
    "structure_review_status", "review_status", "annotation_version",
)

EDGE_FIELDS = (
    "lineage_edge_id", "lineage_id", "paper_id", "doi",
    "root_template_entity_id", "root_template_label", "parent_entity_id",
    "parent_label", "derived_entity_id", "derived_label", "parent_role",
    "iteration_depth", "modification_site", "from_group", "to_group",
    "relation_type", "relation_status", "relation_confidence", "evidence_ids",
    "pair_eligible", "review_status", "review_note", "annotation_version",
)

EVIDENCE_FIELDS = (
    "lineage_evidence_id", "lineage_edge_id", "lineage_id", "paper_id", "doi",
    "evidence_type", "page", "source_locator", "evidence_text",
    "source_object_ids", "evidence_strength", "review_status", "annotation_version",
)

ACTIVITY_FIELDS = (
    "activity_id", "paper_id", "doi", "compound_entity_id", "compound_label",
    "target", "assay", "metric", "value", "unit", "qualifier", "comparator",
    "page", "source_locator", "evidence_text", "review_status", "annotation_version",
)


def _edge(
    lineage: str, root: str, parent: str, derived: str, page: int,
    evidence_text: str, *, locator: str, modification_site: str = MISSING,
    from_group: str = MISSING, to_group: str = MISSING,
    relation_type: str = "direct_optimization", relation_status: str = "text_explicit",
    confidence: str = "high",
) -> dict[str, object]:
    return {
        "lineage": lineage, "root": root, "parent": parent, "derived": derived,
        "page": page, "evidence_text": evidence_text, "locator": locator,
        "modification_site": modification_site, "from_group": from_group,
        "to_group": to_group, "relation_type": relation_type,
        "relation_status": relation_status, "relation_confidence": confidence,
    }


GLP1_PAPER_ID = "7a695794fc7b"
GLP1_DOI = "10.1021/acs.jmedchem.4c02616"

GLP1_LINEAGE_SPECS = [
    _edge(
        "01", "1", "1", "3", 2,
        "Replacing an oxygen atom with a selenium atom in danuglipron yielded compound 3.",
        locator="Figure 2A", modification_site="danuglipron ether linkage",
        from_group="oxygen", to_group="selenium", relation_type="bioisosteric_replacement",
    ),
    _edge(
        "01", "1", "1", "4", 2,
        "Compounds 3 and 4 were designed using a Se-O bioisostere strategy based on the danuglipron scaffold.",
        locator="Figure 2A", modification_site="danuglipron ether linkage",
        from_group="oxygen", to_group="selenoxide", relation_type="bioisosteric_replacement",
    ),
    _edge(
        "01", "1", "3", "5", 4,
        "A series of Se-containing derivatives based on compound 3 were synthesized. Substituting the piperidine ring with piperazine produced compound 5.",
        locator="Figure 3", modification_site="Site 1", from_group="piperidine",
        to_group="piperazine", relation_type="ring_replacement",
    ),
    _edge(
        "01", "1", "3", "6", 4,
        "Amino acid substitutions for the piperidine ring were also explored. Unfortunately, compounds 6 and 7 nearly abolished GLP-1R agonistic activity.",
        locator="Figure 3", modification_site="Site 1", from_group="piperidine",
        to_group="amino acid linker", relation_type="linker_replacement",
    ),
    _edge(
        "01", "1", "3", "7", 4,
        "Amino acid substitutions for the piperidine ring were also explored. Unfortunately, compounds 6 and 7 nearly abolished GLP-1R agonistic activity.",
        locator="Figure 3", modification_site="Site 1", from_group="piperidine",
        to_group="amino acid linker", relation_type="linker_replacement",
    ),
]

for label, replacement in (("8", "sulfonylurea"), ("9", "hydroxamic acid"), ("10", "acylsulfonamide")):
    GLP1_LINEAGE_SPECS.append(_edge(
        "01", "1", "3", label, 4,
        "Further optimization of compound 3 involved modifications to the benzimidazole ring, including bioisostere replacements of the carboxyl group and substituents on the benzimidazole nitrogen. "
        "As shown in Table 1, bioisostere replacements of the carboxyl group, such as sulfonylurea (8), hydroxamic acid (9), and acylsulfonamide (10), maintained full GLP-1R agonistic effects but showed a more than 100-fold reduction in potency compared to compound 3.",
        locator="Table 1", modification_site="Site 2", from_group="carboxylic acid",
        to_group=replacement, relation_type="bioisosteric_replacement",
    ))

for label, replacement in (
    ("11", "methyl ether ethyl"), ("12", "oxacyclopentane"),
    ("13", "methylene-linked imidazole"), ("14", "methylene-linked thiazole"),
):
    GLP1_LINEAGE_SPECS.append(_edge(
        "01", "1", "3", label, 4,
        "Further optimization of compound 3 involved modifications to the benzimidazole ring, including bioisostere replacements of the carboxyl group and substituents on the benzimidazole nitrogen. "
        "Subsequently, a series of compounds with various substitutions on the benzimidazole nitrogen were synthesized, all of which maintained full GLP-1R agonistic effects. The methyl ether ethyl-substituted (11) and oxacyclopentane-substituted (12) compounds exhibited pEC50 values of -1.04 and -1.23, respectively. Notably, methylene-linked imidazole (13) and thiazole (14)-substituted compounds demonstrated activities comparable to those of compound 3.",
        locator="Table 1", modification_site="Site 2 / benzimidazole nitrogen",
        from_group="oxetanyl substituent", to_group=replacement,
        relation_type="substituent_replacement",
    ))

for label, from_group, to_group, evidence_text in (
    ("15", "cyano and fluorine", "hydrogen and hydrogen", "To enhance the potency of GLP-1R agonists, we optimized the benzene ring by substituting the cyano and fluorine groups with alternative functional groups. As shown in Table 2, replacing both the cyano and fluorine groups with hydrogen atoms produced compound 15, which has a 31-fold decrease in activity."),
    ("16", "cyano", "hydrogen", "The SAR of the cyano and fluorine groups was investigated independently. Replacing the cyano group with various substituents yielded hydrogen-containing compound 16, chlorine-containing compound 17, and trifluoromethyl-containing compound 18."),
    ("17", "cyano", "chlorine", "The SAR of the cyano and fluorine groups was investigated independently. Replacing the cyano group with various substituents yielded hydrogen-containing compound 16, chlorine-containing compound 17, and trifluoromethyl-containing compound 18."),
    ("18", "cyano", "trifluoromethyl", "The SAR of the cyano and fluorine groups was investigated independently. Replacing the cyano group with various substituents yielded hydrogen-containing compound 16, chlorine-containing compound 17, and trifluoromethyl-containing compound 18."),
    ("19", "fluorine", "hydrogen", "In parallel studies, removing the fluorine group while retaining either the cyano group (19) or the chlorine group (20) resulted in a 2-fold and 4-fold decrease in activity, respectively, compared to compound 3."),
    ("20", "fluorine", "hydrogen; cyano changed to chlorine", "In parallel studies, removing the fluorine group while retaining either the cyano group (19) or the chlorine group (20) resulted in a 2-fold and 4-fold decrease in activity, respectively, compared to compound 3."),
    ("21", "fluorine", "methoxy", "Given the available space around the fluorine substitution site, a methoxy group was introduced, yielding compounds 21 and 22."),
    ("22", "fluorine; cyano", "methoxy; trifluoromethyl", "Given the available space around the fluorine substitution site, a methoxy group was introduced, yielding compounds 21 and 22."),
):
    GLP1_LINEAGE_SPECS.append(_edge(
        "01", "1", "3", label, 4,
        evidence_text,
        locator="Table 2", modification_site="Site 3 / phenyl substituents",
        from_group=from_group, to_group=to_group, relation_type="substituent_replacement",
    ))

GLP1_LINEAGE_SPECS.extend([
    _edge(
        "02", "2n", "2n", "23", 5,
        "A Se-O bioisostere strategy was applied to compound 2n, leading to compound 23.",
        locator="Table 3", modification_site="aryl ether linkage", from_group="oxygen",
        to_group="selenium", relation_type="bioisosteric_replacement",
    ),
    _edge(
        "02", "2n", "23", "24", 5,
        "Based on compound 23, substitution of trifluoromethyl with a cyano group yielded compound 24.",
        locator="Table 3", modification_site="4-position of benzene ring",
        from_group="trifluoromethyl", to_group="cyano", relation_type="substituent_replacement",
    ),
    _edge(
        "02", "2n", MISSING, "25", 5,
        "Fluorine substitution at the 2-position was explored to design compound 25 with a cyano group.",
        locator="Table 3", modification_site="2-position of benzene ring",
        from_group="methoxy", to_group="fluorine", relation_status="unresolved",
        confidence="unresolved_direct_parent",
    ),
    _edge(
        "02", "2n", MISSING, "26", 5,
        "Fluorine substitution at the 2-position was explored to design compound 26 with a trifluoromethyl group.",
        locator="Table 3", modification_site="2-position of benzene ring",
        from_group="methoxy", to_group="fluorine", relation_status="unresolved",
        confidence="unresolved_direct_parent",
    ),
    _edge(
        "02", "2n", MISSING, "27", 5,
        "Fluorine substitution at the 2-position was explored to design compound 27 with chlorine at the 4-position.",
        locator="Table 3", modification_site="2- and 4-positions of benzene ring",
        from_group="methoxy; unresolved 4-position group", to_group="fluorine; chlorine",
        relation_status="unresolved", confidence="unresolved_direct_parent",
    ),
])

LINEAGE_SPECS = {GLP1_PAPER_ID: GLP1_LINEAGE_SPECS}
PAPER_DOIS = {GLP1_PAPER_ID: GLP1_DOI}
PREFERRED_NAMES = {(GLP1_PAPER_ID, "1"): "danuglipron"}
ORIGINS = {
    (GLP1_PAPER_ID, "1"): "external_reference",
    (GLP1_PAPER_ID, "2n"): "prior_art",
}
BUILTIN_EXTERNAL_STRUCTURES = {
    GLP1_PAPER_ID: [
        {
            "compound_label": "1",
            "canonical_smiles": "C1CO[C@@H]1CN2C3=C(C=CC(=C3)C(=O)O)N=C2CN4CCC(CC4)C5=NC(=CC=C5)OCC6=C(C=C(C=C6)C#N)F",
            "structure_status": "source_confirmed",
            "structure_source_type": "pubchem_pug",
            "structure_source_file": "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/danuglipron/property/CanonicalSMILES,IsomericSMILES,IUPACName/JSON",
            "structure_source_locator": "CID=134611040",
            "structure_review_status": "external_source_confirmed",
        },
    ],
}


def read_csv(path: Path, *, encoding: str = "utf-8-sig", delimiter: str = ",") -> list[dict[str, str]]:
    with Path(path).open(encoding=encoding, errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def load_lineage_annotations(path: Path = DEFAULT_ANNOTATIONS) -> dict[str, dict[str, object]]:
    """Load and validate per-Paper lineage annotations without mutating source data."""
    annotations: dict[str, dict[str, object]] = {}
    if not Path(path).is_dir():
        return annotations
    for annotation_path in sorted(Path(path).glob("*.json")):
        with annotation_path.open(encoding="utf-8") as handle:
            annotation = json.load(handle)
        if not isinstance(annotation, dict):
            raise ValueError(f"annotation must be an object: {annotation_path}")
        paper_id = str(annotation.get("paper_id", "")).strip()
        if not paper_id:
            raise ValueError(f"annotation is missing paper_id: {annotation_path}")
        if paper_id in annotations:
            raise ValueError(f"duplicate lineage annotation for {paper_id}")
        status = str(annotation.get("annotation_status", "evidence_annotated"))
        if status not in {"evidence_annotated", "no_supported_lineage", "needs_manual_review"}:
            raise ValueError(f"unsupported annotation_status for {paper_id}: {status}")
        edges = annotation.get("edges", [])
        if not isinstance(edges, list):
            raise ValueError(f"edges must be a list for {paper_id}")
        normalized_edges: list[dict[str, object]] = []
        for index, raw_edge in enumerate(edges, 1):
            if not isinstance(raw_edge, dict):
                raise ValueError(f"edge {index} must be an object for {paper_id}")
            edge = {
                "lineage": str(raw_edge.get("lineage") or "01"),
                "root": str(raw_edge.get("root") or MISSING),
                "parent": str(raw_edge.get("parent") or MISSING),
                "derived": str(raw_edge.get("derived") or MISSING),
                "page": int(raw_edge.get("page") or 0),
                "evidence_text": str(raw_edge.get("evidence_text") or MISSING),
                "locator": str(raw_edge.get("locator") or MISSING),
                "modification_site": str(raw_edge.get("modification_site") or MISSING),
                "from_group": str(raw_edge.get("from_group") or MISSING),
                "to_group": str(raw_edge.get("to_group") or MISSING),
                "relation_type": str(raw_edge.get("relation_type") or "direct_optimization"),
                "relation_status": str(raw_edge.get("relation_status") or "unresolved"),
                "relation_confidence": str(raw_edge.get("relation_confidence") or "unresolved_direct_parent"),
            }
            if edge["root"] == MISSING or edge["derived"] == MISSING:
                raise ValueError(f"edge {index} is missing root or derived for {paper_id}")
            if edge["relation_status"] not in {"text_explicit", "figure_explicit", "human_confirmed", "unresolved"}:
                raise ValueError(f"unsupported relation_status for {paper_id}: {edge['relation_status']}")
            if edge["relation_status"] in {"text_explicit", "figure_explicit", "human_confirmed"}:
                if edge["parent"] == MISSING:
                    raise ValueError(f"explicit edge requires a direct parent for {paper_id}")
                if edge["evidence_text"] == MISSING or not _compound_label_is_mentioned(
                    edge["derived"], str(edge["evidence_text"])
                ):
                    raise ValueError(f"explicit edge evidence must mention derived label for {paper_id}")
            normalized_edges.append(edge)
        preferred_names = annotation.get("preferred_names", {})
        origins = annotation.get("origins", {})
        activity_columns = annotation.get("activity_columns", [])
        if not isinstance(preferred_names, dict) or not isinstance(origins, dict) or not isinstance(activity_columns, list):
            raise ValueError(f"preferred_names, origins, and activity_columns have invalid types for {paper_id}")
        annotations[paper_id] = {
            **annotation,
            "paper_id": paper_id,
            "annotation_status": status,
            "edges": normalized_edges,
            "preferred_names": {normalize_label(key): str(value) for key, value in preferred_names.items()},
            "origins": {normalize_label(key): str(value) for key, value in origins.items()},
            "activity_columns": activity_columns,
        }
    return annotations


def load_confirmed_path_data(
    path: Path,
    paper_by_doi: Mapping[str, str],
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    """Adapt the existing SI-confirmed path table to the generic lineage schema."""
    if not Path(path).is_file():
        return {}, []
    annotations: dict[str, dict[str, object]] = {}
    structures: list[dict[str, str]] = []
    for row in read_csv(path):
        doi = str(row.get("doi") or "").strip()
        paper_id = paper_by_doi.get(doi.casefold())
        parent = str(row.get("parent_compound") or MISSING).strip()
        derived = str(row.get("derived_compound") or MISSING).strip()
        evidence_text = str(row.get("evidence_text") or MISSING).strip()
        if not paper_id or parent == MISSING or derived == MISSING or evidence_text == MISSING:
            continue
        if not _compound_label_is_mentioned(derived, evidence_text):
            continue
        annotation = annotations.setdefault(paper_id, {
            "paper_id": paper_id,
            "doi": doi,
            "title": "--",
            "annotation_status": "evidence_annotated",
            "review_note": "Imported from SI-confirmed text paths; root defaults to the explicit direct parent.",
            "preferred_names": {},
            "origins": {},
            "activity_columns": [],
            "edges": [],
        })
        annotation["edges"].append({
            "lineage": f"{len(annotations[paper_id]['edges']) + 1:02d}",
            "root": parent,
            "parent": parent,
            "derived": derived,
            "page": int(row.get("page") or 0),
            "evidence_text": evidence_text,
            "locator": str(row.get("page_references") or MISSING),
            "modification_site": str(row.get("reported_from_group") or MISSING),
            "from_group": str(row.get("reported_from_group") or MISSING),
            "to_group": str(row.get("reported_to_group") or MISSING),
            "relation_type": "substituent_replacement",
            "relation_status": "text_explicit",
            "relation_confidence": "high",
        })
        for label, smiles, locator in (
            (parent, row.get("parent_canonical_smiles") or row.get("parent_smiles"), "parent"),
            (derived, row.get("derived_canonical_smiles") or row.get("derived_smiles"), "derived"),
        ):
            if str(smiles or "").strip() in {"", MISSING}:
                continue
            structures.append({
                "paper_id": paper_id,
                "compound_label": normalize_label(label),
                "canonical_smiles": str(smiles).strip(),
                "structure_status": "source_confirmed",
                "structure_source_type": "confirmed_path_structures",
                "structure_source_file": str(path),
                "structure_source_locator": f"{row.get('visual_review_id', '--')}:{locator}",
                "structure_review_status": str(row.get("confirmation_status") or "source_confirmed"),
            })
    return annotations, structures


def _atomic_write_csv(path: Path, fields: tuple[str, ...], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
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


def normalize_label(value: object) -> str:
    label = str(value or "").strip().casefold()
    label = label.replace("–", "-").replace("—", "-")
    label = re.sub(r"^(?:compound|compd?|cmp)\s*", "", label)
    label = re.sub(r"^no\.?\s*", "", label)
    stereo = re.match(r"^\(([rs])\)-(.+)$", label)
    if stereo:
        label = f"{stereo.group(1)}-{stereo.group(2)}"
    racemate = re.match(r"^\((?:\u00b1|\u00a1(?:\u00c0|\u00e0)|\ufffd{1,2})\)-(.+)$", label)
    if racemate:
        label = racemate.group(1)
    label = re.split(r"\s*[\(\[]", label, maxsplit=1)[0]
    prime_suffix = re.search(r"[′’']+$", label)
    if prime_suffix:
        label = label[:prime_suffix.start()] + "prime" * len(prime_suffix.group())
    numeric_label = re.sub(r"\s+", "", label)
    if re.fullmatch(r"\d+(?:[-./]\d+)+", numeric_label):
        return numeric_label
    return re.sub(r"[^a-z0-9]+", "", label) or MISSING


def load_confirmed_structures(
    path: Path = DEFAULT_CONFIRMED_STRUCTURES,
) -> list[dict[str, str]]:
    """Load only final Paper-local structures from the authoritative table."""
    source_path = Path(path)
    if not source_path.is_file():
        return []
    output_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row_number, row in enumerate(read_csv(source_path), start=2):
        if str(row.get("confirmation_status") or "") != "structure_confirmed":
            continue
        paper_id = str(row.get("paper_id") or "").strip()
        label = normalize_label(
            row.get("normalized_label") or row.get("compound_label")
        )
        smiles = _canonical_complete_smiles(
            row.get("canonical_isomeric_smiles") or row.get("canonical_smiles")
        )
        if not paper_id or label == MISSING:
            raise ValueError(
                f"confirmed structure row {row_number} has no Paper-local label"
            )
        provenance_fields = (
            "accepted_work_row_id", "structure_source_file",
            "structure_source_locator",
        )
        if any(
            str(row.get(field) or "").strip() in {"", MISSING}
            for field in provenance_fields
        ):
            raise ValueError(
                f"confirmed structure row {row_number} has incomplete provenance"
            )
        if str(row.get("compound_entity_id") or "").strip() != entity_id(
            paper_id, label,
        ):
            raise ValueError(
                f"confirmed structure row {row_number} has a mismatched entity key"
            )
        if smiles == MISSING or "." in smiles:
            raise ValueError(
                f"confirmed structure row {row_number} has no complete single-component structure"
            )
        normalized_row = dict(row)
        normalized_row.update({
            "paper_id": paper_id,
            "compound_label": str(row.get("compound_label") or label),
            "normalized_label": label,
            "canonical_isomeric_smiles": smiles,
            "confirmation_status": "structure_confirmed",
            "structure_review_status": "structure_confirmed",
        })
        key = (paper_id, label)
        previous = output_by_key.get(key)
        if previous is not None and (
            previous["canonical_isomeric_smiles"] != smiles
        ):
            raise ValueError(
                f"conflicting confirmed structures for {paper_id}/{label}"
            )
        output_by_key[key] = normalized_row
    return [output_by_key[key] for key in sorted(output_by_key)]


def _compound_label_is_mentioned(label: object, text: str) -> bool:
    """Match an exact label or an explicit compound-label range."""
    raw_label = str(label or "").strip()
    if not raw_label or raw_label == MISSING:
        return False
    candidates = [raw_label]
    if "(" in raw_label:
        primary_label = raw_label.split("(", 1)[0].strip()
        if primary_label and primary_label not in candidates:
            candidates.append(primary_label)
    for candidate in candidates:
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        ):
            return True

        numeric = re.fullmatch(r"\d+", candidate)
        if numeric:
            target = int(candidate)
            for start, end in re.findall(r"(?<![A-Za-z0-9])(\d+)\s*[-–]\s*(\d+)(?![A-Za-z0-9])", text):
                if int(start) <= target <= int(end):
                    return True
            continue

        numbered = re.fullmatch(r"([A-Za-z]+)(\d+)", candidate)
        if numbered:
            prefix, target_text = numbered.groups()
            target = int(target_text)
            range_pattern = rf"(?<![A-Za-z0-9]){re.escape(prefix)}(\d+)\s*[-–]\s*{re.escape(prefix)}(\d+)(?![A-Za-z0-9])"
            for start, end in re.findall(range_pattern, text, flags=re.IGNORECASE):
                if int(start) <= target <= int(end):
                    return True
            continue

        lettered = re.fullmatch(r"([A-Za-z]*\d+)([A-Za-z])", candidate)
        if lettered:
            stem, target_text = lettered.groups()
            target = ord(target_text.casefold())
            range_patterns = (
                rf"(?<![A-Za-z0-9]){re.escape(stem)}([A-Za-z])\s*[-–]\s*{re.escape(stem)}([A-Za-z])(?![A-Za-z0-9])",
                rf"(?<![A-Za-z0-9]){re.escape(stem)}([A-Za-z])\s*[-–]\s*([A-Za-z])(?![A-Za-z0-9])",
            )
            for range_pattern in range_patterns:
                for start, end in re.findall(range_pattern, text, flags=re.IGNORECASE):
                    if ord(start.casefold()) <= target <= ord(end.casefold()):
                        return True
    return False


def entity_id(paper_id: str, label: object) -> str:
    return f"CMP-{paper_id}-{normalize_label(label)}"


def _canonical_complete_smiles(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate == MISSING:
        return MISSING
    molecule = Chem.MolFromSmiles(candidate)
    if (
        molecule is None
        or len(Chem.GetMolFrags(molecule)) != 1
        or any(
            atom.GetAtomicNum() == 0 or atom.GetNumRadicalElectrons()
            for atom in molecule.GetAtoms()
        )
    ):
        return MISSING
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def _row_structure_status(row: Mapping[str, object]) -> str:
    confirmation_status = str(row.get("confirmation_status") or "")
    if confirmation_status == "structure_confirmed":
        return confirmation_status
    return str(
        row.get("structure_status")
        or row.get("reconstruction_status")
        or row.get("structure_review_status")
        or ""
    )


def _row_structure_smiles(row: Mapping[str, object]) -> str:
    return _canonical_complete_smiles(
        row.get("canonical_isomeric_smiles")
        or row.get("canonical_smiles")
        or row.get("reconstructed_canonical_smiles")
        or row.get("reconstructed_smiles")
    )


def _structure_priority(row: Mapping[str, object]) -> tuple[int, int]:
    status = _row_structure_status(row)
    priorities = {
        "structure_confirmed": 100,
        "source_confirmed": 60,
        "exact_source_confirmed": 60,
        "external_source_confirmed": 55,
        "external_source_visual_match_confirmed": 50,
        "model_visual_match_confirmed": 40,
    }
    smiles = _row_structure_smiles(row)
    return priorities.get(status, 0), 1 if smiles != MISSING else 0


def _structure_index(structures: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], dict[str, str]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in structures:
        key = (
            str(row.get("paper_id", "")),
            normalize_label(
                row.get("normalized_label") or row.get("compound_label", "")
            ),
        )
        if key[0] and key[1] != MISSING:
            grouped[key].append(row)
    output: dict[tuple[str, str], dict[str, str]] = {}
    for key, rows in grouped.items():
        ranked_rows = sorted(rows, key=_structure_priority, reverse=True)
        row = ranked_rows[0]
        smiles = _row_structure_smiles(row)
        status = _row_structure_status(row) or MISSING
        if _structure_priority(row)[0] == 0:
            smiles = MISSING
        object_ids = list(dict.fromkeys(
            object_id
            for source_row in rows
            for object_id in str(source_row.get("object_id") or "").split("|")
            if object_id and object_id != MISSING
        ))
        preferred_name = next((
            str(source_row.get("preferred_name"))
            for source_row in ranked_rows
            if source_row.get("preferred_name")
            and str(source_row.get("preferred_name")) != MISSING
        ), MISSING)
        output[key] = {
            "canonical_smiles": smiles,
            "structure_status": "complete_structure_resolved" if smiles != MISSING else "missing_or_fragment_only",
            "structure_source_type": str(row.get("structure_source_type") or row.get("smiles_source") or MISSING),
            "structure_source_file": str(row.get("structure_source_file") or row.get("reference_source_file") or MISSING),
            "structure_source_locator": str(row.get("structure_source_locator") or row.get("reference_source_locator") or MISSING),
            "structure_review_status": status,
            "compound_object_ids": "|".join(object_ids) or MISSING,
            "preferred_name": preferred_name,
        }
    return output


def pair_eligible(edge: Mapping[str, object], entities: Iterable[Mapping[str, object]]) -> bool:
    if str(edge.get("relation_status", "")) not in {"text_explicit", "figure_explicit", "human_confirmed"}:
        return False
    parent_id = str(edge.get("parent_entity_id", ""))
    derived_id = str(edge.get("derived_entity_id", ""))
    if parent_id in {"", MISSING} or derived_id in {"", MISSING} or parent_id == derived_id:
        return False
    by_id = {str(row.get("compound_entity_id", "")): row for row in entities}
    for compound_id in (parent_id, derived_id):
        entity = by_id.get(compound_id, {})
        if str(entity.get("structure_status") or "") != "complete_structure_resolved":
            return False
        if str(entity.get("structure_review_status") or "") not in CONFIRMED_STRUCTURE_REVIEW_STATES:
            return False
        if _canonical_complete_smiles(entity.get("canonical_smiles")) == MISSING:
            return False
    return True


def _matched_evidence_text(
    paper_id: str, page: int, derived_label: str, fallback: str,
    evidence_rows: Iterable[Mapping[str, object]],
) -> str:
    """Return the reviewed annotation evidence without silent substitution.

    Page-level candidate evidence is useful context, but a sentence merely
    mentioning the same compound label is not proof that it supports the same
    immediate-parent relation.  The previous lexical matcher replaced 391
    Batch05/06 annotation statements, including `8991dc7472bd / 1 -> 2` with
    an unrelated sentence about compounds 14-19.  Until the CSV schema has a
    separate contextual-evidence field, the reviewed annotation owns this
    value.
    """
    del paper_id, page, derived_label, evidence_rows
    return str(fallback or "").strip() or MISSING


def _evidence_strength(relation_status: object) -> str:
    """Preserve the provenance class of every supported lineage relation."""
    status = str(relation_status or "").strip()
    return {
        "text_explicit": "text_explicit",
        "figure_explicit": "figure_explicit",
        "human_confirmed": "human_confirmed",
    }.get(status, "unresolved_context")


def build_lineage_snapshot(
    evidence_rows: Iterable[Mapping[str, object]],
    structure_rows: Iterable[Mapping[str, object]],
    activity_rows: Iterable[Mapping[str, object]] = (),
    *, annotations: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    evidence_list = [dict(row) for row in evidence_rows]
    structure_list = [dict(row) for row in structure_rows]
    activity_list = [dict(row) for row in activity_rows]
    annotation_map = dict(annotations or {})
    lineage_specs: dict[str, list[dict[str, object]]] = {
        paper_id: list(specs) for paper_id, specs in LINEAGE_SPECS.items()
    }
    preferred_names = dict(PREFERRED_NAMES)
    origins = dict(ORIGINS)
    paper_dois = dict(PAPER_DOIS)
    active_papers = {
        str(row.get("paper_id", ""))
        for row in evidence_list + structure_list + activity_list
        if row.get("paper_id")
    }
    for paper_id, annotation in annotation_map.items():
        if str(annotation.get("annotation_status", "evidence_annotated")) == "no_supported_lineage":
            lineage_specs.pop(paper_id, None)
            continue
        raw_edges = annotation.get("edges", [])
        if not isinstance(raw_edges, list):
            continue
        lineage_specs[paper_id] = [dict(edge) for edge in raw_edges if isinstance(edge, dict)]
        paper_dois[paper_id] = str(annotation.get("doi") or "")
        for label, name in dict(annotation.get("preferred_names", {})).items():
            preferred_names[(paper_id, normalize_label(label))] = str(name)
        for label, origin in dict(annotation.get("origins", {})).items():
            origins[(paper_id, normalize_label(label))] = str(origin)
        raw_external_structures = annotation.get("external_structures", [])
        if isinstance(raw_external_structures, list):
            for raw_structure in raw_external_structures:
                if isinstance(raw_structure, Mapping):
                    structure_list.append({
                        **dict(raw_structure),
                        "paper_id": paper_id,
                    })
        if annotation.get("edges"):
            active_papers.add(paper_id)
    for paper_id, raw_structures in BUILTIN_EXTERNAL_STRUCTURES.items():
        if paper_id not in active_papers:
            continue
        for raw_structure in raw_structures:
            structure_list.append({
                **dict(raw_structure),
                "paper_id": paper_id,
            })
    structures = _structure_index(structure_list)
    entities: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []

    for paper_id, specs in lineage_specs.items():
        if paper_id not in active_papers:
            continue
        doi = paper_dois.get(paper_id, "")
        labels = sorted(
            {normalize_label(spec[key]) for spec in specs for key in ("root", "parent", "derived") if spec[key] != MISSING},
            key=lambda value: (int(re.match(r"\d+", value).group()) if re.match(r"\d+", value) else 999999, value),
        )
        lineage_by_label: dict[str, set[str]] = defaultdict(set)
        outgoing: Counter[str] = Counter()
        incoming: Counter[str] = Counter()
        for spec in specs:
            lineage_id = f"LINEAGE-{paper_id}-{spec['lineage']}"
            for key in ("root", "parent", "derived"):
                if spec[key] != MISSING:
                    lineage_by_label[normalize_label(spec[key])].add(lineage_id)
            if spec["parent"] != MISSING:
                outgoing[normalize_label(spec["parent"])] += 1
            incoming[normalize_label(spec["derived"])] += 1

        for label in labels:
            source = structures.get((paper_id, label), {})
            preferred_name = preferred_names.get((paper_id, label), "") or (
                source.get("preferred_name", "") if source.get("preferred_name") != MISSING else ""
            )
            is_root = any(normalize_label(spec["root"]) == label for spec in specs)
            if is_root:
                role = "root_template"
            elif outgoing[label] and incoming[label]:
                role = "lead" if label == "3" else "iteration_intermediate"
            elif outgoing[label]:
                role = "lead"
            else:
                role = "derived_compound"
            entities.append({
                "compound_entity_id": entity_id(paper_id, label),
                "paper_id": paper_id,
                "doi": doi,
                "lineage_ids": "|".join(sorted(lineage_by_label[label])),
                "display_label": f"{label} / {preferred_name}" if preferred_name else label,
                "normalized_label": label,
                "preferred_name": preferred_name or MISSING,
                "entity_origin": origins.get((paper_id, label), "in_paper"),
                "entity_role": role,
                "compound_object_ids": source.get("compound_object_ids", MISSING),
                "canonical_smiles": source.get("canonical_smiles", MISSING),
                "structure_status": source.get("structure_status", "missing_or_fragment_only"),
                "structure_source_type": source.get("structure_source_type", MISSING),
                "structure_source_file": source.get("structure_source_file", MISSING),
                "structure_source_locator": source.get("structure_source_locator", MISSING),
                "structure_review_status": source.get("structure_review_status", "unresolved"),
                "review_status": "unreviewed",
                "annotation_version": ANNOTATION_VERSION,
            })

        entity_map = {row["normalized_label"]: row for row in entities if row["paper_id"] == paper_id}
        specs_by_lineage: dict[str, list[dict[str, object]]] = defaultdict(list)
        for spec in specs:
            specs_by_lineage[str(spec["lineage"])].append(spec)
        depths_by_lineage: dict[str, dict[str, int]] = {}
        for lineage_key, lineage_specs in specs_by_lineage.items():
            depths: dict[str, int] = {
                normalize_label(spec["root"]): 0
                for spec in lineage_specs
                if spec["root"] != MISSING
            }
            for _ in range(len(lineage_specs) + 1):
                for spec in lineage_specs:
                    parent = normalize_label(spec["parent"]) if spec["parent"] != MISSING else MISSING
                    derived = normalize_label(spec["derived"])
                    parent_depth = depths.get(parent) if parent != MISSING else 0
                    if parent_depth is None:
                        continue
                    candidate_depth = parent_depth + 1
                    depths[derived] = min(depths.get(derived, candidate_depth), candidate_depth)
            depths_by_lineage[lineage_key] = depths
        for index, spec in enumerate(specs, 1):
            root_label = normalize_label(spec["root"])
            parent_label = normalize_label(spec["parent"]) if spec["parent"] != MISSING else MISSING
            derived_label = normalize_label(spec["derived"])
            lineage_id = f"LINEAGE-{paper_id}-{spec['lineage']}"
            edge_id = f"EDGE-{paper_id}-{int(spec['lineage']):02d}-{index:03d}-{derived_label}"
            evidence_id = f"EVID-{edge_id}-001"
            edge = {
                "lineage_edge_id": edge_id,
                "lineage_id": lineage_id,
                "paper_id": paper_id,
                "doi": doi,
                "root_template_entity_id": entity_map[root_label]["compound_entity_id"],
                "root_template_label": root_label,
                "parent_entity_id": entity_map[parent_label]["compound_entity_id"] if parent_label != MISSING else MISSING,
                "parent_label": parent_label,
                "derived_entity_id": entity_map[derived_label]["compound_entity_id"],
                "derived_label": derived_label,
                "parent_role": entity_map[parent_label]["entity_role"] if parent_label != MISSING else "unresolved",
                "iteration_depth": str(
                    depths_by_lineage[str(spec["lineage"])].get(
                        derived_label,
                        depths_by_lineage[str(spec["lineage"])].get(parent_label, 0) + 1,
                    )
                ),
                "modification_site": str(spec["modification_site"]),
                "from_group": str(spec["from_group"]),
                "to_group": str(spec["to_group"]),
                "relation_type": str(spec["relation_type"]),
                "relation_status": str(spec["relation_status"]),
                "relation_confidence": str(spec["relation_confidence"]),
                "evidence_ids": evidence_id,
                "pair_eligible": "no",
                "review_status": "unreviewed",
                "review_note": MISSING,
                "annotation_version": ANNOTATION_VERSION,
            }
            edge["pair_eligible"] = "yes" if pair_eligible(edge, entities) else "no"
            edges.append(edge)
            evidence.append({
                "lineage_evidence_id": evidence_id,
                "lineage_edge_id": edge_id,
                "lineage_id": lineage_id,
                "paper_id": paper_id,
                "doi": doi,
                "evidence_type": "text",
                "page": str(spec["page"]),
                "source_locator": str(spec["locator"]),
                "evidence_text": _matched_evidence_text(
                    paper_id, int(spec["page"]), str(spec["derived"]),
                    str(spec["evidence_text"]), evidence_list,
                ),
                "source_object_ids": MISSING,
                "evidence_strength": _evidence_strength(spec["relation_status"]),
                "review_status": "unreviewed",
                "annotation_version": ANNOTATION_VERSION,
            })

    entity_by_key = {(row["paper_id"], row["normalized_label"]): row for row in entities}
    activities: list[dict[str, str]] = []
    for index, row in enumerate(activity_list, 1):
        paper_id = str(row.get("paper_id", ""))
        label = normalize_label(row.get("compound_label", ""))
        entity = entity_by_key.get((paper_id, label))
        if not entity:
            continue
        activities.append({
            "activity_id": f"ACT-{paper_id}-{label}-{index:04d}",
            "paper_id": paper_id,
            "doi": str(row.get("doi") or entity["doi"]),
            "compound_entity_id": entity["compound_entity_id"],
            "compound_label": label,
            "target": str(row.get("target") or MISSING),
            "assay": str(row.get("assay") or MISSING),
            "metric": str(row.get("metric") or MISSING),
            "value": str(row.get("value") or MISSING),
            "unit": str(row.get("unit") or MISSING),
            "qualifier": str(row.get("qualifier") or "="),
            "comparator": str(row.get("comparator") or MISSING),
            "page": str(row.get("page") or MISSING),
            "source_locator": str(row.get("source_locator") or MISSING),
            "evidence_text": str(row.get("evidence_text") or MISSING),
            "review_status": "unreviewed",
            "annotation_version": ANNOTATION_VERSION,
        })
    return {"entities": entities, "edges": edges, "evidence": evidence, "activities": activities}


def write_lineage_snapshot(
    evidence_rows: Iterable[Mapping[str, object]],
    structure_rows: Iterable[Mapping[str, object]],
    activity_rows: Iterable[Mapping[str, object]] = (),
    *, annotations: Mapping[str, Mapping[str, object]] | None = None,
    entities: Path = DEFAULT_ENTITIES, edges: Path = DEFAULT_EDGES,
    evidence: Path = DEFAULT_LINEAGE_EVIDENCE, activities: Path = DEFAULT_ACTIVITIES,
    summary: Path = DEFAULT_SUMMARY,
) -> dict[str, object]:
    snapshot = build_lineage_snapshot(
        evidence_rows, structure_rows, activity_rows, annotations=annotations,
    )
    _atomic_write_csv(entities, ENTITY_FIELDS, snapshot["entities"])
    _atomic_write_csv(edges, EDGE_FIELDS, snapshot["edges"])
    _atomic_write_csv(evidence, EVIDENCE_FIELDS, snapshot["evidence"])
    _atomic_write_csv(activities, ACTIVITY_FIELDS, snapshot["activities"])
    lineage_paper_ids = {row["paper_id"] for row in snapshot["edges"]}
    annotation_map = dict(annotations or {})
    annotated_paper_ids = {
        str(paper_id)
        for paper_id, annotation in annotation_map.items()
        if annotation.get("edges")
        and str(annotation.get("annotation_status", "evidence_annotated")) != "no_supported_lineage"
    }
    builtin_paper_ids = {
        paper_id for paper_id in LINEAGE_SPECS
        if paper_id not in annotated_paper_ids and paper_id in lineage_paper_ids
    }
    result: dict[str, object] = {
        **snapshot,
        "summary": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "annotation_version": ANNOTATION_VERSION,
            "paper_rows": len({row["paper_id"] for row in snapshot["entities"]}),
            "lineage_rows": len({row["lineage_id"] for row in snapshot["edges"]}),
            "compound_entity_rows": len(snapshot["entities"]),
            "lineage_edge_rows": len(snapshot["edges"]),
            "lineage_evidence_rows": len(snapshot["evidence"]),
            "activity_rows": len(snapshot["activities"]),
            "pair_eligible_rows": sum(row["pair_eligible"] == "yes" for row in snapshot["edges"]),
            "unresolved_parent_rows": sum(row["parent_entity_id"] == MISSING for row in snapshot["edges"]),
            "relation_status_counts": dict(Counter(row["relation_status"] for row in snapshot["edges"])),
            "structure_status_counts": dict(Counter(row["structure_status"] for row in snapshot["entities"])),
            "lineage_paper_ids": sorted(lineage_paper_ids),
            "lineage_paper_rows": len(lineage_paper_ids),
            "annotated_paper_rows": len(annotated_paper_ids & lineage_paper_ids),
            "builtin_paper_rows": len(builtin_paper_ids),
            "pair_ready_paper_rows": len({row["paper_id"] for row in snapshot["edges"] if row["pair_eligible"] == "yes"}),
            "corpus_paper_rows": len(read_csv(DEFAULT_DOCUMENT_INDEX)) if DEFAULT_DOCUMENT_INDEX.is_file() else 0,
        },
    }
    result["summary"]["remaining_corpus_paper_rows"] = max(
        0,
        int(result["summary"]["corpus_paper_rows"])
        - int(result["summary"]["paper_rows"]),
    )
    _atomic_write_json(summary, result["summary"])
    return result


def _read_source_rows(path: Path, *, delimiter: str = ",") -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
    if not rows:
        return []
    headers = rows[0]
    smiles_index = next(
        (index for index, header in enumerate(headers)
         if "smiles" in str(header or "").casefold()),
        None,
    )
    normalized_rows: list[dict[str, str]] = []
    for values in rows[1:]:
        if smiles_index is not None and len(values) > len(headers):
            # Some ACS exports leave commas inside CXSMILES atom annotations
            # unquoted (for example, ``|a:14,17|``), shifting every assay value.
            close_index = next(
                (
                    index for index in range(smiles_index, len(values))
                    if "|" in values[index] and values[index].rstrip().endswith("|")
                ),
                None,
            )
            if close_index is not None and close_index > smiles_index:
                values[smiles_index:close_index + 1] = [
                    delimiter.join(values[smiles_index:close_index + 1])
                ]
        if len(values) < len(headers):
            values.extend([""] * (len(headers) - len(values)))
        normalized_rows.append(dict(zip(headers, values)))
    return normalized_rows


def _source_structure_and_activity_rows(
    *, annotations: Mapping[str, Mapping[str, object]] | None = None,
    source_manifest: Path = DEFAULT_SOURCE_MANIFEST,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    structures: list[dict[str, str]] = []
    activities: list[dict[str, str]] = []
    if not source_manifest.is_file():
        return structures, activities
    paper_by_doi = {doi.casefold(): paper_id for paper_id, doi in PAPER_DOIS.items()}
    activity_columns_by_paper: dict[str, list[Mapping[str, object]]] = {
        GLP1_PAPER_ID: [
            {
                "column": "EC50 of stimulating cAMP accumulation in HEK293 cells",
                "target": "GLP-1R", "assay": "cAMP accumulation in HEK293 cells",
                "metric": "EC50", "unit": "nM",
            },
            {
                "column": "pEC50 of stimulating cAMP accumulation in HEK293 cells",
                "target": "GLP-1R", "assay": "cAMP accumulation in HEK293 cells",
                "metric": "pEC50", "unit": MISSING,
            },
        ],
    }
    for paper_id, annotation in dict(annotations or {}).items():
        doi = str(annotation.get("doi") or "").casefold()
        if doi:
            paper_by_doi[doi] = paper_id
        raw_activity_columns = annotation.get("activity_columns", [])
        if isinstance(raw_activity_columns, list):
            activity_columns_by_paper[paper_id] = [
                column for column in raw_activity_columns if isinstance(column, Mapping)
            ]
    for manifest in read_csv(source_manifest):
        doi = str(manifest.get("doi", ""))
        paper_id = paper_by_doi.get(doi.casefold())
        if not paper_id:
            continue
        source_file = str(manifest.get("source_file", ""))
        path = source_manifest.parent / source_file
        delimiter = str(manifest.get("delimiter", "") or ",")
        rows = _read_source_rows(path, delimiter=delimiter)
        label_column = str(manifest.get("label_column", "Compound_ID"))
        smiles_column = str(manifest.get("smiles_column", "SMILES"))
        for row in rows:
            label = normalize_label(row.get(label_column, ""))
            smiles = _canonical_complete_smiles(row.get(smiles_column, ""))
            if label == MISSING or smiles == MISSING:
                continue
            structures.append({
                "paper_id": paper_id, "compound_label": label,
                "canonical_smiles": smiles, "structure_status": "source_confirmed",
                "structure_source_type": str(manifest.get("source_type", "supporting_information_csv")),
                "structure_source_file": source_file,
                "structure_source_locator": f"{manifest.get('source_locator_prefix', 'Compound=')}{row.get(label_column, label)}",
                "structure_review_status": "exact_si_label_match",
            })
            for activity_spec in activity_columns_by_paper.get(paper_id, []):
                column = str(activity_spec.get("column") or "")
                raw_value = str(row.get(column, "") or "").strip()
                if not raw_value:
                    continue
                qualifier_match = re.match(r"^([<>]=?)\s*", raw_value)
                qualifier = qualifier_match.group(1) if qualifier_match else "="
                value = re.sub(r"^[<>]=?\s*", "", raw_value).strip()
                unit = str(activity_spec.get("unit") or MISSING)
                if unit != MISSING:
                    value = re.sub(rf"\s*{re.escape(unit)}\s*$", "", value, flags=re.IGNORECASE).strip()
                activities.append({
                    "paper_id": paper_id, "doi": doi, "compound_label": label,
                    "target": str(activity_spec.get("target") or MISSING),
                    "assay": str(activity_spec.get("assay") or MISSING),
                    "metric": str(activity_spec.get("metric") or column or MISSING),
                    "value": value, "unit": unit, "qualifier": qualifier,
                    "page": "--", "source_locator": f"{source_file}:{label_column}={label}",
                    "evidence_text": f"{column}: {raw_value}",
                })
    return structures, activities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--reconstructions", type=Path, default=DEFAULT_RECONSTRUCTIONS)
    parser.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES)
    parser.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    parser.add_argument("--lineage-evidence", type=Path, default=DEFAULT_LINEAGE_EVIDENCE)
    parser.add_argument("--activities", type=Path, default=DEFAULT_ACTIVITIES)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--confirmed-paths", type=Path, default=DEFAULT_CONFIRMED_PATHS)
    parser.add_argument(
        "--confirmed-structures", type=Path,
        default=DEFAULT_CONFIRMED_STRUCTURES,
    )
    args = parser.parse_args(argv)

    annotations = load_lineage_annotations(args.annotations)
    paper_by_doi = {
        str(row.get("doi") or "").casefold(): str(row.get("paper_id") or "")
        for row in read_csv(DEFAULT_DOCUMENT_INDEX)
        if row.get("doi") and row.get("paper_id")
    } if DEFAULT_DOCUMENT_INDEX.is_file() else {}
    paper_by_doi.update({doi.casefold(): paper_id for paper_id, doi in PAPER_DOIS.items()})
    confirmed_annotations, confirmed_structures = load_confirmed_path_data(
        args.confirmed_paths, paper_by_doi,
    )
    for paper_id, annotation in confirmed_annotations.items():
        if paper_id not in annotations and paper_id not in LINEAGE_SPECS:
            annotations[paper_id] = annotation
    reconstructions = read_csv(args.reconstructions) if args.reconstructions.is_file() else []
    authoritative_structures = load_confirmed_structures(args.confirmed_structures)
    source_structures, source_activities = _source_structure_and_activity_rows(annotations=annotations)
    result = write_lineage_snapshot(
        read_csv(args.evidence), [
            *reconstructions,
            *confirmed_structures,
            *source_structures,
            *authoritative_structures,
        ], source_activities,
        entities=args.entities, edges=args.edges, evidence=args.lineage_evidence,
        activities=args.activities, summary=args.summary,
        annotations=annotations,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
