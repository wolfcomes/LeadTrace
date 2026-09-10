#!/usr/bin/env python3
"""Publish source-audited prior-art structures required by Batch 05.

Six named compounds are linked to exact PubChem CIDs.  Dysoxylactam A is
linked to the final row of the Paper's own machine-readable SI table, where
the label is shortened to ``DA`` but the reported activity values match the
article's DLA control.  Generic R-group families remain deliberately absent.
"""

from __future__ import annotations

import csv
from pathlib import Path

from lineage_structure_reconstruction import (
    DEFAULT_CONFIRMED_PATH,
    DEFAULT_WORK_PATH,
    build_external_identifier_work_row,
    build_reviewed_structure_work_row,
    publish_reviewed_structure_candidates,
)


EXTERNAL_IDENTIFIER_REPAIRS = [
    {
        "paper_id": "23fa35c9b113",
        "compound_entity_id": "CMP-23fa35c9b113-1",
        "compound_label": "1",
        "query_name": "Geldanamycin",
        "pubchem_cid": "5288382",
        "canonical_isomeric_smiles": (
            "C[C@H]1C[C@@H]([C@@H]([C@H](/C=C(/[C@@H]([C@H](/C=C\\C=C(\\"
            "C(=O)NC2=CC(=O)C(=C(C1)C2=O)OC)/C)OC)OC(=O)N)\\C)C)O)OC"
        ),
    },
    {
        "paper_id": "23fa35c9b113",
        "compound_entity_id": "CMP-23fa35c9b113-2a",
        "compound_label": "2a",
        "query_name": "17-AAG (tanespimycin)",
        "pubchem_cid": "6505803",
        "canonical_isomeric_smiles": (
            "C[C@H]1C[C@@H]([C@@H]([C@H](/C=C(/[C@@H]([C@H](/C=C\\C=C(\\"
            "C(=O)NC2=CC(=O)C(=C(C1)C2=O)NCC=C)/C)OC)OC(=O)N)\\C)C)O)OC"
        ),
    },
    {
        "paper_id": "23fa35c9b113",
        "compound_entity_id": "CMP-23fa35c9b113-2b",
        "compound_label": "2b",
        "query_name": "17-DMAG (alvespimycin)",
        "pubchem_cid": "5288674",
        "canonical_isomeric_smiles": (
            "C[C@H]1C[C@@H]([C@@H]([C@H](/C=C(/[C@@H]([C@H](/C=C\\C=C(\\"
            "C(=O)NC2=CC(=O)C(=C(C1)C2=O)NCCN(C)C)/C)OC)OC(=O)N)\\C)C)O)OC"
        ),
    },
    {
        "paper_id": "23fa35c9b113",
        "compound_entity_id": "CMP-23fa35c9b113-2c",
        "compound_label": "2c",
        "query_name": "17-Aminogeldanamycin (17-AG)",
        "pubchem_cid": "9893658",
        "canonical_isomeric_smiles": (
            "C[C@H]1C[C@@H]([C@@H]([C@H](/C=C(/[C@@H]([C@H](/C=C\\C=C(\\"
            "C(=O)NC2=CC(=O)C(=C(C1)C2=O)N)/C)OC)OC(=O)N)\\C)C)O)OC"
        ),
    },
    {
        "paper_id": "5589366efa06",
        "compound_entity_id": "CMP-5589366efa06-sgcpikfyve1",
        "compound_label": "SGC-PIKFYVE-1",
        "query_name": "SGC-PIKFYVE-1",
        "pubchem_cid": "165368936",
        "canonical_isomeric_smiles": (
            "CN(C)CC#CC1=CC2=C(C=C1)NC3=C2C4=NC(=NC=C4CCC3)N"
        ),
    },
    {
        "paper_id": "f2e855803f5a",
        "compound_entity_id": "CMP-f2e855803f5a-cc90009",
        "compound_label": "CC-90009",
        "query_name": "CC-90009 (eragidomide)",
        "pubchem_cid": "118647211",
        "canonical_isomeric_smiles": (
            "C1CC(=O)NC(=O)C1N2CC3=C(C2=O)C=CC(=C3)CNC(=O)"
            "C(C4=CC=C(C=C4)Cl)(F)F"
        ),
    },
]


