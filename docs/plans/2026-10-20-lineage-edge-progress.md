# Lineage and Edge viewing progress

User-approved design: keep the four review categories and one shared Lineage
status control, but show separate Lineage and Edge viewed/total counts. Automatic
completion requires all existing items in both sets to be viewed. An empty Edge
set does not block a nonempty, fully viewed Lineage set.

Preserve existing Compound/Lineage signatures and receipts. Add independent Edge
receipts scoped to the current source, edge, evidence links, evidence contents and
endpoint compound contents. Historical Lineage viewing does not imply individual
Edge viewing. Keep existing graph dependency invalidation semantics. No migration,
scientific data edits, or production deployment is part of this change.

Implementation plan (test-driven, executed in this session):
1. Extend `test_review_progress_groups.py` for Edge identity/dependencies and
   aggregate completion, including empty sets and existing Lineage receipts.
2. Extend `review_progress.py` and `workbench.py` to expose/accept Edge receipts;
   aggregate Lineage and Edge items for the shared completion state.
3. Extend frontend workbench schema, status display and Edge detail interaction.
   Preserve explicit current-version viewing and block recording if evidence
   failed to load or content is stale. Add frontend regression tests.
4. Run focused backend tests using a disposable PostgreSQL cluster, frontend
   tests, typecheck/build and diff checks. Preserve unrelated worktree edits.

Verification:
- Backend focused progress, graph confirmation, workbench, structure confirmation
  and undo/redo suites: 35 passed on a disposable PostgreSQL 16 UTF-8 cluster
  (`leadtrace_edge_progress_test`); the cluster was stopped after testing.
- Frontend full suite: 446 passed. After adding the graph-tab cancellation guard,
  the four affected suites passed all 16 tests (including six Edge progress cases).
- Generated Chinese/English Reviewer guides match their JSON source.
- No production deployment or database migration was performed.
- Final `npm run build` (including `vue-tsc --noEmit`) passed; existing dependency
  directive and chunk-size warnings remain. `git diff --check` passed.
