# Lineage Batch 02

**Started:** 2026-09-07

**Scope:** 24 previously unannotated articles selected by SAR evidence density. Selection is deduplicated by DOI so the duplicate RIPK2 corpus record `8f4efc7b9dbf` is not counted separately from `438346965cd9`.

**Standard:** Follow `7a695794fc7b`: root template -> direct parent -> derived compound; use only text/Figure/Table/Scheme-supported medicinal-chemistry relations; keep unresolved parents and unconfirmed structures as `--`; do not convert image-object containment into lineage; require complete RDKit-parseable structures on both sides for pair readiness.

| Paper ID | DOI | Status |
|---|---|---|
| `438346965cd9` | `10.1021/acs.jmedchem.4c01313` | completed |
| `676e00cd96f3` | `10.1021/acs.jmedchem.4c02008` | completed |
| `d84a31c8bd03` | `10.1021/acs.jmedchem.3c01745` | completed |
| `7aaab67d167f` | `10.1021/acs.jmedchem.4c00411` | completed |
| `ee7d9dadb421` | `10.1021/acs.jmedchem.4c00639` | completed |
| `d9cea0896bb8` | `10.1021/acs.jmedchem.4c00527` | completed |
| `86188f27cbfc` | `10.1021/acs.jmedchem.4c00211` | completed |
| `640830bbe4e7` | `10.1021/acs.jmedchem.4c00483` | completed |
| `42ab02822a52` | `10.1021/acs.jmedchem.4c02870` | completed |
| `34de43d32dbf` | `10.1021/acs.jmedchem.3c02099` | completed |
| `24598d139950` | `10.1021/acs.jmedchem.4c00322` | completed |
| `e5f3a608a794` | `10.1021/acs.jmedchem.4c00338` | completed |
| `4a0c8af474d7` | `10.1021/acs.jmedchem.3c01338` | completed |
| `a70d61499fa0` | `10.1021/acs.jmedchem.3c00951` | completed |
| `840ae8d2dffb` | `10.1021/acs.jmedchem.4c01764` | completed |
| `67b71a6c93c9` | `10.1021/acs.jmedchem.4c02161` | completed |
| `387473d95eba` | `10.1021/acs.jmedchem.4c00045` | completed |
| `863a8dc1db41` | `10.1021/acs.jmedchem.4c01743` | completed |
| `7e6d7738d3fa` | `10.1021/acs.jmedchem.4c01539` | completed |
| `782ae9975ace` | `10.1021/acs.jmedchem.4c01304` | completed |
| `5c1b2ee84c36` | `10.1021/acs.jmedchem.3c01905` | completed |
| `47a078594b6b` | `10.1021/acs.jmedchem.3c02266` | completed |
| `af1d2e15528b` | `10.1021/acs.jmedchem.3c02483` | completed |
| `381572722037` | `10.1021/acs.jmedchem.4c01214` | completed |

**Progress fields to report after each sub-batch:** annotation file, edge count, explicit/unresolved counts, structure source and RDKit coverage, pair-ready count, and any source-label discrepancy.

## Progress Log

### 2026-09-08 sub-batch 01

Completed annotation JSON files: `9 / 24` in this batch.

| Paper ID | Edges | Explicit | Unresolved | Structure source | RDKit coverage | Pair-ready |
|---|---:|---:|---:|---|---:|---:|
| `438346965cd9` | 26 | 18 | 8 | no local matching complete SI source | 0 / 29 entities | 0 |
| `676e00cd96f3` | 48 | 43 | 5 | no local matching complete SI source | 0 / 49 entities | 0 |
| `d84a31c8bd03` | 28 | 28 | 0 | no local matching complete SI source | 0 / 29 entities | 0 |
| `7aaab67d167f` | 46 | 46 | 0 | no local matching complete SI source | 0 / 47 entities | 0 |
| `ee7d9dadb421` | 36 | 36 | 0 | confirmed local structure rows for 2 entities; no complete source for remaining entities | 2 / 37 entities | 1 |
| `d9cea0896bb8` | 50 | 35 | 15 | no local matching complete SI source | 0 / 48 entities | 0 |
| `86188f27cbfc` | 30 | 30 | 0 | no local matching complete SI source | 0 / 31 entities | 0 |
| `42ab02822a52` | 38 | 34 | 4 | no local matching complete SI source | 0 / 39 entities | 0 |
| `640830bbe4e7` | 32 | 31 | 1 | no local matching complete SI source | 0 / 33 entities | 0 |

