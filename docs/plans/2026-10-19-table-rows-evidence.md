# Table Compound Rows and Source Evidence Implementation Plan

**Goal:** Let Reviewers save table Compound membership/order and inspect/edit original-table screenshot evidence, retaining AI reconfirmation and Reviewer-only approval differences.
**Architecture:** Extend workspace ActivityTable with optional ordered compound_ids and evidence_ids referencing current workspace records. Columns remain authoritative exact Activity membership; row removal removes those links, so Other remains the complement. Source Evidence stores PDF SHA/page/bbox and renders a verified crop; reuse existing Evidence instead of duplicating images. Frozen snapshots and AI contracts keep backward-compatible optional fields.
**Tech Stack:** PostgreSQL/Alembic, FastAPI/SQLAlchemy/Pydantic, Vue3/TypeScript/PDF.js, existing frozen Codex AI adapter.

## Approved behavior and contract

- User approved adding/removing/reordering existing Compound rows, with removal unlinking its Activities from this table only; unassigned Activities return to Other, scientific rows remain untouched. Show exact candidate observations when adding, never auto-merge repeated conditions.
- API TableDefinition extends compound_ids: UUID[]|null (null legacy derived rows; explicit array ordered chosen rows), evidence_ids: UUID[] (ordered, default[]). No duplicates or cross-workspace refs. Every assigned Activity must belong to chosen compounds when explicit. Manual row-order display is selected through existing sort='default'; other sort modes still available.
- Table evidence is explicit, accepts existing table-kind Evidence with valid same-source page/bbox, supports multiple pages, original page link, crop zoom and Reviewer region creation/replacement. UI candidates can derive from existing Activity Evidence, but linking is explicit/audited. Drafts may lack screenshot; source-table confirmation requires valid screenshot, or explicit unresolved disposition with visible missing-evidence issue. Other/custom do not require a whole-table screenshot.
- Changes to table rows/evidence or referenced Evidence scientific content invalidate relevant table confirmation/view signatures and history. Deletion of referenced Evidence must reject or atomically unlink with audited table changes; prefer existing referenced-record protection. AI dependency invalidation uses AI repair events.
- Preserve optional fields in old snapshots/candidates without changing hashes. New snapshots/publication and undo capture fields. Approval handles per-table evidence/rows and keeps AI out of human diffs; field/list collisions must warn rather than hide human work.
- AI table payload extends compound_refs: string[]|null and evidence_refs:string[]; exporter preserves explicit scope/order and exact IDs. Guides require source screenshot includes table number/header/units/footnotes and all relevant rows; multi-page portions separate Evidence. Missing crop remains draft/unresolved, never fabricate.
- Reuse the two previous examples and existing source-identical table Evidence; no scientific values/structures changed. Any actual linking must use audited version-guarded service, preserve any new human work, and remain pending confirmation. Supervisor may inspect output/metadata but not original PDF content/crops/reasoning. No model retry needed merely to reuse explicit existing output associations; no false AI attribution for deterministic operations.

## Task 1: Backend contract, storage, invariants

Files: app/activity_tables/{models,schemas,service}.py; migration0039_table_rows_evidence.py; app/evidence/{service,router}.py; workspaces/{snapshot,review_progress,validation,edit_history}.py; publications/{schemas,comparison}.py; tests/workspaces/test_activity_tables.py and evidence/DB tests.
Write failing tests for persistence/order, Other after row removal, cross-scope and duplicate rejection, source crop requirement, evidence edits invalidating confirmation, deletion reference guard, undo/frozen legacy compatibility. Run red on isolated PostgreSQL then implement and run green serially. Publish final wire shape before frontend implementation. No production DB tests.

## Task 2: Frontend rows, source evidence, frozen view

Files: ActivityComparison.vue plus focused TableRowsEditor/TableEvidence components; v2/{api,types}.ts; approvals/FrozenActivityTable.vue and recordComparison.ts; i18n; canonical reviewer guide/generated docs; relevant unit/e2e tests.
Write meaningful failing interaction tests. Implement Compound search/selection and explicit observation selection on addition, reorder/remove with real unlink preview, shared save/version lock/pending-edit guards. Reuse verified PDF crop renderer with view-scoped resource pool, lazy crop loading and read-only admin/frozen behavior. Support choose existing Evidence, new/reframed region safely with version updates. UI/crop tests synthetic only; source requests blocked in supervisor live browser checks.

## Task 3: AI and provenance

Files: ai_prefill/{contracts,service,workspace_export,assistance_validation}.py; ai_tasks/repair_apply.py; publications/reviewer_projection.py if required; current AI guide bundle/schema and corresponding tests.
Write regression first: optional old hash compatibility, compound/evidence refs and source validity, export-roundtrip, scoped repair unchanged science, AI invalidation, reviewer-only differences. Extend bindings/import/export/repair; do not turn derived defaults into fake science changes. Preserve existing stable Activity refs and unchanged human notes. Run pure then serial DB suites on dedicated test cluster.

## Task 4: Review, integrate, deploy, examples

Run targeted/full frontend checks, meaningful backend/DB/migration tests serially, guide generation check, independent spec then code review. Back up root dirty files and three-way preserve unrelated work. Merge/push authorized source changes. Deploy additive migration after fresh encrypted backup/restored migration check; retain auth/Ketcher/CSP and production scientific records. Do not repeat full snapshot in per-table loop. Verify two existing articles through real APIs and readonly browser, with all tables pending and no Reviewer edit attribution for system preparation. Archive completed plan with hash outside tracked tree; update production/run HANDOFF and final results. No Preview import.
