# Compound Optimization Lineage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace image-containment-based molecule pairs with evidence-backed compound optimization lineages that retain both the root template and each direct parent-to-derived iteration.

**Architecture:** Add a derived graph layer with normalized compound entities, directed lineage edges, evidence records, and activities. Build it from text relationships plus reviewed structure mappings, expose it through the Paper detail API, and render it as lineage lanes while keeping image objects as evidence only.

**Tech Stack:** Python 3, CSV/JSON, RDKit, existing vanilla JavaScript/CSS Dashboard, pytest.

---

### Task 1: Stop treating object containment as a molecule pair

**Files:**
- Modify: `dashboard/server.py`
- Test: `dashboard/tests/test_dashboard_server.py`

**Steps:**

1. Add a failing regression test proving that `shared_scaffold -> variable_site` and `shared_scaffold -> replacement_fragment` links do not create `molecule_pair` review items.
2. Run the focused test and verify it fails against the current `_molecule_object_pair_links()` behavior.
3. Remove object-link pair generation from Paper counts and unified review items without deleting Objects or attachment-inference data.
4. Run the focused test and the complete Dashboard test suite.

### Task 2: Add normalized lineage records

**Files:**
- Create: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- Create: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_entities.csv`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_edges.csv`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_evidence.csv`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`

**Steps:**

1. Write failing tests for stable entity IDs, named external roots, direct-parent edges, one-to-many branches, iterative chains, and multiple lineages per Paper.
2. Add negative tests proving that comparison-only language, synthesis reactions, number adjacency, and object containment cannot confirm an edge.
3. Implement explicit relation extraction and Paper-local entity resolution.
4. Materialize lineage IDs, root IDs, and iteration depth after graph construction; flag cycles and conflicting confirmed parents for review.
5. Generate the first-page snapshot and verify that every edge references existing entities and evidence.

### Task 3: Resolve complete structures to compound entities

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- Test: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

**Steps:**

1. Write failing tests for exact label matching against SI/external references and reviewed molecule reconstructions.
2. Implement source precedence and preserve every structure source locator.
3. Reject fragments, wildcard atoms, unresolved attachment points, and object-level OCSR proposals as complete compound structures.
4. Canonicalize accepted SMILES with RDKit and assign a separate structure status and confidence.
5. Verify that unresolved sides stay `--` and that no pair image is generated from a partial structure.

### Task 4: Add compound-level activity records

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/scripts/build_compound_lineages.py`
- Generate: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_activities.csv`
- Test: `source_pdfs/分子修改提取_2024_JMC/tests/test_compound_lineages.py`

**Steps:**

1. Write failing tests for multiple assays per compound and explicit comparator values.
2. Extract compound-bound activity measurements without assigning paragraph-level values to every mentioned compound.
3. Link activity records to entities and edge evidence.
4. Keep unresolved values and qualitative activity statements as evidence rather than invented numeric measurements.

### Task 5: Expose and render lineage data

**Files:**
- Modify: `dashboard/server.py`
- Modify: `dashboard/app.js`
- Modify: `dashboard/styles.css`
- Test: `dashboard/tests/test_dashboard_server.py`

**Steps:**

1. Add failing API tests for `compound_entities`, `lineages`, direct edges, evidence, activities, and zero legacy object-based pairs.
2. Load the new snapshots into `/api/papers/<paper_id>` and produce complete-molecule images only from accepted SMILES.
3. Render one lane per lineage with the root template, immediate parent/derived pairs, branches, relation status, structure status, activity, and source evidence.
4. Preserve the filtered Objects section as a separate evidence browser.
5. Add edit-mode persistence for lineage edge corrections without modifying generated source snapshots.

### Task 6: Validate the representative Paper and all first-page Papers

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/README.md`
- Modify: `dashboard/README.md`

**Steps:**

1. Verify explicit routes in Paper `7a695794fc7b`, including `danuglipron -> compound 3`, `compound 2n -> compound 23`, and `compound 23 -> compound 24`.
2. Keep ambiguous parents such as later context-dependent series as unresolved until figure/table evidence establishes the direct parent.
3. Check every first-page Paper for false pairs, graph cycles, duplicate entities, dangling edges, and fragment-derived complete structures.
4. Run the complete structure-processing and Dashboard test suites plus Python/JavaScript syntax checks.
5. Restart the Dashboard and verify API counts, lineage rendering, complete-structure images, and edit persistence through HTTP smoke tests.
