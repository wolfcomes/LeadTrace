# Lineage Batch06 processing report

Date: 2026-09-10  
Batch version: `compound_lineages_v1_2026-09-10-batch06`  
Scope: 24 DOI-unique Papers selected by the locked evidence-density ordering.

> **Audit revision (2026-09-10):** compounds `2a98b0589a08 / 12` and `15`
> are explicitly reported as pairs of diastereomers and have been withdrawn
> from the authoritative single-molecule table. The current Batch06 result is
> **1,018 confirmed structures, 166 unresolved entities, and 280 pair-ready
> edges across 21 Papers**. The original 1,020 count below is retained as a
> historical checkpoint; the revised boundary is documented in the addendum
> and `docs/batch05_06_audit_repair_2026-09-10.md`.

## Final outcome

- Batch boundary: 24/24 Papers are complete, DOI-unique, and protected by regression tests.
- Main-text/SI coverage: 24/24 main PDFs and the downloaded DOI-exact supporting files were reviewed. The current source manifest contains 529 Batch06 attachment records: 162 downloaded and 367 deferred after the relevant machine-readable and PDF sources were secured.
- Machine-readable structures: current inspection yields 1,233 records, of which 1,228 parse in RDKit and five remain rejected source rows. Parseability is treated only as a candidate property, not an accuracy or confirmation claim.
- Parser repairs: the CR-only `bf54bac4775b` CSV yields 63 labelled structures; `Compd.` and `Strings(SMILES)` headers are recognized; and the ISO-8859/CP1252 `1994543a9112` CSV now preserves its first section plus later repeated-header sections. That repair recovers `24a-24e` and `58a-58c` and ignores repeated headers as data.
- Annotation publication: 24 Paper-local JSON files contain 1,157 lineage rows: 93 `text_explicit`, 361 `figure_explicit`, and 703 conservative `unresolved` records.
- Structure publication: 1,020/1,184 Batch06 entities have one confirmed complete structure. The remaining 164 show `--`; 141 are source-reported non-unique stereochemical materials, two are exact source-structure mismatches, one is an unreviewed multicomponent source row, 19 lack a machine candidate, and one source label is not uniquely bound.
- Pair publication: 280 edges are pair-ready across 21/24 Papers. A pair is published only when the immediate-parent relation is supported and both endpoints are distinct, confirmed, complete single-component structures.
- Aggregate publication: the corpus now contains 138 lineage Papers, 4,301 entities, 4,144 edges/evidence rows, 4,126 complete structures, and 1,738 pair-ready edges.

The tuple in the fourth column below is `modification / evidence / path / distinct evidence pages`. The fifth is `attachments / downloaded / deferred / machine tables`, and the sixth is `machine rows / parsed / rejected`.

