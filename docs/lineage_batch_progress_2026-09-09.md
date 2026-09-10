# Lineage Batch Progress

**Snapshot date:** 2026-09-10  
**Aggregate generated at:** 2026-09-10T03:04:33.463062+00:00

This report summarizes the 138 Papers currently represented in the aggregate
lineage snapshot. Batch 03 and Batch 04 repairs remain published; Batch 05 and
Batch 06 have completed annotation, conservative structure confirmation,
aggregate publication, integrity audit, and Dashboard verification.

## Batch Comparison

| Batch | Requested | Papers with lineage | Edges | Explicit / figure edges | Unresolved edges | Entities | `structure_confirmed` | Complete structures | Missing / non-unique structures | Pair-ready edges | Papers with pair-ready edges |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Batch 01 | 23 | 23 | 308 | 265 | 43 | 335 | 333 | 334 | 1 | 263 | 23 |
| Batch 02 | 24 | 24 | 961 | 816 | 145 | 990 | 990 | 990 | 0 | 816 | 24 |
| Batch 03 | 24 | 19 | 242 | 62 | 180 | 268 | 268 | 268 | 0 | 62 | 18 |
| Batch 04 | 24 | 24 | 530 | 127 | 403 | 559 | 555 | 555 | 4 | 127 | 24 |
| Batch 05 | 24 | 24 | 946 | 190 | 756 | 965 | 959 | 959 | 6 | 190 | 23 |
| Batch 06 | 24 | 24 | 1,157 | 454 | 703 | 1,184 | 1,020 | 1,020 | 164 | 280 | 21 |
| **Current total** | **143 requested slots** | **138** | **4,144** | **1,914** | **2,230** | **4,301** | **4,125** | **4,126** | **175** | **1,738** | **133** |

The batches are disjoint. The 143 requested slots produce 138 aggregate Papers
because five Batch 03 Papers have no entity-backed lineage. The distinct-Paper
count in the aggregate edge table remains authoritative.

## Batch Interpretation

- Batch 01 retains one variable `R/R′` quinazoline-pyrimidine template without
  a unique complete structure. It also contains the one legacy complete entity
  whose review state is `model_visual_match_confirmed` rather than
  `structure_confirmed`.
- Batch 02 is structurally complete: all 990 entities are confirmed. The prime
  label normalization repair separates `26a` and `26a′`; all 816 explicit or
  figure-supported edges are now pair-ready.
- Batch 03 is structurally complete at `268 / 268`. Its remaining bottleneck is
  relation evidence: 180 of 242 edges retain an unresolved immediate parent.
  All 62 explicit or figure-supported edges are pair-ready, across 18 Papers.
- Batch 04 is structurally complete wherever the source defines one unique
  molecule: `555 / 559` entities are confirmed, and all 127 explicit or
  figure-supported edges are pair-ready. The remaining four records are
  deliberate quality boundaries, not ordinary extraction omissions.
- Batch 05 confirms `959 / 965` entities. All 190 explicit or figure-supported
  edges are pair-ready. Its six missing entities belong to one review Paper and
  remain unresolved because they are variable-R families or lack a uniquely
  source-located complete graph; no pseudo-structure was generated.
- Batch 06 confirms `1,020 / 1,184` entities. Of its 454 explicit or
  figure-supported relations, 280 are pair-ready; the remainder touch a
  source-reported racemate/mixture, a source mismatch, a multicomponent row, or
  another deliberately unresolved structure. It does not convert a parseable
  constitution-only graph into one falsely unique experimental stereoisomer.

## Batch 05 Outcome

Batch 05 adds 24 Paper-local annotation JSON files, 965 entities, and 946
lineage edges. Relation evidence is intentionally conservative: 190 edges are
explicit or figure-supported and 756 retain an unresolved immediate parent.
Number adjacency and structure similarity were not used to manufacture direct
parent-child relationships.

Its 959 confirmed structures consist of:

- 839 direct exact-label machine-readable structures;
- 105 reviewed parent-component selections for chloride or formic-acid source
  records;
- three reviewed primary-table records duplicated identically in a trailing
  summary section;
- six exact named-compound PubChem identifier matches;
- five complete graph reconstructions from labeled main-article figures;
- one Paper-local SI label correction binding `DA` to the DLA control.

The annotation repair for `c6fdd5c7e071` also removed nonexistent bare labels
`43`, `47`, `53`, and `55`, retaining only the source-observed suffixed series.
The figure reconstructions include Paper-local page/figure locators and were
cross-checked against SAR transformations or analytical data before RDKit
publication.

## Batch 06 Outcome

Batch 06 adds 24 Paper-local annotation JSON files, 1,184 entities, and 1,157
lineage edges. The immediate-parent audit confirms 454 text- or
figure-supported relations and leaves 703 series members unresolved instead of
guessing from compound numbering, table order, or structural similarity.

The final structure review adds two reusable safeguards:

- ISO-8859/CP1252 CSV parsing now recognizes a mojibake UTF-8 BOM, selects the
  first complete structure header, follows repeated section widths, and does
  not emit repeated headers as compounds. This recovers `24a-24e` and
  `58a-58c` for `1994543a9112`.
