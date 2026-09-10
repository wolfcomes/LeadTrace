# Lineage Structure Reconstruction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Discover source-backed structures, reconstruct scaffold/R-group compounds, RDKit-validate complete molecules, and bind confirmed structures to all existing lineage entities.

**Architecture:** A new Paper-centric pipeline discovers and inspects ACS Figshare attachments, emits auditable work candidates, assembles atom-mapped scaffold/R-group records, and writes a minimal authoritative confirmed-structure table. The existing lineage builder consumes that table at the highest local-source precedence and recalculates pair eligibility without changing source PDFs or annotation JSON.

**Tech Stack:** Python 3.12, standard-library HTTP/CSV/ZIP utilities, pandas/openpyxl where available for spreadsheets, RDKit for molecule parsing/assembly/rendering, pytest.

---

The workspace root is not a Git repository. Commit steps from the standard workflow are therefore recorded as checkpoints and cannot be executed in this workspace.

### Task 1: Define The Source Manifest And Atomic Snapshot Contract

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

**Step 1: Write the failing tests**

Add tests that assert:

- Figshare search and article-detail payloads become deterministic manifest rows;
- every row contains `paper_id`, `doi`, `article_id`, `source_file`, `download_url`, `extension`, `content_class`, `local_path`, `download_status`, and `inspection_status`;
- structure-like extensions are candidates but are not classified as machine-readable structures until their contents are inspected;
- CSV and JSON snapshots are written atomically.

Use injected fake HTTP functions so unit tests never use the network.

**Step 2: Run the tests and verify they fail**

Run:

```bash
cd source_pdfs/分子修改提取_2024_JMC
pytest -q tests/test_lineage_structure_reconstruction.py
```

Expected: collection fails because `lineage_structure_reconstruction` does not exist.

**Step 3: Implement the minimal manifest layer**

Implement constants for the three CSV contracts, DOI normalization, Figshare
metadata conversion, conservative extension classification, checksum helpers,
and atomic CSV/JSON writers. Network access must be behind injected callables.

**Step 4: Run the tests and verify they pass**

Run the Task 1 test subset and expect all tests to pass.

**Step 5: Checkpoint**

Record the passing test count in the progress summary. Git commit is unavailable.

### Task 2: Inspect And Parse Machine-Readable Structure Sources

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

**Step 1: Write the failing tests**

Create fixtures for:

- CSV with `Compound_ID` and `SMILES`;
- CSV with no structure column;
- XLSX with a numbered compound and SMILES column;
- SDF containing a compound-label property;
- duplicate labels with conflicting structures;
- invalid SMILES and CXSMILES annotations.

Tests must require exact label extraction, canonical isomeric SMILES, source-row
locators, and an explicit rejection reason for non-structure or conflicting data.

**Step 2: Run the tests and verify they fail**

Run only the new source-inspection tests and expect missing parser failures.

**Step 3: Implement content inspection**

Implement format-aware parsers using `csv`, `pandas`/`openpyxl`, and RDKit's
`SDMolSupplier`/`MolFromMolFile`. Detect label and SMILES columns from normalized
header aliases. Remove trailing CXSMILES metadata only after preserving the raw
value. Never infer chemical content from the extension alone.

**Step 4: Run the tests and verify they pass**

Run the source-inspection subset, then all tests in the new test module.

**Step 5: Checkpoint**

Capture supported formats and rejected-fixture counts in the progress summary.

### Task 3: Match Source Records To Paper-Local Lineage Entities

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

**Step 1: Write the failing tests**

Tests must cover exact numeric, alphanumeric, qualified labels such as
`18 (CHF-6523)`, Paper-local namespaces, duplicate source labels, and labels that
do not appear in `compound_entities.csv`. Assert that only one-to-one exact or
normalized-prefix matches become candidates.

**Step 2: Run the tests and verify they fail**

Expected: candidate binding helpers are missing.

**Step 3: Implement candidate matching**

Build an entity index keyed by `(paper_id, normalized_label)`. Emit work rows for
valid mappings and retain unmatched/conflicting records with dispositions such
as `unmatched_label`, `duplicate_conflict`, or `invalid_structure`.

**Step 4: Run the tests and verify they pass**

Run the candidate-binding subset and the complete new test module.

**Step 5: Checkpoint**

Record exact matches, unmatched records, and conflicts per Paper.

### Task 4: Reconstruct Scaffold And R-Group Molecules

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

**Step 1: Write the failing tests**

Use small chemically valid fixtures to test:

- one scaffold site and one R group;
- two independently mapped scaffold sites;
- a replacement fragment whose attachment atom is not its first atom;
- aromatic and single-bond attachment;
- missing, duplicate, or mismatched atom maps;
- a product that retains a dummy atom;
- stereochemistry already encoded in scaffold or fragment input.

**Step 2: Run the tests and verify they fail**

Expected: `assemble_mapped_fragments` is missing.

**Step 3: Implement mapped graph assembly**

