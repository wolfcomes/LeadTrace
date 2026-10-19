# Activity Table Builder Implementation Plan

**Goal:** Let reviewers select, label and order measurement columns, automatically displaying relevant Compounds in a read-only comparison table.
**Architecture:** Reuse the authorized comparison GET and existing guarded editor navigation. Columns bind exact assay/metric/unit plus either all matching observations or explicitly selected Activity IDs. Literal text search previews candidate conditions; it never infers scientific equivalence. Store named table configurations per account/workspace in browser localStorage, without storing measurement values. This first version explicitly labels browser-local persistence; no backend/schema changes.
**Tech Stack:** Vue 3, TypeScript, Zod, Vitest, Playwright.

## Approved behavior

- Initial empty table with obvious Add column action. Search existing measurement groups; show distinct Compound coverage. Recommend groups sharing Compound coverage with chosen columns, without preselecting them.
- Add/edit column with custom display name and exact underlying measurement identity shown. Default all records; optional explicit record selection with literal condition/Compound search, select shown/clear shown, matching counts and preview of values/conditions. Apply freezes selected IDs for subset columns; all-record columns track new matching observations. Renaming never changes matching. Deleted or moved records do not silently migrate to other measurements.
- Repeated observations remain independent clickable values, preserving precision, qualifier, condition and hint. Per-record conditions can be expanded. Multiple columns can reference the same assay with different record subsets.
- Move columns with drag/drop and accessible left/right buttons; remove/edit actions. Default natural Compound identifier order; optional similar measurement profiles and original order.
- Union rows by default (at least one selected column); optional intersection rows (all columns). Empty and stale configurations have explicit feedback; no averaging or fabricated cells.
- Named tables: New, Save, select, Delete; browser-local per account/workspace storage with schema validation and graceful storage errors. Save layout only, never scientific values. Unsaved table settings identified; switching/deleting cannot silently drop changes. Reload saved table against current data. Existing editor pending guards and comparison return scroll/filter behavior retained.

## Steps

1. Run baseline comparison/navigation suites. Add failing helper tests for exact binding, duplicate/precision preservation, union/intersection, id-stable subset mapping, storage validation/isolation and recommendations.
2. Implement typed builder helper; add UI tests for add/rename/reorder/remove, subset previews, saved tables, no scientific writes, stale GETs and return preservation. Implement ActivityColumnEditor and update ActivityComparison, bilingual text and guide.
3. Update navigation fixtures to explicitly add intended columns. Synthetic Playwright tests: choose two conditions for one assay, rename/reorder, union/intersection, save/reload, edit exact Activity and return, mobile. Read-only live smoke exercises local config and restores local view only; block original source requests and scientific writes.
4. Full frontend tests, typecheck/build, guide and diff checks; independent review and fix findings. Merge preserving root dirty work, push, frontend-only deploy under prior authorization. Retain worktrees and rollback assets. Record limitations and validation.
