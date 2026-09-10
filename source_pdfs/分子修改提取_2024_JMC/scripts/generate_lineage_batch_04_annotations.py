#!/usr/bin/env python3
"""Generate the conservative, auditable lineage annotation boundary for batch 04.

The batch is deliberately source-first.  Explicit article statements become
directed edges; table/series observations without a unique direct parent are
kept as unresolved records rather than inferred by compound-number adjacency.
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANNOTATION_DIR = PROJECT_ROOT / "09_paper_review" / "auto_fill" / "lineage_annotations"
MISSING = "--"
VERSION = "compound_lineages_v1_2026-09-09-batch04"


def edge(root, parent, derived, page, text, locator, site=MISSING, old=MISSING, new=MISSING, *, relation="substituent_replacement", status="text_explicit", confidence="high"):
    return {
        "lineage": "01", "root": root, "parent": parent, "derived": derived,
        "page": page, "evidence_text": text, "locator": locator,
        "modification_site": site, "from_group": old, "to_group": new,
        "relation_type": relation, "relation_status": status,
        "relation_confidence": confidence,
    }


def unresolved(root, derived, page, text, locator):
    return edge(
        root, MISSING, derived, page, text, locator,
        relation="series_membership_only", status="unresolved",
        confidence="unresolved_direct_parent",
    )


def series(root, labels, page, text, locator):
    return [unresolved(root, label, page, text, locator) for label in labels]


def record(doi, edges, note, *, status="evidence_annotated", names=None, origins=None):
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
        "source_files": {},
        "edges": edges,
        "annotation_version": VERSION,
    }


def build_annotations():
    return {
        "548156debd90": record(
            "10.1021/acs.jmedchem.3c02336",
            [
                edge("7a", "7a", "8a", 3, "The chiral stability of the sulfone-substituted derivative was improved following the introduction of an ortho-methoxy substituent at the top phenyl moiety: the chiral stability of the ortho-methoxy-substituted sulfone-derivative 8a was established.", "SAR; Figure 1; Table 2", "top phenyl ortho position", "hydrogen", "methoxy"),
                edge("8a", "8a", "10a", 3, "Transferring the 6-fluoro indole substitution pattern to the sulfone series in combination with the para-fluorine substituent resulted in compound 10a when compared to compound 8a.", "SAR; Table 1", "indole substitution", "hydrogen", "6-fluoro", relation="substitution_pattern_transfer", confidence="medium"),
                edge("8a", "8a", "11a", 3, "Transferring the 6-fluoro indole substitution pattern to the sulfone series in combination with the para-chlorine substituent resulted in compound 11a when compared to compound 8a.", "SAR; Table 1", "indole/top phenyl substitution", "hydrogen", "6-fluoro/para-chloro", relation="substitution_pattern_transfer", confidence="medium"),
                edge("8a", "8a", "12a", 3, "Transferring the 5-methyl-6-methoxy indole substitution pattern to the sulfone series in combination with the para-fluorine substituent resulted in compound 12a when compared to compound 8a.", "SAR; Table 1", "indole substitution", "hydrogen", "5-methyl-6-methoxy", relation="substitution_pattern_transfer", confidence="medium"),
                edge("8a", "8a", "13a", 3, "Transferring the 5-methyl-6-methoxy indole substitution pattern to the sulfone series in combination with the para-chlorine substituent resulted in compound 13a when compared to compound 8a.", "SAR; Table 1", "indole/top phenyl substitution", "hydrogen", "5-methyl-6-methoxy/para-chloro", relation="substitution_pattern_transfer", confidence="medium"),
                *series("8a", ["9", "10a", "11a", "12a", "13a", "14a", "16a", "17a", "18a", "19a", "20a", "21a", "22a", "23a", "24a", "25a", "26a"], 6, "The article and supporting-information tables contain these sulfone/glycol series members; the extracted text does not identify a unique immediate parent for each.", "SAR; Tables 1-9"),
            ],
            "The 8a baseline and the named indole-pattern transfers are retained. Table-only analogues stay unresolved until the source figures are reviewed.",
        ),
        "cda62beb2e03": record(
            "10.1021/acs.jmedchem.4c02016",
            [
                edge("30", "30", "32", 5, "Substitution of the F atom in 30 with chlorine gave compound 32.", "SAR; Table 2", "benzene substituent", "fluorine", "chlorine"),
                edge("30", "30", "33", 5, "Substitution of the F atom in 30 with bromine gave compound 33.", "SAR; Table 2", "benzene substituent", "fluorine", "bromine"),
                edge("30", "30", "34", 5, "Substitution of the F atom in 30 with a cyano group gave compound 34.", "SAR; Table 2", "benzene substituent", "fluorine", "cyano"),
                edge("34", "34", "44", 6, "Substitution of methyl for trifluoromethyl in 34 gave compound 44.", "SAR; Table 2", "aryl substituent", "methyl", "trifluoromethyl"),
                edge("34", "34", "45", 6, "Substitution of methyl for trifluoromethyl in 34 gave compound 45.", "SAR; Table 2", "aryl substituent", "methyl", "trifluoromethyl"),
                edge("34", "34", "46", 6, "Substitution of methyl for trifluoromethyl in 34 gave compound 46.", "SAR; Table 2", "aryl substituent", "methyl", "trifluoromethyl"),
                edge("46", "46", "47", 6, "Substitution of chlorine for methyl of 46 gave compound 47.", "SAR; Table 2", "aryl substituent", "methyl", "chlorine"),
                edge("46", "46", "48", 6, "Substitution of bromine for methyl of 46 gave compound 48.", "SAR; Table 2", "aryl substituent", "methyl", "bromine"),
                edge("48", "48", "51", 6, "Introduction of an additional F atom on 48 gave compound 51.", "SAR; Table 2", "aryl substituent", "hydrogen", "fluorine"),
                edge("48", "48", "52", 6, "Introduction of an additional methyl group on 48 gave compound 52.", "SAR; Table 2", "aryl substituent", "hydrogen", "methyl"),
                *series("30", ["25", "26", "27", "28", "29", "31", "35", "36", "37", "38", "39", "40", "41", "42", "43", "49", "50", "53"], 5, "The SAR tables contain these analogues, but the extracted article text does not identify a unique immediate parent for each.", "SAR; Tables 1-2"),
            ],
            "The fluorine/halogen/cyano and methyl/trifluoromethyl scans are explicit; broad methyl-effect series records remain unresolved.",
            names={"9": "CLPP-1061"},
        ),
        "e5823b439fdc": record(
            "10.1021/acs.jmedchem.4c00250",
            [
                edge("7f", "7f", "7b", 2, "Replacement of 5-indolyl with 4-indolyl was evaluated as compound 7b.", "SAR; Figure 1", "indole orientation", "5-indolyl", "4-indolyl", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7c", 2, "Replacement of 5-indolyl with 6-indolyl was evaluated as compound 7c.", "SAR; Figure 1", "indole orientation", "5-indolyl", "6-indolyl", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7d", 2, "Replacement of 5-indolyl with 7-indolyl was evaluated as compound 7d.", "SAR; Figure 1", "indole orientation", "5-indolyl", "7-indolyl", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7e", 2, "Replacement of 5-indolyl with 2-indolyl was evaluated as compound 7e.", "SAR; Figure 1", "indole orientation", "5-indolyl", "2-indolyl", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7h", 2, "Compared to compound 7f, introduction of indazole gave compound 7h.", "SAR; Figure 1", "indole heteroaromatic fragment", "5-indolyl", "indazole", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7j", 2, "Compared to compound 7f, introduction of 4-azaindole gave compound 7j.", "SAR; Figure 1", "indole heteroaromatic fragment", "5-indolyl", "4-azaindole", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7k", 2, "Compared to compound 7f, introduction of 5-azaindole gave compound 7k.", "SAR; Figure 1", "indole heteroaromatic fragment", "5-indolyl", "5-azaindole", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7l", 2, "Compared to compound 7f, introduction of 6-azaindole gave compound 7l.", "SAR; Figure 1", "indole heteroaromatic fragment", "5-indolyl", "6-azaindole", relation="ring_replacement", confidence="medium"),
                edge("7f", "7f", "7u", 4, "Introduction of a methyl substituent onto indole at the 5-position gave compound 7u.", "SAR; Table 2", "indole 5-position", "hydrogen", "methyl"),
                edge("7f", "7f", "7w", 4, "Introduction of a methoxy substituent onto indole at the 5-position gave compound 7w.", "SAR; Table 2", "indole 5-position", "hydrogen", "methoxy"),
                edge("7f", "7f", "7y", 4, "Introduction of an isopropoxy substituent onto indole at the 5-position gave compound 7y.", "SAR; Table 2", "indole 5-position", "hydrogen", "isopropoxy"),
                *series("7f", ["7p", "7q", "7r", "7s", "7t", "7aa", "7ah", "7ai", "7aj"], 4, "The indole position/substitution table contains these series members without a unique immediate parent in the extracted evidence.", "SAR; Table 2"),
            ],
            "The indole-orientation and 5-position scans are linked to the named 7f baseline; the remaining table members remain unresolved.",
        ),
        "367784395644": record(
            "10.1021/acs.jmedchem.4c02177",
            [
                edge("7", "7", "9", 4, "The initial naphthalene and indole P3-prime groups were replaced by benzene in compound 9, which was compared with compound 7.", "SAR; Table 2", "P3-prime group", "naphthalene/indole", "benzene", relation="group_replacement", confidence="medium"),
                *series("LBM415", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "23", "24", "25", "26", "27", "28", "29", "30", "36", "43", "49"], 3, "The TDZ PDF inhibitor series is reported in these numbered tables, but the extracted text does not establish a unique direct parent for each member.", "SAR; Tables 1-5"),
            ],
            "The benzene-versus-naphthalene/indole comparison is the only direct structure relationship exposed clearly by the text layer; remaining series members are unresolved.",
            origins={"LBM415": "prior_art"},
        ),
        "566841ee4e78": record(
            "10.1021/acs.jmedchem.4c00825",
            [
                edge("12c", "12c", "12k", 5, "The contribution of the two methyl groups of 12b was compared to 12c, and two methyl groups were introduced into the ortho positions of the benzene ring to give 12k.", "SAR; Figure 2; Table 2", "benzene ortho positions", "hydrogen", "methyl", confidence="medium"),
                edge("12f", "12f", "15", 7, "The methyleneoxy linker was modified by deuteration to give compound 15, and compound 15 was tested with the bromo-to-chloro change.", "SAR; Table 3", "benzyl methyleneoxy linker", "CH2O", "CD2O/Cl", relation="linker_isotope_and_halogen_edit", confidence="medium"),
                edge("12f", "12f", "S2", 7, "The methyleneoxy linker (Ar-CH2O-) of 12f was modified with fluoromethyl (Ar-CH(CH2F)O-) to give compound S2.", "SAR; Table S2", "pyrazole methyleneoxy linker", "Ar-CH2O", "Ar-CH(CH2F)O", relation="linker_replacement"),
                *series("12f", ["12a", "12b", "12c", "12d", "12e", "12g", "12h", "12i", "12j", "13", "14a", "14b", "14c", "14d", "14k"], 6, "The CD73 analogue table contains these compounds, but the extracted text does not identify a unique immediate parent for each.", "SAR; Tables 1-3"),
            ],
            "The 12c-to-12k, S2 fluoromethyl-linker, and linker/deuterium records are retained; bromine/amino and aromatic scans remain unresolved until structure tables are reviewed.",
        ),
        "3148de26a8d7": record(
            "10.1021/acs.jmedchem.4c01341",
            [
                edge("1a", "1a", "2a", 3, "Compound 1a was converted into dichlorinated derivative 2a after treatment with phosphorus oxychloride.", "Synthetic Scheme", "pyridazine chlorination", "unmodified", "dichlorinated"),
                edge("1b", "1b", "2b", 3, "Compound 1b was converted into dichlorinated derivative 2b after treatment with phosphorus oxychloride.", "Synthetic Scheme", "pyridazine chlorination", "unmodified", "dichlorinated"),
                edge("10", "10", "11", 3, "Compound 10 was converted into dichlorinated derivative 11 after treatment with phosphorus oxychloride.", "Synthetic Scheme", "pyridazine chlorination", "unmodified", "dichlorinated"),
                edge("17", "17", "18", 3, "Compound 17 was converted into dichlorinated derivative 18 after treatment with phosphorus oxychloride.", "Synthetic Scheme", "pyridazine chlorination", "unmodified", "dichlorinated"),
                edge("P18", "P18", "P19", 6, "The nitrogen atom on piperidine was replaced by a fluorinated linear or branched alkyl group in P19.", "SAR; Table 3", "piperidine nitrogen", "nitrogen", "fluorinated alkyl", relation="heteroatom_replacement", confidence="medium"),
                edge("P18", "P18", "P20", 6, "The nitrogen atom on piperidine was replaced by a fluorinated linear or branched alkyl group in P20.", "SAR; Table 3", "piperidine nitrogen", "nitrogen", "fluorinated alkyl", relation="heteroatom_replacement", confidence="medium"),
                edge("P18", "P18", "P21", 6, "The nitrogen atom on piperidine was replaced by a fluorinated linear or branched alkyl group in P21.", "SAR; Table 3", "piperidine nitrogen", "nitrogen", "fluorinated alkyl", relation="heteroatom_replacement", confidence="medium"),
                *series("P18", ["P3", "P4", "P5", "P10", "P11", "P12", "P15", "P16", "P17", "P22", "P23", "P24", "P25", "P26", "P27", "P32", "P33", "P37", "P38"], 7, "These pyridazine/NLRP3 analogues are described in the structure-activity tables without a unique immediate parent in the extracted text.", "SAR; Tables 1-5"),
            ],
            "Synthetic chlorination and the named piperidine nitrogen replacements are explicit; the remaining P-series members are unresolved.",
        ),
        "262736df5806": record(
            "10.1021/acs.jmedchem.4c02792",
            [
                edge("8", "8", "9", 3, "Switching the piperidine group in 8 to a piperazine ring provided compound 9.", "SAR; Table 1", "basic ring", "piperidine", "piperazine", relation="ring_replacement"),
                edge("9", "9", "10", 3, "Introduction of a methyl group in the piperazine ring gave compound 10.", "SAR; Table 1", "piperazine ring", "hydrogen", "methyl"),
                edge("9", "9", "11", 3, "Introduction of an isopropyl group in the piperazine ring gave compound 11.", "SAR; Table 1", "piperazine ring", "hydrogen", "isopropyl"),
                edge("38", "38", "44", 4, "Replacement of the isopropyl in the R4 moiety with a methyl group gave compound 44.", "SAR; Table 4", "R4 substituent", "isopropyl", "methyl"),
                edge("38", "38", "46", 5, "The pyrimidine system was replaced by a 2-cyclopropylphenyl ring in compound 46.", "SAR; Table 5", "heteroaryl core", "pyrimidine", "2-cyclopropylphenyl", relation="ring_replacement", confidence="medium"),
                edge("38", "38", "47", 5, "The pyrimidine system was replaced by a 2-isopropylphenyl ring in compound 47.", "SAR; Table 5", "heteroaryl core", "pyrimidine", "2-isopropylphenyl", relation="ring_replacement", confidence="medium"),
                edge("38", "38", "48", 5, "The disubstituted pyrimidine was replaced by a 2-isopropylpyridin-3-yl moiety in compound 48.", "SAR; Table 5", "heteroaryl core", "disubstituted pyrimidine", "2-isopropylpyridin-3-yl", relation="ring_replacement", confidence="medium"),
            ],
            "The piperidine/piperazine, R4, and core-replacement relationships are retained; the broader USP1 analogue table remains outside the directed graph.",
        ),
        "1d74f0cb49aa": record(
            "10.1021/acs.jmedchem.3c01245",
            [
                edge("31", "31", "69", 3, "Key intermediate 31 was condensed with thiazolyl benzylamine to offer target compound 69.", "Synthetic Scheme 4", "benzamide N-substituent", "intermediate", "thiazolyl benzylamine", relation="late_stage_derivatization", confidence="medium"),
                edge("39", "39", "80", 4, "Intermediate 39 was converted into target compound 80 by condensation with Cbz-protected methylamine and deprotection.", "Synthetic Scheme", "benzamide N-substituent", "intermediate", "methylamine", relation="late_stage_derivatization", confidence="medium"),
                *series("RY796", ["43", "44", "45", "46", "47", "48", "49", "50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75", "76", "77", "78", "79", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89", "90", "91", "92", "93", "94", "95", "96"], 4, "The Kv2.1 optimization tables contain these labelled compounds, but the extracted text does not assign a unique immediate parent to each.", "SAR; Tables 1-5"),
            ],
            "The two synthetic transformations are source-backed; the large Kv2.1 table remains unresolved and will require structure-figure review.",
            origins={"RY796": "prior_art"},
        ),
        "be3fe48ae7ac": record(
            "10.1021/acs.jmedchem.3c02392",
            [
                edge("18", "18", "26a", 5, "When tetrahydropyran was replaced with 2-morpholinoethyl, compound 26a was obtained.", "SAR; Table 1", "solvent-exposed side chain", "tetrahydropyran", "2-morpholinoethyl", relation="side_chain_replacement"),
                edge("26a", "26a", "26ac", 7, "Replacement of the benzyl group with 6-methylpyridinyl gave compound 26ac.", "SAR; Table 2", "benzyl group", "benzyl", "6-methylpyridinyl", relation="ring_replacement", confidence="medium"),
                *series("18", ["26g", "26j", "26m", "26p", "26r", "26s", "26t", "26u", "26v", "26w", "26x", "26y", "26z", "26aa", "26ab", "33a", "33b", "33c", "33d", "33f", "33g", "33l"], 7, "The ERK2 analogue tables contain these substituted members, but the extracted evidence does not identify a unique immediate parent for each.", "SAR; Tables 2-3"),
            ],
            "The 26a side-chain and 26ac ring replacement are explicit; remaining ERK2 analogue labels remain unresolved.",
        ),
        "c258ca874e3e": record(
            "10.1021/acs.jmedchem.4c00504",
            [
                edge("16", "16", "17", 8, "Compound 17 showed a better cytokine inhibitory rate than ethyl-substituted compound 16, indicating that aryl substitution was more favorable.", "SAR; Table 2", "C7 hydroxyl substituent", "ethyl", "aryl", relation="group_replacement", confidence="medium"),
                edge("17", "17", "20", 8, "The inhibition rate fell when the benzene ring was replaced in compound 20 compared with compound 17.", "SAR; Table 2", "aryl ring", "benzene", "replacement ring", relation="ring_replacement", confidence="medium"),
                *series("5", ["12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49"], 8, "Compound 5 was selected as the hit for this large hydroxyl-derivatization series; the extracted text does not assign a unique immediate parent to every numbered analogue.", "SAR; Tables 1-3"),
            ],
            "The named 16-to-17 and 17-to-20 comparisons are retained; the remaining oridonin derivatives remain unresolved.",
            origins={"5": "in_paper"},
        ),
        "482f4d44f7c3": record(
            "10.1021/acs.jmedchem.4c01346",
            [
                edge("1a", "1a", "1c", 7, "Within the 2-substituted phenyl analogs, the chloro analog 1c was evaluated relative to the 1a vinyl sulfone series.", "SAR; Table 2", "5-aryl substituent", "hydrogen", "chloro", confidence="medium"),
                edge("1a", "1a", "1e", 7, "Within the 2-substituted phenyl analogs, the methyl analog 1e was evaluated relative to the 1a vinyl sulfone series.", "SAR; Table 2", "5-aryl substituent", "hydrogen", "methyl", confidence="medium"),
                edge("1a", "1a", "1f", 7, "Within the 2-substituted phenyl analogs, the trifluoromethyl analog 1f was evaluated relative to the 1a vinyl sulfone series.", "SAR; Table 2", "5-aryl substituent", "hydrogen", "trifluoromethyl", confidence="medium"),
                edge("1a", "1a", "4c", 7, "The saturated 5-cyclohexyl pyrazole 4c was evaluated as a lipophilic replacement at the 5-position.", "SAR; Table 2", "pyrazole 5-position", "aryl", "cyclohexyl", relation="ring_replacement", confidence="medium"),
                edge("1a", "1a", "24e", 10, "The alternative alpha-substituted vinyl sulfone 24e was compared to the beta-substituted vinyl sulfone 1a.", "SAR; Table 8", "vinyl sulfone warhead", "beta-substituted", "alpha-substituted", relation="warhead_isomerization", confidence="medium"),
                *series("1a", ["1d", "1j", "1k", "1l", "1m", "8d", "23a", "23b", "23c", "23d", "23e", "23f", "24b", "24c", "24d", "25c", "25d", "25e", "25f", "25g"], 7, "The vinyl-sulfone analogue tables contain these labelled compounds, but the extracted text does not establish a unique direct parent for each.", "SAR; Tables 2-13"),
            ],
            "The 1a scaffold and several warhead/aryl comparisons are retained conservatively; mixture-containing and table-only analogues remain unresolved.",
            origins={"1a": "prior_art"},
        ),
        "622d8d5d0c50": record(
            "10.1021/acs.jmedchem.4c00992",
            [
                edge("15", "15", "16", 4, "Methyl substitution resulted in compound 16 and increased potency compared to the unsubstituted pyrimidine.", "SAR; Table 3", "pyrimidine 6-position", "hydrogen", "methyl"),
                edge("15", "15", "17", 4, "Introduction of a trifluoromethyl group resulted in compound 17.", "SAR; Table 3", "pyrimidine 6-position", "hydrogen", "trifluoromethyl"),
                edge("15", "15", "18", 4, "Introduction of a methoxy group resulted in compound 18.", "SAR; Table 3", "pyrimidine 6-position", "hydrogen", "methoxy"),
                edge("15", "15", "19", 4, "Amino substitution yielded compound 19.", "SAR; Table 3", "pyrimidine 6-position", "hydrogen", "amino"),
                edge("19", "19", "21", 5, "Ethyl substitution elevated potency compared to the unsubstituted amino reference 19, giving compound 21.", "SAR; Table 3", "amino substituent", "hydrogen", "ethyl"),
                *series("15", ["20", "22", "23", "27", "28", "29", "30", "31", "32", "33"], 5, "The 9-substituted PI3K-alpha table contains these labelled derivatives, but the extracted text does not identify a unique immediate parent for each.", "SAR; Table 3"),
            ],
            "The pyrimidine 6-position scan is explicitly directed from the unsubstituted reference; later amino/alkyl variants remain conservative table-level records.",
        ),
        "315744adb452": record(
            "10.1021/acs.jmedchem.4c01325",
            [
                edge("1", "1", "2", 3, "Replacement of the pyrimidine with a urea gave compound 2.", "SAR; Table 1", "A-ring heterocycle", "pyrimidine", "urea", relation="ring_replacement"),
                edge("13", "13", "14", 5, "Methylation of the pendant hydroxy group on the oxazine produced compound 14.", "SAR; Table 3", "oxazine hydroxy group", "hydroxy", "methoxy", relation="methylation"),
                edge("15", "15", "20", 5, "Installation of a gem-difluoro group on the oxazine led to compound 20.", "SAR; Table 3", "oxazine", "unsubstituted", "gem-difluoro", relation="geminal_substitution"),
                edge("27", "27", "28", 6, "Introduction of a polar cyano residue on the cyclopropane gave compound 28.", "SAR; Table 4", "cyclopropane substituent", "methyl", "cyano"),
                edge("37", "37", "38", 7, "Installation of a spiro-tetrahydropyran resulted in compound 38.", "SAR; Table 6", "oxazine substituent", "non-spiro", "spiro-tetrahydropyran", relation="ring_fusion"),
                *series("1", ["15", "16", "19", "23", "24", "25", "26", "29", "30", "32", "33", "34", "35", "36", "37"], 6, "The ROCK2/azaindole analogue tables contain these labels, but the extracted text does not consistently specify a direct parent.", "SAR; Tables 2-6"),
            ],
            "The urea, oxazine, cyclopropane, and spiro changes are explicit; other table-only records remain unresolved.",
        ),
        "bb7b0d91006e": record(
            "10.1021/acs.jmedchem.4c01674",
            [
                edge("1", "1", "3a", 2, "Replacement of the trifluoromethyl moiety by a phenyl ring gave compound 3a.", "SAR; Table 1", "p-substituent", "trifluoromethyl", "phenyl", relation="ring_replacement", confidence="medium"),
                *series("1", ["3b", "3c", "3d", "6", "7e", "7t", "8a"], 4, "The PfFNT p-substituted inhibitor series contains these members, but the extracted text does not establish a unique immediate parent for each.", "SAR; Tables 1-3"),
            ],
            "The 3a replacement is retained as the clearest numbered transformation; p-amino/anilide series records remain unresolved.",
            origins={"1": "prior_art", "2": "prior_art"},
        ),
        "04e61596f895": record(
            "10.1021/acs.jmedchem.4c02422",
            [
                edge("A2", "A2", "A3", 3, "Conversion of the amine group in A2 to t-butyl carbamate resulted in compound A3.", "SAR; Table 1", "amine protection", "amine", "Boc carbamate", relation="protection"),
                edge("A4", "A4", "A9", 4, "Substitution of the 4-methylpiperazine moiety in A4 with 4-ethylpiperazine gave A9.", "SAR; Table 1", "piperazine N-substituent", "methyl", "ethyl"),
                edge("B2", "B2", "B4", 5, "The amine group in B2 was converted to t-butyl carbamate to give B4.", "SAR; Table 2", "amine protection", "amine", "Boc carbamate", relation="protection"),
                edge("B5", "B5", "B6", 5, "The amine group in B5 was converted to t-butyl carbamate to give B6.", "SAR; Table 2", "amine protection", "amine", "Boc carbamate", relation="protection"),
                edge("B18", "B18", "B31", 5, "Chlorine substitution at the 3-position of B18 gave B31.", "SAR; Table 2", "phenyl 3-position", "hydrogen", "chlorine"),
                *series("A1", ["A2", "A4", "A6", "A7", "A9", "B1", "B2", "B5", "B18", "B24", "B25", "B27", "B29", "B30"], 5, "The PLK1/PIS analogue tables contain these labels, but the extracted text does not assign a unique parent to every record.", "SAR; Tables 1-2"),
            ],
            "The amine-protection, piperazine, and B31 transformations are explicit; broader A/B series entries remain unresolved.",
        ),
        "9b9e5d0c40bc": record(
            "10.1021/acs.jmedchem.3c01795",
            [
                edge("12a", "12a", "13", 4, "Bromide analog 12a was converted to the amino analog 13.", "Synthetic Scheme 2", "pyridyl bromide", "bromide", "amino", relation="functional_group_conversion"),
                edge("12a", "12a", "15a", 4, "Bromide analog 12a was converted to methyl analog 15a with trimethylboroxine.", "Synthetic Scheme 3", "aryl bromide", "bromide", "methyl", relation="cross_coupling"),
                edge("12b", "12b", "15b", 4, "Bromide analog 12b was converted to methyl analog 15b with trimethylboroxine.", "Synthetic Scheme 3", "aryl bromide", "bromide", "methyl", relation="cross_coupling"),
                edge("11a", "11a", "58", 5, "The bromide of 11a was converted to an acetyl group in analog 58.", "Synthetic Scheme 4", "aryl bromide", "bromide", "acetyl", relation="cross_coupling", confidence="medium"),
                edge("10g", "10g", "33", 6, "Intermediate 10g underwent Paal-Knorr condensation to afford N-methyl analog 33.", "Synthetic Scheme 8", "pyridyl/side-chain region", "precursor", "N-methyl pyrrole", relation="ring_formation", confidence="medium"),
                edge("11g", "11g", "61", 5, "An aldehyde was installed on 11g to give compound 61.", "Synthetic Scheme 6", "aryl position", "hydrogen", "aldehyde", relation="formylation", confidence="medium"),
                *series("1", ["2", "3", "4", "5", "6", "12a", "12b", "18a", "18b", "20", "40", "41", "54", "55", "56"], 8, "The PfPKG pyrrole-series tables contain these labels, but the extracted text does not establish a unique immediate parent for every analogue.", "SAR; Figures 1-4"),
            ],
            "Synthetic conversion edges are retained where both precursor and product labels are named; broad SAR members remain unresolved.",
        ),
        "97dfe9492a7f": record(
            "10.1021/acs.jmedchem.3c02292",
            [
                edge("2", "2", "3", 3, "Hydrazine substitution of compound 2 prepared hydrazine derivative 3.", "Synthetic Scheme", "triazine substituent", "leaving group", "hydrazine", relation="late_stage_derivatization"),
                edge("28", "28", "36", 5, "One side arm of 28 was replaced by 4-benzylamine to obtain compound 36.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "4-benzylamine", relation="side_arm_replacement"),
                edge("28", "28", "37", 5, "One side arm of 28 was replaced by cyclohexylmethylamine to obtain compound 37.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "cyclohexylmethylamine", relation="side_arm_replacement"),
                edge("28", "28", "38", 5, "One side arm of 28 was replaced by furan-2-ylmethylamine to obtain compound 38.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "furan-2-ylmethylamine", relation="side_arm_replacement"),
                edge("28", "28", "39", 5, "One side arm of 28 was replaced by 4-fluorophenylamine to obtain compound 39.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "4-fluorophenylamine", relation="side_arm_replacement"),
                edge("28", "28", "40", 5, "One side arm of 28 was replaced by 4-methoxyphenylamine to obtain compound 40.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "4-methoxyphenylamine", relation="side_arm_replacement"),
                edge("28", "28", "41", 5, "One side arm of 28 was replaced by morpholine to obtain compound 41.", "SAR; Figure 2", "triazine side arm", "4-fluorophenylmethylamine", "morpholine", relation="side_arm_replacement"),
                edge("28", "28", "42", 6, "Both side arms of 28 were replaced by furan-2-ylmethylamine to give compound 42.", "SAR; Figure 2", "both triazine side arms", "mixed arms", "bis-furan-2-ylmethylamine", relation="side_arm_replacement"),
                edge("28", "28", "43", 6, "Both side arms of 28 were replaced by 4-methoxyphenylamine to give compound 43.", "SAR; Figure 2", "both triazine side arms", "mixed arms", "bis-4-methoxyphenylamine", relation="side_arm_replacement"),
                edge("28", "28", "44", 6, "Both side arms of 28 were replaced by morpholine to give compound 44.", "SAR; Figure 2", "both triazine side arms", "mixed arms", "bis-morpholino", relation="side_arm_replacement"),
            ],
            "The hydrazine and 28 side-arm replacement series are explicitly linked; the remaining triazine members are not assigned inferred parents.",
        ),
        "f81cf5ac9c0c": record(
            "10.1021/acs.jmedchem.4c00610",
            [
                edge("5", "5", "9", 6, "The cyclopentyl group of 5 was replaced by a phenyl group in compound 9.", "SAR; Table 2", "R1 group", "cyclopentyl", "phenyl", relation="ring_replacement"),
                edge("9", "9", "10", 6, "The benzyl group of 9 was replaced by a tert-butyl group in compound 10.", "SAR; Table 2", "R2 group", "benzyl", "tert-butyl", relation="group_replacement"),
                edge("9", "9", "12", 6, "Introduction of a chlorine atom at R2 in compound 12 led to a potent PI3K-delta inhibitor.", "SAR; Table 2", "R2 position", "hydrogen", "chlorine"),
                edge("12", "12", "14", 8, "Replacement of the chlorine atom with a methyl group gave compound 14.", "SAR; Table 3", "R2 substituent", "chlorine", "methyl", relation="group_replacement"),
                edge("12", "12", "17", 8, "Replacement of the chlorine atom with a methoxy group gave compound 17.", "SAR; Table 3", "R2 substituent", "chlorine", "methoxy", relation="group_replacement"),
                *series("5", ["11", "13", "15", "16", "18", "19"], 8, "The PI3K-delta pyridazinone table contains these analogue labels, but the extracted text does not establish a unique direct parent for each.", "SAR; Tables 2-3"),
            ],
            "The R1/R2 replacement chain is explicit for 5, 9, 10, 12, 14, and 17; other analogues remain unresolved.",
        ),
        "0fd48a620db8": record(
            "10.1021/acs.jmedchem.4c01241",
            [
                edge("10a", "10a", "10g", 4, "N-methyl substitution on the 4-pyrazole gave compound 10g.", "SAR; Table 2", "pyrazole nitrogen", "hydrogen", "methyl", relation="N_methylation"),
                edge("10a", "10a", "10h", 4, "N-methyl substitution on the 3-pyrazole gave compound 10h.", "SAR; Table 2", "pyrazole nitrogen", "hydrogen", "methyl", relation="N_methylation"),
                edge("10a", "10a", "10i", 4, "Introduction of N-methyl-4-imidazole at the 8-position gave compound 10i.", "SAR; Table 2", "8-position heterocycle", "carbocycle", "N-methyl-imidazole", relation="ring_replacement", confidence="medium"),
                edge("10a", "10a", "10j", 4, "Introduction of a N-substituted imidazole at the 8-position gave compound 10j.", "SAR; Table 2", "8-position heterocycle", "carbocycle", "N-substituted imidazole", relation="ring_replacement", confidence="medium"),
                edge("10a", "10a", "10k", 4, "Introduction of N-substituted pyrazole gave compound 10k.", "SAR; Table 2", "8-position heterocycle", "carbocycle", "N-substituted pyrazole", relation="ring_replacement", confidence="medium"),
                edge("10a", "10a", "10ah", 13, "The 8-pyrazole and 6-fluoro modifications produced the frontrunner analog WJM992 10ah.", "SAR; Table 7", "dihydroquinazolinone substituents", "parent scaffold", "8-pyrazole/6-fluoro", relation="lead_optimization", confidence="medium"),
            ],
            "The 10a heterocycle/N-methyl scan and WJM992 endpoint are retained; table-only analogues remain unresolved.",
            names={"10ah": "WJM992"},
        ),
        "2384986d4271": record(
            "10.1021/acs.jmedchem.4c01713",
            [
                edge("10", "10", "13", 5, "Replacement of the chlorine atom at position 4 of the aniline of compound 10 by fluorine gave compound 13.", "SAR; Table 1", "aniline 4-position", "chlorine", "fluorine", relation="halogen_exchange"),
                edge("4", "4", "16", 6, "Replacement of the methoxy group of compound 4 by a hydroxyl group gave compound 16.", "SAR; Table 1", "quinazoline methoxy", "methoxy", "hydroxyl", relation="group_replacement"),
                edge("17", "17", "19", 6, "Replacement of the chlorine atom of compound 17 by bromide gave compound 19.", "SAR; Table 1", "aniline chlorine", "chlorine", "bromine", relation="halogen_exchange"),
                edge("17", "17", "20", 6, "Replacement of the chlorine atom of compound 17 by fluorine gave compound 20.", "SAR; Table 1", "aniline chlorine", "chlorine", "fluorine", relation="halogen_exchange"),
                edge("17", "17", "21", 6, "Substitution of the hydroxyl function of compound 17 by an amine function gave compound 21.", "SAR; Table 1", "aniline substituent", "hydroxyl", "amine", relation="group_replacement"),
                edge("4", "4", "37", 7, "Replacing a methoxy group with a 2-diethylaminoethoxy chain gave compound 37.", "SAR; Table 2", "quinazoline methoxy", "methoxy", "diethylaminoethoxy", relation="side_chain_installation"),
                *series("4", ["5", "6", "7", "8", "9", "10", "11", "12", "14", "15", "18", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "38", "39", "40", "41", "42", "43"], 7, "The anilinoquinazoline table contains these labels, but the extracted text does not establish a unique direct parent for every analogue.", "SAR; Tables 1-2"),
            ],
            "The halogen, hydroxyl/amine, and long-chain substitutions are explicit; the remaining anilinoquinazoline series stays unresolved.",
        ),
        "73569644c5da": record(
            "10.1021/acs.jmedchem.4c00591",
            [
                edge("Phoenicein", "Phoenicein", "D228", 14, "The acetylation structural modification of Phoenicein resulted in D228.", "SAR; Figure 13E", "sugar region", "hydroxyl", "acetyl", relation="prodrug_derivatization", confidence="medium"),
                edge("D228", "D228", "7a", 16, "D228 is released in animals into Phoenicein, which is converted to the active aglycone compound 7a.", "SAR; Figure 13E", "glycoside/aglycone relationship", "glycoside", "aglycone", relation="prodrug_unmasking", confidence="medium"),
                edge("7a", "7a", "3a", 6, "Replacement of the isopropyl group by cyclopentyl gave compound 3a.", "SAR; Table 2", "aglycone substituent", "isopropyl", "cyclopentyl", relation="group_replacement", confidence="medium"),
                *series("D228", ["3b", "3c", "3d", "3e", "5a", "5b", "5c", "7b", "7c", "7d", "7e", "7f"], 6, "The D228/furanone glycoside SAR series contains these labelled compounds, but the extracted text does not identify a unique direct parent for each.", "SAR; Tables 1-3"),
            ],
            "The prodrug/aglycone chain and the named cyclopentyl modification are retained; other D228 series members remain unresolved.",
            origins={"Phoenicein": "prior_art", "D228": "in_paper"},
        ),
        "ede33eb21948": record(
            "10.1021/acs.jmedchem.3c02124",
            [
                edge("16", "16", "22", 4, "Replacement of the N-methylpyrazole group in compound 16 with hydrogen generated compound 22.", "SAR; Table 1", "CRBN-ligand substituent", "N-methylpyrazole", "hydrogen"),
                edge("16", "16", "23", 4, "Replacement of the N-methylpyrazole with a Br atom resulted in compound 23.", "SAR; Table 1", "CRBN-ligand substituent", "N-methylpyrazole", "bromine"),
                edge("16", "16", "26", 4, "Replacement of the N-methylpyrazole group with a larger alkyl substituent generated compound 26.", "SAR; Table 1", "CRBN-ligand substituent", "N-methylpyrazole", "larger alkyl", relation="side_group_replacement", confidence="medium"),
                edge("16", "16", "32", 5, "Conversion of the amide group in compound 16 into a CHCH2 group gave compound 32.", "SAR; Table 2", "linker amide", "amide", "CHCH2", relation="linker_replacement"),
                edge("38", "38", "40", 14, "SN2 substitution of pyrazole 38 with benzyl piperidine reagent 39 yielded compound 40.", "Synthetic Scheme", "pyrazole substitution", "pyrazole", "benzyl piperidyl", relation="late_stage_derivatization", confidence="medium"),
                edge("40", "40", "41", 14, "Compound 40 underwent Buchwald amination to give compound 41.", "Synthetic Scheme", "amine coupling", "amine precursor", "tetrahydroquinoline amine", relation="late_stage_derivatization", confidence="medium"),
                edge("48", "48", "17", 16, "Acid 48 was coupled with CRBN ligand TX16 to yield final compound 17.", "Synthetic Scheme", "CRBN conjugation", "acid", "TX16 conjugate", relation="late_stage_conjugation", confidence="medium"),
                edge("51", "51", "16", 16, "Key intermediate 51 underwent amide formation with amine 47a to assemble final compound 16.", "Synthetic Scheme", "terminal carboxylic acid", "carboxylic acid", "amide-linked CBP/p300 ligand", relation="late_stage_conjugation"),
                *series("16", ["18", "19", "20", "21", "24", "25", "27", "28", "29", "30", "31"], 4, "The CBP/p300 degrader table contains these final compounds, but the extracted text does not assign a unique direct parent to every analogue.", "SAR; Tables 1-2"),
            ],
            "The 16-centered SAR and several synthetic conjugation steps are explicit; the remaining degrader series stays unresolved.",
        ),
        "5c2d23f2662b": record(
            "10.1021/acs.jmedchem.3c01524",
            [
                edge("28", "28", "23", 3, "Fluorine was introduced at the para position of the phenyl moiety in compound 23.", "SAR; Table 1", "N-phenyl para position", "hydrogen", "fluorine"),
                edge("28", "28", "27", 3, "Hydroxyl was introduced at the para position of the phenyl moiety in compound 27.", "SAR; Table 1", "N-phenyl para position", "hydrogen", "hydroxyl"),
                edge("28", "28", "29", 3, "Methoxy substitution at the para position was evaluated as compound 29.", "SAR; Table 1", "N-phenyl para position", "hydrogen", "methoxy", confidence="medium"),
                edge("28", "28", "34", 3, "Isopropyl substitution at the para position was evaluated as compound 34.", "SAR; Table 1", "N-phenyl para position", "hydrogen", "isopropyl", confidence="medium"),
                edge("44", "44", "48", 5, "The para trifluoromethyl compound 48 exhibited activity comparable to compound 44.", "SAR; Table 3", "terminal phenyl substituent", "hydrogen", "trifluoromethyl", confidence="medium"),
                edge("44", "44", "49", 5, "A para-chlorine replacement gave compound 49.", "SAR; Table 3", "terminal phenyl substituent", "hydrogen", "chlorine", confidence="medium"),
                edge("44", "44", "50", 5, "A para-fluorine replacement gave compound 50.", "SAR; Table 3", "terminal phenyl substituent", "hydrogen", "fluorine", confidence="medium"),
                edge("44", "44", "66", 6, "Introduction of a hydroxyl group at position 6 of the isobenzofuranone scaffold gave compound 66.", "SAR; Table 4", "isobenzofuranone position 6", "hydrogen", "hydroxyl", confidence="medium"),
                *series("28", ["25", "30", "31", "39", "40", "41", "42", "43", "45", "46", "47", "58", "67", "68", "69", "70", "71", "72"], 6, "The NMDAR-GluN2B analogue tables contain these labels, but the extracted text does not establish a unique immediate parent for each.", "SAR; Tables 1-4"),
            ],
            "The para-substitution scans and terminal-template comparisons are retained; remaining pierardine-series labels remain unresolved.",
        ),
        "64cd821fe49d": record(
            "10.1021/acs.jmedchem.4c01755",
            [
                edge("3", "3", "79", 11, "Compound 79 confirms replacement of the carboxylic acid by a carboxamido group.", "SAR; Figure S52", "benzoic acid group", "carboxylic acid", "carboxamide", relation="group_replacement", confidence="medium"),
                edge("3", "3", "74", 7, "Replacement of the carboxylate group by a five-membered acidic heterocycle resulted in compounds 74-76.", "SAR; Table 4", "acidic group", "carboxylate", "acidic heterocycle", relation="group_replacement", confidence="medium"),
                edge("3", "3", "11", 6, "Substitution at the R1 position with bromine in compound 11 was compared with other furan substitutions.", "SAR; Table 2", "furan phenyl position", "hydrogen", "bromine", confidence="medium"),
                edge("3", "3", "40", 7, "Compound 40 is the unsubstituted derivative used for comparison in the substitution series.", "SAR; Table 3", "phenyl substituent", "hydrogen", "unsubstituted", confidence="medium"),
                *series("3", ["10", "17", "22", "23", "31", "32", "33", "34", "38", "47", "48", "49", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "74", "75", "76", "79", "80", "81", "82", "83", "84"], 7, "The GPR17 anthranilic-acid/furan table contains these labels, but the extracted text does not assign a unique direct parent to every analogue.", "SAR; Tables 1-5"),
            ],
            "The carboxylic-acid replacement and selected furan substitutions are retained; the broad GPR17 table remains unresolved.",
            origins={"3": "prior_art"},
        ),
    }


def main() -> None:
    ANNOTATION_DIR.mkdir(parents=True, exist_ok=True)
    annotations = build_annotations()
    for paper_id, payload in annotations.items():
        output = {"paper_id": paper_id, **payload}
        (ANNOTATION_DIR / f"{paper_id}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{paper_id}: {len(payload['edges'])} edges")
    print(f"wrote {len(annotations)} batch-04 annotation files")


if __name__ == "__main__":
    main()
