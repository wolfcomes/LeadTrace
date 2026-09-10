# Deep Lineage Batch Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand additional Paper records to the same root-template, direct-parent, complete-SMILES, evidence, and activity depth as Paper `7a695794fc7b`.

**Architecture:** Each Paper is annotated in an independent JSON file under `lineage_annotations/`, so Paper analysis can run in parallel without writing shared aggregate CSV files. `build_compound_lineages.py` validates and merges those files, binds structures and activity columns from DOI-matched ACS SI CSV files, computes iteration depths, and writes the shared Dashboard snapshot only after all per-Paper files pass validation.

**Tech Stack:** Python 3.12, JSON/CSV, RDKit, pytest, the existing Dashboard HTTP server, original article PDFs, and ACS Supporting Information CSV files.

---

### Task 1: Define the deep-annotation quality gate

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`

1. Add tests requiring a valid annotation to declare its evidence provenance and structure-completeness expectations.
2. Run the focused tests and confirm they fail for the missing validation.
3. Add minimal validation that rejects object-containment relationships, explicit edges without a direct parent, evidence that omits the derived label, and duplicate direct edges.
4. Run the focused tests and confirm they pass.

### Task 2: Annotate independent Papers

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/04effc6577c7.json`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/f25aa649b48e.json`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/e3b177ffc6cd.json`
- Create: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/75843eeb816b.json`

1. Read the article design/SAR sections and relevant Figure/Table captions.
2. Identify every independently supported root template.
3. Record each explicit direct parent-to-derived edge and retain unresolved parent relationships as `--`.
4. Cross-check every compound label against the DOI-matched SI CSV.
5. Declare the SI activity columns that can be displayed without interpretation.
6. Validate every JSON file with `python -m json.tool` and the lineage loader.

### Task 3: Regenerate and inspect the aggregate snapshot

**Files:**
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_evidence.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_activities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`

1. Run `build_compound_lineages.py`.
2. Confirm each annotated Paper has the expected root, branch, and iteration-depth graph.
3. Confirm pair eligibility requires two distinct complete RDKit-parseable structures.
4. Confirm unresolved edges do not become molecule pairs.

### Task 4: Verify the Dashboard end to end

**Files:**
- Test: `dashboard/tests/test_dashboard_server.py`
- Test: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

1. Run the complete Dashboard and extraction test suites.
2. Run Python and JavaScript syntax checks.
3. Restart the Dashboard on the active browser port.
4. Fetch every annotated Paper through the HTTP API.
5. Verify all formal pairs have `pair_kind=compound_optimization_lineage`, object IDs equal to `--`, and two complete RDKit-parseable SMILES.
6. Record the updated Paper, lineage, edge, pair-ready, unresolved, and remaining-corpus counts in `compound_lineage_summary.json`.
