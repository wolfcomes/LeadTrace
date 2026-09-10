# Lineage Paper Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `Lineage` as the only new Paper-library Pipeline filter while keeping the existing four workflow filters and removing any standalone `Confirmed` filter.

**Architecture:** The Paper catalog keeps its primary `workflow_status` (`text_ready`, `evidence_review`, `candidate_review`, or `path_review`) unchanged. The server exposes a derived `lineage` filter that selects records with at least one lineage edge, and the client adds that option to the Pipeline select and label map.

**Tech Stack:** Python standard-library dashboard server, vanilla JavaScript, pytest.

---

### Task 1: Lock the filter contract with tests

**Files:**
- Modify: `dashboard/tests/test_dashboard_server.py`

**Steps:**
1. Add a test that `load_papers(status="lineage")` returns only Papers with `lineage_edge_count > 0` and includes the expected lineage Paper IDs.
2. Add a test that the HTML Pipeline select contains `Lineage` and does not contain a `Confirmed` option.
3. Run the focused tests and confirm they fail because the server and HTML do not yet expose the new option.

### Task 2: Implement the derived Lineage filter

**Files:**
- Modify: `dashboard/server.py`

**Steps:**
1. Treat `lineage` as a derived catalog filter using `lineage_edge_count > 0`.
2. Preserve the existing workflow-status filtering for the four original statuses.
3. Keep each Paper row's displayed primary workflow status unchanged.

### Task 3: Add the UI option and label

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/app.js`

**Steps:**
1. Add the `Lineage` option to the Pipeline select.
2. Add the `lineage` label mapping for pipeline labels.
3. Allow overview navigation/filter handling to preserve the new value if it is used later.

### Task 4: Verify the complete behavior

**Steps:**
1. Run the focused dashboard tests.
2. Run the complete Dashboard test file.
3. Run Python and JavaScript syntax checks.
4. Call `/api/papers?status=lineage&page_size=20` on the active local server and verify the response contains only lineage Papers.