The completed annotation count records evidence-backed lineage work only. It does not mean that all compound structures are SMILES-confirmed or that every edge is pair-ready. The remaining `15` Papers are still queued.

### 2026-09-08 sub-batch 02 started

The remaining `15` queued Papers have been split into four disjoint annotation groups. Each group is writing only its assigned per-Paper annotation JSON; shared lineage CSVs will be rebuilt only after all files are validated.

| Group | Papers | Status |
|---|---:|---|
| A | `34de43d32dbf`, `24598d139950`, `e5f3a608a794` | completed |
| B | `4a0c8af474d7`, `a70d61499fa0`, `840ae8d2dffb` | completed |
| C | `67b71a6c93c9`, `387473d95eba`, `863a8dc1db41`, `7e6d7738d3fa` | completed |
| D | `782ae9975ace`, `5c1b2ee84c36`, `47a078594b6b`, `af1d2e15528b`, `381572722037` | completed |

No SMILES are being guessed in this sub-batch. Final progress will report per-Paper edge counts, explicit/unresolved counts, structure-source and RDKit coverage, and pair-ready counts after aggregation.

### 2026-09-08 sub-batch 02 completed

Completed annotation JSON files: `24 / 24` in this batch. The final `15` Papers added `627` evidence-backed lineage edges.

| Paper ID | Edges | Explicit | Unresolved | RDKit coverage | Pair-ready |
|---|---:|---:|---:|---:|---:|
| `34de43d32dbf` | 37 | 35 | 2 | 0 / 38 entities | 0 |
| `24598d139950` | 31 | 27 | 4 | 0 / 33 entities | 0 |
| `e5f3a608a794` | 58 | 58 | 0 | 0 / 59 entities | 0 |
| `4a0c8af474d7` | 66 | 15 | 51 | 0 / 67 entities | 0 |
| `a70d61499fa0` | 58 | 56 | 2 | 0 / 59 entities | 0 |
| `840ae8d2dffb` | 51 | 51 | 0 | 0 / 51 entities | 0 |
| `67b71a6c93c9` | 33 | 29 | 4 | 0 / 36 entities | 0 |
| `387473d95eba` | 54 | 35 | 19 | 0 / 58 entities | 0 |
| `863a8dc1db41` | 33 | 29 | 4 | 0 / 34 entities | 0 |
| `7e6d7738d3fa` | 37 | 26 | 11 | 0 / 39 entities | 0 |
| `782ae9975ace` | 29 | 29 | 0 | 0 / 30 entities | 0 |
| `5c1b2ee84c36` | 32 | 32 | 0 | 0 / 33 entities | 0 |
| `47a078594b6b` | 55 | 39 | 16 | 0 / 56 entities | 0 |
| `af1d2e15528b` | 17 | 10 | 7 | 0 / 15 entities | 0 |
| `381572722037` | 36 | 36 | 0 | 0 / 36 entities | 0 |

No audited complete-structure source was available locally for these `15` Papers, so no SMILES were guessed and no new pair-ready rows were promoted. The annotation loader was extended to recognize explicit source ranges such as `2-7`, `A1-A3`, `C1-C19`, `5b-5z`, and abbreviated `36a-b`; exact-label and negative out-of-range checks remain enforced.

After aggregation, the corpus contains `47` lineage Papers, `1,269` lineage edges, `1,324` compound entities, `188` unresolved-parent edges, and `240` pair-ready edges. The remaining corpus count is `625 / 672` Papers without lineage data.
