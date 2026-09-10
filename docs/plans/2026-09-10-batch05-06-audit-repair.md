# Batch05 / Batch06 Audit Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish the evidence-backed Batch05 / Batch06 stereochemistry repairs and rebuild a semantically correct lineage aggregate.

**Architecture:** A batch-specific repair publisher validates immutable source work rows, rejects non-unique/source-insufficient structures, and publishes source-located R-isomer replacements before invoking the existing aggregate builder.  General aggregate evidence behavior is corrected in the common builder and protected by focused regression tests.

**Tech Stack:** Python 3.12, RDKit, CSV/JSON, pytest, the existing Python Dashboard server.

---

### Task 1: Lock the reviewed structure decision boundary

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_06_audit_repairs.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

1. Write failing tests asserting exactly 112 Batch05 exclusions, 28
   `0eb39d3b45ae` replacements, and two Batch06 exclusions.
2. Assert that the manifests reject missing, duplicate, or substituted
   immutable source work rows.
3. Run the focused tests and verify they fail because the publisher does not
   yet exist.
4. Implement constants and manifest builders with paper/label-specific source
   notes.
5. Run the focused tests and verify they pass.

### Task 2: Reconstruct the 28 source-defined active R enantiomers

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/publish_batch05_06_audit_repairs.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_lineage_structure_reconstruction.py`

1. Write failing tests that each selected source graph has exactly one
   unassigned tetrahedral center and that the repaired graph assigns it CIP R.
2. Assert connectivity equivalence after removing stereochemistry and
   preservation of the pre-existing indoline centers in compounds 11 and 12.
3. Run the focused tests and observe the expected failure.
4. Implement RDKit stereoisomer enumeration and select the unique candidate
   whose formerly unassigned center is CIP R.
5. Build accepted `reviewed_complete_structure` rows with exact source files,
   article pages, and `explicit_replace` decisions.
6. Run the focused tests and verify they pass.

### Task 3: Correct evidence strength and evidence ownership

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`

1. Write a failing test showing that a `figure_explicit` edge receives
   `figure_explicit` evidence strength.
2. Write a failing regression test in which a same-page sentence mentions the
   derived label but must not replace the annotation evidence sentence.
3. Run both tests and verify the current failures.
4. Implement the explicit status-to-strength mapping and make annotation
   evidence authoritative.
5. Run focused and full lineage tests.

### Task 4: Publish structures and rebuild the aggregate

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_structure_work.csv`
- Modify: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/confirmed_compound_structures.csv`
- Modify: aggregate CSV/JSON files under `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/`

1. Run the repair publisher against temporary copies and assert the expected
   counts and idempotency.
2. Run the publisher against authoritative files.
3. Rebuild `compound_entities.csv`, `compound_lineage_edges.csv`,
   `compound_lineage_evidence.csv`, `compound_activities.csv`, and
   `compound_lineage_summary.json` with `build_compound_lineages.py`.
4. Audit exact Batch05/Batch06 confirmed and pair-ready counts, all 28 R-CIP
   assignments, absence of the 114 excluded records, and standard graph/ID
   invariants.

### Task 5: Verify Dashboard and document the repair

**Files:**
- Modify: `docs/lineage_batch_05_2026-09-09.md`
- Modify: `docs/lineage_batch_06_2026-09-10.md`
- Create: `docs/batch05_06_audit_repair_2026-09-10.md`

1. Run the full lineage/structure pytest suite.
2. Run the Dashboard test suite because published API-visible counts and
   molecule availability changed.
3. Restart the Dashboard only if required to reload data.
4. Verify live Paper endpoints for representative repaired, excluded, and
   unaffected compounds; verify excluded image endpoints are suppressed and
   repaired R-SMILES render.
5. Record before/after counts, exact repaired labels, remaining review queue,
   test output, and Dashboard URL in the repair report.

This workspace is not a Git repository; commit steps are intentionally omitted
and every changed artifact will instead be enumerated in the final report.
