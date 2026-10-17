# Reviewer editing workflow implementation plan

**Goal:** Add persistent undo/redo, Compound/Lineage copy and paste, Lineage search and explicit viewed, local IUPAC conversion, and problem-report submissions.

**Approved design:** User approved server-side undo/redo with append-only history and optimistic version checks; current-Lineage viewed without edge navigation; search Compound identifiers/names across Lineages; local OPSIN conversion validated by RDKit; exceptional submissions with required reason and frozen blockers that cannot be published. Copy/paste only Compound and Lineage, with label/name blank on paste. Same-workspace only; reset copied review status and do not copy view receipts. Lineage copies reuse Compounds but create new members/edges. No live migrations/deployment.

**Architecture:** Extend existing workspace mutation locking/versioning. Persist reversible before/after domain states separately from immutable audit history, and add compensating history entries when undoing/redoing. All content mutations invalidate redo and incompatible external writes block undo. Use dedicated APIs for cloning, conversion and exceptional submission. Keep current permissions and snapshot integrity.

**Tech stack:** FastAPI, SQLAlchemy, PostgreSQL, Vue, Vitest, RDKit, local OPSIN.

## 1. Baseline and isolation
Use codex/reviewer-editing worktree. Create a disposable UTF-8 PostgreSQL cluster, dedicated *_test database and external TMPDIR. Install isolated backend/frontend dependencies. Run affected baseline tests serially for DB.

## 2. Undo and redo
Files: backend/app/workspaces/edit_history.py (new), service.py, workbench.py, main.py registration as needed, migrations/versions/0037_reviewer_edit_history.py (new), frontend/src/review/paper/WorkspaceHistory.vue (new), PaperWorkspacePage.vue.
Write failing tests for create/update/delete with dependencies, undo/redo, redo invalidation, external updates and permissions. Add immutable history snapshots and a cursor with fresh versions, preserve scientific assets and protected metadata, invalidate viewing receipts on restored content. Run backend history/API tests against disposable DB; add toolbar interaction and conflict tests.

## 3. Compound and Lineage copying
Files: backend/app/workspaces/clipboard.py (new), frontend/src/review/paper/RecordClipboard.vue (new), CompoundList.vue, LineageEditor.vue.
Write tests first for blank names, unique IDs, reset confirmation, same-workspace enforcement, lineage references, duplicate label conflicts. Clone in one locked transaction with history. UI previews selected source and editable blank labels/names; no Activity/Edge buttons.

## 4. Independent IUPAC conversion
Files: new chemistry resolver/router, CompoundStructureEditor.vue, runtime packaging. Tests first for real OPSIN fixtures, bad name, stereochemistry, authentication, timeout, no automatic save/confirmation. Local pinned OPSIN dependency; no external name lookup.

## 5. Independent problem-report submission
Files: workspace submission/schemas/router, publication decision/supplement paths, SubmissionChecklist.vue, approval pages. Tests first for required explanation, frozen blockers, normal submit unchanged, admin visibility, publication rejection including supplemental revisions, version/ownership/idempotency.

## 6. Independent lineage search/viewed
Files: LineageEditor.vue, LineageGraph.vue as needed, targeted tests. Search IDs/names across Lineages, focus matching node, filter members and add member choices. Explicit current-Lineage viewed only when current loaded data matches server version.

## 7. Integration and verification
Run backend suites serially, full frontend tests/typecheck/build, targeted browser regressions. Review permissions, undo cross-feature integration and publication boundary. Archive completed plan outside tracked tree with hash before final local commit. Preserve feature worktree; no push/merge/deployment unless requested.
