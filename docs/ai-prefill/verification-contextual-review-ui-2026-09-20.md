# Compound Activity and Lineage Evidence UI — 2026-09-20

## Requested behavior

The reviewer workspace now has four tabs: bibliography, compounds/structures,
Lineage, and submission. The former combined Evidence/Activity tab is removed.

Each selected compound includes its own Activity editor and source Evidence excerpts.
Activity requests are limited to that compound. New records use its compound ID.
Switching compounds resets pagination/forms and ignores late responses from the old
selection. No records produces an honest “当前化合物尚无活性记录” message; failed
requests display an error, not an absence claim. “Not reported” remains a separately
reviewed scientific section decision.

Each Edge displays its actual Evidence links, roles, quotations, captions, notes,
and PDF page links inside Lineage. Stored bounding boxes can be opened as a PDF
page with a highlighted source region. The viewer is read-only. Edges without
Evidence remain allowed and show an explicit empty state. Contextual Evidence
editing preselects the current Edge; the full library remains available for
existing/unlinked/shared Evidence. Activity source Evidence is managed from the
compound details and selected in its Activity form. Shared Evidence is not copied.

The compound directory scrolls independently, with no intrinsic contribution to
the desktop grid height. Its height is bounded by the detail panel and viewport.
The mobile directory is capped at 260 px. Sticky navigation has an opaque surface
and the directory is offset below the application header and preview banner.

Legacy `tab=evidence&entity=...` links route Activity records to their compound
and Edge/Evidence records to Lineage as appropriate. Submission blockers retain
record navigation. Structure record deep links remain supported.

## Validation

- All 21 frontend Vitest files pass: 104 tests.
- New contextual tests cover scoped fetching, correct Evidence, late response
  isolation, error vs empty state, legacy navigation, optional Edge Evidence,
  current-Edge linking, image-region props, read-only Activity and version conflicts.
- Existing CRUD, shared Evidence multi-link/partial failure, concurrency,
  structure and submission tests remain covered. Editor unit tests were decoupled
  from the deleted tab; tab placement has separate integration coverage.
- `npm run build` includes `vue-tsc --noEmit`; succeeds. Existing dependency
  directive/chunk-size warnings remain non-fatal.
- Live browser acceptance: papers 004 (44 compounds), 007 (54), 005 (41).
  004 compound51 has 21 Activity records; compound10g has none. Activity source
  PDF region rendered successfully. Edge quotations appear within their own rows.
  Sidebar has independent overflow; grid height equals detail-panel height.
  At 390 px viewport, document width remains 390 px and list height is 258 px.
- Seven workspaces retain their existing versions (004:391, remaining six:2).
  Browser acceptance observed no scientific writes or page errors.

## Operational artifacts

Worktree: `/data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools`

Live browser script, JSON report and screenshots:
`/data/home/zhangzhiyong/lead_optimization_collection/leadtrace-data/contextual-ui-20260920/`

Preview: http://10.21.53.251:18080/review/tasks

Frontend dist was rebuilt in the existing worktree and is served by the existing
preview. No backend or scientific schema/data migration is required. These checks
validate UI behavior and relationship display; they do not constitute scientific
approval of the AI-prefilled structures, activities, or inferred edges.