- Exact source mismatches can be withdrawn atomically by immutable work-row ID
  while retaining `source_structure_mismatch` and `review_decision=reject`
  through later revalidation. This protects `58c` and `7-31B` from accidental
  re-confirmation solely because their wrong graphs parse in RDKit.

The stereochemical review deliberately retains 141 non-unique experimental
materials as `--`. It also corrects an over-broad series exclusion by restoring
the four achiral complete structures `feef9e819b88 / A4, D15, D16, D17`.
For the SMIP series, 37 reviewed component selections remove exactly one
disconnected monatomic bromide counterion while preserving the charged organic
component and any covalent bromine.

## Batch 03 / 04 Repair Outcome

The repair publisher contains 29 source-reviewed graph reconstructions and four
external-identifier-backed structures. It writes candidates through the same
RDKit and confirmation gate as other authoritative structures. After
publication, the authoritative structure table contains 2,146
`structure_confirmed` rows.

For Paper `9b9e5d0c40bc`, compounds 2-6 were resolved from the article and
cross-source identifiers:

- compound 2: Gilleran compound 2 = Matralis compound 5 = Tsagris compound 23;
  machine-readable graph from ChEMBL `CHEMBL4286841`;
- compound 3, ML-10: RCSB PDB `5EZR`, chemical component `4ZS`;
- compound 4, MMV030084: PubChem CID `22185475`;
- compound 5, RY-1-165: RCSB PDB `8EM8`, chemical component `WLK`, preserving
  the source-encoded `(R)` stereochemistry;
- compound 6: Gilleran compound 6 = Eck et al. 2022 compound 3; the reconstructed
  isoxazole graph contains one source-supported `(R)` stereocenter and passes
  RDKit validation.

The old annotation also collapsed intermediate series `7a-7e`, `8a-8d`, and
`9a-9h` into nonexistent bare labels `7`, `8`, and `9`. Those three placeholder
entities and their unresolved edges were removed; real suffixed labels were not
silently reassigned to arbitrary members.

## Deliberately Unresolved Structures

The aggregate now has 175 entities with `--` as the complete SMILES. The 11
pre-Batch06 quality-boundary records remain unchanged. Batch06 adds 164:

| Batch06 unresolved class | Count | Interpretation |
|---|---:|---|
| Source-reported racemate, epimer, or diastereomer mixture | 141 | A complete constitutional graph may exist, but the experimental material is not one uniquely assigned stereoisomer. |
| Exact source-structure mismatch | 2 | `1994543a9112 / 58c` and `56f50284cedf / 7-31B`; the parseable machine graph conflicts with the article. |
| Multicomponent source requiring a separate decision | 1 | `1994543a9112 / 24b`; no largest-fragment shortcut is permitted. |
| No exact machine candidate | 19 | Includes prior-art roots, two separately named D4 enantiomers without their own source rows, and other Paper-local labels. |
| Source label not uniquely bound | 1 | The record remains unresolved rather than being positionally assigned. |

These rows must not be counted as ordinary SMILES syntax failures. Most encode
a scientific uniqueness or source-provenance boundary. A future
`constitution_confirmed` or multicomponent data layer could represent some of
them without changing the stricter single-molecule `structure_confirmed`
meaning.

## Current Aggregate

- `138 / 672` corpus Papers have lineage edges; `534` remain outside lineage.
- There are `193` lineages, `4,301` Paper-local compound entities, `4,144`
  directed lineage edges, `4,144` evidence rows, and `620` activity rows.
- Relation status is `1,480` `text_explicit`, `434` `figure_explicit`, and
  `2,230` `unresolved`.
- `4,126` entities have complete, single-component structures. Of these,
  `4,125` are `structure_confirmed`; one legacy complete structure remains
  `model_visual_match_confirmed`.
- `1,738 / 4,144` edges are pair-ready. Pair readiness requires a supported
  relation plus confirmed, complete, dummy-free, radical-free RDKit structures
  at both endpoints.
- `133 / 138` current lineage Papers have at least one pair-ready edge.
- Integrity audit: `0` self-loops, `0` duplicate directed edges, `0` unresolved
  pair-ready edges, `0` dangling edge endpoints, `0` dangling evidence
  references, and `0` invalid pair endpoints.

## Verification

Fresh verification after publication and aggregate rebuild:

```text
lineage tests:   311 passed in 7.90s
Dashboard tests: 69 passed in 654.97s
```

Commands:

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests

PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
```

## Quality Boundary

“Entered lineage” means that a Paper has at least one source-backed edge or a
retained unresolved series record. It does not mean that every edge has a
uniquely supported immediate parent. Likewise, RDKit parseability alone is not
structure confirmation. The Dashboard should continue to expose relation
status, structure status, and pair readiness separately.

Final molecule images must be redrawn from confirmed complete SMILES. Source
article screenshots remain evidence locators only and must not be used as the
displayed pair structures.

Authoritative files:

- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
