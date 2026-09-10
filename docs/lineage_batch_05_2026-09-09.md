# Lineage Batch 05

**Started:** 2026-09-09  
**Completed:** 2026-09-10  
**Status:** complete under the 2026-09-10 audited publication boundary

> **Audit revision (2026-09-10):** the original Batch05 publication counted
> 959 structures under an overly permissive stereochemistry boundary. A
> source-level repair has withdrawn 112 records that do not identify one
> unique experimental stereoisomer and has rebuilt 28 explicitly `(R)`
> entries from article-assigned experimental names. The current authoritative
> Batch05 result is **847 confirmed structures, 118 unresolved entities, and
> 182 pair-ready edges across 21 Papers**. The historical checkpoints below
> are retained to document what changed; see the audit addendum at the end of
> this report and `docs/batch05_06_audit_repair_2026-09-10.md`.

## Scope

Batch 05 contains the next 24 DOI-deduplicated Papers after the 90-Paper
post-Batch04 aggregate. Selection is deterministic and locked by a regression
test. All 24 local article PDFs are present.

| # | Paper ID | DOI | Modification statements | Evidence rows | Candidate paths | Evidence pages |
|---:|---|---|---:|---:|---:|---:|
| 1 | `a1d7361647de` | `10.1021/acs.jmedchem.4c01072` | 17 | 18 | 17 | 6 |
| 2 | `9fc4e02fbcdb` | `10.1021/acs.jmedchem.4c01766` | 16 | 25 | 16 | 11 |
| 3 | `8968e9a60ef9` | `10.1021/acs.jmedchem.3c01920` | 16 | 25 | 16 | 7 |
| 4 | `e64c071652ca` | `10.1021/acs.jmedchem.4c01464` | 16 | 20 | 16 | 5 |
| 5 | `ba6944db3fe2` | `10.1021/acs.jmedchem.4c01760` | 16 | 19 | 16 | 5 |
| 6 | `23fa35c9b113` | `10.1021/acs.jmedchem.4c01048` | 16 | 17 | 16 | 12 |
| 7 | `5589366efa06` | `10.1021/acs.jmedchem.4c02531` | 16 | 17 | 16 | 9 |
| 8 | `f2e855803f5a` | `10.1021/acs.jmedchem.4c01787` | 16 | 16 | 16 | 7 |
| 9 | `8b306e91bc78` | `10.1021/acs.jmedchem.3c01790` | 16 | 16 | 16 | 6 |
| 10 | `1a7457834b7a` | `10.1021/acs.jmedchem.4c01851` | 16 | 16 | 16 | 5 |
| 11 | `cfc4a0d0ef41` | `10.1021/acs.jmedchem.4c01221` | 15 | 25 | 15 | 11 |
| 12 | `a797514debbc` | `10.1021/acs.jmedchem.4c01303` | 15 | 23 | 15 | 9 |
| 13 | `d168508d74ca` | `10.1021/acs.jmedchem.4c01092` | 15 | 21 | 15 | 6 |
| 14 | `0eb39d3b45ae` | `10.1021/acs.jmedchem.4c01568` | 15 | 20 | 15 | 7 |
| 15 | `f501045da21f` | `10.1021/acs.jmedchem.4c01283` | 15 | 20 | 15 | 5 |
| 16 | `c6fdd5c7e071` | `10.1021/acs.jmedchem.3c02246` | 15 | 19 | 15 | 11 |
| 17 | `2f3a5d2f7fb0` | `10.1021/acs.jmedchem.3c01961` | 15 | 19 | 15 | 8 |
| 18 | `83d4f2ab5b7c` | `10.1021/acs.jmedchem.3c02473` | 15 | 17 | 15 | 10 |
| 19 | `dfe42148eabf` | `10.1021/acs.jmedchem.3c01976` | 15 | 17 | 15 | 6 |
| 20 | `14c9ce88d1c2` | `10.1021/acs.jmedchem.4c02093` | 15 | 17 | 15 | 6 |
| 21 | `5531836ee3c3` | `10.1021/acs.jmedchem.3c02460` | 15 | 16 | 15 | 10 |
| 22 | `1535ba2a9a58` | `10.1021/acs.jmedchem.4c00860` | 15 | 16 | 15 | 6 |
| 23 | `c3b3eba1f5b3` | `10.1021/acs.jmedchem.3c01347` | 15 | 15 | 15 | 8 |
| 24 | `df798aa2ca88` | `10.1021/acs.jmedchem.4c00856` | 14 | 23 | 14 | 10 |

