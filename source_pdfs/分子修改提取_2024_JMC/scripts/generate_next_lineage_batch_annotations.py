#!/usr/bin/env python3
"""Generate the reviewed annotation boundary for the next 24-Paper batch.

The source files are inspected by the structure pipeline separately. This
module only records evidence-backed direct edges and deliberately keeps broad
SAR series with an unresolved direct parent out of pair eligibility.
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANNOTATION_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "lineage_annotations"
MISSING = "--"


def edge(
    root: str,
    parent: str,
    derived: str,
    page: int,
    evidence_text: str,
    locator: str,
    modification_site: str,
    from_group: str,
    to_group: str,
    *,
    relation_type: str = "substituent_replacement",
    relation_status: str = "text_explicit",
    relation_confidence: str = "high",
    lineage: str = "01",
) -> dict[str, object]:
    return {
        "lineage": lineage,
        "root": root,
        "parent": parent,
        "derived": derived,
        "page": page,
        "evidence_text": evidence_text,
        "locator": locator,
        "modification_site": modification_site,
        "from_group": from_group,
        "to_group": to_group,
        "relation_type": relation_type,
        "relation_status": relation_status,
        "relation_confidence": relation_confidence,
    }


def unresolved(
    root: str,
    derived: str,
    page: int,
    locator: str,
    note: str,
    *,
    lineage: str = "01",
) -> dict[str, object]:
    return edge(
        root,
        MISSING,
        derived,
        page,
        note,
        locator,
        MISSING,
        MISSING,
        MISSING,
        relation_type="series_membership_only",
        relation_status="unresolved",
        relation_confidence="unresolved_direct_parent",
        lineage=lineage,
    )


def series(
    root: str,
    labels: list[str],
    page: int,
    locator: str,
    *,
    note: str = "The compound is in the reported SAR series, but the article does not identify a unique immediate parent.",
    lineage: str = "01",
) -> list[dict[str, object]]:
    return [unresolved(root, label, page, locator, f"Compound {label}: {note}", lineage=lineage) for label in labels]


def build_annotations() -> dict[str, dict[str, object]]:
    annotations: dict[str, dict[str, object]] = {
        "e04dfea8eedb": {
            "doi": "10.1021/acs.jmedchem.3c02190",
            "annotation_status": "needs_manual_review",
            "review_note": "The SI contains numbered structures 1-23, but the extracted article text provides activity observations without a unique direct parent-to-derived medicinal-chemistry path. Structures remain source-auditable and are not promoted to a lineage pair until the schemes are reviewed.",
            "edges": [],
        },
        "aad1af4320ce": {
            "doi": "10.1021/acs.jmedchem.4c03046",
            "annotation_status": "evidence_annotated",
            "review_note": "XCT is represented by 7a. Direct substitutions explicitly described in the article are retained. The chlorinated 17b record is kept as an unresolved mixture because it is inseparable from a propenyl byproduct. Broad 5a-6e, 9a-c, 11a-g, and 16a series records remain source candidates without invented direct parents.",
            "preferred_names": {"7a": "XCT", "17a": "CF3-substituted XCT", "17b": "chlorinated XCT mixture", "19": "BRF110"},
            "origins": {"7a": "prior_art_lead", "17a": "in_paper", "17b": "in_paper", "19": "in_paper"},
            "edges": [
                edge("7a", "7a", "7b", 5, "Introduction of a chlorine group at the angular C2 phenyl ring resulted in the less active compound 7b compared to parent XCT compound 7a.", "SAR; Figure 3C", "angular C2 phenyl ring", "hydrogen", "chlorine"),
                edge("7a", "7a", "7c", 5, "Substitution of the allyl group with a propyl group led to compound 7c.", "SAR; Figure 3C", "pyrimidine substituent", "allyl", "propyl"),
                edge("7a", "7c", "7d", 5, "The activity of 7c dropped further by incorporation of a chlorine group in the para position at the C2 phenyl ring to give 7d.", "SAR; Figure 3C", "angular C2 phenyl ring", "hydrogen", "chlorine"),
                edge("7a", "7a", "7e", 5, "Substitution of the allyl group with an isopropyl group resulted in compound 7e.", "SAR; Figure 3C", "pyrimidine substituent", "allyl", "isopropyl"),
                edge("7a", "7a", "7f", 5, "Substitution of the allyl group with the one-carbon-shorter ethyl group gave compound 7f.", "SAR; Figure 3C", "pyrimidine substituent", "allyl", "ethyl"),
                edge("7a", "7a", "17a", 8, "The CF3-substituted analogue of XCT, compound 17a, was predicted to bind in a similar pose to its parent compound.", "Figure 3D", "angular C2 phenyl ring", "hydrogen", "trifluoromethyl", relation_status="figure_explicit"),
                unresolved("7a", "17b", 7, "SAR; Figure 3D", "Compound 17b is a chlorinated analogue of XCT, but its direct parent is unresolved and the isolated material is an inseparable mixture."),
                unresolved("7a", "19", 8, "SAR summary; Table 1", "Compound 19 (BRF110) is a reported endpoint of the optimization series, but the available evidence does not identify one unique immediate parent."),
            ],
        },
        "2cd1c423645f": {
            "doi": "10.1021/acs.jmedchem.4c02751",
            "annotation_status": "evidence_annotated",
            "review_note": "MPX-004/MPX-007 are prior reference compounds. Compounds 1-3 and the 4-16 series are retained where the text gives only a series-level design; those records use unresolved direct parents. The 4-5-6-7-8-11-12 path follows explicit modification wording.",
            "preferred_names": {"MPX-004": "MPX-004 reference", "MPX-007": "MPX-007 reference"},
            "origins": {"MPX-004": "prior_art", "MPX-007": "prior_art"},
            "edges": [
                *series("MPX-004", ["1", "2", "3", "4"], 3, "Design rationale; Table 1", note="Compounds 1-4 are part of the new sulfone series, but the article does not identify a unique immediate parent for each individual record."),
                edge("MPX-004", "4", "5", 3, "The replacement of the methylene attached to the halogenated aromatic ring by a ketone in 5 led to a dramatic loss in potency.", "SAR; Table 1", "benzylic linker", "methylene", "ketone"),
                edge("MPX-004", "4", "6", 3, "The introduction of one fluorine substituent on the benzylic position in 6 gave a gain in activity compared to 4.", "SAR; Table 1", "benzylic position", "hydrogen", "fluorine"),
                edge("MPX-004", "6", "7", 3, "A second fluorine substituent was introduced to form benzylic CF2 compound 7.", "SAR; Table 1", "benzylic position", "CH2F", "CF2"),
                edge("MPX-004", "7", "8", 3, "The subsequent replacement of the CH2 next to the pyrazine ring by an O atom in 8 led to a slight decrease in activity.", "SAR; Table 1", "pyrazine-side linker", "methylene", "oxygen"),
                edge("MPX-004", "8", "11", 3, "The replacement of the 3,4-difluorophenyl left-hand side by a 3-chlorophenyl in 11 increased potency.", "SAR; Table 1", "left-hand aryl ring", "3,4-difluorophenyl", "3-chlorophenyl"),
                edge("MPX-004", "11", "12", 3, "The replacement of the 3-chlorophenyl by a 4-chloropyridine-2-yl, combined with methylation of the central pyrazine, produced 12.", "SAR; Table 1", "left-hand aryl and central pyrazine", "3-chlorophenyl; unmethylated pyrazine", "4-chloropyridin-2-yl; methylated pyrazine"),
                *series("4", ["9", "10", "13", "14", "15", "16"], 3, "SAR; Table 1"),
            ],
        },
        "35c6365ddfa1": {
            "doi": "10.1021/acs.jmedchem.3c01917",
            "annotation_status": "evidence_annotated",
            "review_note": "The article explicitly describes the indole-to-aminopyrazole change and the cyclopropyl sulfone replacements. Other numbered structures in the SI remain source candidates unless a unique parent is stated.",
            "edges": [
                edge("3", "3", "7", 3, "An aminopyrazole was a viable replacement for the indole of compound 3, giving compound 7.", "SAR; Figure 2", "hinge-binding heteroaromatic ring", "indole", "aminopyrazole", relation_type="ring_replacement"),
                edge("14", "14", "17", 4, "Replacement of the cyclopropyl sulfone with the similarly sized dimethylacetamide gave compound 17.", "SAR; Figure 3", "cyclopropyl sulfone", "cyclopropyl sulfone", "dimethylacetamide", relation_type="group_replacement"),
                edge("14", "14", "18", 4, "Replacement of the cyclopropyl sulfone with dimethylacetonitrile gave compound 18.", "SAR; Figure 3", "cyclopropyl sulfone", "cyclopropyl sulfone", "dimethylacetonitrile", relation_type="group_replacement"),
                edge("14", "18", "19", 4, "Ortho-substituted aryl compound 19 was evaluated as a follow-up analogue of 18.", "SAR; Figure 3", "azaindazole aryl vector", "hydrogen", "ortho substituent"),
                edge("14", "18", "20", 4, "Ortho-substituted aryl compound 20 was evaluated as a follow-up analogue of 18.", "SAR; Figure 3", "azaindazole aryl vector", "hydrogen", "ortho substituent"),
            ],
        },
        "9126813c6d98": {
            "doi": "10.1021/acs.jmedchem.3c01894",
            "annotation_status": "evidence_annotated",
            "review_note": "The initial scaffold switch is explicit in the text. The central-ring table gives a common compound 9 reference for 15-17, but the immediate-parent mapping is retained as unresolved until the graphical table is manually checked.",
            "edges": [
                edge("1", "1", "3", 2, "The N-substituted pyrazole 3 retained good potency at OX1 while switching the profile from the starting DORA series.", "Results and Discussion; Table 1", "central heteroaromatic ring", "benzene-like ring", "N-substituted pyrazole", relation_type="ring_replacement"),
                edge("1", "3", "4", 2, "The N-1-substituted triazole 4 was introduced as the related heteroaromatic analogue of 3.", "Results and Discussion; Table 1", "central heteroaromatic ring", "pyrazole", "N-1-substituted triazole", relation_type="ring_replacement"),
                edge("1", "4", "7", 2, "Moving the N-2-substituted triazole from the 2-position to the 3-position of the benzyl ring gave compound 7.", "Results and Discussion; Table 1", "benzyl-ring triazole position", "2-position", "3-position"),
                unresolved("9", "15", 3, "Central-ring modified triazolobenzamides; Table 3", "Compound 15 is listed in the central-ring modification table, but the unique immediate parent is not stated in the extracted evidence."),
                unresolved("9", "16", 3, "Central-ring modified triazolobenzamides; Table 3", "Compound 16 is listed in the central-ring modification table, but the unique immediate parent is not stated in the extracted evidence."),
                unresolved("9", "17", 3, "Central-ring modified triazolobenzamides; Table 3", "Compound 17 is listed in the central-ring modification table, but the unique immediate parent is not stated in the extracted evidence."),
            ],
        },
        "66b63d71b500": {
            "doi": "10.1021/acs.jmedchem.4c01691",
            "annotation_status": "evidence_annotated",
            "review_note": "Compound 1 is the selected lead. Most A2AR NAM analogues are retained as unresolved series members because the extracted text compares groups of compounds without assigning a single direct parent. This prevents false pair formation while preserving source-backed structure candidates.",
            "preferred_names": {"1": "selected A2AR NAM lead"},
            "origins": {"1": "in_paper"},
            "edges": [
                *series("1", ["3", "4", "5", "6", "7", "8", "9", "10", "13", "14", "15", "16", "17", "19", "20", "21", "28", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "45", "47", "48", "49", "50", "51"], 5, "SAR; Tables 1-5"),
            ],
        },
        "6f5323ca6636": {
            "doi": "10.1021/acs.jmedchem.3c02006",
            "annotation_status": "evidence_annotated",
            "review_note": "M1 is the hydroxamic-acid dual-target reference and M2 is the amide analogue. The remaining M-series structures are preserved as unresolved series members because the available text does not assign each one a unique direct parent.",
            "preferred_names": {"M1": "hydroxamic-acid reference", "M2": "amide analogue", "B401": "B401 lead", "Belinostat": "belinostat reference", "Tubacin": "tubacin reference"},
            "origins": {"M1": "in_paper", "M2": "in_paper", "B401": "prior_art", "Belinostat": "prior_art", "Tubacin": "prior_art"},
            "edges": [
                edge("M1", "M1", "M2", 7, "When the alkane chain was replaced by a nitrogen heterocycle while retaining the chain length, amide compound M2 showed increased sEH inhibitory activity relative to hydroxamic-acid M1.", "SAR; Figure 4", "HDAC warhead", "hydroxamic acid", "amide", relation_type="warhead_replacement"),
                *series("M1", [f"M{i}" for i in range(3, 25)], 10, "SAR; Table 3"),
            ],
        },
        "51180402d2ac": {
            "doi": "10.1021/acs.jmedchem.3c01687",
            "annotation_status": "no_supported_lineage",
            "review_note": "The local corpus contains complete SI structures for compounds 3 and 4, but no supported medicinal-chemistry modification path was extracted. No pair is created.",
            "edges": [],
        },
        "7ecfba90bd62": {
            "doi": "10.1021/acs.jmedchem.3c01662",
            "annotation_status": "evidence_annotated",
            "review_note": "The article explicitly compares 6d with the reference 6a for the meta-fluoro modification. Other 6-series members are retained as unresolved series records without assuming adjacency as parentage.",
            "edges": [
                edge("6a", "6a", "6d", 4, "Fluorine substitution at the meta position of the phenyl ring in 6d moderately decreased affinity and efficacy relative to 6a.", "SAR; Figure 3; Table 1", "phenyl ring meta position", "hydrogen", "fluorine"),
                *series("6a", ["6b", "6c", "6e", "6f", "6g", "6h", "6i", "6j", "6k", "6l", "6m", "6n"], 4, "SAR; Table 1"),
            ],
        },
        "7709b4e1637d": {
            "doi": "10.1021/acs.jmedchem.3c01938",
            "annotation_status": "needs_manual_review",
            "review_note": "The SI contains structures 1-16 and CMX990. The extracted evidence only mentions compound 10 in an NMR context and does not establish a unique direct modification path; no unsupported parentage is created.",
            "edges": [],
        },
        "3b16e57c63cb": {
            "doi": "10.1021/acs.jmedchem.3c02040",
            "annotation_status": "evidence_annotated",
            "review_note": "The source workbook is content-detected as XLSX despite its CSV extension. The methoxy-substituted pyridyl analogues 7 and 8 are retained as figure-supported descendants of the reported baseline 6; remaining structures await graphical parent review.",
            "edges": [
                edge("6", "6", "7", 3, "Introduction of a methoxy group at the ortho position of the nitrogen in the 3-pyridyl moiety generated compound 7.", "SAR; Figure 3A", "3-pyridyl ring", "hydrogen", "methoxy", relation_status="figure_explicit", relation_confidence="medium"),
                edge("6", "6", "8", 3, "Introduction of a methoxy group at the ortho position of the nitrogen in the 3-pyridyl moiety generated compound 8.", "SAR; Figure 3A", "3-pyridyl ring", "hydrogen", "methoxy", relation_status="figure_explicit", relation_confidence="medium"),
            ],
        },
        "a4380f187553": {
            "doi": "10.1021/acs.jmedchem.4c03104",
            "annotation_status": "needs_manual_review",
            "review_note": "The SI contains compounds 5-51, while the extracted article evidence references DHI/AQ numbering and a later optimized descendant without a reliable one-to-one mapping to the local SI labels. Structures remain source-auditable but no unsupported lineage is generated.",
            "edges": [],
        },
        "360b9bc1c4fe": {
            "doi": "10.1021/acs.jmedchem.4c02830",
            "annotation_status": "evidence_annotated",
            "review_note": "The 7a-s group is a terminal-phenyl SAR series with no single baseline stated for every analogue. The two explicit 7j heterocycle substitutions are retained as direct edges; all other 7-series members remain unresolved series records.",
            "edges": [
                edge("7a", "7j", "7n", 6, "Substitution of one CF3 group in 7j with aromatic 4-methyl-1H-imidazole produced compound 7n.", "SAR; Table 5", "terminal phenyl substituent", "trifluoromethyl", "4-methyl-1H-imidazolyl", relation_type="heterocycle_substitution"),
                edge("7a", "7j", "7o", 6, "Substitution of one CF3 group in 7j with morpholine produced compound 7o.", "SAR; Table 5", "terminal phenyl substituent", "trifluoromethyl", "morpholinyl", relation_type="heterocycle_substitution"),
                *series("7a", [f"7{letter}" for letter in "bcdefghiklmpqrs"], 3, "SAR; Figure 3; Tables 4-6"),
            ],
        },
        "2c57076f0b26": {
            "doi": "10.1021/acs.jmedchem.3c01715",
            "annotation_status": "evidence_annotated",
            "review_note": "Compound 8 is the macrocyclic inhibitor endpoint. The carbonate prodrug 7 is explicitly obtained from 8, while the 9-19 aryl series is retained as unresolved because the article compares substitution patterns without naming a unique parent for every member.",
            "edges": [
                edge("8", "8", "7", 6, "Compound 8 was converted into the carbonate prodrug 7 for in vivo antiviral evaluation.", "Scheme 2", "macrocycle alcohol", "alcohol", "carbonate prodrug", relation_type="prodrug_derivatization"),
                *series("8", [str(i) for i in range(9, 20)], 4, "SAR; Table 2"),
            ],
        },
        "f4b9ad99e0a3": {
            "doi": "10.1021/acs.jmedchem.4c02230",
            "annotation_status": "evidence_annotated",
            "review_note": "The meta-methoxy derivative 2 is explicitly described relative to compound 1. The broader 1-24 series is retained as unresolved because the text does not assign every substituted analogue a unique immediate parent.",
            "preferred_names": {"PF-07208254": "PF-07208254 reference", "BT2": "BT2 reference", "BT2F": "BT2F reference", "6": "PF-07328948"},
            "origins": {"PF-07208254": "prior_art", "BT2": "prior_art", "BT2F": "prior_art", "6": "in_paper"},
            "edges": [
                edge("1", "1", "2", 2, "The meta-methoxy substituted analogue 2 improved cell potency relative to compound 1.", "SAR; Table 2", "C3 aryl substituent", "chloro", "meta-methoxy"),
                *series("1", ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16a", "16b", "16c", "16d", "16e", "16f", "16g", "16h", "16i", "16j", "17", "18", "18a", "19", "20", "21", "22", "23", "24"], 2, "SAR; Tables 2-4"),
            ],
        },
        "265d6151a4f8": {
            "doi": "10.1021/acs.jmedchem.4c02254",
            "annotation_status": "evidence_annotated",
            "review_note": "Explicit parentage is retained for the terminal phenyl substitutions, linker expansion, and cross-series comparisons stated in the text. The remaining 8-series labels are kept as unresolved structure-backed series members.",
            "edges": [
                edge("8a", "8a", "8b", 5, "The para-dimethylamino substitution at the terminal phenyl group led to compound 8b.", "SAR; Table 1", "terminal phenyl group", "hydrogen", "dimethylamino"),
                edge("8a", "8a", "8c", 5, "The trifluoromethoxy substitution at the terminal phenyl group led to compound 8c.", "SAR; Table 1", "terminal phenyl group", "hydrogen", "trifluoromethoxy"),
                edge("8a", "8a", "8l", 5, "Insertion of oxygen in the phenoxyacetyl derivative 8l improved potency compared with 8a.", "SAR; Table 1", "P3 linker", "alkyl linker", "oxygen-containing linker", relation_type="linker_replacement"),
                edge("8a", "8r", "8s", 5, "The gem-dimethyl substitution at the linker of the 2-(phenylthio)acetyl moiety resulted in compound 8s compared with 8r.", "SAR; Table 1", "phenylthioacetyl linker", "unsubstituted linker", "gem-dimethyl linker"),
                edge("8a", "8n", "10c", 6, "Replacement of the phenyl ring with an indole system in 10c reduced the activity of 8n.", "SAR; Table 2", "P1 aromatic ring", "phenyl", "indole", relation_type="ring_replacement"),
                edge("8a", "9a", "10e", 6, "Comparing 10e with 9a showed the effect of moving the fluoro substituent from meta to ortho.", "SAR; Table 2", "terminal aryl fluoro position", "meta-fluoro", "ortho-fluoro", relation_type="positional_isomerization"),
                *series("8a", ["8d", "8e", "8f", "8g", "8h", "8i", "8j", "8k", "8m", "8n", "8o", "8p", "8q", "8t", "8u", "8v", "8w", "8x", "8y", "8z", "8aa", "8ab", "8ac", "8ad", "8ae", "9b", "10a", "10b", "10d", "10f", "12a", "12b", "13a"], 5, "SAR; Tables 1-3"),
            ],
        },
        "cc5929fc88ba": {
            "doi": "10.1021/acs.jmedchem.3c02316",
            "annotation_status": "evidence_annotated",
            "review_note": "The N17 cyano precursor 14 and its de-cyano analogue 15 form an explicit modification pair. Other naltrexone-derived records remain source candidates without a forced parent.",
            "edges": [
                edge("14", "14", "15", 3, "Removal of the N17 cyano group from precursor 14 yielded compound 15 and reduced TLR4 inhibitory activity.", "SAR; Figure S1", "N17 substituent", "cyano", "hydrogen", relation_type="deprotection_or_group_removal"),
            ],
        },
        "cf3d5e3ba03c": {
            "doi": "10.1021/acs.jmedchem.3c01989",
            "annotation_status": "evidence_annotated",
            "review_note": "ART-P1 and ART-P2 are explicitly described as ART-derived probes and are mapped to SI labels 6 and 9 respectively. Other natural products, controls, and synthesis intermediates are not assigned unsupported direct parents.",
            "preferred_names": {"ART": "artemisinin", "DART": "DART reference", "DHA": "dihydroartemisinin", "6": "ART-P1", "9": "ART-P2"},
            "origins": {"ART": "prior_art", "DART": "prior_art", "DHA": "prior_art", "6": "in_paper", "9": "in_paper"},
            "edges": [
                edge("ART", "ART", "6", 2, "ART-P1 was designed from ART by incorporating a diazirine photoreactive group and is recorded as compound 6 in the SI.", "Figure 2A; SI structure table", "C10 side chain", "parent ART side chain", "ART-P1 diazirine probe", relation_type="probe_derivatization", relation_status="figure_explicit"),
                edge("ART", "ART", "9", 2, "ART-P2 was designed from ART by incorporating a diazirine photoreactive group and is recorded as compound 9 in the SI.", "Figure 2A; SI structure table", "C10 side chain", "parent ART side chain", "ART-P2 diazirine probe", relation_type="probe_derivatization", relation_status="figure_explicit"),
            ],
        },
        "836f93c225ef": {
            "doi": "10.1021/acs.jmedchem.4c02415",
            "annotation_status": "evidence_annotated",
            "review_note": "The source label 6 (QXG-6442) is normalized to Paper-local label 6 while preserving the preferred name. Explicit changes from the quinoline/quinoxaline series and the methoxy/halogen scan are retained; broad library members without a stated direct parent remain unresolved.",
            "preferred_names": {"6": "QXG-6442"},
            "origins": {"6": "in_paper"},
            "edges": [
                edge("5", "5", "6", 5, "Further replacement of the 2-quinoxaline produced compound 6, QXG-6442, with a 2-imidazo[1,2-a]pyridine moiety.", "SAR; Table 1", "heteroaromatic gluing moiety", "2-quinoxaline", "2-imidazo[1,2-a]pyridine", relation_type="ring_replacement"),
                edge("6", "6", "6-Me", 5, "Compound 6-Me was synthesized by methylating the lead heteroaromatic nitrogen as a negative control.", "SAR; Table 1", "imidazo[1,2-a]pyridine N1", "nitrogen", "methylated carbon analogue", relation_type="heteroatom_blocking"),
                edge("6", "6", "14", 6, "Changing the carbonyl attachment of the imidazo[1,2-a]pyridine motif from the 2-position to the 3-position resulted in compound 14.", "SAR; Table 2", "carbonyl attachment position", "2-position", "3-position", relation_type="positional_isomerization"),
                edge("6", "6", "17", 6, "Replacing the 1-nitrogen with carbon afforded indolizine analogue 17.", "SAR; Table 2", "heteroaromatic ring N1", "nitrogen", "carbon", relation_type="heteroatom_replacement"),
                edge("6", "6", "22", 7, "The 6-methoxy modification in compound 22 increased potency over lead QXG-6442.", "SAR; Table 3", "isoindolinone aryl position", "hydrogen", "6-methoxy"),
                edge("6", "6", "23", 7, "Replacing the methoxy group with chlorine produced compound 23 while preserving potency.", "SAR; Table 3", "isoindolinone aryl position", "methoxy", "chloro"),
                edge("6", "6", "24", 7, "The 6-fluoro analogue 24 was compared with lead QXG-6442 in the fluorine substitution scan.", "SAR; Table 3", "isoindolinone aryl position", "hydrogen", "6-fluoro"),
                edge("6", "6", "25", 7, "The 7-methoxy analogue 25 was compared with lead QXG-6442 in the positional methoxy scan.", "SAR; Table 3", "isoindolinone aryl position", "hydrogen", "7-methoxy"),
                edge("6", "6", "26", 7, "The 7-fluoro analogue 26 was evaluated against the corresponding 6-fluoro compound 24.", "SAR; Table 3", "isoindolinone aryl position", "hydrogen", "7-fluoro"),
                edge("6", "6", "27", 7, "The 8-methoxy analogue 27 was compared with lead QXG-6442 in the positional methoxy scan.", "SAR; Table 3", "isoindolinone aryl position", "hydrogen", "8-methoxy"),
            ],
        },
        "cf88ca0c12c6": {
            "doi": "10.1021/acs.jmedchem.3c01981",
            "annotation_status": "evidence_annotated",
            "review_note": "The SI uses enantiomer-qualified labels. The leading stereo descriptor is preserved in the Paper-local normalization, so (R)-4 and (R)-5 remain separate entities rather than collapsing to numeric labels.",
            "edges": [
                edge("(R)-4", "(R)-4", "(R)-5", 2, "Installation of a methoxypropyl chain at R1 resulted in a three-fold potency increase for (R)-5 versus (R)-4.", "SAR; Figure 2; Table 1", "R1 side chain", "hydrogen", "methoxypropyl", relation_type="side_chain_installation"),
            ],
        },
        "eb9f347196d0": {
            "doi": "10.1021/acs.jmedchem.3c01764",
            "annotation_status": "evidence_annotated",
            "review_note": "The methyl-to-fluoro/ethyl modifications are explicitly anchored to XY-01. The later pyrimidine CF3 scan is retained as source evidence but not given an invented direct parent.",
            "edges": [
                edge("XY-01", "XY-01", "XY-06", 4, "The methyl group of XY-01 was replaced with a smaller fluoro group to give XY-06.", "SAR; Table 1", "methyl substituent", "methyl", "fluorine"),
                edge("XY-01", "XY-01", "XY-07", 4, "The methyl group of XY-01 was replaced with a larger ethyl group to give XY-07.", "SAR; Table 1", "methyl substituent", "methyl", "ethyl"),
            ],
        },
        "0de5157cf90a": {
            "doi": "10.1021/acs.jmedchem.3c01759",
            "annotation_status": "no_supported_lineage",
            "review_note": "The SI contains compounds 1-47, but the extracted article evidence describes natural-product SAR without a uniquely supported direct modification path. No pair is created.",
            "edges": [],
        },
        "0dbd1ded12e3": {
            "doi": "10.1021/acs.jmedchem.3c02064",
            "annotation_status": "evidence_annotated",
            "review_note": "The explicit hydroxyl-to-methoxy and methoxy-position comparisons are retained. The 1-to-3e/3f relationship is kept unresolved pending scheme review because the extracted text does not provide a unique direct mapping.",
            "edges": [
                edge("4a", "4a", "4f", 5, "The hydroxyl group of compound 4a was replaced by methoxy to yield compound 4f.", "SAR; Figure 4; Table 3", "aromatic hydroxyl", "hydroxyl", "methoxy"),
                edge("4l", "4l", "4m", 5, "The methoxy position was changed from compound 4l to give positional analogue 4m.", "SAR; Figure 4; Table 3", "methoxy position", "position in 4l", "position in 4m", relation_type="positional_isomerization"),
                edge("4l", "4l", "4n", 5, "The methoxy position was changed from compound 4l to give positional analogue 4n.", "SAR; Figure 4; Table 3", "methoxy position", "position in 4l", "position in 4n", relation_type="positional_isomerization"),
                unresolved("1", "3e", 4, "SAR; Scheme 2", "Compound 3e is in the halogenated alkyl-chain series, but the extracted evidence does not establish a unique immediate parent."),
                unresolved("1", "3f", 4, "SAR; Scheme 2", "Compound 3f is in the halogenated alkyl-chain series, but the extracted evidence does not establish a unique immediate parent."),
            ],
        },
        "5688225882e4": {
            "doi": "10.1021/acs.jmedchem.4c02200",
            "annotation_status": "evidence_annotated",
            "review_note": "The 5-F to 5-Cl/Br/I/CH3 scan and the positional chloride scan are explicit. The remaining reported comparisons are kept unresolved if the sentence does not establish one direct parent.",
            "edges": [
                edge("21", "21", "28", 4, "Replacement of the 5-F group of 21 with 5-Cl gave compound 28.", "SAR; Figure 3; Table 2", "indole 5-position", "5-fluoro", "5-chloro"),
                edge("21", "21", "29", 4, "Replacement of the 5-F group of 21 with 5-Br gave compound 29.", "SAR; Figure 3; Table 2", "indole 5-position", "5-fluoro", "5-bromo"),
                edge("21", "21", "30", 4, "Replacement of the 5-F group of 21 with 5-I gave compound 30.", "SAR; Figure 3; Table 2", "indole 5-position", "5-fluoro", "5-iodo"),
                edge("21", "21", "31", 4, "Replacement of the 5-F group of 21 with 5-CH3 gave compound 31.", "SAR; Figure 3; Table 2", "indole 5-position", "5-fluoro", "5-methyl"),
                edge("21", "28", "32", 4, "Changing the 5-Cl position of 28 to the 4-Cl position resulted in compound 32.", "SAR; Figure 3; Table 2", "indole chloride position", "5-chloro", "4-chloro", relation_type="positional_isomerization"),
                edge("21", "28", "33", 4, "Changing the 5-Cl position of 28 to the 6-Cl position resulted in compound 33.", "SAR; Figure 3; Table 2", "indole chloride position", "5-chloro", "6-chloro", relation_type="positional_isomerization"),
                edge("21", "28", "34", 4, "Changing the 5-Cl position of 28 to the 7-Cl position resulted in compound 34.", "SAR; Figure 3; Table 2", "indole chloride position", "5-chloro", "7-chloro", relation_type="positional_isomerization"),
                edge("21", "28", "38", 4, "Changing the 4-CF3 group of 28 to 3-CF3 gave compound 38.", "SAR; Figure 3; Table 2", "benzene CF3 position", "4-CF3", "3-CF3", relation_type="positional_isomerization"),
                edge("21", "28", "39", 4, "Changing the 4-CF3 group of 28 to 2-CF3 gave compound 39.", "SAR; Figure 3; Table 2", "benzene CF3 position", "4-CF3", "2-CF3", relation_type="positional_isomerization"),
                unresolved("21", "35", 4, "SAR; Figure 3; Table 2", "Compound 35 is discussed as a comparison analogue, but the direct parent is not uniquely specified in the extracted sentence."),
                unresolved("21", "36", 4, "SAR; Figure 3; Table 2", "Compound 36 is discussed as a comparison analogue, but the direct parent is not uniquely specified in the extracted sentence."),
                unresolved("28", "37", 4, "SAR; Figure 3; Table 2", "Compound 37 is discussed in the positional substitution scan, but the direct parent is not uniquely specified in the extracted sentence."),
            ],
        },
    }

    for annotation in annotations.values():
        annotation.setdefault("preferred_names", {})
        annotation.setdefault("origins", {})
        annotation.setdefault("activity_columns", [])
        annotation.setdefault("source_files", {})
        labels = {
            str(edge_row[key])
            for edge_row in annotation["edges"]
            for key in ("root", "parent", "derived")
            if edge_row[key] != MISSING
        }
        for label in labels:
            annotation["origins"].setdefault(label, "in_paper")
        annotation["annotation_version"] = "compound_lineages_v1_2026-09-08"
    return annotations


def main() -> None:
    ANNOTATION_DIR.mkdir(parents=True, exist_ok=True)
    for paper_id, annotation in build_annotations().items():
        output = {"paper_id": paper_id, **annotation}
        path = ANNOTATION_DIR / f"{paper_id}.json"
        path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{paper_id}: {len(annotation['edges'])} edges -> {path}")


if __name__ == "__main__":
    main()
