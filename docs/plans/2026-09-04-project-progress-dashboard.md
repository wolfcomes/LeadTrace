# Project Progress Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local web dashboard that truthfully summarizes the JMC lead-optimization pipeline and supports human review of current path and OCSR records.

**Architecture:** A Python standard-library HTTP server reads the existing pipeline CSV/JSON files and serves cached JSON endpoints plus reviewed PNG assets. A dependency-free HTML/CSS/JavaScript client renders the overview, path queue, OCSR review workspace, and evidence table; localStorage holds only browser-local review notes.

**Tech Stack:** Python 3.12 standard library, HTML5, CSS, vanilla JavaScript, pytest.

---

### Task 1: Define the dashboard data contract with failing tests

**Files:**
- Create: `dashboard/tests/test_dashboard_server.py`
- Create: `dashboard/server.py`

**Step 1: Write the failing tests**

Cover overview counts, distinct stage semantics, explicit-path filtering, and safe asset lookup. Tests should import the server module and use the real current pipeline snapshots for the overview contract.

**Step 2: Run tests to verify RED**

Run: `python -m pytest dashboard/tests/test_dashboard_server.py -q`

Expected: collection fails because `dashboard.server` does not yet exist.

**Step 3: Implement the minimal server data layer**

Add path constants, UTF-8 CSV/JSON readers, overview aggregation, paginated path loading, proposal loading, and a safe basename-only asset resolver. Keep all source pipeline files read-only.

**Step 4: Run tests to verify GREEN**

Run: `python -m pytest dashboard/tests/test_dashboard_server.py -q`

Expected: all server contract tests pass.

### Task 2: Add local HTTP endpoints and static serving

**Files:**
- Modify: `dashboard/server.py`
- Modify: `dashboard/tests/test_dashboard_server.py`

**Step 1: Write the failing endpoint tests**

Test `/api/overview`, `/api/paths`, `/api/proposals`, one path detail endpoint, and asset traversal rejection using an in-process handler or a temporary HTTP server.

**Step 2: Run the endpoint tests to verify RED**

Run: `python -m pytest dashboard/tests/test_dashboard_server.py -q`

Expected: endpoint tests fail because the HTTP handler is absent.

**Step 3: Implement the handler**

Serve dashboard files, return JSON with stable error responses, serve only known reviewed page/crop PNG basenames, and accept query parameters for search, scope, priority, status, page, and page size.

**Step 4: Run the endpoint tests to verify GREEN**

Run: `python -m pytest dashboard/tests/test_dashboard_server.py -q`

Expected: all tests pass.

### Task 3: Build the dashboard shell and overview

**Files:**
- Create: `dashboard/index.html`
- Create: `dashboard/styles.css`
- Create: `dashboard/app.js`

**Step 1: Add the semantic page shell**

Create navigation for Overview, Path queue, OCSR review, and Evidence; include a live snapshot label and responsive main regions.

**Step 2: Add overview rendering**

Render KPI metrics, stage map, workload queue, data-quality alerts, and an explicit zero-final-confirmations state using `/api/overview`.

**Step 3: Add visual system and responsive layout**

Implement the paper/ink/coral/teal palette, compact dashboard typography, stable metric dimensions, mobile stacking, loading, empty, and error states.

### Task 4: Build path queue, detail panel, and evidence view

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/styles.css`
- Modify: `dashboard/app.js`

**Step 1: Add queue controls and table**

Implement explicit/unresolved tabs, search, priority/status filters, pagination, and row selection without loading all unresolved records into the DOM.

**Step 2: Add selected path detail**

Show parent/derived IDs, text evidence, activity mentions, source page, cited references, available structure slots, and proposal links. Make pending structure state prominent.

**Step 3: Add evidence view**

Render an evidence-first table with source page links and a selected evidence preview using safely served PNGs.

### Task 5: Build OCSR review workspace with local review ledger

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/styles.css`
- Modify: `dashboard/app.js`

**Step 1: Render proposal queue and structure evidence**

Show crop image, source evidence page, compound role/ID, raw SMILES, confidence summary, RDKit status, canonical SMILES, and model version.

**Step 2: Add review actions**

Store only localStorage notes and review states under a versioned dashboard key. Expose copy buttons and a clear read-only warning. Do not create a confirmed-structure write path.

**Step 3: Add error and incomplete states**

Handle invalid RDKit proposals, absent parent or derived crops, image load failures, and empty proposal queues without layout shifts.

### Task 6: Document, run, and inspect the finished dashboard

**Files:**
- Create: `dashboard/README.md`

**Step 1: Document startup and data boundaries**

Document `python dashboard/server.py`, the local URL, endpoint behavior, source directories, and localStorage review semantics.

**Step 2: Run verification**

Run: `python -m pytest dashboard/tests/test_dashboard_server.py -q`

Run: `python dashboard/server.py --host 127.0.0.1 --port 8765`

Use browser or HTTP checks against `/`, `/api/overview`, `/api/paths`, and `/api/proposals`; confirm the page renders on desktop and mobile-sized viewports if browser tooling is available.

**Step 3: Report the actual output**

Report test counts, local URL, current dashboard counts, and any environment limitation preventing screenshot inspection.
