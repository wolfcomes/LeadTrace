# Lineage Batch 05 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Process the fixed next 24 DOI-deduplicated Papers into source-backed compound lineages, complete structures where uniquely recoverable, RDKit-confirmed molecule pairs, and Dashboard-readable aggregate outputs.

**Architecture:** A Batch 05 generator owns only the fixed selection and per-Paper evidence annotations. Source discovery and structure confirmation continue through the existing auditable work/confirmation pipeline, while `build_compound_lineages.py` remains the only aggregate writer. Annotation, structure confirmation, and aggregate publication are separate checkpoints so an uncertain graph or parent cannot become a display pair merely because a Paper was selected.

**Tech Stack:** Python 3.12, CSV/JSON, PyMuPDF/pdftotext, ACS Figshare source discovery, RDKit, pytest, existing Dashboard HTTP API.

**Workspace note:** This project is not a Git repository. The commit steps normally required by the planning workflow are replaced with explicit file inventories, generated snapshots, and fresh verification output; no Git operation is permitted.

---

### Task 1: Lock the Batch Boundary

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_05_annotations.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

1. Add a failing test importing the Batch 05 generator and requiring the exact 24 Paper IDs.
2. Require selection IDs and DOIs to be unique and disjoint from existing annotations/aggregate DOIs.
3. Run the focused test and confirm the expected missing-module failure.
4. Implement the constants and validation helper only.
5. Run the focused selection test and confirm it passes.

### Task 2: Build the Source and Evidence Packets

**Files:**
- Create: `docs/lineage_batch_05_2026-09-09.md`
- Generate under: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_structure_sources/<paper_id>/`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_manifest.csv`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_snapshot.json`

1. Record each Paper's DOI, title, local PDF, evidence rows, and candidate paths.
2. Discover DOI-matched supporting-information attachments.
3. Download machine-readable structure tables and retain PDF/PDB/ZIP rows in the manifest with honest status.
4. Inspect source schemas, labels, salts/mixtures, stereochemistry, and activity columns.
5. Record per-Paper source counts and unresolved source issues in the Batch 05 report.

### Task 3: Add Conservative Per-Paper Annotations

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_05_annotations.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/<batch05-paper-id>.json`

1. For each Paper, inspect Results/SAR text and relevant Figure/Table/Scheme context.
2. Add a failing invariant test requiring exactly 24 Batch 05 payloads, unique edges, no self-loops, direct parents on explicit relations, and `parent=--` on unresolved records.
3. Declare only source-supported direct edges; put series membership without a unique immediate parent into `unresolved` rows.
4. Preserve Paper-local suffixes, prime marks, stereochemical qualifiers, preferred names, and prior-art origins.
5. Generate JSON files and validate them with `load_lineage_annotations`.

### Task 4: Confirm Complete Structures

**Files:**
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
- Optionally create: `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_repairs.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

1. Build a provisional aggregate to create Paper-local entities for structure binding.
2. Run source inspection/binding for all 24 selected Papers.
3. Add focused failing tests before each manually reconstructed or component-selected structure family.
4. Reconstruct Figure/Scheme R-group structures only when scaffold, substitutions, attachment mapping, and stereochemistry are source-supported.
5. Publish accepted structures through the common confirmation gate.
6. Keep generic R structures, multi-stereoisomer compounds, unresolved mixtures, dummy atoms, and unsupported stereochemistry as `--`.

### Task 5: Publish and Audit the Aggregate

**Files:**
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_evidence.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_activities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`

1. Run the lineage builder after structure publication.
2. Assert zero self-loops, duplicate directed edges, dangling references, and unresolved pair-ready rows.
3. Assert every pair-ready endpoint is distinct, `structure_confirmed`, complete, single-component, dummy-free, radical-free, and RDKit-parseable.
4. Compare all aggregate deltas with the 90-Paper baseline and explain every removed/replaced row.
5. Confirm no Paper outside the fixed 24 was newly introduced by Batch 05.

### Task 6: Verify Dashboard and Report Progress

**Files:**
- Modify: `docs/lineage_batch_05_2026-09-09.md`
- Modify: `docs/lineage_batch_progress_2026-09-09.md`
- Modify: `docs/project_conversation_record_2026-09-09.md`
- Test: `dashboard/tests/test_dashboard_server.py`

1. Run all lineage tests from a fresh process.
2. Run all Dashboard tests with `PYTHONPATH=.`.
3. Fetch each Batch 05 Paper from the Dashboard API and verify lineage/pair counts and generated-SMILES images.
4. Report Papers with lineage, explicit/figure/unresolved edges, entities, confirmed/missing structures, pair-ready edges, and reason-coded unresolved rows.
5. State separately what is structurally complete and what still lacks unique parent evidence.
