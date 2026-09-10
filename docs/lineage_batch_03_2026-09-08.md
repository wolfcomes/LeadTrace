# Lineage Batch 03

**Date:** 2026-09-08  
**Post-repair snapshot:** 2026-09-09

**Scope:** The next 24 Papers after the previous 47-Paper lineage set. The
batch follows the `7a695794fc7b` standard: Paper-local labels, explicit
parent-to-derived evidence, source-first structure resolution, conservative
R-group handling, RDKit validation, and no pair promotion when either endpoint
is unresolved.

## Batch Result

| Metric | Result |
|---|---:|
| Papers requested | 24 |
| Figshare source attachments discovered | 103 |
| Attachments downloaded and inspected | 26 |
| Machine-readable structure attachments | 24 |
| Paper-local Papers with lineage entities | 19 |
| Paper-local compound entities | 268 |
| `structure_confirmed` entities | 268 |
| Lineage edges | 242 |
| Pair-ready edges | 62 |
| Papers with pair-ready edges | 18 |
| Papers with no supported lineage | 2 |
| Papers held for manual lineage review | 3 |

The remaining 77 attachments are PDF, PDB, or ZIP files intentionally deferred
from this source-first pass. They remain in
`09_paper_review/auto_fill/structure_source_manifest.csv` with their download
and inspection status; they were not silently discarded.

## Per-Paper Progress

`E/U` means explicit or figure-supported edges versus unresolved-parent edges.
The source column is `discovered attachments / downloaded attachments`.

| Paper ID | Source | Entities | Confirmed | Edges E/U | Pair-ready | Status |
|---|---:|---:|---:|---:|---:|---|
| `e04dfea8eedb` | 18 / 1 | 0 | 0 | 0 / 0 | 0 | manual lineage review |
| `aad1af4320ce` | 3 / 1 | 9 | 9 | 6 / 2 | 6 | processed |
| `2cd1c423645f` | 2 / 1 | 17 | 17 | 6 / 10 | 6 | processed |
| `35c6365ddfa1` | 2 / 1 | 7 | 7 | 5 / 0 | 5 | processed |
| `9126813c6d98` | 2 / 1 | 8 | 8 | 3 / 3 | 3 | processed |
| `66b63d71b500` | 2 / 1 | 36 | 36 | 0 / 35 | 0 | series parents unresolved |
| `6f5323ca6636` | 8 / 1 | 24 | 24 | 1 / 22 | 1 | processed |
| `51180402d2ac` | 4 / 1 | 0 | 0 | 0 / 0 | 0 | no supported lineage |
| `7ecfba90bd62` | 5 / 1 | 14 | 14 | 1 / 12 | 1 | processed |
| `7709b4e1637d` | 2 / 1 | 0 | 0 | 0 / 0 | 0 | manual lineage review |
| `3b16e57c63cb` | 5 / 1 | 3 | 3 | 2 / 0 | 2 | processed; XLSX content under CSV name |
| `a4380f187553` | 3 / 1 | 0 | 0 | 0 / 0 | 0 | manual lineage review |
| `360b9bc1c4fe` | 3 / 1 | 19 | 19 | 2 / 15 | 2 | processed |
| `2c57076f0b26` | 10 / 1 | 13 | 13 | 1 / 11 | 1 | processed; compound `7` structure repaired |
| `f4b9ad99e0a3` | 2 / 1 | 34 | 34 | 1 / 32 | 1 | processed; `16a-16j` labels retained |
| `265d6151a4f8` | 3 / 1 | 42 | 42 | 6 / 33 | 6 | processed |
| `cc5929fc88ba` | 3 / 1 | 2 | 2 | 1 / 0 | 1 | processed |
| `cf3d5e3ba03c` | 4 / 1 | 3 | 3 | 2 / 0 | 2 | processed |
| `836f93c225ef` | 5 / 2 | 11 | 11 | 10 / 0 | 10 | processed; `6 (QXG-6442)` normalized to `6` |
| `cf88ca0c12c6` | 2 / 1 | 2 | 2 | 1 / 0 | 1 | processed; stereo labels preserved |
| `eb9f347196d0` | 9 / 2 | 3 | 3 | 2 / 0 | 2 | processed |
| `0de5157cf90a` | 2 / 1 | 0 | 0 | 0 / 0 | 0 | no supported lineage |
| `0dbd1ded12e3` | 2 / 1 | 8 | 8 | 3 / 2 | 3 | processed; one blank source row retained as audit |
| `5688225882e4` | 2 / 1 | 13 | 13 | 9 / 3 | 9 | processed |

## Structure And Lineage Rules Applied

- Exact SI CSV/XLSX structures were canonicalized with RDKit and bound only to
  a unique Paper-local label.
- Complete confirmed structures are single-component, dummy-free, and
  radical-free. RDKit parseability alone was not used as a lineage claim.
- `(R)-4`, `(S)-4`, `(R)-5`, and `(R)/(S)-XY-05` remain distinct labels. The
  damaged racemate prefix in the SI for `2c57076f0b26` is normalized to the
  corresponding racemic numeric label without inventing absolute
  stereochemistry.
- `3b16e57c63cb` was content-detected as XLSX even though Figshare named the
  downloaded file with a `.csv` suffix.
- `e04dfea8eedb` uses a semicolon-delimited SI with an `identification number`
  label column; that alias is now recognized, but the Paper has no supported
  direct lineage edge and therefore no entity rows.
- Generic series statements, comparator-only statements, mixtures, and
  ambiguous direct parents remain unresolved or pending rather than being
  connected by numbering adjacency.

## Files Updated

- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/`
  - 24 batch annotation JSON files.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_manifest.csv`
  - source discovery and inspection manifest.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_snapshot.json`
  - checksummed manifest snapshot.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
  - auditable direct-source candidates, unmatched labels, and pending records.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
  - authoritative confirmed structures.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
  - Paper-local structure binding.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
  - lineage and pair eligibility snapshot.
- `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_structure_reconstruction_summary.json`
  - batch processing summary.
- `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch03_04_repairs.py`
  - source-reviewed post-batch structure repairs published through the common
    RDKit confirmation gate.

## Code And Tests

The batch added the annotation generator
`source_pdfs/分子修改提取_2024_JMC/scripts/generate_next_lineage_batch_annotations.py`.
The source parser now recognizes `identification number` label columns and
preserves stereo-qualified labels while safely handling damaged racemate
prefixes.

Fresh post-repair verification completed on 2026-09-09:

```text
source_pdfs/分子修改提取_2024_JMC: 281 passed
dashboard/tests/test_dashboard_server.py: 69 passed
independent structure/manifest/lineage audit: PASS
```

The next follow-up is manual scheme/figure review for the five Papers without
entity-backed lineage output and for unresolved direct parents. The current
confirmed tables are already safe for the Dashboard: no unsupported structure
is promoted to a complete molecule pair. Batch 03 is now structurally complete
at `268 / 268`; its remaining limitation is the 180 relations whose unique
immediate parent is not source-supported.