| # | Paper ID | DOI | Title | Evidence | Sources | Structure rows |
|---:|---|---|---|---:|---:|---:|
| 1 | `2c96aaf509b1` | 10.1021/acs.jmedchem.4c03149 | Oxazole-based ferroptosis inhibitors with promising properties to treat central nervous system disease | 14 / 21 / 14 / 7 | 2 / 1 / 1 / 1 | 51 / 49 / 2 |
| 2 | `56f50284cedf` | 10.1021/acs.jmedchem.4c01645 | Pyrazolopyrimidinones with improved solubility and selective inhibition of adenylyl cyclase type 1 | 14 / 20 / 14 / 8 | 2 / 1 / 1 / 1 | 69 / 69 / 0 |
| 3 | `434e5748f070` | 10.1021/acs.jmedchem.4c01744 | Discovery of new nanomolar selective IRAP inhibitors | 14 / 18 / 14 / 7 | 3 / 1 / 2 / 1 | 44 / 44 / 0 |
| 4 | `f3d107dabbcb` | 10.1021/acs.jmedchem.3c02302 | Discovery of novel 5,6-dihydro-4H-pyrido[2,3,4-de]quinazoline irreversible inhibitors | 14 / 18 / 14 / 6 | 2 / 1 / 1 / 1 | 37 / 37 / 0 |
| 5 | `1485ed4aa91b` | 10.1021/acs.jmedchem.4c00555 | Discovery of N-substituted acetamide derivatives as P2Y14R antagonists | 14 / 18 / 14 / 5 | 3 / 1 / 2 / 1 | 29 / 29 / 0 |
| 6 | `c150a5edd8dd` | 10.1021/acs.jmedchem.4c01815 | Discovery of potent and selective blockers targeting the epilepsy-associated KNa1.1 channel | 14 / 17 / 14 / 9 | 8 / 1 / 7 / 1 | 100 / 100 / 0 |
| 7 | `8991dc7472bd` | 10.1021/acs.jmedchem.3c02441 | Discovery of D25, a potent and selective MNK inhibitor | 14 / 17 / 14 / 7 | 2 / 1 / 1 / 1 | 41 / 41 / 0 |
| 8 | `1994543a9112` | 10.1021/acs.jmedchem.4c00265 | Discovery of YFJ-36: catechol-conjugated beta-lactams | 14 / 15 / 14 / 9 | 3 / 1 / 2 / 1 | 38 / 38 / 0 |
| 9 | `bf54bac4775b` | 10.1021/acs.jmedchem.4c02377 | Discovery of STX-721, a covalent mutant-selective EGFR/HER2 exon-20 insertion inhibitor | 14 / 15 / 14 / 8 | 2 / 1 / 1 / 1 | 63 / 63 / 0 |
| 10 | `feef9e819b88` | 10.1021/acs.jmedchem.4c01727 | Discovery of a 1-(phenylsulfonyl)-1,2,3,4-tetrahydroquinoline derivative | 14 / 15 / 14 / 7 | 7 / 4 / 3 / 1 | 48 / 48 / 0 |
| 11 | `2a98b0589a08` | 10.1021/acs.jmedchem.4c00734 | Discovery of preclinical candidate AD1058, a brain-penetrant ATR inhibitor | 14 / 15 / 14 / 5 | 2 / 1 / 1 / 1 | 42 / 42 / 0 |
| 12 | `c958fce90ec5` | 10.1021/acs.jmedchem.4c01395 | Discovery of a potent, orally active, long-lasting P2X7 receptor antagonist | 14 / 14 / 14 / 6 | 7 / 1 / 6 / 1 | 38 / 38 / 0 |
| 13 | `e4043323f96c` | 10.1021/acs.jmedchem.4c02169 | Discovery of SZJK-0421, a selective second-generation CRM1 inhibitor | 14 / 14 / 14 / 5 | 4 / 1 / 3 / 1 | 63 / 63 / 0 |
| 14 | `65e19df86a4a` | 10.1021/acs.jmedchem.4c01323 | Bipyridine derivatives as NOP2/Sun RNA methyltransferase 3 inhibitors | 14 / 14 / 14 / 4 | 6 / 1 / 5 / 1 | 92 / 92 / 0 |
| 15 | `cab92325187b` | 10.1021/acs.jmedchem.3c02288 | Pyrido[2,3-d]pyrimidin-7-one derivatives as ENPP1 inhibitors | 13 / 25 / 13 / 9 | 5 / 1 / 4 / 1 | 25 / 24 / 1 |
| 16 | `8e421ecc451e` | 10.1021/acs.jmedchem.3c02046 | Potent antimalarial type-II kinase inhibitors selective over human kinases | 13 / 23 / 13 / 5 | 2 / 1 / 1 / 1 | 33 / 33 / 0 |
| 17 | `07dcad0214c3` | 10.1021/acs.jmedchem.3c02203 | Potency-enhanced peptidomimetic VHL ligands with improved oral bioavailability | 13 / 22 / 13 / 9 | 2 / 1 / 1 / 1 | 109 / 109 / 0 |
| 18 | `7e503b3382bf` | 10.1021/acs.jmedchem.4c01178 | 6-Fluorine-substituted coumarin analogues as POLRMT inhibitors | 13 / 20 / 13 / 8 | 2 / 1 / 1 / 1 | 31 / 31 / 0 |
| 19 | `4bd630dc5dc8` | 10.1021/acs.jmedchem.4c00972 | 2-Aryl-4-aminoquinazoline-based LSD1 inhibitors | 13 / 18 / 13 / 6 | 2 / 1 / 1 / 1 | 53 / 53 / 0 |
| 20 | `2d5a56fffb44` | 10.1021/acs.jmedchem.4c00357 | Isoalantolactone-based NLRP3 inflammasome inhibitors | 13 / 17 / 13 / 8 | 3 / 1 / 2 / 1 | 66 / 65 / 1 |
| 21 | `c6c61d0fc737` | 10.1021/acs.jmedchem.4c00643 | MCL-1 inhibitors with a 3-substituted-1H-indol-1-yl P1-P3 moiety | 13 / 15 / 13 / 6 | 9 / 1 / 8 / 1 | 42 / 42 / 0 |
| 22 | `096b579fa25f` | 10.1021/acs.jmedchem.3c01934 | Dual EGFR L858R/T790M and ACK1 inhibitors | 13 / 15 / 13 / 6 | 6 / 1 / 5 / 1 | 46 / 45 / 1 |
| 23 | `023145d60eea` | 10.1021/acs.jmedchem.4c00513 | Small-molecule targeting PPM1A for tuberculosis host-directed therapy | 13 / 15 / 13 / 4 | 5 / 1 / 4 / 1 | 37 / 37 / 0 |
| 24 | `b09de250fcb3` | 10.1021/acs.jmedchem.4c03205 | Pyrrolopyrazine carboxamides as selective FGFR2/3 inhibitors | 13 / 14 / 13 / 7 | 2 / 1 / 1 / 1 | 37 / 36 / 1 |

