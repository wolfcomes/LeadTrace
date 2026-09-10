# First Page Fragment Structure Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize the first 20 manifest Papers into a fragment-aware structure review snapshot and Dashboard view that prioritizes PDF image interpretation and SMILES accuracy gates.

**Architecture:** Add a deterministic Python snapshot builder under the existing JMC scripts. It joins read-only manifest, OCR candidate/proposal, auto-fill, and progress layers into a 20-Paper derived CSV/JSON snapshot. Extend the local Dashboard server with a read-only endpoint and render a chemistry-first panel while preserving the existing Paper workspace and review persistence boundaries.

**Tech Stack:** Python 3, CSV/JSON, existing `dashboard/server.py`, vanilla JavaScript/CSS, pytest.

---

### Task 1: Add first-page snapshot builder

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/build_first_page_fragment_review.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/tests/test_first_page_fragment_review.py`

**Steps:**

1. Write tests for selecting the first 20 manifest Papers, joining proposal rows, classifying RDKit proposal quality, preserving R/linker notation, and writing deterministic output fields.
2. Run the focused tests and verify they fail because the builder does not exist.
3. Implement the builder with explicit input/output paths under `09_paper_review/auto_fill/`, proposal classification, attachment-point preservation, and a summary JSON.
4. Run the focused tests and verify they pass.

### Task 2: Generate the first-page derived snapshot

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/` generated outputs only

**Steps:**

1. Run the builder against the current full snapshots.
2. Check that output contains exactly 20 Papers and 31 candidate rows.
3. Check that every record is proposal-only and all missing or unresolved fragment fields use `--` or an explicit unresolved state.

### Task 3: Add Dashboard API and view

**Files:**
- Modify: `dashboard/server.py`
- Modify: `dashboard/app.js`
- Modify: `dashboard/index.html`
- Modify: `dashboard/styles.css`
- Modify: `dashboard/tests/test_dashboard_server.py`

**Steps:**

1. Add a server loader and `GET /api/first-page-structure` endpoint for the derived snapshot.
2. Add a failing API test for 20 Papers, 31 candidates, and accuracy-state fields.
3. Implement the endpoint and render a chemistry-first first-page panel in the overview.
4. Add compact styles for crop, reasoning fields, accuracy gates, and candidate tables without introducing a second top-level navigation item.
5. Run Dashboard tests and browser/static checks.

### Task 4: Verify and document the result

**Files:**
- Modify: `dashboard/README.md`
- Modify: `source_pdfs/分子修改提取_2024_JMC/README.md`

**Steps:**

1. Document the first-page structure review snapshot and accuracy semantics.
2. Run `PYTHONPATH=. pytest -q`.
3. Run `node --check dashboard/app.js` and `python -m py_compile` for modified Python files.
4. Start a fresh Dashboard port and verify the endpoint returns the generated 20-Paper snapshot.
