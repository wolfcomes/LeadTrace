# Shared article filters across Admin pages

User authorized implementation across article catalog, submission approvals, files, and AI task center.

## Design

A shared compact filter bar sends server-side AND conditions: `journal` exact text, `year_from`/`year_to` inclusive publication years, `volume`/`issue` exact text (not numeric), `assignment_status` (`assigned`/`unassigned`), `prefill_status` (`not_started`/`queued`/`running`/`succeeded`/`failed`/`superseded`). Blank means all. Assignment refers to latest nonarchived review task and actual reviewer; prefill refers to current nonarchived workspace, both legacy extraction runs and modern prefill tasks; revise/review must not overwrite prefill status. Consistent choices may be suggested using `GET /api/v2/admin/papers/filter-options` -> `{journals: string[], years: number[], volumes: string[], issues: string[]}` (metadata from visible catalog only).

Four APIs accept same flat query parameters. Catalog counts/pagination filter before limits. Approvals filter by current catalog paper while retaining reviewer-round history/status behavior. Files match any associated visible paper, including original/derived/historical assets, excluding unrelated assets only while article filters active. AI tasks filter by associated paper before limit and return true total; add offset pagination. Existing permissions/removal rules stay intact.

Frontend uses one component and typed parameter helper; labels bilingual, fields labeled/accessibility, responsive two-row grid, apply/reset, invalid year range prevented. Filter state persisted in URL, change/reset page to first; catalog keyword search composes with filters. Existing approval pending/all toggle composes. Files and AI center expose pagination so matches after first page are reachable. Empty/error/loading states preserved; stale responses cannot replace newer filtered results. AI console per-paper view need not show article filter bar.

## Execution and validation

1. Backend: failing tests for shared query semantics, latest/current workspace status, all four routes including beyond limit and removed/shared assets; implement shared dependency/query helpers and route wiring. Serial tests on dedicated new PostgreSQL cluster (never production/Preview).
2. Frontend: implement shared filter UI/helper and API params; wire four pages with URL/pagination; write meaningful component/API tests, typecheck/build.
3. Integration: independent spec/code review, fix findings, run affected backend suites serially and frontend checks. No schema migration needed. Prepare concrete deployable code; no production deploy unless authorized for that step. Do not modify main worktree existing human changes or frozen AI runs.
