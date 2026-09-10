# Batch05 / Batch06 source-audit repair

Date: 2026-09-10  
Scope: the 48 Papers in lineage Batch05 and Batch06  
Publication rule: `structure_confirmed` requires a source-supported, unique,
complete, single-component molecular graph with all source-required
stereochemistry represented.

## Outcome

The repair withdraws 114 records that had been published as one molecule even
though the source describes a racemate, stereoisomer mixture, an isolated
enantiomer without absolute assignment, or another incompletely assigned
stereochemical material. It also reconstructs 28 source-supported `(R)`
structures whose DOI-exact source table contained the complete connectivity
but omitted the alpha-center stereo encoding.

| Result | Batch05 | Batch06 | Total |
|---|---:|---:|---:|
| Confirmations withdrawn | 112 | 2 | 114 |
| Source-located R-SMILES replacements | 28 | 0 | 28 |
| Confirmed structures after repair | 847 | 1,018 | 1,865 |
| Missing or non-unique entities | 118 | 166 | 284 |
| Pair-ready edges after repair | 182 | 280 | 462 |
| Papers with pair-ready edges | 21 | 21 | 42 |

Across the complete 138-Paper lineage aggregate, the authoritative confirmed
table now contains 4,011 rows. The entity aggregate reports 4,012 complete
structures because `7a695794fc7b / 2n` is an older
`model_visual_match_confirmed` legacy entity rather than a row in the newer
confirmed-structure table. This one-row difference is pre-existing and is not
a Batch05/06 inconsistency.

## Source decisions

### Batch05 withdrawals

- `cfc4a0d0ef41`: compounds `7` and `11`-`61` (52 rows). Compound `14` is
  reported as separated enantiomers; `50`, `53`, and `54` are explicitly
  mixtures of four stereoisomers; the remaining affected source graphs do not
  assign one unique alpha-carboxylic-acid stereoisomer.
- `0eb39d3b45ae`: `3c`, `3e`-`3j`, and `4e` (eight rows). The seven isolated
  entries are named only “Enantiomer II” without an absolute assignment, and
  `4e` is explicitly a racemate.
- `1a7457834b7a`: `31`, `33`, and `44` (three rows). Compound `33` is reported
  as a mixture of two diastereomers; the other two do not source-assign every
  represented stereogenic center.
- `2f3a5d2f7fb0`: `3`, `5`, and source-table label `21` (three rows). The
  sulfoxide centers in `3` and `5` are unassigned, while source label `21`
  corresponds to explicitly racemic article compound `21f`.
- `f2e855803f5a`: `CC-90009`, `LYG-101`-`108`, `LYG-201`-`207`,
  `LYG-301`-`309`, and `LYG-401`-`421` (46 rows). The source does not assign
  the glutarimide stereocenter as one unique experimental stereoisomer.

### Batch05 explicit R reconstruction

For `0eb39d3b45ae`, the following 28 experimental names explicitly assign the
omitted alpha center as `(R)`:

```text
3b, 3d
4a-4d, 4f-4l
5a-5h
6-12
```

For each entry, the DOI-exact CSV supplies complete connectivity and the main
article experimental name supplies the stereochemical assignment. RDKit
enumerates only the one unassigned tetrahedral center, selects the unique
R-CIP result, and preserves any center already encoded by the source. In
particular, compounds `11` and `12` each retain their distinct indoline center
and now also encode the shared alpha-(R) center.

The seven “Enantiomer II”-only entries are deliberately excluded from this
list. Elution order alone is not evidence for an absolute R/S assignment.

### Batch06 withdrawals

`2a98b0589a08 / 12` and `15` are described in the article as the
diastereoisomers containing both R and S sulfone-ring configurations relative
to the fixed R morpholine center. Their connectivity remains auditable in the
work table, but neither is published as one isomeric SMILES.

## Aggregate and evidence repairs

The aggregate builder now preserves reviewed annotation evidence verbatim;
it no longer substitutes an unrelated sentence merely because it occurs on
the same page and shares a derived label. It also maps evidence strength by
relation status:

```text
text_explicit   -> text_explicit
figure_explicit -> figure_explicit
human_confirmed -> human_confirmed
other           -> unresolved_context
```

This repairs 385 Batch05/06 `figure_explicit` strength values and prevents 391
annotation evidence strings from being silently replaced. For example,
`8991dc7472bd / 1 -> 2` again carries the annotation sentence beginning
“Changing the pyridine structure of compound 1 ...” and has
`evidence_strength=figure_explicit`.

The machine-source ingestion path now detects real unassigned tetrahedral and
double-bond stereochemistry. A newly imported `direct_source_structure` row
with such a risk receives `source_unspecified` and cannot be confirmed
automatically. Square-planar RDKit possibilities are excluded from this gate
because they produced topology-related false positives in this corpus.
Source-reviewed figure reconstructions retain their explicit human decision
and are not retrospectively reclassified by the machine-ingestion gate.

## Integrity and acceptance

After authoritative publication and aggregate rebuild:

```text
Batch05: 965 entities; 946 edges/evidence; 847 confirmed; 182 pair-ready
Batch06: 1,184 entities; 1,157 edges/evidence; 1,018 confirmed; 280 pair-ready

self-loops:                              0
duplicate directed edges:               0
dangling edge endpoints:                0
dangling evidence references:           0
unresolved pair-ready edges:            0
pair-ready endpoints with same SMILES:  0
confirmed rows missing work rows:       0
confirmed work rows not eligible:       0
```

Fresh automated and live checks:

```text
Lineage/structure tests: 323 passed in 88.80 s
Dashboard tests:          69 passed in 615.33 s
Live Dashboard checks:    23 / 23 passed
```

The live acceptance checks verify complete SMILES and RDKit-rendered PNGs for
`0eb39d3b45ae / 3b`, `11`, and `12`; image suppression and `--` for
`0eb39d3b45ae / 3c`, `4e`, `cfc4a0d0ef41 / 50`, `53`, `54`, and
`2a98b0589a08 / 12`, `15`; complete endpoints for every retained tested pair;
and the repaired `8991dc7472bd / 1 -> 2` evidence.

## Follow-up boundary

The repaired manifest covers every source-reviewed issue established in this
audit. There remain 59 RDKit stereo-risk hits—37 in Batch05 and 22 in
Batch06—that have not yet received individual source-level classification.
They may include true unassigned material, a unique isomer whose source row
omits stereo, or topology/bridgehead false positives. They are intentionally
left unchanged until paper/SI evidence supports a decision; they must not be
mass-assigned or mass-withdrawn from the RDKit warning alone.
