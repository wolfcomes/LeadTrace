# Lineage Batch 05 Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the next 24 DOI-deduplicated Papers to the evidence-backed compound lineage pipeline without inventing direct parent relationships.

**Architecture:** A batch-specific generator will declare the selected Paper IDs, DOI set, and conservative per-Paper annotations. Explicit article statements become directed edges; series observations without a unique immediate parent become `unresolved` records with `parent=--`. The existing lineage builder remains the single writer for aggregate CSV/JSON outputs, and existing structure-source/confirmed-structure precedence remains authoritative.

**Tech Stack:** Python 3.12, pytest, pandas/PyMuPDF for source inspection, RDKit for single-component structure validation, existing CSV/JSON lineage pipeline.

---

## Approved Selection

The 2026-09-09 post-repair aggregate is the immutable Batch 05 baseline:

- 90 lineage Papers;
- 2,152 Paper-local compound entities;
- 2,041 lineage edges;
- 2,146 `structure_confirmed` rows;
- 1,268 pair-ready edges.

Selection starts from Papers that are absent from both the lineage aggregate
and every existing annotation JSON. It also excludes any DOI already represented
by another Paper ID. Remaining Papers are ranked deterministically by:

1. descending `modification_statement` count;
2. descending total evidence-row count;
3. descending path-candidate count;
4. descending distinct evidence-page count;
5. descending Paper ID as a stable final tie-breaker.

The fixed Batch 05 Paper IDs, in selection order, are:

```text
a1d7361647de  9fc4e02fbcdb  8968e9a60ef9  e64c071652ca
ba6944db3fe2  23fa35c9b113  5589366efa06  f2e855803f5a
8b306e91bc78  1a7457834b7a  cfc4a0d0ef41  a797514debbc
d168508d74ca  0eb39d3b45ae  f501045da21f  c6fdd5c7e071
2f3a5d2f7fb0  83d4f2ab5b7c  dfe42148eabf  14c9ce88d1c2
5531836ee3c3  1535ba2a9a58  c3b3eba1f5b3  df798aa2ca88
```

This explicit list prevents the batch from drifting after aggregate rebuilds.

## Scope and Invariants

- The batch contains exactly 24 Paper IDs and none may already occur in `compound_lineage_summary.json`.
- Paper identity is DOI-based; a DOI already represented in lineage is excluded even when its Paper ID differs.
- Annotation edges must not contain self-loops.
- Explicit edges (`text_explicit`, `figure_explicit`, `human_confirmed`) require a direct parent and evidence text mentioning the derived label.
- Unresolved edges use `parent=--` and never become pair-ready.
- Pair-ready status is delegated to the existing builder and requires two confirmed, complete, single-component RDKit structures.

## Implementation Steps

1. Add a failing Batch 05 regression test for selection boundaries and annotation invariants.
2. Add `generate_lineage_batch_05_annotations.py` with the selected 24 Paper IDs and conservative evidence declarations.
3. Run the generator and validate all generated JSON through `load_lineage_annotations`.
4. Rebuild aggregate lineage outputs with the existing builder.
5. Discover and inspect source attachments for all 24 Paper IDs. Publish
   machine-readable and reviewed reconstructions before the final aggregate
   snapshot; retain salts, mixtures, generic R groups, and ambiguous structures
   outside `structure_confirmed` until an explicit decision exists.
6. Rebuild aggregate outputs after structure confirmation and run the lineage,
   pipeline, and Dashboard test suites.
7. Report explicit/unresolved edges, entity and structure counts, pair-ready
   counts, deferred manual reviews, and remaining corpus Papers. Do not describe
   a Paper as complete merely because it has an annotation JSON.
