# Legacy Dashboard Split Source Paths Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make legacy Dashboard Paper list and detail payloads display the reorganized `volume<number> issue<number>` source directory and a project-relative PDF path.

**Architecture:** Add a read-only filename index for eligible issue directories beneath `source_pdfs`, then normalize each canonical Paper record during payload assembly. Preserve snapshot metadata whenever the physical match is missing or ambiguous, and do not expose or serve the resolved filesystem path.

**Tech Stack:** Python 3.12 standard library, existing `dashboard/server.py`, pytest, HTTP smoke tests

---

### Task 1: Resolve Split Source Locations

**Files:**
- Modify: `dashboard/tests/test_dashboard_server.py`
- Modify: `dashboard/server.py`

**Step 1: Write the failing resolver tests**

Add focused tests that point the resolver at a temporary `source_pdfs` root and
assert that a unique `volume67 issue1/paper.pdf` match becomes:

```python
{
    "source_folder": "volume67 issue1",
    "source_pdf": "source_pdfs/volume67 issue1/paper.pdf",
}
```

Also assert that missing and duplicate physical filenames preserve the input
metadata, and that two Paper inputs may resolve to the same physical PDF.

**Step 2: Run the resolver tests to verify RED**

Run:

```bash
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k split_source_location
```

Expected: FAIL because the source-location resolver does not exist.

**Step 3: Implement the minimal resolver**

In `dashboard/server.py`:

- define `SOURCE_PDFS_ROOT = PROJECT_ROOT / "source_pdfs"`;
- accept only direct child directories matching `volume\d+ issue\d+`;
- index regular `.pdf` files by basename;
- return normalized display fields only for a unique match;
- use `Path.as_posix()` on a path relative to `PROJECT_ROOT`;
- preserve the input values for missing or ambiguous matches.

Keep the implementation read-only and independent of file size.

**Step 4: Run the resolver tests to verify GREEN**

Run the command from Step 2.

Expected: all selected tests pass.

### Task 2: Apply Resolution to Canonical Paper Payloads

**Files:**
- Modify: `dashboard/tests/test_dashboard_server.py`
- Modify: `dashboard/server.py`

**Step 1: Write the failing payload test**

Patch the source index for a known fixture Paper and assert both `load_papers()`
and `load_paper_detail()` return the same new `source_folder` and relative
`source_pdf` value.

**Step 2: Run the payload test to verify RED**

Run:

```bash
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k paper_payload_uses_split_source_location
```

Expected: FAIL because canonical Paper assembly still copies the historical
document-index values.

**Step 3: Apply the resolver once during Paper assembly**

Normalize the source fields in the function that constructs canonical Paper
records so all list/detail consumers receive identical data without duplicate
logic.

**Step 4: Run the payload test to verify GREEN**

Run the command from Step 2.

Expected: PASS.

### Task 3: Verify and Restart the Legacy Dashboard

**Files:**
- Modify: `dashboard/README.md`

**Step 1: Document the display-only path resolution**

Explain that source locations are resolved by filename from direct
`volume<number> issue<number>` directories at startup and require a restart
after reorganizing the corpus.

**Step 2: Run static and full regression verification**

Run:

```bash
python -m py_compile dashboard/server.py
node --check dashboard/app.js
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
```

Expected: compilation and syntax checks exit zero; all Dashboard tests pass.

**Step 3: Restart the existing read-only service**

Stop only the process listening on `127.0.0.1:8765` after verifying its command
is `dashboard/server.py --read-only`, then start the current code with the same
interpreter, host, port, and read-only option.

**Step 4: Run live HTTP acceptance**

Check `/`, `/api/overview`, Paper list, and two Paper detail records whose
resolved locations exercise volume 67 and volume 68. Verify that writes still
return HTTP 405 and that no absolute local source path appears in the Paper
payloads.

**Step 5: Review the final diff**

Run `git diff --check` and `git status --short`. Confirm that only the planned
Dashboard files and plan document are attributable to this task; preserve all
pre-existing LeadTrace changes.
