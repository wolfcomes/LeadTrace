# Lineage Batch 06 Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the next 24 DOI-deduplicated Papers to the evidence-backed compound lineage pipeline without weakening the Batch 05 source and parent-relation standards.

**Architecture:** Batch 06 uses a batch-specific annotation generator with a fixed Paper/DOI boundary. Paper-local structure sources are discovered and bound through the existing structure work table; reviewed graph reconstruction, component selection, and external identifiers are published only through the common RDKit confirmation gate. The existing lineage builder remains the only aggregate writer and the Dashboard continues to consume only aggregate outputs.

**Tech Stack:** Python 3.12, CSV/JSON, PyMuPDF, ACS Figshare discovery, RDKit, pytest, and the existing Dashboard HTTP API.

---

## Selection Decision

Three selection approaches were considered:

1. **Continue deterministic evidence-density ranking — selected.** This keeps
   Batch 06 comparable with Batch 05 and is reproducible from corpus tables.
2. Prefer Papers that already expose machine-readable SI. This would improve
   short-term structure yield but bias the sample toward source availability.
3. Select randomly from the remaining corpus. This would reduce ranking bias
   but make the next batch harder to reproduce and less information-dense.

The ranking is unchanged from Batch 05:

1. descending `modification_statement` count;
2. descending total evidence-row count;
3. descending path-candidate count;
4. descending distinct evidence-page count;
5. descending Paper ID as the stable final tie-breaker.

Selection excludes every Paper ID already owned by an annotation or aggregate
lineage and every DOI already represented under another Paper ID. Replaying the
algorithm against the pre-Batch05 boundary exactly reproduces all 24 Batch 05
IDs, validating the implementation of the selection rule.

## Fixed Batch 06 Scope

```text
01  2c96aaf509b1  10.1021/acs.jmedchem.4c03149
02  56f50284cedf  10.1021/acs.jmedchem.4c01645
03  434e5748f070  10.1021/acs.jmedchem.4c01744
04  f3d107dabbcb  10.1021/acs.jmedchem.3c02302
05  1485ed4aa91b  10.1021/acs.jmedchem.4c00555
06  c150a5edd8dd  10.1021/acs.jmedchem.4c01815
07  8991dc7472bd  10.1021/acs.jmedchem.3c02441
08  1994543a9112  10.1021/acs.jmedchem.4c00265
09  bf54bac4775b  10.1021/acs.jmedchem.4c02377
10  feef9e819b88  10.1021/acs.jmedchem.4c01727
11  2a98b0589a08  10.1021/acs.jmedchem.4c00734
12  c958fce90ec5  10.1021/acs.jmedchem.4c01395
13  e4043323f96c  10.1021/acs.jmedchem.4c02169
14  65e19df86a4a  10.1021/acs.jmedchem.4c01323
15  cab92325187b  10.1021/acs.jmedchem.3c02288
16  8e421ecc451e  10.1021/acs.jmedchem.3c02046
17  07dcad0214c3  10.1021/acs.jmedchem.3c02203
18  7e503b3382bf  10.1021/acs.jmedchem.4c01178
19  4bd630dc5dc8  10.1021/acs.jmedchem.4c00972
20  2d5a56fffb44  10.1021/acs.jmedchem.4c00357
21  c6c61d0fc737  10.1021/acs.jmedchem.4c00643
22  096b579fa25f  10.1021/acs.jmedchem.3c01934
23  023145d60eea  10.1021/acs.jmedchem.4c00513
24  b09de250fcb3  10.1021/acs.jmedchem.4c03205
```

## Data Flow and Quality Boundary

For each Paper:

1. inspect the article, SI inventory, structure tables, figures, schemes, and
   relevant SAR prose;
2. identify complete molecules, scaffolds, R-group definitions, and attachment
   positions before producing a SMILES;
3. record `root template -> immediate parent -> derived compound` only when the
   immediate parent is source-supported;
4. retain series membership as `unresolved` with `parent=--` when the direct
   parent is not uniquely stated;
5. confirm structures only after exact Paper-local binding, complete-graph
   review, single-component validation, and RDKit parsing;
6. redraw Dashboard molecule images from confirmed SMILES only.

Generic R-group structures, unresolved mixtures, multi-stereoisomer records,
unsupported stereochemistry, and prior-art roots without an exact source remain
`--`. RDKit parseability is a syntax/graph check and is never reported as
structure accuracy.

## Error Handling and Verification

- The batch boundary test requires exactly 24 unique IDs and DOIs disjoint from
  pre-Batch06 annotations and lineages.
- Annotation tests reject self-loops, duplicate directed edges, explicit edges
  without a parent, and unresolved edges with a parent.
- Source parser and repair changes require focused red/green tests before
  production edits.
- Aggregate audit requires zero self-loops, duplicate directed edges, dangling
  entity references, unresolved pair-ready rows, and invalid pair endpoints.
- Completion requires fresh full data tests, Dashboard tests, and HTTP checks of
  representative confirmed and deliberately unresolved records.

## Reporting

The Batch 06 report will separately state annotation coverage, explicit versus
unresolved relationships, confirmed complete structures, deliberate `--`
records, pair-ready edges, source files inspected/deferred, and aggregate
deltas. A Paper is not described as fully processed merely because an
annotation JSON exists.
