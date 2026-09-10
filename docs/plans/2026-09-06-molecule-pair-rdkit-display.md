# Molecule Pair RDKit Display Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render every molecule-pair entry's complete candidate structure from its assembled SMILES and use that RDKit image as the primary visual in the Paper unified review list.

**Architecture:** The server will generate deterministic PNGs from `assembled_smiles` with RDKit into the existing auto-fill asset area and expose them through the approved asset resolver. A molecule pair with no complete, parseable candidate remains explicitly pending and keeps its PDF crops only as source evidence. The frontend will render the generated complete structure first, then show candidate SMILES and compact source crops as provenance.

**Tech Stack:** Python 3, RDKit, the existing local HTTP dashboard, vanilla JavaScript, pytest.

---

### Task 1: Specify RDKit molecule-pair image generation

**Files:**
- Modify: `dashboard/tests/test_dashboard_server.py`
- Modify: `dashboard/server.py`

**Step 1: Write failing tests**

Add tests for deterministic rendering of a valid assembled SMILES, rejection of endpoint-marked fragment SMILES as a complete image input, and exposure of the generated image URL in a molecule-pair review item.

**Step 2: Run the focused tests**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_rdkit`

Expected: FAIL because the renderer and image URL do not exist yet.

**Step 3: Implement the minimal renderer**

Add a small server helper that parses `assembled_smiles`, rejects empty values and `[*:n]` endpoint markers, writes a stable PNG filename derived from a hash of the SMILES, and returns an empty result when RDKit cannot parse the candidate. Add the generated URL to each molecule-pair payload without changing the source snapshots.

**Step 4: Run the focused tests**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_rdkit`

Expected: PASS.

### Task 2: Make generated structure assets servable

**Files:**
- Modify: `dashboard/server.py`
- Modify: `dashboard/tests/test_dashboard_server.py`

**Step 1: Write the asset-serving regression test**

Verify that the generated molecule-pair PNG URL resolves through the existing approved asset endpoint and that missing candidates have no generated image URL.

**Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_asset`

Expected: FAIL until the asset root is registered and the image is generated.

**Step 3: Implement asset registration**

Register the molecule-pair RDKit image directory in `resolve_asset` and ensure the helper creates the directory before writing. Keep basename and path-traversal protections unchanged.

**Step 4: Run the test**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_asset`

Expected: PASS.

### Task 3: Replace the molecule-pair primary visual in the unified review item

**Files:**
- Modify: `dashboard/app.js`
- Modify: `dashboard/styles.css`
- Modify: `dashboard/tests/test_dashboard_server.py`

**Step 1: Write the frontend contract test**

Assert that the molecule-pair renderer uses the generated RDKit image as its primary structure visual and labels PDF crops as source evidence.

**Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_primary_visual`

Expected: FAIL because the current renderer puts parent/derived crops first and shows a pending placeholder.

**Step 3: Update the renderer and styles**

Render the complete RDKit image first when available, followed by assembled and fragment SMILES, status facts, inference note, and a compact source-evidence crop row. Render an explicit pending state when no complete candidate exists. Add responsive styles for the primary structure image and source evidence row.

**Step 4: Run the focused test and syntax checks**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py -k molecule_pair_primary_visual`

Run: `node --check dashboard/app.js`

Expected: PASS with no syntax errors.

### Task 4: Full verification and live dashboard refresh

**Files:**
- Modify: `dashboard/README.md`

**Step 1: Document the display contract**

State that molecule-pair primary images are RDKit renders from complete assembled SMILES, while PDF crops are provenance only; incomplete candidates remain pending.

**Step 2: Run all verification**

Run: `PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py`

Run: `PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts pytest -q source_pdfs/分子修改提取_2024_JMC/tests`

Run: `node --check dashboard/app.js && python -m py_compile dashboard/server.py`

Expected: all tests pass and syntax checks exit successfully.

**Step 3: Start the dashboard and inspect live Paper data**

Run the current dashboard on the user's active local port, inspect Paper `7a695794fc7b`, and verify that the entries with assembled candidates expose generated RDKit PNG URLs while unresolved pairs remain pending.
