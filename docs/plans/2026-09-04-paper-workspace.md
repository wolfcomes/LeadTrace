# Paper Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Paper-first review workspace with 20-paper pagination, Paper detail aggregation, and durable server-side review overrides.

**Architecture:** Keep the current snapshot CSV/JSON pipeline read-only. Add a small JSON review overlay beside the pipeline, expose Paper summary/detail/review APIs from the existing Python HTTP server, and make the browser render overview, library, and one Paper detail workspace with read/edit modes.

**Tech Stack:** Python standard library HTTP server and CSV/JSON readers, vanilla HTML/CSS/JavaScript, pytest.

---

### Task 1: Lock the server contract with tests

**Files:**
- Modify: `dashboard/tests/test_dashboard_server.py`

**Steps:**
1. Replace the 40-item pagination assertions with 20 items, 34 pages, and 12 items on page 34.
2. Add tests for stable manifest order and the `GET /api/papers/<paper_id>` detail payload.
3. Add isolated temporary-directory tests for review override persistence, unknown Paper rejection, and reviewed Paper locking.
4. Add HTTP tests for Paper detail and POST review.
5. Run the focused tests and confirm they fail because the new API and persistence functions do not exist yet.

### Task 2: Add durable review overrides and Paper detail APIs

**Files:**
- Modify: `dashboard/server.py`

**Steps:**
1. Set `PAPER_PAGE_SIZE` to 20 and define the review directory/path and allowed statuses.
2. Implement JSON override loading, validation, atomic save, and Paper ID lookup.
3. Merge override fields into summaries returned by `load_papers`.
4. Normalize evidence, candidates, explicit paths, structures, and proposals for one Paper detail response.
5. Add `POST /api/papers/<paper_id>/review` with JSON body validation and reviewed-state protection.
6. Run the focused server tests and then the full dashboard test module.

### Task 3: Reshape the frontend around Paper detail

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/app.js`
- Modify: `dashboard/styles.css`

**Steps:**
1. Keep only overview and Paper library in primary navigation, with overview first.
2. Change the Paper library copy and controls to 20 per page and add review-status filtering.
3. Replace the side detail panel with a full Paper detail view that loads the detail API and shows all linked data layers.
4. Keep the SMILES/RDKit image as the primary structure display and source images as evidence-only labels.
5. Post edits to the review API, preserve read/edit mode behavior, and show unsaved/edit/locked states.
6. Add responsive styles for the full detail workspace and data tables.
7. Run `node --check dashboard/app.js`.

### Task 4: Update documentation and verify the assembled workspace

**Files:**
- Modify: `dashboard/README.md`

**Steps:**
1. Document the Paper-first navigation, 20/page behavior, detail/review endpoints, and override file.
2. Run dashboard tests, Python compilation, and API smoke tests.
3. Compare hashes of representative original pipeline CSV files before/after the review API smoke test.
4. Start the dashboard on an available local port and report the URL.
