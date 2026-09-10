#!/usr/bin/env python3
"""Generate conservative Paper-local lineage annotations for Batch 05.

The fixed batch boundary is declared before any annotation or aggregate write.
Later sections of this module add only source-backed direct relationships;
series membership without a unique immediate parent remains unresolved.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTO_FILL_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill"
ANNOTATION_DIR = AUTO_FILL_DIR / "lineage_annotations"
BATCH_05_VERSION = "compound_lineages_v1_2026-09-09-batch05"
MISSING = "--"

BATCH_05_PAPERS: tuple[tuple[str, str], ...] = (
    ("a1d7361647de", "10.1021/acs.jmedchem.4c01072"),
    ("9fc4e02fbcdb", "10.1021/acs.jmedchem.4c01766"),
    ("8968e9a60ef9", "10.1021/acs.jmedchem.3c01920"),
    ("e64c071652ca", "10.1021/acs.jmedchem.4c01464"),
    ("ba6944db3fe2", "10.1021/acs.jmedchem.4c01760"),
    ("23fa35c9b113", "10.1021/acs.jmedchem.4c01048"),
    ("5589366efa06", "10.1021/acs.jmedchem.4c02531"),
    ("f2e855803f5a", "10.1021/acs.jmedchem.4c01787"),
    ("8b306e91bc78", "10.1021/acs.jmedchem.3c01790"),
    ("1a7457834b7a", "10.1021/acs.jmedchem.4c01851"),
    ("cfc4a0d0ef41", "10.1021/acs.jmedchem.4c01221"),
    ("a797514debbc", "10.1021/acs.jmedchem.4c01303"),
    ("d168508d74ca", "10.1021/acs.jmedchem.4c01092"),
    ("0eb39d3b45ae", "10.1021/acs.jmedchem.4c01568"),
    ("f501045da21f", "10.1021/acs.jmedchem.4c01283"),
    ("c6fdd5c7e071", "10.1021/acs.jmedchem.3c02246"),
    ("2f3a5d2f7fb0", "10.1021/acs.jmedchem.3c01961"),
    ("83d4f2ab5b7c", "10.1021/acs.jmedchem.3c02473"),
    ("dfe42148eabf", "10.1021/acs.jmedchem.3c01976"),
    ("14c9ce88d1c2", "10.1021/acs.jmedchem.4c02093"),
    ("5531836ee3c3", "10.1021/acs.jmedchem.3c02460"),
    ("1535ba2a9a58", "10.1021/acs.jmedchem.4c00860"),
    ("c3b3eba1f5b3", "10.1021/acs.jmedchem.3c01347"),
    ("df798aa2ca88", "10.1021/acs.jmedchem.4c00856"),
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
    """Reject a duplicate or previously owned Batch 05 Paper/DOI boundary.

    The validation remains reusable after publication: a selected Paper already
    present in the aggregate is accepted only when its own annotation carries
    the Batch 05 version. A duplicate DOI owned by another Paper is always an
    error.
    """
    if len(BATCH_05_PAPERS) != 24:
        raise ValueError("Batch 05 must contain exactly 24 Papers")
    selected = dict(BATCH_05_PAPERS)
    if len(selected) != len(BATCH_05_PAPERS):
        raise ValueError("Batch 05 contains duplicate Paper IDs")
    selected_dois = {_normalize_doi(doi) for doi in selected.values()}
    if "" in selected_dois or len(selected_dois) != len(selected):
        raise ValueError("Batch 05 contains blank or duplicate DOIs")

    own_annotations: set[str] = set()
    for path in Path(annotation_dir).glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unreadable lineage annotation: {path}") from error
        paper_id = str(payload.get("paper_id") or path.stem)
        doi = _normalize_doi(payload.get("doi"))
        if paper_id in selected:
            if payload.get("annotation_version") != BATCH_05_VERSION:
                raise ValueError(
                    f"Batch 05 Paper already belongs to another annotation: {paper_id}"
                )
            if doi != _normalize_doi(selected[paper_id]):
                raise ValueError(f"Batch 05 annotation DOI mismatch: {paper_id}")
            own_annotations.add(paper_id)
        elif doi in selected_dois:
            raise ValueError(
                f"Batch 05 DOI is already owned by another Paper: {doi}"
            )

    aggregate_selected_ids: set[str] = set()
    for row in _read_csv(Path(entities_path)):
        paper_id = str(row.get("paper_id") or "")
        doi = _normalize_doi(row.get("doi"))
        if paper_id in selected:
            aggregate_selected_ids.add(paper_id)
        elif doi in selected_dois:
            raise ValueError(
                f"Batch 05 DOI is already present under another Paper: {doi}"
            )
    unpublished_conflicts = aggregate_selected_ids - own_annotations
    if unpublished_conflicts:
        raise ValueError(
            "Batch 05 Paper was already published before its annotation: "
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
        "annotation_version": BATCH_05_VERSION,
    }


def _peptide_substitution(
    derived: str,
    site: str,
    old: str,
    new: str,
) -> dict[str, object]:
    return edge(
        "0",
        "0",
        derived,
        4,
        f"Table 1 identifies compound 0 as the parent peptide and compound {derived} as the {new} substitution analogue.",
        "Table 1: calcium-mobilization functional activity",
        site,
        old,
        new,
        relation="amino_acid_substitution",
        status="figure_explicit",
    )


def _gpr52_edge(
    parent: str,
    derived: str,
    page: int,
    summary: str,
    site: str,
    old: str,
    new: str,
    *,
    relation: str = "substituent_replacement",
) -> dict[str, object]:
    return edge(
        "4a",
        parent,
        derived,
        page,
        f"Compound {derived}: {summary}",
        "GPR52 SAR; Tables 1-3 and Figure 2",
        site,
        old,
        new,
        relation=relation,
    )


def build_annotations() -> dict[str, dict[str, object]]:
    """Return reviewed annotations accumulated for the fixed Batch 05 scope."""
    return {
        "a1d7361647de": record(
            "10.1021/acs.jmedchem.4c01072",
            [
                edge("1", "1", "3", 3, "Compound 3, obtained by removing OCF3 from compound 1, was chosen as the starting compound for structural modification.", "SAR; Figure 2", "phenyl substituent", "OCF3", "hydrogen", relation="substituent_deletion"),
                *series("3", ["4", "5", "6", "7", "8"], 3, "Compounds 4-8 comprise the pyrazole-region substitution and ring scan around starting compound 3; the text does not uniquely specify every immediate comparison.", "SAR; Table 1"),
                *series("3", ["9", "10", "11", "12", "13", "14", "15", "17", "18"], 3, "Compounds 9-18 comprise the linker-region scan around starting compound 3; the text does not uniquely identify an immediate parent for every table member.", "SAR; Table 2"),
                edge("1", "3", "16", 3, "Exchanging the position of methylene and oxygen in the linker of compound 3 provided compound 16.", "SAR; Table 2", "ether linker", "methylene-oxygen order", "oxygen-methylene order", relation="linker_atom_transposition"),
                *series("3", [str(number) for number in range(19, 38)], 3, "Various single substituents were introduced on the phenyl group to generate compounds 19-37 from the compound 3 optimization campaign; the source passage does not identify a unique immediate parent for every member.", "SAR; Tables 3-4"),
                *series("3", [str(number) for number in range(38, 54)], 4, "Compounds 38-53 are the di- or tri-substituted benzene series; a unique immediate parent for each member is not stated.", "SAR; Table 4"),
                *series("29", ["29E", "54", "55", "56", "57", "58"], 6, "The carboxylic acid of compound 29 was derivatized through substitution or condensation in the prodrug series, but the reviewed text does not uniquely enumerate the precise parent mapping for every label.", "SAR; Table 5"),
            ],
            "Compound 1-to-3 and 3-to-16 are explicit. Broad pyrazole, linker, phenyl, and prodrug table scans stay unresolved where the immediate relation is not uniquely stated. The machine structure table provides complete single-component structures for labels 4-58 and 29E, but not the prior-art compound 1 or starting compound 3.",
            source_files={"machine_structure_table": "48985318_jm4c01072_si_002.csv"},
        ),
        "9fc4e02fbcdb": record(
            "10.1021/acs.jmedchem.4c01766",
            [
                *series("25", ["22", "23", "24", "25", "26"], 4, "The initial fused and phenylquinoline SAR identified the 7-urea-substituted compound 25 as the scaffold retained for C-ring modification, but one immediate parent for every initial member is not stated.", "SAR; Tables 1-2"),
                *series("25", [str(number) for number in range(29, 44) if number != 39], 4, "The 7-substituted phenylquinoline moiety of compound 25 was retained while C-ring substituents were modified to generate the 29-43 series; individual immediate parent assignments are not stated.", "SAR; Scheme 4; Table 2"),
                edge("25", "29", "56", 6, "Extending the methylene linker of compound 29 to an ethylene spacer gave compound 56.", "SAR; Table 3", "urea-side linker", "methylene", "ethylene", relation="linker_extension"),
                edge("25", "29", "57", 6, "Substituting the methylene linker of compound 29 with its NH bioisostere gave compound 57.", "SAR; Table 3", "urea-side linker", "methylene", "NH", relation="linker_bioisostere"),
                edge("25", "29", "77", 6, "Replacing the urea of compound 29 with the extended squaramide bioisostere gave compound 77.", "SAR; Table 4", "central urea", "urea", "squaramide", relation="linker_bioisostere"),
                edge("25", "59", "78", 6, "Replacing the urea of compound 59 with the extended squaramide bioisostere gave compound 78.", "SAR; Table 4", "central urea", "urea", "squaramide", relation="linker_bioisostere"),
                *series("29", [str(number) for number in range(47, 76)], 5, "A diverse array of urea substituents was introduced based on compound 29 to yield compounds 47-75, but the article does not identify a unique stepwise immediate parent for every member.", "SAR; Schemes 5-6; Tables 3-5"),
                edge("25", "74", "75", 8, "Replacement of the 4-pyridine substitution in compound 74 by 2-pyridine gave the corresponding compound 75.", "SAR; Table 5", "urea aryl heterocycle", "4-pyridyl", "2-pyridyl", relation="substituent_transposition", confidence="medium"),
            ],
            "The retained 25 scaffold and broad C-ring/urea scans remain unresolved where immediate mappings are not unique. The 29-to-56/57, 29/59-to-squaramide, and 74-to-75 edits are direct. The machine table covers 75 single-component labelled structures.",
            names={"68": "DJ-53"},
            source_files={"machine_structure_table": "49590154_jm4c01766_si_001.csv"},
        ),
        "8968e9a60ef9": record(
            "10.1021/acs.jmedchem.3c01920",
            [
                *series("DLA", [str(number) for number in range(1, 13)], 6, "The multichiral C9-C14 moiety of DLA was replaced with amino-alcohol R1 and amino-acid R2 combinations in compounds 1-12; the source does not specify one stepwise immediate parent for every member.", "SAR; Tables 1-2; Figure 2"),
                edge("DLA", "2", "6", 6, "Introduction of a 3-amino-2,2-difluoropropan-1-ol substituent into compound 2 gave compound 6.", "SAR; Table 1", "amino-alcohol substituent", "unsubstituted chain", "2,2-difluoro chain", confidence="medium"),
                edge("DLA", "9", "12", 6, "Fluorine substitution on the aromatic ring of compound 9 gave compound 12.", "SAR; Table 1", "aromatic amino-alcohol ring", "hydrogen", "fluorine", confidence="medium"),
                *series("9", ["13", "14", "15"], 6, "Compound 9 was selected for further ring-size modification to give analogues 13-15; the individual chain-length step is not represented as a unique immediate parent.", "SAR; Table 2"),
                *series("11", ["16", "17", "18"], 6, "Compound 11 was selected for further ring-size modification to give analogues 16-18; the individual chain-length step is not represented as a unique immediate parent.", "SAR; Table 2"),
                *series("DLA", [str(number) for number in range(19, 51)], 6, "Compounds 19-50 explore R2/R3 amino-acid and amino-alcohol combinations derived from the DLA simplification strategy, without unique immediate parents for every member.", "SAR; Tables 2-4"),
                *series("DLA", [str(number) for number in range(51, 62)], 6, "Compounds 51-61 explore ring size and linker composition while retaining privileged L-phenylglycinol; the source does not identify a unique immediate parent for each.", "SAR; Tables 4-5"),
            ],
            "The source supports DLA as the root template, explicit 2-to-6 and 9-to-12 comparisons, and two named 9/11 ring-size branches. Other combinatorial macrocycle series remain unresolved. The machine table has 62 parsed numbered structures plus a DLA-like 'DA' row; that spelling mismatch is not automatically bound to DLA.",
            names={"DLA": "dysoxylactam A"},
            origins={"DLA": "prior_art"},
            source_files={"machine_structure_table": "45139553_jm3c01920_si_004.csv"},
        ),
        "e64c071652ca": record(
            "10.1021/acs.jmedchem.4c01464",
            [
                *series("M17-B15", [f"N{number}" for number in range(1, 32)], 5, "The B/C/D moieties of M17-B15 were modified to generate compounds N1-N31; the reviewed text reports regional series but does not identify a unique immediate parent for each compound.", "SAR; Tables 1-3"),
                *[
                    edge("M17-B15", "N29", f"N{number}", 7, f"Further exploration of the benzene-ring substitution pattern of compound N29 generated compound N{number}.", "SAR; Table 4", "benzene-ring substituent", "3-CF3", "Table 4 substitution pattern", relation="phenyl_substitution_scan", confidence="medium")
                    for number in range(32, 44)
                ],
            ],
            "M17-B15 is the prior dimer-interface antagonist and root template. N1-N31 remain unresolved regional SAR records. The article explicitly states that N29 was taken forward for the N32-N43 benzene-ring scan. The machine source contains complete single-component structures for N1-N43 but not M17-B15.",
            names={"M17-B15": "M17-B15"},
            origins={"M17-B15": "prior_art"},
            source_files={"machine_structure_table": "49470628_jm4c01464_si_003.csv"},
        ),
        "23fa35c9b113": record(
            "10.1021/acs.jmedchem.4c01048",
            [
                edge("1", "1", "2a", 3, "Second generation benzoquinone ansamycin derivatives formed by C-17 substitution included 17-AAG, compound 2a.", "Review Scheme 1", "geldanamycin C-17", "methoxy", "allylamino", relation="c17_substitution"),
                edge("1", "1", "2b", 3, "Second generation benzoquinone ansamycin derivatives formed by C-17 substitution included 17-DMAG, compound 2b.", "Review Scheme 1", "geldanamycin C-17", "methoxy", "dimethylaminoethylamino", relation="c17_substitution"),
                edge("1", "1", "2c", 3, "Second generation benzoquinone ansamycin derivatives formed by C-17 substitution included 17-AG, compound 2c.", "Review Scheme 1", "geldanamycin C-17", "methoxy", "amino", relation="c17_substitution"),
                unresolved("1", "13", 7, "The review identifies compound 13 as a naturally occurring C-19 carbon-substituted geldanamycin derivative, but it does not define a Paper-local immediate synthetic parent.", "Review; C-19 natural products"),
                unresolved("1", "19", 8, "The review uses compound 19 for a family of 19-sulfur-substituted geldanamycin derivatives; the variable substituent prevents a unique complete structure and immediate parent assignment.", "Review Scheme 7"),
                unresolved("1", "20", 8, "The review uses compound 20 for a family of 19-sulfur-substituted geldanamycin derivatives; the variable substituent prevents a unique complete structure and immediate parent assignment.", "Review Scheme 7"),
                unresolved("1", "24", 8, "The review uses compound 24 for a range of 19-substituted thiol-adduct derivatives; the variable substituent prevents a unique complete structure and immediate parent assignment.", "Review Scheme 8"),
                unresolved("1", "29", 10, "Compound 29 is the O-benzyloxime example within a C-19 adduct series, but the reviewed passage does not provide a unique immediate parent relationship.", "Review Scheme 9"),
                unresolved("1", "33", 10, "The review uses compound 33 for a variable-R family of 19-carbon-substituted benzoquinone ansamycins; it is not a unique molecular structure.", "Review Schemes 12-13; Figure 8"),
            ],
            "This is a review article rather than one original analogue campaign. Only the explicitly named geldanamycin-to-17-substituted relationships are direct. Generic variable-R scheme numbers remain unresolved and have no confirmable single SMILES. No DOI-matched Figshare attachment was discovered.",
            names={"1": "geldanamycin", "2a": "17-AAG", "2b": "17-DMAG", "2c": "17-AG"},
            origins={"1": "prior_art", "2a": "prior_art", "2b": "prior_art", "2c": "prior_art"},
        ),
        "ba6944db3fe2": record(
            "10.1021/acs.jmedchem.4c01760",
            [
                unresolved("9g", "12b", 7, "Compared to 9f and 9g, derivatives 12b and 12c substituted with chlorine at quinoline position 7 showed improved antibiofilm activity; the sentence does not uniquely map both parents.", "SAR; Table 2"),
                unresolved("9g", "12c", 7, "Compared to 9f and 9g, derivatives 12b and 12c substituted with chlorine at quinoline position 7 showed improved antibiofilm activity; the sentence does not uniquely map both parents.", "SAR; Table 2"),
                edge("9g", "12c", "12i", 8, "Replacement of the chlorine atom at position 7 of the quinoline ring of 12c with trifluoromethyl resulted in compound 12i.", "SAR; Table 2", "quinoline 7-position", "chlorine", "trifluoromethyl"),
                edge("9g", "12c", "12j", 8, "Replacement of the chlorine atom at position 7 of the quinoline ring of 12c with methoxy resulted in compound 12j.", "SAR; Table 2", "quinoline 7-position", "chlorine", "methoxy"),
                edge("9g", "12c", "12g", 8, "Replacement of the chlorine atom at position 7 of the quinoline ring of 12c with fluorine resulted in compound 12g.", "SAR; Table 2", "quinoline 7-position", "chlorine", "fluorine"),
                edge("9g", "12c", "12h", 8, "Replacement of the chlorine atom at position 7 of the quinoline ring of 12c with bromine resulted in compound 12h.", "SAR; Table 2", "quinoline 7-position", "chlorine", "bromine"),
                edge("9g", "9g", "15a", 8, "The quinoline ring in 9g was replaced by a pyridine ring to obtain compound 15a.", "SAR; Table 3", "fused heteroaromatic scaffold", "quinoline", "pyridine", relation="ring_replacement", confidence="medium"),
                edge("9g", "12c", "15b", 8, "The quinoline ring in 12c was replaced by a pyridine ring to obtain compound 15b.", "SAR; Table 3", "fused heteroaromatic scaffold", "quinoline", "pyridine", relation="ring_replacement", confidence="medium"),
                edge("9g", "9g", "30a", 8, "The imino group in the linker of 9g was replaced by an amide bond, yielding compound 30a.", "SAR; Figure 2; Table 3", "linker", "imino", "amide", relation="linker_bioisostere", confidence="medium"),
                edge("9g", "12c", "30b", 8, "The imino group in the linker of 12c was replaced by an amide bond, yielding compound 30b.", "SAR; Figure 2; Table 3", "linker", "imino", "amide", relation="linker_bioisostere", confidence="medium"),
                edge("9g", "12j", "30c", 8, "The imino group in the linker of 12j was replaced by an amide bond, yielding compound 30c.", "SAR; Figure 2; Table 3", "linker", "imino", "amide", relation="linker_bioisostere", confidence="medium"),
                *series("9g", ["9a", "9b", "9c", "9d", "9e", "9f", "9h", "9i", "9j", "9k", "9l", "9m", "12a", "12d", "12e", "12f", "12k", "12l", "12m"], 7, "The article reports the 9- and 12-series hybrid molecules in the SAR tables, but the reviewed text does not identify one unique immediate parent for every member.", "SAR; Tables 1-2"),
            ],
            "The 12c halogen/substituent replacements and the ordered pyridine/linker comparisons are retained. The 9/12 table series stays unresolved where direct parent mapping is not unique. The machine structure table covers all retained labels and contains single-component structures.",
            source_files={
                "machine_structure_table": "49238588_jm4c01760_si_002.csv",
            },
        ),
        "5531836ee3c3": record(
            "10.1021/acs.jmedchem.3c02460",
            [
                edge("B4", "B4", "I16", 4, "Compared with lead compound B4, optimized compound I16 showed more than 3-fold and 4-fold increases in inhibitory activity and selectivity, respectively.", "SAR; Table 2 and Table S1", "indazole-carboxamide substituent", MISSING, "I16 substituent", relation="lead_optimization", confidence="medium"),
                *series("B4", [
                    "I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10", "I11", "I12", "I13", "I14", "I15", "I17", "I18", "I19", "I20", "I21", "I22", "I23", "I24", "I25", "I26", "I27", "I28", "I29", "I30", "I31", "I32", "I33", "I34",
                ], 4, "The I-series indazole-carboxamide substitution table contains these analogues, but the article text does not specify a unique immediate parent for each member.", "SAR; Table 2 and Table S1"),
            ],
            "The article explicitly names B4 as the lead and I16 as the optimized analogue. Other I-series table members remain unresolved because one immediate parent is not stated. The SI machine table includes B4, I16, and the numbered I series; a repeated header row is rejected rather than treated as a molecule.",
            names={"B4": "lead B4"},
            source_files={
                "machine_structure_table": "46488058_jm3c02460_si_003.csv",
            },
        ),
        "1535ba2a9a58": record(
            "10.1021/acs.jmedchem.4c00860",
            [
                edge("14a", "14a", "14b", 4, "Compound 14b without the N-(2-hydroxyethoxy)formamide fragment showed much lower activity than compound 14a.", "SAR; Table 1", "terminal formamide region", "N-(2-hydroxyethoxy)formamide", "removed", relation="fragment_deletion"),
                *series("14a", ["14c", "14d", "14e", "14f", "14g", "14h", "14i", "14j", "14k", "14l"], 5, "Based on the molecular-dynamics analysis of 14a, compounds 14c-l were synthesized to explore the R1 substituent; the text does not specify a unique stepwise immediate parent for every member.", "SAR; Table 2"),
                *series("14a", ["15a", "15b"], 6, "The aromatic ring at R0 was replaced by an aliphatic ring to obtain compounds 15a-b, but the source does not uniquely map each member to a specific immediate parent among the preceding templates.", "SAR; Table 3"),
                *series("14a", ["16a", "16b"], 7, "Introduction of fluorine at the C-2 position of R2 produced compounds 16a-b from the preceding 14a/14f templates, but the sentence does not uniquely map each pair.", "SAR; Table 4"),
                *series("14a", ["16c", "16d", "16e", "16f", "16g", "16h", "16i", "16j"], 8, "The fluorine-position and chlorine scans produced compounds 16c-j; the reviewed text does not uniquely identify the immediate parent of each member.", "SAR; Table 4"),
                *series("14a", ["17a", "17b", "17c", "17d", "17e", "17f", "17g", "17h", "17i", "17j", "17k", "17l", "17m", "17n", "17o", "17p"], 9, "The R3 substitution scan produced compounds 17a-p; the reviewed article does not identify one unique immediate parent for every member.", "SAR; Table 5"),
            ],
            "Only the explicit 14a-to-14b deletion is represented as a direct pair. The R1/R0/R2/R3 optimization families stay unresolved where two-template mappings or table-only series do not identify the immediate parent. The SI machine table provides single-component structures for all 40 labels 14a-17p.",
            source_files={
                "machine_structure_table": "48700133_jm4c00860_si_002.csv",
            },
        ),
        "5589366efa06": record(
            "10.1021/acs.jmedchem.4c02531",
            [
                unresolved("SGC-PIKFYVE-1", "1", 2, "The ring-opened analogue of SGC-PIKFYVE-1, compound 1, retained high cellular affinity; the source treats it as a matched analogue but the exact ring-closed Paper-local parent has no numbered row in the SI table.", "SAR; Table 1"),
                unresolved("SGC-PIKFYVE-1", "2", 2, "Compound 2 is a previously reported ring-opened analogue of SGC-PIKFYVE-1, but the prior source rather than this Paper defines its exact matched parent.", "SAR; Table 1"),
                *series("1", [str(number) for number in range(3, 42)], 3, "The article explores indole, aminopyrimidine, and alkyne modifications in compounds 3-41, but the reviewed text does not uniquely identify one immediate parent for every member.", "SAR; Tables 1-4"),
                *[
                    edge("6", "6", str(number), 7, f"Based on biaryl analogue 6, replacement of the alkyne with the substituted phenyl ring gave compound {number}.", "SAR; Table 4", "alkyne region", "alkyne", "substituted phenyl", relation="alkyne_to_aryl_replacement", confidence="medium")
                    for number in range(42, 46)
                ],
                unresolved("6", "46", 7, "Compound 46 is the para-dimethylamino pendant-aryl analogue in the series based on biaryl compound 6, but the exact immediate member used for this second substitution is not stated.", "SAR; Table 4"),
                edge("6", "46", "47", 7, "Removal of a single methyl group from the amino group of compound 46 yielded monomethylated compound 47.", "SAR; Table 4", "pendant aryl amino group", "dimethylamino", "methylamino", relation="substituent_deletion"),
                edge("6", "46", "48", 7, "Insertion of a methylene group between the dimethylamino group and phenyl ring of compound 46 yielded compound 48.", "SAR; Table 4", "aryl-amino linkage", "aryl-NMe2", "aryl-CH2-NMe2", relation="linker_insertion"),
            ],
            "The source defines the prior probe and ring-opened campaign, but most table members lack a unique immediate parent. The 6-centered alkyne-to-aryl scan and 46-to-47/48 edits are explicit. The SI structure table contains labels 1-48 as complete single-component structures.",
            names={"SGC-PIKFYVE-1": "SGC-PIKFYVE-1"},
            origins={"SGC-PIKFYVE-1": "prior_art"},
            source_files={"machine_structure_table": "51840111_jm4c02531_si_002.csv"},
        ),
        "f2e855803f5a": record(
            "10.1021/acs.jmedchem.4c01787",
            [
                *series("CC-90009", ["LYG-101", "LYG-102", "LYG-103", "LYG-104", "LYG-105", "LYG-106", "LYG-107", "LYG-108"], 5, "The difluoroacetamide of CC-90009 was replaced with oxime or hydrazone in the LYG-101-108 campaign; individual immediate-parent mappings beyond the prior-art template are not stated.", "SAR; Tables 1-2"),
                *series("LYG-108", [f"LYG-{number}" for number in range(201, 208)], 7, "The oxime was replaced by primary amine or amide groups in the LYG-201-207 series, but the reviewed sentence does not identify a unique immediate parent for each compound.", "SAR; Table 3"),
                *series("LYG-108", [f"LYG-{number}" for number in range(301, 310)], 11, "The subsequent fused-ring optimization generated LYG-301-309; the reviewed text does not establish a unique direct parent for every member.", "SAR; Tables 4-7"),
                edge("LYG-308", "LYG-308", "LYG-401", 11, "Inspired by the stability and degradation activity of compound LYG-308, introduction of a double bond to block the metabolic site gave benzopyran compound LYG-401.", "SAR; Table 8", "metabolic soft spot/ring", "saturated ring", "benzopyran double bond", relation="ring_unsaturation", confidence="medium"),
                *series("LYG-401", [f"LYG-{number}" for number in range(402, 422)], 11, "The article explored SAR based on the benzopyran compound LYG-401 to produce LYG-402-421, but the text does not provide a unique stepwise immediate parent for every member.", "SAR; Table 8"),
            ],
            "The source supports a CC-90009-derived programme and a later LYG-308-to-LYG-401 design step. Other table series stay unresolved. Two machine-source records are multicomponent salts and require explicit component selection before confirmation.",
            names={"CC-90009": "CC-90009"},
            origins={"CC-90009": "prior_art"},
            source_files={"machine_structure_table": "51906210_jm4c01787_si_002.csv"},
        ),
        "8b306e91bc78": record(
            "10.1021/acs.jmedchem.3c01790",
            [
                edge("6", "6", "7", 3, "Commercially available compound 7 is the close analogue of hit compound 6 devoid of the para methyl group on the N1 phenyl ring.", "SAR; Table 1", "N1 phenyl para position", "methyl", "hydrogen", relation="substituent_deletion"),
                edge("6", "7", "8", 3, "Replacement of the methoxy group of compound 7 with morpholine on the C4 phenyl group gave compound 8, the reference for further SAR.", "SAR; Table 1", "C4 phenyl substituent", "methoxy", "morpholine"),
                *[
                    edge("6", "8", str(number), 3, f"N1 substitution of reference compound 8 generated compound {number} in the N1 SAR series.", "SAR; Table 2", "N1 substituent", "phenyl", "Table 2 substituent", relation="n1_group_replacement", confidence="medium")
                    for number in range(9, 15)
                ],
                *series("8", [str(number) for number in range(15, 24)], 3, "The C3 and subsequent vector scans produced compounds 15-23, but the reviewed text does not uniquely identify one immediate parent for every member.", "SAR; Tables 3-4"),
                edge("8", "24", "25", 3, "N-methyl substitution of the secondary aniline compound 24 yielded the less polar tertiary aniline compound 25.", "SAR; Table 4", "aniline nitrogen", "NH", "N-methyl"),
                *series("8", [str(number) for number in range(24, 46) if number != 25], 4, "The C4 and C6 SAR tables contain compounds 24-45, but only selected immediate comparisons are explicit in the reviewed text.", "SAR; Tables 4-7"),
                edge("8", "45", "46", 6, "Removal of the aromatic moiety from compound 45 with direct linkage of an unsubstituted piperidine gave compound 46.", "SAR; Table 9", "C4 aromatic linker", "aryl-piperidine", "direct piperidine", relation="fragment_deletion"),
                *series("45", ["47", "48", "49", "50", "51"], 7, "The distribution-focused C4/C6 optimization generated compounds 47-51, but the reviewed text does not uniquely identify every immediate parent.", "SAR; Tables 9-10"),
                edge("45", "51", "52", 8, "Replacement of the morpholine in compound 51 by a more basic 4-methoxypiperidine substituent gave compound 52.", "SAR; Tables 9-11", "basic heterocycle", "morpholine", "4-methoxypiperidine", relation="ring_replacement"),
            ],
            "The hit-to-reference chain 6-to-7-to-8, 8-centered N1 scan, 24-to-25, 45-to-46, and 51-to-52 edits are retained. Other C3/C4/C6 table members remain unresolved. The machine table covers labels 6-52 with complete single-component structures.",
            names={"52": "GLPG2737"},
            source_files={"machine_structure_table": "45271548_jm3c01790_si_002.csv"},
        ),
        "1a7457834b7a": record(
            "10.1021/acs.jmedchem.4c01851",
            [
                edge("6", "6", "10", 3, "Alpha-phenyl substitution on pyrrolidine compound 6 gave the R-isomer compound 10.", "SAR; Table 1", "alpha to carboxylic acid", "hydrogen", "phenyl (R)", relation="stereodefined_substitution", confidence="medium"),
                edge("6", "6", "11", 3, "Alpha-phenyl substitution on pyrrolidine compound 6 gave the more potent S-isomer compound 11.", "SAR; Table 1", "alpha to carboxylic acid", "hydrogen", "phenyl (S)", relation="stereodefined_substitution", confidence="medium"),
                edge("6", "11", "12", 3, "The polar amide linker in compound 11 was replaced with an ether linker in compound 12.", "SAR; Table 2", "central linker", "amide", "ether", relation="linker_bioisostere"),
                *[
                    edge("6", "12", str(number), 4, f"Phenyl-ring substitution of compound 12 generated compound {number} in the regioisomer scan.", "SAR; Table 2", "phenyl ring", "hydrogen", "Table 2 substituent", confidence="medium")
                    for number in range(13, 19)
                ],
                *series("12", [str(number) for number in range(19, 45)], 4, "The permeability and ring-expansion optimization produced compounds 19-44, but the reviewed text does not identify a unique immediate parent for every member.", "SAR; Tables 3-5"),
            ],
            "The 6-to-10/11 stereodefined alpha-phenyl change, 11-to-12 linker replacement, and 12-centered phenyl substitution scan are retained. Later permeability/ring-expansion table series stay unresolved. The SI table covers labels 1-44 as complete single-component structures.",
            source_files={"machine_structure_table": "49971896_jm4c01851_si_002.csv"},
        ),
        "cfc4a0d0ef41": record(
            "10.1021/acs.jmedchem.4c01221",
            [
                edge("7", "7", "11", 3, "The cyclized compound 11 was designed from linear compound 7 and showed lower affinity than compound 7.", "Design; Figure 2", "linear scaffold", "linear", "cyclized", relation="conformational_restriction", status="figure_explicit", confidence="medium"),
                edge("7", "7", "12", 3, "The cyclized tetrahydroisoquinoline compound 12 was designed from linear compound 7 and improved affinity relative to compound 7.", "Design; Figure 2", "linear scaffold", "linear", "cyclized THIQ", relation="conformational_restriction", status="figure_explicit"),
                *series("12", [str(number) for number in range(13, 47)], 4, "The amide-chain and benzenesulfonamide optimization produced compounds 13-46, but the reviewed text does not establish one unique immediate parent for every member.", "SAR; Tables 1-3"),
                edge("12", "46", "47", 7, "The meta-cyano group of compound 46 was replaced with an ester group to give compound 47.", "SAR; Table 3", "benzenesulfonamide meta substituent", "cyano", "ester"),
                edge("12", "12", "48", 7, "The phenyl group of compound 12 was replaced by a saturated cyclohexyl ring to give compound 48.", "SAR; Table 3", "P5-binding aromatic group", "phenyl", "cyclohexyl", relation="ring_replacement"),
                edge("12", "44", "49", 7, "The carbonyl of compound 44 was replaced with hydroxyl to give compound 49.", "SAR; Tables 2-3", "fluorenone carbonyl", "carbonyl", "hydroxyl"),
                edge("12", "44", "50", 7, "The carbonyl of compound 44 was replaced with methoxy to give compound 50.", "SAR; Tables 2-3", "fluorenone carbonyl", "carbonyl", "methoxy"),
                *series("12", [str(number) for number in range(51, 62)], 8, "The fluorenone-to-carbazole and subsequent optimization series contains compounds 51-61, but the reviewed text does not uniquely identify every immediate parent.", "SAR; Tables 3-4"),
            ],
            "The design explicitly links linear compound 7 to cyclized 11 and 12. Selected 46-to-47, 12-to-48, and 44-to-49/50 edits are direct; other table members stay unresolved. The SI table covers labels 11-61 with complete single-component structures, while linear compound 7 is absent.",
            source_files={"machine_structure_table": "49855111_jm4c01221_si_002.csv"},
        ),
        "a797514debbc": record(
            "10.1021/acs.jmedchem.4c01303",
            [
                *series("2", [f"3{suffix}" for suffix in "abcde"], 5, "Compound 2 was modified through bioisosteric or heterocyclic replacement of the triazole linker to generate the 3 series; unique immediate parents are not stated for every member.", "SAR; Table 1"),
                edge("2", "2", "4c", 5, "Replacement around lead compound 2 with the cyclohexyl-substituted analogue gave compound 4c.", "SAR; Table 2", "triazole phenyl region", "phenyl", "cyclohexyl", relation="ring_replacement", confidence="medium"),
                edge("2", "2", "4g", 5, "Replacement around lead compound 2 with the pyrazol-substituted analogue gave compound 4g.", "SAR; Table 2", "triazole phenyl region", "phenyl", "pyrazole", relation="ring_replacement", confidence="medium"),
                *series("2", [f"4{suffix}" for suffix in "abdef"], 5, "The remaining 4-series replacements are compared within the compound 2 campaign without a unique immediate parent in the reviewed text.", "SAR; Table 2"),
                *series("2", [f"5{suffix}" for suffix in "abcdefghi"], 6, "The monosubstitution-position scan on the triazole phenyl ring generated compounds 5a-5i; the source does not identify a unique immediate parent for each regioisomer.", "SAR; Table 3"),
                *series("2", [f"6{suffix}" for suffix in "abcdefghijk"], 6, "The subsequent phenyl-region optimization generated compounds 6a-6k without a unique immediate parent for every member.", "SAR; Table 4"),
                *series("2", [f"7{suffix}" for suffix in "abcdefghij"], 9, "The region-A substitution series contains compounds 7a-7j; individual immediate parent relations are not stated.", "SAR; Table 5"),
                *series("2", ["8a", "8b", "8c"], 9, "Compounds 8a-8c are further lead-derived analogues without a unique direct parent in the reviewed text.", "SAR; Table 5"),
            ],
            "Compound 2 is the stated lead. Only two named ring replacements are represented directly; all broader table scans remain unresolved. The machine source has labels 2, 3a-e, 4a-g, 5a-i, 6a-k, 7a-j, and 8a-c, but 45 records are multicomponent hydrochloride salts requiring explicit parent-component selection.",
            source_files={"machine_structure_table": "47838740_jm4c01303_si_003.csv"},
        ),
        "d168508d74ca": record(
            "10.1021/acs.jmedchem.4c01092",
            [
                *series("37", ["38", "39", "41", "42", "43", "44", "50", "51", "56", "57", "58", "59", "60", "61"], 5, "The terminal aryl-group optimization around compound 37 contains these analogues, but the reviewed text does not establish a unique immediate parent for every member.", "SAR; Tables 1-2"),
                edge("37", "37", "40", 5, "A methyl group was introduced at the 6-position of the pyridine ring of compound 37 to obtain compound 40.", "SAR; Scheme 2; Table 1", "pyridine 6-position", "hydrogen", "methyl"),
                edge("37", "37", "45", 5, "The pyridine ring of compound 37 was replaced with pyrimidin-2-yl to obtain compound 45.", "SAR; Scheme 2; Table 1", "terminal heteroaryl", "2-pyridyl", "2-pyrimidinyl", relation="ring_replacement"),
                *[
                    edge("37", "37", label, 5, f"Transfer of the pyridine nitrogen of compound 37 generated the 3-pyridyl analogue {label}.", "SAR; Scheme 2; Table 1", "pyridine nitrogen position", "2-pyridyl", "3-pyridyl", relation="heteroatom_transposition", confidence="medium")
                    for label in ("46", "47", "48")
                ],
                edge("37", "37", "49", 5, "The pyridine ring of compound 37 was replaced with a 3-tolyl group to obtain compound 49.", "SAR; Scheme 2; Table 1", "terminal heteroaryl", "2-pyridyl", "3-tolyl", relation="ring_replacement"),
                edge("37", "37", "52", 5, "The pyridine ring of compound 37 was replaced with indole to obtain compound 52.", "SAR; Scheme 2; Table 1", "terminal heteroaryl", "2-pyridyl", "indole", relation="ring_replacement"),
                edge("37", "37", "53", 5, "The pyridine ring of compound 37 was replaced with purine to obtain compound 53.", "SAR; Scheme 2; Table 1", "terminal heteroaryl", "2-pyridyl", "purine", relation="ring_replacement"),
                edge("37", "37", "54", 5, "A methylene linker was introduced between the core and pyridine ring of compound 37 to obtain compound 54.", "SAR; Scheme 2; Table 1", "core-pyridyl linkage", "direct bond", "methylene", relation="linker_insertion"),
                edge("37", "48", "55", 18, "The 3-pyridyl group in compound 48 was changed to 3-pyridylmethylene to give compound 55.", "SAR; Table 2", "core-pyridyl linkage", "direct 3-pyridyl", "3-pyridylmethylene", relation="linker_insertion"),
                edge("37", "37", "74", 18, "Replacement of the 2,6-dichlorophenyl group in compound 37 by 2,6-dibromophenyl gave compound 74.", "SAR; Scheme 6; Table 3", "isoxazole aryl group", "2,6-dichlorophenyl", "2,6-dibromophenyl"),
                edge("37", "37", "75", 18, "Replacement of the 2,6-dichlorophenyl group in compound 37 by 2,6-dimethylphenyl gave compound 75.", "SAR; Scheme 6; Table 3", "isoxazole aryl group", "2,6-dichlorophenyl", "2,6-dimethylphenyl"),
                edge("39", "39", "76", 18, "Replacement of the 2,6-dichlorophenyl group in compound 39 by 2,6-dibromophenyl gave compound 76.", "SAR; Scheme 6; Table 3", "isoxazole aryl group", "2,6-dichlorophenyl", "2,6-dibromophenyl"),
                edge("39", "39", "77", 18, "Replacement of the 2,6-dichlorophenyl group in compound 39 by 2,6-dimethylphenyl gave compound 77.", "SAR; Scheme 6; Table 3", "isoxazole aryl group", "2,6-dichlorophenyl", "2,6-dimethylphenyl"),
            ],
            "Compound 37 is the designed lead for terminal heteroaryl optimization and compounds 37/39 are explicit parents for the 74-77 aryl replacements. The repaired wrapped-row CSV now yields 29/29 parsed, single-component records for labels 37-61 and 74-77.",
            source_files={"machine_structure_table": "47998437_jm4c01092_si_001.csv"},
        ),
        "0eb39d3b45ae": record(
            "10.1021/acs.jmedchem.4c01568",
            [
                *series("1a", ["1b", "1c", "1d", "1e", "1f", "1g", "1h", "2a", "2b", "3b", "3c", "3d", "3e", "3f", "3g", "3h", "3i", "3j"], 3, "The urea and chiral methyl-spacer optimization generated compounds 1b-3j; the reviewed text does not establish a unique immediate parent for each member.", "SAR; Tables 1-3"),
                *[
                    edge("1a", "3b", f"4{suffix}", 5, f"Substitution on the isoquinolinone ring of active enantiomer 3b generated compound 4{suffix}.", "SAR; Table 4", "isoquinolinone ring", "hydrogen", "Table 4 substituent", confidence="medium")
                    for suffix in "abcdefghijkl"
                ],
                *[
                    edge("1a", "4j", f"5{suffix}", 7, f"Modification of the substituted phenyl urea of compound 4j generated compound 5{suffix}.", "SAR; Table 5", "phenyl urea substituent", "3-Cl,4-F", "Table 5 pattern", confidence="medium")
                    for suffix in "abcdefgh"
                ],
                *series("4j", ["6", "7", "8", "9", "10", "11", "12"], 7, "Replacement of the urea functionality by alternative hydrogen-bonding fragments generated compounds 6-12, but the reviewed text does not identify a unique immediate parent for every member.", "SAR; Table 6"),
            ],
            "The active enantiomer 3b is the parent for the isoquinolinone substitution table and 4j is the parent for the phenyl-urea scan. Earlier urea/chiral series and later core replacements stay unresolved. The machine table covers all 46 retained labels as single-component structures.",
            source_files={"machine_structure_table": "49011961_jm4c01568_si_002.csv"},
        ),
        "f501045da21f": record(
            "10.1021/acs.jmedchem.4c01283",
            [
                *series("E1", [f"E{number}" for number in range(2, 17)], 3, "R1 alkyl and ring variants E2-E16 were introduced around hit compound E1; the reviewed text does not identify one immediate parent for each member.", "SAR; Tables 1-2"),
                edge("E1", "E1", "E17", 4, "Introduction of bromine at the 4-position of the benzyl group of hit compound E1 gave compound E17.", "SAR; Table 2", "benzyl para position", "hydrogen", "bromine"),
                *series("E1", ["E18", "E19", "E20", "E21"], 4, "The remaining benzyl substitution series E18-E21 is reported around hit E1 without a unique immediate parent for every member.", "SAR; Table 2"),
                *[
                    edge("E1", "E17", f"E{number}", 4, f"Replacement of the para phenyl group of compound E17 generated compound E{number}.", "SAR; Table 3", "para group attached to benzyl", "phenyl", "Table 3 group", confidence="medium")
                    for number in range(22, 26)
                ],
                *series("E17", [f"E{number}" for number in range(26, 39)], 5, "The R2/methoxy-region optimization generated compounds E26-E38; the reviewed text does not establish one immediate parent for each member.", "SAR; Tables 3-4"),
                edge("E17", "E37", "E39", 3, "Compound E37 was condensed with N-methylpiperazine to give compound E39.", "Chemistry; Scheme 1", "carboxyl group", "carboxylic acid", "N-methylpiperazine amide", relation="amide_formation"),
                edge("E17", "E38", "E40", 3, "Compound E38 was condensed with N-methylpiperazine to give compound E40.", "Chemistry; Scheme 1", "carboxyl group", "carboxylic acid", "N-methylpiperazine amide", relation="amide_formation"),
                edge("E17", "E26", "E41", 3, "Nucleophilic substitution of compound E26 with methyl 3-aminobenzoate gave compound E41.", "Chemistry; Scheme 1", "leaving group", MISSING, "methyl 3-aminobenzoate", relation="nucleophilic_substitution"),
                edge("E17", "E26", "E42", 3, "Nucleophilic substitution of compound E26 with methyl 4-aminobenzoate gave compound E42.", "Chemistry; Scheme 1", "leaving group", MISSING, "methyl 4-aminobenzoate", relation="nucleophilic_substitution"),
            ],
            "Hit E1, explicit E1-to-E17, E17-to-E22-25, and synthetic E37/38/26 branches are retained. Other R1/R2 table members stay unresolved. GB18030 decoding and the Chinese label header are now explicitly supported; all 42 machine rows bind to E1-E42 and parse as single-component structures.",
            source_files={"machine_structure_table": "49235830_jm4c01283_si_002.csv"},
        ),
        "c6fdd5c7e071": record(
            "10.1021/acs.jmedchem.3c02246",
            [
                edge("9", "9", "10", 3, "Replacement of the ethyl pyrazole moiety of compound 9 by a nonaromatic morpholine substituent gave compound 10.", "SAR; Table 2", "benzimidazole 5-position", "ethyl pyrazole", "morpholine", relation="group_replacement"),
                *series("10", [str(number) for number in range(11, 17)], 3, "Starting from hit compound 10, scaffold hopping and benzamide modification generated compounds 11-16; one immediate parent for every member is not stated.", "SAR; Tables 2-3"),
                edge("10", "16", "17", 5, "The N-methyl basic center of compound 16 was replaced by a polar nonbasic acetamide to give compound 17.", "SAR; Table 4", "terminal basic center", "N-methyl amine", "acetamide"),
                edge("10", "16", "18", 5, "Extension of the chain on the piperazine nitrogen of compound 16 with hydroxyethyl gave compound 18.", "SAR; Table 4", "piperazine nitrogen", "methyl", "hydroxyethyl", relation="chain_extension"),
                *series("10", [str(number) for number in range(19, 26)], 5, "Compounds 19-25 form the subsequent scaffold and substituent series, without a unique immediate parent for every member in the reviewed text.", "SAR; Tables 4-5"),
                unresolved("10", "26", 7, "O-linked compound 26 improved CYP TDI properties relative to the N-linked series, but the reviewed text does not uniquely state its immediate numbered parent.", "SAR; Table 5"),
                *series("10", ["27", "28", "29", "30"], 7, "Compounds 27-30 continue the O-linked/pyridine optimization but lack unique immediate parent statements.", "SAR; Table 5"),
                edge("10", "28", "31", 7, "Cyclization of the amide of pyridine compound 28 into a cyclopropyl-substituted lactam gave compound 31.", "SAR; Table 5", "benzamide/pyridine region", "open amide", "cyclized lactam", relation="lactam_cyclization"),
                edge("10", "31", "32", 7, "Replacement of the cyclopropyl group on lactam compound 31 by trifluoroethyl gave compound 32 (GLPG3970).", "SAR; Table 5", "lactam substituent", "cyclopropyl", "trifluoroethyl"),
                *series("10", [
                    "33", "34", "35", "36", "37", "38", "39", "40", "41", "42",
                    "43a", "43b", "43c", "44", "45", "46",
                    "47a", "47b", "47c", "48", "49", "50", "51", "52",
                    "53a", "53b", "54", "55a", "55b",
                ], 8, "The article and SI contain later intermediates and analogues, but the reviewed SAR text does not identify a unique immediate parent for each label.", "Chemistry and SI structure table"),
            ],
            "The direct 9-to-10, 16-to-17/18, 28-to-31, and 31-to-32 chain is retained. Other table members remain unresolved. The machine source covers 54 single-component structures and binds labels from either SMILES-first or compound-number-second columns.",
            names={"32": "GLPG3970"},
            source_files={"machine_structure_table": "45376983_jm3c02246_si_002.csv"},
        ),
        "2f3a5d2f7fb0": record(
            "10.1021/acs.jmedchem.3c01961",
            [
                *series("2C-TFM", [str(number) for number in range(1, 40)], 2, "The article synthesized 39 new 2C-X compounds focused on 4-thio and lipophilic fluoroalkyl substitutions; the reviewed text does not identify a unique immediate parent for every numbered member.", "SAR; Figures 2-4; Tables 1-4"),
                unresolved("2C-TFM", "2C-T", 5, "The 2C-T family is used as a comparator for the 4-thiofluoroalkyl SAR, but one unique immediate parent relation is not defined in this Paper.", "SAR; Figure 1"),
                unresolved("2C-TFM", "2C-tBu", 6, "2C-tBu is a nonfluorinated bulky 4-substituted comparator, not an explicitly identified direct child of one numbered compound.", "SAR; Figure 4"),
                unresolved("2C-TFM", "2C-T-28", 6, "2C-T-28 is a named comparator in the 4-substituted phenethylamine SAR without a unique immediate parent in the reviewed text.", "SAR; Figure 1"),
                unresolved("2C-TFM", "2C-T-9", 6, "2C-T-9 is a named thio-tert-butyl comparator in the SAR without a unique immediate parent in the reviewed text.", "SAR; Figure 1"),
            ],
            "This Paper reports a broad 2C-X SAR, but the extracted prose does not expose reliable Paper-local number-to-parent mappings for the 39 structures. All relationships therefore remain unresolved rather than inferred from structural similarity. The machine table provides 44 parsed single-component labelled structures and one empty trailing row.",
            names={"2C-TFM": "CYB210010"},
            source_files={"machine_structure_table": "45559667_jm3c01961_si_001.csv"},
        ),
        "83d4f2ab5b7c": record(
            "10.1021/acs.jmedchem.3c02473",
            [
                *series("1", ["13", "14", "15", "21", "27", "30", "31", "33", "34", "35"], 4, "Lead compound 1 motivated introduction of solubilizing elements at C7/C8 in compounds 13-35, but the reviewed text does not identify a unique immediate parent for every selected compound.", "SAR; Figures 3-5; Tables 1-2"),
                edge("1", "33", "59", 10, "Compound 59 was optimized from compound 33 by introducing a meta-fluoro phenyl substituent while retaining the glycol ether moiety.", "SAR; Figure 6", "C7 phenyl meta position", "hydrogen", "fluorine", confidence="medium"),
                edge("1", "33", "60", 10, "Compound 60 was optimized from compound 33 by introducing a difluoro phenyl substitution while retaining the glycol ether moiety.", "SAR; Figure 6", "C7 phenyl meta positions", "hydrogen", "difluoro", confidence="medium"),
            ],
            "Compound 1 is the stated lead. The broad C7/C8 solubilizing series remains unresolved; Figure 6 explicitly identifies compounds 59 and 60 as optimized from derivative 33. The machine table contains 13 complete, single-component selected structures.",
            source_files={"machine_structure_table": "47014540_jm3c02473_si_004.csv"},
        ),
        "dfe42148eabf": record(
            "10.1021/acs.jmedchem.3c01976",
            [
                *[
                    edge("2", "2", label, 2, f"Methyl substitution around one of the three scaffold nitrogen positions of hit compound 2 generated compound {label}.", "SAR; Table 1", "scaffold nitrogen region", "hydrogen", "methyl", relation="n_methylation", confidence="medium")
                    for label in ("7", "11", "15")
                ],
                edge("2", "2", "17", 5, "The carbonyl group of hit compound 2 was replaced by an amino group to give compound 17 for solubility optimization.", "SAR; Table 1", "pyrazolopyrimidinone carbonyl", "carbonyl", "amino", relation="functional_group_replacement"),
                *series("2", ["21a", "21b", "21c", "21d", "21e", "21f"], 3, "The R2-focused optimization generated compounds 21a-f from several active templates (7, 11, 15, and 17), but the reviewed text does not uniquely map each immediate parent.", "SAR; Table 2; Scheme 4"),
                *series("2", ["22", "31a", "31b", "31c", "31d", "31e", "31f", "35"], 5, "The R4 and phenyl-replacement optimization generated these later compounds, but the reviewed text does not identify one unique immediate parent for each.", "SAR; Tables 2-3"),
            ],
            "Compound 2 (NPD-2975) is the explicit prior hit. Three initial N-methyl variants and the carbonyl-to-amino compound 17 are direct; R2/R4 series remain unresolved. The machine source has 19 parsed records, one of which is multicomponent and requires explicit component selection.",
            names={"2": "NPD-2975", "31c": "NPD-3519"},
            origins={"2": "prior_art"},
            source_files={"machine_structure_table": "44474952_jm3c01976_si_002.csv"},
        ),
        "14c9ce88d1c2": record(
            "10.1021/acs.jmedchem.4c02093",
            [
                *series("2", [str(number) for number in range(21, 57)], 4, "Natural tylophorine analogues 2 and 3 were used to explore ring-B ether and terminal-amine substitutions in compounds 21-56; the reviewed text does not uniquely map every analogue to one of the two templates.", "SAR; Tables 1-2"),
                edge("2", "27", "29", 4, "Introduction of OCF3 into the benzyloxy moiety of compound 27 gave compound 29.", "SAR; Table 1", "benzyloxy substituent", "hydrogen", "trifluoromethoxy"),
                *[
                    edge("5", "5", str(number), 6, f"Replacement of the ring-B methoxy group of natural product 5 generated compound {number}.", "SAR; Table 3", "ring-B 4-position", "methoxy", "Table 3 ether", confidence="medium")
                    for number in range(64, 73)
                ],
                edge("6", "6", "73", 6, "Replacement of the ring-B methoxy group of natural product 6 with ethoxy gave compound 73.", "SAR; Table 3", "ring-B 4-position", "methoxy", "ethoxy"),
                edge("6", "6", "74", 6, "Replacement of the ring-B methoxy group of natural product 6 with propoxy gave compound 74.", "SAR; Table 3", "ring-B 4-position", "methoxy", "propoxy"),
                *series("5", ["75", "76", "77", "78", "79", "80", "81"], 6, "The remaining PG ring-B/ring-C substitutions 75-81 belong to the natural-product optimization series, but one unique immediate parent for each is not stated.", "SAR; Table 3"),
            ],
            "Natural products 2/3 and 5/6 are the source templates. Compound 27-to-29 and the 5/6-centered PG ether replacements are direct; other two-template series remain unresolved. The machine table has 97 parsed rows, including 58 multicomponent salt representations requiring explicit component selection.",
            origins={"2": "natural_product", "3": "natural_product", "5": "natural_product", "6": "natural_product"},
            source_files={"machine_structure_table": "49880746_jm4c02093_si_002.csv"},
        ),
        "c3b3eba1f5b3": record(
            "10.1021/acs.jmedchem.3c01347",
            [
                _peptide_substitution("1", "residue 1", "Tyr", "Dmt1"),
                _peptide_substitution("2", "residue 3", "Gly", "Ala3"),
                _peptide_substitution("3", "residue 3", "Gly", "D-Ala3"),
                _peptide_substitution("4", "residue 3", "Gly", "Aib3"),
                _peptide_substitution("5", "residue 3", "Gly", "Nle3"),
                _peptide_substitution("6", "residue 3", "Gly", "Pro3"),
                _peptide_substitution("7", "residue 3", "Gly", "beta-Ala3"),
                _peptide_substitution("8", "residue 3", "Gly", "Sar3"),
                _peptide_substitution("9", "residue 4", "Phe", "D-Phe4"),
                _peptide_substitution("10", "residue 4", "Phe", "Cha4"),
                _peptide_substitution("11", "residue 4", "Phe", "2-Nal4"),
                _peptide_substitution("12", "residue 4", "Phe", "Phg4"),
                _peptide_substitution("13", "residue 4", "Phe", "Homo-Phe4"),
                _peptide_substitution("14", "residue 4", "Phe", "NPhe4"),
                _peptide_substitution("15", "residue 4", "Phe", "p-F-Phe4"),
                _peptide_substitution("16", "residue 4", "Phe", "p-Me-Phe4"),
                _peptide_substitution("17", "residue 4", "Phe", "NMe-Phe4"),
                _peptide_substitution("18", "residue 6", "D-Pro", "Pro6"),
                _peptide_substitution("19", "residue 6", "D-Pro", "des-D-Pro6"),
                _peptide_substitution("20", "residue 6", "D-Pro", "Gly6"),
                _peptide_substitution("21", "residue 6", "D-Pro", "D-Pip6"),
                _peptide_substitution("22", "residue 6", "D-Pro", "Pip6"),
            ],
            "The article defines 0 as the parent peptide and Table 1 identifies all 22 single-residue substitution analogues. The SI structure table contains complete SMILES for labels 0-22.",
            names={"0": "Tyr-c[D-Lys-Gly-Phe-Asp]-D-Pro-NH2"},
            source_files={
                "machine_structure_table": "43778040_jm3c01347_si_002.csv",
            },
        ),
        "df798aa2ca88": record(
            "10.1021/acs.jmedchem.4c00856",
            [
                _gpr52_edge("4a", "10a", 4, "opening the indoline ring of parent compound 4a led to compound 10a.", "indoline ring", "fused indoline", "open aminobenzamide", relation="ring_opening"),
                *[
                    _gpr52_edge("10a", label, 4, f"the aminoalcohol side chain of 10a was replaced with the cycloalkane member {label}.", "aminoalcohol side chain", "ethanolamine", "cycloalkane", relation="side_chain_replacement")
                    for label in ("10b", "10c", "10d")
                ],
                *[
                    _gpr52_edge("10a", label, 4, f"the article's 10e-g set appended substituents to the aminoalcohol side chain of 10a, including {label}.", "aminoalcohol side chain", "unsubstituted", "substituted aminoalcohol", relation="side_chain_substitution")
                    for label in ("10e", "10f", "10g")
                ],
                _gpr52_edge("10a", "10h", 4, "replacing the aminoalcohol hydroxy group of 10a with difluoro afforded 10h.", "aminoalcohol hydroxy group", "hydroxy", "difluoro"),
                _gpr52_edge("10a", "10i", 4, "swapping the aminoalcohol hydroxy group of 10a with methoxy yielded 10i.", "aminoalcohol hydroxy group", "hydroxy", "methoxy"),
                *[
                    _gpr52_edge("10a", label, 4, f"extension of the aminoalcohol alkyl chain of 10a led to the 10j-l series member {label}.", "aminoalcohol alkyl chain", "two-carbon chain", "extended chain", relation="chain_extension")
                    for label in ("10j", "10k", "10l")
                ],
                *[
                    _gpr52_edge("10a", label, 5, f"a 2-position substitution on ring A of 10a led to compound {label}.", "ring A 2-position", "hydrogen", "Table 2 substituent")
                    for label in ("15a", "15b", "15c", "15d", "15e")
                ],
                *[
                    _gpr52_edge("10a", label, 5, f"a 4-position substitution on ring A of 10a provided compound {label}.", "ring A 4-position", "hydrogen", "Table 2 substituent")
                    for label in ("15f", "15g")
                ],
                _gpr52_edge("10a", "15h", 5, "introduction of fluorine at the 6-position of ring A afforded compound 15h.", "ring A 6-position", "hydrogen", "fluorine"),
                _gpr52_edge("10a", "19", 5, "transposition of the amide from the 1-position to the 6-position on ring A yielded compound 19.", "ring A amide position", "1-position amide", "6-position amide", relation="functional_group_transposition"),
                _gpr52_edge("15b", "24a", 5, "introduction of an additional CF3 group on 15b led to 24a (3,5-di-CF3).", "ring C", "3-CF3", "3,5-di-CF3"),
                _gpr52_edge("15b", "24b", 5, "compound 24b is the 2,4-di-CF3 analogue compared directly with 15b.", "ring C", "3-CF3", "2,4-di-CF3", relation="substitution_pattern_change"),
                _gpr52_edge("15b", "24c", 5, "transposition of the CF3 group of 15b to the 4-position led to 24c.", "ring C CF3 position", "3-CF3", "4-CF3", relation="substituent_transposition"),
                _gpr52_edge("15b", "24d", 5, "transposition of the CF3 group of 15b to the 2-position led to 24d.", "ring C CF3 position", "3-CF3", "2-CF3", relation="substituent_transposition"),
                _gpr52_edge("15b", "24e", 5, "installation of chlorine at the 3-position and fluorine at the 5-position provided 24e.", "ring C", "3-CF3", "3-Cl,5-F", relation="substitution_pattern_change"),
                _gpr52_edge("15b", "24f", 5, "compound 24f bears a 3-OMe group in the ring-C substitution scan derived from 15b.", "ring C 3-position", "trifluoromethyl", "methoxy"),
                _gpr52_edge("15b", "24g", 5, "compound 24g is the unsubstituted ring-C member in the scan derived from 15b.", "ring C 3-position", "trifluoromethyl", "hydrogen"),
                _gpr52_edge("15b", "24h", 5, "compound 24h contains chlorine at the 4-position and fluorine at the 2-position in the 15b ring-C scan.", "ring C", "3-CF3", "4-Cl,2-F", relation="substitution_pattern_change"),
                _gpr52_edge("15b", "24i", 5, "compound 24i bears fluorine at the 3-position in the ring-C scan derived from 15b.", "ring C 3-position", "trifluoromethyl", "fluorine"),
                _gpr52_edge("15b", "24j", 5, "incorporating fluorine at the 4-position on ring C led to 24j.", "ring C", "3-CF3", "4-F", relation="substitution_pattern_change"),
                _gpr52_edge("15b", "24k", 5, "compound 24k bears OCF3 at the 3-position in the ring-C scan derived from 15b.", "ring C 3-position", "trifluoromethyl", "trifluoromethoxy"),
            ],
            "The article explicitly defines 4a as the parent scaffold, 10a as its ring-opened derivative, the 10a side-chain/ring-A series, and 15b as the immediate template for the 24a-k ring-C scan. The SI table covers 10a-l, 15a-h, 19, and 24a-k; 4a itself is not in that machine-readable table.",
            names={"10a": "PW0677", "15b": "PW0729", "24f": "PW0866"},
            origins={"4a": "prior_art"},
            source_files={
                "machine_structure_table": "46541584_jm4c00856_si_002.csv",
            },
        ),
    }


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
    print(f"wrote {len(BATCH_05_PAPERS)} batch-05 annotation files")


if __name__ == "__main__":
    main()