Parse scaffold and fragment SMILES containing paired atom-map dummy atoms such
as `[*:1]`. For each map, identify both neighboring atoms and intended bond type,
combine the graphs, add the resolved bond, remove the paired dummies in descending
atom-index order, sanitize, and canonicalize with `isomericSmiles=True`. Reject
every incomplete or non-bijective mapping.

**Step 4: Run the tests and verify they pass**

Run the reconstruction subset and inspect canonical products with RDKit.

**Step 5: Checkpoint**

Record all supported and rejected attachment cases.

### Task 5: Enforce Confirmation Rules And Write Authoritative Structures

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/lineage_structure_reconstruction.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

**Step 1: Write the failing tests**

Test complete single-component molecules, salts, mixtures, unresolved dummies,
unsupported stereochemistry, invalid valence, deterministic canonicalization,
existing confirmed values, and two candidates that disagree. Assert that only
an explicitly accepted candidate can emit `confirmation_status=structure_confirmed`.

**Step 2: Run the tests and verify they fail**

Expected: strict confirmation selection is missing.

**Step 3: Implement validation and selection**

Separate RDKit validation from source confirmation. Require complete graph,
unambiguous label, accepted source/reconstruction evidence, and recorded visual
or exact machine-readable match. Preserve salts and mixtures as unresolved unless
an explicit component-selection decision is stored. Never overwrite an existing
confirmed structure with a weaker or conflicting candidate.

**Step 4: Run the tests and verify they pass**

Run all new tests and verify the output uses only `structure_confirmed` as the
final confirmation state.

**Step 5: Checkpoint**

Record confirmed, pending, rejected, and conflict counts.

### Task 6: Bind Confirmed Structures Into The Lineage Builder

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

**Step 1: Write the failing tests**

Add tests proving that:

- a confirmed Paper-local structure binds by label without requiring an image
  object;
- its canonical SMILES and source fields reach `compound_entities.csv`;
- `structure_review_status` is exactly `structure_confirmed`;
- existing object IDs remain attached as evidence;
- an edge becomes pair-ready only when both sides are complete and confirmed;
- pending or rejected work rows never affect entities.

**Step 2: Run the tests and verify they fail**

Run the new `test_compound_lineages.py` cases and expect missing confirmed-input
support.

**Step 3: Implement confirmed-structure ingestion**

Add `DEFAULT_CONFIRMED_STRUCTURES`, read only rows with
`confirmation_status=structure_confirmed`, merge them at explicit confirmed-local
precedence, and retain current source and object evidence. Update `pair_eligible`
to require a complete canonical structure and final structure confirmation for
new rows while preserving equivalent legacy confirmed states.

**Step 4: Run the tests and verify they pass**

Run `pytest -q tests/test_compound_lineages.py` and the full suite.

**Step 5: Checkpoint**

Compare entity and edge counts before and after fixture ingestion.

### Task 7: Run A Five-Paper Calibration Batch

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_manifest.csv`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_structure_reconstruction_summary.json`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_structure_sources/`

**Step 1: Select fixtures from real Papers**

Choose five zero-structure Papers whose attachments cover CSV, XLS/XLSX or ZIP,
PDF-only scaffold/R-group tables, stereochemistry, and at least one non-structure
CSV. Record the Paper IDs in the summary before processing.

**Step 2: Discover and download sources**

Run the pipeline in discovery/download mode. Verify checksums, local paths, and
content classifications before parsing.

**Step 3: Generate work candidates**

Parse machine-readable sources first. Render and inspect PDF regions only for
remaining entity labels. Store direct and reconstructed candidates with complete
provenance and explicit disposition.

**Step 4: Validate and confirm**

Run RDKit validation, generate standardized molecule renderings, compare them
against the source graph, and mark accepted candidates `structure_confirmed`.
Leave ambiguous attachment or stereochemistry cases pending.

**Step 5: Rebuild lineage outputs**

Run the lineage builder, compare before/after entity coverage and pair-ready
counts, and ensure no unrelated Paper changes unexpectedly.

### Task 8: Scale To All Existing Lineage Papers

**Files:**
- Modify generated CSV and JSON files from Task 7 only through pipeline commands.
- Create: `docs/lineage_structure_reconstruction_2026-09-08.md`

**Step 1: Verify calibration quality**

Review all confirmed calibration structures and classify errors by label mapping,
graph connectivity, R-group placement, or stereochemistry. Fix pipeline logic and
add a regression test for every systematic error before scaling.

**Step 2: Process Papers in parallel**

Parallelize DOI discovery, downloads, and per-Paper candidate generation. Keep
authoritative CSV merging single-writer and deterministic.

**Step 3: Re-run the full suite**

Run:

```bash
cd source_pdfs/分子修改提取_2024_JMC
pytest -q
```

Expected: the existing suite and all new reconstruction tests pass.

**Step 4: Audit final data**

Report lineage Papers processed, entities total, direct-source confirmations,
R-group reconstructions, pending candidates, rejected candidates, pair-ready
edges, and remaining unresolved entities. Spot-check standardized RDKit drawings
for each reconstruction class.

**Step 5: Record progress**

Write the dated report with exact commands, counts, unresolved reasons, source
coverage, and the next batch boundary. Keep the dashboard service running.
