"""Publish source-reviewed Batch 03/04 structure repairs.

Keep every manually reconstructed graph in one auditable manifest before it is
merged into the authoritative structure tables.
"""

from __future__ import annotations

from lineage_structure_reconstruction import (
    build_external_identifier_work_row,
    build_reviewed_structure_work_row,
    publish_reviewed_structure_candidates,
)


REVIEWED_REPAIRS = [
    {
        "paper_id": "548156debd90",
        "compound_entity_id": "CMP-548156debd90-9",
        "compound_label": "9",
        "canonical_isomeric_smiles": (
            "COc1cc(NC(C(=O)c2c[nH]c3ccccc23)c2ccc(F)cc2)"
            "cc(S(=O)(=O)CCCO)c1"
        ),
        "source_id": "figshare:25305994:44727064",
        "source_file": "jm3c02336_si_002.csv",
        "source_locator": "SI CSV row 10; article compound 9",
        "source_label": "9",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "exact_complete_structure_match",
        "decision_note": (
            "The SI machine-readable structure table identifies row 10 as "
            "compound 9. The source SMILES is a complete single-component "
            "graph and is recorded after RDKit canonicalization; the article "
            "label is 9, not a 9a-9e series."
        ),
        "stereochemistry_status": "source_encoded",
        "scaffold_smiles": "--",
        "r_group_assignments": "--",
        "attachment_mapping": "--",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-10g",
        "compound_label": "10g",
        "canonical_isomeric_smiles": (
            "O=C(CC(C(=O)c1ccc(F)cc1)c1ccncc1)"
            "C1CCN(C(=O)OCc2ccccc2)CC1"
        ),
        "source_id": "article:9b9e5d0c40bc",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf"
        ),
        "source_locator": "Main PDF page 3, Scheme 2, intermediate 10g",
        "source_label": "10g",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Scheme 2 shows 10g as the Cbz-protected piperidinyl diketone "
            "formed from the unsubstituted pyridyl ketone 9g and the Cbz "
            "alpha-bromoketone. The complete graph is reconstructed from the "
            "two carbonyls, the 4-fluorophenyl/pyridyl groups, and the "
            "4-piperidyl Cbz substituent; no source stereochemistry is assigned."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "--",
        "r_group_assignments": "9g alpha-methylene -> CH2C(=O)-4-(N-Cbz)piperidine",
        "attachment_mapping": "Diketone chain links the aryl ketone alpha carbon to piperidine C4 ketone",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-11a",
        "compound_label": "11a",
        "canonical_isomeric_smiles": (
            "O=C(OCc1ccccc1)N1CCC(c2cc(-c3ccnc(Br)c3)"
            "c(-c3ccc(F)cc3)[nH]2)CC1"
        ),
        "source_id": "article:9b9e5d0c40bc",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf"
        ),
        "source_locator": "Main PDF page 3, Scheme 2, intermediate 11a",
        "source_label": "11a",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Scheme 2 identifies 11a as the Paal-Knorr pyrrole intermediate "
            "with R1a = Br, R1b = H, R5 = F, and a Cbz-protected piperidine. "
            "The neutral organic graph is recorded; the later hydrochloride "
            "salt form is not included."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "--",
        "r_group_assignments": "pyridine R1a = Br; piperidine N = Cbz",
        "attachment_mapping": "Pyrrole C substituents retain pyridyl, p-fluorophenyl, and 4-piperidyl groups",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-11g",
        "compound_label": "11g",
        "canonical_isomeric_smiles": (
            "O=C(OCc1ccccc1)N1CCC(c2cc(-c3ccncc3)"
            "c(-c3ccc(F)cc3)[nH]2)CC1"
        ),
        "source_id": "article:9b9e5d0c40bc",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf"
        ),
        "source_locator": "Main PDF page 3, Scheme 2, intermediate 11g",
        "source_label": "11g",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Scheme 2 identifies 11g as the unsubstituted pyridyl/p-fluoro-"
            "phenyl Paal-Knorr intermediate with a Cbz-protected piperidine. "
            "Its complete graph is retained as the precursor used in Schemes "
            "6 and 8; no salt counterion is included."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "--",
        "r_group_assignments": "pyridine R1a = H, R1b = H; piperidine N = Cbz",
        "attachment_mapping": "Pyrrole C substituents retain pyridyl, p-fluorophenyl, and 4-piperidyl groups",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-58",
        "compound_label": "58",
        "canonical_isomeric_smiles": (
            "CC(=O)c1cc(-c2cc(C3CCNCC3)[nH]c2-c2ccc(F)cc2)ccn1"
        ),
        "source_id": "article:9b9e5d0c40bc",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf"
        ),
        "source_locator": "Main PDF page 4, Scheme 4, compound 58",
        "source_label": "58",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Scheme 4 shows Stille conversion of the bromopyridine in 11a to "
            "the acetyl group of 58, followed by removal of the piperidine "
            "Cbz group. The source labels R1a = COCH3 and R = H; the neutral "
            "organic graph is recorded without the hydrochloride counterion."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "--",
        "r_group_assignments": "11a pyridine Br -> acetyl; piperidine N-Cbz -> N-H",
        "attachment_mapping": "Acetyl carbonyl carbon is directly bonded to the pyridine R1a position",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-61",
        "compound_label": "61",
        "canonical_isomeric_smiles": (
            "O=Cc1c(C2CCN(C(=O)OCc3ccccc3)CC2)[nH]"
            "c(-c2ccc(F)cc2)c1-c1ccncc1"
        ),
        "source_id": "article:9b9e5d0c40bc",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf"
        ),
        "source_locator": "Main PDF page 5, Scheme 6, compound 61",
        "source_label": "61",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "visual_graph_match",
        "decision_note": (
            "Scheme 6 shows Vilsmeier-Haack formylation of 11g at the free R2 "
            "pyrrole position to give 61. The Cbz-protected piperidine and "
            "unsubstituted pyridyl/p-fluorophenyl groups are retained, and the "
            "source drawing does not specify new stereochemistry."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "--",
        "r_group_assignments": "11g pyrrole R2-H -> formyl",
        "attachment_mapping": "Formyl carbon is directly bonded to the previously unsubstituted pyrrole carbon",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-6",
        "compound_label": "6",
        "canonical_isomeric_smiles": (
            "CS(=O)(=O)Cc1onc(-c2cccc(Cl)c2)c1-"
            "c1ccnc(N[C@@H]2CCN(C(=O)c3nccs3)C2)n1"
        ),
        "source_id": "article-and-external:9b9e5d0c40bc:PMC9132199",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "gilleran-et-al-2024-structure-activity-relationship-of-a-"
            "pyrrole-based-series-of-pfpkg-inhibitors-as-anti-malarials.pdf; "
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC9132199/"
        ),
        "source_locator": (
            "Main PDF page 2, Figure 1, compound 6; "
            "Eck et al. 2022 Figure 1, compound 3"
        ),
        "source_label": "6 (Eck compound 3)",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "The current article's compound 6 and Eck et al. 2022 compound 3 "
            "show the same complete graph. The isoxazole bears 3-chlorophenyl, "
            "2-aminopyrimidinyl, and methylsulfonylmethyl substituents. The "
            "pyrimidine amino group is attached to the source-encoded (R)-3-"
            "aminopyrrolidine whose ring nitrogen carries thiazole-2-carbonyl. "
            "RDKit gives C23H21ClN6O4S2 and one R stereocenter."
        ),
        "stereochemistry_status": "source_encoded",
        "scaffold_smiles": "N[C@@H]1CCN(C(=O)c2nccs2)C1",
        "r_group_assignments": (
            "isoxazole = 3-chlorophenyl / pyrimidinyl / CH2SO2Me; "
            "pyrimidine NH = (R)-3-aminopyrrolidine-thiazole-2-carboxamide"
        ),
        "attachment_mapping": (
            "Isoxazole C substituents are mapped independently from both "
            "source figures; pyrrolidine connectivity is cross-checked against "
            "the shared RY-1-165/8EM8 WLK side-chain graph"
        ),
    },
    {
        "paper_id": "cda62beb2e03",
        "compound_entity_id": "CMP-cda62beb2e03-40",
        "compound_label": "40",
        "canonical_isomeric_smiles": "N=C(N)n1nccc1",
        "source_id": "article:cda62beb2e03",
        "source_file": (
            "source_pdfs/case5 volume67 issue1-4/"
            "sun-et-al-2025-harnessing-the-magic-methyl-effect-discovery-of-"
            "clpp-2068-as-a-novel-hsclpp-activator-for-the-treatment.pdf"
        ),
        "source_locator": (
            "Main PDF page 4, Scheme 1, fixed structure labelled 40; "
            "page 15, General Procedure B, identified as "
            "1H-pyrazole-1-carboxamidine hydrochloride"
        ),
        "source_label": "40",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Compound 40 is a fixed reagent, 1H-pyrazole-1-carboxamidine "
            "hydrochloride. The neutral organic graph is recorded here; the "
            "hydrochloride counterion is noted in the source but is not part "
            "of the organic SMILES graph. In contrast, 39 and 41 use variable "
            "R2 groups and are intentionally not assigned a single SMILES."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "N=C(N)n1nccc1",
        "r_group_assignments": "pyrazole N1 -> carboxamidine",
        "attachment_mapping": "N1 of pyrazole bonded to the carboxamidine carbon",
    },
    {
        "paper_id": "381572722037",
        "compound_entity_id": "CMP-381572722037-26aprime",
        "compound_label": "26a′",
        "canonical_isomeric_smiles": (
            "C[C@H](Nc1cc(N2CCN(C(N)=O)CC2)nc2nc(C3CC3)nn12)"
            "c1ccc2ccccc2c1"
        ),
        "source_id": "article:381572722037",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "kim-et-al-2024-discovery-of-triazolopyrimidine-derivatives-as-"
            "selective-p2x3-receptor-antagonists-binding-to-an.pdf"
        ),
        "source_locator": (
            "PDF page 7, SAR stereochemistry paragraph; PDF page 19, "
            "experimental entry for (S)-26a-prime"
        ),
        "source_label": "26a′",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "The article identifies 26a-prime as the enantiomer of 26a and "
            "the experimental section gives the full (S)-configured IUPAC "
            "name. The source-confirmed 26a graph has one (R) stereocenter, "
            "so only that center was inverted; connectivity was preserved."
        ),
        "stereochemistry_status": "source_encoded",
        "scaffold_smiles": (
            "C[C@@H](Nc1cc(N2CCN(C(N)=O)CC2)nc2nc(C3CC3)nn12)"
            "c1ccc2ccccc2c1"
        ),
        "r_group_assignments": "26a (R) benzylic center -> 26a-prime (S)",
        "attachment_mapping": (
            "No connectivity change; invert the sole benzylic stereocenter "
            "specified by the experimental name"
        ),
    },
    {
        "paper_id": "97dfe9492a7f",
        "compound_entity_id": "CMP-97dfe9492a7f-2",
        "compound_label": "2",
        "canonical_isomeric_smiles": (
            "Clc1nc(NCc2ccc(F)cc2)nc(NCc2ccc(F)cc2)n1"
        ),
        "source_id": "article:97dfe9492a7f",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "xie-et-al-2024-from-synergy-to-monotherapy-discovery-of-novel-"
            "2-4-6-trisubstituted-triazine-hydrazone-derivatives-with.pdf"
        ),
        "source_locator": (
            "PDF page 3, Scheme 1; PDF page 11, experimental entry for 2"
        ),
        "source_label": "2",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 and the experimental name identify 2 as the cyanuric "
            "chloride product bearing two 4-fluorobenzylamino arms and one "
            "remaining triazine chloride."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "Clc1ncncn1",
        "r_group_assignments": (
            "two triazine C-Cl sites -> NH-CH2-(4-fluorophenyl); one C-Cl retained"
        ),
        "attachment_mapping": (
            "Scheme 1 triazine positions 2 and 4 carry 4-fluorobenzylamino arms"
        ),
    },
    {
        "paper_id": "97dfe9492a7f",
        "compound_entity_id": "CMP-97dfe9492a7f-3",
        "compound_label": "3",
        "canonical_isomeric_smiles": (
            "NNc1nc(NCc2ccc(F)cc2)nc(NCc2ccc(F)cc2)n1"
        ),
        "source_id": "article:97dfe9492a7f",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "xie-et-al-2024-from-synergy-to-monotherapy-discovery-of-novel-"
            "2-4-6-trisubstituted-triazine-hydrazone-derivatives-with.pdf"
        ),
        "source_locator": (
            "PDF page 3, Scheme 1; PDF page 11, experimental entry for 3"
        ),
        "source_label": "3",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 explicitly converts the sole remaining triazine "
            "chloride of 2 into hydrazine derivative 3 while retaining both "
            "4-fluorobenzylamino arms."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "NNc1ncncn1",
        "r_group_assignments": (
            "remaining triazine C-Cl in 2 -> NH-NH2; both benzylamino arms retained"
        ),
        "attachment_mapping": (
            "Scheme 1 hydrazine substitutes the third triazine carbon"
        ),
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-1a",
        "compound_label": "1a",
        "canonical_isomeric_smiles": "O=c1[nH][nH]c(=O)c2c1CCCC2",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": "PDF page 3, Scheme 1, A-ring key for 1a",
        "source_label": "1a",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 assigns the saturated six-membered A ring to the "
            "pyridazine-dione starting material 1a."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "O=c1[nH][nH]c(=O)c2c1CCCC2",
        "r_group_assignments": "A = saturated six-membered ring",
        "attachment_mapping": "A ring fused across the two adjacent scaffold carbons",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-2a",
        "compound_label": "2a",
        "canonical_isomeric_smiles": "Clc1nnc(Cl)c2c1CCCC2",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": "PDF page 3, Scheme 1, 1a to 2a",
        "source_label": "2a",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 explicitly converts both carbonyl positions of 1a to "
            "chlorides with POCl3 while retaining its fused A ring."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "Clc1nnc(Cl)c2c1CCCC2",
        "r_group_assignments": "1a carbonyl oxygens -> two chlorides",
        "attachment_mapping": "Fused saturated A ring retained from 1a",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-1b",
        "compound_label": "1b",
        "canonical_isomeric_smiles": "O=c1[nH][nH]c(=O)c2ccccc12",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": "PDF page 3, Scheme 1, A-ring key for 1b",
        "source_label": "1b",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 assigns the benzene A ring to the phthalazine-dione "
            "starting material 1b."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "O=c1[nH][nH]c(=O)c2ccccc12",
        "r_group_assignments": "A = benzene",
        "attachment_mapping": "A ring fused across the two adjacent scaffold carbons",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-2b",
        "compound_label": "2b",
        "canonical_isomeric_smiles": "Clc1nnc(Cl)c2ccccc12",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": "PDF page 3, Scheme 1, 1b to 2b",
        "source_label": "2b",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 explicitly converts both carbonyl positions of 1b to "
            "chlorides with POCl3 while retaining the fused benzene ring."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "Clc1nnc(Cl)c2ccccc12",
        "r_group_assignments": "1b carbonyl oxygens -> two chlorides",
        "attachment_mapping": "Fused benzene A ring retained from 1b",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-10",
        "compound_label": "10",
        "canonical_isomeric_smiles": "O=c1[nH][nH]c(=O)c2c1C1CCC2C1",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": (
            "PDF page 3, Scheme 1 A-ring key; PDF page 4, Scheme 2"
        ),
        "source_label": "10",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Schemes 1 and 2 independently show 10 as the pyridazine-dione "
            "fused to the norbornane-type A ring. The drawings do not assign "
            "bridgehead stereochemistry."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "O=c1[nH][nH]c(=O)c2c1C1CCC2C1",
        "r_group_assignments": "A = norbornane-type bridged ring",
        "attachment_mapping": "Bridged A ring fused across its adjacent alkene-derived carbons",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-11",
        "compound_label": "11",
        "canonical_isomeric_smiles": "Clc1nnc(Cl)c2c1C1CCC2C1",
        "source_id": "article-and-si:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf; "
            "jm4c01341_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 4, Scheme 2; SI PDF page 7 (S7), compound 11"
        ),
        "source_label": "11",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 2 explicitly chlorinates both carbonyl positions of 10 "
            "to give 11; SI S7 independently displays the same complete "
            "graph. Bridgehead stereochemistry is not assigned."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "Clc1nnc(Cl)c2c1C1CCC2C1",
        "r_group_assignments": "10 carbonyl oxygens -> two chlorides",
        "attachment_mapping": "Norbornane-type fused A ring retained from 10",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-17",
        "compound_label": "17",
        "canonical_isomeric_smiles": "O=c1[nH][nH]c(=O)c2c1C1CCC2CC1",
        "source_id": "article:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf"
        ),
        "source_locator": (
            "PDF page 3, Scheme 1 A-ring key; PDF page 4, Scheme 3"
        ),
        "source_label": "17",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Schemes 1 and 3 independently show 17 as the pyridazine-dione "
            "fused to the bicyclo[2.2.2]octane-type A ring."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "O=c1[nH][nH]c(=O)c2c1C1CCC2CC1",
        "r_group_assignments": "A = bicyclo[2.2.2]octane-type bridged ring",
        "attachment_mapping": "Bridged A ring fused across its adjacent alkene-derived carbons",
    },
    {
        "paper_id": "3148de26a8d7",
        "compound_entity_id": "CMP-3148de26a8d7-18",
        "compound_label": "18",
        "canonical_isomeric_smiles": "Clc1nnc(Cl)c2c1C1CCC2CC1",
        "source_id": "article-and-si:3148de26a8d7",
        "source_file": (
            "source_pdfs/case volume67 issue14-18/"
            "fu-et-al-2024-discovery-of-potent-specific-and-orally-available-"
            "nlrp3-inflammasome-inhibitors-based-on-pyridazine.pdf; "
            "jm4c01341_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 4, Scheme 3; SI PDF page 7 (S7), compound 18"
        ),
        "source_label": "18",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 3 explicitly chlorinates both carbonyl positions of 17 "
            "to give 18; SI S7 independently displays the same complete graph."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": "Clc1nnc(Cl)c2c1C1CCC2CC1",
        "r_group_assignments": "17 carbonyl oxygens -> two chlorides",
        "attachment_mapping": "Bicyclo[2.2.2]octane-type fused A ring retained from 17",
    },
    {
        "paper_id": "73569644c5da",
        "compound_entity_id": "CMP-73569644c5da-phoenicein",
        "compound_label": "Phoenicein",
        "canonical_isomeric_smiles": (
            "O=C1C(O[C@H]2[C@H](O)[C@@H](O)[C@H](O)[C@@H](CO)O2)="
            "C(C)O/C1=C(C)\\C"
        ),
        "source_id": "figshare:27066983:49298117",
        "source_file": "jm4c00591_si_002.csv",
        "source_locator": (
            "CSV row 2, Compound_ID 1; main PDF pages 3 and 18 identify "
            "Phoenicein as compound 1"
        ),
        "source_label": "1 (Phoenicein)",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "exact_complete_structure_match",
        "decision_note": (
            "The main article explicitly identifies Phoenicein as compound "
            "1, and the SI structure CSV supplies the complete isomeric "
            "SMILES for Compound_ID 1."
        ),
        "stereochemistry_status": "source_encoded",
        "scaffold_smiles": "O=C1C(O)=C(C)O/C1=C(C)\\C",
        "r_group_assignments": "aglycone O -> beta-D-glucopyranosyl group",
        "attachment_mapping": (
            "SI row 2 glycosidic oxygen and article compound 1/Phoenicein identity"
        ),
    },
    {
        "paper_id": "73569644c5da",
        "compound_entity_id": "CMP-73569644c5da-7f",
        "compound_label": "7f",
        "canonical_isomeric_smiles": (
            "O=C1C(O)=C(C)O/C1=C2CCN(C(C)=O)CC\\2"
        ),
        "source_id": "article:73569644c5da",
        "source_file": (
            "source_pdfs/case3 volume67 issue 19-22/"
            "tang-et-al-2024-from-hit-to-lead-discovery-of-first-in-class-"
            "furanone-glycoside-d228-derived-from-chimonanthus.pdf"
        ),
        "source_locator": (
            "PDF page 17, experimental section 4.2.1.6 for compound 7f"
        ),
        "source_label": "7f",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "The experimental section gives the complete name "
            "2-(1-acetylpiperidin-4-ylidene)-4-hydroxy-5-methylfuran-"
            "3(2H)-one and matching MS for 7f. The graph is the explicitly "
            "N-acetylated analogue of source-confirmed 7e."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "O=C1C(O)=C(C)O/C1=C2CCNCC\\2",
        "r_group_assignments": "7e piperidine N-H -> N-C(=O)CH3",
        "attachment_mapping": "Acetyl group attached to piperidine nitrogen",
    },
    {
        "paper_id": "1d74f0cb49aa",
        "compound_entity_id": "CMP-1d74f0cb49aa-31",
        "compound_label": "31",
        "canonical_isomeric_smiles": "CCOc1ccc(N2CCCC2=O)cc1C(=O)O",
        "source_id": "article-and-si:1d74f0cb49aa",
        "source_file": (
            "source_pdfs/case5 volume67 issue1-4/"
            "zhou-et-al-2023-discovery-of-2-ethoxy-5-isobutyramido-n-1-"
            "substituted-benzamide-derivatives-as-selective-kv2-1.pdf; "
            "jm3c01245_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 8, Scheme 4; SI PDF page 80 (S80), section 3.4.3"
        ),
        "source_label": "31",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 4 and SI section 3.4.3 independently identify 31 as "
            "2-ethoxy-5-(2-oxopyrrolidin-1-yl)benzoic acid, the acid directly "
            "coupled to form source-confirmed compound 69."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "CCOc1ccc(N2CCCC2=O)cc1C(=O)O",
        "r_group_assignments": "5-amino substituent -> N-linked 2-pyrrolidone",
        "attachment_mapping": (
            "2-pyrrolidone nitrogen attached at benzoic-acid C5; ethoxy at C2"
        ),
    },
    {
        "paper_id": "1d74f0cb49aa",
        "compound_entity_id": "CMP-1d74f0cb49aa-39",
        "compound_label": "39",
        "canonical_isomeric_smiles": "CCOc1ccc(NC(=O)C(C)C)cc1C(=O)O",
        "source_id": "article-and-si:1d74f0cb49aa",
        "source_file": (
            "source_pdfs/case5 volume67 issue1-4/"
            "zhou-et-al-2023-discovery-of-2-ethoxy-5-isobutyramido-n-1-"
            "substituted-benzamide-derivatives-as-selective-kv2-1.pdf; "
            "jm3c01245_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 9, Scheme 5; SI PDF page 84 (S84), section 3.5.1"
        ),
        "source_label": "39",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 5 and SI section 3.5.1 independently identify 39 as "
            "2-ethoxy-5-isobutyramidobenzoic acid, the common acid precursor "
            "for the following benzamide series."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "CCOc1ccc(NC(=O)C(C)C)cc1C(=O)O",
        "r_group_assignments": "benzoic-acid C5 amino group -> isobutyryl amide",
        "attachment_mapping": "isobutyramide at C5; ethoxy at C2; acid at C1",
    },
    {
        "paper_id": "ede33eb21948",
        "compound_entity_id": "CMP-ede33eb21948-38",
        "compound_label": "38",
        "canonical_isomeric_smiles": (
            "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2)I"
        ),
        "source_id": "article:ede33eb21948;pubchem:10427869",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "chen-et-al-2024-discovery-of-cbpd-268-as-an-exceptionally-"
            "potent-and-orally-efficacious-cbp-p300-protac-degrader.pdf"
        ),
        "source_locator": (
            "Main PDF pages 14 and 16, Scheme 1 and exact reagent name; "
            "PubChem CID 10427869 exact-name structure cross-check"
        ),
        "source_label": "38",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 and the experimental reagent name identify 38 as "
            "tert-butyl 3-iodo-1,4,6,7-tetrahydro-5H-pyrazolo[4,3-c]pyridine-"
            "5-carboxylate. PubChem CID 10427869 independently matches the name."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2)I",
        "r_group_assignments": "pyrazole C3 = iodine; fused-ring N5 = Boc",
        "attachment_mapping": "Iodine at pyrazole C3; Boc on saturated ring nitrogen",
    },
    {
        "paper_id": "ede33eb21948",
        "compound_entity_id": "CMP-ede33eb21948-40",
        "compound_label": "40",
        "canonical_isomeric_smiles": (
            "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2C3CCN(C(=O)OCc4ccccc4)CC3)I"
        ),
        "source_id": "article:ede33eb21948",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "chen-et-al-2024-discovery-of-cbpd-268-as-an-exceptionally-"
            "potent-and-orally-efficacious-cbp-p300-protac-degrader.pdf"
        ),
        "source_locator": (
            "Main PDF page 14, Scheme 1; page 16, complete experimental name for 40"
        ),
        "source_label": "40",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 and the complete experimental name show SN2 attachment "
            "of the 1-Cbz-piperidin-4-yl group to pyrazole N1 of 38; iodine "
            "and both protecting groups are retained."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2)I",
        "r_group_assignments": "pyrazole N1-H -> 1-Cbz-piperidin-4-yl",
        "attachment_mapping": "Pyrazole N1 bonded to piperidine C4",
    },
    {
        "paper_id": "ede33eb21948",
        "compound_entity_id": "CMP-ede33eb21948-41",
        "compound_label": "41",
        "canonical_isomeric_smiles": (
            "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2C3CCN(C(=O)OCc4ccccc4)CC3)"
            "N1CCCc3ccc(C(F)F)cc31"
        ),
        "source_id": "article:ede33eb21948",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "chen-et-al-2024-discovery-of-cbpd-268-as-an-exceptionally-"
            "potent-and-orally-efficacious-cbp-p300-protac-degrader.pdf"
        ),
        "source_locator": (
            "Main PDF page 14, Scheme 1; page 17, complete experimental name for 41"
        ),
        "source_label": "41",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 and the experimental name explicitly replace the C3 "
            "iodide of 40 with 7-(difluoromethyl)-1,2,3,4-tetrahydroquinolin-"
            "1-yl while retaining the N1-piperidyl, Boc, and Cbz groups."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": (
            "CC(C)(C)OC(=O)N1CCC2=C(C1)C(=NN2C3CCN(C(=O)OCc4ccccc4)CC3)I"
        ),
        "r_group_assignments": (
            "pyrazole C3-I -> 7-(difluoromethyl)-tetrahydroquinolin-1-yl"
        ),
        "attachment_mapping": "Tetrahydroquinoline N1 bonded to pyrazole C3",
    },
    {
        "paper_id": "ede33eb21948",
        "compound_entity_id": "CMP-ede33eb21948-48",
        "compound_label": "48",
        "canonical_isomeric_smiles": (
            "CC(=O)N1CCc2c(c(N3CCCc4cc(-c5cnn(C)c5)c(C(F)F)cc43)"
            "nn2C2CCN(CC(=O)O)CC2)C1"
        ),
        "source_id": "article:ede33eb21948",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "chen-et-al-2024-discovery-of-cbpd-268-as-an-exceptionally-"
            "potent-and-orally-efficacious-cbp-p300-protac-degrader.pdf"
        ),
        "source_locator": (
            "Main PDF page 14, Scheme 1; page 19, complete experimental name "
            "and MS for acid 48"
        ),
        "source_label": "48",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 and the complete experimental name identify 48 as the "
            "N-acetic acid derivative of amine 47a. The reconstructed formula "
            "and exact mass agree with the reported [M+H]+ 568.16."
        ),
        "stereochemistry_status": "not_applicable",
        "scaffold_smiles": (
            "CC(=O)N1CCc2c(c(N3CCCc4cc(-c5cnn(C)c5)c(C(F)F)cc43)"
            "nn2C2CCNCC2)C1"
        ),
        "r_group_assignments": "47a piperidine N-H -> N-CH2-CO2H",
        "attachment_mapping": "Acetic-acid methylene attached to piperidine nitrogen",
    },
    {
        "paper_id": "566841ee4e78",
        "compound_entity_id": "CMP-566841ee4e78-s2",
        "compound_label": "S2",
        "canonical_isomeric_smiles": (
            "O=C(O)C(Cc1ccccc1)(OC(CF)c1n[nH]c2cc("
            "-n3nnc4c(F)cc(Br)cc43)ccc12)C(=O)O"
        ),
        "source_id": "article-and-si:566841ee4e78",
        "source_file": (
            "source_pdfs/case2 volume67 issue10-13/"
            "shi-et-al-2024-discovery-of-novel-non-nucleoside-inhibitors-"
            "interacting-with-dizinc-ions-of-cd73.pdf; "
            "jm4c00825_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 7, explicit 12f-to-S2 linker modification; "
            "SI PDF page 3 (S3), Table S2; page 6 (S6), Scheme S1; "
            "page 7 (S7), formula and HRMS"
        ),
        "source_label": "S2",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "The article explicitly changes the 12f Ar-CH2O linker to "
            "Ar-CH(CH2F)O in S2. The complete SI graph and synthesis agree; "
            "the reconstructed C25H18BrF2N5O5 [M-H]- exact mass 584.0381 "
            "matches the reported 584.0381 (found 584.0380)."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": (
            "O=C(O)C(Cc1ccccc1)(OCc1n[nH]c2cc("
            "-n3nnc4c(F)cc(Br)cc43)ccc12)C(=O)O"
        ),
        "r_group_assignments": "12f Ar-CH2O -> Ar-CH(CH2F)O",
        "attachment_mapping": (
            "Insert CH2F on the carbon between the indazole C3 and malonate "
            "oxygen; SI assigns no configuration at the new stereocenter"
        ),
    },
    {
        "paper_id": "ede33eb21948",
        "compound_entity_id": "CMP-ede33eb21948-51",
        "compound_label": "51",
        "canonical_isomeric_smiles": (
            "O=C(O)CN1Cc2cc3c(cc2C1)C(=O)N(C1CCC(=O)NC1=O)C3=O"
        ),
        "source_id": "article-and-si:ede33eb21948",
        "source_file": (
            "source_pdfs/case4 volume67 issue5-9/"
            "chen-et-al-2024-discovery-of-cbpd-268-as-an-exceptionally-"
            "potent-and-orally-efficacious-cbp-p300-protac-degrader.pdf; "
            "jm3c02124_si_001.pdf"
        ),
        "source_locator": (
            "Main PDF page 14, Scheme 1; page 16, chemistry paragraph; "
            "SI PDF page 66 (S65), compound 51 spectrum with complete graph"
        ),
        "source_label": "51",
        "reconstruction_method": "reviewed_complete_structure",
        "source_match_status": "reconstructed_source_graph_match",
        "decision_note": (
            "Scheme 1 identifies 51 as the N-acetic acid derivative of TX16. "
            "The same complete graph is embedded above its SI S65 spectrum. "
            "The article explicitly couples 51 with amine 47a to form 16, "
            "not the longer-linker compound 18."
        ),
        "stereochemistry_status": "source_unspecified",
        "scaffold_smiles": (
            "N1Cc2cc3c(cc2C1)C(=O)N(C1CCC(=O)NC1=O)C3=O"
        ),
        "r_group_assignments": "TX16 isoindoline N-H -> N-CH2-CO2H",
        "attachment_mapping": (
            "Acetic-acid methylene attached to the isoindoline nitrogen; "
            "glutarimide stereochemistry is not specified in the source"
        ),
    },
]


