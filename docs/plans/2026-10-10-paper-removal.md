# Recoverable Paper Removal Implementation Plan

**Goal:** remove excluded papers from all user-facing application surfaces while preserving immutable audit/history and unrelated scientific data. User confirmed design and deployment in chat.

**Architecture:** add nullable deletion metadata to Paper; an authorized version-aware Admin endpoint writes a tombstone and audit event, rejects open AI tasks, archives assignments, and prevents every catalog, workspace, document, publication, search and task access path from serving removed paper content. Prefer explicit shared visibility checks with regression tests over query-specific omissions. No new user flow needed for this operational request; API is sufficient.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, pytest.

## Task 1: tests and implementation
1. In backend/tests add failing tests for admin delete, forbidden role/CSRF, stale workspace, open job conflict, removal from catalog/tasks/search/documents/direct IDs, preserved data/audit and unrelated papers.
2. Run on a fresh disposable PostgreSQL cluster whose database ends _test. Never use production or Preview.
3. Add migration after 0033, model fields, deletion service/router and all visibility guards. Do not reset workspaces or mutate immutable audit rows.
4. Run relevant backend suites serially and schema/migration checks.
5. Document operating/recovery behavior and commit feature.

## Task 2: review
Separate spec compliance and code quality reviews. Fix findings, rerun affected checks.

## Task 3: authorized production operation
Back up DB with encrypted recovery verification. Freeze release code, deploy narrowly with incremental migration preserving current database and all scientific records. Avoid interrupting ongoing model work; drain before worker restart. Delete only frozen reviewed exclusions via API. Check source hashes and backup bytes before unlinking local source PDFs. Verify HTTP absence, unaffected catalog and audit; update production and run handoffs. Never import Preview data.