## Baseline Before Publication

```text
Lineage Papers:       90 / 672
Compound entities:   2152
Lineage edges:       2041
structure_confirmed: 2146
Pair-ready edges:    1268
```

## Quality Boundary

- Evidence-density selection does not imply that all candidate statements are
  valid direct modification edges.
- Complete structure confirmation requires an exact Paper-local label binding,
  source locator, a unique single-component molecular graph, and RDKit
  validation.
- Number adjacency, scaffold similarity, and OCSR parseability are insufficient
  to infer a parent or a complete structure.
- Generic R groups, multi-stereoisomer records, and unresolved mixtures remain
  `--` until the source supports an explicit representation decision.
- Final Dashboard molecule images are redrawn from confirmed complete SMILES;
  article images are evidence only.

## Progress Log

### Checkpoint 1: batch boundary

- Fixed selection: `24 / 24` Paper IDs and DOIs.
- Local article PDFs: `24 / 24` present.
- Selection regression test: red on missing generator, then green after the
  fixed boundary and conflict validator were implemented.
- No annotation JSON or aggregate row was published at this checkpoint.

### Checkpoint 2: DOI-matched source discovery

- DOI-exact discovery attempted: `24 / 24` Papers; discovery failures: `0`.
- Figshare attachments discovered for `23 / 24` Papers: `81` rows total.
- Downloaded and inspected machine-readable candidates: `23`.
- Deferred, still uninspected attachments: `58` (`23` PDF, `29` PDB,
  `2` ZIP, `2` AVI, and `2` CIF across the full manifest extension counts;
  these rows are not described as reviewed sources).
- Initial manifest classification: `22` machine-readable structure tables and
  `1` apparent non-structure table. After the wrapped-row parser repair, all
  `23` downloaded candidates are recognized as structure tables.
- `d168508d74ca` exposed a reproducible parser edge case: every complete CSV
  row has one additional outer quote layer. A focused red/green regression
  test now parses this file as a structure table with `29 / 29` valid records;
  its manifest classification remains to be refreshed during the provisional
  entity/binding run.
- `23fa35c9b113` has no discovered Figshare attachment and therefore remains
  dependent on the local article PDF or a separately verified SI source.
- No structure was promoted to `structure_confirmed` merely because a source
  row parsed successfully.

### Checkpoint 3: Paper-local annotation

- Annotation JSON: `24 / 24` Papers.
- Paper-local compound entities: `965`.
- Directed lineage edges and evidence rows: `946` each.
- Relation status: `166` `text_explicit`, `24` `figure_explicit`, and `756`
  `unresolved`.
- Immediate parents were not inferred from numbering adjacency or molecular
  similarity. Series lacking an explicit parent remain `unresolved` and do not
  enter pair review.
- A regression test removed four phantom unsuffixed labels from
  `c6fdd5c7e071`: the source contains `43a-c`, `47a-c`, `53a-b`, and `55a-b`,
  but not independent compounds `43`, `47`, `53`, or `55`.

### Checkpoint 4: structure confirmation

The final Batch 05 entity-level structure result is:

```text
Paper-local entities:         965
Complete confirmed structures: 959
Deliberately unresolved:         6
```

The `959` confirmed structures comprise:

- `839` exact-label, complete, single-component machine-source structures;
- `105` explicit selections of the sole drug-like parent component from
  reviewed chloride/formic-acid source records;
- `3` reviewed primary-table rows whose identical structures were repeated in
  a trailing summary block (`5531836ee3c3`: `i15`, `i16`, and `i19`);
- `6` exact named-compound PubChem identifier matches: geldanamycin, 17-AAG,
  17-DMAG, 17-AG, SGC-PIKFYVE-1, and CC-90009;
- `5` complete graphs reconstructed from labeled main-article figures and
  cross-checked against the surrounding SAR or analytical data (`a1d7361647de`
  compounds `1` and `3`; `cfc4a0d0ef41` compound `7`; `df798aa2ca88`
  compound `4a`; `e64c071652ca` M17-B15);
- `1` Paper-local SI label audit binding the final `DA` row to the article's
  DLA control (`8968e9a60ef9`), supported by the matching reported activity.