REVIEWED_FIGURE_REPAIRS = [
    {
        "paper_id": "a1d7361647de",
        "compound_entity_id": "CMP-a1d7361647de-1",
        "compound_label": "1",
        "canonical_isomeric_smiles": (
            "O=C(O)C1=CN(C2=NC=C(OCC3=CC=CC(OC(F)(F)F)=C3)C=N2)N=C1"
        ),
        "source_id": "article:a1d7361647de",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "li-et-al-2024-structural-optimization-and-structure-activity-"
            "relationship-of-1h-pyrazole-4-carboxylic-acid-derivatives.pdf"
        ),
        "source_locator": "Main PDF page 2, Figure 1, compound 1",
        "source_label": "1",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Figure 1 shows the complete pyrazole carboxylic acid, "
            "pyrimidine, benzyloxy, and meta-OCF3 graph for compound 1. "
            "Figure 2 and the accompanying text independently identify "
            "compound 3 as the OCF3-deleted analogue."
        ),
        "stereochemistry_status": "not_applicable",
    },
    {
        "paper_id": "a1d7361647de",
        "compound_entity_id": "CMP-a1d7361647de-3",
        "compound_label": "3",
        "canonical_isomeric_smiles": (
            "O=C(O)C1=CN(C2=NC=C(OCC3=CC=CC=C3)C=N2)N=C1"
        ),
        "source_id": "article:a1d7361647de",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "li-et-al-2024-structural-optimization-and-structure-activity-"
            "relationship-of-1h-pyrazole-4-carboxylic-acid-derivatives.pdf"
        ),
        "source_locator": "Main PDF page 2, Figure 2B, compound 3",
        "source_label": "3",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Figure 2B draws the complete starting structure 3. The graph "
            "also equals the common unsubstituted scaffold of SI compounds "
            "4-11 after removal of their pyrazole-region substituent."
        ),
        "stereochemistry_status": "not_applicable",
    },
    {
        "paper_id": "cfc4a0d0ef41",
        "compound_entity_id": "CMP-cfc4a0d0ef41-7",
        "compound_label": "7",
        "canonical_isomeric_smiles": (
            "O=C(O)C(C1=CC=CC(CNS(=O)(=O)C2=CC=CC=C2)=C1)"
            "NC(C3=CC=CC(C4=O)=C3C5=C4C=CC=C5)=O"
        ),
        "source_id": "article:cfc4a0d0ef41",
        "source_file": (
            "source_pdfs/case3 volume67 issue 19-22/"
            "qin-et-al-2024-structure-guided-conformational-restriction-"
            "leading-to-high-affinity-selective-and-cell-active.pdf"
        ),
        "source_locator": "Main PDF page 2, Figure 1B, compound 7 (R = H)",
        "source_label": "7",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Figure 1B gives the complete linear fluorenone carboxamide, "
            "alpha-carboxylic acid, benzylsulfonamide, and phenyl graph for "
            "compound 7. No stereochemical wedge is assigned to 7."
        ),
        "stereochemistry_status": "source_unspecified",
    },
    {
        "paper_id": "df798aa2ca88",
        "compound_entity_id": "CMP-df798aa2ca88-4a",
        "compound_label": "4a",
        "canonical_isomeric_smiles": (
            "O=C(NCCO)c1cccc2c1CCN2c1cc(Cc2cccc(C(F)(F)F)c2)ccn1"
        ),
        "source_id": "article:df798aa2ca88",
        "source_file": (
            "source_pdfs/case2 volume67 issue10-13/"
            "murphy-et-al-2024-discovery-of-3-((4-benzylpyridin-2-yl)"
            "amino)benzamides-as-potent-gpr52-g-protein-biased-agonists.pdf"
        ),
        "source_locator": "Main PDF page 2, Figure 1, compound 4a (R = H; X = CH)",
        "source_label": "4a",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Figure 1 draws the complete 4a indoline carboxamide and labels "
            "its variable positions R = H and X = CH. The paper's explicit "
            "4a-to-10a ring-opening step independently checks the shared "
            "2-amino-4-benzylpyridine and hydroxyethyl carboxamide graph."
        ),
        "stereochemistry_status": "not_applicable",
    },
    {
        "paper_id": "e64c071652ca",
        "compound_entity_id": "CMP-e64c071652ca-m17b15",
        "compound_label": "M17-B15",
        "canonical_isomeric_smiles": (
            "O=C(CC1=NSC(NC(C2=C(OC(C3=CC(C(F)(F)F)=CC=C3)=C2)C)=O)"
            "=N1)C"
        ),
        "source_id": "article:e64c071652ca",
        "source_file": (
            "source_pdfs/case3 volume67 issue 19-22/"
            "liao-et-al-2024-discovery-of-thiadiazoleamide-derivatives-as-"
            "potent-selective-and-orally-available-antagonists.pdf"
        ),
        "source_locator": (
            "Main PDF page 2, Figure 1B; page 15 systematic name and HRMS, "
            "M17-B15"
        ),
        "source_label": "M17-B15",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Figure 1B supplies the complete graph. The systematic name and "
            "HRMS on page 15 independently confirm C18H14F3N3O3S (neutral; "
            "calculated [M+H]+ 410.0781) for the reconstructed structure."
        ),
        "stereochemistry_status": "not_applicable",
    },
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _build_dla_source_repair(work_path: Path) -> dict[str, str]:
    rows = [
        row for row in _read_csv(work_path)
        if row.get("paper_id") == "8968e9a60ef9"
        and row.get("source_label") == "DA"
        and row.get("source_locator") == "row=64"
        and row.get("binding_status") == "unmatched_label"
        and row.get("record_status") == "parsed"
    ]
    if len(rows) != 1:
        raise ValueError(
            "expected one unmatched DLA source row labelled DA at row=64; "
            f"observed {len(rows)}"
        )
    source = rows[0]
    return build_reviewed_structure_work_row(
        paper_id="8968e9a60ef9",
        compound_entity_id="CMP-8968e9a60ef9-dla",
        compound_label="DLA",
        canonical_isomeric_smiles=source["canonical_isomeric_smiles"],
        source_id=source["source_id"],
        source_file=source["source_file"],
        source_locator=source["source_locator"],
        source_label=source["source_label"],
        reconstruction_method="reviewed_complete_structure",
        source_match_status="exact_complete_structure_match",
        decision_note=(
            "The Paper's SI structure table ends with label DA and the DLA "
            "control values (99.5% inhibition and 3.5 nM IC50). The article "
            "uses DLA throughout and reports the same 3.5 nM control value; "
            "DA is therefore audited as the truncated DLA row."
        ),
        stereochemistry_status="source_encoded",
    )


