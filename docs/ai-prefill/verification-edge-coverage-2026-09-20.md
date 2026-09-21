# PfPKG 004 Edge coverage audit — 2026-09-20

## Result

Live preview workspace `27bf4ad2-187d-429c-b18b-3d3cf79c3eba`, version 391,
contains 44 compounds, 279 activities, one Lineage, 11 members, six Edges,
and six Edge–Evidence links. Thirty-three compounds are outside every Lineage.
The prior compound repair appended compounds, structures, source locators,
Evidence and Activity; it did not revisit membership or relationship coverage.

Source: *Structure–Activity Relationship of a Pyrrole Based Series of PfPKG
Inhibitors as Anti-Malarials*, DOI 10.1021/acs.jmedchem.3c01795.
PDF SHA-256: `c1664b69f81386283770d847dece35dd69b12674545d91bd97fa32a598c7a34e`.
All page references below are PDF page numbers (1-based).

## Confirmed missing transformations

The following nine relationships have both endpoint compounds in the current
workspace and are absent from its graph. They are a lower bound from Schemes 3–5,
not a claim of complete synthesis-route coverage or improved biological potency.

| Parent | Child | Source | Basis |
| --- | --- | --- | --- |
| 12a | 16 | p4 Scheme 3 | Explicit parent label/arrow; fused tetrazole formation |
| 12b | 17 | p4 Scheme 3 + prose | Bromide to hydroxymethyl substitution |
| 18a | 19a | p4 Scheme 4, p5 prose | Nitrile to carboxamide |
| 18b | 19b | p4 Scheme 4, p5 prose | Nitrile to carboxamide |
| 1 | 21 | p5 Scheme 5 + prose | R2 bromination |
| 21 | 22 | p5 Scheme 5 + prose | Bromide to vinyl |
| 21 | 23 | p5 Scheme 5 + prose | Bromide to nitrile |
| 22 | 25 | p5 Scheme 5 + prose | Vinyl to ethyl |
| 23 | 26 | p5 Scheme 5 | Nitrile hydrolysis; prose incorrectly calls nitrile “22” |

The last row needs its source discrepancy retained in any proposed summary:
Scheme 5 identifies 22 as vinyl and 23 as nitrile. Do not transcribe the prose
error into an incorrect 22→26 Edge. The original Scheme 3 also contains a 13
parent annotation inconsistent with its shown substituent and prose; no existing
12a→13 record was changed during this audit.

## SAR coverage

The design strategy on pp3,7–9 explicitly explores R1–R5 around compound 1.
Tables 1–5 provide 38 other assayed analog identities relative to that baseline:

| Axis | Table / PDF page | Comparison candidates from compound 1 |
| --- | --- | --- |
| R1 | Table 1 / p9 | 12a, 12b, 12c, 12d, 13, 15a, 15b, 16, 17, 18a, 18b, 19a, 19b, 20 (14) |
| R2 | Table 2 / p10 | 21, 22, 23, 24, 25, 26, 27, 28, 32 (9) |
| R3 | Table 3 / p11 | 38, 39, 40, 41, 55, 56, 57, 50, 51, 52, 53 (11) |
| R4 | Table 4 / p12 | 33 (1) |
| R5 | Table 5 / p12 | 12e, 12f, 54 (3) |

None of these baseline comparisons is represented by an Edge. These are proposed
SAR comparisons, **not 38 proven immediate-parent optimization events**. Their
summaries must identify the baseline semantics and concrete structural change;
no arrow should imply every derivative improves activity or was synthesized
from 1. One pair, 1→21, also occurs in the transformation inventory. The combined
inventories contain 47 typed entries but only 46 unique directed pairs. Do not
create duplicate same-lineage endpoints just to match that count.

R3 prose on p8 repeats labels 40–41 for both methyl positions. Table 3, p6 synthesis
and the structure identities distinguish 38/39 (3-methyl, cis/trans racemates)
from 40/41 (2-methyl). Preserve that discrepancy and the distinct pure enantiomers
50–53; do not manufacture sequential 50→51→52→53 optimization.

Other paths deliberately withheld from the nine simple transformations include
58→59→20, 11g→14→27 and 11g→62→28: intermediates 59,14,62 are not in the workspace.
11a→18a also needs the previously recorded N-Boc/N-Cbz identity conflict settled.
61→24 is a documented multistep route and must be labelled at that level if used.

## Why the omission occurred

The exact old annotation states:

> Synthetic conversion edges are retained where both precursor and product labels
> are named; broad SAR members remain unresolved.

Source file: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/9b9e5d0c40bc.json`
in the main workspace. Its aggregate CSV contains 21 records: six text-explicit
relations and 15 unresolved records, all 15 with unknown parent (`--`). The live
six pairs exactly match the six resolved pairs. Much of the SAR was never
represented as a resolved relationship, and later compound completion did not
re-run relationship extraction.

Historically the adapter also required `pair_eligible=yes` and a valid text
Evidence. That hard requirement has already been removed in this session's
worktree. Current behavior:

- Candidate validator reports unlinked Edges as `needs_review`, `can_apply=true`.
- Legacy adapter accepts resolved/AI-inferred Edges without text Evidence and
  without the stale pair-eligibility flag. Unknown endpoints remain excluded.
- V2 Edge create/update checks endpoints/membership/duplicates, not Evidence.
- Submission requires a reviewer disposition; supporting text is optional.
- UI reads every returned Edge and explicitly displays an unlinked state.

Therefore absence of text was an earlier policy bias/hard gate, but it is not a
current rendering filter. Simply allowing empty Evidence does not infer missing
parents or regenerate missing relationships. An unrelated old v1 helper still
contains `MISSING_EVIDENCE`; reference search found no callers in the current v2
service path, so it must not be cited as the cause of this preview's omission.

## Checks and handoff

- Captured fresh snapshots of all seven preview workspaces with preview identity
  verification, and compared the live graph with the source and legacy CSV.
  Final verification confirms all seven complete scientific snapshot hashes are unchanged.
- Re-rendered and visually checked source PDF pages 4 and 5; used existing reviewed
  main-table identities plus the actual pp3–9 design/SAR prose.
- Ran the current adapter/validator regression tests for absent Evidence and
  invalid/unresolved/rejected relations: 11 tests passed (14 deselected).
  Results are recorded in the external audit test log.
- Guidance and checklist now require an independent Edge inventory after compound
  changes, separate baseline/synthesis/inference semantics, and explicit missing
  or withheld reasons. This is operator guidance, not a new completeness validator.
- Audit only: no scientific mutations and no auto-approval. Missing relationships
  are saved as a concrete reviewable inventory, not silently written as confirmed
  science. Existing six Edges and all compound/activity records remain intact.

External audit artifacts:
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/edge-coverage-audit-20260920/`

`audit.json` contains endpoint IDs, evidence locations, per-candidate reasoning,
source conflicts and withheld paths; `missing-edges.csv` is the compact inventory.
`before-workspaces.json` contains the captured snapshots, `page-4.png` and
`page-5.png` are source renderings. `build_audit.py` rebuilds the report offline.