The source PDF for every row is the absolute `source_pdf` recorded in `02_text_extraction/full_document_text_index.csv`; all 24 currently have `text_status=ok`.

## Quality boundary

The following are not counted as confirmed simply because they parse in RDKit:

- generic R-group rows or partial fragments;
- multi-component salt/mixture rows without a reviewed component decision;
- structures whose source label cannot be bound exactly to a Paper-local compound;
- prior-art templates not represented by the Paper's authoritative structure source;
- an apparent series relation for which the article does not identify one immediate parent.

Only evidence-backed `root -> immediate parent -> derived` relations can become pair-ready. All other Paper-local compounds remain visible as unresolved lineage members with `parent=--` until stronger evidence is available.

## Reviewed structure boundaries

- `434e5748f070`: compounds 1-44 are reported as racemates or 50:50 diastereomer mixtures and remain `--`.
- `feef9e819b88`: 44 genuinely stereogenic racemate records remain `--`; achiral `A4`, `D15`, `D16`, and `D17` are retained as confirmed complete structures. Racemic `D4` is not assigned to either separately named enantiomer.
- `1994543a9112`: 22 epimer-mixture rows remain `--`. `58c` is separately rejected as `source_structure_mismatch` because its machine row duplicates cyclobutyl `58b`, whereas the paper identifies `58c` as the isopropyl analogue. `24b` remains unresolved because its source row is multicomponent and has not received an exact component decision.
- `56f50284cedf`: eight source-reported racemic/mixture labels remain `--`. `7-31B` is separately rejected as `source_structure_mismatch` because the machine row has a naphthalene-containing graph instead of the paper's 4-methylcyclohexyl minor regioisomer.
- `07dcad0214c3`: racemic compound `1` remains `--`; separated source-named compounds `2` and `3` remain confirmed.
- `bf54bac4775b`: 22 arbitrary-stereo or non-unique source rows remain `--`; source-supported single structures such as `22`, `23`, `32`, `38-40`, `44`, `45`, and `47-53` remain confirmed.
- `023145d60eea`: 37 SMIP bromide-salt rows use a reviewed exact-component rule that removes only disconnected monatomic `[Br-]`. It retains the organic cation charge and every covalent bromine. `SMIP-30`, which has no exact machine row, remains `--`.

## Verification

Fresh verification after annotation generation, source rebinding, reviewed exclusions/mismatches, and the final aggregate rebuild:

```text
lineage/structure tests: 311 passed in 7.90s
Dashboard tests:          69 passed in 654.97s

self-loops:                    0
duplicate directed edges:     0
unresolved pair-ready edges:  0
dangling edge endpoints:      0
dangling evidence references: 0
invalid pair endpoints:       0
```

Live HTTP acceptance against the restarted Dashboard also passed:

```text
Batch06 Paper detail endpoints:       24 / 24
entities returned:                    1,184
lineage edges returned:               1,157
Papers returning pair-ready content:     21
representative RDKit PNG endpoints:       42 / 42
critical unresolved image suppression:    3 / 3
critical confirmed structure checks:      5 / 5
```

Batch06 is complete under the current quality boundary. Later work may add a dedicated constitution-only or multicomponent representation, but it must not overwrite these non-unique experimental materials with one arbitrary isomeric SMILES.

## 2026-09-10 audit repair addendum

The article experimental sections state that compounds `12` (PDF page 14)
and `15` (PDF page 16) were prepared as the diastereoisomers containing both
the R and S sulfone-ring centers relative to the fixed R-methylmorpholine
center. Their machine rows therefore encode useful connectivity but do not
identify one unique experimental molecule. Both confirmations have been
withdrawn and the Dashboard now displays `--` without generating an RDKit
image for either entry.

The revised Batch06 result is:

```text
Paper-local entities:         1,184
Confirmed complete structures: 1,018
Missing / non-unique:             166
Lineage edges / evidence:   1,157 / 1,157
Text / figure explicit:       93 / 361
Unresolved context:                703
Pair-ready edges:                  280
Papers with pair-ready:        21 / 24
```

Neither withdrawn compound is an endpoint of a published direct pair, so the
Batch06 pair-ready count remains 280. A further 22 Batch06 RDKit stereo-risk
hits remain follow-up source-review scope and have not been altered solely on
the basis of a cheminformatics warning.
