#!/usr/bin/env python3
"""Generate conservative Paper-local lineage annotations for Batch 06.

The fixed batch boundary is declared before annotation or aggregate writes.
Later additions to this module must preserve source-backed immediate parents
and use unresolved records for series without one unique direct parent.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTO_FILL_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
ANNOTATION_DIR = AUTO_FILL_DIR / "lineage_annotations"
BATCH_06_VERSION = "compound_lineages_v1_2026-09-10-batch06"
MISSING = "--"

BATCH_06_PAPERS: tuple[tuple[str, str], ...] = (
    ("2c96aaf509b1", "10.1021/acs.jmedchem.4c03149"),
    ("56f50284cedf", "10.1021/acs.jmedchem.4c01645"),
    ("434e5748f070", "10.1021/acs.jmedchem.4c01744"),
    ("f3d107dabbcb", "10.1021/acs.jmedchem.3c02302"),
    ("1485ed4aa91b", "10.1021/acs.jmedchem.4c00555"),
    ("c150a5edd8dd", "10.1021/acs.jmedchem.4c01815"),
    ("8991dc7472bd", "10.1021/acs.jmedchem.3c02441"),
    ("1994543a9112", "10.1021/acs.jmedchem.4c00265"),
    ("bf54bac4775b", "10.1021/acs.jmedchem.4c02377"),
    ("feef9e819b88", "10.1021/acs.jmedchem.4c01727"),
    ("2a98b0589a08", "10.1021/acs.jmedchem.4c00734"),
    ("c958fce90ec5", "10.1021/acs.jmedchem.4c01395"),
    ("e4043323f96c", "10.1021/acs.jmedchem.4c02169"),
    ("65e19df86a4a", "10.1021/acs.jmedchem.4c01323"),
    ("cab92325187b", "10.1021/acs.jmedchem.3c02288"),
    ("8e421ecc451e", "10.1021/acs.jmedchem.3c02046"),
    ("07dcad0214c3", "10.1021/acs.jmedchem.3c02203"),
    ("7e503b3382bf", "10.1021/acs.jmedchem.4c01178"),
    ("4bd630dc5dc8", "10.1021/acs.jmedchem.4c00972"),
    ("2d5a56fffb44", "10.1021/acs.jmedchem.4c00357"),
    ("c6c61d0fc737", "10.1021/acs.jmedchem.4c00643"),
    ("096b579fa25f", "10.1021/acs.jmedchem.3c01934"),
    ("023145d60eea", "10.1021/acs.jmedchem.4c00513"),
    ("b09de250fcb3", "10.1021/acs.jmedchem.4c03205"),
)


def _normalize_doi(value: object) -> str:
    doi = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):].strip()
    return doi


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_batch_selection(
    *,
    annotation_dir: Path = ANNOTATION_DIR,
    entities_path: Path = AUTO_FILL_DIR / "compound_entities.csv",
) -> None:
    """Reject duplicate or previously owned Batch 06 Paper/DOI boundaries."""
    if len(BATCH_06_PAPERS) != 24:
        raise ValueError("Batch 06 must contain exactly 24 Papers")
    selected = dict(BATCH_06_PAPERS)
    if len(selected) != len(BATCH_06_PAPERS):
        raise ValueError("Batch 06 contains duplicate Paper IDs")
    selected_dois = {_normalize_doi(doi) for doi in selected.values()}
    if "" in selected_dois or len(selected_dois) != len(selected):
        raise ValueError("Batch 06 contains blank or duplicate DOIs")

    own_annotations: set[str] = set()
    for path in Path(annotation_dir).glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unreadable lineage annotation: {path}") from error
        paper_id = str(payload.get("paper_id") or path.stem)
        doi = _normalize_doi(payload.get("doi"))
        if paper_id in selected:
            if payload.get("annotation_version") != BATCH_06_VERSION:
                raise ValueError(
                    f"Batch 06 Paper already belongs to another annotation: {paper_id}"
                )
            if doi != _normalize_doi(selected[paper_id]):
                raise ValueError(f"Batch 06 annotation DOI mismatch: {paper_id}")
            own_annotations.add(paper_id)
        elif doi in selected_dois:
            raise ValueError(
                f"Batch 06 DOI is already owned by another Paper: {doi}"
            )

    aggregate_selected_ids: set[str] = set()
    for row in _read_csv(Path(entities_path)):
        paper_id = str(row.get("paper_id") or "")
        doi = _normalize_doi(row.get("doi"))
        if paper_id in selected:
            aggregate_selected_ids.add(paper_id)
        elif doi in selected_dois:
            raise ValueError(
                f"Batch 06 DOI is already present under another Paper: {doi}"
            )
    unpublished_conflicts = aggregate_selected_ids - own_annotations
    if unpublished_conflicts:
        raise ValueError(
            "Batch 06 Paper was already published before its annotation: "
            + ", ".join(sorted(unpublished_conflicts))
        )


def edge(
    root: str,
    parent: str,
    derived: str,
    page: int,
    text: str,
    locator: str,
    site: str = MISSING,
    old: str = MISSING,
    new: str = MISSING,
    *,
    relation: str = "substituent_replacement",
    status: str = "text_explicit",
    confidence: str = "high",
) -> dict[str, object]:
    return {
        "lineage": "01",
        "root": root,
        "parent": parent,
        "derived": derived,
        "page": page,
        "evidence_text": text,
        "locator": locator,
        "modification_site": site,
        "from_group": old,
        "to_group": new,
        "relation_type": relation,
        "relation_status": status,
        "relation_confidence": confidence,
    }


def unresolved(
    root: str,
    derived: str,
    page: int,
    text: str,
    locator: str,
) -> dict[str, object]:
    return edge(
        root,
        MISSING,
        derived,
        page,
        text,
        locator,
        relation="series_membership_only",
        status="unresolved",
        confidence="unresolved_direct_parent",
    )


def series(
    root: str,
    labels: list[str],
    page: int,
    text: str,
    locator: str,
) -> list[dict[str, object]]:
    return [unresolved(root, label, page, text, locator) for label in labels]


def record(
    doi: str,
    edges: list[dict[str, object]],
    note: str,
    *,
    status: str = "evidence_annotated",
    names: dict[str, str] | None = None,
    origins: dict[str, str] | None = None,
    source_files: dict[str, str] | None = None,
) -> dict[str, object]:
    names = dict(names or {})
    origins = dict(origins or {})
    for row in edges:
        for key in ("root", "parent", "derived"):
            label = str(row[key])
            if label != MISSING:
                origins.setdefault(label, "in_paper")
    return {
        "doi": doi,
        "annotation_status": status,
        "review_note": note,
        "preferred_names": names,
        "origins": origins,
        "activity_columns": [],
        "source_files": dict(source_files or {}),
        "edges": edges,
        "annotation_version": BATCH_06_VERSION,
    }


def _numbers(start: int, end: int) -> list[str]:
    return [str(number) for number in range(start, end + 1)]


def _prefixed(prefix: str, start: int, end: int, width: int = 0) -> list[str]:
    return [f"{prefix}{number:0{width}d}" for number in range(start, end + 1)]


def _reviewed_record(
    doi: str,
    root: str,
    machine_labels: list[str],
    explicit_edges: list[dict[str, object]],
    note: str,
    source_file: str,
    *,
    names: dict[str, str] | None = None,
    origins: dict[str, str] | None = None,
    unresolved_page: int = 3,
    unresolved_locator: str = "SAR tables; immediate-parent review",
) -> dict[str, object]:
    """Add every source-labelled structure without inventing direct edges."""
    owned_derived = {str(row["derived"]) for row in explicit_edges}
    remaining = [
        label for label in machine_labels
        if label != root and label not in owned_derived
    ]
    unresolved_edges = series(
        root,
        remaining,
        unresolved_page,
        (
            "The Paper and DOI-matched machine table identify this compound "
            "as a member of the reviewed SAR campaign, but the reviewed source "
            "does not state one unique immediate parent for this label."
        ),
        unresolved_locator,
    )
    return record(
        doi,
        [*explicit_edges, *unresolved_edges],
        note,
        names=names,
        origins=origins,
        source_files={"machine_structure_table": source_file},
    )


def build_annotations() -> dict[str, dict[str, object]]:
    """Return source-reviewed, conservative annotations for Batch 06."""
    annotations: dict[str, dict[str, object]] = {}

    # Ferrostatin campaign: the article explicitly identifies Fer-1 ->
    # UAMC-3203 and four corresponding cycloalkyl matched series.
    ferrostatin_edges = [
        edge("FER-1", "FER-1", "UAMC-3203", 2, "UAMC-3203 is a Fer-1 analogue in which the labile ester moiety was replaced with a more stable ethyl-piperazine sulfonamide.", "Introduction; Figure 1", "linker", "ester", "ethyl-piperazine sulfonamide", relation="linker_bioisostere"),
    ]
    for parent, children in {
        "75": ["73", "74", "76", "77"],
        "80": ["78", "79", "81", "82"],
        "96": ["94", "95", "97", "98"],
        "101": ["99", "100", "102", "103"],
    }.items():
        for child in children:
            ferrostatin_edges.append(edge(
                "FER-1", parent, child, 4,
                f"Compound {child} is the cycloalkyl replacement matched to the corresponding cyclohexyl analogue {parent} in the article's ring-size comparison.",
                "SAR; Tables 2-3", "lipophilic cycloalkyl anchor", "cyclohexyl", "alternate cycloalkyl", relation="ring_size_change", status="figure_explicit",
            ))
    annotations["2c96aaf509b1"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c03149", "FER-1",
        [*_numbers(13, 16), *_numbers(35, 51), *_numbers(73, 86), *_numbers(94, 105), "FER-1", "UAMC-3203"],
        ferrostatin_edges,
        "Fer-1 and UAMC-3203 are named templates. Only the named ester-to-sulfonamide step and the four article-defined corresponding cyclohexyl/ring-size comparisons are direct; the remaining benzamide and oxazole table members stay unresolved.",
        "jm4c03149_si_001.csv", names={"FER-1": "ferrostatin-1", "96": "UAMC-4821"}, origins={"FER-1": "prior_art", "UAMC-3203": "prior_art"},
    )

    ac1_labels = [f"7-{number}A" for number in range(1, 63)] + [
        "7-1B", "7-27B", "7-31B", "7-42B", "7-43B", "7-47B", "7-49B",
    ]
    ac1_edges = [
        edge("7-6A", "7-6A", f"7-{number}A", 4, f"The 3-substituted analogue 7-{number}A was compared directly with the unsubstituted phenyl derivative 7-6A.", "SAR; Table 1", "phenyl 3-position", "hydrogen", "alkyl substituent", status="figure_explicit")
        for number in range(1, 6)
    ]
    for parent, children in {
        "7-6A": ["7-45A", "7-46A", "7-47A", "7-58A", "7-59A", "7-60A", "7-61A", "7-62A"],
        "7-27A": ["7-48A", "7-49A", "7-50A"],
        "7-1A": ["7-51A", "7-52A", "7-53A"],
        "7-17A": ["7-54A", "7-55A", "7-56A"],
    }.items():
        for child in children:
            ac1_edges.append(edge(
                "7-6A", parent, child, 5,
                f"Table 2 identifies compound {child} as the methylene-branched member matched to nonbranched compound {parent}.",
                "SAR; Table 2", "amine-linker methylene", "hydrogen", "methyl/alkyl branch", relation="linker_substitution", status="figure_explicit", confidence="medium",
            ))
    for parent, derived in {
        "AC10079": "7-1A", "AC10081": "7-2A", "AC10071": "7-4A",
        "AC10068": "7-6A", "AC10048": "7-14A", "AC10061": "7-17A",
        "AC10102": "7-39A",
    }.items():
        ac1_edges.append(edge(
            "AC10102", parent, derived, 7,
            f"Removal of the amide carbonyl from prior comparator {parent} produced its amine-linker matched molecular pair {derived}.",
            "Design rationale; Figure 2; Table 4", "pyrazole-pendant linker", "amide C(O)", "amine CH2", relation="linker_bioisostere", status="figure_explicit",
        ))
    for row in ac1_edges:
        row["root"] = "AC10102"
    annotations["56f50284cedf"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01645", "AC10102", ac1_labels, ac1_edges,
        "Prior amide-linked AC10102 is the motivating root, with seven explicit amide-to-amine matched pairs. Table-defined branched pairs are direct; other positional, stereochemical, and A/B regioisomer scans remain unresolved.",
        "jm4c01645_si_002.csv", names={"7-47A": "AC10142A"}, origins={name: "prior_art" for name in ["AC10079", "AC10081", "AC10071", "AC10068", "AC10048", "AC10061", "AC10102"]},
    )

    irap_edges = [
        *[edge("BDM_14470", "BDM_14470", str(number), 3, f"Figure 3C identifies compound {number} as a member of the first optimization step from BDM_14470.", "Figure 3C", "malonamide side chain", "BDM_14470 side chain", "compound-series side chain", status="figure_explicit") for number in range(1, 7)],
        edge("6", "6", "7", 4, "Introduction of an iso-pentyl group into compound 6 gave compound 7.", "SAR; Table 1", "alkyl side chain", "iso-butyl", "iso-pentyl"),
        edge("6", "6", "8", 4, "Replacement of the iso-butyl group of compound 6 with a 2,2-dimethylbutyl group produced compound 8.", "SAR; Table 1", "alkyl side chain", "iso-butyl", "2,2-dimethylbutyl"),
        edge("6", "6", "9", 4, "Replacement of the iso-butyl group of compound 6 with a phenethyl group produced compound 9.", "SAR; Table 1", "alkyl side chain", "iso-butyl", "phenethyl"),
        *[edge("6", "6", str(number), 6, f"Substitution at indole position 5 or 6 of compound 6 produced compound {number}.", "SAR; Table 2", "indole C5/C6", "hydrogen", "Table 2 substituent", status="figure_explicit") for number in range(10, 20)],
        *[edge("6", "18", str(number), 6, f"Isosteric replacement of the terminal phenyl ring of compound 18 with pyridine produced compound {number}.", "SAR; Table 2", "C5 benzyloxy terminal ring", "phenyl", "pyridyl", relation="ring_aza_substitution") for number in range(20, 23)],
        *[
            edge("6", "7", label, 6, f"The 5-hydroxyindole group of isopentyl inhibitor 7 was substituted to give compound {label} in the 23-36 series.", "SAR; Table 3", "5-hydroxyindole substituent", "hydroxy", "Table 3 substituent", status="figure_explicit")
            for label in _numbers(23, 36)
        ],
        edge("6", "18", "43", 8, "For the 5-benzyloxy analogue, introduction of the (S)-carbamoyl moiety produced compound 43 from compound 18.", "SAR; Table 4", "alkyl linker", "hydrogen", "(S)-carbamoyl"),
        *[edge("6", "6", str(number), 7, f"Substitution at R2 of compound 6 produced compound {number}.", "SAR; Table 4", "linker R2", "hydrogen", "methyl/hydroxymethyl/carbamoyl", status="figure_explicit") for number in range(37, 41)],
    ]
    for row in irap_edges:
        row["root"] = "BDM_14470"
    annotations["434e5748f070"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01744", "BDM_14470", _numbers(1, 44), irap_edges,
        "Figure 3C identifies BDM_14470 as the prior-work root and compound 6 as the operative local parent. The alkyl, indole, 18-pyridine, 7-rooted C5, R2, and 18-to-43 comparisons are direct. Combination products 41, 42, and 44 remain unresolved.",
        "jm4c01744_si_002.csv", names={"18": "BDM_76464", "43": "BDM_92499"}, origins={"BDM_14470": "prior_art"},
    )

    her2_labels = ["2", "3"] + [
        f"{prefix}{suffix}" for prefix in range(4, 10) for suffix in "abcd"
    ] + [f"10{x}" for x in "abcde"] + [f"11{x}" for x in "abcdef"]
    her2_edges = [
        *[edge("2", "4a", f"4{x}", 7, f"Modification of compound 4a at the 3- and 4-positions of its C5 phenyl group produced compound 4{x}.", "SAR; Table 2", "C5 phenyl substitution", "4a pattern", "modified pattern") for x in "bcd"],
        *[edge("2", "5a", f"5{x}", 7, f"Modification of compound 5a at the 3- and 4-positions of its C5 phenyl group produced compound 5{x}.", "SAR; Table 2", "C5 phenyl substitution", "5a pattern", "modified pattern") for x in "bcd"],
        *[edge("2", "3", f"8{x}", 10, f"Cyclization of compound 3 generated conformationally restricted compound 8{x}.", "SAR; Figure 5; Table 3", "quinazoline C5/N4", "acyclic", "cyclized", relation="ring_closure", status="figure_explicit") for x in "abcd"],
        *[edge("2", "3", f"9{x}", 10, f"Cyclization of compound 3 generated conformationally restricted compound 9{x}.", "SAR; Figure 5; Table 3", "quinazoline C5/N4", "acyclic", "cyclized", relation="ring_closure", status="figure_explicit") for x in "abcd"],
    ]
    annotations["f3d107dabbcb"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c02302", "2", her2_labels, her2_edges,
        "Lead 2, the 4a/5a phenyl branches, and the compound-3 cyclizations are retained as article-defined comparisons. Compound 3 itself and the 6/7/10/11 series remain unresolved because their unique immediate parents are not stated.",
        "jm3c02302_si_001.csv", origins={"2": "prior_art"},
    )

    p2y_edges = [
        *[edge("9", "9", f"I-{number}", 4, f"Replacement of the tryptophan moiety of compound 9 with the benzoheterocycle in compound I-{number} produced that analogue.", "Design; Figure 3; Table 1", "tryptophan/basic region", "tryptophan moiety", "Table 1 benzoheterocycle", status="figure_explicit") for number in range(1, 12)],
        *[edge("9", "I-1", f"I-{number}", 4, f"On the basis of I-1, replacement of the para methyl substituent produced compound I-{number}.", "SAR; Table 2", "para phenoxy substituent", "methyl", "Table 2 substituent", status="figure_explicit") for number in range(12, 21)],
        *[edge("9", "I-7", f"I-{number}", 4, f"Replacement of the para methyl substituent of I-7 produced compound I-{number} in the matched quinoline series.", "SAR; Table 2", "para phenoxy substituent", "methyl", "Table 2 substituent", status="figure_explicit") for number in range(21, 30)],
    ]
    annotations["1485ed4aa91b"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00555", "9", _prefixed("I-", 1, 29), p2y_edges,
        "Prior antagonist 9 is the design template. I-1 and I-7 anchor the two explicitly described para-substituent scans; the initial heterocycle scan I-1-I-11 does not have a unique immediate parent in the reviewed passage.",
        "jm4c00555_si_001.csv", names={"2": "PPTN"}, origins={"9": "prior_art"},
    )

    kna_labels = ["D27", *_prefixed("Z", 1, 38, 2)]
    annotations["c150a5edd8dd"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01815", "D27", kna_labels,
        [
            edge("D27", "Z05", "Z06", 10, "Replacement of the piperidine ring of compound Z05 with pyridine produced compound Z06.", "SAR; Table 1", "terminal six-membered heterocycle", "piperidine", "pyridine", relation="ring_replacement"),
            *[edge("D27", "D27", f"Z{number:02d}", 10, f"Moving the imine of D27 toward the aryl group and replacing the terminal amino group produced compound Z{number:02d} in the Z22-Z38 series.", "SAR; Table 3; Scheme 4", "aryl-linked amine region", "D27 amine placement", "Table 3 basic substituent", status="figure_explicit") for number in range(22, 39)],
        ],
        "D27 is the explicitly selected second-round screening hit. Z05-to-Z06 and the D27-rooted Z22-Z38 aryl-methylamine series are direct. B01-B31 and D01-D29 are screening-library records, not automatically treated as lineage descendants; Z01-Z05 and Z07-Z21 remain unresolved.",
        "jm4c01815_si_002.csv", origins={"D27": "virtual_screen_hit"}, names={"Z05": "Z05"},
    )

    mnk_edges = [
        *[edge("1", "1", str(number), 5, f"Changing the pyridine structure of compound 1 to the benzene or substituted-benzene analogue produced compound {number}.", "Molecular design; Table 1", "pyrazole-linked aryl/heteroaryl", "4-pyridyl", "phenyl/substituted phenyl", status="figure_explicit") for number in range(2, 9)],
        edge("1", "1", "41", 7, "Introduction of a methyl group on the piperidine of compound 1 gave compound 41.", "SAR; Table 4", "piperidine nitrogen", "hydrogen", "methyl"),
    ]
    annotations["8991dc7472bd"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c02441", "1", _numbers(1, 41), mnk_edges,
        "Compound 1 is the stated parent for the 2-8 aryl-change series and piperidine methyl analogue 41. The paper names compound 36 as D25, but its conclusion-level path from 1 is not treated as one immediate step. Other heteroaromatic and table members remain unresolved.",
        "jm3c02441_si_002.csv", names={"36": "D25"},
    )

    cef_labels = (
        [f"24{x}" for x in "abcde"]
        + [f"58{x}" for x in "abcdefghijklmnopqrsuv"]
        + [f"73{x}" for x in "abcdefgh"]
        + ["86a", "86b"]
    )
    annotations["1994543a9112"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00265", "cefiderocol", cef_labels,
        [
            *[edge("cefiderocol", "cefiderocol", f"24{x}", 6, f"Replacement of cefiderocol's C3 pyrrolidinium linker with the neutral thioether linker produced compound 24{x}.", "SAR; Table 1", "cephalosporin C3 linker", "cationic pyrrolidinium", "aliphatic thioether", status="figure_explicit") for x in "abcde"],
            edge("cefiderocol", "cefiderocol", "58q", 7, "One methyl group of the gem-dimethyl fragment of cefiderocol was replaced by CF3 to give compound 58q.", "SAR; Table 4", "oxime-ether gem-dimethyl fragment", "methyl", "trifluoromethyl"),
            edge("cefiderocol", "58l", "58m", 10, "Blocking the para metabolic site of cyclohexyl compound 58l with fluorines produced compound 58m.", "PK optimization; Table 7", "cyclohexyl para carbon", "methylene", "difluoromethylene"),
            edge("cefiderocol", "58m", "86b", 10, "Compound 86b is the favorable isolated epimer of compound 58m.", "Stereochemical SAR; Tables 5 and 7", "oxime-ether alpha stereocenter", "epimeric mixture", "favorable single epimer", relation="stereoisomer_resolution"),
        ],
        "Cefiderocol is the explicit antibiotic template. Its C3 thioether set, CF3 analogue 58q, 58l-to-58m metabolic-site block, and 58m-to-86b stereochemical selection are direct. Other machine-labelled 58, 73, and 86 analogues remain unresolved; the 58c machine row is additionally withheld because its graph duplicates 58b and conflicts with the paper's isopropyl description.",
        "jm4c00265_si_001.csv", names={"86b": "YFJ-36"}, origins={"cefiderocol": "prior_art"},
    )

    stx_labels = [*_numbers(1, 53), *_prefixed("S", 1, 10)]
    stx_edges = [
        *[edge("1", "1", str(number), 3, f"Modification of the pyridyl hinge binder of compound 1 produced compound {number}.", "SAR; Table 1", "pyridyl hinge binder", "compound-1 group", "Table 1 group", status="figure_explicit") for number in range(2, 9)],
        *[edge("1", "8", str(number), 4, f"Modification of the aniline substitution pattern of compound 8 produced compound {number}.", "SAR; Table 2", "aniline substitution", "2-OMe/3-Cl", "Table 2 pattern", status="figure_explicit") for number in range(9, 20)],
        *[edge("1", "4", str(number), 5, f"Pyrrololactam-core substitution of compound 4 toward the ribose pocket produced compound {number}.", "SAR; Table 3", "pyrrololactam core", "hydrogen", "methoxyalkyl substituent", status="figure_explicit") for number in range(20, 26)],
        edge("1", "23", "26", 6, "The putative oxidative/elimination metabolite of compound 23 was synthesized as compound 26.", "Metabolite/PK review; Table 5", "pyrrololactam core", "compound-23 core", "oxidized/eliminated metabolite", relation="metabolite_relationship"),
        edge("1", "23", "27", 7, "Methyl substitution at the oxidation-prone 7-position of compound 23 produced isomer 27.", "SAR; Table 5", "pyrrololactam 7-position", "hydrogen", "methyl"),
        edge("1", "23", "28", 7, "Cyclization of the ethylmethoxy substituent of compound 23 produced oxetane compound 28.", "SAR; Table 5", "ribose-pocket ethylmethoxy", "acyclic ethylmethoxy", "oxetane", relation="ring_closure"),
        *[edge("1", "23", str(number), 7, f"Cyclization of the ethylmethoxy substituent of compound 23 produced dioxolane compound {number}.", "SAR; Table 5", "ribose-pocket ethylmethoxy", "acyclic ethylmethoxy", "dioxolane", relation="ring_closure") for number in [29, 30]],
        edge("1", "33", "38", 9, "Covalent-warhead growth from noncovalent 3-alkynylpyridine compound 33 produced R-pyrrolidine acrylamide compound 38.", "Covalent design; Figure 6; Table 8", "3-alkynylpyridine terminus", "noncovalent alkyne", "propargylic pyrrolidine acrylamide", status="figure_explicit"),
        edge("1", "38", "39", 9, "The fluorine analogue of compound 38 is compound 39.", "SAR; Table 8", "aniline 3-position", "chlorine", "fluorine"),
        *[edge("1", "38", str(number), 9, f"Pyrrolidine-linker substitution of compound 38 produced compound {number}.", "SAR; Table 10", "covalent-linker pyrrolidine", "unsubstituted pyrrolidine", "Table 10 substituted pyrrolidine", status="figure_explicit") for number in range(43, 48)],
        *[edge("1", "38", str(number), 10, f"Covalent-warhead modification of compound 38 produced compound {number}.", "SAR; Table 11", "covalent warhead", "acrylamide", "Table 11 warhead", status="figure_explicit") for number in range(48, 53)],
        edge("1", "1", "S1", 6, "Compound S1 is the R enantiomer of compound 1.", "Stereochemical review; Table 4", "pyrrololactam stereocenter", "compound-1 stereoisomer", "R enantiomer", relation="stereoisomer_resolution"),
        edge("1", "47", "53", 10, "Combining the methyl-pyrrolidine linker of compound 47 with the optimized warhead produced compound 53.", "SAR; Table 12", "covalent warhead", "compound-47 warhead", "beta-dimethylamino acrylamide"),
        edge("1", "50", "53", 10, "Combining the beta-dimethylamino acrylamide of compound 50 with the optimized linker produced compound 53.", "SAR; Table 12", "pyrrolidine linker", "compound-50 linker", "methyl-pyrrolidine"),
    ]
    annotations["bf54bac4775b"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c02377", "1", stx_labels, stx_edges,
        "Patent-series compound 1 is the root. The hinge, aniline, pyrrololactam, covalent-linker, warhead, and final combination branches follow article-defined tables. S2-S10 remain unresolved and stereochemical assignments require source-level caution.",
        "jm4c02377_si_002.csv", names={"53": "STX-721"}, origins={"1": "prior_art"},
    )

    rorgt_labels = [*_prefixed("A", 1, 9), *_prefixed("B", 1, 6), *_prefixed("C", 1, 13), *_prefixed("D", 1, 20)]
    rorgt_edges = [
        edge("A1", "A1", "A2", 2, "Moving the position-3 methyl group of A1 to position 2 produced compound A2.", "Section 2.1; Table 1", "tetrahydroquinoline methyl position", "3-methyl", "2-methyl", relation="substituent_transposition"),
        edge("A1", "A1", "A3", 2, "Moving the position-3 methyl group of A1 to position 4 produced compound A3.", "Section 2.1; Table 1", "tetrahydroquinoline methyl position", "3-methyl", "4-methyl", relation="substituent_transposition"),
        edge("A1", "A6", "A9", 4, "Heterocyclic modification of benzene ring A of compound A6 produced compound A9.", "SAR; Table 1", "benzene ring A", "benzene", "aza-heterocycle", relation="ring_replacement"),
        *[edge("A1", "A1", f"D{number}", 5, f"Starting from A1, the authors designed and synthesized compound D{number} as part of the 20-member D1-D20 analogue series.", "Section 2.1; Table 4", "tetrahydroquinoline R4 region", "A1 group", "Table 4 group", status="text_explicit") for number in range(1, 21)],
        edge("A1", "D4", "(R)-D4", 6, "Chiral separation of compound D4 furnished the individually assigned (R)-D4 enantiomer.", "Section 2.3; Figure 5A; Table 5", "D4 tetrahydroquinoline stereocenter", "racemic D4", "(R)-D4", relation="stereoisomer_resolution"),
        edge("A1", "D4", "(S)-D4", 6, "Chiral separation of compound D4 furnished the individually assigned (S)-D4 enantiomer.", "Section 2.3; Figure 5A; Table 5", "D4 tetrahydroquinoline stereocenter", "racemic D4", "(S)-D4", relation="stereoisomer_resolution"),
    ]
    annotations["feef9e819b88"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01727", "A1", rorgt_labels, rorgt_edges,
        "A1 anchors the A2/A3 methyl transpositions and the explicitly A1-rooted D1-D20 series; A6-to-A9 is a direct heterocycle comparison. A4-A8 where not otherwise stated, and the B/C scans, remain unresolved. D4 was assayed as a racemate and its machine SMILES has unassigned stereochemistry; the separately resolved (R)-D4 and (S)-D4 entities must remain distinct and cannot inherit that row.",
        "jm4c01727_si_002.csv", names={"D4": "lead D4", "(R)-D4": "(R)-D4", "(S)-D4": "(S)-D4"},
    )

    atr_edges = [
        edge("AZ20", "16", "36", 4, "Replacement of the 4-substituted indole analogue 16 with the 5-substituted indole analogue produced compound 36.", "SAR; Table 4", "indole substitution position", "4-substituted", "5-substituted", relation="substituent_transposition"),
        edge("AZ20", "36", "37", 4, "Insertion of a ring nitrogen into the 5-substituted indole scaffold 36 gave compound 37.", "SAR; Table 4", "5-substituted indole scaffold", "indole carbon", "ring nitrogen", relation="ring_aza_substitution"),
        edge("AZ20", "36", "38", 4, "Insertion of a ring nitrogen into the 5-substituted indole scaffold 36 gave compound 38.", "SAR; Table 4", "5-substituted indole scaffold", "indole carbon", "ring nitrogen", relation="ring_aza_substitution"),
    ]
    annotations["2a98b0589a08"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00734", "AZ20", _numbers(1, 42), atr_edges,
        "AZ20 is the prior-art design template. The 16-to-36 positional replacement and 36-to-37/38 aza-scaffold edits are explicit; the remaining numbered series lacks unique immediate-parent wording in the reviewed text.",
        "jm4c00734_si_002.csv", names={"AD1058": "AD1058", "AD1091": "AD1091"}, origins={"AZ20": "prior_art"},
    )

    p2x_labels = [f"{prefix}{suffix}" for prefix, suffixes in [(4, "abcdefghi"), (5, "abcdefghi"), (8, "abcdefgh"), (9, "abcdefgh"), (13, "abcd")] for suffix in suffixes]
    p2x_edges = [
        *[edge("6", "6", f"8{x}", 4, f"Suzuki or Buchwald replacement of the para bromide of prior compound 6 produced compound 8{x}.", "SAR; Scheme 2; Tables 1-3", "pyridine para substituent", "bromine", "Table substituent", status="figure_explicit") for x in "bcdefgh"],
        *[edge("6", "7", f"9{x}", 4, f"Suzuki or Buchwald replacement of the para bromide of prior compound 7 produced compound 9{x}.", "SAR; Scheme 2; Tables 1-3", "pyridine para substituent", "bromine", "Table substituent", status="figure_explicit") for x in "bcdefgh"],
        edge("6", "4i", "8a", 5, "Replacing the para methyl group of compound 4i with trifluoromethyl produced compound 8a.", "SAR; Table 2", "pyridine para substituent", "methyl", "trifluoromethyl"),
        edge("6", "5i", "9a", 5, "Replacing the para methyl group of compound 5i with trifluoromethyl produced compound 9a.", "SAR; Table 2", "pyridine para substituent", "methyl", "trifluoromethyl"),
    ]
    annotations["c958fce90ec5"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01395", "6", p2x_labels, p2x_edges,
        "Prior compounds 6 and 7 are the two bromide templates for the parallel 8/9 branches. The 4i/5i methyl-to-CF3 comparisons are explicit; methyl-linker 13a-d members remain unresolved.",
        "jm4c01395_si_001.csv", origins={"6": "prior_art", "7": "prior_art"},
    )

    crm_edges = [
        edge("KPT-8602", "KPT-8602", "A2", 3, "Replacement of the pyrimidinyl group of KPT-8602 with pyridine-4-yl produced compound A2.", "SAR; Table 1", "terminal heteroaryl", "pyrimidinyl", "pyridine-4-yl", relation="ring_replacement"),
        edge("KPT-8602", "A5", "A7", 3, "Replacement of the trifluoromethyl group of A5 with methyl produced compound A7.", "SAR; Table 1", "heteroaryl substituent", "trifluoromethyl", "methyl"),
        *[edge("KPT-8602", "KPT-8602", label, 3, f"Modification of the pyrimidine region of KPT-8602 produced compound {label}.", "SAR; Table 1", "pyrimidine region", "KPT-8602 group", "reported replacement", status="text_explicit") for label in ["A9", "A10", "A11", "A12"]],
        edge("KPT-8602", "A37", "A38", 6, "Replacement of the methoxy group of SZJK-0421 (A37) with ethoxy produced compound A38.", "SAR; Table 3", "amide N-alkoxy group", "methoxy", "ethoxy"),
        edge("KPT-8602", "A37", "A39", 6, "N-methyl substitution of SZJK-0421 (A37) produced compound A39.", "SAR; Table 3", "amide nitrogen", "hydrogen", "methyl"),
        edge("KPT-8602", "A37", "A41", 6, "Replacement of the amide of SZJK-0421 (A37) with formamide produced compound A41.", "SAR; Table 3", "amide substituent", "O-methylhydroxamate", "formamide"),
        edge("KPT-8602", "A52", "A54", 6, "Introduction of a ring nitrogen meta to the 4-cyanophenyl group of A52 produced compound A54.", "SAR; Table 3", "4-cyanophenyl ring", "carbon", "ring nitrogen", relation="ring_aza_substitution"),
        edge("KPT-8602", "A54", "A55", 6, "Replacement of the cyano group of A54 with methoxy produced compound A55.", "SAR; Table 3", "heteroaryl substituent", "cyano", "methoxy"),
    ]
    annotations["e4043323f96c"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c02169", "KPT-8602", _prefixed("A", 1, 63), crm_edges,
        "KPT-8602 is the prior template and A37 is explicitly SZJK-0421. Only stated heteroaryl, hydroxamate, and A52/A54 edits are direct; all other A-series members remain unresolved.",
        "jm4c02169_si_004.csv", names={"A37": "SZJK-0421", "KPT-8602": "eltanexor"}, origins={"KPT-8602": "prior_art"},
    )

    nsun_labels = [*_prefixed("A", 1, 27), *_prefixed("B", 1, 39), "Bio-B8", *_prefixed("C", 1, 24), "P1"]
    annotations["65e19df86a4a"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01323", "B8", nsun_labels,
        [edge("B8", "B8", "Bio-B8", 7, "Biotin conjugation of compound B8 produced Bio-B8 for target fishing.", "Chemical biology; Scheme 4", "probe attachment site", "hydrogen", "biotin linker", relation="probe_conjugation", status="figure_explicit")],
        "B8 is the selected active chemical-biology template. Its Bio-B8 probe is direct; the A-C SAR tables and P1 photoaffinity probe are retained unresolved because the source does not state one unique immediate molecular parent for each.",
        "jm4c01323_si_002.csv", names={"Bio-B8": "biotinylated B8", "P1": "photoaffinity probe P1"},
    )

    enpp_edges = [
        *[edge("8", "8", str(number), 4, f"Replacement of the piperidine linker of lead compound 8 produced compound {number}.", "SAR; Table 2", "linker ring", "piperidine", "reported linker", status="figure_explicit") for number in range(14, 19)],
        *[edge("8", "8", str(number), 5, f"Replacement of the piperidine linker of lead compound 8 with a benzene-containing linker produced compound {number}.", "SAR; Table 2", "linker", "piperidine", "benzene-containing linker", status="figure_explicit") for number in range(20, 23)],
        edge("8", "8", "25", 5, "Introduction of a methyl group at the 4-position of the piperidine of compound 8 produced compound 25.", "SAR; Table 2", "piperidine 4-position", "hydrogen", "methyl"),
        edge("8", "8", "29", 5, "Introduction of a trifluoromethyl group into compound 8 produced compound 29.", "SAR; Table 2", "linker substituent", "hydrogen", "trifluoromethyl"),
        *[edge("8", "8", str(number), 5, f"Replacement of the piperidine of compound 8 with a conformationally constrained linker produced compound {number}.", "SAR; Table 2", "linker ring", "piperidine", "constrained bicyclic/spiro linker", status="figure_explicit") for number in [30, 31]],
    ]
    annotations["cab92325187b"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c02288", "8", _numbers(8, 31), enpp_edges,
        "Compound 8 is the explicit hit/lead. The piperidine replacement, 4-methyl, CF3, and constrained-linker comparisons are direct; remaining scaffold/linker members are unresolved.",
        "jm3c02288_si_005.csv",
    )

    malaria_edges = [
        edge("1", "1", "6", 2, "Removal of the thiophene group from compound 1 produced pyridine compound 6.", "SAR; Table 2", "thiophenylpyridine head", "thiophene-pyridine", "pyridine", relation="substituent_deletion"),
        edge("1", "6", "7", 2, "Replacement of the pyridine ring of compound 6 with piperazine produced compound 7.", "SAR; Table 2", "heterocyclic head", "pyridine", "piperazine", relation="ring_replacement"),
        edge("1", "6", "8", 2, "Removal of the pyridine nitrogen of compound 6 produced phenyl compound 8.", "SAR; Table 2", "heterocyclic head", "pyridine", "phenyl", relation="ring_deaza_substitution"),
        edge("1", "1", "9", 2, "Removal of the pyridine nitrogen from thiophenylpyridine compound 1 produced phenylthiophene compound 9.", "SAR; Table 2", "thiophenylpyridine head", "thiophenylpyridine", "phenylthiophene", relation="ring_deaza_substitution"),
        *[edge("1", "1", label, 3, f"Replacement of the central-ring 3-chloro group of compound 1 produced compound {label}.", "SAR; Table 3", "central-ring chloro position", "3-chloro", "reported replacement", status="figure_explicit") for label in ["24", "25", "31", "32", "33"]],
        edge("1", "29", "30", 4, "Moving the pyridine nitrogen from the ortho position in compound 29 to the meta position produced compound 30.", "SAR; Table 3", "central pyridine nitrogen", "ortho", "meta", relation="ring_nitrogen_transposition"),
    ]
    annotations["8e421ecc451e"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c02046", "1", _numbers(1, 33), malaria_edges,
        "Compound 1 is the identified antimalarial lead. Head-group removals/replacements, selected central 3-Cl replacements, and the 29-to-30 nitrogen transposition are direct; the rest remain unresolved.",
        "jm3c02046_si_002.csv",
    )

    vhl_edges = [
        edge("VH032", "VH032", "VH-021", 11, "Introduction of a benzylic methyl group into VH032 produced VH-021.", "Figure 2a; late-stage optimization", "RHS benzylic position", "hydrogen", "methyl"),
        edge("VH032", "VH032", "5", 3, "Replacement of the VH032 4-methylthiazole with the phenyl group of d-biphenylalanine produced compound 5.", "Design; Figure 3", "RHS methylthiazole", "4-methylthiazole", "phenyl", relation="heteroaryl_replacement"),
        edge("VH032", "5", "32", 4, "Introduction of an S alpha-methyl group into parent compound 5 produced compound 32.", "SAR; Table 2", "LHS side-chain alpha carbon", "hydrogen", "S-methyl"),
        edge("VH032", "51", "53", 5, "Introduction of a beta branch into compound 51 produced the matched compound 53.", "SAR; Table 2", "LHS side-chain beta carbon", "hydrogen", "branch", status="figure_explicit"),
    ]
    annotations["07dcad0214c3"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c02203", "VH032", [*_numbers(1, 107), "VH-021", "VH032"], vhl_edges,
        "VH032 is the prior VHL ligand and compound 5 the stated dBip parent for the systematic campaign. Only source-explicit matched edits are direct; combinatorial R1/R2/R3 libraries and assembled compounds 104-107 remain unresolved.",
        "jm3c02203_si_002.csv", names={"107": "GNE7599"}, origins={"VH032": "prior_art", "VH-021": "prior_art"},
    )

    polrmt_edges = [
        *[edge("IMT1B", "IMT1B", f"M{number}", 3, f"Substitution on the coumarin scaffold of IMT1B produced compound M{number}.", "SAR; Table 1", "coumarin ring", "hydrogen", "Table 1 substituent", status="figure_explicit") for number in range(1, 7)],
        *[edge("IMT1B", "M4", f"Q{number}", 3, f"Optimization of the R2 moiety of fluorinated coumarin M4 produced compound Q{number}.", "SAR; Table 2", "R2 amide moiety", "M4 group", "Table 2 group", status="figure_explicit") for number in range(1, 17)],
        *[edge("IMT1B", "Q15", f"S{number}", 4, f"Hydrophobic-moiety substitution of the favorable Q15 scaffold produced compound S{number}.", "SAR; Table 3", "R3 hydrophobic aryl", "Q15 aryl", "Table 3 aryl", status="figure_explicit", confidence="medium") for number in range(1, 9)],
    ]
    annotations["7e503b3382bf"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c01178", "IMT1B", ["IMT1B", *_prefixed("M", 1, 6), *_prefixed("Q", 1, 16), *_prefixed("S", 1, 8)], polrmt_edges,
        "IMT1B anchors the coumarin-position scan, M4 the fluorinated R2 scan, and Q15 the retained amide for the hydrophobic S series. The `Compd.` source labels are now bound exactly.",
        "jm4c01178_si_002.csv", origins={"IMT1B": "prior_art"},
    )

    lsd_labels = [f"3{x}" for x in [*"abcdefghijklmnopqrstuvwxyz", *["aa", "ab", "ac", "ad", "ae", "af", "ag", "ah", "ai", "aj", "ak", "al", "am", "an", "ao", "ap", "aq", "ar", "as", "at", "au", "av", "aw", "ax", "ay"]]] + ["Erlotinib", "ORY-1001"]
    lsd_edges = [
        edge("Erlotinib", "Erlotinib", "3a", 4, "Replacement of erlotinib's meta-aminobenzyl acetylene with N,N-dimethyl-o-phenylenediamine produced compound 3a.", "SAR; Table 1", "quinazoline 4-position substituent", "meta-aminobenzyl acetylene", "N,N-dimethyl-o-phenylenediamine"),
        edge("Erlotinib", "3a", "3b", 4, "Elimination of the long chains at the 6- and 7-positions of compound 3a produced compound 3b.", "SAR; Table 1", "quinazoline 6/7 positions", "long chains", "hydrogen", relation="substituent_deletion"),
        *[edge("Erlotinib", "3ap", label, 4 if label in ["3aq", "3ar"] else 5, f"Further structural optimization of Z-1 (3ap) produced compound {label}.", "SAR; Tables 3-4", "Z-1 aromatic/substituent region", "Z-1 group", "reported replacement", status="figure_explicit") for label in ["3aq", "3ar", "3as", "3at", "3au", "3av", "3aw", "3ax", "3ay"]],
    ]
    annotations["4bd630dc5dc8"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00972", "Erlotinib", lsd_labels, lsd_edges,
        "Erlotinib is the explicit lead, 3a/3b are sequential lead edits, and Z-1 (3ap) anchors the final optimization. Other 3-series table members remain unresolved.",
        "jm4c00972_si_002.csv", names={"3ap": "Z-1", "3am": "Z-2"}, origins={"Erlotinib": "prior_art", "ORY-1001": "prior_art"},
    )

    nlrp_edges = [
        *[edge("IAL", "IAL", str(number), 3, f"Modification of the alpha-methylene-gamma-butyrolactone moiety of IAL produced compound {number}.", "SAR; Scheme 1", "alpha-methylene-gamma-butyrolactone", "IAL motif", "reported modification", status="figure_explicit") for number in range(1, 4)],
        *[edge("IAL", "5", str(number), 5, f"C3 derivatization of compound 5 produced compound {number} in the designed series.", "SAR; Figure 2; Tables 1-2", "C3 hydroxyl", "hydroxyl", "reported C3 group", status="figure_explicit") for number in range(9, 27)],
        *[edge("IAL", "27", str(number), 7, f"Replacement of the phenyl ring of compound 27 with a six-membered heteroaryl ring produced compound {number}.", "SAR; Table 4", "C3 ester aryl", "phenyl", "heteroaryl", relation="ring_replacement", status="figure_explicit") for number in range(36, 51)],
        edge("IAL", "20", "59", 8, "The C3 ester linkage of compound 20 was replaced by an amide to give compound 59, whose inhibition was compared directly with compound 20.", "SAR; Table 5", "C3 linkage", "ester", "amide", relation="linker_bioisostere"),
        edge("IAL", "54", "63", 9, "Compounds 63 and 64 retained potency comparable to 54 and 55, respectively, after the stated C3 ester-to-amide replacement.", "SAR; Table 5", "C3 linkage", "ester", "amide", relation="linker_bioisostere"),
        edge("IAL", "55", "64", 9, "Compounds 63 and 64 retained potency comparable to 54 and 55, respectively, after the stated C3 ester-to-amide replacement.", "SAR; Table 5", "C3 linkage", "ester", "amide", relation="linker_bioisostere"),
    ]
    annotations["2d5a56fffb44"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00357", "IAL", [*_numbers(1, 64), "IAL"], nlrp_edges,
        "IAL is the natural-product root and compound 5 the C3 design template. The IAL motif edits, compound-5 C3 set, compound-27 heteroaryl replacements, and source-mapped 20-to-59, 54-to-63, and 55-to-64 ester-to-amide pairs are direct. The grouped 28/29/49 and 60-62 ranges lack an explicit one-to-one mapping and remain unresolved.",
        "jm4c00357_si_002.csv", names={"IAL": "isoalantolactone"}, origins={"IAL": "natural_product"},
    )

    mcl_edges = [
        *[edge("4", "4", str(number), 4, f"The first P1/P3 occupation design based on lead compound 4 produced compound {number}.", "SAR; Table 1; Figure 3", "P1/P3 hydrophobic groups", "lead-4 groups", "Table 1 groups", status="figure_explicit", confidence="medium") for number in range(5, 19)],
        edge("4", "20", "21", 5, "Introduction of the 1H-indol-1-yl group into compound 20 produced compound 21.", "SAR; Table 2", "P1 hydrophobic group", "parent group", "1H-indol-1-yl"),
        edge("4", "21", "22", 5, "Introduction of 2-ethylmorpholine into compound 21 produced compound 22.", "SAR; Table 2", "solvent-exposed substituent", "hydrogen", "2-ethylmorpholine"),
    ]
    annotations["c6c61d0fc737"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00643", "4", _numbers(5, 47), mcl_edges,
        "Lead compound 4 anchors the figure-defined first design. Compound 12 motivated a broader second design round, but the source does not assign one immediate parent to each member of 20-47; those members remain unresolved except for the explicit 20-to-21 and 21-to-22 comparisons.",
        "jm4c00643_si_002.csv", origins={"4": "prior_art"},
    )

    egfr_labels = [*_prefixed("14", 0, 0)]
    egfr_labels = [f"14{x}" for x in "abcdefghijklmnop"] + [f"15{x}" for x in "abc"] + [f"20{x}" for x in "abcdefghijklmnop"] + [f"21{x}" for x in "abcdefghij"]
    egfr_edges = [
        *[edge("9", "9", f"14{x}", 4, f"Substitution at the 2-position of the retained aminoquinazoline core of lead compound 9 produced compound 14{x}.", "SAR; Table 1", "aminoquinazoline 2-position", "lead-9 group", "Table 1 group", status="figure_explicit", confidence="medium") for x in "abcdefghijklmnop"],
        *[edge("9", "14j", f"20{x}", 6, f"Core substitution of the follow-up lead 14j produced compound 20{x}.", "SAR; Table 3", "aminoquinazoline 6-position", "chlorine", "Table 3 substituent", status="figure_explicit") for x in "abcdefghijklmnop"],
        *[edge("9", "14j", f"21{x}", 7, f"Pyrazole N-substituent optimization of follow-up lead 14j produced compound 21{x}.", "SAR; Table 4", "1-methylpyrazole N-substituent", "methyl", "Table 4 alkyl", status="figure_explicit", confidence="medium") for x in "abcdefghij"],
    ]
    annotations["096b579fa25f"] = _reviewed_record(
        "10.1021/acs.jmedchem.3c01934", "9", egfr_labels, egfr_edges,
        "Docking hit 9 is the first lead and 14j the explicitly selected follow-up lead. Their table-defined 14, 20, and 21 branches are retained; the 15 warhead-position series remains unresolved.",
        "jm3c01934_si_005.csv", names={"21a": "lead compound 21a"}, origins={"9": "virtual_screen_hit"},
    )

    smip_labels = [f"SMIP-{number:03d}" for number in [*range(1, 30), *range(31, 39)]]
    smip_edges = [
        *[edge("SMIP-30", "SMIP-30", f"SMIP-{number:03d}", 5, f"Part-I substitution based on SMIP-30 produced compound SMIP-{number:03d}.", "SAR; Table 1", "Part I R1/R2 substituent", "SMIP-30 groups", "Table 1 groups", status="figure_explicit", confidence="medium") for number in range(3, 10)],
        *[edge("SMIP-30", "SMIP-30", f"SMIP-{number:03d}", 5, f"N-substituent optimization based on SMIP-30 produced compound SMIP-{number:03d}.", "SAR; Table 2", "Part II N-substituent", "SMIP-30 group", "Table 2 group", status="figure_explicit", confidence="medium") for number in range(10, 17)],
        edge("SMIP-30", "SMIP-30", "SMIP-020", 6, "Introduction of a para-methoxyphenyl group at R4 of SMIP-30 produced compound SMIP-020.", "SAR; Table 3", "R4", "hydrogen", "4-methoxyphenyl"),
        edge("SMIP-30", "SMIP-30", "SMIP-031", 6, "Replacement of the R5 methoxy group of SMIP-30 with ethoxy produced compound SMIP-031.", "SAR; Table 4", "R5", "methoxy", "ethoxy"),
        edge("SMIP-30", "SMIP-30", "SMIP-036", 6, "Replacement of the R5 methoxy group of SMIP-30 with trifluoromethoxy produced compound SMIP-036.", "SAR; Table 4", "R5", "methoxy", "trifluoromethoxy"),
    ]
    annotations["023145d60eea"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c00513", "SMIP-30", smip_labels, smip_edges,
        "Prior lead SMIP-30 anchors the Part I/II and selected R4/R5 edits. Machine rows are quaternary ammonium bromide salts; counterion removal requires explicit component-selection review before confirmation.",
        "jm4c00513_si_005.csv", names={"SMIP-031": "SMIP-031"}, origins={"SMIP-30": "prior_art"},
    )

    fgfr_labels = [*_numbers(1, 27), *_prefixed("A", 1, 7), "RE1"]
    fgfr_edges = [
        edge("A4", "A4", "A6", 3, "Replacement of pyridine at the X position of compound A4 with pyrimidine produced compound A6.", "Early SAR; Table 1", "hinge heterocycle X", "pyridine", "pyrimidine", relation="ring_replacement"),
        edge("A4", "3", "4", 4, "Introduction of a terminal methyl group on the acetylene of compound 3 produced compound 4.", "Warhead SAR; Table 2", "terminal acetylene", "hydrogen", "methyl"),
        *[edge("A4", "10", str(number), 5, f"Substitution near the FGFR hinge of compound 10 produced compound {number}.", "SAR; Table 3", "hinge-region R position", "hydrogen", "reported substituent", status="figure_explicit") for number in range(19, 24)],
        edge("A4", "20", "24", 6, "Introduction of fluorine at R3 of compound 20 produced compound 24.", "SAR; Table 3", "R3", "hydrogen", "fluorine"),
        edge("A4", "20", "25", 6, "Introduction of methyl at R3 of compound 20 produced compound 25.", "SAR; Table 3", "R3", "hydrogen", "methyl"),
    ]
    annotations["b09de250fcb3"] = _reviewed_record(
        "10.1021/acs.jmedchem.4c03205", "A4", fgfr_labels, fgfr_edges,
        "A4 anchors the early hinge series and compound 10 the reported optimized warhead scaffold. Only the explicit A4-to-A6, 3-to-4, and compound-10/20 substituent comparisons are direct.",
        "jm4c03205_si_002.csv", origins={"RE1": "prior_art"},
    )

    if set(annotations) != {paper_id for paper_id, _ in BATCH_06_PAPERS}:
        raise ValueError("Batch 06 annotation coverage does not match fixed scope")
    return annotations


def write_annotations(output_dir: Path = ANNOTATION_DIR) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for paper_id, payload in build_annotations().items():
        output = output_dir / f"{paper_id}.json"
        output.write_text(
            json.dumps(
                {"paper_id": paper_id, **payload},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        paths.append(output)
    return paths


def main() -> None:
    validate_batch_selection()
    for path in write_annotations():
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"{path.stem}: {len(payload['edges'])} edges")
    print(f"wrote {len(BATCH_06_PAPERS)} batch-06 annotation files")


if __name__ == "__main__":
    main()