def build_prior_art_repair_candidates(
    work_path: Path = DEFAULT_WORK_PATH,
) -> list[dict[str, str]]:
    candidates = []
    for repair in EXTERNAL_IDENTIFIER_REPAIRS:
        cid = repair["pubchem_cid"]
        candidates.append(build_external_identifier_work_row(
            paper_id=repair["paper_id"],
            compound_entity_id=repair["compound_entity_id"],
            compound_label=repair["compound_label"],
            query_name=repair["query_name"],
            canonical_isomeric_smiles=repair["canonical_isomeric_smiles"],
            source_url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            source_locator=(
                f"PubChem CID {cid}; exact named-compound identifier match"
            ),
        ))
    candidates.extend(
        build_reviewed_structure_work_row(**repair)
        for repair in REVIEWED_FIGURE_REPAIRS
    )
    candidates.append(_build_dla_source_repair(Path(work_path)))
    return candidates


def main() -> None:
    candidates = build_prior_art_repair_candidates()
    result = publish_reviewed_structure_candidates(
        candidates,
        work_path=DEFAULT_WORK_PATH,
        confirmed_path=DEFAULT_CONFIRMED_PATH,
    )
    confirmed_keys = {
        (row["paper_id"], row["normalized_label"])
        for row in result["confirmed_rows"]
    }
    for row in candidates:
        key = (row["paper_id"], row["normalized_label"])
        if key not in confirmed_keys:
            raise RuntimeError(f"prior-art repair was not confirmed: {key}")
    print(f"published_prior_art_repairs={len(candidates)}")
    print(f"confirmed_rows={len(result['confirmed_rows'])}")


if __name__ == "__main__":
    main()