EXTERNAL_IDENTIFIER_REPAIRS = [
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-2",
        "compound_label": "2",
        "query_name": "Tsagris compound 23",
        "canonical_isomeric_smiles": (
            "CN1CCC(c2nc(-c3ccc(F)c(NS(C)(=O)=O)c3)"
            "c(-c3ccnc(NCC4CC4)n3)s2)CC1"
        ),
        "source_url": "https://www.ebi.ac.uk/chembl/explore/compound/CHEMBL4286841",
        "source_locator": (
            "ChEMBL CHEMBL4286841; source document CHEMBL4265899, compound 23"
        ),
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-3",
        "compound_label": "3",
        "query_name": "ML-10",
        "canonical_isomeric_smiles": (
            "Cc1cn2c(cc1CN(C)C)nc(c2c3ccnc(n3)NCC4CC4)"
            "c5ccc(c(c5)NS(=O)(=O)C)F"
        ),
        "source_url": "https://www.rcsb.org/structure/5EZR",
        "source_locator": "RCSB PDB 5EZR, chemical component 4ZS",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-4",
        "compound_label": "4",
        "query_name": "MMV030084",
        "canonical_isomeric_smiles": (
            "CC(C)(CN)C1=NC(=C(N1)C2=CC=NC=C2)"
            "C3=CC(=C(C=C3)Cl)O"
        ),
        "source_url": "https://pubchem.ncbi.nlm.nih.gov/compound/22185475",
        "source_locator": "PubChem CID 22185475",
    },
    {
        "paper_id": "9b9e5d0c40bc",
        "compound_entity_id": "CMP-9b9e5d0c40bc-5",
        "compound_label": "5",
        "query_name": "RY-1-165",
        "canonical_isomeric_smiles": (
            "c1ccc(cc1)c2nc(cn2c3ccnc(n3)N[C@@H]4CCN(C4)"
            "C(=O)c5nccs5)C6CC6"
        ),
        "source_url": "https://www.rcsb.org/structure/8EM8",
        "source_locator": "RCSB PDB 8EM8, chemical component WLK",
    },
]


def main() -> None:
    candidates = [
        build_reviewed_structure_work_row(**repair)
        for repair in REVIEWED_REPAIRS
    ]
    candidates.extend(
        build_external_identifier_work_row(**repair)
        for repair in EXTERNAL_IDENTIFIER_REPAIRS
    )
    result = publish_reviewed_structure_candidates(candidates)
    confirmed_keys = {
        (row["paper_id"], row["normalized_label"])
        for row in result["confirmed_rows"]
    }
    for row in candidates:
        key = (row["paper_id"], row["normalized_label"])
        if key not in confirmed_keys:
            raise RuntimeError(f"reviewed repair was not confirmed: {key}")
    print(
        f"published={len(candidates)} work_rows={len(result['work_rows'])} "
        f"confirmed_rows={len(result['confirmed_rows'])}"
    )


if __name__ == "__main__":
    main()