All promoted structures are RDKit-parseable, complete, single-component,
dummy-free, and radical-free. The five figure reconstructions retain exact PDF
page/figure locators and review notes. M17-B15 is additionally checked against
the article's systematic name, molecular formula, and HRMS value.

The six remaining Batch 05 records are all in review Paper `23fa35c9b113`:

| Compound | Reason for retaining `--` |
|---|---|
| `13` | Natural-product derivative discussed without one Paper-local complete graph and immediate synthetic parent. |
| `19` | Variable-substituent C-19 sulfur family, not one unique molecule. |
| `20` | Variable-substituent C-19 sulfur family, not one unique molecule. |
| `24` | Range of variable 19-substituted thiol-adduct derivatives. |
| `29` | Review-level O-benzyloxime example without a sufficiently source-located complete graph for confirmation. |
| `33` | Variable-R 19-carbon-substituted family, not one unique molecule. |

These rows are quality boundaries, not failed ordinary SMILES parses. The
Dashboard must display `--` and must not generate a pseudo-complete molecule.

### Checkpoint 5: aggregate publication

Batch 05 contributes:

```text
Papers with lineage:          24
Lineages added:               24
Entities added:              965
Edges added:                 946
Explicit / figure edges:     190
Unresolved edges:            756
Pair-ready edges:            190
Papers with pair-ready:    23 / 24
```

The post-Batch05 aggregate is:

```text
Corpus Papers:                     672
Lineage Papers:                    114
Remaining corpus Papers:           558
Lineages:                          169
Compound entities:                3117
Lineage edges / evidence rows:     2987 / 2987
Activity rows:                      620
structure_confirmed rows:          3105
Complete structures:               3106
Missing / non-unique structures:     11
Pair-ready edges:                  1458
Papers with pair-ready edges:       112
```

The one-record difference between `structure_confirmed` (`3105`) and complete
structures (`3106`) is a pre-existing legacy `model_visual_match_confirmed`
entity, not a Batch 05 inconsistency.

### Checkpoint 6: final integrity and verification

Aggregate integrity audit:

```text
self-loops:                    0
duplicate directed edges:     0
unresolved pair-ready edges:  0
dangling entity references:   0
invalid pair endpoints:       0
```

Fresh test results after the final publication and rebuild:

```text
lineage/data tests: 293 passed in 6.40s
Dashboard tests:     69 passed in 495.17s
```

Commands:

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests

PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
```

## 2026-09-10 audit repair addendum

The stricter post-publication audit distinguishes a valid two-dimensional
connectivity graph from a source-supported unique stereochemical molecule.
It makes the following authoritative changes:

- 112 Batch05 confirmations are withdrawn. They comprise 52 entries in
  `cfc4a0d0ef41`, eight in `0eb39d3b45ae`, three in `1a7457834b7a`, three in
  `2f3a5d2f7fb0`, and 46 in `f2e855803f5a`.
- Of the `0eb39d3b45ae` source rows with one omitted alpha center, 28 have an
  experimental name that explicitly assigns `(R)`. Those entries receive a
  source-located `explicit_replace` work row after RDKit enumeration selects
  the unique R-CIP graph and preserves all source-encoded centers.
- `0eb39d3b45ae` compounds `3c` and `3e`-`3j` are described only as
  “Enantiomer II”. They are not assigned an arbitrary R/S configuration and
  now display `--`, as does explicitly racemic compound `4e`.
- Article-reported racemates, mixtures of two/four stereoisomers, and
  unassigned glutarimide/sulfoxide centers remain in the auditable work layer
  but no longer appear as one confirmed complete molecule.

The revised Batch05 result is:

```text
Paper-local entities:          965
Confirmed complete structures: 847
Missing / non-unique:           118
Lineage edges / evidence:   946 / 946
Text / figure explicit:    166 / 24
Unresolved context:             756
Pair-ready edges:               182
Papers with pair-ready:     21 / 24
```

Eight formerly pair-ready edges lost eligibility because at least one
endpoint was withdrawn. Every retained pair still has two distinct, complete,
confirmed structures. A further 37 Batch05 RDKit stereo-risk hits have not
been reclassified mechanically; they require individual source-level review
and are recorded as follow-up scope rather than being assigned arbitrary
stereochemistry.
