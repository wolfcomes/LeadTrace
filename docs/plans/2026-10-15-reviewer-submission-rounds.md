# Reviewer Submission Rounds Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Admin reviews real Reviewer submissions, navigates their frozen versions and sees human changes separately from verified metadata supplements.

**Architecture:** Add an opt-in Reviewer-round projection to the existing Admin APIs; preserve legacy frozen records and audit actors. Validate supplement chains, compare against the preceding real Reviewer submission, and use the verified supplemented metadata as the human-edit baseline where applicable. Technical supplement snapshots cannot be approved. Return existing pending supplements through the audited decision service so Reviewers check only pending additions and retain all prior work.

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL; Vue/TypeScript/Zod/Vitest/Playwright.

## Accepted design

- Navigate genuine Reviewer submissions only, with real submission time, author, note and decision. Latest pending is actionable; all historical views are read-only.
- First round uses a verifiable pre-review baseline. Later rounds reference the preceding real Reviewer round; supplemental metadata is a separate collapsed comparison and is excluded from human-change counts. Human edits to supplemented fields remain visible.
- Preserve immutable snapshots/hashes and actual Admin audit attribution; never infer AI authorship from an Admin role alone. Supplements use explicit verified links and are labelled as prefill/supplement context.
- AI additions after submission require Reviewer checking and resubmission, preserving previous confirmations and scientific work. No fabricated approvals, confirmations or resets.
- Keep current paired cards, folded unchanged fields/screenshots/confirmations, and existing Lineage behavior.

## Task 1: Backend projection and decision boundary

Files: `leadtrace/backend/app/publications/reviewer_rounds.py`, `service.py`, `schemas.py`, `admin_router.py`; tests `tests/publications/test_reviewer_rounds.py`.

1. Add failing tests for technical snapshots excluded from navigation, original submission selected, two real rounds with an intervening supplement, human metadata corrections, immutable history, authorization and technical approval rejection.
2. Run only these tests on disposable `article_metadata_test` port 55459; verify expected failures.
3. Implement validated round summaries, decisions, separate supplement comparisons and pending/all list projection behind `reviewer_rounds=true`.
4. Reject approval of technical or unverifiable submission boundaries. Preserve request-changes transition.
5. Re-run new tests plus existing publications/workspace suites serially.

## Task 2: UI navigation and separated supplements

Files: `leadtrace/frontend/src/v2/{types,api}.ts`, `src/approvals/{ApprovalCenterPage,PaperSubmissionReviewPage}.vue`, translations and `tests/paper-approval-v2.spec.ts`.

1. Add failing UI tests for version navigation, historical read-only state, folded supplements, queue filters and reset of decision form on navigation.
2. Implement strict optional response models; opt in from Admin client. Render version selector and previous/next links, timestamp/author/status, decision reason, separate lazy supplement disclosure, and pending/all views.
3. Guard asynchronous loads/actions against route changes; verify hash targeting.
4. Run frontend tests, typecheck and build; inspect desktop/mobile rendered fixtures.

## Task 3: Existing pending supplements and delivery

Files: operator runbook, scoped return helper/test, current runtime handoff under ignored `leadtrace-data/reviewer-submission-rounds-20261015/`.

1. Add idempotent operator return helper that verifies the current supplement chain/hash/version and calls the existing request-changes service without changing scientific content or confirmations.
2. Document that supplements remain unconfirmed until genuine Reviewer resubmission; never directly approve technical snapshots.
3. Review diff, run relevant checks and archive this completed plan with hash outside tracked tree before integration.
4. Confirm production identity and current user changes; create verified encrypted backup and rehearse transition on isolated restored database. Deploy immutable code and return only still-matching pending supplements under maintenance.
5. Verify API/browser round navigation, preserved data/hashes/receipts, actual reviewer editing state, ready/audit and maintenance OFF. Retain all worktrees; no Preview import or remote push.
