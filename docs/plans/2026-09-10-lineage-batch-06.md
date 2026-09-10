# Lineage Batch 06 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Process the fixed next 24 DOI-deduplicated Papers into source-backed compound lineages, uniquely recoverable complete structures, RDKit-confirmed molecule pairs, and Dashboard-readable aggregate outputs.

**Architecture:** A Batch 06 generator owns the fixed scope and Paper-local evidence annotations. The existing source manifest, work table, confirmation publisher, and lineage builder retain their current responsibilities; batch-specific repair publishers may only construct audited candidates for the common confirmation gate. Annotation, structure confirmation, aggregate publication, and Dashboard verification remain separate checkpoints.

**Tech Stack:** Python 3.12, CSV/JSON, PyMuPDF, ACS Figshare sources, RDKit, pytest, and the existing Dashboard HTTP server.

**Workspace note:** This directory is not a Git repository. Steps that normally commit changes are replaced by explicit file inventories, deterministic generated outputs, and fresh test evidence. No Git operation is permitted.

---

### Task 1: Lock the Batch 06 Boundary

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_06_annotations.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

1. Add a failing test requiring the exact 24 Paper/DOI pairs.
2. Run the focused test and confirm failure because the Batch 06 module does not exist.
3. Implement the constants and boundary validator only.
4. Require unique IDs/DOIs and disjointness from existing annotations and aggregate DOI ownership, while allowing only the Batch 06 output filenames during a rerun.
5. Run the focused test and confirm it passes.

### Task 2: Inventory Paper and Supporting Sources

**Files:**
- Create: `docs/lineage_batch_06_2026-09-10.md`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_manifest.csv`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/structure_source_snapshot.json`
- Generate under: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_structure_sources/<paper_id>/`

1. Record title, DOI, local PDF, evidence counts, path counts, and evidence pages for all 24 Papers.
2. Discover DOI-exact supporting attachments.
3. Download and inspect machine-readable structure candidates; retain other attachments with honest deferred status.
4. Record schemas, label fields, salts/mixtures, stereochemistry, and rejected rows.
5. Do not count a source as inspected merely because it was discovered or downloaded.

### Task 3: Create Conservative Paper-local Annotations

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/generate_lineage_batch_06_annotations.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/lineage_annotations/<batch06-paper-id>.json`

1. Inspect the SAR text and the referenced Figure/Table/Scheme context for each Paper.
2. Add a failing test requiring exactly 24 payloads, valid DOI/version, no self-loop, no duplicate edge, explicit parent/evidence rules, and `parent=--` for unresolved rows.
3. Add only source-supported direct edges; preserve all uncertain series as unresolved.
4. Preserve Paper-local suffixes, prime marks, stereo labels, names, and prior-art origins.
5. Generate and reload all 24 JSON files through `load_lineage_annotations`.

### Task 4: Bind and Confirm Complete Structures

**Files:**
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- Update: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
- Optionally create: `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch06_*_repairs.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

1. Build a provisional aggregate so every selected label has a Paper-local entity.
2. Run source inspection and exact-label binding for the fixed 24 Papers.
3. For each parser change, component selection, duplicate repair, external identifier, or figure/R-group reconstruction, first add a focused failing test and observe the expected failure.
4. Publish only complete single-component candidates with source locators and recorded stereochemistry decisions.
5. Retain generic, ambiguous, conflicting, or unsupported graphs as `--` with a reason.

### Task 5: Publish and Audit the Aggregate

**Files:**
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_evidence.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_activities.csv`
- Regenerate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`

1. Run the lineage builder after annotation and again after structure publication.
2. Assert zero self-loops, duplicate directed edges, dangling references, unresolved pair-ready rows, and invalid pair endpoints.
3. Verify every pair-ready endpoint is distinct, confirmed, complete, single-component, dummy-free, radical-free, and RDKit-parseable.
4. Compare exact aggregate deltas with the 114-Paper baseline.
5. Confirm the only newly introduced lineage Papers are the fixed Batch 06 scope.

### Task 6: Verify Dashboard and Record Progress

**Files:**
- Modify: `docs/lineage_batch_06_2026-09-10.md`
- Modify: `docs/lineage_batch_progress_2026-09-09.md`
- Modify: `docs/project_conversation_record_2026-09-09.md`
- Test: `dashboard/tests/test_dashboard_server.py`

1. Run the complete lineage/data test suite in a fresh process.
2. Run the complete Dashboard test suite with `PYTHONPATH=.`.
3. Restart the Dashboard and fetch all 24 Paper detail endpoints.
4. Verify representative complete molecule-pair PNGs and deliberately unresolved boundaries over HTTP.
5. Report annotation, source, structure, relation, pair-ready, integrity, test, and aggregate figures separately.
