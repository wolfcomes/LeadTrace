# Lineage Structure Reconstruction Progress

Date: 2026-09-08

> Historical snapshot: this report records the state before Batch 03 was
> published. For the subsequent 24-Paper batch and the current counts, see
> `docs/lineage_batch_03_2026-09-08.md`.

## Scope

This run continued the source-backed reconstruction workflow for all 47 Papers
already represented in the lineage dataset. The final external structure state
remains `structure_confirmed`. Machine-readable records, source-figure
reconstructions, R-group expansions, explicit component selections, and source
error corrections are kept in the same authoritative table with separate
provenance fields.

The workflow does not promote a structure only because RDKit can parse it. Each
accepted row has a Paper-local entity key, source file and locator, an accepted
work row, and a complete single-component graph without dummy atoms or radicals.

## Results

Authoritative counts after the run:

| Metric | Result |
| --- | ---: |
| Lineage Papers | 47 |
| Lineage entities | 1,324 |
| Complete entities | 1,323 |
| `structure_confirmed` rows | 1,322 |
| Legacy non-final complete entities | 1 |
| Missing entities | 1 |
| Lineage edges | 1,269 |
| Pair-ready edges | 1,078 |
| Papers with pair-ready edges | 47 / 47 |
| Structure work rows | 1,981 |
| Manifest rows | 160 |
| Downloaded source files | 50 |

The one complete legacy entity is `7a695794fc7b/2n`, which remains
`model_visual_match_confirmed` and is deliberately excluded from pair-ready
eligibility. The one unresolved entity is `3725c30c81e3/1`; the source figure
defines it as a variable quinazoline-pyrimidine scaffold with `R` and `R'`, not
as one uniquely assignable compound. Assigning a dummy-free SMILES would be an
unsupported guess, so it remains pending.

The previous baseline was 1,306 complete entities and 987 pair-ready edges.
This run therefore added 17 complete authoritative structures and 91
pair-ready edges, while preserving the strict final-state gate.

## Reviewed Additions

The following previously unresolved entities were promoted after source and
graph review:

- `04effc6577c7/13b`: article Figure 1 complete structure; R/S mixture retained by leaving the wavy stereocenter unspecified.
- `24598d139950/39`: `[R6]` expanded to chlorine using the synthesis reagent, formula, and X-ray evidence; assembled with RDKit atom-map joining.
- `34de43d32dbf/BMS-HIT`: SMe structure from Figure 2 and the systematic name.
- `34de43d32dbf/1`: corrected to the OMe structure from Figure 2; the SI row labelled `1` was an entity-mapping error containing the BMS-HIT SMe graph.
- `381572722037/9`: complete hit structure from Figure 2, with unsupported absolute stereochemistry left unspecified.
- `381572722037/19e` and `22e`: exact structures retained from SI rows whose labels were damaged by spreadsheet scientific notation; the correction is recorded as a reviewed source-label correction.
- `438346965cd9/1`: corrected the SI oxygen radical placeholder to the methoxy group shown in Figure 2 and specified by the article.
- `75843eeb816b/63` and `66`: racemate parent structures reconstructed from the corresponding epimer rows; supported trans stereochemistry retained and the racemic center left unspecified.
- `7e6d7738d3fa/biotincompound45` and `IV`: complete structures from the article figures, including the PEG-biotin connection.
- `840ae8d2dffb/Q63`: complete structure from the SI section and HRMS evidence.
- `86188f27cbfc/S1`: complete phenyltetrazole starting structure from Figure 2.
- `b72748fcd28a/BIBR1591`: complete structure cross-checked against Figure 1, PubChem, and ChEMBL.
- `d84a31c8bd03/14`: complete structure mapped to the prior-paper compound `8o`.
- `e5f3a608a794/6o`: explicit main-component selection; the trailing `.CC` is an export artifact rejected by formula and HRMS evidence.
- `e5f3a608a794/7k`: removed the nonchemical `.[ONC-D130]` placeholder and retained the free-base graph.

The confirmed outputs are in
`source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`.
The audited candidate and source records are in
`source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`.

## Integrity Checks

The final independent audit reported no issues:

- 1,322 confirmed keys are unique.
- All 1,322 accepted work-row references exist and have `review_decision=accept`.
- All confirmed entity keys match the Paper-local entity key.
- All confirmed graphs are RDKit-valid, single-component, dummy-free, and radical-free.
- All downloaded source checksums match the manifest.
- All 1,078 pair-ready edges have two `structure_confirmed` endpoints.
- The `34de43d32dbf/1` OMe correction and BMS-HIT SMe record are now distinct.
- The `381572722037/19e` and `22e` confirmed rows reference the reviewed correction work rows after full-batch reinspection.

The full source-processing test suite passes with `255 passed`. The full
Dashboard suite passes with `69 passed` after updating counts affected by the
new structures. Final molecular drawings remain generated from canonical
SMILES through the Dashboard RDKit path, not copied from article figures.

## Concurrency And Reproducibility

Full-batch publication now uses one outer file lock covering the read, merge,
confirmation selection, and atomic writes for manifest, work, confirmed, and
summary outputs. Independent source investigation can remain parallel, while
authoritative publication is serialized and deterministic.

The automatic machine-source `review_decision=accept` values represent the
current pipeline policy for exact parsed sources. They are not a claim of an
independent human review. Figure reconstructions, source corrections, and
component selections carry explicit review notes and source locators.

## Commands

```bash
cd source_pdfs/分子修改提取_2024_JMC
pytest -q
python scripts/build_compound_lineages.py
cd ../..
python -m pytest -q dashboard/tests/test_dashboard_server.py
```

The next safe boundary is the remaining 625 non-lineage corpus Papers. The
same source-first and final-state rules should be applied in batches, with
ambiguous generic scaffolds kept pending rather than forced into molecule
pairs.
